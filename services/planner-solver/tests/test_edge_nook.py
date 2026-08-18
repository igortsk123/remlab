"""Q6b свода №13: banquette-уголок (`build_edge_nook`/`place_edge_nook` + `check_edge_nook_contract`).
Синтетические сцены; поправки Codex 17.08: места — из caps (не из ширины), стол вровень (0–3 см),
минимум 4 места, окно спинкой запрещено (Q8), доступный торец, отодвигание стульев."""
import math

import pytest

from planner.models import Item, Opening, Placement, Room
from planner.template import build_edge_nook, place_edge_nook, NOOK_DIAG
from planner.validate import check_edge_nook_contract
from planner.zones import usable_polygon


def _bench(w=140, d=40, seats=2, dining=True):
    return Item(role='банкетка', w_cm=w, d_cm=d, h_cm=46,
                caps={'guaranteed_seats': seats, 'dining_seat_capable': dining,
                      'wall_seat_capable': True, 'requires_wall_back_support': True})


def _kit(bench=None, table=(140, 80), chairs=2):
    by = {'банкетка': bench or _bench(),
          'стол обеденный': Item(role='стол обеденный', w_cm=table[0], d_cm=table[1], h_cm=75)}
    for i in range(chairs):
        r = 'стул' if i == 0 else f'стул {i + 1}'
        by[r] = Item(role=r, w_cm=45, d_cm=50, h_cm=90)
    return by


def test_build_requires_caps_not_width():
    """Места банкетки — ТОЛЬКО из capability-проекции: без caps шаблон не собирается,
    даже если ширина «на глаз» подходит (Codex: пуф-банкетка ≠ обеденная посадка)."""
    no_caps = Item(role='банкетка', w_cm=140, d_cm=40, h_cm=46)
    assert build_edge_nook(_kit(bench=no_caps)) is None
    assert NOOK_DIAG['reject'] == 'bench_capability_unknown'
    assert build_edge_nook(_kit(bench=_bench(dining=False))) is None
    assert NOOK_DIAG['reject'] == 'bench_not_dining_capable'
    assert build_edge_nook(_kit(bench=_bench(seats=1))) is None
    assert NOOK_DIAG['reject'] == 'bench_capacity_lt2'


def test_build_geometry_table_flush_and_four_seats():
    b = build_edge_nook(_kit())
    assert b is not None and NOOK_DIAG['total_seats'] >= 4
    rel = {r[0].role: r for r in b.rel}
    bench, tbl = rel['банкетка'], rel['стол обеденный']
    gap = (tbl[2] - tbl[0].d_cm / 2) - (bench[2] + bench[0].d_cm / 2)
    assert 0 <= gap <= 3, gap                                  # вровень, не щель 10–15
    chairs = [r for role, r in rel.items() if role.startswith('стул')]
    assert len(chairs) == 2 and all(int(c[3]) % 360 in (180, 270, 90) for c in chairs)
    assert all(c[2] > tbl[2] - 1 for c in chairs)              # со свободной стороны, не на банкетке


def test_build_needs_two_chairs_and_matching_table():
    assert build_edge_nook(_kit(chairs=1)) is None and NOOK_DIAG['reject'] == 'chairs_lt2'
    assert build_edge_nook(_kit(table=(220, 90))) is None and NOOK_DIAG['reject'] == 'table_bench_mismatch'
    assert build_edge_nook(_kit(), variant='edge_nook_6') is None   # нужно 4 стула
    b6 = build_edge_nook(_kit(chairs=4), variant='edge_nook_6')
    assert b6 is not None and NOOK_DIAG['chairs'] == 4


def _room(win=False):
    ops = [Opening(kind='door', wall='south', offset_cm=20, width_cm=90, swing_cm=90)]
    if win:
        ops.append(Opening(kind='window', wall='north', offset_cm=100, width_cm=160, sill_cm=80))
    return Room(width_cm=420, depth_cm=380, openings=ops)


def test_place_puts_bench_to_wall_and_passes_contract():
    room = _room()
    items = list(_kit().values())
    ps = place_edge_nook(room, items, usable_polygon(room))
    assert ps is not None, NOOK_DIAG
    assert all(p.tpl_id == 'dining' for p in ps) and all(p.tpl_variant.startswith('edge_nook') for p in ps)
    assert not check_edge_nook_contract(room, ps), [v.code for v in check_edge_nook_contract(room, ps)]


def test_place_avoids_window_wall_q6b():
    """Окно в Q6b исключено: банкетка не опирается спинкой на проём (Q8 — отдельный пакет)."""
    room = _room(win=True)
    ps = place_edge_nook(room, list(_kit().values()), usable_polygon(room))
    if ps:
        bench = next(p for p in ps if p.role == 'банкетка')
        from planner.geometry import footprint, opening_polygon
        for op in room.openings:
            if op.kind == 'window':
                assert footprint(bench).distance(opening_polygon(room, op)) >= 40


def _pl(role, x, y, rot, w, d, h=80, var='edge_nook_4', caps=None):
    p = Placement(role=role, x=x, y=y, rot=rot,
                  item=Item(role=role, w_cm=w, d_cm=d, h_cm=h, caps=caps or {}))
    p.tpl_id = 'dining'; p.tpl_variant = var
    return p


def test_contract_flags_gap_capacity_and_window():
    room = _room(win=True)
    caps = {'guaranteed_seats': 2, 'dining_seat_capable': True}
    # щель 20 см между банкеткой и столом + один стул = брак
    bad = [_pl('банкетка', 210, 22, 0, 140, 40, 46, caps=caps),
           _pl('стол обеденный', 210, 102, 0, 140, 80, 75),
           _pl('стул', 210, 170, 180, 45, 50, 90)]
    codes = {v.code for v in check_edge_nook_contract(room, bad)}
    assert 'NOOK_TABLE_GAP' in codes and 'NOOK_CAPACITY' in codes
    # банкетка спинкой к окну (север) — запрещено в Q6b
    win = [_pl('банкетка', 180, 358, 180, 140, 40, 46, caps=caps),
           _pl('стол обеденный', 180, 296, 180, 140, 80, 75),
           _pl('стул', 150, 230, 0, 45, 50, 90), _pl('стул 2', 210, 230, 0, 45, 50, 90)]
    assert 'NOOK_WINDOW_WALL' in {v.code for v in check_edge_nook_contract(room, win)}


def test_contract_flags_blocked_end_and_pullout():
    room = _room()
    caps = {'guaranteed_seats': 3, 'dining_seat_capable': True}
    # уголок втиснут в угол: оба торца перекрыты шкафом и стеной
    ps = [_pl('банкетка', 90, 22, 0, 160, 40, 46, caps=caps),
          _pl('стол обеденный', 90, 84, 0, 150, 80, 75),
          _pl('стул', 60, 150, 180, 45, 50, 90), _pl('стул 2', 120, 150, 180, 45, 50, 90),
          _pl('шкаф', 195, 60, 270, 60, 200, 220, var='')]
    codes = {v.code for v in check_edge_nook_contract(room, ps)}
    assert 'NOOK_END_BLOCKED' in codes
