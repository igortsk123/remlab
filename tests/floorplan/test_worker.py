"""Воркер DEV пробы для агентов (agent-trial-01, T-B) против поддельного сервера на 127.0.0.1 — без сети к проду.

Поддельный прод повторяет контракт ручек `app/api/trial/worker/*` (Bearer, ограждение id/attempt/leaseToken, paused →
job null, 409 — аренда потеряна); вместо стенда — поддельный `pipeline.py job` (режим из FAKE_MODE).
"""
import hashlib
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
if mode == 'killed':                     # OOM / earlyoom: напечатал (без flush) и убит сигналом — строка должна остаться в журнале
    print('разбор: лист 1 из 1, VLM 4/9'); os.kill(os.getpid(), 9)
if mode in ('no_plan', 'capacity'):
    code = 'no_plan' if mode == 'no_plan' else 'waiting_capacity'
    put('error.json', json.dumps({'code': code, 'retryable': mode == 'capacity', 'detail': 'x'})); sys.exit(3)
if '--cache-only' in a:                  # план заново с текстом агента (Р2-текст): «лёг», если в тексте «A на B»
    if os.environ.get('FAKE_CACHE') == 'gone':
        put('error.json', json.dumps({'code': 'source_gone', 'retryable': False, 'detail': 'vlm cache missing'})); sys.exit(3)
    if os.environ.get('FAKE_NAMES'):     # подписи плана с этими именами; текст — настоящим разбором `listing` (как bench.blind_gold)
        sys.path.insert(0, os.environ['FAKE_FP'])
        import listing
        names = os.environ['FAKE_NAMES'].split('|')
        labs, _ = listing.match([{'name': n, 'dims': None} for n in names],
                                listing.parse_listing(open(a[a.index('--listing-file') + 1], encoding='utf-8').read()))
        rooms = []
        for i, lb in enumerate(labs):
            r = {'id': f'p0-r{i}', 'name': lb['name'], 'kind': 'kitchen', 'flags': []}
            if lb.get('dims_src') == 'text':
                r['dims'] = {'w': round(lb['dims'][0] * 100, 1), 'd': round(lb['dims'][1] * 100, 1), 'src': 'listing'}
            rooms.append(r)
        n = sum(1 for r in rooms if 'dims' in r)
        put('result.json', json.dumps({'version': 1, 'units': 'cm', 'fake': True, 'reread': True,
                                       'scale': {'status': 'listing' if n else 'not_verified'}, 'panels': [{'id': 'p0', 'rooms': rooms}]}))
        sys.exit(0)
    ok = ' на ' in open(a[a.index('--listing-file') + 1], encoding='utf-8').read()
    keep = os.environ.get('FAKE_KEEP_FLAG', '').split(',')         # эти комнаты и с текстом ждут проверки
    rooms = [{'id': 'r1', 'kind': 'living'}, {'id': 'k1', 'kind': 'kitchen'}, {'id': 'b1', 'kind': 'bedroom'}]
    for r in rooms:
        r['flags'] = ['dims_mismatch'] if r['id'] in keep or (not ok and r['id'] == 'r1') else []
    if ok:
        rooms[0]['dims'] = {'w': 420, 'd': 380, 'src': 'listing'}
    put('result.json', json.dumps({'version': 1, 'units': 'cm', 'fake': True, 'reread': True,
                                   'scale': {'status': 'listing' if ok else 'not_verified'}, 'panels': [{'id': 'p0', 'rooms': rooms}]}))
    sys.exit(0)
put('stage', 'walls'); time.sleep(0.25)
flagged = os.environ.get('FAKE_SIZE_FLAG', '').split(',')        # «размер не сошёлся» у этих комнат
rooms = [{'id': 'r1', 'kind': 'living'}, {'id': 'k1', 'kind': 'kitchen'}]
if os.environ.get('FAKE_BEDROOMS_IN_PLAN', '1') == '1':
    rooms.append({'id': 'b1', 'kind': 'bedroom'})
if os.environ.get('FAKE_NO_LIVING') == '1':                       # гостиной в плане нет (T-20261110-07)
    rooms = [r for r in rooms if r['kind'] != 'living']
for r in rooms:
    r['flags'] = ['dims_mismatch'] if r['id'] in flagged else []
put('result.json', json.dumps({'version': 1, 'units': 'cm', 'fake': True, 'panels': [{'id': 'p0', 'rooms': rooms}]}))
'''

# ── поддельные стадии конвейера (`conveyor.py`): тот же интерфейс командной строки, что у настоящих ──
FAKE_BUNDLE = r'''
import json, os, sys
a = sys.argv[1:]
def opt(n):
    if n in a:
        i = a.index(n); v = a[i + 1]; del a[i:i + 2]; return v
scene, parts, out = opt('--scene'), opt('--parts'), opt('--out')
release = (opt('--release') or '').split(',')
jid, res = a
result = json.load(open(res))
mode = os.environ.get('FAKE_BUNDLE', 'ok')
sc = json.load(open(scene)) if scene else None
if mode == 'refuse' or (mode == 'leak' and sc and sc['status'] == 'ok'):
    print('сборка: отказ')
    print(json.dumps({'refusal': 'shop_leak' if mode == 'leak' else 'bad_result', 'detail': 'x'})); sys.exit(2)
got = {e['src_id']: e for e in (json.load(open(parts)) if parts else {}).get('apartment_rooms') or []}
rooms, n, pages = [], {}, []
for p in result['panels']:
    pages.append({'id': p['id'], 'rooms': []})
    for r in p['rooms']:
        n[r['kind']] = n.get(r['kind'], 0) + 1
        rid = 'living' if r['kind'] == 'living' and n['living'] == 1 else f"{r['kind']}-{n[r['kind']]}"
        pages[-1]['rooms'].append({'id': rid, 'src_id': r['id']})
        consent = rid in release or 'approx_consent' in (r.get('flags') or [])
        if r['kind'] in ('living', 'bedroom') and 'dims_mismatch' in (r.get('flags') or []) and not consent \
                and not (r['kind'] == 'living' and sc and sc['status'] == 'ok'):
            st, code = 'awaiting_check', 'dims_mismatch'
        elif r['kind'] == 'living':
            if sc is None:
                st, code = 'pending', None
            elif sc['status'] in ('ok', 'partial'):
                st, code = 'ready', None
            else:
                st, code = 'refused', (sc.get('refusal') or {}).get('code') or sc['status']
        elif r['kind'] == 'bedroom':
            e = got.get(r['id'])
            st, code = (e['furniture_state'], e.get('furniture_code')) if e else ('pending', None)
        else:
            st, code = 'not_furnished', None
        rooms.append({'id': rid, 'kind': r['kind'], 'furniture_state': st, 'furniture_code': code})
