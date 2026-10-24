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
import concurrent.futures as cf
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
# Тот же интерпретатор, что у конвейера: шаги уборки зовутся из venv, а не из системного python.
PY = os.environ.get('MESH_PY') or os.path.expanduser('~/venvs/scout/bin/python')
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
sys.path.insert(0, HERE)
import salad_groups as SG  # noqa: E402 — тариф/окно/цена группы: ОДИН источник (rules/salad-groups.json)
import sink_health as SH   # noqa: E402 — здоров ли приёмник: проверка ДО раздачи GPU-времени
# Без умолчания (04.09): тихий `mesh-run3` из старого кода заставил бы работать с удалённой
# группой. Пусто допустимо только при импорте (стенд); `main()` откажет.
GROUPS = SG.groups_or_empty()
GROUP = GROUPS[0] if GROUPS else ''
# Предохранитель от разросшейся очереди. Владелец 31.08 ставил 2000 (481 сетовых + демо +
# добор), но 01.09 очередь стала полной по каталогу — 11 704 задания в порядке регламента
# (`rules/mesh-priority.json`). Держим переопределяемым: молчаливое усечение хуже явного
# отказа, а зашитая цифра однажды уже уронила конвейер при живых нодах.
MAX_JOBS = int(os.environ.get('MESH_MAX_JOBS', '2000'))
_lock = threading.Lock()
import random
# СОСТОЯНИЕ ПРИЁМНИКА — один опрос на процесс (супервизор, раз в POLL_S), воркеры читают флаг без
# сети перед КАЖДЫМ заданием: красный приёмник = не брать работу, а не узнать о 507 после GPU.
_SINK = {'ok': True, 'why': '', 'at': 0.0}

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
import proc_run as PR     # noqa: E402 — шаг оболочки без сирот (общий с `batch_show`)
import input_quarantine as IQ  # noqa: E402 — фото, которое магазин не отдаёт (403), не гоняем по машинам (T-20261022-10 Г)

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


def probe_health(port: int) -> dict:
    """Ответ `/health` ноды, спрошенный через её терминал. Пустой словарь — не ответила.

    Отдельно от `probe_warm`, потому что сам ответ нужен не только для «брать/не брать»:
    по нему пересаживают ноды с намертво упавшим прогревом (`batch_show.cull_dead_warmups`).
    """
    try:
        r = ssh_text(port, 'python -c "import urllib.request;'
                           'print(urllib.request.urlopen(\'http://127.0.0.1:8000/health\','
                           'timeout=5).read().decode())"', timeout=50)
    except Exception as e:  # noqa: BLE001 — ЗАВИСШИЙ SSH НЕ ВАЛИТ ПРОГОН (31.08: нода
        # перестала отвечать, TimeoutExpired вылетел из пробы и убил всю пачку —
        # «пачка без итога (код 1) — стоп, разбор руками», группа погашена в разгар волны)
        print(f'  порт {port}: проба не удалась ({type(e).__name__}) — считаю ноду холодной',
              flush=True)
        return {}
    m = re.search(r'\{.*\}', r or '')
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return {}


def warmup_fault(h: dict) -> str:
    """Короткая причина упавшего прогрева, пригодная для группировки. Пусто — прогрев цел."""
    why = (h.get('warmup_error') or '').strip().splitlines()
    return why[-1][:160] if why else ''


# МОЛЧАЩАЯ НОДА — ТОЖЕ МЁРТВАЯ, И ЕЁ НАДО СНИМАТЬ ИЗ СУПЕРВИЗОРА (04.09).
# Два детектора зомби расходились: `batch_show.cull_dead_warmups` считает пустой `/health`
# смертью («нет ответа по SSH»), а супервизор — нет, потому что `warmup_fault({})` == ''
# и `phase` у пустого ответа отсутствует. Но `batch_show` крутится только МЕЖДУ пачками, а
# `ssh_run --keep-alive` держит процесс часами — всё это время молчащие ноды тарифицируются
# как `running` и не снимает их никто. Замер 04.09: нода `c9cedfa9` молчала 305 с и дальше,
# при этом соседняя прогрелась за 147 с. Молчание дольше SILENT_ZOMBIE_S — приговор.
#
# Порог, а не мгновенный приговор: uvicorn поднимается ДО прогрева, но у только что
# стартовавшей ноды первые секунды ответа может не быть, а пересадка стирает уже скачанный
# образ (урок 402 — так сняли ноду со 100 % закачки).
SILENT_ZOMBIE_S = float(os.environ.get('MESH_SILENT_ZOMBIE_S', '600'))
_SILENT: dict = {}       # instance_id → когда впервые не ответила подряд


def silent_fault(iid: str, h: dict, now: float | None = None) -> str:
    """Приговор молчащей ноде. Пусто — либо ответила, либо молчит ещё недолго.

    Причина возвращается БЕЗ секунд: строка идёт в группировку «общая беда» — с разными
    числами одинаковые случаи не схлопнулись бы, и предохранитель перестал бы работать.
    """
    now = now or time.time()
    if h:
        _SILENT.pop(iid, None)
        return ''
    first = _SILENT.setdefault(iid, now)
    return 'нет ответа по SSH' if now - first >= SILENT_ZOMBIE_S else ''


