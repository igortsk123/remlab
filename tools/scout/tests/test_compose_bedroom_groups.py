"""Сборщик спальни при движке групп (T-20261112-38/2, план bedroom-groups-01, ADR-0384): ступень 140 для пары (только движок
групп), суд банка берёт спальное место ступени из записи, «одна тумба» с причиной — предупреждение, ковёр по варианту «сна»
(пара тумб — симметрично). Без базы и сети.

  /home/pakar/venvs/scout/bin/python -m pytest tools/scout/tests/test_compose_bedroom_groups.py
"""
from __future__ import annotations

import os
import sys

import pytest

SCOUT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SCOUT)

import compose_bedroom as CB  # noqa: E402

sys.path.insert(0, CB.SOLVER)
from planner.bedroom import solve_bedroom  # noqa: E402
from planner.models import Item  # noqa: E402


@pytest.fixture
def composer():
    R = CB.rules()
    return CB.Composer([], [], set(), set(), R, CB.tolerance(), 0.5)


def test_step140_only_groups_couple(composer, monkeypatch):
    monkeypatch.setenv('BEDROOM_ENGINE', 'items')
    assert composer.step140('couple') is None                    # поштучный движок (откат) — как было
    monkeypatch.delenv('BEDROOM_ENGINE', raising=False)          # по умолчанию groups (T-20261112-47)
    sl = composer.step140('couple')
    assert sl['sleep_w'] == [140, 140] and sl['step'] == 140 and sl['ideal']['w'] == 155 and sl['role'] == 'кровать'
    assert composer.step140('single') is None


def test_gate_step140_slot(composer, monkeypatch):
    monkeypatch.setenv('BEDROOM_ENGINE', 'groups')
    sl = composer.step140('couple')
    band = CB.band_of(sl, composer.tol)
    bed140 = {'role': 'кровать', 'w': 150, 'd': 210, 'h': 100, 'sleep_w': 140, 'footprint_ok': True}
    assert CB.gate(bed140, sl, band) is None
    base = next(s for s in composer.R['purposes']['couple']['slots'] if s['role'] == 'кровать')
    assert CB.gate(bed140, base, CB.band_of(base, composer.tol)) is not None     # в общий слот 160–180 не годится


def _bank_rec(lay, room_spec, purpose='couple', ns_qty=2, slots_extra=None):
    items = {'кровать': {'sid': 'b', 'w': 175, 'd': 215, 'h': 110, 'sleep_w': 160},
             'тумба прикроватная': {'sid': 'n', 'w': 45, 'd': 40, 'h': 55, 'qty': ns_qty},
             'комод': {'sid': 'k', 'w': 100, 'd': 45, 'h': 85}}
    slots = {r: {'ideal': {'w': x['w'], 'd': x['d'], 'h': x['h']}, 'band': {}} for r, x in items.items()}
    slots['кровать']['ideal'] = {'w': 175, 'd': 215, 'h': 110}
    for r, v in (slots_extra or {}).items():
        slots[r].update(v)
    layout = {p.role: {'x': p.x, 'z': p.y, 'rot': int(p.rot), 'w': p.item.w_cm, 'd': p.item.d_cm, 'h': p.item.h_cm}
              for p in lay.placements}
    layout['_room'] = dict(room_spec)
    layout['_meta'] = {'sleep_variant': lay.meta.get('sleep_variant')}
    return {'set_id': 's1', 'room_id': 'bedroom-1', 'room_type': 'bedroom', 'purpose': purpose, 'style': 'сканди',
            'tier': 'комфорт', 'cell': 'c', 'items': items, 'slots': slots, 'layout': layout,
            'alternates': {r: [{}] * CB.SPARE_MIN for r in items}}


