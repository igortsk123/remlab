"""Паспорт полной гостиной `rules/room-templates/living.json` (T-20261112-63/1, план living-full-01 Т1 шаг 0 — тень):
схема чиста, спальня не сломана, каждый шаблон LR-C1…L2 и модификатор X1 разворачиваются в места, уровни — целые составы,
поломанные копии паспорта ловятся проверкой, реестр geometry_ref указывает на настоящие схемы старого движка, зеркала норм
совпадают с источниками."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from planner import room_templates as RT

RULES = Path(__file__).resolve().parent.parent / "rules"
ROOT = RULES.parent.parent.parent
IDS = ["LR-C1", "LR-C2", "LR-C3", "LR-M1", "LR-O1", "LR-O2", "LR-L1", "LR-L2"]
CORE_ROLES = {"диван", "столик", "ковёр", "тв-тумба", "экран", "подушка", "плед", "люстра", "шторы"}


def _doc():
    return copy.deepcopy(RT.load("living"))


def _tpl(doc, tid):
    return next(t for t in doc["templates"] if t["id"] == tid)


def _err(doc):
    return " | ".join(RT.check(doc))


def test_living_passport_clean():
    assert RT.check(RT.load("living")) == []
    assert {t["id"] for t in RT.load("living")["templates"]} == set(IDS) | {"LR-X1"}


def test_bedroom_passport_still_clean():
    assert RT.check(RT.load("bedroom")) == []
    tpl = RT.template_for("bedroom", "couple")
    places, err = RT.compile_level(RT.load("bedroom"), tpl, "A")
    assert err == []
    assert {(p["role"], p["count"]) for p in places} >= {("кровать", 1), ("тумба прикроватная", 2), ("шкаф", 1)}


@pytest.mark.parametrize("tid", IDS)
def test_each_template_level_compiles_to_places(tid):
    doc = RT.load("living")
    tpl = _tpl(doc, tid)
    assert tpl["levels"]
    for lv in tpl["levels"]:
        places, err = RT.compile_level(doc, tpl, lv["id"])
        assert err == [], err
        roles = {p["role"] for p in places}
        assert CORE_ROLES <= roles, (lv["id"], CORE_ROLES - roles)
        assert ("лампа" in roles) != ("торшер" in roles), lv["id"]   # свет — ровно один вариант уровня
        screen = [p for p in places if p["role"] == "экран"]
        assert len(screen) == 1 and screen[0]["sellable"] is False and screen[0]["marker"] == "virtual_screen"
        for p in places:
            if p["kind"] == "dependent":   # условное место «при глухой стене» — только картины (T-71); остальное — отказ уровня
                assert p["on_failure"] == ("leave_empty" if p["role"] == "картина" else "reject_composition"), p["id"]


def test_x1_modifier_compiles_on_every_base_level():
    doc = RT.load("living")
    x1 = _tpl(doc, "LR-X1")
    assert x1["modifier"] and set(x1["applies_to"]) == set(IDS)
    n = 0
    for tid in IDS:
        base = _tpl(doc, tid)
        for blv in base["levels"]:
            for lv in x1["levels"]:
                places, err = RT.compile_level(doc, x1, lv["id"], base=(base, blv["id"]))
                assert err == [], err
                n += 1
                if lv["id"] == "XB":   # кашпо в эркере ЗАМЕНЯЕТ напольное место основного состава, второго нет
                    assert [p["geometry_ref"] for p in places if p["role"] == "кашпо"] == ["decor.bay_plant"]
    assert n > 0
    assert RT.template_for("living", "living")["id"] == "LR-C1"   # модификатор шаблоном назначения не выбирается


def test_dependents_sit_on_carriers():
    doc = RT.load("living")
    places, _ = RT.compile_level(doc, _tpl(doc, "LR-M1"), "A4")
    by = {p["id"]: p for p in places}
    assert by["soft.pillows"]["carrier"] == {"slot_ref": "seating.sofa"}
    assert by["soft.pillows"]["anchor"] == {"kind": "item_surface", "surface": "seat"}
    assert by["soft.pillows"]["cardinality"]["kind"] == "by_carrier_width"
    assert by["vase.vase"]["carrier"] == {"slot_ref": "seating.coffee"}
    assert by["light.lamp"]["carrier"] == {"slot_ref": "light.dresser"}
    assert by["ceiling.chandelier"]["carrier"] == {"zone": "seating"}
    assert by["textile.curtains"]["when"] == [{"kind": "room_has_window"}]
    assert by["plant.planter"]["kind"] == "slot"   # напольное кашпо — обычное место пола, не на носителе
    o1, _ = RT.compile_level(doc, _tpl(doc, "LR-O1"), "A4")
    assert {p["id"] for p in o1 if p["role"] == "люстра"} == {"ceiling.chandelier", "ceiling.pendant"}


def _use(tpl, lid):
    return next(lv["use"] for lv in tpl["levels"] if lv["id"] == lid)


def test_levels_are_whole_compositions_as_t0_schemes():
    """Как `tools/scout/living_schemes.py:levels_for`: < 16 м² — SA…SE; ≥ 16 — A (стол по бюджету) → B (на 2 меньше,
    на 2 — компактный) → D (торшер вместо «комод + лампа»). Торшер — отдельный уровень, а не выкидывание лампы."""
    doc = RT.load("living")
    c1 = _tpl(doc, "LR-C1")
    assert RT.levels_for(c1, {"area_m2": 14.4}) == ["SA", "SB", "SC", "SD", "SE"]
    assert RT.levels_for(c1, {"area_m2": 17}) == ["A2", "B2", "D2"]
    assert RT.levels_for(c1, {"area_m2": 24}) == ["A4", "B4", "D4"]
    o1 = _tpl(doc, "LR-O1")
    assert RT.levels_for(o1, {"area_m2": 45}) == ["A6", "B6", "D6"]
    a6, b6, d6 = (_use(o1, k) for k in ("A6", "B6", "D6"))
    assert (a6["dining"], b6["dining"]) == ("table_6", "table_4")      # столовая 6 → 4
    assert (_use(o1, "A4")["dining"], _use(o1, "B4")["dining"]) == ("table_4", "table_2")
    assert (_use(o1, "A2")["dining"], _use(o1, "B2")["dining"]) == ("table_2", "table_2_compact")
    assert {k: v for k, v in d6.items() if k not in ("light", "art")} == {k: v for k, v in b6.items() if k not in ("light", "art")}
    assert (b6["light"], d6["light"]) == ("dresser_lamp", "floor_lamp")
    sa, sb, sc, sd, se = (_use(c1, k) for k in ("SA", "SB", "SC", "SD", "SE"))
    assert sa["seating"] == "sofa_table_rug" and _use(c1, "A2")["seating"] == "sofa_armchair"   # кресло — от 16 м²
    assert set(sa) - set(sb) == {"plant"} and sc["dining"] == "table_2_compact"
    assert all(x["vase"] == "vase_on_coffee" for x in (sa, sb, sc, sd, se))     # ваза на столике у всех малых (T-71)
    assert sd["light"] == "floor_lamp" and "dining" not in se
    m1 = _tpl(doc, "LR-M1")
    assert RT.level_of(m1, {**_use(m1, "B4")}, {"area_m2": 30}) == (RT.level_index(m1, "B4"), "B4")


@pytest.mark.parametrize("facts,order", [
    ({"area_m2": 14.4, "aspect": 1.35}, ["LR-C1", "LR-C2"]),          # демо 439×325
    ({"area_m2": 15.0, "aspect": 1.67}, ["LR-C2", "LR-C1"]),          # 300×500
    ({"area_m2": 16.0, "aspect": 1.2}, ["LR-M1", "LR-C3", "LR-C1"]),  # граница 16 — уже «от 16»
    ({"area_m2": 20.0, "aspect": 1.5}, ["LR-C2", "LR-M1"]),
    ({"area_m2": 28.0, "aspect": 1.5}, ["LR-L1", "LR-M1", "LR-C3"]),
    ({"area_m2": 33.0, "aspect": 1.3}, ["LR-L1", "LR-M1", "LR-C3"]),
    ({"area_m2": 41.6, "aspect": 1.3}, ["LR-L2", "LR-L1"]),
    ({"area_m2": 20.8, "aspect": 1.3, "kitchen": True}, ["LR-O1", "LR-O2"]),
    ({"area_m2": 30.25, "aspect": 1.5, "annex": True}, ["LR-L1", "LR-M1"]),
])
def test_selection_matches_t0_choose_templates(facts, order):
    """Те же ответы, что `tools/scout/living_schemes.py:choose_templates` (схемы Т0 владельца) — из паспорта и порогов
    `distances_cm.living_select`, без импорта scout."""
    assert RT.select(RT.load("living"), facts) == order


def test_dining_budget_from_zones():
    assert [RT.dining_budget(a) for a in (14, 21.9, 22, 39.9, 40)] == [2, 2, 4, 4, 6]


def test_pillow_count_norm_matches_t0_schemes():
    """`living_schemes.py:pillow_count`: 2 до 189, 3 при 190–253, 4 от 254."""
    rule = RT.rule_value("distances_cm.dependents.sofa_pillow_count")["by_outer_width_cm"]
    assert [RT.count_by_width(rule, w) for w in (150, 189, 190, 253, 254, 300)] == [2, 2, 3, 3, 4, 4]


def test_geometry_registry_points_to_old_engine_schemes():
    zones = json.loads((RULES / "templates.json").read_text(encoding="utf-8"))["zones"]
    for key, g in RT.GEOMETRY.items():
        assert g["zone"] in zones, key
        if g["scheme"] is not None:
            assert g["scheme"] in {s["id"] for s in zones[g["zone"]].get("schemes", [])}, key
    used = set()
    for spec in RT.load("living")["groups"].values():
        for var in spec["variants"].values():
            used |= {var.get("geometry_ref")} | {s.get("geometry_ref") for s in var.get("slots", [])}
    assert used - {None} <= set(RT.GEOMETRY)


def test_mounting_mirrors_equal():
    """Зеркала `distances_cm.mounting` = исходные ключи (occupancy `_mirrors`): числа не менялись."""
    occ = json.loads((RULES / "occupancy.json").read_text(encoding="utf-8"))
    h, m = occ["heights_cm"], occ["distances_cm"]["mounting"]
    art = json.loads((ROOT / "data" / "flat3d" / "wall-art.json").read_text(encoding="utf-8"))
    pairs = [(m["wall_art"]["bottom_above_carrier"], h["art_bottom_above_sofa_back"]),
             (m["wall_art"]["center_from_floor"], h["art_center"]),
             (m["wall_art"]["gap_between_frames"], h["art_gap_between_frames"]),
             (m["wall_art"]["width_share_of_carrier"], art["share"]),
             (m["wall_art"]["width_share_range"], art["share_range"]),
             (m["wall_art"]["max_count"], art["max_count"]),
             (m["wall_art"]["ceiling_gap"], art["ceiling_gap_cm"]),
             (m["wall_art"]["opening_clear"], art["opening_clear_cm"]),
             (m["wall_carrier"]["back_gap_max"], art["back_gap_cm"]),
             (m["wall_carrier"]["wall_edge"], art["wall_edge_cm"]),
             (m["chandelier"]["bottom_min"], h["chandelier_bottom_min"]),
             (m["chandelier"]["above_dining_table"], h["chandelier_above_dining_table"]),
             (m["chandelier"]["over_seating_bottom"], h["pendant_over_sofa"]),
             (m["wall_planter"]["over_passage_bottom_min"], h["chandelier_bottom_min"]),
             # T-20261112-91: экран паспорта — на той же норме, что живая сцена и серверный кадр (occupancy.hung_furniture)
             (m["tv_screen"]["center_from_floor"], occ["hung_furniture"]["tv_center_range_cm"]),
             (m["tv_screen"]["center_from_floor_over55inch"], occ["hung_furniture"]["tv_center_range_cm"])]
    for a, b in pairs:
        assert a == b
    ts = (ROOT / "lib" / "viewer3d" / "scene-extras.ts").read_text(encoding="utf-8")
    assert f"TV_MAX_STAND_FRAC = {m['tv_screen']['max_share_of_stand']};" in ts
    assert "distances_cm.mounting" in occ["_mirrors"]


# ── поломанные копии паспорта ловятся ──

def _var(doc, g, v):
    return doc["groups"][g]["variants"][v]


def test_broken_cycle_caught():
    doc = _doc()
    sofa = _var(doc, "seating", "sofa_armchair")["slots"][0]
    sofa["near"] = "seating.armchair"      # диван ← кресло ← столик ← диван
    assert "цикл зависимостей" in _err(doc)


def test_broken_dangling_carrier_caught():
    doc = _doc()
    _var(doc, "vase", "vase_on_coffee")["dependents"][0]["carrier"] = {"slot_ref": "seating.nope"}
    assert "seating.nope — ссылка в никуда" in _err(doc)


def test_carrier_absent_from_level_caught():
    doc = _doc()
    tpl = _tpl(doc, "LR-C1")
    next(g for g in tpl["groups"] if g["id"] == "vase")["variants"].append("vase_on_dresser")
    next(lv for lv in tpl["levels"] if lv["id"] == "SD")["use"]["vase"] = "vase_on_dresser"   # SD — торшер, комода нет
    assert "LR-C1.SD: vase.vase — носителя light.dresser нет в составе уровня" in _err(doc)


@pytest.mark.parametrize("where,mutate,frag", [
    ("anchor", lambda d: _var(d, "soft", "pillows_throw")["dependents"][0]["anchor"].update(kind="hover"), "anchor kind 'hover' неизвестен"),
    ("predicate", lambda d: _tpl(d, "LR-M1")["predicates"].append({"kind": "teleport"}), "predicates kind 'teleport' неизвестен"),
    ("cardinality", lambda d: _var(d, "soft", "pillows_throw")["dependents"][1]["cardinality"].update(kind="many"), "cardinality kind 'many'"),
    ("when", lambda d: _tpl(d, "LR-M1")["levels"][0]["when"].append({"kind": "full_moon"}), "when kind 'full_moon' неизвестен"),
    ("support", lambda d: _var(d, "textile", "curtains")["dependents"][0]["carrier"].update(support="roof"), "carrier.support 'roof'"),
])
def test_broken_unknown_kind_caught(where, mutate, frag):
    doc = _doc()
    mutate(doc)
    assert frag in _err(doc), where


def test_broken_geometry_ref_outside_registry_caught():
    doc = _doc()
    _var(doc, "seating", "u_sofa_2armchairs")["geometry_ref"] = "planner.template.place_u"
    _tpl(doc, "LR-L1")["geometry_ref"] = "os.system"
    e = _err(doc)
    assert "'planner.template.place_u' вне реестра" in e and "'os.system' вне реестра" in e


def test_broken_on_failure_not_reject_caught():
    doc = _doc()
    _var(doc, "art", "over_sofa_or_dresser")["dependents"][0]["on_failure"] = "drop_item"
    assert "on_failure 'drop_item' — допустимо ['leave_empty', 'reject_composition']" in _err(doc)


def test_broken_slot_required_caught():
    doc = _doc()
    _var(doc, "plant", "floor")["slots"][0]["required"] = "иногда"
    _var(doc, "seating", "sofa_armchair")["slots"][3]["required"] = [{"kind": "full_moon"}]
    e = _err(doc)
    assert "required — true/false или список условий when" in e and "when kind 'full_moon' неизвестен" in e


# ── выбор уровня по набору (T-20261112-71, ADR-0391) ──

FULL = {"area_m2": 20.0, "aspect": 1.2}          # 16–28 м², не вытянутая → LR-M1, LR-C3, LR-C1
NEED_M1 = {"seating.sofa": 1, "seating.coffee": 1, "seating.rug": 1, "seating.armchair": 1, "media.tv_stand": 1}


def _found(have: dict):
    """found_of для `levels_by_set`: столько предметов на место, сколько есть в наборе (как сопоставление тени); угловое
    место дивана — только угловой диван (`corner_sofa` в наборе)."""
    def key(p):
        return "corner_sofa" if p["variant"] == "corner_sofa" and p["id"] == "seating.sofa" else p["id"]
    return lambda places: {p["id"]: min(p.get("count", 1), have.get(key(p), 0)) for p in places if p["kind"] == "slot"}


def test_by_set_optional_role_absent_place_stays_empty():
    """Нет торшера и комода (свет — по желанию), нет стола и стульев в гостиной (не кухня) — уровень всё равно годен, места
    пусты; лампа уходит вместе с комодом, поэтому уровень с торшером (одно пустое место) раньше уровня с комодом."""
    good, _ = RT.levels_by_set(RT.load("living"), FULL, _found({**NEED_M1, "plant.planter": 1}))
    first = good[0]
    assert (first["tpl"], first["level"]) == ("LR-M1", "D2"), [(g["tpl"], g["level"], g["empty"]) for g in good[:4]]
    assert set(first["empty"]) == {"light.floor_lamp×1", "dining.table×1", "dining.chairs×2"}
    ids = {p["id"] for p in first["places"]}
    assert not ids & {"light.floor_lamp", "dining.table", "dining.chairs", "ceiling.pendant"}
    assert {"seating.sofa", "soft.pillows", "art.art", "vase.vase"} <= ids


def test_by_set_fewer_empty_first_then_passport_order():
    """Есть торшер и стол на 2 — D2 без пустых раньше A2 (пустой комод с лампой); есть и комод — порядок паспорта (A2)."""
    have = {**NEED_M1, "plant.planter": 1, "dining.table": 1, "dining.chairs": 2, "light.floor_lamp": 1}
    good, _ = RT.levels_by_set(RT.load("living"), FULL, _found(have))
    assert (good[0]["level"], good[0]["empty"]) == ("D2", [])
    good, _ = RT.levels_by_set(RT.load("living"), FULL, _found({**have, "light.dresser": 1}))
    assert [g["level"] for g in good[:3]] == ["A2", "B2", "D2"]


def test_by_set_required_role_absent_next_level_then_honest_refusal():
    """Кресло обязательно от 16 м²: нет его — LR-M1 и LR-C1 (≥16 — с креслом) не годны целиком, угловой C3 без углового
    дивана — тоже; годных нет — честный отказ с перечнем, чего не хватает."""
    have = {k: v for k, v in NEED_M1.items() if k != "seating.armchair"}
    good, bad = RT.levels_by_set(RT.load("living"), FULL, _found(have))
    assert good == []
    m1 = [b for b in bad if b["tpl"] == "LR-M1"]
    assert m1 and all("seating.armchair×1" in b["missing"] for b in m1)
    # меньше 16 м²: кресла в составе нет, кашпо и стол — по желанию → годны все малые; меньше всего пустого у SE (без стола)
    good, _ = RT.levels_by_set(RT.load("living"), {"area_m2": 14.4, "aspect": 1.35}, _found(have))
    assert [(g["tpl"], g["level"], g["empty"]) for g in good[:1]] == [("LR-C1", "SE", ["light.floor_lamp×1"])]
    sa = next(g for g in good if g["tpl"] == "LR-C1" and g["level"] == "SA")
    assert "plant.planter×1" in sa["empty"]


def test_by_set_kitchen_dining_required():
    """Кухня-гостиная: стол и стулья обязательны («по типу комнаты») — без стола уровня нет; в гостиной — место пусто."""
    have = {**NEED_M1, "plant.planter": 1, "light.floor_lamp": 1}
    good, bad = RT.levels_by_set(RT.load("living"), {**FULL, "kitchen": True}, _found(have))
    assert good == [] and all("dining.table×1" in b["missing"] for b in bad if "missing" in b)
    assert RT.slot_required({"required": [{"kind": "kitchen"}]}, {"kitchen": False}) is False
    assert RT.slot_required({}, {}) is True and RT.slot_required({"required": False}, {}) is False


def test_broken_unknown_field_and_rule_ref_caught():
    doc = _doc()
    _var(doc, "seating", "sofa_armchair")["slots"][0]["colour"] = "red"
    _var(doc, "ceiling", "chandelier_seating")["dependents"][0]["placement"]["rule_ref"] = "distances_cm.mounting.nope"
    e = _err(doc)
    assert "неизвестные поля ['colour']" in e and "distances_cm.mounting.nope нет в occupancy.json" in e


def test_broken_level_without_places_and_bad_modifier_caught():
    doc = _doc()
    doc["groups"]["dining"]["variants"]["table_9"] = {"slots": []}
    tpl = _tpl(doc, "LR-M1")
    next(g for g in tpl["groups"] if g["id"] == "dining")["variants"].append("table_9")
    tpl["levels"][0]["use"]["dining"] = "table_9"
    _tpl(doc, "LR-X1")["applies_to"].append("LR-Z9")
    e = _err(doc)
    assert "вариант dining.table_9 не разворачивается в места" in e and "applies_to LR-Z9" in e
