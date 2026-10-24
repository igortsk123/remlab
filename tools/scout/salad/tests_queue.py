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


def start(d: str, url: str | None, sha: str | None, port: int, **env) -> tuple[subprocess.Popen, str]:
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
    p = subprocess.Popen(QS.entry_command(ENTRY), env=e, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
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
    QR.SG.queue_of = lambda g: 'q' if g == 'g' else ''
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
    orig_req, orig_q = QR.req, QR.SG.queue_of
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
            QR.req, QR.SG.queue_of = orig_req, orig_q
            S.TRANSPORT = 'ssh'


def main() -> int:
    print('обёртка запуска (queue_entry.sh):')
    wrapper_cases('--real' in sys.argv)
    print('сборщик очереди (queue_run):')
    collector_cases()
    print('очередь: ВСЁ ЗЕЛЁНОЕ' if not FAILS else f'очередь: ПРОВАЛ {len(FAILS)}: {FAILS}')
    return 1 if FAILS else 0


if __name__ == '__main__':
    sys.exit(main())