def test_check_bank_one_side_is_warning(composer, monkeypatch):
    monkeypatch.setenv('BEDROOM_ENGINE', 'groups')
    spec = CB.room_spec('bedroom-1', 'registry-17.5')
    room = CB._room_model(spec, 'couple')
    lay = solve_bedroom(room, [Item(role='кровать', w_cm=175, d_cm=215, h_cm=110),
                               Item(role='тумба прикроватная', w_cm=45, d_cm=40, h_cm=55),
                               Item(role='комод', w_cm=100, d_cm=45, h_cm=85)])
    rec = _bank_rec(lay, spec, ns_qty=1)
    rec['layout']['_meta']['sleep_variant'] = 'one_side'
    probs = [p for p in CB.check_bank([rec], composer.R, composer.tol) if 'тумб' in p]
    assert probs and all(p.startswith('~') for p in probs)
    rec['layout']['_meta']['sleep_variant'] = None
    probs = [p for p in CB.check_bank([rec], composer.R, composer.tol) if 'тумб' in p]
    assert probs and not probs[0].startswith('~')


def test_check_bank_step140_sleep_w_from_record(composer):
    spec = CB.room_spec('bedroom-1', 'registry-17.5')
    room = CB._room_model(spec, 'couple')
    lay = solve_bedroom(room, [Item(role='кровать', w_cm=155, d_cm=215, h_cm=110)])
    rec = _bank_rec(lay, spec)
    rec['items']['кровать'].update(w=155, sleep_w=140)
    rec['slots']['кровать'].update(ideal={'w': 155, 'd': 215, 'h': 110}, band={})
    assert any('спальное место' in p for p in CB.check_bank([rec], composer.R, composer.tol))
    rec['slots']['кровать'].update(sleep_w=[140, 140], step=140)
    assert not any('спальное место' in p for p in CB.check_bank([rec], composer.R, composer.tol))


def test_rug_pair_symmetric(monkeypatch):
    """Пара тумб (sleep_variant=pair) — ковёр симметрично, «бок у стены» не ищем; без варианта — как было."""
    spec = CB.room_spec('bedroom-1', 'registry-17.5')
    room = CB._room_model(spec, 'couple')
    lay = solve_bedroom(room, [Item(role='кровать', w_cm=175, d_cm=215, h_cm=110),
                               Item(role='тумба прикроватная', w_cm=45, d_cm=40, h_cm=55),
                               Item(role='тумба прикроватная 2', w_cm=45, d_cm=40, h_cm=55)], engine='groups')
    assert lay.meta['sleep_variant'] == 'pair'
    called = []
    monkeypatch.setattr(CB, '_bed_wall_sides', lambda *a: called.append(1) or {'left': 0.0})
    f = CB.rug_place(lay, room, {'w': 300, 'd': 200}, fit={'wall_side': True, 'overhang_tolerated': True})
    assert not called
    assert f is None or abs(f['fit']['side'] - (300 - 175) / 2) < 0.6 or abs(f['fit']['side'] - (200 - 175) / 2) < 0.6
    lay.meta.pop('sleep_variant')
    CB.rug_place(lay, room, {'w': 300, 'd': 200}, fit={'wall_side': True, 'overhang_tolerated': True})
    assert called


# ── T-20261112-95: лестница тумб пары (rules nightstand_steps: узкие → подвесные) ──

class _Lay:
    def __init__(self, variant, level, mode='target'):
        self.meta = {'engine': 'groups', 'sleep_variant': variant, 'sleep_why': None if variant == 'pair' else 'NIGHTSTAND_NO_FIT',
                     'composition': {'template': 'br.pair_axis', 'level': level}, 'clearance': {'mode': mode}}


def _res(variant, level, mode='target', ns=True):
    ch = {'кровать': {'fam': 'B'}}
    if ns:
        ch['тумба прикроватная'] = {'fam': 'N', 'qty': 2 if variant == 'pair' else 1}
    return {'layout': _Lay(variant, level, mode), 'chosen': ch, 'slots': {'кровать': {}}}


def test_nightstand_steps_slots_in_rules(composer):
    """Ступени — в правилах пары: узкие 26–36 × 26–35 (идеал 45×40 туда не входит), подвесные — по слову в имени."""
    steps = {s['id']: s for s in composer.R['purposes']['couple']['nightstand_steps']}
    assert list(steps) == ['slim', 'wall_hung']
    base = next(s for s in composer.R['purposes']['couple']['slots'] if s['role'] == 'тумба прикроватная')
    slim = dict(base, **{k: v for k, v in steps['slim'].items() if not k.startswith('_') and k != 'id'})
    band = CB.band_of(slim, composer.tol)
    ok = {'role': 'тумба прикроватная', 'w': 35, 'd': 32, 'h': 50}
    assert CB.gate(ok, slim, band) is None
    assert CB.gate(dict(ok, w=45, d=40), slim, band) is not None
    assert steps['wall_hung']['name_re'] == 'подвесн'
    assert 'nightstand_steps' not in composer.R['purposes']['single']      # одному — одна тумба, лестница не нужна


