#!/usr/bin/env python3
"""Прогон заданий через SSH-терминал нод — обход шлюза Salad. Запускается ЛОКАЛЬНО.

ЗАЧЕМ. Шлюз группы отдаёт 503 при готовых инстансах (ready:true, воркер прогрет и отвечает
изнутри) — 29.08 это воспроизводилось и с их readiness-пробой, и без неё. Воркер при этом
полностью рабочий: канарейка через SSH прошла весь путь (генерация 154с, комплект доехал до
приёмника). Не воюем с их балансировщиком — задания возим через их же SSH-обёртку.

Особенность обёртки: это интерактивный терминал в контейнер (`Connecting to container ...`),
обычный exec и проброс портов не поддерживает. Поэтому команды подаются на stdin, задание
кладётся heredoc-ом во временный файл, а результат воркера ловится по маркерам в выводе.

  ~/venvs/scout/bin/python ssh_run.py --limit 10        # десятка на всех тёплых нодах
  ~/venvs/scout/bin/python ssh_run.py --report          # сводка из mesh-pilot-results.json
"""
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
# Файл очереди переопределяется переменной: старый пилотный снимок НЕ переписываем и не
# удаляем (его курсор --skip осмыслен только для него), а новую очередь в порядке
# регламента подаём отдельным файлом. Так переключение обратимо.
SAMPLE = os.environ.get('MESH_SAMPLE') or os.path.join(HERE, '..', 'mesh-pilot-sample.json')
RESULTS = os.path.join(HERE, '..', 'mesh-pilot-results.json')
SSH_KEY = os.path.expanduser('~/.ssh/salad_mesh_ed25519')
SSH_HOST = 'root@195.181.163.241'
API = 'https://api.salad.com/api/public'
ORG, PROJECT = 'prodstore', 'dmodel'
# Несколько групп через запятую (владелец 30.08: параллельная группа на baked-образе).
# Порты собираются со ВСЕХ, стоп гасит ВСЕ — иначе вторая группа жгла бы деньги после финала.
GROUPS = [g.strip() for g in os.environ.get('SALAD_GROUP', 'mesh-run3').split(',') if g.strip()]
GROUP = GROUPS[0]
RATE = 0.16                     # 4090 batch $/ч — сверено по API 28.08
# Предохранитель от разросшейся очереди. Владелец 31.08 ставил 2000 (481 сетовых + демо +
# добор), но 01.09 очередь стала полной по каталогу — 11 704 задания в порядке регламента
# (`rules/mesh-priority.json`). Держим переопределяемым: молчаливое усечение хуже явного
# отказа, а зашитая цифра однажды уже уронила конвейер при живых нодах.
MAX_JOBS = int(os.environ.get('MESH_MAX_JOBS', '2000'))
_lock = threading.Lock()
import random

# Динамический пул (план mesh-dynamic-node-pool): ноды приходят и уходят посреди прогона.
POLL_S = float(os.environ.get('MESH_POLL_S', '45'))        # как часто ищем НОВЫЕ ноды
CULL_S = float(os.environ.get('MESH_CULL_S', '150'))       # как часто пересаживаем зависшие
STALL_S = float(os.environ.get('MESH_STALL_S', '1800'))    # без живых нод и движения — выходим
RETRY_GRACE_S = float(os.environ.get('MESH_RETRY_GRACE_S', '300'))
MAX_ATTEMPTS = int(os.environ.get('MESH_MAX_ATTEMPTS', '3'))
NODE_COOLDOWN_S = float(os.environ.get('MESH_NODE_COOLDOWN_S', '60'))
# Пересаженная нода качает образ 25–35 мин — дольше, чем STALL_S. После СВОЕЙ пересадки
# даём прогону отсрочку, иначе он сам себе устраивает «нет живых нод» (Codex 01.09).
WARMUP_GRACE_S = float(os.environ.get('MESH_WARMUP_GRACE_S', '2100'))   # 35 мин
PROGRESS = os.path.join(HERE, '..', 'mesh-run-progress.jsonl')
# Спул повторов: задания, исчерпавшие попытки НЕ по своей вине. Раньше они закрывались
# молча и курсор уходил вперёд (01.09: 4 товара за одну пачку). Не «источник правды», а
# очередь — конвейер скармливает её следующим прогоном через --jobs-file.
RETRY_SPOOL = os.path.join(HERE, '..', 'mesh-retry-queue.jsonl')
MAX_SPOOL_RETRIES = int(os.environ.get('MESH_MAX_SPOOL_RETRIES', '3'))
EXIT_NO_CAPACITY = 75           # «нод нет» — не авария, конвейер ждёт и повторяет
sys.path.insert(0, HERE)
import node_health as NH  # noqa: E402