data = {'apartment_rooms': rooms, 'pad': 'x' * int(os.environ.get('FAKE_BUNDLE_PAD', '0')),
        'trial': {'job_id': jid, 'complete': all(x['furniture_state'] != 'pending' for x in rooms), 'panels': pages}}
json.dump(data, open(out, 'w'))
print(json.dumps({'ok': True}))
'''

FAKE_LIVING = r'''
import json, os, sys, time
jid = sys.argv[1]
mode = os.environ.get('FAKE_LIVING', 'ok')
d = os.path.join(os.environ['TRIAL_SCENES_ROOT'], jid)
os.makedirs(d, exist_ok=True)
if mode == 'slow':
    time.sleep(60)
if mode == 'crash':
    os._exit(9)
if mode == 'stale':                      # упала тихо: scene.json не обновлён (лежит от прошлого раза)
    sys.exit(0)
json.dump({'trial_id': jid, 'status': mode}, open(os.path.join(d, 'scene.json'), 'w'))
sys.exit({'ok': 0, 'partial': 3}.get(mode, 2))
'''

FAKE_BEDROOMS = r'''
import json, os, sys
jid, res, out = sys.argv[1:]
if os.environ.get('FAKE_BEDROOMS') == 'crash':
    os._exit(9)
r = json.load(open(res))
rooms = [{'id': f'bedroom-{i}', 'panel': p['id'], 'src_id': x['id'], 'furniture_state': 'ready'}
         for i, (p, x) in enumerate(((p, x) for p in r['panels'] for x in p['rooms'] if x['kind'] == 'bedroom'), 1)]
json.dump({'rooms_geo': {}, 'apartment_rooms': rooms, 'variants': []}, open(out, 'w'))
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
        self.bundle_codes = []
        self.bundles = []                       # принятые версии: {'sha', 'data'} — как манифест `trial_jobs.bundle_version/hash`
        self.rebuilds = []                      # очередь пересборок «Обустроить» (claim отдаёт после заданий)
        self.rebuild_codes = []                 # ответы …/rebuild/publish по очереди: (код, error)
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
            if self.path.startswith('/api/trial/worker/rebuild/') and self.path.endswith('/input'):   # = rebuild/[id]/input
                L = prod.lease
                if not L or self.path != f'/api/trial/worker/rebuild/{L["id"]}/input' or L.get('kind') != 'listing' or \
                        self.headers.get('X-Trial-Lease') != L['leaseToken'] or self.headers.get('X-Trial-Attempt') != str(L['attempt']):
                    return self.send(409, {'error': 'lease_lost'})
                if prod.input_status != 200:
                    return self.send(prod.input_status, {'error': 'source_gone'})
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
                if not b.get('paused') and not prod.jobs and prod.rebuilds and b.get('rebuilds') and \
                        (prod.rebuilds[0].get('kind') != 'listing' or b.get('listing')):
                    prod.lease = prod.rebuilds.pop(0)
                    return self.send(200, {'ok': True, 'job': None, 'rebuild': prod.lease})
                if b.get('paused') or not prod.jobs:
                    return self.send(200, {'ok': True, 'job': None})
                prod.lease = prod.jobs.pop(0)
                return self.send(200, {'ok': True, 'job': prod.lease})
            if self.path == '/api/trial/worker/rebuild/publish':   # = app/api/trial/worker/rebuild/publish/route.ts
                if not self.fenced(b) or b.get('jobId') != prod.lease.get('jobId'):
                    return self.send(409, {'error': 'lease_lost'})
                raw = b['bundle'].encode()
                if hashlib.sha256(raw).hexdigest() != b['sha256']:
                    return self.send(422, {'error': 'hash_mismatch'})
                if prod.rebuild_codes:
                    code, err = prod.rebuild_codes.pop(0)
                    return self.send(code, {'error': err})
                if 'result' in b and prod.lease.get('kind') != 'listing':
                    return self.send(422, {'error': 'result_unexpected'})
                with prod.lock:
                    prod.bundles.append({'sha': b['sha256'], 'data': json.loads(raw), 'result': b.get('result')})
                    return self.send(200, {'ok': True, 'version': len(prod.bundles), 'repeated': False})
            if self.path in ('/api/trial/worker/rebuild/heartbeat', '/api/trial/worker/rebuild/fail'):
                if prod.hb_status != 200 or not self.fenced(b):
                    return self.send(409, {'error': 'lease_lost'})
                return self.send(200, {'ok': True, 'leaseUntil': 'x', 'status': 'failed'})
            if self.path == '/api/trial/worker/heartbeat':
                if prod.hb_status != 200 or not self.fenced(b):
                    return self.send(409, {'error': 'lease_lost'})
                return self.send(200, {'ok': True, 'leaseUntil': 'x'})
            if self.path == '/api/trial/worker/result':
                code = prod.result_codes.pop(0) if prod.result_codes else 200
                if code == 200 and not self.fenced(b):
                    code = 409
                return self.send(code, {'ok': code == 200})
            if self.path == '/api/trial/worker/bundle':          # = app/api/trial/worker/bundle/route.ts (без проверки формы)
                if not self.fenced(b):
                    return self.send(409, {'error': 'lease_lost'})
                raw = b['bundle'].encode()
                if len(raw) > 8 * 1024 * 1024:
                    return self.send(413, {'error': 'too_large'})
                if hashlib.sha256(raw).hexdigest() != b['sha256']:
                    return self.send(422, {'error': 'hash_mismatch'})
                if prod.bundle_codes:
                    code = prod.bundle_codes.pop(0)
                    return self.send(code, {'error': 'x'})
                with prod.lock:
                    if prod.bundles and prod.bundles[-1]['sha'] == b['sha256']:
                        return self.send(200, {'ok': True, 'version': len(prod.bundles), 'repeated': True})
                    prod.bundles.append({'sha': b['sha256'], 'data': json.loads(raw)})
                    return self.send(200, {'ok': True, 'version': len(prod.bundles), 'repeated': False})
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

    stages = {}
    for name, src in (('bundle', FAKE_BUNDLE), ('living', FAKE_LIVING), ('bedrooms', FAKE_BEDROOMS)):
        p = tmp_path / f'fake_{name}.py'
        p.write_text(src)
        stages[name] = [sys.executable, str(p)]

    def make(mode='ok', waiting=0, furnish=False, bedroom_stage=True, **over):
        monkeypatch.setenv('FAKE_MODE', mode)
        kw = dict(url=prod.url, token=TOKEN, worker_id='dev-test', base=tmp_path / 'trial', poll_s=0.05,
                  heartbeat_s=0.1, stage_poll_s=0.05, meminfo=str(mem), retry_s=0.01, kill_grace_s=2,
                  pipeline=[sys.executable, str(child)], furnish=furnish, scenes_root=tmp_path / 'scenes',
                  stage_cmds={**stages, 'bedrooms': stages['bedrooms'] if bedroom_stage else None})
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


