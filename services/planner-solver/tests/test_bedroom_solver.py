"""Спальня (план onb-05, ADR-0330 п.1/7): солвер детерминирован, годная раскладка проходит повторную проверку,
отказ — с кодом причины, путь гостиной не задет, пары правил совместимы (урок 204)."""
from __future__ import annotations

import json
from pathlib import Path

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


FLAT215 = Path(__file__).resolve().parents[3] / "tools" / "scout" / "flat215-bedrooms.json"


def _flat215(room_id: str, variant: str, purpose: str = "child", child_age: str | None = "7-12") -> Room:
    """Комната квартиры 215 из `tools/scout/flat215-bedrooms.json` (та же геометрия, что берёт сборщик спальни)."""
    spec = next(r for r in json.loads(FLAT215.read_text(encoding="utf-8"))["rooms"]
                if r["id"] == room_id and r["variant"] == variant)
    clean = lambda o: {k: v for k, v in o.items() if not k.startswith("_")}  # noqa: E731
    return Room(width_cm=spec["w"], depth_cm=spec["d"], contour=spec.get("contour"),
                openings=[Opening(**clean(o)) for o in spec.get("openings", [])],
                radiators=[Radiator(**clean(r)) for r in spec.get("radiators", [])],
                room_type="bedroom", purpose=purpose, child_age=child_age)


# детская 7–12 (kids-room-01): размеры — каталог 07.11 (Анджи 80×160, Трикси, Филлис Мини, детские шкаф и комод)
KIDS = [Item(role="кровать детская", w_cm=86, d_cm=166, h_cm=80),
        Item(role="стол детский", w_cm=100, d_cm=55, h_cm=75),
        Item(role="стул детский", w_cm=51, d_cm=45, h_cm=57),
        Item(role="шкаф", w_cm=93, d_cm=55, h_cm=195),
        Item(role="комод", w_cm=80, d_cm=45, h_cm=86)]
BEDROOM2 = ["drawing-180", "small-9.7"]       # спальня 2: 13,2 м² по чертежу и 9,7 м² по реестру


@pytest.mark.parametrize("variant", BEDROOM2)
def test_child_7_12_solves_on_both_bedroom2_areas(variant):
    room = _flat215("bedroom-2", variant)
    lay = solve_bedroom(room, KIDS)
    assert lay.ok and not lay.unplaced, (lay.meta, [v.message for v in lay.violations])
    assert {"кровать детская", "стол детский", "стул детский"} <= {p.role for p in lay.placements}
    assert lay.meta["purpose"] == "child" and lay.meta["child_age"] == "7-12"
    re_ = validate(room, lay.placements)       # повторная проверка через диспетчер — без жёсткого
    assert not [v.message for v in re_.violations if v.severity is Severity.HARD]
    assert _sig(lay) == _sig(solve_bedroom(room, KIDS))
    codes = {v.code for v in lay.violations}
    # нормы детской — нормы взрослых ролей: проход 75 сбоку / 60 в ногах, 75 под стул; мягкие — кровать не под окном,
    # стол у окна, свет не справа (на этой геометрии решаются все)
    assert not codes & {"BED_SIDE_PASSAGE", "BED_FOOT_PASSAGE", "BR_ACCESS_BLOCKED", "BR_ACCESS_WALL"}
    assert not codes & {"BED_HEAD_WINDOW", "DESK_FAR_FROM_WINDOW", "DESK_LIGHT_RIGHT"}, codes


def _mirror_x(room: Room) -> Room:
    """Та же комната зеркально по ширине: окно и радиатор с запада на восток, двери на южной/северной — с другого края."""
    W = room.width_cm
    side = {"west": "east", "east": "west"}
    ops = [o.model_copy(update={"wall": side[o.wall]}) if o.wall in side else
           o.model_copy(update={"offset_cm": W - o.offset_cm - o.width_cm}) for o in room.openings]
    rads = [r.model_copy(update={"wall": side[r.wall]}) if r.wall in side else
            r.model_copy(update={"offset_cm": W - r.offset_cm - r.width_cm}) for r in room.radiators]
    return room.model_copy(update={"openings": ops, "radiators": rads})


