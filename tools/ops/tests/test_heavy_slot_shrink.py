"""T-162/2 · П1.116: бронь держателя по ФАКТУ (heavy_slot._holder_share / _holders_need / holders_report / head_report_due).
Без настоящих процессов: замки слотов подменены (`is_held`), память дерева — HEAVY_SLOT_MEM_STUB, /proc/meminfo — файл."""
import importlib.util
import json
import os
import sys
import time

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location('heavy_slot_t', os.path.join(HERE, '..', 'heavy_slot.py'))
hs = importlib.util.module_from_spec(spec)
sys.modules['heavy_slot_t'] = hs
spec.loader.exec_module(hs)

NOW = 1_800_000_000.0


class Env:
    def __init__(self, tmp, monkeypatch):
        self.d, self.mp, self.stub = str(tmp / 'slot'), monkeypatch, []
        os.makedirs(self.d + '/wait', exist_ok=True)
        monkeypatch.setenv('HEAVY_SLOT_DIR', self.d)
        monkeypatch.setenv('HEAVY_SLOT_LOG', str(tmp / 'hs.log'))
        monkeypatch.setenv('HEAVY_SLOT_MEM_STUB', str(tmp / 'stub'))
        monkeypatch.setenv('HEAVY_SLOT_MEMINFO', str(tmp / 'meminfo'))
        monkeypatch.setenv('HEAVY_SLOT_CPU_FACT', '0')
        monkeypatch.setenv('HEAVY_SLOT_CORES_BUDGET', '64')
        monkeypatch.setenv('HEAVY_SLOT_SLOTS', '5')
        self.tmp, self.held = tmp, set()
        monkeypatch.setattr(hs, 'is_held', lambda k=1: k in self.held)
        monkeypatch.setattr(hs.time, 'time', lambda: NOW)
        self.rules()
        self.mem(12.4)

    def mem(self, free, total=29.0):
        (self.tmp / 'meminfo').write_text(f'MemTotal: {int(total * 1048576)} kB\nMemAvailable: {int(free * 1048576)} kB\n')

    def rules(self, **kw):
        r = {'enabled': True, 'shrink_after_min': 15, 'margin': 1.5, 'floor_gb': 0.5, 'grow_guard_min': 5, 'head_report_min': 60, 'head_report_every_min': 30}
        r.update(kw)
        p = self.tmp / 'rules.json'
        p.write_text(json.dumps(r))
        os.utime(p, (NOW + len(str(kw)), NOW + len(str(kw)) + self.mp_ctr()))
        self.mp.setenv('HEAVY_SLOT_RULES', str(p))

    _c = 0

    def mp_ctr(self):
        Env._c += 1
        return Env._c

    def holder(self, k, label, th, used, peak=None, held_min=59.0, peak_ago_min=None, decl=None, eff=None):
        h = {'label': label, 'pid': 1, 'stage': 'работает', 'min_gb': decl if decl is not None else th, 'eff_gb': eff if eff is not None else th,
             'run_t': f'{NOW - held_min * 60:.2f}'}
        if peak is not None:
            h['peak_gb'] = f'{peak:.3f}'
            h['peak_t'] = f'{NOW - (peak_ago_min if peak_ago_min is not None else held_min) * 60:.2f}'
        hs._write_kv(hs._holder_file(self.d, k), h)
        with open(self.tmp / 'stub', 'a', encoding='utf-8') as f:
            f.write(f'{label} {used}\n')
        self.held.add(k)


@pytest.fixture
def env(tmp_path, monkeypatch):
    return Env(tmp_path, monkeypatch)


def _director_case(env):
    """Факты директора 22.11 11:40: ms04-recount — ручной порог 6,0, по факту 0,55 ГБ уже 59 мин; sh8b-g1 — порог 3,5, по факту 2,3."""
    env.holder(1, 'ms04-recount', 6.0, 0.55, peak=0.55)
    env.holder(2, 'sh8b-g1', 3.5, 2.3, peak=2.3)


def test_before_rule_head_is_blocked(env):
    env.rules(enabled=False)
    _director_case(env)
    need, _, any_h = hs._holders_need(env.d, 0, 5)
    assert any_h and need == pytest.approx(5.45 + 1.2)
    ok, *_ = hs._need(env.d, 0, 8.5, 5, 2.0, 0)
    assert not ok


def test_rule_shrinks_holders_to_fact_and_head_enters(env):
    env.rules(margin=1.3)
    _director_case(env)
    need, why, _ = hs._holders_need(env.d, 0, 5)
    assert need == pytest.approx((0.55 * 1.3 - 0.55) + (3.5 - 2.3) * 0 + (2.3 * 1.3 - 2.3), abs=0.02)   # 0,165 + 0,69
    assert 'по факту' in why
    ok, why, free, _ = hs._need(env.d, 0, 8.5, 5, 2.0, 0)
    assert ok, why