def test_pipeline_killed_by_signal_reason_has_signal_and_log_tail(prod, mk, monkeypatch):
    """T-20261110-05: разбор убит сигналом без `error.json` — в причине сбоя имя сигнала и последние строки журнала; вывод без буфера
    (10.11 `pipeline.log` был пуст: строки остались в буфере убитого процесса)."""
    monkeypatch.delenv('PYTHONUNBUFFERED', raising=False)      # без буфера — забота воркера, не окружения
    prod.add_job()
    w = mk('killed')
    w.loop(max_iter=1)
    f = prod.by('/api/trial/worker/fail')
    assert len(f) == 1 and f[0]['code'] == 'pipeline_error' and f[0]['retryable'] is True
    assert f[0]['detail'] == 'pipeline rc=-9 (SIGKILL) · разбор: лист 1 из 1, VLM 4/9'
    prod.reqs.clear()
    prod.add_job(attempt=2)                                    # своя папка попытки: журнал первой сюда не дописывается
    w = mk('crash')
    w.loop(max_iter=1)
    assert prod.by('/api/trial/worker/fail')[0]['detail'] == 'pipeline rc=9 · журнал пуст'


def test_child_failure_signal_names_and_tail(tmp_path):
    log = tmp_path / 'x.log'
    assert wk.child_failure('living', -15, log) == 'living rc=-15 (SIGTERM) · журнал пуст'
    log.write_text('\n'.join(f'строка {i}' for i in range(20)) + '\n\n')
    got = wk.child_failure('bedrooms', 137, log, lines=3)
    assert got == 'bedrooms rc=137 (128+SIGKILL) · строка 17 | строка 18 | строка 19'
    log.write_text('я' * 5000)
    got = wk.child_failure('pipeline', 1, log, max_chars=200)
    assert len(got) == 200 and got.startswith('pipeline rc=1 · …я')


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


def test_heavy_waiting_counts_only_trial_class(monkeypatch):
    """T-20261110-29: предохранитель считает только ждущих класса пробы и выше — наши обычные прогоны задание не держат."""
    import heavy_slot as hs
    asked = []
    monkeypatch.setattr(hs, 'waiting', lambda p: asked.append(p) or 1)
    assert wk.heavy_waiting() == 1 and asked == [wk.conveyor.SLOT_PRIO_TRIAL]

    def boom(p):
        raise FileNotFoundError('wait')
    monkeypatch.setattr(hs, 'waiting', boom)
    assert wk.heavy_waiting() == 0
    # очередь старой версии (без `waiting`) — как раньше, по строке «ЖДУТ: N»
    monkeypatch.delattr(hs, 'waiting')
    monkeypatch.setattr(hs, 'status', lambda out: out.write('ДЕРЖИТ: x\nЖДУТ: 3 (по порядку прихода)\n'))
    assert wk.heavy_waiting() == 3


def test_main_without_token_exits(monkeypatch):
    monkeypatch.delenv('TRIAL_WORKER_TOKEN', raising=False)
    assert wk.main([]) == 2


def test_cfg_from_env():
    c = wk.Cfg.from_env({'TRIAL_WORKER_TOKEN': 'x', 'TRIAL_API_URL': 'https://example.test/', 'TRIAL_JOB_TIMEOUT_S': '60',
                         'TRIAL_WORK_DIR': '/tmp/t'})
    assert (c.url, c.token, c.job_timeout_s, str(c.base), str(c.vlm_root)) == \
        ('https://example.test', 'x', 60.0, '/tmp/t', '/tmp/t/vlm-cache')
    assert c.worker_id.startswith('dev-') and c.mem_min_gb == 3.0 and c.heartbeat_s == 10.0
    assert c.furnish is True and c.living_timeout_s == 1800.0 and c.bundle_max_bytes == 8 * 1024 * 1024
    c = wk.Cfg.from_env({'TRIAL_FURNISH': '0', 'TRIAL_SCENES_ROOT': '/tmp/s', 'TRIAL_LIVING_TIMEOUT_S': '30'})
    assert c.furnish is False and str(c.scenes_root) == '/tmp/s' and c.living_timeout_s == 30.0


# ───────────────────────── конвейер после стен (conveyor.py, T-20261109-23) ─────────────────────────

def _states(prod):
    """По каждой принятой версии: {комната: состояние[:код]} и `complete`."""
    out = []
    for b in prod.bundles:
        rooms = {r['id']: r['furniture_state'] + (f":{r['furniture_code']}" if r.get('furniture_code') else '')
                 for r in b['data']['apartment_rooms']}
        out.append((rooms, b['data']['trial']['complete']))
    return out


def _order(prod):
    return [p.rsplit('/', 1)[-1] for p, _, _ in prod.reqs if p in ('/api/trial/worker/bundle', '/api/trial/worker/result',
                                                                       '/api/trial/worker/fail')]