def probe_warm(port: int) -> bool:
    """Прогрет ли воркер ноды. Спрашиваем ноду ЛИЧНО через её терминал — флагам платформы
    после тех двух дней веры нет. Проба дорогая (до 50 с), поэтому зовём её только для
    НОВЫХ и остывших нод, а не по кругу для всех."""
    h = probe_health(port)
    if h.get('warm'):
        # `warm` воркер ставит в `finally` — то есть и после упавшего прогрева
        # (`worker.py`). Такая нода отвечает «готова», берёт задания и валит их.
        # Правку самого воркера видно только после пересборки образа, поэтому гейт
        # ставим здесь: у нас эта информация уже есть, она едет в /health.
        fault = warmup_fault(h)
        if fault:
            # ТЕКСТ ОШИБКИ ОБЯЗАТЕЛЕН (02.09): три часа пул простаивал с сообщением
            # «прогрев упал», и причину — недостающую DINOv2 и таймаут CDN HuggingFace —
            # пришлось доставать из ноды руками. Отказ без причины в логе не отличим от
            # любого другого отказа, и разбор начинается заново каждый раз.
            print(f'  порт {port}: прогрев упал — ноду не беру: {fault}', flush=True)
            return False
        return True
    # РАЗЛИЧАТЬ «МОЛЧИТ» И «ЕЩЁ ГРЕЕТСЯ» (04.09). Раньше здесь была одна строка на оба случая —
    # «не прогрет ИЛИ не отвечает», — и по логу нельзя было понять, что происходит с пулом:
    # 16 нод тарифицировались как `running`, конвейер видел «тёплых 0», а причина (сеть или
    # долгий прогрев) требовала ручного захода на ноду. Лечение у случаев РАЗНОЕ: молчащую
    # надо пересаживать, греющуюся — ждать. Поэтому печатаем то, что нода реально ответила.
    if not h:
        print(f'  порт {port}: нода не ответила на /health (SSH или разбор ответа)', flush=True)
    else:
        print(f'  порт {port}: воркер не готов — warm={h.get("warm")} '
              f'phase={h.get("phase")!r} done={h.get("done")}', flush=True)
    return False


PROBE_WORKERS = int(os.environ.get('MESH_PROBE_WORKERS', '6'))


# УПРЕЖДАЮЩАЯ УБОРКА ТРАНЗИТА (05.09). Замер: за час 08:15–09:15 была одна пауза в 17.6 минуты —
# все воркеры разом встали в 08:55 и разом пошли в 09:12. Это цикл `while not _SINK['ok']` ниже:
# приёмник покраснел, и защита из ADR-0175 честно остановила раздачу, чтобы не жечь GPU на
# заведомо неудачных отправках. Но 18 минут простоя при двух десятках оплаченных машин — это
# ~7 нодо-часов из 16, около 30 % стоимости мешей за тот час.
#
# Корень не в защите, а в том, что уборка была РЕАКТИВНОЙ: чистка запускалась по таймеру разбора
# и по факту отказа, то есть уже ПОСЛЕ остановки пула. При 100+ мешах в час приёмник наполняется
# быстрее (замер: +2.5 ГБ/ч), чем приходит таймер, и упирается в предел 8 ГБ раньше.
# Теперь супервизор, который и так опрашивает здоровье каждые POLL_S, при пересечении ЖЁЛТОГО
# порога запускает drain+purge фоном — до того, как приёмник станет красным.
#
# Шаги те же, что у аварийной ветки `batch_show` («приёмник не принимает — стаскиваю и чищу
# СЕЙЧАС»): drain --keep + purge. Гонок нет: у `drain.sh` свой flock (ждёт и возвращает 75), а
# `receiver_purge` идемпотентен и удаляет только уже скачанное и записанное в реестр.
# Жёлтый порог — «тесно» из `sink_health.tight` (20.10, mesh-12): своя копия числа 6 ГБ здесь мерила
# тот же каталог, что ворота, но порог жил отдельно от чистки — теперь у всех троих одна лестница.
SINK_RELIEF_COOLDOWN_S = float(os.environ.get('MESH_SINK_RELIEF_COOLDOWN_S', '600'))
_RELIEF: dict = {'busy': False, 'at': 0.0}

# МИНИМАЛЬНАЯ ЦЕПОЧКА ОСВОБОЖДЕНИЯ ПРИЁМНИКА — не «стащить и почистить» (05.09).
# `receiver_purge` удаляет комплект с моделью, только если он записан в реестр поколений
# (`receiver_purge.registered_dirs`, пишет `ingest_registry`; до 20.10 — метка `mesh_status='ready'`
# от `mesh_bind`). Уборка из
# двух шагов честно печатала «ok» и удаляла НОЛЬ: 459 комплектов, 7.3 ГБ, «оставляю: нет в базе
# 459» — то есть и упреждающая уборка (ADR-0199), и аварийная ветка `batch_show` были пустыми,
# а пул стоял оплаченным на красном приёмнике. `apply_repairs` (приёмка) здесь пропускаем
# намеренно: она долгая, а для метки не нужна. Полный разбор — `batch_show.post_steps`.
SINK_RELIEF_CHAIN = (
    ('стаскиваю', f'bash {HERE}/drain.sh --keep'),
    ('реестр', f'{PY} {HERE}/ingest_registry.py'),
    ('пометка в базе', f'{PY} {os.path.join(HERE, "..", "mesh_bind.py")}'),
    ('чистка', f'{PY} {HERE}/receiver_purge.py --apply'),
)


