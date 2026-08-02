from math import isclose

from planner.geometry import (
    access_zone,
    facing_vector,
    floor_used_pct,
    footprint,
    free_space,
    largest_free_rectangles,
    quantize_rot,
    room_polygon,
)
from planner.models import Item, Opening, Placement, Room

SOFA = Item(role="диван", w_cm=200, d_cm=90, h_cm=85)


def _room(w=400, d=460, **kw):
    return Room(width_cm=w, depth_cm=d, **kw)


def test_footprint_axis_rotations_swap_dims():
    p0 = Placement(role="диван", x=200, y=200, rot=0, item=SOFA)
    p90 = Placement(role="диван", x=200, y=200, rot=90, item=SOFA)
    x0, y0, x1, y1 = footprint(p0).bounds
    a0, b0, a1, b1 = footprint(p90).bounds
    assert isclose(x1 - x0, 200) and isclose(y1 - y0, 90)
    assert isclose(a1 - a0, 90) and isclose(b1 - b0, 200)


def test_facing_and_quantization():
    assert [round(v) for v in facing_vector(0)] == [0, 1]
    assert [round(v) for v in facing_vector(90)] == [1, 0]
    assert [round(v) for v in facing_vector(180)] == [0, -1]
    assert quantize_rot(219) == 180 and quantize_rot(-95) == 270 and quantize_rot(46) == 90


def test_access_zone_is_in_front_of_face():
    p = Placement(role="диван", x=200, y=400, rot=180, item=SOFA)  # у северной стены, лицом на юг
    zx0, zy0, zx1, zy1 = access_zone(p).bounds
    fx0, fy0, fx1, fy1 = footprint(p).bounds
    assert zy0 < fy0, "зона подхода должна быть ЮЖНЕЕ дивана (перед лицом)"


def test_corner_sofa_polygon_is_l_shaped():
    it = Item(role="диван", w_cm=250, d_cm=170, h_cm=85, corner=True, corner_section_cm=95)
    poly = footprint(Placement(role="диван", x=200, y=200, rot=0, item=it))
    assert len(poly.exterior.coords) == 7  # 6 точек + замыкание
    assert poly.area < 250 * 170, "Г-полигон меньше bbox — иначе это прямоугольник"


def test_free_space_subtracts_item_and_clearance():
    room = _room()
    p = Placement(role="диван", x=200, y=room.depth_cm - 45, rot=180, item=SOFA)
    bare = free_space(room, [p], with_clearance=False).area
    with_cl = free_space(room, [p]).area
    assert with_cl < bare, "клиренс вычитается из свободного места (механика ProcTHOR)"
    assert isclose(room_polygon(room).area - bare, footprint(p).area, rel_tol=1e-6)


def test_free_space_subtracts_door_swing():
    """Дуга двери вычитается целиком + технологический зазор (SAFE_GAP_CM)."""
    room = _room(openings=[Opening(kind="door", wall="south", offset_cm=20, width_cm=90, swing_cm=100)])
    cut = room_polygon(room).area - free_space(room, []).area
    assert 90 * 100 <= cut <= (90 + 12) * (100 + 12)


def test_floor_used_pct_counts_overlap_once():
    room = _room()
    a = Placement(role="диван", x=200, y=200, rot=0, item=SOFA)
    b = Placement(role="диван", x=250, y=200, rot=0, item=SOFA)
    assert floor_used_pct(room, [a, b]) < 2 * floor_used_pct(room, [a])


def test_largest_free_rectangles_finds_big_open_area():
    room = _room()
    p = Placement(role="диван", x=200, y=room.depth_cm - 45, rot=180, item=SOFA)
    rects = largest_free_rectangles(free_space(room, [p]), min_side_cm=60, limit=5)
    assert rects, "в пустой комнате обязан находиться хотя бы один прямоугольник"
    assert rects[0].area > 4 * 10_000, "самый большой прямоугольник — крупнее 4 м²"
    assert all(not r.intersects(footprint(p).buffer(-1)) for r in rects)