# Параллельные сессии к РАЗНЫМ нодам допустимы, если не открывать их залпом: сбой 29.08
# («нет маркера», пустой вывод) случался при одновременном старте. Разносим НАЧАЛА всех
# ssh-сессий (и проб, и заданий) единым лимитером; держать замок на время генерации нельзя —
# иначе ноды работают по очереди, а не параллельно.
SSH_STAGGER_S = float(os.environ.get('MESH_SSH_STAGGER_S', '5'))
_start_lock = threading.Lock()
_last_start = 0.0


def ssh_slot() -> None:
    """Пропуск на СТАРТ ssh-сессии: не чаще, чем раз в SSH_STAGGER_S, плюс джиттер."""
    global _last_start
    while True:
        with _start_lock:
            wait = _last_start + SSH_STAGGER_S - time.time()
            if wait <= 0:
                _last_start = time.time()
                break
        time.sleep(min(wait, 2.0))
    time.sleep(random.uniform(0.2, 1.5))


def key() -> str:
    k = os.environ.get('SALAD_API_KEY')
    if not k:
        sys.exit('нет SALAD_API_KEY')
    return k


def api(path: str) -> dict:
    req = urllib.request.Request(f'{API}/organizations/{ORG}/projects/{PROJECT}/{path}',
                                 headers={'Salad-Api-Key': key(), 'User-Agent': 'remlab-mesh/1.0'})
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.loads(r.read() or b'{}')


def instances() -> list[dict]:
    """Стартовавшие инстансы всех групп. Идентичность — `id` платформы, а НЕ ssh-порт:
    порт после пересадки ноды переиспользуется, и по нему задание уедет не туда."""
    out = []
    for g in GROUPS:
        try:
            insts = api(f'containers/{g}/instances').get('instances') or []
        except Exception:  # noqa: BLE001 — одна группа недоступна: работаем с остальными
            continue
        for i in insts:
            if not i.get('started'):
                st = i.get('state')
                if st in ('running', 'starting'):  # жива, а started=False — видно в логе
                    print(f"  инстанс {str(i.get('machine_id'))[:8]}: state={st}, started=False — пропущен")
                continue
            if i.get('id') and i.get('ssh_port'):
                out.append({'id': i['id'], 'port': int(i['ssh_port']), 'group': g,
                            'state': i.get('state')})
    return out


def probe_warm(port: int) -> bool:
    """Прогрет ли воркер ноды. Спрашиваем ноду ЛИЧНО через её терминал — флагам платформы
    после тех двух дней веры нет. Проба дорогая (до 50 с), поэтому зовём её только для
    НОВЫХ и остывших нод, а не по кругу для всех."""
    try:
        r = ssh_text(port, 'python -c "import urllib.request;'
                           'print(urllib.request.urlopen(\'http://127.0.0.1:8000/health\','
                           'timeout=5).read().decode())"', timeout=50)
    except Exception as e:  # noqa: BLE001 — ЗАВИСШИЙ SSH НЕ ВАЛИТ ПРОГОН (31.08: нода
        # перестала отвечать, TimeoutExpired вылетел из пробы и убил всю пачку —
        # «пачка без итога (код 1) — стоп, разбор руками», группа погашена в разгар волны)
        print(f'  порт {port}: проба не удалась ({type(e).__name__}) — считаю ноду холодной',
              flush=True)
        return False
    m = re.search(r'\{.*\}', r or '')
    if m:
        try:
            h = json.loads(m.group(0))
        except json.JSONDecodeError:
            h = {}
        if h.get('warm'):
            # `warm` воркер ставит в `finally` — то есть и после упавшего прогрева
            # (`worker.py`). Такая нода отвечает «готова», берёт задания и валит их.
            # Правку самого воркера видно только после пересборки образа, поэтому гейт
            # ставим здесь: у нас эта информация уже есть, она едет в /health.
            if h.get('warmup_error'):
                print(f'  порт {port}: прогрев упал (warmup_error) — ноду не беру', flush=True)
                return False
            return True
    print(f'  порт {port}: воркер не прогрет или не отвечает', flush=True)
    return False