def test_conveyor_versions_in_order_then_done(prod, mk):
    """Стены → версия 1 (всё pending), гостиная → версия 2, спальни → версия 3 (complete), и только потом `result`."""
    prod.add_job()
    w = mk(furnish=True)
    w.loop(max_iter=1)
    assert w.done == [(JID, 'done')]
    assert _states(prod) == [
        ({'living': 'pending', 'kitchen-1': 'not_furnished', 'bedroom-1': 'pending'}, False),
        ({'living': 'ready', 'kitchen-1': 'not_furnished', 'bedroom-1': 'pending'}, False),
        ({'living': 'ready', 'kitchen-1': 'not_furnished', 'bedroom-1': 'ready'}, True)]
    assert _order(prod) == ['bundle', 'bundle', 'bundle', 'result']
    sent = prod.by('/api/trial/worker/bundle')
    assert all(s['id'] == JID and s['attempt'] == 1 and s['leaseToken'] == 'L' * 32 for s in sent)
    assert all(hashlib.sha256(s['bundle'].encode()).hexdigest() == s['sha256'] for s in sent)
    # стадии живут, пока идёт heartbeat: аренда продлевается и во время мебели
    assert prod.by('/api/trial/worker/fail') == []


def test_conveyor_living_failure_is_room_refusal_and_job_done(prod, mk, monkeypatch):
    for mode, code, over in (('crash', 'stage_failed', {}), ('slow', 'stage_timeout', {'living_timeout_s': 1.0})):
        prod.reqs.clear()
        prod.bundles.clear()
        monkeypatch.setenv('FAKE_LIVING', mode)
        prod.add_job(attempt=len(prod.reqs) + 1)
        w = mk(furnish=True, base=mk.mem.parent / f'trial-{mode}', **over)
        w.loop(max_iter=1)
        assert w.done == [(JID, 'done')], mode
        st = _states(prod)
        assert st[1][0]['living'] == f'refused:{code}' and st[-1][1] is True, (mode, st)
        assert _order(prod)[-1] == 'result'


def test_conveyor_stale_scene_is_not_taken_for_fresh(prod, mk, monkeypatch, tmp_path):
    """Гостиная вышла без новой сцены — старый `scene.json` (прошлая попытка) за итог не принимается."""
    d = tmp_path / 'scenes' / JID
    d.mkdir(parents=True)
    (d / 'scene.json').write_text(json.dumps({'trial_id': JID, 'status': 'ok'}))
    old = time.time() - 3600
    os.utime(d / 'scene.json', (old, old))
    monkeypatch.setenv('FAKE_LIVING', 'stale')
    prod.add_job()
    w = mk(furnish=True)
    w.loop(max_iter=1)
    assert _states(prod)[1][0]['living'] == 'refused:stage_failed' and w.done == [(JID, 'done')]


def test_conveyor_honest_living_outcome_kept(prod, mk, monkeypatch):
    monkeypatch.setenv('FAKE_LIVING', 'no_products')
    prod.add_job()
    w = mk(furnish=True)
    w.loop(max_iter=1)
    assert _states(prod)[1][0]['living'] == 'refused:no_products' and w.done == [(JID, 'done')]


def test_conveyor_without_bedroom_module_bedrooms_pending_then_refused(prod, mk):
    """Ветка спален не влита: в версии 2 спальня ещё `pending`, в последней — отказ `stage_unavailable`, задание — `done`."""
    prod.add_job()
    w = mk(furnish=True, bedroom_stage=False)
    w.loop(max_iter=1)
    st = _states(prod)
    assert st[1][0]['bedroom-1'] == 'pending' and st[2][0]['bedroom-1'] == 'refused:stage_unavailable' and st[2][1] is True
    assert w.done == [(JID, 'done')]


def test_conveyor_bedroom_crash_refused(prod, mk, monkeypatch):
    monkeypatch.setenv('FAKE_BEDROOMS', 'crash')
    prod.add_job()
    w = mk(furnish=True)
    w.loop(max_iter=1)
    assert _states(prod)[-1] == ({'living': 'ready', 'kitchen-1': 'not_furnished', 'bedroom-1': 'refused:stage_failed'}, True)


def test_conveyor_builder_refusal_of_stage_piece_becomes_room_refusal(prod, mk, monkeypatch):
    """Сборщик не принял сцену (утечка магазина) — сцена не публикуется, гостиная получает отказ этим кодом."""
    monkeypatch.setenv('FAKE_BUNDLE', 'leak')
    prod.add_job()
    w = mk(furnish=True)
    w.loop(max_iter=1)
    st = _states(prod)
    assert st[1][0]['living'] == 'refused:shop_leak' and st[-1][1] is True and w.done == [(JID, 'done')]


def test_conveyor_repeat_does_not_duplicate_versions(prod, mk, monkeypatch):
    """Одинаковая версия не шлётся дважды: без спален в плане версия 3 = версия 2 — её нет; перезапуск (новая попытка того же
    задания) не откатывает страницу к пустой версии 1 и не плодит версий."""
    monkeypatch.setenv('FAKE_BEDROOMS_IN_PLAN', '0')
    prod.add_job()
    w = mk(furnish=True)
    w.loop(max_iter=1)
    assert len(prod.bundles) == 2 and len(prod.by('/api/trial/worker/bundle')) == 2
    prod.add_job(attempt=2, leaseToken='M' * 32)
    w.loop(max_iter=1)
    assert len(prod.bundles) == 2 and len(prod.by('/api/trial/worker/bundle')) == 2
    assert w.done == [(JID, 'done'), (JID, 'done')] and len(prod.by('/api/trial/worker/result')) == 2


def test_conveyor_lease_lost_during_living_stops_everything(prod, mk, monkeypatch):
    monkeypatch.setenv('FAKE_LIVING', 'slow')
    prod.add_job()
    w = mk(furnish=True)
    t0 = time.time()
    threading.Timer(2.0, lambda: setattr(prod, 'hb_status', 409)).start()
    w.loop(max_iter=1)
    assert time.time() - t0 < 20 and w.done == [(JID, 'lost')]
    assert len(prod.bundles) == 1 and prod.by('/api/trial/worker/result') == [] and prod.by('/api/trial/worker/fail') == []


