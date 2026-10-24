#!/usr/bin/env python3
"""Транспорт «очередь Salad» (план mesh-18) — БЕЗ Salad и GPU.

ОБЁРТКА ЗАПУСКА (`queue_entry.sh`; поддельные архив воркера очереди и генерация, сеть не нужна):
  1) SHA-256 не совпал — выход 12, генерация не запускалась;
  2) воркер очереди стартует только ПОСЛЕ /ready генерации, работают оба;
  3) упала генерация — гасится воркер очереди, контейнер выходит; и наоборот;
  4) SIGTERM контейнеру — оба процесса остановлены, выход 143;
  5) генерация умерла до прогрева — выход 14, воркер очереди не запускался;
  6) текст для `command` группы ≤ 1000 знаков (лимит Salad).
СБОРЩИК (`queue_run.run` через `ssh_run.run` с MESH_TRANSPORT=queue; поддельный API очереди):
  7) задание идёт pending → running → succeeded, итог — по ответу воркера, журнал с id задания очереди;
  8) логический отказ воркера при `succeeded` — не успех: повтор нашей политикой, попытки исчерпаны — нерешённое;
  9) `failed` очереди — транспорт: задание кладётся заново, второй раз выходит;
 10) нет готовых машин — код 75, в очередь ничего не положено;
 11) незакрытое задание прошлого раздатчика доопрашивается, второй раз не кладётся;
 12) машины пропали — остаток закрыт, ждущие сняты (DELETE), код 75;
 13) в очереди не больше PER_READY заданий на готовую машину.
ЭТАП 2 (боевой режим):
 14) посредник `queue_proxy.py`: ответ генерации с тем же кодом + `_salad` (машина из окружения Salad), не-JSON — как есть,
     генерация молчит — 502;
 15) обёртка с посредником: он слушает после прогрева, упал — контейнер выходит, SIGTERM гасит все три процесса;
 16) машина из ответа (`_salad`) — в журнал полями `instance`/`machine`, как у SSH (учёт пула видит, кто работал);
 17) `auto`: группа с очередью — очередь, без — SSH, в одном прогоне; SSH машин группы очереди не трогает;
 18) машины очереди пропали при живой SSH-группе — ждущие сняты, задания доделывает SSH, прогон закрыт целиком;
 19) замок конвейера: свободен — держим (отметка жизни для «мёртвой руки»), занят — 'busy';
 20) прогрев без /ready дольше WARM_MAX_S — пересадка; у половины группы — «наша беда», не трогаем;
 21) `disabled` в rules — группу не поднимает никто (`allowed_now`, `--can-start`);
 22) `auto` без групп с очередью — обычный SSH-прогон.

  ~/venvs/scout/bin/python tests_queue.py            # всё без сети
  ~/venvs/scout/bin/python tests_queue.py --real     # + настоящий воркер очереди v0.7.0 с GitHub (скачать, sha, 2 процесса, стоп)
"""
import contextlib
import io
import json
import os
import signal
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import hashlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ.setdefault('SALAD_API_KEY', 'test')
import queue_run as QR    # noqa: E402
import queue_setup as QS  # noqa: E402
import ssh_run as S       # noqa: E402
import tests_pool as TP   # noqa: E402 — те же быстрые таймеры и временные файлы стенда пула

FAILS: list[str] = []
ENTRY = os.path.join(HERE, 'queue_entry.sh')


def check(cond: bool, what: str) -> None:
    print(('  ✓ ' if cond else '  ✗ ') + what)
    if not cond:
        FAILS.append(what)


# ---------- обёртка ----------

APP = r'''
import http.server, os, sys, time
open(os.environ['MARK'] + '/app.pid', 'w').write(str(os.getpid()))
T0 = time.time(); DELAY = float(os.environ.get('READY_AFTER', '1')); DIE = os.environ.get('DIE_EARLY')
if DIE: time.sleep(0.5); sys.exit(3)
class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        ok = time.time() - T0 > DELAY
        if ok and not os.path.exists(os.environ['MARK'] + '/ready.at'):
            open(os.environ['MARK'] + '/ready.at', 'w').write(str(time.time()))
        self.send_response(200 if ok else 503); self.end_headers()
http.server.HTTPServer(('127.0.0.1', int(os.environ['APORT'])), H).serve_forever()
'''
QWORKER = '#!/bin/sh\necho $$ > "$MARK/qw.pid"; date +%s.%N > "$MARK/qw.at"; exec sleep 300\n'


