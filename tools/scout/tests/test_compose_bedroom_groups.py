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
