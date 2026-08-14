"""Пакет A свода №8 (MASTER-zones-v2): паспорт dining — source of truth.

Сторожа: seats_by_area / edge_per_diner_cm / operational_envelope_cm реально
ЧИТАЮТСЯ кодом (не хардкод), envelope-классификатор island/edge работает.
"""
from shapely.geometry import box

from planner.invariants import TEMPLATES
from planner.models import Item, Placement
from planner.template import (build_dining, dining_envelope_cm,
                              dining_envelope_ok, dining_seats_cap)


def test_seats_cap_matches_passport():
    sba = TEMPLATES['zones']['dining']['rules']['seats_by_area']
    assert dining_seats_cap(15) == sba['<=18']
    assert dining_seats_cap(25) == sba['<=30']
    assert dining_seats_cap(45) == sba['>30']


def test_seats_cap_is_wired_not_hardcoded():
    rules = TEMPLATES['zones']['dining']['rules']
    orig = rules['seats_by_area']
    try:
        rules['seats_by_area'] = {'<=18': 3, '<=30': 5, '>30': 7}
        assert dining_seats_cap(15) == 3
        assert dining_seats_cap(45) == 7
    finally:
        rules['seats_by_area'] = orig


def test_envelope_cm_from_passport():
    assert dining_envelope_cm() == float(
        TEMPLATES['zones']['dining']['rules']['operational_envelope_cm'])


def _table(x, y, rot=0.0):
    it = Item(role='стол обеденный', w_cm=110, d_cm=70, h_cm=75)
    return Placement(role=it.role, x=x, y=y, rot=rot, item=it)


def test_envelope_island_center_ok_wall_not():
    free = box(0, 0, 500, 500)
    assert dining_envelope_ok(_table(250, 250), free, sides='all')
    # стол спинкой к южной стене (35 = d/2) — остров невозможен
    assert not dining_envelope_ok(_table(250, 35), free, sides='all')


def test_envelope_edge_mode_asymmetric():
    free = box(0, 0, 500, 500)
    # та же пристенная позиция: edge-режим (rot 0 — фронт на север, тыл у юга)
    # envelope не требует юга → валидна
    assert dining_envelope_ok(_table(250, 35, rot=0.0), free, sides='front')
    # но в углу (торец без envelope) — нет
    assert not dining_envelope_ok(_table(60, 35, rot=0.0), free, sides='front')


def test_pair_needs_passport_edge_per_diner():
    edge = float(TEMPLATES['zones']['dining']['rules']['edge_per_diner_cm'])
    chairs = {f'стул{"" if i == 0 else f" {i + 1}"}':
              Item(role=f'стул{"" if i == 0 else f" {i + 1}"}',
                   w_cm=45, d_cm=50, h_cm=90) for i in range(4)}
    # кромка чуть короче 2×edge_per_diner: пары по длинной стороне запрещены,
    # даже если чисто физически стулья влезали (2×45+24=114)
    tbl = Item(role='стол обеденный', w_cm=2 * edge - 4, d_cm=80, h_cm=75)
    b = build_dining({'стол обеденный': tbl, **chairs}, 4, sides='all')
    assert b is not None
    xs = [round(x, 1) for _, x, y, r in b.rel[1:]]
    # все стулья на осях: длинные стороны по x=0, торцы по |x|=w/2 (пар нет)
    assert all(abs(x) < 1 or abs(abs(x) - tbl.w_cm / 2) < 30 for x in xs)
    # достаточная кромка — пары появляются
    tbl2 = Item(role='стол обеденный', w_cm=2 * edge + 20, d_cm=80, h_cm=75)
    b2 = build_dining({'стол обеденный': tbl2, **chairs}, 4, sides='all')
    assert b2 is not None
    assert any(0 < abs(round(x, 1)) < tbl2.w_cm / 2 - 20 for _, x, y, r in b2.rel[1:])
