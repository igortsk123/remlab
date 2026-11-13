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
if b.get('drop_cams'):                       # шаг ракурсов сборки не уложился (WARN:trial_cams) — пары нет ни у кого
    for v in b.get('variants') or []:
        v['cams'] = []
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
    assert f'{A}: пропущен — busy: идёт пересборка агента (тур не тронут)' in capsys.readouterr().out and p.posts == []
    p.busy.clear()
    p.stale.add(A)
    assert RS.main(['--job', A], cfg=cfg, cmd=cmd) == 0 and p.tours[A]['version'] == 3
    assert 'пропущен — stale' in capsys.readouterr().out
    p.stale.clear()
    p.posts.clear()
    assert RS.main(['--job', A, '--dry-run'], cfg=cfg, cmd=cmd) == 0
    assert p.posts == [] and f'{A}: собран (без публикации)' in capsys.readouterr().out


def test_cards_batch_only_where_changed_and_unchanged_counted(env, capsys, monkeypatch):
    """`--cards batch` (автоперевыпуск, T-20261112-92): одна пачка карточек после прохода, только туры с новыми данными или
    витриной; «те же байты и та же витрина» — «без изменений», ни версии, ни карточек; `stale` — один повтор сразу."""
    p, cfg, cmd = env
    import cards as CD
    calls = []
    monkeypatch.setattr(CD, 'spawn', lambda jid, *a, **k: calls.append(jid) or True)
    cfg.cards = True
    del p.tours[B], p.tours[C]
    assert RS.main(['--days', '7', '--cards', 'batch'], cfg=cfg, cmd=cmd) == 0
    assert calls == [[A]]                                                    # пачкой, а не по туру
    out = capsys.readouterr().out
    assert 'итого туров 1: published 1' in out
    # тот же проход ещё раз: сборка даёт те же байты, сервер — repeated и та же витрина → «без изменений», без карточек
    calls.clear()
    monkeypatch.setattr(RS, 'one', lambda api, cfg, jid, run_dir, dry, cmd=None, cards='each': {
        'id': jid, 'status': 'published', 'from': 4, 'version': 4, 'repeated': True, 'release': 'f' * 32, 'previous': 'f' * 32,
        'unchanged': True, 'cards_need': False})
    assert RS.main(['--days', '7', '--cards', 'batch'], cfg=cfg, cmd=cmd) == 0 and calls == []
    out = capsys.readouterr().out
    assert f'{A}: без изменений (v4' in out and 'итого туров 1: unchanged 1' in out


def test_stale_retried_once(env, capsys, monkeypatch):
    p, cfg, cmd = env
    seq = [{'id': A, 'status': 'skipped', 'why': 'stale'}, {'id': A, 'status': 'published', 'from': 4, 'version': 5}]
    monkeypatch.setattr(RS, 'one', lambda *a, **k: seq.pop(0))
    assert RS.main(['--job', A], cfg=cfg, cmd=cmd) == 0 and seq == []
    out = capsys.readouterr().out
    assert 'версия сменилась, пока собирали — повтор' in out and f'{A}: опубликован v4 → v5' in out
    seq[:] = [{'id': A, 'status': 'skipped', 'why': 'stale'}, {'id': A, 'status': 'skipped', 'why': 'stale'}]
    assert RS.main(['--job', A], cfg=cfg, cmd=cmd) == 0 and seq == []           # второй stale — пропуск, не бесконечный круг


def test_hold_list_skips_tours_without_touching_them(env, capsys, tmp_path):
    """«держать» (T-20261112-92/5): id из файла — skipped/hold, тур не читается и не публикуется; «*» — все; нет файла — как обычно."""
    p, cfg, cmd = env
    hold = tmp_path / 'hold.txt'
    hold.write_text(f'# спальни в отказе\n{B}\n\n{C}  # сбоит\n')
    assert RS.main(['--days', '7', '--hold', str(hold)], cfg=cfg, cmd=cmd) == 0      # держим отказ и сбой — код 0
    out = capsys.readouterr().out
    assert [j for j, _ in p.posts] == [A]
    assert f'{B}: пропущен — hold: в списке «держать»' in out and f'{C}: пропущен — hold' in out
    hold.write_text('*\n')
    assert RS.main(['--days', '7', '--hold', str(hold)], cfg=cfg, cmd=cmd) == 0 and [j for j, _ in p.posts] == [A]
    rep = json.loads(sorted((cfg.base / 'reissue').iterdir())[-1].joinpath('report.json').read_text())
    assert {(r['status'], r['why']) for r in rep} == {('skipped', 'hold')}
    assert RS.hold_list(str(tmp_path / 'нет.txt')) == set() and RS.hold_list(None) == set()


