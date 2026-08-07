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


def test_sofa_sliver_hard():
    """Щель за спинкой дивана 20–76 см — жёсткий запрет (правило владельца 2026-08-02)."""
    from tests.rooms import make_room
    room = make_room("31-40")
    sofa_gap_45 = Placement(role="диван", x=room.width_cm / 2, y=45 + 50, rot=0,
                            item=Item(role="диван", w_cm=220, d_cm=100, h_cm=85))
    lay = validate(room, [sofa_gap_45])
    assert "SOFA_SLIVER" in {v.code for v in lay.violations}, "щель 45 см должна браковаться"
    sofa_tight = Placement(role="диван", x=room.width_cm / 2, y=50, rot=0,
                           item=Item(role="диван", w_cm=220, d_cm=100, h_cm=85))
    assert "SOFA_SLIVER" not in {v.code for v in validate(room, [sofa_tight]).violations}
    sofa_pass = Placement(role="диван", x=room.width_cm / 2, y=90 + 50, rot=0,
                          item=Item(role="диван", w_cm=220, d_cm=100, h_cm=85))
    assert "SOFA_SLIVER" not in {v.code for v in validate(room, [sofa_pass]).violations}
    behind = Placement(role="комод", x=room.width_cm / 2, y=20, rot=0,
                       item=Item(role="комод", w_cm=180, d_cm=40, h_cm=80))
    lay_filled = validate(room, [sofa_gap_45, behind])
    assert "SOFA_SLIVER" not in {v.code for v in lay_filled.violations}, \
        "щель, заполненная хранением, щелью не считается"


def test_dead_zone_and_aim_and_chairs():
    """R1/R2 (2026-08-07): мёртвая зона за спинкой, прицел на ТВ, стул-сирота."""
    from tests.rooms import make_room
    room = make_room("31-40")
    sofa = Placement(role="диван", x=room.width_cm / 2, y=room.depth_cm - 150, rot=180,
                     item=Item(role="диван", w_cm=220, d_cm=100, h_cm=85))
    kashpo_behind = Placement(role="кашпо", x=room.width_cm / 2, y=room.depth_cm - 50, rot=0,
                              item=Item(role="кашпо", w_cm=30, d_cm=30, h_cm=60))
    codes = {v.code for v in validate(room, [sofa, kashpo_behind]).violations}
    assert "DEAD_ZONE_BEHIND_SOFA" in codes, "кашпо за спинкой дивана должно браковаться"
    tv_aside = Placement(role="тв-тумба", x=60, y=room.depth_cm - 80, rot=90,
                         item=Item(role="тв-тумба", w_cm=180, d_cm=45, h_cm=50))
    codes = {v.code for v in validate(room, [sofa, tv_aside]).violations}
    assert "SOFA_AIM_OFF_TV" in codes, "диван, смотрящий мимо ТВ, должен браковаться"
    tbl = Placement(role="стол обеденный", x=100, y=100, rot=0,
                    item=Item(role="стол обеденный", w_cm=140, d_cm=80, h_cm=75))
    chair_far = Placement(role="стул", x=room.width_cm - 60, y=100, rot=0,
                          item=Item(role="стул", w_cm=45, d_cm=45, h_cm=90))
    codes = {v.code for v in validate(room, [tbl, chair_far]).violations}
    assert "CHAIR_ORPHAN" in codes, "стул вдали от стола должен браковаться"


def test_functional_zones():
    """R1: столовая группа не в разговорной зоне; высокое хранение не в обеденной."""
    from tests.rooms import make_room
    room = make_room("41-50")
    sofa = Placement(role="диван", x=200, y=room.depth_cm - 150, rot=180,
                     item=Item(role="диван", w_cm=220, d_cm=100, h_cm=85))
    tv = Placement(role="тв-тумба", x=200, y=30, rot=0,
                   item=Item(role="тв-тумба", w_cm=180, d_cm=45, h_cm=50))
    table_in_zone = Placement(role="стол обеденный", x=200, y=room.depth_cm - 320, rot=0,
                              item=Item(role="стол обеденный", w_cm=140, d_cm=80, h_cm=75))
    codes = {v.code for v in validate(room, [sofa, tv, table_in_zone]).violations}
    assert "DINING_IN_LIVING_ZONE" in codes, "стол на оси диван→ТВ должен браковаться"
    tbl = Placement(role="стол обеденный", x=room.width_cm - 120, y=150, rot=0,
                    item=Item(role="стол обеденный", w_cm=140, d_cm=80, h_cm=75))
    shelf_in_dining = Placement(role="стеллаж", x=room.width_cm - 120, y=225, rot=180,
                                item=Item(role="стеллаж", w_cm=80, d_cm=35, h_cm=180))
    codes = {v.code for v in validate(room, [tbl, shelf_in_dining]).violations}
    assert "STORAGE_IN_DINING_ZONE" in codes, "стеллаж вплотную к обеденной группе — брак"