def warm_ports() -> list[int]:
    """SSH-порты прогретых нод — стартовый снимок; дальше состав пула ведёт супервизор."""
    return [i['port'] for i in instances() if probe_warm(i['port'])]


def ssh_text(port: int, cmd: str, timeout: int = 60) -> str:
    """Одна команда через интерактивную обёртку. stdin — команды, вывод — как есть."""
    ssh_slot()
    r = subprocess.run(
        ['ssh', '-i', SSH_KEY, '-tt', '-o', 'StrictHostKeyChecking=no',
         '-o', 'BatchMode=yes', '-o', 'ServerAliveInterval=30', '-p', str(port), SSH_HOST],
        input=f'{cmd}; exit\n', capture_output=True, text=True, timeout=timeout)
    return r.stdout


def run_job(port: int, job: dict) -> dict:
    """Одно задание на одной ноде. Результат воркера вылавливаем между маркерами."""
    payload = json.dumps(job, ensure_ascii=False)
    script = (
        "cat > /tmp/job.json <<'RLEOF'\n" + payload + "\nRLEOF\n"
        "python - <<'RLPY'\n"
        "import urllib.request\n"
        "body=open('/tmp/job.json','rb').read()\n"
        "req=urllib.request.Request('http://127.0.0.1:8000/generate',data=body,"
        "headers={'Content-Type':'application/json'})\n"
        "print('RLBEG'+urllib.request.urlopen(req,timeout=1100).read().decode()+'RLEND')\n"
        "RLPY\n"
        "exit\n")
    t0 = time.time()
    try:
        for attempt in (1, 2):
            ssh_slot()
            r = subprocess.run(
                ['ssh', '-i', SSH_KEY, '-tt', '-o', 'StrictHostKeyChecking=no',
                 '-o', 'BatchMode=yes', '-o', 'ServerAliveInterval=30',
                 '-p', str(port), SSH_HOST],
                input=script, capture_output=True, text=True, timeout=1150)
            m = re.search(r'RLBEG(\{.*?\})RLEND', r.stdout, re.S)
            if m:
                break
            if attempt == 1 and len((r.stdout or '').strip()) < 40:
                time.sleep(8)          # пустой вывод = коллизия сессий, второй заход
                continue
        if not m:
            return {'sku': job['sku'], 'status': 'transport_failed', 'node_port': port,
                    'error': ('нет маркера в выводе: ' + r.stdout[-180:]).strip()}
        res = json.loads(m.group(1))
        res['wall_s'] = round(time.time() - t0, 1)
        res['node_port'] = port
        return res
    except subprocess.TimeoutExpired:
        return {'sku': job['sku'], 'status': 'transport_failed', 'error': 'ssh timeout'}
    except Exception as e:  # noqa: BLE001 — транспорт не должен ронять весь прогон
        return {'sku': job['sku'], 'status': 'transport_failed',
                'error': f'{type(e).__name__}: {str(e)[:160]}'}


def stop_group() -> None:
    """Гасим ВСЕ группы сразу после прогона: тарифицируется состояние, а не работа (ADR-0135)."""
    for g in GROUPS:
        try:
            req = urllib.request.Request(
                f'{API}/organizations/{ORG}/projects/{PROJECT}/containers/{g}/stop',
                data=b'', method='POST', headers={'Salad-Api-Key': key(), 'User-Agent': 'remlab-mesh/1.0'})
            with urllib.request.urlopen(req, timeout=60) as r:
                r.read()
            print(f'группа {g} остановлена — счёт больше не идёт')
        except Exception as e:  # noqa: BLE001 — это деньги, говорим громко
            print(f'!! ГРУППУ {g} НЕ ОСТАНОВИТЬ ({type(e).__name__}: {str(e)[:120]}) — '
                  f'останови вручную в портале', flush=True)


# Канон стратегий — ЕДИНСТВЕННЫЙ источник (rules/asset-strategies.json, Codex q27).
sys.path.insert(0, os.path.join(HERE, '..'))
import asset_strategy as AS  # noqa: E402


