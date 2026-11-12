"""Проходы по норме обычного жилья (T-20261112-68, ADR-0394; канон `.memory_bank/domain/room-templates.md` § «Проходы»).

Функция порогов (`planner/passage_norms.py`): проход + режим + профиль → см; движок групп спальни: проход 1 все уровни по
цели → проход 2 с допуском compact (строка покупателю) → честный отказ с причиной.
"""
from __future__ import annotations

import pytest

from planner import passage_norms as PN
from planner.bedroom import solve_bedroom
from planner.bedroom_checks import bedroom_spec, check_bed, validate_bedroom
from planner.models import Item, Opening, Placement, Radiator, Room, Severity

GENERAL = {  # канон: цель / допуск / жёстко
    "bed_side_couple": (60, 50, 50), "bed_side_work": (60, 50, 50), "bed_foot_route": (60, 50, 50),
    "bed_long_side_window_wall": (70, 70, 70), "route_door_window": (75, 50, 50),
    "wardrobe_hinged_front": (90, 70, 70), "storage_sliding_front": (70, 50, 50), "dresser_front": (76, 70, 70),
}


@pytest.mark.parametrize("name,nums", sorted(GENERAL.items()))
def test_general_profile_matches_canon(name, nums):
    assert tuple(PN.clearance(name, lv) for lv in ("target", "compact", "hard")) == tuple(float(x) for x in nums)


def test_accessible_profiles_have_no_allowances():
    for prof, floor in (("m4_2", 75), ("m4_3", 100), ("mgn", 90)):
        assert not PN.allowances_on(prof)
        for name, (t, _, _) in GENERAL.items():
            tri = PN.triple(name, prof)
            assert tri["target"] == tri["compact"] == tri["hard"] == max(t, floor), (prof, name)
    assert PN.allowances_on("general") and PN.profile() == "general"


def test_mode_and_legacy_keys():
    assert PN.mode() == "compact"                      # вне движка — законность по допуску
    with PN.using("target"):
        assert PN.clearance("bed_side_couple") == 60
    with PN.using("legacy"):                           # поштучный движок: прежние ключи, байт в байт
        assert PN.clearance("bed_side_couple") == 75 and PN.clearance("route_door_window") == 46
        assert PN.clearance("bed_long_side_window_wall") is None
    with pytest.raises(ValueError):
        with PN.using("tight"):
            pass
    with pytest.raises(KeyError):
        PN.clearance("no_such_passage")


def test_wardrobe_kind_and_fronts():
    hinged = Item(role="шкаф", w_cm=150, d_cm=60, h_cm=220, name="Шкаф 3-дверный")
    sliding = Item(role="шкаф", w_cm=150, d_cm=60, h_cm=220, name="Шкаф-купе Лайт")
    caps = Item(role="шкаф", w_cm=150, d_cm=60, h_cm=220, caps={"doors": "sliding"})
    assert [PN.wardrobe_kind(i) for i in (hinged, sliding, caps, Item(role="шкаф", w_cm=1, d_cm=1))] == \
        ["hinged", "sliding", "sliding", "hinged"]
    with PN.using("target"):
        assert bedroom_spec("шкаф", hinged).front_cm == 90 and bedroom_spec("шкаф", sliding).front_cm == 70
        assert bedroom_spec("комод", Item(role="комод", w_cm=100, d_cm=45)).front_cm == 76
    with PN.using("compact"):
        assert bedroom_spec("шкаф", hinged).front_cm == 70 and bedroom_spec("шкаф", sliding).front_cm == 50
        wide = Item(role="шкаф", w_cm=150, d_cm=60, caps={"door_leaf_cm": 75})
        assert bedroom_spec("шкаф", wide).front_cm == 75                 # не меньше дуги створки
        assert bedroom_spec("комод", Item(role="комод", w_cm=100, d_cm=45)).front_cm == 70   # вылет неизвестен — 70
        assert bedroom_spec("комод", Item(role="комод", w_cm=100, d_cm=45, caps={"drawer_reach_cm": 74})).front_cm == 74