def sink_relief(h: dict, now: float | None = None) -> bool:
    """Запустить уборку транзита ДО красной черты. True — запустили в этот раз. `h` — ответ
    `SH.check()`: уборка идёт, когда там непустое `tight`.

    Порог жёлтый, а не красный: на красном пул уже стоит. Дроссель нужен, чтобы при медленной
    уборке не плодить параллельные заходы — один разбор идёт до 30 минут.
    """
    now = now or time.time()
    why = h.get('tight') or ''
    if _RELIEF['busy'] or not why or now - _RELIEF['at'] < SINK_RELIEF_COOLDOWN_S:
        return False
    _RELIEF.update(busy=True, at=now)
    print(f'  приёмник: тесно — {why}; упреждающая уборка, пул не останавливаю', flush=True)

    def work() -> None:
        try:
            for step, cmd in SINK_RELIEF_CHAIN:
                # ЧЕРЕЗ proc_run, А НЕ subprocess.run: по таймауту тот убил бы только оболочку,
                # а rsync/purge остались бы сиротами и полезли в тот же каталог со следующим
                # заходом уборки (тот же дефект, что съел дев-машину 05.09).
                rc, out = PR.run_step(cmd, timeout=1800)
                tail = out.strip().splitlines()[-1:] or ['']
                print(f'  [упреждающая уборка] {step}: rc={rc} {tail[0][:120]}', flush=True)
        except Exception as e:  # noqa: BLE001 — уборка не должна ронять раздачу
            print(f'  [упреждающая уборка] сбой: {type(e).__name__}: {str(e)[:80]}', flush=True)
        finally:
            _RELIEF['busy'] = False

    threading.Thread(target=work, daemon=True).start()
    return True


def sink_poll(force: bool = False) -> bool:
    """Обновить флаг приёмника. Не чаще POLL_S, кроме `force` (подозрение на 507 у воркера)."""
    now = time.time()
    if not force and now - _SINK['at'] < POLL_S * 0.9:
        return _SINK['ok']
    h = SH.check()
    sink_relief(h, now)
    if _SINK['ok'] and not h['ok']:
        print(f'!! приёмник красный: {h["why"]} — воркеры ждут', flush=True)
    elif not _SINK['ok'] and h['ok']:
        print('приёмник снова принимает — продолжаем', flush=True)
    _SINK.update(ok=h['ok'], why=h['why'], at=now)
    return h['ok']


def sink_preflight() -> bool:
    """Перед раздачей: место + канарейка. Печатает «ПРИЁМНИК …» — по этому слову `batch_show`
    запускает drain+purge немедленно, не дожидаясь тика разбора."""
    h = SH.check()
    if not h['ok']:
        print(f'ПРИЁМНИК не принимает: {h["why"]} — задания не раздаю', flush=True)
        SH.alert_throttled(f'Меши: приёмник не принимает — {h["why"]}. Раздача остановлена, '
                           f'конвейер стаскивает и чистит.')
        return False
    c = SH.canary()
    if not c['ok']:
        print(f'ПРИЁМНИК не прошёл канарейку: {c["why"]} — задания не раздаю', flush=True)
        SH.alert_throttled(f'Меши: приёмник не прошёл проверку записью — {c["why"]}. Раздача остановлена.')
        return False
    _SINK.update(ok=True, why='', at=time.time())
    print(f'приёмник: свободно {h["free_gb"]:.1f} ГБ, каталог {h["dir_gb"]:.1f}/{h["max_dir_gb"]:.0f} ГБ, '
          f'канарейка {c["sec"]:.1f} с', flush=True)
    return True


def warm_ports() -> list[int]:
    """SSH-порты прогретых нод — стартовый снимок; дальше состав пула ведёт супервизор.

    ПРОБЫ ИДУТ ПАРАЛЛЕЛЬНО (02.09). Раньше здесь был последовательный обход, а одна проба
    стоит до 50 с: девять неготовых нод задерживали запуск ЕДИНСТВЕННОЙ готовой на 7.5 минуты,
    и так на каждой пачке. Ноды в это время оплачивались и простаивали. Порядок портов в ответе
    сохраняем — от него зависит раздача заданий.
    """
    ports = [i['port'] for i in instances()]
    if not ports:
        return []
    with cf.ThreadPoolExecutor(max_workers=min(PROBE_WORKERS, len(ports))) as ex:
        verdicts = dict(zip(ports, ex.map(probe_warm, ports)))
    return [p for p in ports if verdicts.get(p)]


def ssh_text(port: int, cmd: str, timeout: int = 60) -> str:
    """Одна команда через интерактивную обёртку. stdin — команды, вывод — как есть."""
    ssh_slot()
    r = subprocess.run(
        ['ssh', '-i', SSH_KEY, '-tt', '-o', 'StrictHostKeyChecking=no',
         '-o', 'BatchMode=yes', '-o', 'ServerAliveInterval=30', '-p', str(port), SSH_HOST],
        input=f'{cmd}; exit\n', capture_output=True, text=True, timeout=timeout)
    return r.stdout