def _mesh_eligible(jobs: list[dict]) -> list[dict]:
    out = [j for j in jobs if AS.strategy(j.get('role')) == 'hunyuan3d']
    if len(out) != len(jobs):
        print(f'не-мешевых по канону: {len(jobs) - len(out)}', flush=True)
    return out


def jobs_from_file(path: str) -> list[dict]:
    """Очередь заданий из файла: перегон (`mesh-reseed.json`, массив) или спул повторов
    (`mesh-retry-queue.jsonl`, по записи на строку). Формат определяем по содержимому —
    вызывающему не нужно знать, какая это очередь."""
    raw = open(path, encoding='utf-8').read().strip()
    if not raw:
        return []
    if raw[0] == '[':
        js = json.loads(raw)
    else:
        js = [json.loads(line) for line in raw.splitlines() if line.strip()]
    # Записи спула — обёртка вокруг задания; исчерпавшие попытки не гоняем (мёртвое фото
    # жгло бы GPU бесконечно), они остаются в файле как след для разбора.
    jobs, seen = [], set()
    for rec in js:
        job = rec.get('job') if isinstance(rec, dict) and 'job' in rec else rec
        if not isinstance(job, dict) or not job.get('sku'):
            continue
        if int(job.get('_retries', 0)) >= MAX_SPOOL_RETRIES:
            continue
        k = (job.get('sku'), job.get('seed'))
        if k in seen:
            continue
        seen.add(k)
        jobs.append(job)
    if len(jobs) > MAX_JOBS:
        sys.exit(f'ПРЕДОХРАНИТЕЛЬ: {len(jobs)} > {MAX_JOBS}')
    return _mesh_eligible(jobs)


def plan_jobs() -> list[dict]:
    """КАНОНИЧЕСКИЙ плоский список заданий прогона — единственный источник для `total`,
    `--skip` и `--limit`.

    Раньше супервизор считал план по числу SKU в файле (1465), а прогон разворачивал seeds и
    отсеивал не-мешевые роли (1515 → 1503): конвейер останавливался на 1465, и последние
    38 заданий не запрашивались никогда (найдено Codex 01.09, проверено скриптом).
    """
    return jobs_from_sample(None)


def jobs_from_sample(limit: int | None) -> list[dict]:
    s = json.load(open(SAMPLE, encoding='utf-8'))
    out = []
    for j in s['jobs']:
        for seed in j['seeds']:
            out.append({'sku': j['sku'], 'role': j['role'], 'image_url': j['image_url'],
                        'dims_cm': j['dims_cm'], 'seed': seed, 'params': {}})
    if len(out) > MAX_JOBS:
        sys.exit(f'ПРЕДОХРАНИТЕЛЬ: {len(out)} > {MAX_JOBS}')
    out = _mesh_eligible(out)
    return out[:limit] if limit else out


def checkpoint(rec: dict) -> None:
    """Строка на КАЖДОЕ завершённое задание. Раньше знание о сделанном появлялось только в
    конце прогона — падение процесса стирало его целиком."""
    try:
        with open(PROGRESS, 'a', encoding='utf-8') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
    except Exception as e:  # noqa: BLE001 — журнал не должен ронять прогон
        print(f'  чекпойнт: {type(e).__name__}', flush=True)


def spool_unresolved(rows: list[dict]) -> int:
    """Задания, закрытые НЕ по своей вине, — в спул повторов, а не в тишину.

    Сюда попадает то, что курсор уже пропустил: задание побывало на двух разных нодах и всё
    равно не получилось (`Jobs.blocking`). Раньше такой товар исчезал бесследно — приёмка его
    не видит, потому что `input_failed` случается ДО создания манифеста (`worker.py`).
    Счётчик `_retries` едет внутри задания: спул может быть скормлен обратно через
    `--jobs-file`, и без счётчика мёртвое фото жгло бы GPU вечно.
    """
    out = []
    for r in rows:
        if NH.classify(r) not in (NH.FAULT_NODE, NH.FAULT_UNKNOWN):
            continue
        if Jobs.blocking(r, int(r.get('tried_n') or 0)):
            continue    # курсор его не пропустил — вернётся сам следующей пачкой, дубль не нужен
        job = dict(r.get('job') or {})
        if not job:
            continue
        tries = int(job.get('_retries', 0)) + 1
        job['_retries'] = tries
        out.append({'job': job, 'sku': r.get('sku'), 'seed': r.get('seed'),
                    'status': r.get('status'), 'fault': NH.classify(r),
                    'error': str(r.get('error') or '')[:200],
                    'retries': tries, 'exhausted': tries >= MAX_SPOOL_RETRIES,
                    'at': round(time.time())})
    if not out:
        return 0
    try:
        with open(RETRY_SPOOL, 'a', encoding='utf-8') as f:
            for rec in out:
                f.write(json.dumps(rec, ensure_ascii=False) + '\n')
    except Exception as e:  # noqa: BLE001 — спул не должен ронять прогон
        print(f'  спул повторов: {type(e).__name__}', flush=True)
        return 0
    dead = sum(1 for r in out if r['exhausted'])
    print(f'  в спул повторов: {len(out)}'
          + (f' (из них исчерпали попытки: {dead})' if dead else ''), flush=True)
    return len(out)


