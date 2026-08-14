"""Пакет G свода №8 (MASTER-zones-v2): новые оси — только измерение, без порогов."""
from planner.models import Item, Opening, Placement, Room
from planner.quality import (residual_fragmentation, route_active_dining_cm,
                             route_width_cm, visual_balance)


def _p(role, x, y, rot, w, d, h=80, **kw):
    return Placement(role=role, x=x, y=y, rot=rot,
                     item=Item(role=role, w_cm=w, d_cm=d, h_cm=h, **kw))


def test_fragmentation_counts_pockets():
    room = Room(width_cm=400, depth_cm=400)
    # шкаф-перегородка почти во всю ширину делит пол на два куска
    wall = _p('шкаф', 200, 200, 0, 400, 60, 220)
    out = residual_fragmentation(room, [wall])
    assert out['components'] >= 2
    empty = residual_fragmentation(room, [])
    assert empty['components'] == 1


def test_visual_balance_detects_one_sided_mass():
    room = Room(width_cm=400, depth_cm=400)
    west_heavy = [_p('диван', 60, 200, 90, 220, 95),
                  _p('шкаф', 40, 340, 90, 120, 60, 220)]
    b = visual_balance(room, west_heavy)
    assert b['west_share'] > 0.9
    assert b['centroid_offset_pct'] > 20


def test_active_dining_route_not_wider_than_static():
    room = Room(width_cm=460, depth_cm=420,
                openings=[Opening(kind='door', wall='south', offset_cm=40, width_cm=90)])
    ps = [_p('диван', 230, 370, 180, 200, 95),
          _p('стол обеденный', 340, 140, 0, 110, 70, 75),
          _p('стул', 340, 55, 0, 45, 50, 90),
          _p('стул 2', 340, 225, 180, 45, 50, 90)]
    static = route_width_cm(room, ps)
    active = route_active_dining_cm(room, ps)
    assert active is not None and active <= static
    # без столовой — None (ось не применима)
    assert route_active_dining_cm(room, [ps[0]]) is None