# ─────────────────────────── движок: уровни по цели → compact → отказ ───────────────────────────
BED = Item(role="кровать", w_cm=165, d_cm=213, h_cm=100)
NS = [Item(role="тумба прикроватная", w_cm=45, d_cm=40, h_cm=50), Item(role="тумба прикроватная 2", w_cm=45, d_cm=40, h_cm=50)]
DR = Item(role="комод", w_cm=100, d_cm=45, h_cm=85)
WR = Item(role="шкаф", w_cm=150, d_cm=60, h_cm=220)


def _room(W, D, *, window=True, door_wall="west"):
    """Окно с радиатором — на севере, дверь — у северного конца западной стены: изголовье ложится к южной стене."""
    ops = [Opening(kind="door", wall=door_wall, offset_cm=D - 95, width_cm=80, swing_cm=80)]
    rads = []
    if window:
        ops.append(Opening(kind="window", wall="north", offset_cm=W / 2 - 60, width_cm=120, sill_cm=85))
        rads.append(Radiator(wall="north", offset_cm=W / 2 - 50, width_cm=100, depth_cm=10))
    return Room(width_cm=W, depth_cm=D, room_type="bedroom", purpose="couple", openings=ops, radiators=rads)


def _hard(lay):
    return [v.code for v in lay.violations if v.severity is Severity.HARD]


def test_roomy_bedroom_stays_on_target():
    lay = solve_bedroom(_room(420, 400), [BED] + NS + [DR, WR], "couple", engine="groups")
    assert lay.meta["clearance"]["mode"] == "target" and lay.meta["allowances"] == []
    assert lay.meta["composition"]["level"] == "A" and not _hard(lay)


def test_items_go_before_allowance():
    """Пара 330×320: по цели всё не входит — проход 1 уходит на уровень без хранения, допуск не берёт (канон: «сперва
    предметы, потом допуск»)."""
    lay = solve_bedroom(_room(330, 320), [BED] + NS + [DR, WR], "couple", engine="groups")
    assert lay.meta["clearance"]["mode"] == "target", lay.meta["clearance"]
    assert lay.meta["allowances"] == [] and not _hard(lay)
    assert {"комод", "шкаф"} & set(lay.skipped_optional)


def test_compact_when_no_level_fits_target():
    """275×330: у кровати по 55 см с боков — меньше цели 60 на любом уровне, но не меньше допуска 50 → проход 2, допуск
    строкой покупателю."""
    lay = solve_bedroom(_room(275, 330), [BED] + NS, "couple", engine="groups")
    cl = lay.meta["clearance"]
    assert cl["mode"] == "compact" and cl["target_level"] is None, cl
    assert not _hard(lay) and lay.placements
    al = lay.meta["allowances"]
    assert al and all(a["hard"] <= a["fact"] < a["target"] for a in al), al
    side = [a for a in al if a["name"] == "bed_side_couple"]
    assert side and side[0]["fact"] == 55 and side[0]["target"] == 60
    assert side[0]["text"].startswith("Компактно: у бока кровати 55 см вместо 60 — допустимо для обычной квартиры")
    assert lay.meta["allowance_text"]
    # проверка извне (по допуску) раскладку принимает; по цели — нет
    assert not [v for v in validate_bedroom(lay.room, lay.placements).violations if v.severity is Severity.HARD]
    with PN.using("target"):
        assert "BED_SIDE_PASSAGE" in [v.code for v in check_bed(lay.room, lay.placements)]