def cull_slow() -> None:
    """Пересадка зависших загрузок образа ВО ВРЕМЯ прогона: раньше это делалось только в
    паузах ожидания batch_show, то есть при длинной волне — никогда."""
    try:
        if HERE not in sys.path:
            sys.path.insert(0, HERE)
        import batch_show  # noqa: PLC0415 — ленивый импорт, чтобы не тянуть его в тестах
        batch_show.cull_slow_pulls()
    except Exception as e:  # noqa: BLE001
        print(f'  пересадка медленных: {type(e).__name__}: {str(e)[:70]}', flush=True)


class Jobs:
    """Очередь с жизненным циклом задания.

    Транспортный сбой — это НЕ ответ генератора: задание возвращается в очередь (после паузы
    и по возможности на другую ноду), а не хоронится в результатах. Содержательные статусы
    (`ok`, `cached`, `bad_cutout`, `flat_shape`, …) терминальны — их лечит слой приёмки.
    """

    def __init__(self, jobs: list[dict]):
        self.items = [{'job': j, 'attempts': 0, 'not_before': 0.0, 'busy': False,
                       'tried': set(), 'result': None} for j in jobs]
        self.cv = threading.Condition()
        self.inflight = 0
        self.stalled = False      # остаток закрыт не потому, что задания плохи, а потому что нод нет
        self.grace_until = 0.0    # ждём прогрева пересаженной ноды (см. `extend_grace`)

    def extend_grace(self, seconds: float) -> None:
        """Отложить приговор «нет живых нод»: мы только что кого-то пересадили.

        Замена качает образ 25–35 минут, а `STALL_S` — 30: без этой отсрочки собственная
        пересадка приводила бы к закрытию остатка ровно перед тем, как новая нода оживёт."""
        with self.cv:
            self.grace_until = max(self.grace_until, time.time() + seconds)
            self.cv.notify_all()

    def _all_done(self) -> bool:
        return all(it['result'] is not None for it in self.items)

    def take(self, node_id: str):
        """Задание для ноды. Ждём на условии, а не выходим по первой пустой очереди: иначе
        воркер умрёт за миг до возврата задания из паузы, и работать станет некому."""
        with self.cv:
            while True:
                if self._all_done():
                    return None
                now = time.time()
                free = [it for it in self.items
                        if it['result'] is None and not it['busy'] and it['not_before'] <= now]
                pick = ([it for it in free if node_id not in it['tried']] or free)
                if pick:
                    it = pick[0]
                    it['busy'] = True
                    it['attempts'] += 1
                    it['tried'].add(node_id)
                    self.inflight += 1
                    return it
                waits = [it['not_before'] - now for it in self.items
                         if it['result'] is None and not it['busy'] and it['not_before'] > now]
                self.cv.wait(timeout=max(0.5, min(waits + [5.0])))

    def done(self, it: dict, res: dict, transport_ok: bool) -> None:
        with self.cv:
            it['busy'] = False
            self.inflight -= 1
            if transport_ok or it['attempts'] >= MAX_ATTEMPTS:
                it['result'] = res
            else:
                it['not_before'] = time.time() + RETRY_GRACE_S
            self.cv.notify_all()

    def pending(self) -> int:
        with self.cv:
            return sum(1 for it in self.items if it['result'] is None)

    def wait_all(self) -> None:
        """Ждём терминальности ВСЕХ заданий. Предохранитель: если нод не осталось и ничего
        не двигается STALL_S, закрываем остаток честной ошибкой, а не висим вечно."""
        with self.cv:
            last_change, closed = time.time(), sum(1 for it in self.items if it['result'])
            while not self._all_done():
                self.cv.wait(timeout=30)
                now_closed = sum(1 for it in self.items if it['result'])
                if now_closed != closed:
                    closed, last_change = now_closed, time.time()
                elif (self.inflight == 0 and time.time() - last_change > STALL_S
                      and time.time() >= self.grace_until):
                    for it in self.items:
                        if it['result'] is None:
                            it['result'] = {'sku': it['job']['sku'], 'status': 'transport_failed',
                                            'error': f'нет живых нод {int(STALL_S)}с'}
                    self.stalled = True
                    print(f'!! нет живых нод {int(STALL_S / 60)} мин — закрываю остаток', flush=True)
                    break

    def results(self) -> list[dict]:
        return [{**(it['result'] or {}), 'role': it['job'].get('role'),
                 'seed': it['job'].get('seed'), 'attempts': it['attempts'],
                 'tried_n': len(it['tried']), 'job': it['job']} for it in self.items]

    @staticmethod
    def blocking(res: dict | None, tried_n: int) -> bool:
        """Держит ли этот результат курсор `--skip` на месте.

        Держит всё, в чём задание не виновато: транспорт, сеть ноды, непонятные отказы.
        НО только пока задание не побывало на двух разных нодах: если оно упало и там, и там,
        дело не в конкретной ноде, и вечно топтаться на нём нельзя — оно уходит в спул
        повторов, а конвейер идёт дальше (иначе одно мёртвое фото останавливает всю очередь).
        """
        if res is None:
            return True
        return NH.classify(res) in (NH.FAULT_NODE, NH.FAULT_UNKNOWN) and tried_n < 2

    def summary(self) -> dict:
        """`terminal_prefix` — сколько заданий закрыто подряд с начала списка: только на
        столько конвейер вправе сдвинуть курсор `--skip`, иначе дырки теряются молча."""
        bad = [it for it in self.items if self.blocking(it['result'], len(it['tried']))]
        prefix = 0
        for it in self.items:
            if it['result'] is not None and not self.blocking(it['result'], len(it['tried'])):
                prefix += 1
            else:
                break
        return {'requested': len(self.items), 'terminal': len(self.items) - len(bad),
                'terminal_prefix': prefix, 'unresolved': len(bad)}


