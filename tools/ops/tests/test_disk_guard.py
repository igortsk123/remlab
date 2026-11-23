"""Тесты сторожа места `tools/ops/disk_guard.py` и его встройки в heavy-slot и `kit_driver.require_slot` (T-20261123-35).

Только временная папка и подставные функции: настоящий диск не заполняем, настоящий Telegram не трогаем (`notify` подменён, `DISK_GUARD_ALERT` — заглушка),
журнал и состояние — в tmp_path. Запуск: `python -m pytest tools/ops/tests/test_disk_guard.py -q`."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
OPS = HERE.parents[1]
ROOT = HERE.parents[3]
sys.path.insert(0, str(OPS))
sys.path.insert(0, str(ROOT / 'tools' / 'scout' / 'salad'))
import disk_guard as dg  # noqa: E402


@pytest.fixture
def env(tmp_path, monkeypatch):
    rules = tmp_path / 'rules.json'
    rules.write_text(json.dumps({'start_min_free_gb': 15, 'start_guard_path': '/', 'alert_every_min': 30}))
    monkeypatch.setenv('DISK_GUARD_RULES', str(rules))
    monkeypatch.setenv('DISK_GUARD_STATE', str(tmp_path / 'state'))
    monkeypatch.setenv('DISK_GUARD_LOG', str(tmp_path / 'disk-guard.log'))
    monkeypatch.delenv('DISK_GUARD', raising=False)
    return tmp_path


def test_rules_in_repo_have_threshold():
    r = json.loads((ROOT / 'tools' / 'scout' / 'rules' / 'dev-disk.json').read_text(encoding='utf-8'))
    assert r['start_min_free_gb'] == 15 and r['start_guard_path'] == '/' and r['alert_every_min'] > 0
    a = r['archive']
    assert a['days'] == 5 and a['dst'].startswith('/mnt/hdd/') and a['min_hdd_free_gb'] > 0


def test_enough_space_passes_silently(env):
    sent = []
    ok, msg = dg.check('проба', free_fn=lambda p: 40.0, notify=sent.append)
    assert ok and not sent and 'свободно 40.0' in msg and not (env / 'disk-guard.log').exists()


def test_boundary_exactly_threshold_passes(env):
    ok, _ = dg.check('x', free_fn=lambda p: 15.0, notify=lambda t: True)
    assert ok


def test_low_space_refuses_logs_and_alerts(env):
    sent = []
    ok, msg = dg.check('heavy-slot «t»', free_fn=lambda p: 3.7, notify=lambda t: sent.append(t) or True, now=1000.0)
    assert not ok and msg.startswith('❗') and '3.7' in msg and 'меньше порога 15' in msg and 'heavy-slot «t»' in msg
    assert sent == [msg]
    log = (env / 'disk-guard.log').read_text(encoding='utf-8')
    assert '❗' in log and 'НЕ запущено' in log


def test_alert_rate_limited(env):
    sent = []
    for t in (1000.0, 1010.0, 1000.0 + 31 * 60):
        dg.check('x', free_fn=lambda p: 1.0, notify=lambda m: sent.append(m) or True, now=t)
    assert len(sent) == 2                                  # второй отказ через 10 с — без нового сообщения; через 31 мин — снова


def test_guard_off_is_explicit_and_logged(env, monkeypatch):
    monkeypatch.setenv('DISK_GUARD', '0')
    ok, msg = dg.check('уборка', free_fn=lambda p: 0.0, notify=lambda t: pytest.fail('не должно слать'))
    assert ok and 'выключен' in msg and 'выключен' in (env / 'disk-guard.log').read_text(encoding='utf-8')


def test_require_raises_disklow(env, monkeypatch):
    monkeypatch.setattr(dg, 'free_gb', lambda p='/': 2.0)
    monkeypatch.setenv('DISK_GUARD_ALERT', '/bin/true')
    with pytest.raises(dg.DiskLow):
        dg.require('x')


def test_unreadable_path_refuses(env, monkeypatch):
    def boom(p):
        raise OSError('нет такой точки')
    ok, msg = dg.check('x', free_fn=boom, notify=lambda t: True)
    assert not ok and 'не удалось узнать' in msg


def test_cli_exit_codes(env):
    rules = env / 'low.json'
    rules.write_text(json.dumps({'start_min_free_gb': 10 ** 9}))
    e = dict(os.environ, DISK_GUARD_RULES=str(rules), DISK_GUARD_ALERT='/bin/true')
    r = subprocess.run([sys.executable, str(OPS / 'disk_guard.py'), '--label', 'тест'], env=e, capture_output=True, text=True)
    assert r.returncode == 3 and '❗' in r.stderr
    rules.write_text(json.dumps({'start_min_free_gb': 0}))
    r = subprocess.run([sys.executable, str(OPS / 'disk_guard.py'), '--quiet'], env=e, capture_output=True, text=True)
    assert r.returncode == 0


def test_alert_goes_through_ci_channel_script(env, monkeypatch):
    """Канал — как у красного CI: bash <alert.sh> <текст>; здесь вместо него заглушка, пишущая аргумент в файл."""
    stub = env / 'alert-stub.sh'
    out = env / 'alert-out.txt'
    stub.write_text(f'#!/bin/bash\nprintf "%s" "$1" > {out}\nexit 0\n')
    monkeypatch.setenv('DISK_GUARD_ALERT', str(stub))
    ok, msg = dg.check('платное', free_fn=lambda p: 1.0, now=5000.0)
    assert not ok and out.read_text(encoding='utf-8') == msg
    assert (ROOT / 'tools' / 'scout' / 'alert.sh').exists() and dg.ALERT.endswith('tools/scout/alert.sh')


def test_heavy_slot_refuses_with_rc3_and_runs_nothing(env):
    rules = env / 'low.json'
    rules.write_text(json.dumps({'start_min_free_gb': 10 ** 9}))
    marker = env / 'ran'
    e = dict(os.environ, DISK_GUARD_RULES=str(rules), DISK_GUARD_ALERT='/bin/true', HEAVY_SLOT_DIR=str(env / 'slots'), HOME=str(env))
    r = subprocess.run([sys.executable, str(OPS / 'heavy_slot.py'), 'тест-диска', '--min-gb', '0.1', '--timeout', '5', '--', 'touch', str(marker)],
                       env=e, capture_output=True, text=True, timeout=60)
    assert r.returncode == 3 and '❗' in r.stderr and not marker.exists()


def test_require_slot_refuses_on_low_disk(env, monkeypatch):
    import kit_driver as KD
    monkeypatch.setattr(dg, 'free_gb', lambda p='/': 2.0)
    monkeypatch.setenv('DISK_GUARD_ALERT', '/bin/true')
    pid = os.getpid()
    cmdline = env / 'proc' / str(pid)
    cmdline.mkdir(parents=True)
    (cmdline / 'cmdline').write_bytes(b'heavy_slot.py\x00m\x00--prio\x002\x00--\x00x\x00')
    monkeypatch.setitem(os.environ, 'HEAVY_SLOT_HELD', str(pid))
    # боевой вызов (env=os.environ): слот есть по /proc заглушки, но диск полон → SlotRefused
    with pytest.raises(KD.SlotRefused) as ei:
        KD.require_slot(proc_root=str(env / 'proc'))
    assert '❗' in str(ei.value)
    # тестовый вызов с подставным env диск не трогает
    KD.require_slot(env={'HEAVY_SLOT_HELD': str(pid)}, proc_root=str(env / 'proc'))