def test_conveyor_no_version_without_walls_bundle_still_done(prod, mk, monkeypatch):
    """Версию 1 не собрать (отказ сборщика) или она больше потолка — мебель не подбираем, задание закрываем как раньше."""
    monkeypatch.setenv('FAKE_BUNDLE', 'refuse')
    prod.add_job()
    w = mk(furnish=True)
    w.loop(max_iter=1)
    assert prod.bundles == [] and _order(prod) == ['result'] and w.done == [(JID, 'done')]
    monkeypatch.setenv('FAKE_BUNDLE', 'ok')
    monkeypatch.setenv('FAKE_BUNDLE_PAD', '5000')
    prod.reqs.clear()
    prod.add_job(attempt=2, leaseToken='M' * 32)
    w = mk(furnish=True, bundle_max_bytes=4096, base=mk.mem.parent / 'trial-big')
    w.loop(max_iter=1)
    assert prod.bundles == [] and _order(prod) == ['result']


def test_conveyor_no_living_tour_still_published_bedrooms_go_on(prod, mk, monkeypatch, tmp_path):
    """T-20261110-07: гостиной в плане нет — версия 1 есть (тур откроется), подбор гостиной не запускается, сцена-отказ
    «size_check» не пишется, спальня обставляется своей стадией, задание `done`."""
    monkeypatch.setenv('FAKE_NO_LIVING', '1')
    prod.add_job()
    w = mk(furnish=True)
    w.loop(max_iter=1)
    st = _states(prod)
    assert st[0] == ({'kitchen-1': 'not_furnished', 'bedroom-1': 'pending'}, False)
    assert st[-1] == ({'kitchen-1': 'not_furnished', 'bedroom-1': 'ready'}, True)
    assert _order(prod) == ['bundle', 'bundle', 'result'] and w.done == [(JID, 'done')]
    assert not (tmp_path / 'scenes' / JID).exists()                    # trial_demo не запускался
    wd = next(d for d in (w.cfg.base / JID).iterdir() if d.is_dir())
    assert not (wd / 'scene-refused.json').exists()


def test_conveyor_server_rejects_version_logged_and_job_finishes(prod, mk, capsys):
    prod.add_job()
    prod.bundle_codes = [422]
    w = mk(furnish=True)
    w.loop(max_iter=1)
    assert 'bundle_rejected http=422' in capsys.readouterr().out
    assert w.done == [(JID, 'done')]


def test_conveyor_size_flag_room_skipped_and_job_done(prod, mk, monkeypatch, tmp_path):
    """TG 531: гостиная с «размер не сошёлся» ждёт проверки — подбор гостиной не запускается, спальня обставляется, `done`."""
    monkeypatch.setenv('FAKE_SIZE_FLAG', 'r1')
    prod.add_job()
    w = mk(furnish=True)
    w.loop(max_iter=1)
    st = _states(prod)
    assert [s[0]['living'] for s in st] == ['awaiting_check:dims_mismatch'] * 2 and st[-1][0]['bedroom-1'] == 'ready'
    assert st[-1][1] is True and w.done == [(JID, 'done')]
    assert not (tmp_path / 'scenes' / JID).exists()                    # trial_demo не запускался
    # все комнаты-цели ждут проверки (масштаб квартиры / флаги): версия 1 уже полная — ни одной стадии, сразу `done`
    monkeypatch.setenv('FAKE_SIZE_FLAG', 'r1,b1')
    prod.reqs.clear()
    prod.bundles.clear()
    prod.add_job(attempt=2, leaseToken='M' * 32)
    w = mk(furnish=True, base=mk.mem.parent / 'trial-all')
    w.loop(max_iter=1)
    assert _order(prod) == ['bundle', 'result'] and _states(prod)[0][1] is True


def test_furnish_rooms_entry_releases_checked_rooms(prod, mk, monkeypatch, tmp_path):
    """Точка входа будущей кнопки «Обустроить»: по списку комнат проверка снята — стадия гостиной идёт, пустая версия 1 не шлётся."""
    import conveyor as cv
    monkeypatch.setenv('FAKE_SIZE_FLAG', 'r1')
    prod.add_job()
    w = mk(furnish=True)
    w.loop(max_iter=1)
    n = len(prod.bundles)
    wd = next(d for d in (w.cfg.base / JID).iterdir() if d.is_dir())
    hb = wk.Heartbeat(w, {'id': JID, 'attempt': 1, 'leaseToken': 'L' * 32}, wd)
    end = cv.furnish_rooms(w, {'id': JID, 'attempt': 1, 'leaseToken': 'L' * 32}, wd, hb, wd / 'result.json', ['living'])
    assert end == 'result' and len(prod.bundles) == n + 1
    assert prod.bundles[-1]['data']['apartment_rooms'][0]['furniture_state'] == 'ready'
    assert (tmp_path / 'scenes' / JID / 'scene.json').exists()


def test_bedroom_refusals_cover_every_bedroom():
    import conveyor as cv
    res = {'panels': [{'id': 'p0', 'rooms': [{'id': 'b1', 'kind': 'bedroom'}, {'id': 'r1', 'kind': 'living'}]},
                      {'id': 'p1', 'rooms': [{'id': 'b2', 'kind': 'bedroom'}]}]}
    parts = cv.bedroom_refusals(res, 'stage_unavailable')
    assert [(e['panel'], e['src_id'], e['furniture_state'], e['furniture_code']) for e in parts['apartment_rooms']] == \
        [('p0', 'b1', 'refused', 'stage_unavailable'), ('p1', 'b2', 'refused', 'stage_unavailable')]
    assert len({e['id'] for e in parts['apartment_rooms']}) == 2


# ───────────────────────── «Обустроить» — пересборка (conveyor.Rebuild, T-20261109-27) ─────────────────────────

RID = 'RbRbRbRbRbRbRbRbRbRbRb'


