"""Команда оператора «пересобрать готовые туры как есть» (`tools/floorplan/reissue.py`, T-20261110-05) против поддельного прода:
список младше N дней → исходник → сборка (поддельный сборщик) → публикация от той же версии; пропуски и отказы — строкой, тур не тронут."""
import hashlib
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools' / 'floorplan'))
sys.path.insert(1, str(ROOT / 'tools' / 'ops'))
import reissue as RS  # noqa: E402
import worker as wk  # noqa: E402

TOKEN = 'T' * 32
A, B, C = 'A' * 22, 'B' * 22, 'C' * 22

FAKE_BUILD = r'''
import json, sys
jid, res, old, _, out = sys.argv[1:6]
b = json.load(open(old))
if b.get('refuse'):
    print(json.dumps({'refusal': 'no_core', 'detail': 'ядро'})); sys.exit(2)
if b.get('crash'):
    print('падаю'); sys.exit(1)
b['rev'] = 'new'
open(out, 'w').write(json.dumps(b))
print(json.dumps({'ok': True, 'kept_furniture': ['living'], 'kept_outcome': [], 'no_source': [], 'renamed_rooms': {}}))
'''


class Prod:
    def __init__(self):
        self.tours = {A: {'version': 3, 'bundle': json.dumps({'trial': {'job_id': A}})},
                      B: {'version': 1, 'bundle': json.dumps({'trial': {'job_id': B}, 'refuse': True})},
                      C: {'version': 2, 'bundle': json.dumps({'trial': {'job_id': C}, 'crash': True})}}
        self.busy, self.posts, self.stale = set(), [], set()


def handler(p: Prod):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def send(self, code, body):
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.headers.get('Authorization') != f'Bearer {TOKEN}':
                return self.send(401, {'ok': False})
            if self.path == '/api/trial/worker/reissue?days=7':
                return self.send(200, {'ok': True, 'jobs': [{'id': j, 'version': t['version'], 'createdAt': 'x'} for j, t in p.tours.items()]})
            jid = self.path.rsplit('/', 1)[-1]
            if jid in p.busy:
                return self.send(409, {'ok': False, 'error': 'busy'})
            t = p.tours.get(jid)
            if not t:
                return self.send(404, {'ok': False, 'error': 'not_found'})
            return self.send(200, {'ok': True, 'jobId': jid, 'version': t['version'], 'result': {'version': 1}, 'bundle': t['bundle']})

        def do_POST(self):
            b = json.loads(self.rfile.read(int(self.headers.get('Content-Length') or 0)))
            jid = self.path.rsplit('/', 1)[-1]
            p.posts.append((jid, b))
            if hashlib.sha256(b['bundle'].encode()).hexdigest() != b['sha256']:
                return self.send(422, {'ok': False, 'error': 'hash_mismatch'})
            if jid in p.stale or b['baseVersion'] != p.tours[jid]['version']:
                return self.send(409, {'ok': False, 'error': 'stale'})
            p.tours[jid] = {'version': p.tours[jid]['version'] + 1, 'bundle': b['bundle']}
            return self.send(200, {'ok': True, 'version': p.tours[jid]['version'], 'repeated': False, 'release': 'f' * 32, 'previous': 'e' * 32})
    return H


@pytest.fixture
def env(tmp_path):
    p = Prod()
    srv = ThreadingHTTPServer(('127.0.0.1', 0), handler(p))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    fake = tmp_path / 'fake_build.py'
    fake.write_text(FAKE_BUILD)
    cfg = wk.Cfg(url=f'http://127.0.0.1:{srv.server_address[1]}', token=TOKEN, base=tmp_path / 'trial', retry_s=0.01)
    yield p, cfg, [sys.executable, str(fake)]
    srv.shutdown()


def test_batch_publishes_built_and_reports_refusal_and_crash(env, capsys):
    p, cfg, cmd = env
    rc = RS.main(['--days', '7'], cfg=cfg, cmd=cmd)
    out = capsys.readouterr().out
    assert rc == 1                                                    # отказ и сбой — не тихо
    assert [j for j, _ in p.posts] == [A] and p.tours[A]['version'] == 4 and json.loads(p.tours[A]['bundle'])['rev'] == 'new'
    assert p.posts[0][1]['baseVersion'] == 3
    assert f'{A}: опубликован v3 → v4, витрина ffffffffffff; мебель прежняя в комнатах: living' in out
    assert f'{B}: отказ сборщика no_core — тур остался прежним' in out
    assert f'{C}: сбой — trial_reissue rc=1 · падаю (тур остался прежним)' in out
    rep = json.loads(next((cfg.base / 'reissue').iterdir()).joinpath('report.json').read_text())
    assert [r['status'] for r in rep] == ['published', 'refused', 'failed']


def test_busy_stale_and_dry_run_leave_tour_alone(env, capsys):
    p, cfg, cmd = env
    p.busy.add(A)
    assert RS.main(['--job', A], cfg=cfg, cmd=cmd) == 0
    assert f'{A}: пропущен — busy (тур не тронут)' in capsys.readouterr().out and p.posts == []
    p.busy.clear()
    p.stale.add(A)
    assert RS.main(['--job', A], cfg=cfg, cmd=cmd) == 0 and p.tours[A]['version'] == 3
    assert 'пропущен — stale' in capsys.readouterr().out
    p.stale.clear()
    p.posts.clear()
    assert RS.main(['--job', A, '--dry-run'], cfg=cfg, cmd=cmd) == 0
    assert p.posts == [] and f'{A}: собран (без публикации)' in capsys.readouterr().out


def test_without_token_or_target(env):
    p, cfg, cmd = env
    cfg.token = ''
    assert RS.main(['--job', A], cfg=cfg, cmd=cmd) == 2
    cfg.token = TOKEN
    with pytest.raises(SystemExit):
        RS.main([], cfg=cfg, cmd=cmd)
