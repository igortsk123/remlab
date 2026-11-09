"""Воркер DEV пробы для агентов (agent-trial-01, T-B) против поддельного сервера на 127.0.0.1 — без сети к проду.

Поддельный прод повторяет контракт ручек `app/api/trial/worker/*` (Bearer, ограждение id/attempt/leaseToken, paused →
job null, 409 — аренда потеряна); вместо стенда — поддельный `pipeline.py job` (режим из FAKE_MODE).
"""
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools' / 'floorplan'))
sys.path.insert(1, str(ROOT / 'tools' / 'ops'))
import worker as wk  # noqa: E402

TOKEN = 'T' * 32
JID = 'AbCdEfGhIjKlMnOpQrStUv'

FAKE_CHILD = r'''
import json, os, sys, time
a = sys.argv[1:]
W = a[a.index('--workdir') + 1]
mode = os.environ.get('FAKE_MODE', 'ok')
def put(name, text):
    open(os.path.join(W, name + '.tmp'), 'w').write(text); os.replace(os.path.join(W, name + '.tmp'), os.path.join(W, name))
open(os.path.join(W, 'argv.json'), 'w').write(json.dumps(a))
put('stage', 'raster'); time.sleep(0.25)
put('stage', 'labels'); put('spent', '0.012'); time.sleep(0.25)
if mode == 'slow':
    time.sleep(60)
if mode == 'crash':
    os._exit(9)
if mode in ('no_plan', 'capacity'):
    code = 'no_plan' if mode == 'no_plan' else 'waiting_capacity'
    put('error.json', json.dumps({'code': code, 'retryable': mode == 'capacity', 'detail': 'x'})); sys.exit(3)
put('stage', 'walls'); time.sleep(0.25)
put('result.json', json.dumps({'version': 1, 'units': 'cm', 'fake': True}))
'''


class Prod:
    """Состояние поддельного прода: очередь, файл, ответы по ручкам, журнал запросов."""

    def __init__(self):
        self.jobs, self.reqs = [], []
        self.lease = None
        self.input = b'\x89PNG fake'
        self.input_status = 200
        self.hb_status = 200
        self.result_codes = []
        self.health = 200
        self.lock = threading.Lock()

    def add_job(self, **over):
        j = {'id': JID, 'kind': 'floorplan', 'attempt': 1, 'leaseToken': 'L' * 32, 'leaseUntil': 'x',
             'inputMime': 'image/png', 'inputBytes': len(self.input), 'inputHash': None, 'listingText': 'Lounge 3x4',
             'budgetUsd': 0.1, **over}
        self.jobs.append(j)

    def by(self, path):
        return [b for p, b, _ in self.reqs if p == path]


def make_handler(prod: Prod):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def send(self, code, body=None, raw=None):
            data = raw if raw is not None else json.dumps(body or {}).encode()
            self.send_response(code)
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def fenced(self, b):
            L = prod.lease
            return L and b.get('id') == L['id'] and b.get('attempt') == L['attempt'] and b.get('leaseToken') == L['leaseToken']

        def do_GET(self):
            with prod.lock:
                prod.reqs.append((self.path, None, dict(self.headers)))
            if self.path == '/api/health':
                return self.send(prod.health, {'ok': prod.health == 200})
            if self.headers.get('Authorization') != f'Bearer {TOKEN}':
                return self.send(401, {'ok': False})
            if self.path == f'/api/trial/worker/{JID}/input':
                L = prod.lease
                if not L or self.headers.get('X-Trial-Lease') != L['leaseToken'] or \
                        self.headers.get('X-Trial-Attempt') != str(L['attempt']):
                    return self.send(409, {'error': 'lease_lost'})
                if prod.input_status != 200:
                    return self.send(prod.input_status, {'error': 'x'})
                return self.send(200, raw=prod.input)
            self.send(404, {})

        def do_POST(self):
            n = int(self.headers.get('Content-Length') or 0)
            b = json.loads(self.rfile.read(n) or b'{}')
            with prod.lock:
                prod.reqs.append((self.path, b, dict(self.headers)))
            if self.headers.get('Authorization') != f'Bearer {TOKEN}':
                return self.send(401, {'ok': False})
            if self.path == '/api/trial/worker/claim':
                if b.get('paused') or not prod.jobs:
                    return self.send(200, {'ok': True, 'job': None})
                prod.lease = prod.jobs.pop(0)
                return self.send(200, {'ok': True, 'job': prod.lease})
            if self.path == '/api/trial/worker/heartbeat':
                if prod.hb_status != 200 or not self.fenced(b):
                    return self.send(409, {'error': 'lease_lost'})
                return self.send(200, {'ok': True, 'leaseUntil': 'x'})
            if self.path == '/api/trial/worker/result':
                code = prod.result_codes.pop(0) if prod.result_codes else 200
                if code == 200 and not self.fenced(b):
                    code = 409
                return self.send(code, {'ok': code == 200})
            if self.path == '/api/trial/worker/fail':
                return self.send(200 if self.fenced(b) else 409, {'ok': True, 'status': 'queued'})
            self.send(404, {})
    return H