def _plan(flagged=('r1',)):
    """Сохранённый результат задания (как в Postgres): у комнат из `flagged` — «размер не сошёлся»."""
    rooms = [{'id': 'r1', 'kind': 'living'}, {'id': 'k1', 'kind': 'kitchen'}, {'id': 'b1', 'kind': 'bedroom'}]
    for r in rooms:
        r['flags'] = ['dims_mismatch'] if r['id'] in flagged else []
    return {'version': 1, 'units': 'cm', 'fake': True, 'panels': [{'id': 'p0', 'rooms': rooms}]}


def _rebuild(prod, rooms, flagged=('r1',), **over):
    prod.rebuilds.append({'id': RID, 'jobId': JID, 'attempt': 1, 'leaseToken': 'R' * 32, 'leaseUntil': 'x', 'rooms': rooms,
                          'baseVersion': 2, 'result': _plan(flagged), **over})


def test_rebuild_publishes_one_version_other_rooms_kept(prod, mk, tmp_path):
    """Гостиная ждала проверки, спальня была обставлена. «Обустроить» гостиную → ОДНА версия на …/rebuild/publish: гостиная с мебелью,
    спальня снова с мебелью (стадии из того же результата), кухня как была; ни `/bundle`, ни `result` задания."""
    _rebuild(prod, ['living'])
    w = mk(furnish=True)
    w.loop(max_iter=1)
    assert w.done == [(RID, 'rebuilt')]
    assert prod.by('/api/trial/worker/claim')[0]['rebuilds'] is True
    sent = prod.by('/api/trial/worker/rebuild/publish')
    assert len(sent) == 1 and sent[0]['jobId'] == JID and sent[0]['id'] == RID and sent[0]['leaseToken'] == 'R' * 32
    assert _states(prod) == [({'living': 'ready', 'kitchen-1': 'not_furnished', 'bedroom-1': 'ready'}, True)]
    assert prod.by('/api/trial/worker/bundle') == [] and prod.by('/api/trial/worker/result') == []
    assert prod.by('/api/trial/worker/rebuild/fail') == []
    hbs = prod.by('/api/trial/worker/rebuild/heartbeat')
    assert hbs and all(h['id'] == RID and 'stage' not in h for h in hbs) and prod.by('/api/trial/worker/heartbeat') == []
    wd = next((tmp_path / 'trial' / JID).glob('r1-*'))
    consent = json.loads((wd / 'result-consent.json').read_text())
    flags = {r['id']: r['flags'] for r in consent['panels'][0]['rooms']}
    assert flags == {'r1': ['dims_mismatch', 'approx_consent'], 'k1': [], 'b1': []}
    assert (tmp_path / 'scenes' / JID / 'scene.json').exists()            # стадия гостиной шла по заданию, не по id пересборки


# Обёртка стадии: пишет «имя класс-очереди» (HEAVY_SLOT_PRIO, которым стадия возьмёт heavy_slot) и запускает настоящую подделку.
PRIO_SPY = r'''
import os, runpy, sys
log, name, script = sys.argv[1:4]
open(log, 'a').write(f"{name} {os.environ.get('HEAVY_SLOT_PRIO', '-')}\n")
sys.argv = [script, *sys.argv[4:]]
runpy.run_path(script, run_name='__main__')
'''


def _prio_spy(mk, tmp_path):
    """Рабочий, у которого стены и все стадии мебели идут через `PRIO_SPY`. → (рабочий, путь журнала)."""
    spy, log = tmp_path / 'prio_spy.py', tmp_path / 'prio.log'
    spy.write_text(PRIO_SPY)
    w0 = mk(furnish=True)
    wrap = lambda name, cmd: [sys.executable, str(spy), str(log), name, cmd[-1]]   # noqa: E731
    w = mk(furnish=True, pipeline=wrap('walls', w0.cfg.pipeline),
           stage_cmds={k: wrap(k, v) for k, v in w0.cfg.stage_cmds.items() if v})
    return w, log


def test_heavy_slot_class_job_stages_trial_rebuild_first(prod, mk, tmp_path):
    """T-20261109-31: агент ждёт на открытой странице → стадии берут общую очередь heavy_slot не последними. Загрузка тура (стены
    и мебель задания) — класс 1, пересборка «Обустроить» — класс 2 (раньше всех); сам порядок по классу — `heavy-slot-selftest.sh`."""
    prod.add_job()
    w, log = _prio_spy(mk, tmp_path)
    w.loop(max_iter=1)
    assert w.done == [(JID, 'done')]
    got = log.read_text().split('\n')[:-1]
    assert got[0] == 'walls 1' and {'living 1', 'bedrooms 1', 'bundle 1'} <= set(got) and all(x.endswith(' 1') for x in got)
    assert wk.conveyor.SLOT_PRIO_TRIAL == 1 and wk.conveyor.SLOT_PRIO_REBUILD == 2

    log.write_text('')
    _rebuild(prod, ['*'], flagged=('r1', 'b1'))
    w.loop(max_iter=1)
    assert w.done[-1] == (RID, 'rebuilt')
    got = log.read_text().split('\n')[:-1]
    assert {'living 2', 'bedrooms 2', 'bundle 2'} <= set(got) and all(x.endswith(' 2') for x in got)


def test_rebuild_all_releases_every_waiting_room(prod, mk):
    _rebuild(prod, ['*'], flagged=('r1', 'b1'))
    w = mk(furnish=True)
    w.loop(max_iter=1)
    assert w.done == [(RID, 'rebuilt')]
    assert _states(prod) == [({'living': 'ready', 'kitchen-1': 'not_furnished', 'bedroom-1': 'ready'}, True)]


def test_rebuild_only_chosen_room_others_keep_waiting(prod, mk):
    """Снята проверка только со спальни — гостиная по-прежнему ждёт проверки (без мебели), спальня обставлена."""
    _rebuild(prod, ['bedroom-1'], flagged=('r1', 'b1'))
    w = mk(furnish=True)
    w.loop(max_iter=1)
    st = _states(prod)
    assert len(st) == 1 and st[0][0]['living'] == 'awaiting_check:dims_mismatch' and st[0][0]['bedroom-1'] == 'ready'


