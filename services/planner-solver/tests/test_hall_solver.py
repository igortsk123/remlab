"""СОЛВЕР ПРИХОЖЕЙ (план onb-13 Т3, T-20261105-34): planner/hall.py.

Хранение одежды обязательно (MISSING_ITEM / STORAGE_NO_FIT), прочее — опционально; раскладка детерминирована,
повторная проверка — 0 жёстких; гостиная и спальня не задеты (их модули прихожая не меняет).
"""
import typing

import pytest

from planner.geometry import base_role
from planner.hall import solve_hall, storage_roles
from planner.hall_checks import dist_to_entry, validate_hall
from planner.models import Item, Opening, Room, RoomType, Severity
from tests.test_hall_rules import hall_room

FULL = [("шкаф-купе", 150, 60, 240), ("обувница", 99, 39, 44), ("банкетка", 80, 43, 49), ("консоль", 90, 40, 81),
        ("вешалка", 46, 17, 92), ("зеркало", 50, 3, 150)]


def items(kit) -> list[Item]:
    return [Item(role=r, w_cm=w, d_cm=d, h_cm=h) for r, w, d, h in kit]


def sig(lay):
    return [(p.role, round(p.x, 1), round(p.y, 1), p.rot, p.elev_cm) for p in lay.placements]


def test_flat215_full_solves_clean_and_deterministic():
    room = hall_room()
    lay = solve_hall(room, items(FULL))
    assert lay.ok and not lay.unplaced, [(v.code, v.message) for v in lay.violations]
    assert any(base_role(p.role) in storage_roles() for p in lay.placements)
    assert not [v for v in validate_hall(room, lay.placements).violations if v.severity is Severity.HARD]
    assert sig(lay) == sig(solve_hall(room, items(FULL)))
    assert lay.meta["solver"] == "hall-v1"


def test_flat215_layout_sense():
    """Как у дизайнера: купе у глухой стены (без дверей), обувница у входа, зеркало на стене."""
    room = hall_room()
    lay = solve_hall(room, items(FULL))
    by = {p.role: p for p in lay.placements}
    assert by["шкаф-купе"].tpl_id == "storage_solid_wall" and by["шкаф-купе"].x > 100     # восток — глухая стена
    assert dist_to_entry(room, by["обувница"]) <= 150
    assert by["зеркало"].elev_cm > 0


def test_missing_storage_is_missing_item():
    lay = solve_hall(hall_room(), items([("обувница", 99, 39, 44), ("банкетка", 80, 43, 49)]))
    assert not lay.placements and "MISSING_ITEM" in lay.meta["reason"] and lay.unplaced == ["хранение"]


def test_storage_no_fit_in_narrow_corridor():
    room = Room(width_cm=110, depth_cm=400, openings=[Opening(kind="door", wall="south", offset_cm=10, width_cm=90),
                                                       Opening(kind="door", wall="east", offset_cm=250, width_cm=80)])
    lay = solve_hall(room, items([("шкаф-купе", 180, 60, 230)]))
    assert "STORAGE_NO_FIT" in lay.meta["reason"] and lay.unplaced == ["шкаф-купе"]


def test_narrow_corridor_takes_slim_storage():
    """Коридор 1,1 м: купе не встаёт, хранение — настенной вешалкой; купе уходит в skipped_optional."""
    room = Room(width_cm=110, depth_cm=400, openings=[Opening(kind="door", wall="south", offset_cm=10, width_cm=90),
                                                       Opening(kind="door", wall="east", offset_cm=250, width_cm=80)])
    lay = solve_hall(room, items(FULL))
    assert lay.ok and "вешалка" in {p.role for p in lay.placements} and "шкаф-купе" in lay.skipped_optional


def test_hall_does_not_read_room_type():
    """До интегратора (T-37) у Room нет типа hall — солвер прихожей поле не читает: результат тот же."""
    a = solve_hall(hall_room(), items(FULL))
    r = hall_room()
    object.__setattr__(r, "room_type", "bedroom")
    assert sig(a) == sig(solve_hall(r, items(FULL)))


@pytest.mark.skipif("hall" not in typing.get_args(RoomType), reason="тип hall и реестр — T-37 (Работник 7)")
def test_validate_dispatches_hall_to_hall_checks():
    from planner.validate import validate
    room = hall_room()
    object.__setattr__(room, "room_type", "hall")
    lay = solve_hall(room, items(FULL))
    codes = {v.code for v in validate(room, lay.placements).violations}
    assert not codes & {"MEDIA_MISSING", "CIRCULATION_MISSING", "NO_PASSAGE"}, codes   # не проверки гостиной
    assert codes == {v.code for v in validate_hall(room, lay.placements).violations}
