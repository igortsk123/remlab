"""Правила спальни (план onb-05): у каждого правила — проверка или `_enforce: none` (урок 199); числа норм — одно
место, `rules/occupancy.json` distances_cm (урок 194)."""
from __future__ import annotations

import json
import os
import re

ROOT = os.path.join(os.path.dirname(__file__), "..")
BEDROOM_NUMS = ("bed_side_passage", "bed_foot_min", "bed_head_zone", "bed_radiator_soft", "desk_chair_clear",
                "desk_window_max", "bedroom_floor_max_pct", "wardrobe_hinged_front_min", "dresser_front")


def _load(name):
    with open(os.path.join(ROOT, "rules", name), encoding="utf-8") as f:
        return json.load(f)


def _src(name):
    with open(os.path.join(ROOT, "planner", name), encoding="utf-8") as f:
        return f.read()


def test_every_bedroom_rule_is_enforced():
    code = _src("bedroom_checks.py") + _src("validate.py") + _src("bedroom.py")
    rules = _load("bedroom.json")["rules"]
    for rid, r in rules.items():
        enf = r.get("_enforce")
        assert enf, f"{rid}: нет _enforce"
        if enf == "none":
            assert r.get("_why"), f"{rid}: _enforce none без причины"
            continue
        for c in re.findall(r"\b[A-Z][A-Z_]{3,}\b", enf):
            assert f'"{c}"' in code, f"{rid}: код {c} не найден в проверках"


def test_bedroom_numbers_live_in_occupancy():
    dist = _load("occupancy.json")["distances_cm"]
    for k in BEDROOM_NUMS:
        assert k in dist, f"норма {k} не в occupancy.json distances_cm"
    for rid, r in _load("bedroom.json")["rules"].items():
        if "num" in r:
            key = r["num"].split(".", 1)[1]
            assert key in dist, f"{rid}: ссылка на {r['num']} — ключа нет"


def test_numbers_not_hardcoded_in_bedroom_json():
    """Состав и шаблоны — в bedroom.json, а числа норм — только ссылкой (иначе второй источник истины)."""
    for rid, r in _load("bedroom.json")["rules"].items():
        nums = {k: v for k, v in r.items() if isinstance(v, (int, float, list))}
        assert not nums, f"{rid}: число в bedroom.json {nums} — его место occupancy.json"


def test_purposes_match_adr_vocabulary():
    assert set(_load("bedroom.json")["purposes"]) == {"couple", "single", "child", "office", "guest"}
