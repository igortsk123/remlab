"""Приёмка Э1: валидатор согласен с 20 ручными раскладками и ловит подсунутые дефекты."""
from __future__ import annotations

import pytest

from planner.models import Item, Placement
from planner.validate import validate
from tests.rooms import CATALOG, all_rooms, manual_layout

ROOMS = all_rooms()


def _codes(layout) -> set[str]:
    return {v.code for v in layout.violations if v.severity == "hard"}


def test_twenty_rooms_fixture():
    assert len(ROOMS) == 20


@pytest.mark.parametrize("room", ROOMS, ids=lambda r: f"{r.band}-{r.width_cm:.0f}x{r.depth_cm:.0f}")
def test_manual_layout_is_clean(room):
    layout = validate(room, manual_layout(room))
    assert layout.ok, f"ручная раскладка забракована: {[v.message for v in layout.violations]}"


@pytest.mark.parametrize("room", ROOMS[:6], ids=lambda r: r.band)
def test_floor_cap_respected_in_manual_layouts(room):
    layout = validate(room, manual_layout(room))
    assert layout.floor_used_pct is not None and layout.floor_used_pct > 0


def test_collision_detected():
    room = ROOMS[2]
    ps = manual_layout(room)
    ps[2] = ps[2].model_copy(update={"y": ps[0].y})  # столик внутрь дивана
    assert "COLLISION" in _codes(validate(room, ps))


def test_out_of_room_detected():
    room = ROOMS[2]
    ps = manual_layout(room)
    ps[1] = ps[1].model_copy(update={"x": -50})
    assert "OUT_OF_ROOM" in _codes(validate(room, ps))


def test_door_swing_blocked_detected():
    room = ROOMS[3]
    door = next(o for o in room.openings if o.kind == "door")
    wardrobe = Item(role="шкаф", w_cm=80, d_cm=55, h_cm=220)
    ps = manual_layout(room) + [
        Placement(role="шкаф", x=door.offset_cm + door.width_cm / 2, y=30, rot=0, item=wardrobe)
    ]
    assert "DOOR_SWING" in _codes(validate(room, ps))


def test_access_blocked_detected():
    """Кресло вплотную перед диваном — классический косяк «зона забита»."""
    room = ROOMS[4]
    ps = manual_layout(room)
    sofa = ps[0]
    arm = CATALOG["кресло"].model_copy()
    ps.append(Placement(role="кресло", x=sofa.x, y=sofa.y - sofa.item.d_cm / 2 - arm.d_cm / 2 - 5,
                        rot=0, item=arm))
    codes = _codes(validate(room, ps))
    assert "ACCESS_BLOCKED" in codes or "COLLISION" in codes


def test_sofa_tv_distance_out_of_scale_detected():
    room = ROOMS[0]
    ps = manual_layout(room)
    ps[1] = ps[1].model_copy(update={"y": ps[0].y - 60})  # ТВ вплотную к дивану
    codes = _codes(validate(room, ps))
    assert "SOFA_TV_DIST" in codes


def test_radiator_clearance_detected():
    room = ROOMS[1]
    rad = room.radiators[0]
    shelf = Item(role="стеллаж", w_cm=90, d_cm=40, h_cm=180)
    ps = [Placement(role="стеллаж", x=room.width_cm - 25, y=rad.offset_cm + rad.width_cm / 2,
                    rot=270, item=shelf)]
    assert "RADIATOR" in _codes(validate(room, ps))


def test_window_blocked_by_tall_furniture():
    room = ROOMS[1]
    win = next(o for o in room.openings if o.kind == "window")
    tall = Item(role="шкаф", w_cm=100, d_cm=55, h_cm=220)
    ps = [Placement(role="шкаф", x=room.width_cm - 30, y=win.offset_cm + win.width_cm / 2,
                    rot=270, item=tall)]
    assert "WINDOW_BLOCKED" in _codes(validate(room, ps))


def test_passage_violation_when_room_walled_off():
    """Стена из шкафов поперёк комнаты — до дивана не дойти."""
    room = ROOMS[5]
    ps = manual_layout(room)
    y = room.depth_cm * 0.55
    x = 0.0
    wall_items = []
    while x < room.width_cm:
        it = Item(role="шкаф", w_cm=100, d_cm=55, h_cm=220)
        wall_items.append(Placement(role="шкаф", x=x + 50, y=y, rot=0, item=it))
        x += 100
    layout = validate(room, ps + wall_items)
    assert {"UNREACHABLE", "NO_PASSAGE", "COLLISION", "ACCESS_BLOCKED"} & _codes(layout)


def test_violations_are_explainable():
    room = ROOMS[0]
    ps = manual_layout(room)
    ps[1] = ps[1].model_copy(update={"y": ps[0].y - 60})
    v = next(v for v in validate(room, ps).violations if v.code == "SOFA_TV_DIST")
    assert v.expected and v.value is not None and v.roles == ["диван", "тв-тумба"]
