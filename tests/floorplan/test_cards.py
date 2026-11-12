"""Готовые снимки карточек комнат тура (T-20261112-29): разбор кадров, отправка порциями, фон через systemd-run, крючок конвейера.
Без сети и без браузера: снимальщик и systemd-run подменены."""
import base64
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools' / 'floorplan'))
import cards as CD  # noqa: E402

JPG = base64.b64encode(b'\xff\xd8\xff\xe0' + b'\x01' * 300).decode()
KEY = 'living|set3|s0'


def test_parse_cards_keeps_only_valid():
    res = {'cards': [
        {'key': KEY, 'jpg': JPG},
        {'key': 'bad key', 'jpg': JPG},                                        # ключ не по формату сервера
        {'key': 'a|b|c', 'jpg': base64.b64encode(b'\x89PNG' + b'0' * 300).decode()},   # не JPEG
        {'key': 'a|b|d', 'jpg': '%%%'},                                        # не base64
        {'key': 'a|b|e', 'jpg': base64.b64encode(b'\xff\xd8\xff' + b'0' * (CD.CARD_MAX_BYTES + 1)).decode()},  # больше потолка
        {'key': 'a|b|f', 'err': 'timeout'}, 'junk']}
    assert CD.parse_cards(res) == [{'key': KEY, 'jpg': JPG}]
    assert CD.parse_cards({}) == [] and CD.parse_cards(None) == []


def test_upload_in_parts_and_stops_on_error():
    calls = []

    def ok(method, path, body):
        calls.append((method, path, len(body['cards'])))
        return 200, {'ok': True}
    cards = [{'key': f'r|v{i}|s0', 'jpg': JPG} for i in range(CD.PER_POST * 2 + 1)]
    assert CD.upload(ok, 'J', cards) == (len(cards), None)
    assert calls == [('POST', '/api/trial/worker/cards', CD.PER_POST)] * 2 + [('POST', '/api/trial/worker/cards', 1)]
    n, err = CD.upload(lambda *a: (404, {'error': 'not_found'}), 'J', cards)
    assert n == 0 and err == 'http 404 not_found'


def _runner(res, rc=0):
    def run(cmd, cwd=None, timeout=None):
        Path(cmd[-3] if cmd[-2] == '--timeout' else cmd[-1]).write_text(json.dumps(res), encoding='utf-8')
        return SimpleNamespace(returncode=rc)
    return run


def test_make_sends_and_strips_images_from_log(tmp_path):
    sent = []
    row = CD.make('J', 'https://x.test', tmp_path, call=lambda m, p, b: (sent.append(b), (200, {'ok': True}))[1],
                  runner=_runner({'ok': 1, 'cards': [{'key': KEY, 'jpg': JPG}, {'key': 'a|b|c', 'err': 'x'}]}))
    assert row['status'] == 'sent' and row['sent'] == 1 and row['errors'] == 1
    assert sent[0] == {'id': 'J', 'cards': [{'key': KEY, 'jpg': JPG}]}
    assert 'jpg' not in (tmp_path / 'J.json').read_text(encoding='utf-8')


def test_make_failed_empty_dry(tmp_path):
    assert CD.make('J', 'u', tmp_path, runner=_runner({'error': 'page'}, rc=2))['status'] == 'failed'
    assert CD.make('J', 'u', tmp_path, runner=_runner({'cards': []}))['status'] == 'empty'
    assert CD.make('J', 'u', tmp_path, dry=True, runner=_runner({'cards': [{'key': KEY, 'jpg': JPG}]}))['status'] == 'rendered'

    def slow(*a, **k):
        raise subprocess.TimeoutExpired('x', 1)
    assert CD.make('J', 'u', tmp_path, runner=slow) == {'id': 'J', 'status': 'failed', 'why': 'timeout'}


def test_render_cmd_goes_through_heavy_slot():
    cmd = CD.render_cmd(CD.tour_url('https://x.test/', 'J'), Path('/o.json'))
    assert cmd[0].endswith('tools/ops/heavy-slot.sh') and cmd[cmd.index('--') + 2].endswith('trial_cards.mjs')
    assert 'https://x.test/try/J/tour/' in cmd


def test_spawn_systemd_run_without_secret_values(tmp_path):
    seen = []

    def run(cmd, **k):
        seen.append(cmd)
        return SimpleNamespace(returncode=0, stderr='')
    env = {'TRIAL_WORKER_TOKEN': 'SECRET', 'TRIAL_API_URL': 'https://x.test', 'PATH': '/bin', 'OTHER': '1'}
    assert CD.spawn('J-1', tmp_path, python='/py', runner=run, log=lambda m: None, env=env) is True
    cmd = seen[0]
    assert cmd[:2] == ['systemd-run', '--user'] and 'SECRET' not in ' '.join(cmd)
    assert [cmd[i + 1] for i, x in enumerate(cmd) if x == '-E'] == ['TRIAL_API_URL', 'TRIAL_WORKER_TOKEN', 'PATH']
    assert cmd[-4:] == ['/py', str(CD.HERE / 'cards.py'), '--job', 'J-1'] and any(x.startswith('MemoryMax=') for x in cmd)
    assert CD.spawn('J', tmp_path, runner=lambda c, **k: SimpleNamespace(returncode=1, stderr='no bus'), log=lambda m: None, env=env) is False

    def boom(c, **k):
        raise OSError('no systemd-run')
    assert CD.spawn('J', tmp_path, runner=boom, log=lambda m: None, env=env) is False


def test_conveyor_hook_only_when_enabled(monkeypatch):
    import conveyor as CV
    calls = []
    monkeypatch.setattr(CD, 'spawn', lambda jid, *a, **k: calls.append(jid) or True)
    for on, last, stopped in [(False, 1, False), (True, None, False), (True, 1, True), (True, 1, False)]:
        fake = SimpleNamespace(cfg=SimpleNamespace(cards=on, base='/b', python='/py'), last=last, stopped=stopped, jid='J', log=print)
        CV.Conveyor.cards(fake)
    assert calls == ['J']