def test_nightstand_steps_pick_better_level(composer, monkeypatch):
    """Пара без тумб (C) → узкие дали обе тумбы (A) — берём узкие, подвесные уже не пробуем; пара тумб — ступеней нет."""
    calls = []

    def fake(room_id, purpose, style, tier, spec, built, used, bed_slot=None, ns_slot=None):
        calls.append(ns_slot['step'])
        return _res('pair', 'A') if ns_slot['step'] == 'slim' else _res('one_side', 'B')
    monkeypatch.setattr(composer, '_build', fake)
    got = composer.nightstand_steps(_res('solo', 'C', ns=False), 'bedroom-2', 'couple', 'сканди', 'комфорт', {}, [], {})
    assert got['ns_step'] == 'slim' and got['layout'].meta['sleep_variant'] == 'pair' and calls == ['slim']
    assert got['ns_step_why'] == 'NIGHTSTAND_NO_FIT' and got['ns_steps_tried'] == ['slim: pair · A']
    calls.clear()
    same = _res('pair', 'A', mode='compact')
    assert composer.nightstand_steps(same, 'bedroom-2', 'couple', 'сканди', 'комфорт', {}, [], {}) is same and not calls


class _P:
    def __init__(self, role):
        self.role = role


class _L:
    def __init__(self, roles, mode, target_level):
        self.placements = [_P(r) for r in roles]
        self.meta = {'clearance': {'mode': mode, 'target_level': target_level}}


def test_sleep_ladder_only_is_spare_in_free_wall(composer, monkeypatch):
    """Перебор ширины шкафа: раскладка «compact ради тумб» (по цели тоже принята) — запас, берётся первая по цели, как до лестницы;
    по цели нет ни одной — запас. compact без цели (цель — отказ) — как раньше, сразу."""
    import planner.bedroom as PB
    assert CB.sleep_ladder_only(_L([], 'compact', 'C')) and not CB.sleep_ladder_only(_L([], 'compact', None))
    assert not CB.sleep_ladder_only(_L([], 'target', 'A'))
    roles = ['кровать', 'тумба прикроватная', 'тумба прикроватная 2', 'шкаф']
    base = [Item(role=r, w_cm=40, d_cm=40, h_cm=50) for r in roles[:3]]
    slot = {'ideal': {'w': 150, 'd': 60, 'h': 220}, 'band': ['w', 'd', 'h']}
    monkeypatch.setattr(PB, 'solve_bedroom', lambda room, items, p: _L(roles, 'target', 'A') if items[-1].w_cm <= 120
                        else _L(roles, 'compact', 'C'))
    assert composer.free_wall(None, base, slot, 'couple') == (120, 60)
    monkeypatch.setattr(PB, 'solve_bedroom', lambda room, items, p: _L(roles, 'compact', 'C'))
    assert composer.free_wall(None, base, slot, 'couple')[0] == int(150 * composer.tol[1] // 5 * 5)


def test_nightstand_steps_keep_base_when_not_better(composer, monkeypatch):
    """Ступени не подняли уровень (нет товара / тот же уровень, только compact) — остаётся исходный набор, попытки записаны."""
    def fake(room_id, purpose, style, tier, spec, built, used, bed_slot=None, ns_slot=None):
        return {'empty': 'NO_FIT_AFTER_TRIES'} if ns_slot['step'] == 'slim' else _res('one_side', 'B', mode='compact')
    monkeypatch.setattr(composer, '_build', fake)
    base = _res('one_side', 'B')
    got = composer.nightstand_steps(base, 'bedroom-2', 'couple', 'сканди', 'комфорт', {}, [], {})
    assert 'ns_step' not in got and got['layout'] is base['layout']
    assert got['ns_steps_tried'] == ['slim: NO_FIT_AFTER_TRIES', 'wall_hung: one_side · B']
