"""Предел времени на план для `door_evidence` (T-20261126-169/2): лист, считающийся дольше предела, — SystemExit с причиной, а не
зависание; вне прогона плана и при снятом пределе — без проверки; предел лежит в `door_time_limit.json` вместе с _why."""
import json
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools' / 'floorplan'))
import bench  # noqa: E402
import fpcore as fc  # noqa: E402


def gap():
    thin = np.zeros((120, 160), np.uint8)
    return thin, np.array([80.0, 60.0]), np.array([1.0, 0.0]), np.array([0.0, 1.0]), 30.0, 8.0


def test_no_limit_outside_plan():
    thin, c, u, n, L, d = gap()
    assert fc._DOOR_BUDGET['max'] is None
    assert fc.door_evidence(thin, c, u, n, L, d) == 0.0


def test_over_limit_exits_with_reason():
    thin, c, u, n, L, d = gap()
    fc.arm_door_budget(limit_sec=-1.0)           # предел уже исчерпан
    try:
        with pytest.raises(SystemExit) as e:
            fc.door_evidence(thin, c, u, n, L, d)
        assert 'walls: не сошлось' in str(e.value) and 'процессорного времени плана' in str(e.value)
    finally:
        fc.disarm_door_budget()
    assert fc.door_evidence(thin, c, u, n, L, d) == 0.0        # снят — снова считает


def test_under_limit_computes_and_disarm_returns_seconds():
    thin, c, u, n, L, d = gap()
    fc.arm_door_budget(limit_sec=1000.0)
    try:
        assert fc.door_evidence(thin, c, u, n, L, d) == 0.0
    finally:
        used = fc.disarm_door_budget()
    assert 0.0 <= used < 1000.0 and fc._DOOR_BUDGET['max'] is None


def test_env_overrides_file(monkeypatch):
    monkeypatch.setenv('FP_DOOR_SEC_MAX', '7')
    assert fc.door_time_limit() == 7.0
    monkeypatch.setenv('FP_DOOR_SEC_MAX', '0')
    assert fc.door_time_limit() is None


def test_limit_file_has_value_and_why():
    j = json.loads(Path(fc.DOOR_TIME_FILE).read_text(encoding='utf-8'))
    assert float(j['plan_cpu_sec_max']) > 0
    assert len(j['_why']) > 80 and 'C' in j['_why'] and '14269998' in j['_why']
    assert fc.door_time_limit() == float(j['plan_cpu_sec_max'])


def test_limit_file_records_recount_169_5():
    """T-169/5: предел пересчитан по замеру на стенде (P95 × 2 = 1090, было 690); в _why — было → стало, замер и «следующий пересчёт»;
    предел читается из файла, а не из кода (env FP_DOOR_SEC_MAX сильнее файла)."""
    j = json.loads(Path(fc.DOOR_TIME_FILE).read_text(encoding='utf-8'))
    assert float(j['plan_cpu_sec_max']) == 1090
    why = j['_why']
    for must in ('было 690 → стало 1090', 'P95', 'P99', 'kazan-11908767', 'Следующий пересчёт'):
        assert must in why, must
    assert fc.door_time_limit() == 1090.0


def test_run_plan_arms_and_always_disarms(monkeypatch):
    seen = {}

    def boom(*a, **k):
        seen['armed'] = fc._DOOR_BUDGET['max']
        raise SystemExit('boom')

    monkeypatch.setattr(bench, '_run_plan', boom)
    with pytest.raises(SystemExit):
        bench.run_plan('X', '.', '.')
    assert seen['armed'] == fc.door_time_limit()
    assert fc._DOOR_BUDGET['max'] is None
