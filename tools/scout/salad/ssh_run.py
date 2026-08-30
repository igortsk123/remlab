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
import queue
import re
import subprocess
import sys
import threading
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLE = os.path.join(HERE, '..', 'mesh-pilot-sample.json')
RESULTS = os.path.join(HERE, '..', 'mesh-pilot-results.json')
SSH_KEY = os.path.expanduser('~/.ssh/salad_mesh_ed25519')
SSH_HOST = 'root@195.181.163.241'
API = 'https://api.salad.com/api/public'
ORG, PROJECT = 'prodstore', 'dmodel'
GROUP = os.environ.get('SALAD_GROUP', 'mesh-run3')
RATE = 0.16                     # 4090 batch $/ч — сверено по API 28.08
MAX_JOBS = 700   # 481 сетовых + 78 из демо flat215 + повторы seed
_lock = threading.Lock()
# Параллельные сессии к РАЗНЫМ нодам допустимы, если не открывать их залпом: сбой 29.08
# («нет маркера», пустой вывод) случался при одновременном старте. Поэтому: разнос стартов
# по нодам + случайный джиттер перед каждой сессией + ОДИН повтор при пустом ответе.
# Глобальный замок остаётся только на короткие пробы warm_ports.
_ssh_gate = threading.Lock()
import random


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


def warm_ports() -> list[int]:
    """SSH-порты нод, у которых воркер прогрет. Спрашиваем каждую ноду ЛИЧНО через её
    терминал — флагам платформы после этих двух дней веры нет."""
    out = []
    for i in api(f'containers/{GROUP}/instances').get('instances') or []:
        if not i.get('started'):
            continue
        p = i.get('ssh_port')
        r = ssh_text(p, 'python -c "import urllib.request;'
                        'print(urllib.request.urlopen(\'http://127.0.0.1:8000/health\','
                        'timeout=5).read().decode())"', timeout=50)
        m = re.search(r'\{.*\}', r or '')
        if m:
            try:
                if json.loads(m.group(0)).get('warm'):
                    out.append(p)
                    continue
            except json.JSONDecodeError:
                pass
        print(f'  порт {p}: воркер не прогрет или не отвечает')
    return out


def ssh_text(port: int, cmd: str, timeout: int = 60) -> str:
    """Одна команда через интерактивную обёртку. stdin — команды, вывод — как есть."""
    with _ssh_gate:
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
            time.sleep(random.uniform(0.5, 4.0))
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
    """Гасим группу сразу после прогона: тарифицируется состояние, а не работа (ADR-0135)."""
    try:
        req = urllib.request.Request(
            f'{API}/organizations/{ORG}/projects/{PROJECT}/containers/{GROUP}/stop',
            data=b'', method='POST', headers={'Salad-Api-Key': key(), 'User-Agent': 'remlab-mesh/1.0'})
        with urllib.request.urlopen(req, timeout=60) as r:
            r.read()
        print(f'группа {GROUP} остановлена — счёт больше не идёт')
    except Exception as e:  # noqa: BLE001 — это деньги, говорим громко
        print(f'!! ГРУППУ НЕ ОСТАНОВИТЬ ({type(e).__name__}: {str(e)[:120]}) — '
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
    """Очередь лечения: задания перегона из файла (apply_repairs собирает их по вердиктам)."""
    js = json.load(open(path, encoding='utf-8'))
    if len(js) > MAX_JOBS:
        sys.exit(f'ПРЕДОХРАНИТЕЛЬ: {len(js)} > {MAX_JOBS}')
    return _mesh_eligible(js)


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


def run(limit: int | None, keep_alive: bool, jobs_file: str | None = None,
        skip: int = 0) -> None:
    ports = warm_ports()
    print(f'тёплых нод: {len(ports)} {ports}')
    if not ports:
        sys.exit('нет прогретых нод')
    jobs = jobs_from_file(jobs_file) if jobs_file else jobs_from_sample(None)[skip:(skip + limit) if limit else None]
    # --skip вместо растущего --limit: кэш «уже сделано» живёт на приёмнике и умирает при
    # drain — растущий префикс перегенерировал ВСЁ предыдущее каждой пачкой (поймано 30.08:
    # конвейер стал квадратичным, страница стояла).
    print(f'заданий: {len(jobs)} на {len(ports)} нод(ы)')

    q: queue.Queue = queue.Queue()
    for j in jobs:
        q.put(j)
    results, t0 = [], time.time()

    def worker(port: int):
        while True:
            try:
                job = q.get_nowait()
            except queue.Empty:
                return
            r = run_job(port, job)
            with _lock:
                results.append({**r, 'role': job['role'], 'seed': job['seed']})
                t = (r.get('timings_s') or {}).get('total')
                print(f'  [{len(results)}/{len(jobs)}] {job["role"]:14s} '
                      f'{r.get("status","?"):16s} {"" if t is None else str(t)+"с"} '
                      f'{str(r.get("error") or "")[:70]}', flush=True)
            q.task_done()

    ts = [threading.Thread(target=worker, args=(p,), daemon=True) for p in ports]
    for i, t in enumerate(ts):
        t.start()
        time.sleep(6 * min(i, 1) + (0 if i == 0 else 2))   # разнос стартов сессий
    [t.join() for t in ts]

    state = {'transport': 'ssh', 'ports': ports, 'at': time.time(),
             'wall_s': round(time.time() - t0), 'results': results}
    json.dump(state, open(RESULTS, 'w'), ensure_ascii=False, indent=1)
    report(state)
    if not keep_alive:
        stop_group()


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
    if '--report' in sys.argv:
        report()
        return
    lim = int(sys.argv[sys.argv.index('--limit') + 1]) if '--limit' in sys.argv else None
    skip = int(sys.argv[sys.argv.index('--skip') + 1]) if '--skip' in sys.argv else 0
    jf = sys.argv[sys.argv.index('--jobs-file') + 1] if '--jobs-file' in sys.argv else None
    run(lim, '--keep-alive' in sys.argv, jf, skip)


if __name__ == '__main__':
    main()
