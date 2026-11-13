"""Каталог шаблонов спальни `rules/room-templates/bedroom-catalog.json` (T-20261112-120 — ТЕНЬ: движок `planner/bedroom.py`
читает `bedroom.json`, этот паспорт — нет; план `plans/bedroom-templates-catalog-01.md`, исследование Codex
`_intake/codex/2026-11-12-bedroom-templates-answer.md`): схема чиста; 18 шаблонов (17 по Codex + кандидат прогона br.single_head_wall); у каждого назначения есть шаблон; каждый уровень
разворачивается в места; пара — с двумя тумбами, хранение есть везде, кроме «внешнего хранения»; работа обязательна там, где шаблон —
кабинет/школьник; зависимые (шторы, общий свет, лампа на тумбу) на каждом уровне со сном; числа — только `rule_ref` на ключи
occupancy.json; живой выбор движка не изменился."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from planner import room_templates as RT

RULES = Path(__file__).resolve().parent.parent / "rules"
IDS = {"br.couple_axis_side_storage", "br.couple_axis_foot_storage", "br.couple_cross_long", "br.couple_dressing",
       "br.couple_wardrobe_zone", "br.couple_office", "br.single_double_comfort", "br.single_corner", "br.single_head_wall", "br.single_work_window",
       "br.guest_double", "br.guest_office_flex", "br.twin_parallel", "br.child_0_3_cot", "br.child_3_7_play",
       "br.child_7_12_work", "br.teen_work", "br.accessible_principal"}
PURPOSES = ["couple", "single", "single_narrow", "guest", "office", "twin", "child:0-3", "child:3-7", "child:7-12", "child:teen", "child"]
STORAGE_ROLES = {"шкаф", "комод", "стеллаж", "гардеробная система"}
WORK_TEMPLATES = {"br.couple_office", "br.single_work_window", "br.child_7_12_work", "br.teen_work", "br.guest_office_flex"}
NUM_OK = {"priority", "count", "sides", "w", "h"}      # литералы разрешены только тут; остальные числа — rule_ref


def _doc():
    return copy.deepcopy(RT.load("bedroom-catalog"))


def _places(doc, tpl, lid):
    places, err = RT.compile_level(doc, tpl, lid)
    assert err == [], f"{tpl['id']}.{lid}: {err}"
    return places


def test_schema_clean_and_live_untouched():
    assert RT.check(_doc()) == []
    assert RT.check(RT.load("bedroom")) == []
    live = json.loads((RULES / "room-templates" / "bedroom.json").read_text(encoding="utf-8"))
    assert len(live["templates"]) == 4
    assert RT.template_for("bedroom", "couple")["id"] == "br.pair_axis"   # движок по-прежнему видит только живой паспорт


def test_exactly_18_templates():
    ids = [t["id"] for t in _doc()["templates"]]
    assert len(ids) == len(set(ids)) == 18
    assert set(ids) == IDS


@pytest.mark.parametrize("purpose", PURPOSES)
def test_every_purpose_has_template(purpose):
    assert any(purpose in t["purpose"] for t in _doc()["templates"]), purpose


def test_every_level_compiles_and_has_sleep_or_work():
    doc = _doc()
    for t in doc["templates"]:
        assert t["levels"], t["id"]
        for lv in t["levels"]:
            roles = {p["role"] for p in _places(doc, t, lv["id"]) if p["kind"] == "slot"}
            if t.get("label_without", {}).get("group") == "sleep":     # кабинет-гостевая без дивана — честно «кабинет»
                assert roles & {"кровать", "кроватка", "диван-кровать", "стол рабочий"}, f"{t['id']}.{lv['id']}: пусто"
                continue
            assert roles & {"кровать", "кроватка", "диван-кровать"}, f"{t['id']}.{lv['id']}: нет спального места"


def test_couple_levels_have_two_bedside_tables():
    doc = _doc()
    for t in doc["templates"]:
        if t["purpose"] != ["couple"] or t["id"] == "br.accessible_principal":
            continue
        for lv in t["levels"]:
            ns = [p for p in _places(doc, t, lv["id"]) if p["role"] == "тумба прикроватная"]
            assert ns and ns[0]["count"] == 2, f"{t['id']}.{lv['id']}: паре — обе тумбы (владелец TG 1364)"


def test_storage_everywhere_unless_external():
    doc = _doc()
    for t in doc["templates"]:
        for lv in t["levels"]:
            ext = any(w.get("kind") == "external_storage" for w in lv.get("when") or [])
            roles = {p["role"] for p in _places(doc, t, lv["id"]) if p["kind"] == "slot"}
            if not ext:
                assert roles & STORAGE_ROLES, f"{t['id']}.{lv['id']}: нет хранения"


def test_work_required_where_template_is_work():
    doc = _doc()
    for t in doc["templates"]:
        if t["id"] not in WORK_TEMPLATES:
            continue
        for lv in t["levels"]:
            desk = [p for p in _places(doc, t, lv["id"]) if p["role"] == "стол рабочий"]
            assert desk and desk[0]["required"], f"{t['id']}.{lv['id']}: стол обязателен"


def test_work_templates_need_flag():
    """Шаблоны со столом у пары/одного — только когда стол просили (`work_needed`), иначе они обгоняли бы спальни без стола."""
    for t in _doc()["templates"]:
        if t["id"] in {"br.couple_office", "br.single_work_window"}:
            assert any(w["kind"] == "work_needed" for w in t["when"]), t["id"]
    assert RT.when_ok([{"kind": "work_needed"}], {"work_needed": False}) is False


def test_finish_dependents_on_every_sleep_level():
    doc = _doc()
    for t in doc["templates"]:
        for lv in t["levels"]:
            ps = _places(doc, t, lv["id"])
            deps = {p["role"] for p in ps if p["kind"] == "dependent"}
            assert "шторы" in deps, f"{t['id']}.{lv['id']}: нет штор"
            assert deps & {"люстра", "светильник потолочный"}, f"{t['id']}.{lv['id']}: нет общего света"
            if any(p["role"] == "тумба прикроватная" for p in ps):
                lamp = [p for p in ps if p["kind"] == "dependent" and p["carrier"].get("slot_ref") == "sleep.ns"]
                assert lamp, f"{t['id']}.{lv['id']}: на тумбе нет лампы"


def _walk(node, path=""):
    if isinstance(node, dict):
        for k, v in node.items():
            yield from _walk(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _walk(v, f"{path}[{i}]")
    else:
        yield path, node


def test_numbers_only_via_rule_ref():
    doc = _doc()
    for path, v in _walk({k: doc[k] for k in ("groups", "templates")}):
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            key = path.rsplit(".", 1)[-1]
            assert key in NUM_OK, f"литерал {v} в {path} — числа только через rule_ref"
        if path.endswith(".rule_ref"):
            assert RT.rule_value(v) is not None, f"{path}: {v} не найден в occupancy.json"


def test_bed_ladders_resolve():
    bc = RT._distances()["bedroom_catalog"]
    for k, lad in bc["bed_width_ladder"].items():
        if k.startswith("_"):
            continue
        assert lad and all(isinstance(x, (int, float)) for x in lad), k
        assert lad == sorted(lad, reverse=True) or k == "child_3_7", f"{k}: лестница — от широкой к узкой"
    for k in ("couple", "single", "guest_double", "guest_office", "twin", "child_0_3", "child_3_7", "child_7_12", "teen"):
        assert bc["area_min_m2"][k] > 0
    assert bc["wardrobe_front_cm"]["couple"]["min"] <= bc["wardrobe_front_cm"]["couple"]["target"]


def test_broken_copy_caught():
    doc = _doc()
    doc["templates"][0]["levels"][0]["use"]["sleep"] = "no_such_variant"
    assert RT.check(doc)