def fake_tgz(d: str) -> tuple[str, str]:
    src = os.path.join(d, 'salad-http-job-queue-worker')
    open(src, 'w').write(QWORKER)
    os.chmod(src, 0o755)
    tgz = os.path.join(d, 'q.tgz')
    with tarfile.open(tgz, 'w:gz') as t:
        t.add(src, arcname='salad-http-job-queue-worker')
    # wget не умеет file:// — архив отдаёт локальный HTTP-сервер стенда
    import functools
    import http.server
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass
    h = functools.partial(Quiet, directory=d)
    srv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), h)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return f'http://127.0.0.1:{srv.server_address[1]}/q.tgz', hashlib.sha256(open(tgz, 'rb').read()).hexdigest()


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    # зомби (вышел, не собран) — не живой
    try:
        return open(f'/proc/{pid}/stat').read().split(') ', 1)[1][0] != 'Z'
    except OSError:
        return False


def in_session(sid: int, comm: str) -> list[int]:
    """Процессы сессии обёртки с таким началом имени — по /proc (без pgrep: только наша сессия, без поиска по строке)."""
    out = []
    for x in os.listdir('/proc'):
        if not x.isdigit():
            continue
        try:
            st = open(f'/proc/{x}/stat').read()
        except OSError:
            continue
        name, rest = st[st.index('(') + 1:st.rindex(')')], st[st.rindex(')') + 2:].split()
        if int(rest[3]) == sid and name.startswith(comm[:15]):
            out.append(int(x))
    return out


def pid_of(mark: str, name: str, wait_s: float = 30) -> int | None:
    t0 = time.time()
    while time.time() - t0 < wait_s:
        try:
            return int(open(os.path.join(mark, name)).read().strip())
        except (OSError, ValueError):
            time.sleep(0.2)
    return None


def start(d: str, url: str | None, sha: str | None, port: int, cmd: list | None = None,
          **env) -> tuple[subprocess.Popen, str]:
    """Обёртка ровно тем текстом, что уйдёт в `command` группы (`QS.entry_command`). `python` — shim на python3:
    в образе он есть (`Dockerfile`), на DEV — нет."""
    mark = tempfile.mkdtemp(dir=d)
    shim = os.path.join(d, 'bin')
    os.makedirs(shim, exist_ok=True)
    if not os.path.exists(os.path.join(shim, 'python')):
        os.symlink(sys.executable, os.path.join(shim, 'python'))
    app = os.path.join(d, 'app.py')
    open(app, 'w').write(APP)
    e = {**os.environ, 'PATH': shim + ':' + os.environ['PATH'], 'MARK': mark, 'APORT': str(port),
         'APP': f'{sys.executable} {app}', 'QW_DIR': os.path.join(mark, 'qw'),
         'READY_URL': f'http://127.0.0.1:{port}/ready', **env}
    if url:
        e['QW_URL'] = url
    if sha:
        e['QW_SHA256'] = sha
    p = subprocess.Popen(cmd or QS.entry_command(ENTRY), env=e, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                         start_new_session=True)
    return p, mark


def finish(p: subprocess.Popen, timeout: float = 30) -> tuple[int | None, str]:
    try:
        out, _ = p.communicate(timeout=timeout)
        return p.returncode, out
    except subprocess.TimeoutExpired:
        os.killpg(p.pid, signal.SIGKILL)
        out, _ = p.communicate()
        return None, out