def test_rebuild_stale_not_published_and_not_failed_again(prod, mk):
    """Сервер ответил `stale` (страница сменилась, пока подбирали): версия не записана, воркер не шлёт `fail` — сервер уже пометил."""
    _rebuild(prod, ['living'])
    prod.rebuild_codes = [(409, 'stale')]
    w = mk(furnish=True)
    w.loop(max_iter=1)
    assert w.done == [(RID, 'stale')] and prod.bundles == [] and prod.by('/api/trial/worker/rebuild/fail') == []


def test_rebuild_nothing_to_furnish_fails_with_code(prod, mk):
    _rebuild(prod, ['bedroom-1'], flagged=('r1',))                     # спальня не ждёт проверки — снимать нечего
    w = mk(furnish=True)
    w.loop(max_iter=1)
    fails = prod.by('/api/trial/worker/rebuild/fail')
    assert len(fails) == 1 and fails[0]['code'] == 'nothing_to_furnish' and fails[0]['retryable'] is False
    assert prod.bundles == [] and w.done == [(RID, 'fail:nothing_to_furnish:200')]


def test_rebuild_lease_lost_kills_stage_and_publishes_nothing(prod, mk, monkeypatch):
    monkeypatch.setenv('FAKE_LIVING', 'slow')
    _rebuild(prod, ['living'])
    w = mk(furnish=True)
    t0 = time.time()
    threading.Timer(1.5, lambda: setattr(prod, 'hb_status', 409)).start()
    w.loop(max_iter=1)
    assert time.time() - t0 < 20 and w.done == [(RID, 'lost')]
    assert prod.bundles == [] and prod.by('/api/trial/worker/rebuild/publish') == [] and prod.by('/api/trial/worker/rebuild/fail') == []


def test_rebuild_bad_claim_fails_internal(prod, mk):
    _rebuild(prod, ['living'], result=None)
    w = mk(furnish=True)
    w.loop(max_iter=1)
    assert [f['code'] for f in prod.by('/api/trial/worker/rebuild/fail')] == ['internal']


def test_without_furnish_worker_does_not_ask_for_rebuilds(prod, mk):
    _rebuild(prod, ['living'])
    w = mk(furnish=False)
    w.loop(max_iter=1)
    assert 'rebuilds' not in prod.by('/api/trial/worker/claim')[0] and prod.rebuilds and w.done == []


# ───────────────────────── «Размеры своими словами» — пересборка по тексту (conveyor.ListingRebuild, T-20261109-33) ─────────────────

TEXT_OK = 'Гостиная 4,2 на 3,8'


def _listing(prod, text=TEXT_OK, rooms=(), **over):
    _rebuild(prod, list(rooms), **{'kind': 'listing', 'listingText': text, 'inputMime': 'image/png', **over})


def test_listing_rereads_plan_free_and_publishes_one_version_with_result(prod, mk, tmp_path, capsys):
    """Текст лёг: лист — под арендой пересборки, план заново только из кэша (`--cache-only`, 0 $) → ОДНА версия на …/rebuild/publish
    вместе с новым `result` (масштаб `listing`); гостиная больше не ждёт проверки и обставлена. Текста нет в журнале воркера."""
    _listing(prod)
    w = mk(furnish=True)
    w.loop(max_iter=1)
    assert w.done == [(RID, 'rebuilt')]
    claim = prod.by('/api/trial/worker/claim')[0]
    assert claim['rebuilds'] is True and claim['listing'] is True
    got = [(p, h) for p, b, h in prod.reqs if p == f'/api/trial/worker/rebuild/{RID}/input']
    assert len(got) == 1 and got[0][1]['X-Trial-Lease'] == 'R' * 32 and got[0][1]['X-Trial-Attempt'] == '1'
    wd = next((tmp_path / 'trial' / JID).glob('r1-*'))
    argv = json.loads((wd / 'plan' / 'argv.json').read_text())
    assert '--cache-only' in argv and argv[argv.index('--cap-usd') + 1] == '0' and argv[argv.index('--mime') + 1] == 'image/png'
    assert (wd / 'plan' / 'listing.txt').read_text(encoding='utf-8') == TEXT_OK
    sent = prod.by('/api/trial/worker/rebuild/publish')
    assert len(sent) == 1 and sent[0]['result']['reread'] and sent[0]['result']['scale']['status'] == 'listing'
    assert 'approx_consent' not in json.dumps(sent[0]['result'])          # в задание — чистый результат, не копия со снятием
    assert _states(prod) == [({'living': 'ready', 'kitchen-1': 'not_furnished', 'bedroom-1': 'ready'}, True)]
    assert prod.by('/api/trial/worker/bundle') == [] and prod.by('/api/trial/worker/rebuild/fail') == []
    assert TEXT_OK not in capsys.readouterr().out


def test_listing_no_match_publishes_nothing(prod, mk):
    """Текст ни к одной комнате не подошёл — `no_match` без повтора, страница как была."""
    _listing(prod, text='позвоните после обеда')
    w = mk(furnish=True)
    w.loop(max_iter=1)
    fails = prod.by('/api/trial/worker/rebuild/fail')
    assert [(f['code'], f['retryable']) for f in fails] == [('no_match', False)]
    assert prod.bundles == [] and prod.by('/api/trial/worker/rebuild/publish') == []


def test_listing_source_gone_when_sheet_deleted(prod, mk, tmp_path):
    """Лист удалён по сроку (410) — `source_gone` без повтора; план не перечитывается."""
    prod.input_status = 410
    _listing(prod)
    w = mk(furnish=True)
    w.loop(max_iter=1)
    assert [(f['code'], f['retryable']) for f in prod.by('/api/trial/worker/rebuild/fail')] == [('source_gone', False)]
    assert not list((tmp_path / 'trial' / JID).glob('r1-*/plan/argv.json'))


def test_listing_source_gone_when_vlm_cache_missing(prod, mk, monkeypatch):
    """Кэша чтения плана нет — платно заново не читаем: `source_gone`."""
    monkeypatch.setenv('FAKE_CACHE', 'gone')
    _listing(prod)
    w = mk(furnish=True)
    w.loop(max_iter=1)
    assert [(f['code'], f['retryable']) for f in prod.by('/api/trial/worker/rebuild/fail')] == [('source_gone', False)]
    assert prod.bundles == []


