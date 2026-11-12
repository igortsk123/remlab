"""Паспорт прихожей `rules/room-templates/hall.json` (T-20261112-70/1 — ТЕНЬ, движок `planner/hall.py` его не читает):
схема чиста, спальня и гостиная не сломаны; семейства H1–H9 × ветки хранения (CS купе, CH распашной, M модуль, OW вешалка)
разворачиваются в места; хранение — ветка, а не ступень (внутри шаблона одно и то же на всех уровнях); уровни — целые составы
в порядке уступок консоль → банкетка → зеркало → обувница; H7 «ниша» — надстройка к закрытым веткам; выбор по флагам формы
(`WHEN_FLAGS`); числа — только `rule_ref` на настоящие ключи occupancy.json; поломанные копии паспорта ловятся."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from planner import room_templates as RT

RULES = Path(__file__).resolve().parent.parent / "rules"
FAMILIES = {"H1": "CS CH M OW", "H2": "OW M", "H3": "CS CH M OW", "H4": "CS CH M", "H5": "CS CH M OW",
            "H6": "CS CH M OW", "H8": "OW", "H9": "OW"}
IDS = [f"{f}.{b}" for f, bs in FAMILIES.items() for b in bs.split()]
STORAGE = {"шкаф-купе", "шкаф", "прихожая", "вешалка"}
BRANCH_ROLE = {"CS": "шкаф-купе", "CH": "шкаф", "M": "прихожая", "OW": "вешалка"}
YIELD = ["консоль", "банкетка", "зеркало", "обувница"]       # порядок уступок (Codex § 3)


def _doc():
    return copy.deepcopy(RT.load("hall"))


def _tpl(doc, tid):
    return next(t for t in doc["templates"] if t["id"] == tid)


def _err(doc):
    return " | ".join(RT.check(doc))


def test_hall_passport_clean():
    doc = RT.load("hall")
    assert RT.check(doc) == []
    assert doc["room_type"] == "hall"
    assert {t["id"] for t in doc["templates"]} == set(IDS) | {"H7"}


def test_other_passports_still_clean():
    assert RT.check(RT.load("bedroom")) == []
    assert RT.check(RT.load("living")) == []


@pytest.mark.parametrize("tid", IDS)
def test_each_level_compiles_and_keeps_branch_storage(tid):
    doc = RT.load("hall")
    tpl = _tpl(doc, tid)
    assert tpl["levels"]
    want = BRANCH_ROLE[tid.split(".")[1]]
    for lv in tpl["levels"]:
        places, err = RT.compile_level(doc, tpl, lv["id"])
        assert err == [], (tid, lv["id"], err)
        roles = [p["role"] for p in places]
        assert [r for r in roles if r in STORAGE] == [want], (tid, lv["id"], roles)   # хранение ветки — одно, на всех уровнях
        assert roles.count("зеркало") <= 1
        for p in places:
            if p["kind"] == "dependent":                                   # зеркало над низкой — только при носителе
                assert p["role"] == "зеркало" and p["on_failure"] == "reject_composition"


@pytest.mark.parametrize("tid", IDS)
def test_levels_yield_whole_items_in_order(tid):
    """Уровни — целые составы: каждый следующий = предыдущий без ровно одного предмета, и уходят они в порядке YIELD."""
    doc = RT.load("hall")
    tpl = _tpl(doc, tid)
    prev = None
    for lv in tpl["levels"]:
        places, _ = RT.compile_level(doc, tpl, lv["id"])
        roles = {p["role"] for p in places}
        if prev is not None:
            gone = prev - roles
            assert roles < prev and len(gone) == 1, (tid, lv["id"], gone)
            assert gone <= set(YIELD)
            assert all(r not in roles for r in YIELD[: YIELD.index(gone.pop())]), (tid, lv["id"])
        prev = roles
    assert tpl["levels"][-1]["id"] == "E" and len(prev) == 1      # последний — только хранение


def test_niche_modifier_applies_to_closed_branches_only():
    doc = RT.load("hall")
    h7 = _tpl(doc, "H7")
    assert h7["modifier"] and h7["applies_to"]
    assert all(t.endswith((".CS", ".CH")) for t in h7["applies_to"])
    for base in h7["applies_to"]:
        btpl = _tpl(doc, base)
        places, err = RT.compile_level(doc, h7, "N", base=(btpl, "C"))
        assert err == [], err
        assert [p["role"] for p in places if p["role"] in STORAGE] == ["шкаф-купе"], base   # шкаф ветки заменён купе в нише


@pytest.mark.parametrize("facts, first", [
    ({"has_stairs": True, "shape_l": True, "area_m2": 9}, "H9.OW"),
    ({"micro": True, "area_m2": 1.2}, "H8.OW"),
    ({"shape_l": True, "door_dense": True}, "H6.CS"),
    ({"door_dense": True, "area_m2": 9}, "H3.CS"),
    ({"squareish": True, "area_m2": 4}, "H5.CS"),
    ({"has_niche": True, "area_m2": 7}, "H4.CS"),          # ниша — надстройка, не выбор семейства
    ({}, "H4.CS"),
])
def test_selection_by_shape_flags(facts, first):
    order = RT.select(RT.load("hall"), facts)
    assert order[0] == first
    assert "H7" not in order
    assert order[-1].startswith(("H8", "H2"))   # узкая линия / тамбур — последний запас в каждом правиле
    assert len(order) == len(set(order))


def test_shape_flags_are_room_facts_not_numbers():
    for k in ("shape_l", "has_niche", "has_stairs", "door_dense", "squareish", "micro"):
        assert k in RT.WHEN and k in RT.WHEN_FLAGS
        assert RT.when_ok([{"kind": k}], {k: True})
        assert not RT.when_ok([{"kind": k}], {k: False})
        assert not RT.when_ok([{"kind": k}], {})              # неизвестный факт — условие не выполнено


def test_rule_refs_point_to_real_occupancy_keys():
    occ = json.loads((RULES / "occupancy.json").read_text())
    refs = []

    def walk(x):
        if isinstance(x, dict):
            for k, v in x.items():
                if k == "rule_ref":
                    refs.append(v)
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(RT.load("hall"))
    assert refs, "паспорт без rule_ref — числа должны идти ссылками на occupancy.json"
    for r in refs:
        sec, _, key = r.partition(".")
        assert key.split("[")[0] in occ[sec], r


def test_no_bare_numbers_in_rules():
    """Пороги — только rule_ref: в predicates/relations нет числовых полей (кроме count носителя)."""
    for t in RT.load("hall")["templates"]:
        for sec in ("predicates", "relations"):
            for x in t.get(sec, []):
                assert not [k for k, v in x.items() if isinstance(v, (int, float)) and not isinstance(v, bool)], (t["id"], x)


@pytest.mark.parametrize("break_it, msg", [
    (lambda d: d["templates"][0]["levels"][0]["use"].update({"storage": "wall_hooks"}), "storage"),
    (lambda d: d["templates"][-1]["applies_to"].append("H99.CS"), "H99.CS"),
    (lambda d: d["groups"]["mirror"]["variants"]["over_low"]["dependents"][0].pop("carrier"), "carrier"),
    (lambda d: d["selection"][0]["when"].append({"kind": "has_garage"}), "has_garage"),
    (lambda d: d["templates"][1].setdefault("relations", []).append({"kind": "mirror_on_ceiling"}), "mirror_on_ceiling"),
    (lambda d: d["templates"][2]["levels"][0]["use"].pop("storage"), "storage"),
])
def test_broken_copies_are_caught(break_it, msg):
    doc = _doc()
    break_it(doc)
    err = _err(doc)
    assert err and msg in err, err