@pytest.fixture
def prod():
    p = Prod()
    srv = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(p))
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    p.url = f'http://127.0.0.1:{srv.server_address[1]}'
    yield p
    srv.shutdown()


@pytest.fixture
def mk(prod, tmp_path, monkeypatch):
    child = tmp_path / 'fake_pipeline.py'
    child.write_text(FAKE_CHILD)
    mem = tmp_path / 'meminfo'
    mem.write_text('MemTotal:       16000000 kB\nMemAvailable:    8000000 kB\n')

    def make(mode='ok', waiting=0, **over):
        monkeypatch.setenv('FAKE_MODE', mode)
        kw = dict(url=prod.url, token=TOKEN, worker_id='dev-test', base=tmp_path / 'trial', poll_s=0.05,
                  heartbeat_s=0.1, stage_poll_s=0.05, meminfo=str(mem), retry_s=0.01, kill_grace_s=2,
                  pipeline=[sys.executable, str(child)])
        kw.update(over)
        cfg = wk.Cfg(**kw)
        return wk.Worker(cfg, waiting=lambda: waiting)
    make.mem = mem
    return make


def test_happy_path_claim_input_heartbeat_result(prod, mk):
    prod.add_job()
    w = mk()
    w.loop(max_iter=2)
    assert w.done == [(JID, 'done')]
    claims = prod.by('/api/trial/worker/claim')
    assert claims[0] == {'workerId': 'dev-test', 'version': wk.VERSION, 'paused': False}
    hbs = prod.by('/api/trial/worker/heartbeat')
    assert len(hbs) >= 3 and {h['stage'] for h in hbs} <= set(wk.STAGES)
    assert hbs[0]['stage'] == 'raster' and {'labels', 'walls'} & {h['stage'] for h in hbs}
    assert all(h['id'] == JID and h['attempt'] == 1 and h['leaseToken'] == 'L' * 32 for h in hbs)
    res = prod.by('/api/trial/worker/result')
    assert len(res) == 1 and res[0]['result']['fake'] and res[0]['spentUsd'] == pytest.approx(0.012)
    assert prod.by('/api/trial/worker/fail') == []
    # все ручки воркера — с Bearer; файл — с аренды в заголовках, не в адресе
    assert all(h.get('Authorization') == f'Bearer {TOKEN}' for p, _, h in prod.reqs if p.startswith('/api/trial/'))
    wd = next((w.cfg.base / JID).iterdir())
    argv = json.loads((wd / 'argv.json').read_text())
    assert argv[argv.index('--mime') + 1] == 'image/png' and (wd / 'input.png').read_bytes() == prod.input
    assert (wd / 'listing.txt').read_text() == 'Lounge 3x4' and argv[argv.index('--cap-usd') + 1] == '0.1'