def test_allowance_names_alternative_without_item():
    """280×380 с комодом: по цели не встаёт ни один уровень (бок пары 58 < 60 на любом), проход 2 держит уровень A
    с комодом, путь от двери сужен комодом до 62 — строка называет альтернативу «без комода будет N см». (До входа от
    порога тест стоял на 300×360: там путь 53 считался с дугой двери как препятствием; от порога он 75 — цель.)"""
    lay = solve_bedroom(_room(280, 380), [BED] + NS + [DR], "couple", engine="groups")
    assert lay.meta["clearance"]["mode"] == "compact" and "комод" in {p.role for p in lay.placements}
    alts = [a for a in lay.meta["allowances"] if a["alt"] and a["alt"]["without"] == "комод"]
    assert alts, lay.meta["allowances"]
    for a in alts:
        assert a["alt"]["fact"] > a["fact"] and f"Без комода будет {int(a['alt']['fact'])} см" in a["text"]
    assert lay.meta["allowance_text"].count("Компактно") == len({a["text"] for a in lay.meta["allowances"]})


def test_refusal_with_reason():
    """250×300: у пары с двух боков меньше 50 — допуском не лечится: отказ с причиной «нельзя никогда»."""
    lay = solve_bedroom(_room(250, 300), [BED] + NS, "couple", engine="groups")
    cl = lay.meta["clearance"]
    assert cl["mode"] == "refused" and cl["refusal"], cl
    assert "COUPLE_NO_SECOND_SIDE" in cl.get("bed_blockers", []) + cl["refusal"], cl
    assert lay.meta["allowances"] == []


def test_accessible_profile_refuses_instead_of_compact():
    """Профиль M4(2) (жильё «доступное»): допусков нет — там, где обычной квартире хватает compact, отказ."""
    lay = solve_bedroom(_room(275, 330), [BED] + NS, "couple", engine="groups", profile="m4_2")
    assert lay.meta["clearance"]["mode"] == "refused" and lay.meta["clearance"]["profile"] == "m4_2"


def test_long_side_along_window_wall():
    """Бок кровати вдоль стены с окном ближе 70 — нарушение (R2 «до продольной стороны ≥ 70»); окно стены изголовья — нет."""
    room = Room(width_cm=400, depth_cm=400, room_type="bedroom", purpose="couple",
                openings=[Opening(kind="window", wall="east", offset_cm=150, width_cm=120, sill_cm=85)])
    bed = Item(role="кровать", w_cm=165, d_cm=213, h_cm=100)
    near = Placement(role="кровать", x=400 - 60 - 82.5, y=106.5, rot=0, item=bed)    # бок в 60 от восточной стены
    far = Placement(role="кровать", x=400 - 75 - 82.5, y=106.5, rot=0, item=bed)     # в 75
    assert "BED_SIDE_WINDOW_WALL" in [v.code for v in check_bed(room, [near])]
    assert "BED_SIDE_WINDOW_WALL" not in [v.code for v in check_bed(room, [far])]
    head = Placement(role="кровать", x=400 - 106.5, y=200, rot=270, item=bed)       # изголовье к восточной стене с окном
    assert "BED_SIDE_WINDOW_WALL" not in [v.code for v in check_bed(room, [head])]
    with PN.using("legacy"):
        assert "BED_SIDE_WINDOW_WALL" not in [v.code for v in check_bed(room, [near])]


def test_route_counts_from_threshold_not_swing_tip():
    """450×293 (демо, лист T-62): у двери угол шкафа и угол кровати в 59 см по диагонали. Путь к окну у западной стены
    идёт только через эту щель: по цели 75 — нет пути, по допуску 50 — есть. Прежде (дуга вырезана, «доступна любая часть
    в 75 см от дуги») кончик ядра у петли задевал дугу, и путь шёл как 75."""
    from planner.bedroom_checks import route_violations
    room = Room(width_cm=450, depth_cm=293, room_type="bedroom", purpose="couple",
                openings=[Opening(kind="door", wall="south", offset_cm=130, width_cm=85, swing_cm=85, hinge="left"),
                          Opening(kind="window", wall="west", offset_cm=40, width_cm=210, sill_cm=85)])
    ps = [Placement(role="шкаф", x=75.5, y=25, rot=0, item=Item(role="шкаф", w_cm=91, d_cm=50, h_cm=220)),
          Placement(role="кровать", x=264.5, y=188.5, rot=180, item=Item(role="кровать", w_cm=191, d_cm=209, h_cm=100))]
    assert "BR_WINDOW_UNREACHABLE" in [v.code for v in route_violations(room, ps, 75, extra=True)]
    assert "BR_WINDOW_UNREACHABLE" not in [v.code for v in route_violations(room, ps, 50, extra=True)]