def probe_node(port: int) -> tuple[str, float | None]:
    """Модель карты и ОЗУ машины (MemTotal, десятичные ГБ) одной сессией. `/proc/meminfo` в контейнере — память ВСЕЙ
    машины (у WSL — её виртуалки), а не наш лимит (`mem_probe.py`): именно она решает, переживёт ли машина генерацию.
    Не ответила — ('?', None): проверку пропускаем, ноду не наказываем."""
    try:
        out = ssh_text(port, 'nvidia-smi --query-gpu=name --format=csv,noheader; grep MemTotal /proc/meminfo', timeout=40) or ''
    except Exception:  # noqa: BLE001 — диагностика не должна мешать работе
        return '?', None
    g = re.search(r'(?:NVIDIA|AMD)[^\r\n]*', out)
    m = re.search(r'MemTotal:\s+(\d+)\s*kB', out)
    return (g.group(0).strip()[:40] if g else '?'), (round(int(m.group(1)) * 1024 / 1e9, 1) if m else None)


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
            kind = NH.transport_class(r.stdout, r.stderr, r.returncode)
            # ВТОРОЙ ЗАХОД — ТОЛЬКО ПРИ ПУСТОМ ВЫВОДЕ (04.09). Раньше цикл шёл на вторую попытку
            # при любом отсутствии маркера, в том числе после обрыва ПОСРЕДИ генерации — и слал
            # /generate второй раз: двойная оплата GPU за один меш. При `node_taken` (бывш. mid_generation) первая
            # нода, скорее всего, доделает и опубликует (SSH оборвался, воркер — нет): задание
            # уедет на другую ноду через RETRY_GRACE_S, и `already_done` подхватит результат.
            # Пустой вывод после принятого /generate тоже возможен — остаточный риск признан;
            # закроется `inflight`/`GET /job` в воркере после ребилда образа (план P1-7).
            if attempt == 1 and kind == 'empty':
                time.sleep(8)          # пустой вывод = коллизия сессий, второй заход
                continue
            break
        if not m:
            kind = NH.transport_class(r.stdout, r.stderr, r.returncode)
            # хвосты длиннее (T-20261024-01): 100 знаков обрезали причину на полуслове
            tail = (r.stdout or '').strip()[-300:].replace('\n', ' ')
            etail = (r.stderr or '').strip()[-300:].replace('\n', ' ')
            return {'sku': job['sku'], 'status': 'transport_failed', 'node_port': port,
                    'error': f'ssh/{kind} rc={r.returncode}: {tail} | err: {etail}'.strip()}
        res = json.loads(m.group(1))
        res['wall_s'] = round(time.time() - t0, 1)
        res['node_port'] = port
        return res
    except subprocess.TimeoutExpired as e:
        # хвост вывода первой попытки раньше терялся целиком — теперь видно, что успело напечататься
        out = e.stdout.decode(errors='replace') if isinstance(e.stdout, bytes) else (e.stdout or '')
        return {'sku': job['sku'], 'status': 'transport_failed', 'node_port': port,
                'error': f'ssh/timeout: {out.strip()[-100:]}'.replace('\n', ' ').strip()}
    except Exception as e:  # noqa: BLE001 — транспорт не должен ронять весь прогон
        return {'sku': job['sku'], 'status': 'transport_failed',
                'error': f'{type(e).__name__}: {str(e)[:160]}'}


def group_status(g: str) -> str | None:
    """Состояние группы по API (`current_state.status`); None — не смогли узнать."""
    try:
        req = urllib.request.Request(f'{API}/organizations/{ORG}/projects/{PROJECT}/containers/{g}',
                                     headers={'Salad-Api-Key': key(), 'User-Agent': 'remlab-mesh/1.0'})
        with urllib.request.urlopen(req, timeout=30) as r:
            return (json.loads(r.read()).get('current_state') or {}).get('status')
    except Exception:  # noqa: BLE001 — None = «не знаю», вызывающий решит
        return None


def stop_group(verify: bool = True, wait_s: int = 240, poll_s: int = 15) -> bool:
    """Гасим ВСЕ группы сразу после прогона: тарифицируется состояние, а не работа (ADR-0135).

    ПРОВЕРЯЕМ, А НЕ ВЕРИМ (conv-11, разбор Codex 13.10): `/stop` отвечает 202 «принято», а не «остановлено»,
    и раньше ошибка проглатывалась — финал и сторож простоя сообщали «погасил» с кодом 0. Теперь ждём
    `stopped` у каждой группы не дольше `wait_s` и возвращаем False, если хоть одна не погасла:
    вызывающие (финал конвейера, сторож простоя) по False повторяют и кричат в телеграм."""
    failed = []
    for g in GROUPS:
        try:
            req = urllib.request.Request(
                f'{API}/organizations/{ORG}/projects/{PROJECT}/containers/{g}/stop',
                data=b'', method='POST', headers={'Salad-Api-Key': key(), 'User-Agent': 'remlab-mesh/1.0'})
            with urllib.request.urlopen(req, timeout=60) as r:
                r.read()
            print(f'группа {g}: stop принят')
        except Exception as e:  # noqa: BLE001 — это деньги, говорим громко
            print(f'!! ГРУППУ {g} НЕ ОСТАНОВИТЬ ({type(e).__name__}: {str(e)[:120]}) — '
                  f'останови вручную в портале', flush=True)
            failed.append(g)
    if not verify:
        return not failed
    left = [g for g in GROUPS if g not in failed]
    deadline = time.time() + wait_s
    while left:
        left = [g for g in left if group_status(g) != 'stopped']
        if not left or time.time() >= deadline:
            break
        time.sleep(poll_s)
    for g in [g for g in GROUPS if g not in failed and g not in left]:
        print(f'группа {g} остановлена — счёт больше не идёт')
    for g in left:
        print(f'!! группа {g} за {wait_s} с не перешла в stopped (сейчас {group_status(g)}) — проверь портал', flush=True)
    return not failed and not left


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


# ИДЕМПОТЕНТНОСТЬ ПО СНИМКУ (план mesh-13, 21.10). Курсор позиционный: хвост за «дыркой» (terminal_prefix <
# terminal) и любая пачка, начатая с прежнего места, снова раздавали сделанное, а кэш приёмника, на который
# рассчитывал этот замысел, к тому времени вычищен разбором по таймеру — платили второй раз. Теперь (sku, seed),
# закрытые ok/cached в ЭТОМ снимке, лежат в `<снимок>.done` и ноде не раздаются.
DONE_SET = SAMPLE + '.done'
_done_lock = threading.Lock()
_done_keys: set | None = None


def done_keys() -> set:
    """(sku, seed), уже закрытые ok/cached в этом снимке. Нет файла — пусто; битый — пусто С ПРЕДУПРЕЖДЕНИЕМ
    (худшее — повтор за деньги, но не потеря задания)."""
    global _done_keys
    with _done_lock:
        if _done_keys is None:
            _done_keys = set()
            if os.path.exists(DONE_SET):
                try:
                    _done_keys = {(k[0], int(k[1])) for k in json.load(open(DONE_SET, encoding='utf-8'))}
                except (OSError, ValueError, TypeError, IndexError) as e:
                    print(f'  !! {DONE_SET} не читается ({type(e).__name__}) — сделанное этого снимка не отсекаю',
                          flush=True)
        return set(_done_keys)