def run(limit: int | None, keep_alive: bool, jobs_file: str | None = None,
        skip: int = 0) -> int:
    """Прогон с ДИНАМИЧЕСКИМ пулом: ноды подключаются и выбывают по ходу дела."""
    ports = warm_ports()
    print(f'тёплых нод: {len(ports)} {ports}')
    if not ports:
        print('нет прогретых нод', flush=True)
        return EXIT_NO_CAPACITY
    jobs = jobs_from_file(jobs_file) if jobs_file else jobs_from_sample(None)[skip:(skip + limit) if limit else None]
    # --skip вместо растущего --limit: кэш «уже сделано» живёт на приёмнике и умирает при
    # drain — растущий префикс перегенерировал ВСЁ предыдущее каждой пачкой (поймано 30.08:
    # конвейер стал квадратичным, страница стояла).
    print(f'заданий: {len(jobs)} на {len(ports)} нод(ы) на старте')

    js, t0 = Jobs(jobs), time.time()
    stop = threading.Event()
    nodes: dict = {}          # instance_id → {'thread', 'port', 'until'}: реестр пула
    gpu_of: dict = {}         # instance_id → модель видеокарты (для сравнения скорости)

    def ask_gpu(node_id: str, port: int):
        try:
            m = re.search(r'(?:NVIDIA|AMD)[^\r\n]*',
                          ssh_text(port, 'nvidia-smi --query-gpu=name --format=csv,noheader',
                                   timeout=40) or '')
            gpu_of[node_id] = m.group(0).strip()[:40] if m else '?'
        except Exception:  # noqa: BLE001 — диагностика не должна мешать работе
            gpu_of[node_id] = '?'
    nodes_lock = threading.Lock()
    closed = [0]

    def worker(node_id: str, port: int, group: str):
        node_key = f'{group}/{node_id}'
        while not stop.is_set():
            it = js.take(node_id)
            if it is None:
                return
            r = run_job(port, it['job'])
            # Терминально только то, в чём задание виновато САМО (или отработало). Вина ноды
            # и «непонятно» возвращают задание в очередь: раньше `input_failed` закрывался
            # как ответ генератора, курсор уходил вперёд, и товар терялся молча (01.09).
            fault = NH.classify(r)
            ecls = NH.error_class(r)
            terminal = fault in (NH.FAULT_NONE, NH.FAULT_JOB)
            rec = {**r, 'node': node_id[:8], 'attempt': it['attempts'], 'fault': fault,
                   'at': round(time.time())}
            js.done(it, rec, terminal)
            checkpoint({'sku': it['job'].get('sku'), 'role': it['job'].get('role'),
                        'status': r.get('status'), 'attempt': it['attempts'],
                        'node': node_id[:8], 'prefix': r.get('prefix'),
                        # секунды генерации и модель карты — чтобы сравнивать 4090 с 3090/A5000
                        'sec': (r.get('timings_s') or {}).get('total'),
                        'gpu': gpu_of.get(node_id),
                        # Без seed и полного id инстанса потерянное задание не восстановить —
                        # 01.09 именно поэтому нельзя было сказать точно, что пропало.
                        'seed': it['job'].get('seed'), 'instance': node_id, 'group': group,
                        'fault': fault, 'err_class': ecls,
                        'error': str(r.get('error') or '')[:120], 'at': round(time.time())})
            with _lock:
                closed[0] += 1
                t = (r.get('timings_s') or {}).get('total')
                print(f'  [{closed[0]}/{len(jobs)}] {str(it["job"].get("role")):14s} '
                      f'{r.get("status","?"):16s} {"" if t is None else str(t) + "с"} '
                      f'{node_id[:8]} {str(r.get("error") or "")[:60]}', flush=True)
            streak = NH.record(node_key, fault, ecls)
            if terminal:
                continue
            # Мёртвая нода за минуту провалит весь хвост очереди — уводим её из пула,
            # задание вернётся другой. Супервизор перепроверит ноду после паузы.
            with nodes_lock:
                if node_id in nodes:
                    nodes[node_id]['until'] = time.time() + NODE_COOLDOWN_S
                alive = sum(1 for st in nodes.values()
                            if st['thread'].is_alive() and st is not nodes.get(node_id))
            if fault != NH.FAULT_NODE or streak < NH.FAIL_STREAK:
                print(f'  нода {node_id[:8]}: сбой ({ecls}) — вывожу из пула на '
                      f'{NODE_COOLDOWN_S:.0f}с, серия {streak}/{NH.FAIL_STREAK}', flush=True)
                return
            # Порог владельца: 3 сбоя подряд ПО ВИНЕ НОДЫ — не cooldown, а пересадка.
            if NH.fleet_wide(ecls):
                print(f'  нода {node_id[:8]}: серия {streak} ({ecls}), но то же самое у других '
                      f'нод — это общая сеть, пересадку не делаю', flush=True)
                return
            if alive < 2:
                print(f'  нода {node_id[:8]}: серия {streak} ({ecls}), но живых нод осталось '
                      f'{alive} — пересадку откладываю, иначе прогон встанет', flush=True)
                return
            NH.retire(node_key)     # чтобы супервизор не подключил её обратно через минуту
            # API зовём БЕЗ nodes_lock: это до 30 с сети, под замком повис бы супервизор.
            if NH.take_cull_slot():
                if NH.reallocate(group, node_id, f'{streak} сбоя подряд: {ecls}'):
                    js.extend_grace(WARMUP_GRACE_S)
            else:
                print(f'  нода {node_id[:8]}: серия {streak}, но бюджет пересадок исчерпан — '
                      f'просто вывожу из пула', flush=True)
            return

    def spawn(node_id: str, port: int, group: str = GROUP):
        if node_id not in gpu_of:
            # Модель карты спрашиваем ОДИН раз на ноду и ФОНОМ: нужна для сравнения
            # 4090 с 3090/3090 Ti/A5000, но задерживать из-за неё первое задание нельзя.
            gpu_of[node_id] = None
            threading.Thread(target=ask_gpu, args=(node_id, port), daemon=True).start()
        t = threading.Thread(target=worker, args=(node_id, port, group), daemon=True)
        with nodes_lock:
            nodes[node_id] = {'thread': t, 'port': port, 'until': 0.0}
        t.start()

    for i, inst in enumerate([n for n in instances() if n['port'] in ports]):
        if NH.is_retired(f'{inst["group"]}/{inst["id"]}'):
            print(f'  нода {inst["id"][:8]}: снята за серию сбоев — в прогон не беру', flush=True)
            continue
        spawn(inst['id'], inst['port'], inst['group'])
        time.sleep(2 if i else 0)

    def supervisor():
        """Ищет НОВЫЕ ноды, пока в очереди есть работа: состав пула больше не заморожен
        на момент старта (грабля 31.08 — волна шла на одной ноде рядом с простаивающими)."""
        last_cull = time.time()
        while not stop.wait(POLL_S):
            if js.pending() == 0:
                return
            for inst in instances():
                with nodes_lock:
                    st = nodes.get(inst['id'])
                    busy = st and (st['thread'].is_alive() or time.time() < st['until'])
                if busy:
                    continue
                # Снятая за серию сбоев нода не должна вернуться в пул через минуту —
                # иначе предохранитель бесполезен: она снова наберёт задания и провалит их.
                if NH.is_retired(f'{inst["group"]}/{inst["id"]}'):
                    continue
                if not probe_warm(inst['port']):
                    continue
                print(f'  + нода {inst["id"][:8]} (порт {inst["port"]}) подключена к прогону', flush=True)
                spawn(inst['id'], inst['port'], inst['group'])
            if time.time() - last_cull > CULL_S:
                last_cull = time.time()
                cull_slow()

    threading.Thread(target=supervisor, daemon=True).start()
    js.wait_all()
    stop.set()

    s = js.summary()
    rows = js.results()
    spool_unresolved(rows)
    state = {'transport': 'ssh', 'ports': ports, 'at': time.time(),
             'wall_s': round(time.time() - t0), 'summary': s,
             'results': [{k: v for k, v in r.items() if k != 'job'} for r in rows]}
    json.dump(state, open(RESULTS, 'w'), ensure_ascii=False, indent=1)
    report(state)
    print('RUN_SUMMARY ' + json.dumps(s), flush=True)
    if not keep_alive:
        stop_group()
    if js.stalled:
        # Ноды кончились посреди прогона — это ожидание ёмкости, а не брак заданий: конвейер
        # должен подождать и повторить, а не считать волну проваленной и уйти дальше.
        return EXIT_NO_CAPACITY
    return 0 if s['unresolved'] == 0 else 1