@pytest.mark.parametrize("variant", BEDROOM2)
def test_child_7_12_light_left_on_mirrored_room(variant):
    """Свет слева выбирается правилом, а не совпадением геометрии: у зеркальной спальни 2 стол уходит к другой стене."""
    from planner.bedroom_checks import bedroom_role, light_side
    room = _mirror_x(_flat215("bedroom-2", variant))
    lay = solve_bedroom(room, KIDS)
    assert lay.ok and not lay.unplaced and not [v for v in lay.violations if v.severity is Severity.HARD]
    desk = next(p for p in lay.placements if bedroom_role(p.role) == "стол рабочий")
    assert light_side(room, desk) == "left" and "DESK_LIGHT_RIGHT" not in {v.code for v in lay.violations}


@pytest.mark.parametrize("variant", BEDROOM2)
def test_child_7_12_requires_bed_desk_chair(variant):
    room = _flat215("bedroom-2", variant)
    lay = solve_bedroom(room, [KIDS[0], KIDS[3]])
    assert "MISSING_ITEM" in lay.meta["reason"] and lay.meta["missing"] == ["стол рабочий", "стул рабочий"]
    # взрослый компактный рабочий стул годен детской 7–12 (каталог по назначению) — тоже закрывает «стул»
    mixed = KIDS[:2] + [Item(role="стул рабочий", w_cm=56, d_cm=56, h_cm=81)]
    lay2 = solve_bedroom(room, mixed)
    assert lay2.ok and not lay2.unplaced and "MISSING_ITEM" not in lay2.meta["reason"]


@pytest.mark.parametrize("age", ["0-3", "3-7", "teen", None])
def test_child_other_ages_still_pending(age):
    lay = solve_bedroom(_flat215("bedroom-2", "drawing-180", child_age=age), KIDS)
    assert "PURPOSE_PENDING" in lay.meta["reason"] and not lay.placements


def test_kids_aliases_use_adult_norms():
    from planner.bedroom_checks import bedroom_role, bedroom_spec, num
    assert [bedroom_role(r) for r in ("кровать детская", "стол детский", "стул детский", "тумба прикроватная 2")] == \
        ["кровать", "стол рабочий", "стул рабочий", "тумба прикроватная"]
    assert bedroom_spec("стол детский").front_cm == num("desk_chair_clear", 0) == 75
    # кровать детская в углу без 75 см ни с одного бока — та же ошибка, что у взрослой
    room = Room(width_cm=150, depth_cm=300, room_type="bedroom", purpose="child", child_age="7-12")
    bed = Placement(role="кровать детская", x=75, y=83, rot=0, item=KIDS[0].model_copy())
    assert "BED_SIDE_PASSAGE" in {v.code for v in validate(room, [bed]).violations}


def _desk(rot: int, x: float, y: float) -> Placement:
    return Placement(role="стол детский", x=x, y=y, rot=rot, item=Item(role="стол детский", w_cm=100, d_cm=55, h_cm=75))


def test_desk_light_side_child_only():
    from planner.bedroom_checks import check_desk_light, light_side
    room = Room(width_cm=400, depth_cm=300, room_type="bedroom", purpose="child", child_age="7-12",
                openings=[Opening(kind="window", wall="west", offset_cm=100, width_cm=120, sill_cm=85)])
    # лево/право — как в 3D-сцене покупателя (y плана → z three.js, сверху план зеркален учебной плоскости):
    # стол у стены y=0, сидящий лицом к ней — окно x=0 у него слева; у стены y=max — справа
    south = _desk(0, 200, 27.5)
    north = _desk(180, 200, 300 - 27.5)
    west = _desk(90, 27.5, 160)                  # у окна — свет спереди
    assert (light_side(room, south), light_side(room, north), light_side(room, west)) == ("left", "right", "front")
    assert [v.code for v in check_desk_light(room, [north])] == ["DESK_LIGHT_RIGHT"]
    assert check_desk_light(room.model_copy(update={"purpose": "single"}), [north]) == []   # взрослым — не проверяем


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