def wrapper_cases(real: bool) -> None:
    with tempfile.TemporaryDirectory() as d:
        url, sha = fake_tgz(d)
        c = QS.entry_command(ENTRY)
        check(c[:2] == ['bash', '-c'] and len(c[2]) <= 1000 and '#' not in c[2].split('\n')[0],
              f'command группы: bash -c, {len(c[2])} знаков ≤ 1000, комментарии вырезаны')
        check('074a329cf6462e77fc7b72100f59d8a690831456d9420186a834a8f30634c9e4' in c[2] and 'v0.7.0' in c[2],
              'в command закреплены версия v0.7.0 и SHA-256 официального релиза')

        p, mark = start(d, url, '0' * 64, 18301)
        rc, out = finish(p)
        check(rc == 12 and not os.path.exists(os.path.join(mark, 'app.pid')),
              f'SHA-256 не совпал — выход 12, генерация не запускалась (rc={rc})')

        p, mark = start(d, url, sha, 18302, READY_AFTER='2')
        qpid, apid = pid_of(mark, 'qw.pid'), pid_of(mark, 'app.pid')
        ready_at = float(open(os.path.join(mark, 'ready.at')).read()) if os.path.exists(os.path.join(mark, 'ready.at')) else None
        qw_at = float(open(os.path.join(mark, 'qw.at')).read()) if qpid else None
        check(bool(qpid and apid and alive(qpid) and alive(apid)), 'работают оба процесса: генерация и воркер очереди')
        check(bool(ready_at and qw_at and qw_at >= ready_at), 'воркер очереди стартовал после /ready генерации')
        os.kill(apid, signal.SIGKILL)
        rc, out = finish(p)
        time.sleep(0.3)
        check(rc is not None and qpid is not None and not alive(qpid),
              f'генерация упала — воркер очереди погашен, контейнер вышел (rc={rc})')

        p, mark = start(d, url, sha, 18303, READY_AFTER='0')
        qpid, apid = pid_of(mark, 'qw.pid'), pid_of(mark, 'app.pid')
        os.kill(qpid, signal.SIGKILL)
        rc, out = finish(p)
        time.sleep(0.3)
        check(rc is not None and apid is not None and not alive(apid),
              f'воркер очереди упал — генерация погашена, контейнер вышел (rc={rc})')

        p, mark = start(d, url, sha, 18304, READY_AFTER='0')
        qpid, apid = pid_of(mark, 'qw.pid'), pid_of(mark, 'app.pid')
        p.send_signal(signal.SIGTERM)
        rc, out = finish(p)
        time.sleep(0.3)
        check(rc == 143 and qpid and apid and not alive(qpid) and not alive(apid),
              f'SIGTERM контейнеру — оба остановлены, выход 143 (rc={rc})')

        p, mark = start(d, url, sha, 18305, DIE_EARLY='1')
        rc, out = finish(p)
        check(rc == 14 and not os.path.exists(os.path.join(mark, 'qw.pid')),
              f'генерация умерла до прогрева — выход 14, воркер очереди не запускался (rc={rc})')

        # обёртка с посредником (этап 2): тот же текст, что уйдёт в `command` группы на порту 8001
        pcmd = QS.command(QS.PROXY_PORT)
        check(len(pcmd) == 5 and pcmd[3] == 'qw' and len(pcmd[4]) <= 1000 and '#' not in pcmd[4],
              f'command с посредником: 5 элементов, код посредника {len(pcmd[4])} знаков ≤ 1000, без комментариев')
        p, mark = start(d, url, sha, 18307, cmd=pcmd, READY_AFTER='1', PX_PORT='18317',
                        GEN='http://127.0.0.1:18307/generate')
        apid, qpid = pid_of(mark, 'app.pid'), pid_of(mark, 'qw.pid')
        listening = wait_port(18317, 20)
        ppids = [x for x in in_session(p.pid, 'python') if x != apid]
        check(bool(listening and qpid and len(ppids) == 1),
              f'после прогрева работают три процесса: генерация, посредник (порт 18317), воркер очереди (pid {ppids})')
        if ppids:
            os.kill(ppids[0], signal.SIGKILL)
        rc, out = finish(p)
        time.sleep(0.3)
        check(rc is not None and apid and qpid and not alive(apid) and not alive(qpid),
              f'посредник упал — генерация и воркер очереди погашены, контейнер вышел (rc={rc})')

        p, mark = start(d, url, sha, 18308, cmd=pcmd, READY_AFTER='0', PX_PORT='18318',
                        GEN='http://127.0.0.1:18308/generate')
        apid, qpid = pid_of(mark, 'app.pid'), pid_of(mark, 'qw.pid')
        wait_port(18318, 20)
        ppids = [x for x in in_session(p.pid, 'python') if x != apid]
        p.send_signal(signal.SIGTERM)
        rc, out = finish(p)
        time.sleep(0.3)
        check(rc == 143 and apid and qpid and ppids and not any(alive(x) for x in [apid, qpid, *ppids]),
              f'SIGTERM — все три остановлены, выход 143 (rc={rc})')

        if real:
            # настоящий архив с GitHub по ссылке и SHA-256 ИЗ САМОГО command (без подмен QW_URL/QW_SHA256)
            p, mark = start(d, None, None, 18306, READY_AFTER='0', SALAD_LOG_LEVEL='info')
            apid = pid_of(mark, 'app.pid')
            binp = os.path.join(mark, 'qw', 'salad-http-job-queue-worker')
            t0 = time.time()
            while time.time() - t0 < 120 and not (os.path.exists(binp) and os.path.getsize(binp) > 1_000_000):
                time.sleep(0.5)
            time.sleep(15)                     # readiness-цикл обёртки (10 с) + старт воркера очереди
            qpids = in_session(p.pid, 'salad-http-job')
            check(os.path.exists(binp) and os.path.getsize(binp) > 1_000_000,
                  f'настоящий архив v0.7.0 скачан, SHA-256 сошёлся, бинарь {os.path.getsize(binp) if os.path.exists(binp) else 0} байт')
            check(bool(apid and alive(apid) and qpids and all(alive(x) for x in qpids)),
                  f'настоящий воркер очереди работает рядом с генерацией (pid {qpids})')
            p.send_signal(signal.SIGTERM)
            rc, out = finish(p, 30)
            time.sleep(0.5)
            check(rc == 143 and not alive(apid) and not any(alive(x) for x in qpids),
                  f'SIGTERM — оба остановлены, выход 143 (rc={rc})')
            print('    вывод обёртки (хвост):', ' | '.join(out.strip().splitlines()[-4:])[:400])