def report(state: dict | None = None) -> None:
    state = state or json.load(open(RESULTS, encoding='utf-8'))
    rows = state['results']
    ok = [r for r in rows if r.get('status') in ('ok', 'cached')]
    gpu_s = sum(float((r.get('timings_s') or {}).get('total') or 0) for r in rows)
    cost = gpu_s / 3600 * RATE
    print(f'\nзаданий {len(rows)}, готово {len(ok)}, календарь {state.get("wall_s")}с, '
          f'GPU-секунд {round(gpu_s)}, ≈${cost:.3f} (${cost / max(len(ok), 1):.4f}/меш)')
    st: dict[str, int] = {}
    for r in rows:
        st[r.get('status', '?')] = st.get(r.get('status', '?'), 0) + 1
    print('статусы:', st)
    times = sorted(float(r['timings_s']['total']) for r in ok if r.get('timings_s'))
    if times:
        pk = [float((r.get('gpu') or {}).get('paint_gb') or 0) for r in ok]
        print(f'медиана {times[len(times) // 2]:.0f}с/меш | пик VRAM покраски {max(pk):.1f} ГБ')


def main() -> None:
    """Коды возврата — контракт с конвейером: 0 — всё закрыто, 75 — нет ёмкости (ждать и
    повторить), иной ≠0 — остались нерешённые транспортные задания."""
    if '--report' in sys.argv:
        report()
        return
    lim = int(sys.argv[sys.argv.index('--limit') + 1]) if '--limit' in sys.argv else None
    skip = int(sys.argv[sys.argv.index('--skip') + 1]) if '--skip' in sys.argv else 0
    jf = sys.argv[sys.argv.index('--jobs-file') + 1] if '--jobs-file' in sys.argv else None
    sys.exit(run(lim, '--keep-alive' in sys.argv, jf, skip))


if __name__ == '__main__':
    main()