def test_listing_keeps_rooms_released_earlier(prod, mk, monkeypatch):
    """Спальня и с текстом ждёт проверки; агент раньше снял с неё проверку («Обустроить») — в новой версии она снова обставлена.
    Без такого снятия — ждёт проверки (размеры по тексту есть не у всех комнат)."""
    monkeypatch.setenv('FAKE_KEEP_FLAG', 'b1')
    _listing(prod, rooms=['bedroom-1'])
    w = mk(furnish=True)
    w.loop(max_iter=1)
    assert _states(prod) == [({'living': 'ready', 'kitchen-1': 'not_furnished', 'bedroom-1': 'ready'}, True)]
    prod.bundles.clear()
    _listing(prod)
    w.loop(max_iter=1)
    assert _states(prod) == [({'living': 'ready', 'kitchen-1': 'not_furnished', 'bedroom-1': 'awaiting_check:dims_mismatch'}, True)]


def test_listing_bad_claim_without_mime_fails_internal(prod, mk):
    _listing(prod, inputMime='text/plain')
    w = mk(furnish=True)
    w.loop(max_iter=1)
    assert [f['code'] for f in prod.by('/api/trial/worker/rebuild/fail')] == ['internal']


NAMES = 'Lounge|Kitchen|Bedroom 1|Bedroom 2'


def _dims(res):
    return {r['name']: (r['dims']['w'], r['dims']['d']) for p in res['panels'] for r in p['rooms'] if 'dims' in r}


def _second(prod, mk, monkeypatch, tmp_path, first, second):
    """Первый текст → опубликованный result → второй текст поверх него (как сервер: claim отдаёт текущий result задания)."""
    monkeypatch.setenv('FAKE_NAMES', NAMES)
    monkeypatch.setenv('FAKE_FP', str(ROOT / 'tools' / 'floorplan'))
    _listing(prod, text=first)
    w = mk(furnish=True)
    w.loop(max_iter=1)
    one = prod.by('/api/trial/worker/rebuild/publish')[-1]['result']
    prod.reqs.clear()
    _listing(prod, text=second, result=one)
    w.loop(max_iter=1)
    sent = prod.by('/api/trial/worker/rebuild/publish')
    lst = sorted((tmp_path / 'trial' / JID).glob('r1-*/plan/listing.txt'), key=lambda p: p.stat().st_mtime)[-1]
    return one, sent, lst.read_text(encoding='utf-8')


def test_listing_second_text_supplements_first(prod, mk, monkeypatch, tmp_path, capsys):
    """Ведущий 10.11 (вариант А): второй текст ДОПОЛНЯЕТ. Первый — гостиная и спальня 1, второй — только спальня 2 → в новой
    версии размеры у всех трёх, масштаб не падает. Прошлые размеры берутся из result задания (текст не храним)."""
    one, sent, lst = _second(prod, mk, monkeypatch, tmp_path, 'Lounge 4.4m x 3.8m\nBedroom 1 5.5m x 4.0m', 'Bedroom 2 3.9m x 4.0m')
    assert _dims(one) == {'Lounge': (440, 380), 'Bedroom 1': (550, 400)} and one['scale']['status'] == 'listing'
    assert len(sent) == 1 and _dims(sent[0]['result']) == {'Lounge': (440, 380), 'Bedroom 1': (550, 400), 'Bedroom 2': (390, 400)}
    assert sent[0]['result']['scale']['status'] == 'listing'
    assert lst.splitlines() == ['Lounge — 4.40 m x 3.80 m', 'Bedroom 1 — 5.50 m x 4.00 m', 'Bedroom 2 3.9m x 4.0m']
    assert 'перенесено комнат 2' in capsys.readouterr().out


def test_listing_second_text_same_room_new_value(prod, mk, monkeypatch, tmp_path):
    """Та же комната во втором тексте — новое значение (не «повтор имени», не старое); по-русски — та же комната по виду и номеру."""
    _, sent, lst = _second(prod, mk, monkeypatch, tmp_path, 'Lounge 4.4m x 3.8m\nBedroom 1 5.5m x 4.0m', 'спальня 1 — 5 на 4,2')
    assert _dims(sent[0]['result']) == {'Lounge': (440, 380), 'Bedroom 1': (500, 420)}
    assert lst.splitlines()[0] == 'Lounge — 4.40 m x 3.80 m' and 'Bedroom 1 —' not in lst


def test_listing_second_text_without_match_is_no_match(prod, mk, monkeypatch, tmp_path):
    """Второй текст ни к чему не подошёл — `no_match`, хотя перенесённые прошлые размеры лягут снова: «лёг» считается по новому."""
    _, sent, _ = _second(prod, mk, monkeypatch, tmp_path, 'Lounge 4.4m x 3.8m', 'позвоните после обеда')
    assert sent == [] and [f['code'] for f in prod.by('/api/trial/worker/rebuild/fail')] == ['no_match']


def test_text_applied_only_length_anchors():
    """«Лёг» — размеры комнаты из текста или масштаб стал опираться на длины; только площадь (`area`) — не опора."""
    import conveyor as cv
    P = lambda st, dims=None: {'scale': {'status': st}, 'panels': [{'rooms': [{'id': 'r', **({'dims': dims} if dims else {})}]}]}  # noqa: E731
    assert cv.text_applied(P('not_verified'), P('listing'))
    assert cv.text_applied(P('verified'), P('verified', {'w': 1, 'd': 1, 'src': 'listing'}))
    assert not cv.text_applied(P('not_verified'), P('area'))
    assert not cv.text_applied(P('not_verified'), P('not_verified', {'w': 1, 'd': 1, 'src': 'plan'}))
    assert not cv.text_applied(P('verified'), P('verified'))
    # перенесённый прошлый размер (та же комната и раньше из текста) — не «лёг»; новый текст её задал (`hit`) — «лёг»
    L = {'w': 1, 'd': 1, 'src': 'listing'}
    assert not cv.text_applied(P('listing', L), P('listing', L))
    named = lambda: {'scale': {'status': 'listing'}, 'panels': [{'rooms': [{'id': 'r', 'name': 'Bedroom One', 'dims': L}]}]}  # noqa: E731
    assert cv.text_applied(named(), named(), {'bedroom 1'})
