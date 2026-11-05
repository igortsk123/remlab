"""Спальня (план onb-05, ADR-0330 п.1/7): солвер детерминирован, годная раскладка проходит повторную проверку,
отказ — с кодом причины, путь гостиной не задет, пары правил совместимы (урок 204)."""
from __future__ import annotations

import pytest

from planner.bedroom import solve_bedroom
from planner.models import Item, Opening, Placement, Radiator, Room, Severity
from planner.validate import validate


def _bedroom1(purpose: str = "couple") -> Room:
    """Спальня 1 квартиры 215 по чертежу №180 (`tools/scout/flat215-bedrooms.json`)."""
    return Room(width_cm=618, depth_cm=293, room_type="bedroom", purpose=purpose, openings=[
        Opening(kind="door", wall="south", offset_cm=24, width_cm=90, swing_cm=90),
        Opening(kind="window", wall="east", offset_cm=40, width_cm=210, sill_cm=85),
        Opening(kind="window", wall="north", offset_cm=204, width_cm=240, sill_cm=85)],
        radiators=[Radiator(wall="east", offset_cm=55, width_cm=180), Radiator(wall="north", offset_cm=234, width_cm=180)])


COUPLE = [Item(role="кровать", w_cm=170, d_cm=210, h_cm=94),
          Item(role="тумба прикроватная", w_cm=45, d_cm=40, h_cm=55),
          Item(role="тумба прикроватная 2", w_cm=45, d_cm=40, h_cm=55),
          Item(role="шкаф", w_cm=120, d_cm=60, h_cm=210),
          Item(role="комод", w_cm=91, d_cm=42, h_cm=96)]


def _sig(lay):
    return [(p.role, p.x, p.y, p.rot) for p in lay.placements]


def test_room_type_default_living():
    r = Room(width_cm=400, depth_cm=300)
    assert r.room_type == "living" and r.purpose is None and r.child_age is None
    assert Room(width_cm=400, depth_cm=300, room_type="kitchen").room_type == "kitchen"   # значение для onb-09


def test_couple_solves_and_is_deterministic():
    lay = solve_bedroom(_bedroom1(), COUPLE)
    assert lay.ok and not lay.unplaced, [v.message for v in lay.violations]
    assert {p.role for p in lay.placements} >= {"кровать", "тумба прикроватная", "тумба прикроватная 2", "шкаф"}
    assert _sig(lay) == _sig(solve_bedroom(_bedroom1(), COUPLE))


def test_revalidate_valid_layout_has_no_hard():
    room = _bedroom1()
    lay = solve_bedroom(room, COUPLE)
    re = validate(room, lay.placements)       # диспетчер по room_type
    assert not [v for v in re.violations if v.severity is Severity.HARD]


def test_too_small_for_couple_gives_reason():
    room = Room(width_cm=250, depth_cm=280, room_type="bedroom", purpose="couple",
                openings=[Opening(kind="door", wall="south", offset_cm=20, width_cm=80, swing_cm=80)])
    lay = solve_bedroom(room, COUPLE)
    assert not lay.ok and not lay.placements
    assert "BED_NO_FIT" in lay.meta["reason"] and lay.unplaced == ["кровать"]


def test_couple_needs_double_bed():
    lay = solve_bedroom(_bedroom1(), [Item(role="кровать", w_cm=105, d_cm=212, h_cm=82)])
    assert lay.meta["reason"] == ["BED_NOT_DOUBLE"]


def test_child_waits_for_onb04():
    room = Room(width_cm=450, depth_cm=293, room_type="bedroom", purpose="child", child_age="7-12")
    lay = solve_bedroom(room, COUPLE[:1])
    assert "PURPOSE_PENDING" in lay.meta["reason"] and not lay.placements


def test_living_path_untouched(monkeypatch):
    """Гостиная не заходит в модуль спальни: диспетчер срабатывает только на room_type=bedroom."""
    import planner.bedroom_checks as bc

    def boom(*a, **k):
        raise AssertionError("гостиная ушла в проверки спальни")
    monkeypatch.setattr(bc, "validate_bedroom", boom)
    room = Room(width_cm=439, depth_cm=325)
    validate(room, [Placement(role="диван", x=200, y=280, rot=180, item=Item(role="диван", w_cm=220, d_cm=95, h_cm=85))])


# ---- совместимость пар правил (урок 204): эталонная спальня, где все нормы выполняются ОДНОВРЕМЕННО ----
def _reference():
    room = Room(width_cm=400, depth_cm=350, room_type="bedroom", purpose="couple", openings=[
        Opening(kind="door", wall="south", offset_cm=290, width_cm=90, swing_cm=90),
        Opening(kind="window", wall="north", offset_cm=125, width_cm=150, sill_cm=85)],
        radiators=[Radiator(wall="north", offset_cm=140, width_cm=120)])
    bed, ns, wr, dr = COUPLE[0], COUPLE[1], COUPLE[3], COUPLE[4]
    ps = [Placement(role="кровать", x=105, y=175, rot=90, item=bed),                     # изголовье к западной стене
          Placement(role="тумба прикроватная", x=20, y=175 - 85 - 22.5 - 1, rot=90, item=ns),
          Placement(role="тумба прикроватная 2", x=20, y=175 + 85 + 22.5 + 1, rot=90,
                    item=ns.model_copy(update={"role": "тумба прикроватная 2"})),
          # шкаф напротив изножья: его фронт 90 и проход у изножья 60 делят одну полосу пола — это законно
          Placement(role="шкаф", x=370, y=160, rot=270, item=wr),
          Placement(role="комод", x=345.5, y=329, rot=180, item=dr)]
    return room, ps


def test_reference_bedroom_satisfies_all_rules_at_once():
    room, ps = _reference()
    lay = validate(room, ps)
    assert not lay.violations, [(v.code, v.message) for v in lay.violations]


@pytest.mark.parametrize("move,code", [
    (("шкаф", 300), "BR_ACCESS_BLOCKED"),     # шкаф придвинут к изножью: фронт упирается в кровать
    (("кровать", 120), "BED_HEAD_WALL"),      # изголовье отошло от стены
])
def test_reference_breaks_with_expected_code(move, code):
    room, ps = _reference()
    role, x = move
    ps = [p.model_copy(update={"x": x}) if p.role == role else p for p in ps]
    codes = {v.code for v in validate(room, ps).violations}
    assert code in codes, codes
