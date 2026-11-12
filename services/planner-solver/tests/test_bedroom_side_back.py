"""Кровать с БОКОВОЙ СПИНКОЙ (T-20261112-31; разбор T-27: «Кейси-Б» стояла по центру стены, спинка закрыла подход сбоку).
Угловая модель — только в угол боковой спинкой к стене; паре — нет; выключатель `switches.bed_side_back` возвращает прежнее."""
from __future__ import annotations

import copy

import pytest

from planner import bedroom_checks as BC
from planner.bedroom import solve_bedroom
from planner.bedroom_checks import validate_bedroom
from planner.models import Item, Opening, Placement, Room, Severity

W, D = 420.0, 360.0
BED = dict(role="кровать", w_cm=176, d_cm=212, h_cm=100)


def _room(purpose: str = "single") -> Room:
    # дверь — на северной стене (y = D), изголовье у южной (y = 0, rot 0): изголовью ничто не мешает
    return Room(width_cm=W, depth_cm=D, room_type="bedroom", purpose=purpose,
                openings=[Opening(kind="door", wall="north", offset_cm=20, width_cm=80, swing_cm=80)])


def _bed(x: float, side: str | None) -> Placement:
    return Placement(role="кровать", x=x, y=BED["d_cm"] / 2, rot=0, item=Item(**BED, side_back=side))


def _codes(room: Room, ps: list[Placement]) -> set[str]:
    return {v.code for v in validate_bedroom(room, ps).violations if v.severity is Severity.HARD}


def test_center_of_wall_refused():
    """Угловая кровать по центру стены — отказ (как в демо T-27)."""
    assert "BED_SIDE_BACK_OFF_WALL" in _codes(_room(), [_bed(W / 2, "right")])
    assert "BED_SIDE_BACK_OFF_WALL" in _codes(_room(), [_bed(W / 2, "any")])


def test_corner_with_back_to_wall_ok():
    """В углу, боковая спинка (+x, «right») к восточной стене — годится; обычная кровать там же — тоже."""
    right = _bed(W - BED["w_cm"] / 2, "right")
    assert not _codes(_room(), [right])
    assert not _codes(_room(), [_bed(BED["w_cm"] / 2, "left")])
    assert not _codes(_room(), [_bed(W - BED["w_cm"] / 2, "any")])   # по названию — любой бок у стены


def test_corner_wrong_side_refused():
    """Спинка справа (+x), а к стене прижат левый бок — спинка смотрит в комнату: отказ."""
    assert "BED_SIDE_BACK_OFF_WALL" in _codes(_room(), [_bed(BED["w_cm"] / 2, "right")])


def test_couple_refused_by_rule_and_solver():
    assert "BED_SIDE_BACK_COUPLE" in _codes(_room("couple"), [_bed(W - BED["w_cm"] / 2, "right")])
    lay = solve_bedroom(_room("couple"), [Item(**BED, side_back="right")], "couple")
    assert not lay.placements and "BED_SIDE_BACK_COUPLE" in lay.meta["reason"] and lay.unplaced == ["кровать"]


@pytest.mark.parametrize("side", ["left", "right"])
def test_solver_puts_it_in_corner_back_to_wall(side):
    """Солвер ставит угловую кровать в угол именно её спинкой к стене; тумба — с открытой стороны."""
    items = [Item(**BED, side_back=side), Item(role="тумба прикроватная", w_cm=45, d_cm=40, h_cm=55),
             Item(role="шкаф", w_cm=120, d_cm=60, h_cm=210)]
    room = _room("single")
    lay = solve_bedroom(room, items, "single")
    bed = next(p for p in lay.placements if p.role == "кровать")
    assert lay.meta["template"] == "bed_side_back_corner"
    assert BC._against_wall(room, BC.bed_zones(bed)[f"{side}_wall"])
    assert not [v for v in lay.violations if v.severity is Severity.HARD], [v.code for v in lay.violations]
    assert "тумба прикроватная" in {p.role for p in lay.placements}


@pytest.fixture
def switch_off(monkeypatch):
    rules = copy.deepcopy(BC.bedroom_rules())
    rules["switches"]["bed_side_back"]["on"] = False
    monkeypatch.setattr(BC, "bedroom_rules", lambda: rules)
    yield


def test_switch_off_restores_old_behaviour(switch_off):
    assert not ({"BED_SIDE_BACK_OFF_WALL", "BED_SIDE_BACK_COUPLE"} & _codes(_room("couple"), [_bed(W / 2, "right")]))
    lay = solve_bedroom(_room("couple"), [Item(**BED, side_back="right")], "couple")
    assert lay.placements and "BED_SIDE_BACK_COUPLE" not in lay.meta["reason"]