def wait_port(port: int, wait_s: float) -> bool:
    import socket
    t0 = time.time()
    while time.time() - t0 < wait_s:
        with socket.socket() as so:
            if so.connect_ex(('127.0.0.1', port)) == 0:
                return True
        time.sleep(0.2)
    return False


# ---------- посредник ----------

def proxy_cases() -> None:
    """Код ровно тот, что уйдёт в `command` (`QS.proxy_code`), против поддельной генерации."""
    import http.server
    import urllib.error
    import urllib.request

    class Gen(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            mode = json.loads(self.rfile.read(int(self.headers['Content-Length'])))['mode']
            code, body = {'ok': (200, b'{"status": "ok", "sku": "s1"}'), 'warm': (503, b'{"detail": "warming"}'),
                          'text': (200, b'plain')}[mode]
            self.send_response(code)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    gen = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Gen)
    threading.Thread(target=gen.serve_forever, daemon=True).start()
    env = {**os.environ, 'PX_PORT': '18321', 'GEN': f'http://127.0.0.1:{gen.server_address[1]}/generate',
           'SALAD_INSTANCE_ID': 'inst-1234abcd', 'SALAD_MACHINE_ID': 'mach-77'}
    px = subprocess.Popen([sys.executable, '-c', QS.proxy_code()], env=env)

    def post(mode: str, port: int = 18321) -> tuple[int, bytes]:
        r = urllib.request.Request(f'http://127.0.0.1:{port}/generate', json.dumps({'mode': mode}).encode(),
                                   {'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(r, timeout=10) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    try:
        check(wait_port(18321, 10), 'посредник слушает свой порт')
        c, b = post('ok')
        j = json.loads(b)
        check(c == 200 and j.get('status') == 'ok' and j.get('_salad') == {'instance_id': 'inst-1234abcd',
                                                                            'machine_id': 'mach-77'},
              f'200: ответ генерации + _salad с машиной из окружения Salad ({c}, {j.get("_salad")})')
        c, b = post('warm')
        check(c == 503 and json.loads(b).get('detail') == 'warming', f'503 прогрева — тем же кодом (Salad повторит): {c}')
        c, b = post('text')
        check(c == 200 and b == b'plain', 'ответ не JSON — как есть')
        gen.shutdown()
        gen.server_close()
        c, b = post('ok')
        check(c == 502 and 'proxy:' in json.loads(b).get('error', ''), f'генерация молчит — 502 с причиной ({c})')
    finally:
        px.kill()
        px.wait()


# ---------- сборщик ----------

class FakeSalad:
    """API очереди и инстансов. `plan(sku, n)` → список статусов, которые задание пройдёт на опросах; последний —
    итоговый; для succeeded ответ `output(sku, n)` (n — номер постановки этого sku)."""

    def __init__(self, ready: int = 2):
        self.ready = ready
        self.jobs: dict = {}
        self.posts: list = []
        self.deletes: list = []
        self.max_open = 0
        self.lock = threading.Lock()
        self.plan = lambda sku, n: ['pending', 'running', 'succeeded']
        self.output = lambda sku, n: {'sku': sku, 'status': 'ok', 'timings_s': {'total': 5}}

    def open_n(self) -> int:
        return sum(1 for j in self.jobs.values() if j['status'] in ('pending', 'running'))

    def req(self, method: str, path: str, body=None, timeout=40):
        with self.lock:
            if path.endswith('/instances'):
                return 200, {'instances': [{'state': 'running', 'ready': True}] * self.ready}
            if method == 'POST' and path.endswith('/jobs'):
                sku = body['input'].get('sku')
                n = sum(1 for j in self.jobs.values() if j['sku'] == sku) + 1
                qid = f'id{len(self.jobs)}'
                self.jobs[qid] = {'sku': sku, 'n': n, 'steps': list(self.plan(sku, n)), 'status': 'pending', 'events': []}
                self.posts.append(sku)
                self.max_open = max(self.max_open, self.open_n())
                return 201, {'id': qid, 'status': 'pending'}
            qid = path.rsplit('/', 1)[-1]
            j = self.jobs.get(qid)
            if j is None:
                return 404, {}
            if method == 'DELETE':
                self.deletes.append(qid)
                if j['status'] == 'pending':
                    j['status'] = 'cancelled'
                return 202, {}
            if j['status'] not in ('cancelled',) and j['steps']:
                j['status'] = j['steps'].pop(0)
                if j['status'] == 'running':
                    j['events'].append({'action': 'started'})
            out = {'id': qid, 'status': j['status'], 'events': j['events']}
            if j['status'] == 'succeeded':
                out['output'] = self.output(j['sku'], j['n'])
            return 200, out


def qsetup(tmp: str, fake: FakeSalad) -> None:
    TP.setup(tmp)
    TP.patch([], lambda port, job: {'sku': job['sku'], 'status': 'transport_failed', 'error': 'SSH не должен вызываться'})
    S.GROUPS, S.GROUP = ['g'], 'g'
    S.TRANSPORT = 'queue'
    QR.req = fake.req
    S.SG.queue_of = lambda g: 'q' if g == 'g' else ''
    os.environ['MESH_LOCK'] = os.path.join(tmp, 'batch_show.lock')   # не живой замок конвейера
    QR.POLL_S, QR.READY_POLL_S, QR.STALL_S = 0.05, 0.1, 1.0
    QR.LEDGER = os.path.join(tmp, 'qledger.jsonl')
    if os.path.exists(QR.LEDGER):
        os.remove(QR.LEDGER)
    open(S.PROGRESS, 'w').close()


def run_q(jobs: list) -> tuple[int, dict, list]:
    TP.patch.jobs = jobs
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = S.run(None, True, jobs_file='x')
    st = json.load(open(S.RESULTS, encoding='utf-8')) if os.path.exists(S.RESULTS) else {}
    prog = [json.loads(x) for x in open(S.PROGRESS, encoding='utf-8').read().splitlines() if x.strip()]
    run_q.out = buf.getvalue()
    return code, st, prog


def collector_cases() -> None:
    orig_req, orig_q = QR.req, S.SG.queue_of
    with tempfile.TemporaryDirectory() as tmp:
        try:
            f = FakeSalad()
            qsetup(tmp, f)
            code, st, prog = run_q(TP.jobs(3))
            check(code == 0 and st.get('transport') == 'queue' and st['summary']['unresolved'] == 0
                  and len(f.posts) == 3, f'3 задания через очередь: код {code}, положено {len(f.posts)}, все закрыты')
            check(all(r.get('transport') == 'queue' and r.get('queue_job') and r.get('status') == 'ok'
                      and r.get('queue_status') == 'succeeded' for r in prog) and len(prog) == 3,
                  'журнал: транспорт queue, id задания очереди, статус воркера ok')
            check(S.done_keys() == {(f'sku{i}', 0) for i in range(3)}, 'сделанное — в <снимок>.done')

            f = FakeSalad()
            f.output = lambda sku, n: {'sku': sku, 'status': 'failed', 'error': 'RuntimeError: x'}
            qsetup(tmp, f)
            code, st, prog = run_q(TP.jobs(1))
            check(code == 1 and len(f.posts) == S.MAX_ATTEMPTS and st['summary']['unresolved'] == 1,
                  f'succeeded с логическим отказом — не успех: попыток {len(f.posts)} = MAX_ATTEMPTS, нерешённое, код {code}')

            f = FakeSalad()
            f.plan = lambda sku, n: ['pending', 'running', 'failed'] if n == 1 else ['pending', 'succeeded']
            qsetup(tmp, f)
            code, st, prog = run_q(TP.jobs(1))
            check(code == 0 and len(f.posts) == 2 and prog[0]['error'].startswith('queue/failed')
                  and prog[-1]['status'] == 'ok', 'failed очереди — транспорт: положено заново, второй раз ok')

            f = FakeSalad(ready=0)
            qsetup(tmp, f)
            code, st, prog = run_q(TP.jobs(2))
            check(code == S.EXIT_NO_CAPACITY and not f.posts, f'нет готовых машин — код {code}, в очередь ничего')

            f = FakeSalad()
            qsetup(tmp, f)
            f.jobs['old1'] = {'sku': 'sku0', 'n': 1, 'steps': ['running', 'succeeded'], 'status': 'pending', 'events': []}
            QR.ledger_write({'ev': 'submit', 'qid': 'old1', 'queue': 'q', 'group': 'g', 'sku': 'sku0', 'seed': 0})
            code, st, prog = run_q(TP.jobs(2))
            check(code == 0 and f.posts == ['sku1'] and any(r.get('queue_job') == 'old1' for r in prog),
                  f'незакрытое задание прошлого раздатчика доопрошено, заново положено только {f.posts}')

            f = FakeSalad(ready=1)
            f.plan = lambda sku, n: ['pending'] * 10_000
            qsetup(tmp, f)
            threading.Timer(0.4, lambda: setattr(f, 'ready', 0)).start()
            code, st, prog = run_q(TP.jobs(5))
            check(code == S.EXIT_NO_CAPACITY and f.deletes and all(f.jobs[q]['status'] == 'cancelled' for q in f.deletes),
                  f'машины пропали — остаток закрыт, ждущие сняты ({len(f.deletes)}), код {code}')
            check(f.max_open <= QR.PER_READY, f'в очереди не больше {QR.PER_READY} на готовую машину (было {f.max_open})')
        finally:
            QR.req, S.SG.queue_of = orig_req, orig_q
            S.TRANSPORT = 'auto'


def stage2_cases() -> None:
    orig = (QR.req, S.SG.queue_of, S.SG.info, S.SG.price_halted, S.api, S.instances)
    with tempfile.TemporaryDirectory() as tmp:
        try:
            # 16) машина из ответа посредника — в журнал
            f = FakeSalad()
            f.output = lambda sku, n: {'sku': sku, 'status': 'ok', 'timings_s': {'total': 5},
                                       '_salad': {'instance_id': 'inst-9f8e7d6c', 'machine_id': 'mach-42'}}
            qsetup(tmp, f)
            code, st, prog = run_q(TP.jobs(2))
            check(code == 0 and all(r.get('instance') == 'inst-9f8e7d6c' and r.get('machine') == 'mach-42'
                                    and r.get('node') == 'inst-9f8' for r in prog) and len(prog) == 2
                  and S.MACHINE.get('inst-9f8e7d6c') == 'mach-42',
                  'машина из ответа (_salad) — в журнал: instance, machine, node, как у SSH')
            check(not any('_salad' in r for r in st.get('results') or []), '_salad в итог прогона не попадает')

            # 17) auto: g — очередь, h — SSH, в одном прогоне
            def api_for(path: str) -> dict:
                grp = path.split('/')[1]
                base = 11 if grp == 'g' else 21
                return {'instances': [{'id': f'{grp}{k}' * 4, 'ssh_port': base + k, 'ssh_ip': '10.0.0.1',
                                       'started': True, 'state': 'running', 'machine_id': f'm{grp}{k}'}
                                      for k in range(2)]}
            f = FakeSalad(ready=1)
            f.plan = lambda sku, n: ['pending', 'running', 'running', 'succeeded']
            qsetup(tmp, f)
            used = []

            def ssh_job(port, job):
                used.append(int(port))
                time.sleep(0.3)
                return {'sku': job['sku'], 'status': 'ok', 'timings_s': {'total': 1}}
            TP.patch([], ssh_job)
            S.instances, S.api = TP.ORIG_INSTANCES, api_for
            S.GROUPS, S.GROUP, S.TRANSPORT = ['g', 'h'], 'g', 'auto'
            code, st, prog = run_q(TP.jobs(8))
            tr = {r.get('transport') for r in prog}
            check(code == 0 and st.get('transport') == 'ssh+queue' and st['summary']['unresolved'] == 0
                  and f.posts and used and 'queue' in tr and len(prog) == 8,
                  f'auto: очередь {len(f.posts)} и SSH {len(used)} заданий в одном прогоне, всё закрыто (код {code})')
            check(set(used) <= {21, 22}, f'SSH раздавал только машинам SSH-группы (порты {sorted(set(used))})')

            # 18) машины очереди пропали, SSH жив — ждущие сняты, остаток доделан SSH
            f = FakeSalad(ready=1)
            f.plan = lambda sku, n: ['pending'] * 10_000
            qsetup(tmp, f)
            used.clear()
            TP.patch([], ssh_job)
            S.instances, S.api = TP.ORIG_INSTANCES, api_for
            S.GROUPS, S.GROUP, S.TRANSPORT = ['g', 'h'], 'g', 'auto'
            threading.Timer(0.3, lambda: setattr(f, 'ready', 0)).start()
            code, st, prog = run_q(TP.jobs(6))
            check(code == 0 and st['summary']['unresolved'] == 0 and f.deletes and len(used) == 6
                  and all(f.jobs[q]['status'] == 'cancelled' for q in f.deletes),
                  f'машины очереди пропали — ждущие сняты ({len(f.deletes)}), все 6 доделал SSH (код {code})')

            # 22) auto без групп с очередью — обычный SSH
            f = FakeSalad()
            qsetup(tmp, f)
            used.clear()
            TP.patch([], ssh_job)
            S.instances, S.api = TP.ORIG_INSTANCES, api_for
            S.GROUPS, S.GROUP, S.TRANSPORT = ['h'], 'h', 'auto'
            code, st, prog = run_q(TP.jobs(3))
            check(code == 0 and st.get('transport') == 'ssh' and len(used) == 3 and not f.posts,
                  f'auto без очереди у групп — SSH, как раньше (транспорт {st.get("transport")})')
            S.TRANSPORT = 'queue'
            code, st, prog = run_q(TP.jobs(1))
            check(code == 2 and not f.posts, f'queue без групп с очередью — отказ, код {code}')

            # 19) замок конвейера
            lk = os.path.join(tmp, 'lk')
            r1 = QR.hold_lock(lk)
            r2 = QR.hold_lock(lk)
            if QR._LOCK_FH:
                QR._LOCK_FH.close()
                QR._LOCK_FH = None
            r3 = QR.hold_lock(os.path.join(tmp, 'нет', 'lk'))
            check((r1, r2, r3) == ('held', 'busy', 'none'), f'замок: свободный держим, занятый — busy, нет пути — none: {(r1, r2, r3)}')

            # 20) мёртвый прогрев
            f = FakeSalad()
            qsetup(tmp, f)
            side = QR.Side(S, S.Jobs([]), {'g': 'q'})
            ins = [{'id': f'i{k}' * 4, 'state': 'running', 'ready': k > 0} for k in range(4)]
            side.insts = {'g': ins}
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                side.cull_warmups(1000.0)
                side.cull_warmups(1000.0 + QR.WARM_MAX_S + 1)
            check(TP.culled == ['i0i0i0i0'], f'1 из 4 без /ready дольше WARM_MAX_S — пересажена ({TP.culled})')
            TP.culled.clear()
            side.insts = {'g': [{'id': f'j{k}' * 4, 'state': 'running', 'ready': k > 1} for k in range(4)]}
            with contextlib.redirect_stdout(buf):
                side.cull_warmups(5000.0)
                side.cull_warmups(5000.0 + QR.WARM_MAX_S + 1)
            check(not TP.culled and 'наша беда' in buf.getvalue(), 'у половины группы нет /ready — беда наша, не трогаем')
            side.insts = {'g': [{'id': 'k' * 8, 'state': 'running', 'ready': False}] + ins[1:]}
            with contextlib.redirect_stdout(buf):
                side.cull_warmups(9000.0)
                side.insts = {'g': [{'id': 'k' * 8, 'state': 'running', 'ready': True}] + ins[1:]}
                side.cull_warmups(9000.0 + QR.WARM_MAX_S + 1)
            check(not TP.culled, 'прогрелась вовремя — не трогаем')

            # 21) disabled
            S.SG.price_halted = lambda g: ''
            S.SG.info = lambda g: {'disabled': True}
            check(S.SG.allowed_now('x') is False, 'disabled в rules — allowed_now: нельзя')
            S.SG.info = lambda g: {}
            check(S.SG.allowed_now('x') is True, 'без disabled — можно')
        finally:
            QR.req, S.SG.queue_of, S.SG.info, S.SG.price_halted, S.api, S.instances = orig
            S.TRANSPORT = 'auto'
            S.QUEUE_GROUPS.clear()
    # по живым правилам: боевая группа очереди заведена выключенной
    live = {g: v for g, v in json.load(open(os.path.join(HERE, '..', 'rules', 'salad-groups.json'),
                                            encoding='utf-8')).get('groups', {}).items() if isinstance(v, dict)}
    off = [g for g, v in live.items() if v.get('queue') and not g.endswith('-canary')]
    for g in off:
        r = subprocess.run([sys.executable, os.path.join(HERE, 'salad_groups.py'), '--can-start', g],
                           capture_output=True, text=True)
        check(r.returncode == (1 if live[g].get('disabled') else 0),
              f'{g}: --can-start {r.returncode} ({"выключена" if live[g].get("disabled") else "включена"} в rules) {r.stdout.strip()}')


def main() -> int:
    print('обёртка запуска (queue_entry.sh):')
    wrapper_cases('--real' in sys.argv)
    print('посредник (queue_proxy.py):')
    proxy_cases()
    print('сборщик очереди (queue_run):')
    collector_cases()
    print('этап 2 — боевой режим:')
    stage2_cases()
    print('очередь: ВСЁ ЗЕЛЁНОЕ' if not FAILS else f'очередь: ПРОВАЛ {len(FAILS)}: {FAILS}')
    return 1 if FAILS else 0


if __name__ == '__main__':
    sys.exit(main())