def test_items_engine_unchanged_by_clearances():
    """Поштучный движок (откат) читает прежние ключи: бок 75, путь 46 (байт в байт)."""
    room = _room(420, 400)
    a = solve_bedroom(room, [BED] + NS + [DR, WR], "couple", engine="items")
    with PN.using("legacy"):
        assert PN.clearance("bed_side_couple") == 75
    assert "clearance" not in a.meta


# ─────────────── T-20261112-95: паре вторая тумба важнее режима прохода (паспорт sleep_before_mode) ───────────────
def _demo2():
    """Демо спальня 2 (450×293, чертёж №180) с радиатором под окном — как в банке."""
    return Room(width_cm=450, depth_cm=293, room_type="bedroom", purpose="couple",
                openings=[Opening(kind="door", wall="south", offset_cm=130, width_cm=85, swing_cm=85, hinge="left"),
                          Opening(kind="window", wall="west", offset_cm=40, width_cm=210, sill_cm=85, height_cm=150)],
                radiators=[Radiator(wall="west", offset_cm=55, width_cm=180, depth_cm=12)])


MINI = [Item(role="кровать", w_cm=171, d_cm=212, h_cm=36), Item(role="тумба прикроватная", w_cm=40, d_cm=35, h_cm=56),
        Item(role="тумба прикроватная 2", w_cm=40, d_cm=35, h_cm=56), Item(role="шкаф", w_cm=93, d_cm=50, h_cm=215),
        Item(role="комод", w_cm=96, d_cm=40, h_cm=90)]


def test_couple_nightstands_before_target_mode():
    """Набор банка «минимализм» в демо-спальне 2: по цели — уровень C (без тумб, NIGHTSTAND_NO_FIT), compact возвращает
    обе тумбы (A) — паре берём compact со строкой покупателю (Codex: «одна тумба + compact» выше «без тумб по цели»)."""
    lay = solve_bedroom(_demo2(), MINI, "couple", engine="groups")
    cl = lay.meta["clearance"]
    assert cl["mode"] == "compact" and cl["target_level"] == "C", cl
    assert lay.meta["sleep_variant"] == "pair" and lay.meta["composition"]["level"] == "A" and not _hard(lay)
    assert lay.meta["allowance_text"].startswith("Компактно")


def test_guest_keeps_target_without_nightstand_rule():
    """Правило — только у назначений паспорта (couple): гостевая на той же комнате идёт по цели, как было."""
    room = _demo2()
    room.purpose = "guest"
    kit = [Item(role="кровать", w_cm=146, d_cm=210, h_cm=92), Item(role="тумба прикроватная", w_cm=45, d_cm=40, h_cm=55),
           Item(role="шкаф", w_cm=93, d_cm=50, h_cm=215), Item(role="комод", w_cm=96, d_cm=40, h_cm=90)]
    lay = solve_bedroom(room, kit, "guest", engine="groups")
    assert lay.meta["clearance"]["mode"] in ("target", "refused") or lay.meta["clearance"]["target_level"] is None


def test_storage_alone_does_not_win_compact():
    """«Сперва предметы, потом допуск» для хранения остаётся: 330×320 по цели — D (обе тумбы, без хранения); compact с
    хранением (A) тумб не прибавляет — остаётся цель (тот же случай, что `test_items_go_before_allowance`)."""
    lay = solve_bedroom(_room(330, 320), [BED] + NS + [DR, WR], "couple", engine="groups")
    assert lay.meta["clearance"]["mode"] == "target" and lay.meta["sleep_variant"] == "pair"