def test_lost_cams_refused_tour_kept(env, capsys):
    """БЕЗ РАКУРСОВ НЕ ПЕРЕВЫПУСКАЕМ (T-20261113-17/2): новая сборка потеряла пару ракурсов у комнаты с мебелью — отказ `no_cams`,
    публикации нет, тур на прежней версии, проход — код 1 и строка оператору. Комната в отказе (мебели нет, пары нет и раньше) —
    не держит. Та же сборка с парами — публикуется."""
    p, cfg, cmd = env
    pair = [{'x': 1, 'y': 2}, {'x': 3, 'y': 4}]
    vs = [{'id': 'living-scandi', 'cams': pair, 'furniture_state': 'ready'},
          {'id': 'bedroom-1-scandi', 'cams': [], 'furniture_state': 'refused'}]
    del p.tours[B], p.tours[C]
    p.tours[A]['bundle'] = json.dumps({'trial': {'job_id': A}, 'variants': vs, 'drop_cams': True})
    assert RS.main(['--job', A], cfg=cfg, cmd=cmd) == 1
    out = capsys.readouterr().out
    assert p.posts == [] and p.tours[A]['version'] == 3
    assert f'{A}: отказ сборщика no_cams — тур остался прежним (нет ракурсов у 1: living-scandi' in out
    p.tours[A]['bundle'] = json.dumps({'trial': {'job_id': A}, 'variants': vs})
    assert RS.main(['--job', A], cfg=cfg, cmd=cmd) == 0 and [j for j, _ in p.posts] == [A] and p.tours[A]['version'] == 4


def test_priced_not_3d_refused_tour_kept(env, capsys, monkeypatch):
    """В ЦЕНЕ — ЗНАЧИТ В 3D (T-20261113-23): сторож витрины (`priced_vs_3d.guard`) против прежней версии нашёл НОВУЮ строку — отказ
    `priced_not_3d`, публикации нет, тур на прежней версии, код 1. Чисто — публикуется; сам сторож не сработал — публикуется с причиной."""
    p, cfg, cmd = env
    del p.tours[B], p.tours[C]
    seen = []
    row = {'variant': 'living-scandi', 'role': 'столик', 'name': 'ядро', 'reason': 'ядро: нет в 3D', 'rub': 0.0}
    monkeypatch.setattr(RS.priced_vs_3d, 'guard', lambda new, old: (seen.append(Path(old).name),
                                                                   {'ok': False, 'block': [row], 'report': [], 'error': ''})[1])
    assert RS.main(['--job', A], cfg=cfg, cmd=cmd) == 1
    out = capsys.readouterr().out
    assert p.posts == [] and p.tours[A]['version'] == 3 and seen == ['bundle-old.json']
    assert f'{A}: отказ сборщика priced_not_3d — тур остался прежним (в цене без 3D или без ядра 1: living-scandi столик' in out
    monkeypatch.setattr(RS.priced_vs_3d, 'guard', lambda new, old: {'ok': True, 'block': [], 'report': [], 'error': 'OSError: нет node'})
    assert RS.main(['--job', A], cfg=cfg, cmd=cmd) == 0 and [j for j, _ in p.posts] == [A] and p.tours[A]['version'] == 4


def test_without_token_or_target(env):
    p, cfg, cmd = env
    cfg.token = ''
    assert RS.main(['--job', A], cfg=cfg, cmd=cmd) == 2
    cfg.token = TOKEN
    with pytest.raises(SystemExit):
        RS.main([], cfg=cfg, cmd=cmd)