def test_heartbeat_right_after_claim_and_on_each_stage_change(prod, mk):
    """Прод метит время шага только по heartbeat (`lib/trial/repo-worker.ts:heartbeat`): таймер 30 с здесь не успел бы
    ни разу — удары должны прийти сразу после claim и на каждую смену шага, по одному на шаг."""
    prod.add_job()
    w = mk(heartbeat_s=30)
    w.loop(max_iter=1)
    assert w.done == [(JID, 'done')]
    assert [h['stage'] for h in prod.by('/api/trial/worker/heartbeat')] == ['raster', 'labels', 'walls']


@pytest.mark.parametrize('mode, code, retryable, after', [
    ('no_plan', 'no_plan', False, None), ('crash', 'pipeline_error', True, None), ('capacity', 'waiting_capacity', True, 30),
])
def test_pipeline_errors_go_to_fail(prod, mk, mode, code, retryable, after):
    prod.add_job()
    w = mk(mode)
    w.loop(max_iter=1)
    f = prod.by('/api/trial/worker/fail')
    assert len(f) == 1 and f[0]['code'] == code and f[0]['retryable'] is retryable
    assert f[0].get('retryAfterSec') == after and f[0]['spentUsd'] == pytest.approx(0.012)
    assert prod.by('/api/trial/worker/result') == []
    assert w.streak == (1 if mode == 'crash' else 0)          # вина файла и «DEV занят» — не сбой DEV


def test_lease_lost_kills_pipeline_and_reports_nothing(prod, mk):
    prod.add_job()
    w = mk('slow')
    t0 = time.time()
    threading.Timer(0.6, lambda: setattr(prod, 'hb_status', 409)).start()
    w.loop(max_iter=1)
    assert time.time() - t0 < 10
    assert w.done == [(JID, 'lost')]
    assert prod.by('/api/trial/worker/result') == [] and prod.by('/api/trial/worker/fail') == []


def test_timeout_kills_and_fails(prod, mk):
    prod.add_job()
    w = mk('slow', job_timeout_s=1.0)
    w.loop(max_iter=1)
    f = prod.by('/api/trial/worker/fail')
    assert [x['code'] for x in f] == ['timeout'] and f[0]['retryable'] is False


def test_input_lease_lost_and_deleted(prod, mk):
    # 409: аренда сменилась до скачивания — молча отпустить, ничего не слать
    prod.add_job()
    prod.input_status = 409
    w = mk()
    w.loop(max_iter=1)
    assert prod.by('/api/trial/worker/result') == [] and prod.by('/api/trial/worker/fail') == [] and w.done == []
    # 410: файл уже удалён (истёк срок) — fail internal без повтора
    prod.reqs.clear()
    prod.input_status = 410
    prod.add_job()
    w.loop(max_iter=1)
    f = prod.by('/api/trial/worker/fail')
    assert len(f) == 1 and f[0]['code'] == 'internal' and f[0]['retryable'] is False


def test_result_rejected_and_retried(prod, mk):
    prod.add_job()
    prod.result_codes = [503, 200]                 # первый ответ потерян/сбой — повтор того же тела
    w = mk()
    w.loop(max_iter=1)
    assert len(prod.by('/api/trial/worker/result')) == 2 and w.done == [(JID, 'done')]
    prod.reqs.clear()
    prod.add_job()
    prod.result_codes = [422]
    w.loop(max_iter=1)
    f = prod.by('/api/trial/worker/fail')
    assert [x['code'] for x in f] == ['pipeline_error'] and f[0]['retryable'] is False


def test_breaker_memory_from_meminfo(prod, mk):
    mk.mem.write_text('MemTotal:       16000000 kB\nMemAvailable:    2000000 kB\n')   # 1,9 ГБ < 3
    prod.add_job()
    w = mk()
    w.loop(max_iter=2)
    claims = prod.by('/api/trial/worker/claim')
    assert len(claims) == 2 and all(c['paused'] for c in claims)
    assert prod.jobs and w.done == []                # задание не тронуто, но «жив» отмечен
    assert w.breaker().startswith('memory')


