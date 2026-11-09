"""Замер спален на загруженном плане (T-20261109-15): временный перевод + цепочка назначений + тестовые случаи.

Случаи `fixtures/trial-bedrooms/*.json` — для будущего адаптера спален (agent-trial-04-bedroom): формат
`{"_about", "_expect", "result": floorplanResult}`; `_expect` — по факту нынешнего солвера (замер 09.11).
"""
from __future__ import annotations

import glob
import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import trial_bedroom_probe as tb  # noqa: E402

FX = os.path.join(HERE, 'fixtures', 'trial-bedrooms')
FILES = sorted(glob.glob(os.path.join(FX, '*.json')))


def _ri(w, d, openings, rings=None):
    return tb.RoomIn('t', 'p', 'r1', 'Bedroom', rings or [[(0, 0), (w, 0), (w, d), (0, d)]], openings)


# ── вход ──────────────────────────────────────────────────────────────────────────────────────────────
def test_bench_model_metres_to_cm_and_names():
    m = {'plan': 'X', 'panel': 'First', 'rooms': [
        {'id': 1, 'names': ['Bedroom 2'], 'area_m2': 10},
        {'id': 2, 'names': ['Bathroom'], 'area_m2': 4},
        {'id': 3, 'names': ['Bedroom 3', 'En-suite'], 'area_m2': 9}],
         'floors': [{'room': 1, 'outer': [[0, 0], [3, 0], [3, 3.5], [0, 3.5]], 'holes': []},
                    {'room': 2, 'outer': [[3, 0], [5, 0], [5, 2], [3, 2]], 'holes': []},
                    {'room': 3, 'outer': [[5, 0], [8, 0], [8, 3], [5, 3]], 'holes': []}],
         'openings': [{'kind': 'door', 'c': [1, 3.5], 'width_m': 0.8, 'exterior': False}]}
    rooms = tb.from_bench_model(m)
    assert [r.name for r in rooms] == ['Bedroom 2', 'Bedroom 3']
    assert rooms[0].rings[0][2] == (300, 350)
    assert rooms[0].openings[0]['c'] == (100, 350) and rooms[0].openings[0]['width'] == 80
    assert rooms[1].flags == ['mixed_names']


@pytest.mark.parametrize('name,ok', [('Bedroom 1', True), ('Master Bedroom', True), ('Box Room', True),
                                     ('Bed 4', True), ('En-suite', False), ('Bathroom', False), ('Landing', False)])
def test_bedroom_names(name, ok):
    assert bool(tb._is_bedroom([name])) is ok


# ── перевод: стена, смещение, захват ──────────────────────────────────────────────────────────────────
def test_wall_and_offset_mapping():
    # 300×400; лист: y вниз. Окно сверху (north), дверь снизу (south) у левого края, окно справа (east) по центру
    ops = [{'kind': 'window', 'c': (150, 0), 'width': 120, 'exterior': True},
           {'kind': 'door', 'c': (50, 400), 'width': 80, 'exterior': False},
           {'kind': 'window', 'c': (300, 100), 'width': 100, 'exterior': False}]
    room, info = tb.to_room(_ri(300, 400, ops))
    by = {(o.kind, o.wall): o for o in room.openings}
    assert by[('window', 'north')].offset_cm == 90          # 150 − 60, запад→восток
    assert by[('door', 'south')].offset_cm == 10 and by[('door', 'south')].swing_cm == 80
    # восток: смещение юг→север; центр в 100 от верха листа = 300 от низа → 300 − 50
    assert by[('window', 'east')].offset_cm == 250
    assert len(room.radiators) == 1 and room.radiators[0].wall == 'north'   # радиатор — только под наружным
    assert info['fill'] == 1.0 and 'not_rect' not in info['flags']


def test_snap_tolerance_and_far_openings_ignored():
    ops = [{'kind': 'door', 'c': (150, 400 + tb.SNAP_CM - 5), 'width': 80, 'exterior': False},   # за стеной — ещё эта
           {'kind': 'window', 'c': (150, 200), 'width': 100, 'exterior': True},                  # посреди — не эта
           {'kind': 'door', 'c': (900, 50), 'width': 80, 'exterior': False}]                     # чужая комната
    room, info = tb.to_room(_ri(300, 400, ops))
    assert [(o.kind, o.wall) for o in room.openings] == [('door', 'south')]
    assert 'no_window' in info['flags']


def test_wide_door_swing_capped_and_clipped():
    room, info = tb.to_room(_ri(200, 300, [{'kind': 'door', 'c': (100, 300), 'width': 260, 'exterior': False}]))
    d = room.openings[0]
    assert d.width_cm == 198 and d.swing_cm == tb.DOOR_SWING_MAX
    assert 'opening_clipped:door' in info['flags']


def test_tiny_window_radiator_inside_wall():
    room, _ = tb.to_room(_ri(300, 300, [{'kind': 'window', 'c': (5, 0), 'width': 14, 'exterior': True}]))
    r = room.radiators[0]
    assert r.width_cm <= 14 and 0 <= r.offset_cm <= 300 - r.width_cm


def test_l_shape_flags_not_rect():
    ring = [(0, 0), (400, 0), (400, 200), (250, 200), (250, 350), (0, 350)]
    _, info = tb.to_room(_ri(0, 0, [], rings=[ring]))
    assert 'not_rect' in info['flags'] and info['fill'] < 0.95