def test_default_margin_shrinks_but_close_to_fact(env):
    _director_case(env)                       # запас 1,5: sh8b почти не урезается (2,3×1,5=3,45 против 3,5)
    need, _, _ = hs._holders_need(env.d, 0, 5)
    assert need == pytest.approx(0.275 + 1.15)
    assert need < 6.65 / 4


def test_growing_holder_keeps_reservation(env):
    env.holder(1, 'grower', 6.0, 4.0, peak=4.0, held_min=59, peak_ago_min=1.0)     # пик вырос минуту назад
    sh = hs._holder_share(env.d, hs._read_kv(hs._holder_file(env.d, 1)))
    assert not sh['shrunk'] and sh['th'] == 6.0 and sh['part'] == pytest.approx(2.0)


def test_holder_near_threshold_keeps_reservation(env):
    env.holder(1, 'heavy', 6.0, 5.0, peak=5.0)                                      # пик 5,0 × 1,5 = 7,5 > 6,0 — урезать нечего
    sh = hs._holder_share(env.d, hs._read_kv(hs._holder_file(env.d, 1)))
    assert not sh['shrunk'] and sh['th'] == 6.0


def test_not_before_N_minutes(env):
    env.holder(1, 'young', 6.0, 0.5, peak=0.5, held_min=10)
    assert hs._holder_share(env.d, hs._read_kv(hs._holder_file(env.d, 1)))['th'] == 6.0
    env.holder(1, 'young', 6.0, 0.5, peak=0.5, held_min=16)
    assert hs._holder_share(env.d, hs._read_kv(hs._holder_file(env.d, 1)))['th'] < 6.0


def test_old_version_without_peak_not_shrunk(env):
    env.holder(1, 'old', 6.0, 0.5, peak=None)
    sh = hs._holder_share(env.d, hs._read_kv(hs._holder_file(env.d, 1)))
    assert not sh['shrunk'] and sh['th'] == 6.0


def test_never_below_used_floor_and_type_measure(env):
    env.holder(1, 'tiny', 6.0, 0.1, peak=0.1)
    assert hs._holder_share(env.d, hs._read_kv(hs._holder_file(env.d, 1)))['th'] == pytest.approx(0.5)       # пол floor_gb
    with open(env.d + '/peaks.tsv', 'w', encoding='utf-8') as f:
        f.write(f'{NOW}\ttiny\ttiny\t3.0\t3.0\t600\t6.0\t6.0\n')                                              # замер типа 3,0
    assert hs._holder_share(env.d, hs._read_kv(hs._holder_file(env.d, 1)))['th'] == pytest.approx(3.0)


def test_growth_after_shrink_returns_to_declared(env):
    env.holder(1, 'spike', 6.0, 7.0, peak=7.0, peak_ago_min=0.1)                                           # вырос выше заявки — как прежде: max(заявка, пик) − память
    sh = hs._holder_share(env.d, hs._read_kv(hs._holder_file(env.d, 1)))
    assert sh['over'] and sh['th'] == 7.0 and sh['part'] == 0.0


def test_meter_publishes_peak_always(env, tmp_path):
    p = hs._holder_file(env.d, 1)
    hs._write_kv(p, {'label': 'm', 'pid': str(os.getpid()), 'stage': 'работает', 'min_gb': 6})
    m = hs._Meter('m', os.getpid(), 5, 9999, p, 6.0)
    with open(tmp_path / 'stub', 'a', encoding='utf-8') as f:
        f.write('m 0.8\n')
    m.sample()
    h = hs._read_kv(p)
    assert float(h['peak_gb']) == pytest.approx(0.8) and 'peak_t' in h            # пик ниже порога тоже виден другим
    assert not m.over_told


def test_head_report_due_and_lines(env):
    assert not hs.head_report_due(59 * 60, 0.0, NOW)
    assert hs.head_report_due(61 * 60, 0.0, NOW)
    assert not hs.head_report_due(90 * 60, NOW - 10 * 60, NOW)                     # повтор не чаще раза в 30 мин
    assert hs.head_report_due(90 * 60, NOW - 31 * 60, NOW)
    _director_case(env)
    lines = hs.holders_report(env.d, 5, NOW)
    assert any('ms04-recount' in x and 'держит 59 мин' in x and 'заявка 6' in x and 'пик прогона 0.55' in x for x in lines)
    assert lines[-1].startswith('итого бронь держателей')


def test_rules_file_missing_or_broken_uses_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv('HEAVY_SLOT_RULES', str(tmp_path / 'нет.json'))
    assert hs.rules()['shrink_after_min'] == 15
    (tmp_path / 'bad.json').write_text('{oops')
    monkeypatch.setenv('HEAVY_SLOT_RULES', str(tmp_path / 'bad.json'))
    assert hs.rules()['margin'] == 1.5


def test_repo_rules_file_matches_defaults():
    raw = json.load(open(os.path.join(HERE, '..', 'rules', 'heavy-slot.json'), encoding='utf-8'))
    for k, v in hs._RULES_DEF.items():
        assert raw[k] == v, k