def test_breaker_heavy_queue_and_health(prod, mk):
    w = mk(waiting=2)
    assert w.breaker() == 'heavy_queue 2 waiting'
    w = mk()
    prod.health = 503
    assert w.breaker() == 'prod_health'
    prod.health = 200
    assert w.breaker() == 'prod_health'              # кэш проверки здоровья — 30 с
    w.health = (0.0, False)
    assert w.breaker() is None


def test_breaker_after_three_dev_failures(prod, mk):
    w = mk('crash')
    for _ in range(3):
        prod.add_job()
        w.loop(max_iter=1)
    assert len(prod.by('/api/trial/worker/fail')) == 3
    assert w.breaker().startswith('fail_streak') and w.pause_until > time.time() + 500
    prod.add_job()
    w.loop(max_iter=1)
    assert prod.by('/api/trial/worker/claim')[-1]['paused'] is True and prod.jobs


def test_bad_job_id_is_not_used_as_path(prod, mk):
    prod.add_job(id='../../etc')
    w = mk()
    w.loop(max_iter=1)
    assert not (w.cfg.base.parent / 'etc').exists()
    assert w.done and w.done[0][1].startswith('fail:internal')


def test_janitor_removes_old_job_dirs_only(mk, tmp_path):
    w = mk()
    base = w.cfg.base
    old, fresh, other = base / ('O' * 22), base / ('F' * 22), base / 'notes'
    for d in (old / 'a1', fresh / 'a1', other, base / 'vlm-cache' / 'oldhash', base / 'vlm-cache' / 'newhash'):
        d.mkdir(parents=True)
        (d / 'f').write_text('x')
    (base / ('S' * 22)).symlink_to(tmp_path)
    t = time.time() - 30 * 3600
    for p in (old, old / 'a1', old / 'a1' / 'f'):
        os.utime(p, (t, t))
    t2 = time.time() - 40 * 86400
    for p in (base / 'vlm-cache' / 'oldhash', base / 'vlm-cache' / 'oldhash' / 'f'):
        os.utime(p, (t2, t2))
    gone = w.janitor()
    assert sorted(Path(g).name for g in gone) == sorted(['O' * 22, 'oldhash'])
    assert fresh.exists() and other.exists() and (base / ('S' * 22)).is_symlink() and (base / 'vlm-cache' / 'newhash').exists()
    assert w.janitor() == []                         # не чаще раза в час


def test_heavy_waiting_parses_status(monkeypatch):
    import heavy_slot as hs
    monkeypatch.setattr(hs, 'status', lambda out: out.write('ДЕРЖИТ: x\nЖДУТ: 3 (по порядку прихода)\n'))
    assert wk.heavy_waiting() == 3

    def boom(out):
        raise FileNotFoundError('wait')
    monkeypatch.setattr(hs, 'status', boom)
    assert wk.heavy_waiting() == 0


def test_main_without_token_exits(monkeypatch):
    monkeypatch.delenv('TRIAL_WORKER_TOKEN', raising=False)
    assert wk.main([]) == 2


def test_cfg_from_env():
    c = wk.Cfg.from_env({'TRIAL_WORKER_TOKEN': 'x', 'TRIAL_API_URL': 'https://example.test/', 'TRIAL_JOB_TIMEOUT_S': '60',
                         'TRIAL_WORK_DIR': '/tmp/t'})
    assert (c.url, c.token, c.job_timeout_s, str(c.base), str(c.vlm_root)) == \
        ('https://example.test', 'x', 60.0, '/tmp/t', '/tmp/t/vlm-cache')
    assert c.worker_id.startswith('dev-') and c.mem_min_gb == 3.0 and c.heartbeat_s == 10.0