# ── цепочка назначений по UK NDSS ─────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize('w,d,first,flag', [
    (350, 400, 'couple', False),          # 14 м², 3,5 м
    (330, 350, 'couple', False),          # 11,55 м², короткая 3,3
    (250, 480, 'single', False),          # 12 м², но уже 2,55 → не пара
    (300, 330, 'single', False),          # 9,9 м²: малая двуспальная
    (244, 333, 'single_narrow', False),   # 8,1 м²
    (210, 400, 'single_narrow', True),    # уже 2,15
    (190, 230, 'single_narrow', True),    # 4,4 м²
])
def test_chain(w, d, first, flag):
    order, flags = tb.chain(w, d)
    assert order[0] == first and order[-1] == 'single_narrow'
    assert ('below_ndss_single' in flags) is flag


def test_outside_floor_tolerates_skewed_edge_but_catches_niche():
    # пол косой на 2 см (как у стенда) — мебель к bbox-стене не «вне пола»
    skew = [(0, 0), (300, 2), (300, 400), (0, 400)]
    room, info = tb.to_room(_ri(0, 0, [{'kind': 'door', 'c': (50, 400), 'width': 80, 'exterior': False}], rings=[skew]))
    r = tb.solve_one(room, 'single', info['_floor'])
    assert r['placed'] and r['outside_floor'] == []
    # Г-форма: вырез 150×150 в углу — что встало в вырез, ловится
    ring = [(0, 0), (250, 0), (250, 150), (400, 150), (400, 350), (0, 350)]
    room, info = tb.to_room(_ri(0, 0, [{'kind': 'door', 'c': (50, 350), 'width': 80, 'exterior': False}], rings=[ring]))
    r = tb.solve_one(room, 'single', info['_floor'])
    lay = r['_lay']
    cut = tb.Polygon([(250, 200), (400, 200), (400, 350), (250, 350)])   # вырез в координатах солвера (y вверх)
    inside_cut = {p.role for p in lay.placements if tb.footprint(p).intersection(cut).area > 100}
    assert inside_cut <= set(r['outside_floor'])


def test_slot_kit_only_slot_roles():
    roles = {tb.bedroom_role(x.role) for x in tb.slot_kit('couple')}
    assert 'кровать' in roles and roles <= {'кровать', 'тумба прикроватная', 'шкаф', 'комод'}


# ── тестовые случаи: структура (контракт floorplanResult, минимум без jsonschema) ──────────────────────
def test_fixture_set_present():
    names = {os.path.basename(f) for f in FILES}
    assert {'narrow-single.json', 'door-corner.json', 'wardrobe-niche.json', 'two-windows.json',
            'too-small.json'} <= names


@pytest.mark.parametrize('path', FILES, ids=os.path.basename)
def test_fixture_contract_shape(path):
    d = json.load(open(path, encoding='utf-8'))
    assert d['_about'] and isinstance(d['_expect'], dict)
    res = d['result']
    assert res['version'] == 1 and res['units'] == 'cm' and res['panels']
    for p in res['panels']:
        for r in p['rooms']:
            assert r['kind'] in ('living', 'bedroom', 'kitchen', 'bathroom', 'hall', 'other')
            xs = [x for x, _ in r['contour']]
            ys = [y for _, y in r['contour']]
            b = r['bbox']
            assert abs(b['x'] - min(xs)) <= 1 and abs(b['w'] - (max(xs) - min(xs))) <= 1
            assert abs(b['y'] - min(ys)) <= 1 and abs(b['d'] - (max(ys) - min(ys))) <= 1
            assert abs(tb._area([tuple(pt) for pt in r['contour']]) / 1e4 - r['areaM2']) < 0.05
        for o in p['openings']:
            assert o['kind'] in ('door', 'window', 'opening') and len(o['c']) == 2 and o['widthCm'] > 0


# ── тестовые случаи: решение нынешним солвером против `_expect` ────────────────────────────────────────
@pytest.mark.parametrize('path', FILES, ids=os.path.basename)
def test_fixture_expectations(path):
    rooms, exp = tb.load(path)
    assert len(rooms) == 1
    rec = tb.probe_room(rooms[0])
    best = rec['_best']
    if 'pick' in exp:
        assert rec['pick'] == exp['pick'], (rec['pick'], rec.get('refusal'), best['hard'], best['outside_floor'])
    if 'chain' in exp:
        assert rec['chain'] == exp['chain']
    for f in exp.get('flags_include', []):
        assert f in rec['flags']
    if 'refusal_any' in exp:
        assert rec['pick'] is None and any(c in rec['refusal'] for c in exp['refusal_any'])
    if 'outside_includes' in exp:
        assert exp['outside_includes'] in best['outside_floor']
    if rec['pick']:
        assert not best['hard'] and not best['outside_floor']
        bed_w = max(float(s.split('×')[0]) for s in best['placed']['кровать'])
        assert bed_w >= exp.get('bed_w_min', 0) and bed_w <= exp.get('bed_w_max', 999)
        for c in exp.get('soft_exclude', []):
            assert c not in best['soft']
    if 'radiators' in exp:
        assert len(best['_room'].radiators) == exp['radiators']