def mark_done(sku: str, seed) -> None:
    """Задание закрыто ok/cached — в `<снимок>.done`. Запись атомарная (tmp → rename): файл читают следующие
    вызовы `ssh_run`, половину они видеть не должны. Сбой записи прогон не роняет, но не молчит."""
    global _done_keys
    done_keys()
    k = (sku, int(seed or 0))
    with _done_lock:
        if k in _done_keys:
            return
        _done_keys.add(k)
        tmp = DONE_SET + '.tmp'
        try:
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(sorted([s, n] for s, n in _done_keys), f)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, DONE_SET)
        except OSError as e:
            print(f'  !! {DONE_SET}: не записан ({type(e).__name__}) — повтор этого задания возможен', flush=True)


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
            # `stalled` — остаток уже закрыт (приёмник/нет нод): своё задание в работе закрываем
            # его собственным результатом, повторять его в этой пачке некому
            if transport_ok or it['attempts'] >= MAX_ATTEMPTS or self.stalled:
                it['result'] = res
            else:
                it['not_before'] = time.time() + RETRY_GRACE_S
            self.cv.notify_all()

    def preclose(self, keys: set) -> int:
        """Задания, уже закрытые в этом снимке (`done_keys`), не раздаём: результат `done_before` терминален и
        входит в `terminal_prefix` — курсор проходит их без денег. Возвращает, сколько закрыто."""
        n = 0
        with self.cv:
            for it in self.items:
                j = it['job']
                if it['result'] is None and (j.get('sku'), int(j.get('seed') or 0)) in keys:
                    it['result'] = {'sku': j.get('sku'), 'status': 'done_before'}
                    n += 1
        return n

    def preclose_quarantine(self, skus: set) -> int:
        """Товары в карантине входа (`input_quarantine`) ноде не раздаём: статус `input_quarantined` терминален
        (`node_health._JOB_STATUSES`), курсор идёт дальше; на проверку товар вернёт `release_due` через спул."""
        n = 0
        with self.cv:
            for it in self.items:
                if it['result'] is None and it['job'].get('sku') in skus:
                    it['result'] = {'sku': it['job'].get('sku'), 'status': IQ.STATUS, 'error': 'карантин входа'}
                    n += 1
        return n

    def machine_blocked(self, cur: dict, skus: set) -> int:
        """Машину не пускает магазин (T-20261022-13): её текущее задание `cur` отпускается без результата (вместо `done`:
        busy снят, inflight−1) и вместе с прежними заданиями серии возвращается в очередь — `reopen`. Один шаг под `cv`."""
        with self.cv:
            cur['busy'] = False
            self.inflight -= 1
            if self.stalled:             # остаток уже закрыт (приёмник/нет нод) — своё закрываем, как `done`
                cur['result'] = {'sku': cur['job'].get('sku'), 'status': 'transport_failed', 'error': 'машину не пускает магазин'}
                self.cv.notify_all()
                return 0
            return self.reopen(skus)

    def reopen(self, skus: list | set) -> int:
        """Задания, чьи 403 дала машина, а не магазин (T-20261022-13): попытка на ней не в счёт, закрытое этим запретом
        (карантин или исчерпанные попытки) — снова в очередь, без паузы повтора. Возвращает, сколько вернулось.
        Занятое другой машиной не трогаем (его закроет её `done`), снимаем только попытку."""
        n = 0
        with self.cv:                    # Condition на RLock — повторный вход из `machine_blocked` допустим
            if self.stalled:
                return 0
            for it in self.items:
                r = it['result']
                if it['job'].get('sku') not in skus:
                    continue
                if r is not None and not (r.get('status') == IQ.STATUS or IQ.forbidden(r)):
                    continue                     # уже сделано другой машиной — трогать нечего
                it['attempts'] = max(0, it['attempts'] - 1)
                if it['busy']:
                    continue                     # другая машина уже везёт — снята только попытка
                it['result'], it['not_before'] = None, 0.0
                n += 1
            self.cv.notify_all()
        return n

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

    def close_rest(self, reason: str) -> int:
        """Закрыть все ещё открытые задания как транспортный сбой ИНФРЫ (приёмник не принимает):
        курсор не двигается (`blocking` держит `transport_failed`), задания уйдут в следующую
        пачку, а ноды за это никто не винит и не пересаживает. Возвращает, сколько закрыто."""
        n = 0
        with self.cv:
            for it in self.items:
                if it['result'] is None and not it['busy']:   # занятые закроются своим `done()`
                    it['result'] = {'sku': it['job']['sku'], 'status': 'transport_failed',
                                    'error': f'infra/sink: {reason}'}
                    n += 1
            self.stalled = True
            self.cv.notify_all()
        return n

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
    # ПРИЁМНИК — ДО НОД (04.09): свободное место и настоящая запись (канарейка), иначе меш
    # посчитают за деньги и не смогут сдать. Отказ = «нет ёмкости» (75): конвейер стаскивает,
    # чистит и повторяет, спул остаётся на месте.
    if not sink_preflight():
        return EXIT_NO_CAPACITY
    jobs = jobs_from_file(jobs_file) if jobs_file else jobs_from_sample(None)[skip:(skip + limit) if limit else None]
    # --skip вместо растущего --limit: кэш «уже сделано» живёт на приёмнике и умирает при
    # drain — растущий префикс перегенерировал ВСЁ предыдущее каждой пачкой (поймано 30.08:
    # конвейер стал квадратичным, страница стояла).
    js = Jobs(jobs)
    # Срез снимка — без сделанного в этом снимке (`.done`); перегон и спул идут своими файлами и seed.
    n_pre = 0 if jobs_file else js.preclose(done_keys())
    if n_pre:
        print(f'уже сделано в этом снимке ({os.path.basename(DONE_SET)}): {n_pre} из {len(jobs)} — ноде не раздаю',
              flush=True)
    n_q = js.preclose_quarantine(IQ.active())
    if n_q:
        print(f'в карантине входа (магазин не отдаёт фото): {n_q} — ноде не раздаю', flush=True)
    # Срок вышел — на проверку через спул. Только в прогоне СРЕЗА: прогон по файлу — это сам спул (`drain_retry_spool`
    # забрал его в `.inflight`); новый спул, созданный посреди него, при «нет нод» не дал бы вернуть `.inflight` на место.
    due = [] if jobs_file else IQ.release_due(skip={j.get('sku') for j in jobs})
    if due:
        # срок вышел — один раз на проверку через спул повторов (его прогонит `batch_show.drain_retry_spool`)
        try:
            with open(RETRY_SPOOL, 'a', encoding='utf-8') as f:
                for j in due:
                    f.write(json.dumps({'job': j, 'sku': j.get('sku'), 'seed': j.get('seed'), 'status': 'input_recheck',
                                        'at': round(time.time())}, ensure_ascii=False) + '\n')
            print(f'карантин входа истёк: {len(due)} — в спул повторов на проверку', flush=True)
        except OSError as e:
            print(f'  !! спул повторов: {type(e).__name__} — проверка карантина отложена', flush=True)
    n_pre += n_q
    if jobs and n_pre == len(jobs):
        # Весь срез сделан: курсор проходит его без нод и без денег.
        print('RUN_SUMMARY ' + json.dumps(js.summary()), flush=True)
        return 0
    ports = warm_ports()
    print(f'тёплых нод: {len(ports)} {ports}')
    if not ports:
        print('нет прогретых нод', flush=True)
        return EXIT_NO_CAPACITY
    print(f'заданий: {len(jobs) - n_pre} на {len(ports)} нод(ы) на старте')

    t0 = time.time()
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
    closed = [n_pre]          # счёт [k/N] — по всему срезу, сделанное раньше уже закрыто

    def worker(node_id: str, port: int, group: str):
        node_key = f'{group}/{node_id}'
        while not stop.is_set():
            # красный приёмник — не берём работу, ждём (флаг обновляет супервизор, без сети здесь)
            while not _SINK['ok'] and not stop.is_set():
                time.sleep(15)
            if stop.is_set():
                return
            it = js.take(node_id)
            if it is None:
                return
            r = run_job(port, it['job'])
            # 403 на N разных товарах подряд у ОДНОЙ машины — магазин не пускает её адрес (T-20261022-13): товары не
            # виноваты, текущий запрет в их карантин не идёт, прежние из серии с них снимаются
            blocked = forbid_series(node_id, it['job'], r)
            q_until = 0.0 if blocked else IQ.note(it['job'], r)
            # Подозрение на приёмник (генерация прошла, публикация упала с 507/EOF) — это ПОВОД
            # спросить приёмник, а не диагноз: тот же текст даёт CDN фото и SSH-шлюз (Codex 04.09).
            # Красный → остаток пачки закрываем как инфра-сбой (75), нод не виним и не пересаживаем.
            sink_ok = None
            if NH.infra_suspect(r):
                sink_ok = sink_poll(force=True)
                if not sink_ok:
                    n_closed = js.close_rest(_SINK['why'])
                    print(f'!! ПРИЁМНИК не принимает ({_SINK["why"]}) — закрываю остаток пачки '
                          f'({n_closed}) как инфра-сбой, ноды не виноваты', flush=True)
                    SH.alert_throttled(f'Меши: приёмник не принимает результаты — {_SINK["why"]}. '
                                       f'Пачка остановлена, конвейер стащит и почистит; ноды не виноваты.')
                    stop.set()
            # Терминально только то, в чём задание виновато САМО (или отработало). Вина ноды
            # и «непонятно» возвращают задание в очередь: раньше `input_failed` закрывался
            # как ответ генератора, курсор уходил вперёд, и товар терялся молча (01.09).
            fault = NH.classify(r, sink_ok)
            ecls = NH.error_class(r)
            # карантин входа: запрет магазина набрал серию — задание закрыто, по машинам больше не едет
            terminal = fault in (NH.FAULT_NONE, NH.FAULT_JOB) or bool(q_until)
            rec = {**r, 'node': node_id[:8], 'attempt': it['attempts'], 'fault': fault,
                   'group': group, 'at': round(time.time()), **({'status': IQ.STATUS} if q_until else {})}
            # ЖУРНАЛ И ПЕЧАТЬ — ДО `js.done` (T-20261022-13/2): `done` последнего задания отпускает `wait_all`, и прогон
            # мог подвести итог и выйти раньше, чем поток ноды запишет строку журнала (демон-поток при выходе обрывается)
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
                        'error': str(r.get('error') or '')[:700], 'at': round(time.time()),
                        **({'quarantine_until': round(q_until)} if q_until else {})})
            if q_until:
                print(f'  {it["job"].get("sku")}: магазин не отдаёт фото — карантин входа до '
                      f'{time.strftime("%d.%m %H:%M", time.gmtime(q_until))} UTC', flush=True)
            if r.get('status') in ('ok', 'cached'):
                mark_done(it['job'].get('sku'), it['job'].get('seed'))
            with _lock:
                closed[0] += 1
                t = (r.get('timings_s') or {}).get('total')
                print(f'  [{closed[0]}/{len(jobs)}] {str(it["job"].get("role")):14s} '
                      f'{r.get("status","?"):16s} {"" if t is None else str(t) + "с"} '
                      f'{node_id[:8]} {str(r.get("error") or "")[:60]}', flush=True)
            if blocked:
                for sku in blocked[:-1]:        # текущий запрет в карантин не записан — снимаем только прежние
                    IQ.forgive(sku)
                skus = list(dict.fromkeys(blocked))
                # текущее задание и прежние из серии — в очередь ОДНИМ шагом под замком очереди, вместо `done`:
                # между «закрыто» и «снова открыто» `wait_all` мог бы подвести итог и потерять задание
                n_back = js.machine_blocked(it, set(skus))
                reject_node(node_id, group, 'forbidden', f'403 на {len(skus)} разных товарах подряд — магазин не пускает машину',
                            skus=skus, reopened=n_back)
                return
            js.done(it, rec, terminal)
            if fault == NH.FAULT_INFRA:
                return                     # виновата инфра: серию ноды не растим, из пула не выводим
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

    mem_low: dict = {}        # instance_id → (группа, причина): снятая машина ждёт пересадки (бюджет пересадок кончился)

    def reject_node(node_id: str, group: str, tag: str, why: str, gpu: str | None = None, **fields) -> None:
        """Машина уходит по свойству САМОЙ машины (малая ОЗУ, магазин не пускает её адрес): строка в журнал — не попытка
        и не сбой меша (`kind`); нода снята (`retire`), чтобы супервизор не подключил её снова, и пересажена штатно —
        или ждёт свободного слота пересадок в `mem_low`."""
        gpu = gpu or gpu_of.get(node_id) or '?'
        print(f'  нода {node_id[:8]} ({gpu}): {why} — ухожу', flush=True)
        checkpoint({'at': round(time.time()), 'kind': 'node_reject', 'status': 'node_reject', 'node': node_id[:8],
                    'instance': node_id, 'group': group, 'gpu': gpu, 'reason': tag, 'why': why, **fields})
        NH.retire(f'{group}/{node_id}')
        if NH.take_cull_slot():
            if NH.reallocate(group, node_id, f'{tag}: {why}'):
                js.extend_grace(WARMUP_GRACE_S)
        else:
            mem_low[node_id] = (group, f'{tag}: {why}')

    def mem_reject(node_id: str, group: str, gpu: str, mem: float, need: float) -> None:
        """Машина с ОЗУ меньше порога уходит ДО первого задания (T-20261022-10 Б): задание никто не брал."""
        reject_node(node_id, group, 'ram', f'ОЗУ машины {mem} ГБ < {need:g} — до первого задания', gpu, mem_total_gb=mem, min_gb=need)

    forbid_seq: dict = {}     # instance_id → товары каждого запрета магазина подряд на этой машине (T-20261022-13)

    def forbid_series(node_id: str, job: dict, r: dict) -> list:
        """Серия набрала `node_after_n` РАЗНЫХ товаров — вернуть её (по товару на каждый запрет, текущий — последний;
        серия сброшена), иначе []. Скачанное фото рвёт серию (`IQ.fetched`); обрыв машины, 404, таймаут её не трогают."""
        n = IQ.node_after_n()
        if IQ.fetched(r):
            forbid_seq.pop(node_id, None)
            return []
        if n <= 0 or not IQ.forbidden(r):
            return []
        seq = forbid_seq.setdefault(node_id, [])
        seq.append(job.get('sku'))
        return forbid_seq.pop(node_id) if len(set(seq)) >= n else []

    def spawn(node_id: str, port: int, group: str = GROUP):
        need = SG.node_min_ram_gb()
        if need > 0 and node_id not in gpu_of:
            # ОЗУ — ДО первого задания (T-20261022-10 Б): машина с малой памятью роняет генерацию посередине
            # (гипотеза 22.10; события Salad 24.10 её опровергли: обрывы — вытеснение тарифом, порог выключен
            # в rules/salad-groups.json `node_ram.min_gb` = 0, T-20261024-01). Заодно — модель карты.
            gpu, mem = probe_node(port)
            if gpu != '?':
                gpu_of[node_id] = gpu        # не ответила — карту спросит фоновый опрос ниже
            if mem is not None and mem < need:
                mem_reject(node_id, group, gpu, mem, need)
                return
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
        warm_logged: set[str] = set()   # чей прогрев уже записан
        while not stop.wait(POLL_S):
            if js.pending() == 0:
                return
            sink_poll()                      # один опрос приёмника на процесс, флаг читают воркеры
            for nid, (g, why) in list(mem_low.items()):   # машину сняли, а слота пересадки не было — пробуем снова
                if not NH.take_cull_slot():
                    break
                mem_low.pop(nid)
                if NH.reallocate(g, nid, why):
                    js.extend_grace(WARMUP_GRACE_S)
            cands = []
            for inst in instances():
                with nodes_lock:
                    st = nodes.get(inst['id'])
                    busy = st and (st['thread'].is_alive() or time.time() < st['until'])
                if busy:
                    continue
                # Снятая за серию сбоев нода не должна вернуться в пул через минуту —
                # иначе предохранитель бесполезен: она снова наберёт задания и провалит её.
                if NH.is_retired(f'{inst["group"]}/{inst["id"]}'):
                    continue
                cands.append(inst)
            if not cands:
                continue
            # ПРОБЫ ПАРАЛЛЕЛЬНО (03.09). Здесь был последовательный обход, и каждая немая нода
            # съедала до 50 с: при двух-трёх молчащих круг супервизора растягивался на минуты,
            # а прогретая нода всё это время ждала работы. 03.09 из десяти слотов меши делала
            # ОДНА нода, ещё две стояли прогретыми с `done: 0`. Стартовый снимок (`warm_ports`)
            # распараллелили раньше — про добор на ходу я тогда забыл, хотя он важнее: пул
            # наполняется постепенно, и почти каждая нода приходит именно через супервизор.
            with cf.ThreadPoolExecutor(max_workers=min(PROBE_WORKERS, len(cands))) as ex:
                health = list(ex.map(lambda i: probe_health(i['port']), cands))
            # ЗОМБИ СНИМАЕМ ЗДЕСЬ, А НЕ ТОЛЬКО ПРИ ПУСТОМ ПУЛЕ (03.09). Пересадка нод с мёртвым
            # прогревом стояла в `batch_show` в ветках «нет тёплых нод» — то есть срабатывала,
            # лишь когда простаивал ВЕСЬ пул. Пока часть нод работает, ветки не выполняются, и
            # зомби живёт бесконечно: 03.09 одна такая простояла 225 минут при живом пуле, ещё
            # одна 73, и средняя занятость упала с 90% до 56%. Супервизор крутится каждые
            # POLL_S секунд независимо от загрузки — вот его законное место.
            # Зомби — по ошибке прогрева или `phase == 'failed'`, НЕЗАВИСИМО от `warm`: после ребилда
            # воркер перестанет ставить warm=true при провале (план P1-7), и правило «warm и ошибка»
            # перестало бы ловить их вовсе.
            zombies = [(i, warmup_fault(h)
                        or ('прогрев провален (phase=failed)' if h.get('phase') == 'failed' else '')
                        or silent_fault(i['id'], h))
                       for i, h in zip(cands, health)]
            zombies = [(i, w) for i, w in zombies if w]
            # Общая беда — не повод менять машины: заменят такой же (тот же принцип, что в
            # `node_health.fleet_wide` и в пересадке по закачке).
            if zombies and len({w for _, w in zombies}) == 1 and len(zombies) >= max(2, len(cands) * 0.5):
                print(f'  [супервизор] прогрев упал одинаково у {len(zombies)} из {len(cands)} — '
                      f'это наша беда, не машины: {zombies[0][1][:90]}', flush=True)
            else:
                for inst, why in zombies:
                    if not NH.take_cull_slot():
                        break
                    print(f'  [супервизор] нода {inst["id"][:8]} прогрев мёртв — ПЕРЕСАЖИВАЮ: '
                          f'{why[:90]}', flush=True)
                    NH.reallocate(inst['group'], inst['id'], f'warmup: {why[:80]}')
            warm = [bool(h.get('warm')) and not warmup_fault(h) and h.get('phase') != 'failed' for h in health]
            # ЗАМЕР ПРОГРЕВА ПИШЕМ В ЖУРНАЛ (03.09). `warmup_s` живёт только в `/health` живой
            # ноды: машина исчезла — замер пропал. Из-за этого сравнение образов упиралось в
            # n=1 и n=2 на группу, и мой прогноз «прогрев вдвое быстрее» нечем было ни
            # подтвердить, ни опровергнуть. Пишем при подключении — накопится за часы.
            for inst, h, is_warm in zip(cands, health, warm):
                if is_warm and h.get('warmup_s') and inst['id'] not in warm_logged:
                    warm_logged.add(inst['id'])
                    checkpoint({'at': time.time(), 'kind': 'warmup', 'status': 'warmup', 'node': inst['id'][:8],
                              'instance': inst['id'], 'group': inst['group'],
                              'warmup_s': round(float(h['warmup_s']), 1)})
            added = 0
            for inst, is_warm in zip(cands, warm):
                if not is_warm:
                    continue
                print(f'  + нода {inst["id"][:8]} (порт {inst["port"]}) подключена к прогону', flush=True)
                spawn(inst['id'], inst['port'], inst['group'])
                added += 1
            # ПУЛЬС СУПЕРВИЗОРА (03.09). За 2.5 часа одной пачки он не подключил НИ ОДНОЙ ноды,
            # и понять почему было нечем: сообщение печаталось только при удачном подключении.
            # Нода 21998 простояла прогретой 169 минут — она опоздала на стартовый снимок пачки
            # на несколько минут, а супервизор её не подобрал. Молчание — не диагноз, поэтому
            # печатаем состав КАЖДОГО круга: сколько кандидатов было и сколько из них тёплых.
            print(f'  [супервизор] кандидатов {len(cands)}, тёплых {sum(warm)}, '
                  f'подключено {added}, в очереди {js.pending()}', flush=True)
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
    # Цена — по тарифу ГРУППЫ каждой строки (rules/salad-groups.json), а не по одному хардкоду;
    # это НИЖНЯЯ ГРАНИЦА по секундам генерации: прогрев, паузы и простой оплаченных нод сюда
    # не входят. Оплаченную цену считает `tier_compare` по переписи сторожа.
    cost = sum(float((r.get('timings_s') or {}).get('total') or 0) / 3600 * (SG.price(r.get('group') or '') or 0)
               for r in rows)
    print(f'\nзаданий {len(rows)}, готово {len(ok)}, календарь {state.get("wall_s")}с, '
          f'GPU-секунд {round(gpu_s)}, ≈${cost:.3f} (${cost / max(len(ok), 1):.4f}/меш — нижняя граница '
          f'по секундам генерации; оплаченную цену см. tier_compare)')
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
    if not GROUPS:
        sys.exit('нет SALAD_GROUP — задай в ~/scout-scenes/salad.env (через запятую)')
    lim = int(sys.argv[sys.argv.index('--limit') + 1]) if '--limit' in sys.argv else None
    skip = int(sys.argv[sys.argv.index('--skip') + 1]) if '--skip' in sys.argv else 0
    jf = sys.argv[sys.argv.index('--jobs-file') + 1] if '--jobs-file' in sys.argv else None
    sys.exit(run(lim, '--keep-alive' in sys.argv, jf, skip))


if __name__ == '__main__':
    main()
