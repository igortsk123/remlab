"""Общий формат комнатного шаблона `room-composition/1` (T-20261112-38/2; проект контракта —
`.memory_bank/_intake/codex/2026-11-12-bedroom-templates-answer.md` § «Универсальный формат»).

Один модуль на все комнаты: паспорта лежат в `rules/room-templates/<room_type>.json`, здесь — загрузка, проверка схемы
и выбор уровня. Геометрия групп (как ставится «сон» pair, «работа» и т. п.) — в движке комнаты (спальня —
`planner/bedroom.py:_solve_groups`); формат описывает ЧТО ставить и в каком порядке уступать, а не координаты.

Сущности паспорта:
  groups      — группы комнаты: роли и варианты группы (общие для всех шаблонов комнаты);
  order       — порядок групп по умолчанию (обязательные по назначению — раньше, это решает движок);
  templates[] — шаблон: id, purpose (назначения; детская — `child:<возраст>`), priority, anchors, predicates, groups
                (какие группы и варианты в этом шаблоне, required), relations, levels (ЦЕЛЫЕ разрешённые составы по
                порядку предпочтения), next_step (ступень до уровня, например кровать 140 у пары), label_without
                (метка комнаты без группы: спальня без кровати — «кабинет»), invariants, selection_tags.
Числа — только через `rule_ref` на `occupancy.json` (distances_cm.*); формулы строками не пишем.

Новая комната (например гостиная): `rules/room-templates/living.json` с теми же полями → `load('living')`,
`check(doc)` в тесте, движок комнаты читает `template_for`/`level_of`/`group_of`. Новые kind — в KINDS ниже.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

SCHEMA = "room-composition/1"
DIR = Path(__file__).resolve().parent.parent / "rules" / "room-templates"
OCCUPANCY = Path(__file__).resolve().parent.parent / "rules" / "occupancy.json"

# известные kind — неизвестный в паспорте = ошибка схемы (Codex: «запретить неизвестные kind»)
KINDS = {
    "anchors": {"wall_segment", "corner", "window", "door", "niche"},
    "predicates": {"side_access", "door_swing_clear", "route", "bed_sleep_width", "area_max", "aspect_min"},
    "relations": {"no_storage_in_sleep_side_zone", "no_storage_in_sleep_or_work_access", "storage_front_radiator",
                  "no_wardrobe_small_square", "reserve_wall_for"},
    "invariants": {"sku_dimensions_intact", "door_clear", "required_routes", "required_roles"},
    "next_step": {"bed_sleep_width"},
}


@lru_cache(maxsize=None)
def load(room_type: str) -> dict:
    """Паспорт комнаты; нет файла — {} (комната ещё не переведена на формат)."""
    p = DIR / f"{room_type}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _distances() -> dict:
    return json.loads(OCCUPANCY.read_text(encoding="utf-8")).get("distances_cm", {})


def check(doc: dict) -> list[str]:
    """Ошибки схемы паспорта (пусто — годен): версия, неизвестные kind, ссылки на несуществующие группы/варианты,
    уровни без обязательной группы, rule_ref мимо occupancy.json, повтор id."""
    err = []
    if doc.get("schema_version") != SCHEMA:
        err.append(f"schema_version {doc.get('schema_version')!r} ≠ {SCHEMA}")
    groups = doc.get("groups") or {}
    dist = _distances()
    for g in doc.get("order", []):
        if g not in groups:
            err.append(f"order: нет группы {g}")
    seen = set()

    def ref(where, x):
        r = x.get("rule_ref")
        if r and not (r.startswith("distances_cm.") and r.split(".", 1)[1] in dist):
            err.append(f"{where}: rule_ref {r} нет в occupancy.json")

    for t in doc.get("templates", []):
        tid = t.get("id", "?")
        if tid in seen:
            err.append(f"{tid}: повтор id")
        seen.add(tid)
        if not t.get("purpose"):
            err.append(f"{tid}: нет purpose")
        tg = {}
        for g in t.get("groups", []):
            if g["id"] not in groups:
                err.append(f"{tid}: группа {g['id']} не описана в groups")
                continue
            for v in g.get("variants", []):
                if v not in (groups[g["id"]].get("variants") or {}):
                    err.append(f"{tid}: вариант {g['id']}.{v} не описан")
            tg[g["id"]] = g
        for sec in ("predicates", "relations"):
            for x in t.get(sec, []):
                if x.get("kind") not in KINDS[sec]:
                    err.append(f"{tid}: {sec} kind {x.get('kind')!r} неизвестен")
                ref(f"{tid}.{sec}", x)
        for a, x in (t.get("anchors") or {}).items():
            if x.get("type") not in KINDS["anchors"]:
                err.append(f"{tid}: anchor {a} type {x.get('type')!r} неизвестен")
        for i in t.get("invariants", []):
            if i not in KINDS["invariants"]:
                err.append(f"{tid}: invariant {i!r} неизвестен")
        req = {g for g, x in tg.items() if x.get("required")}
        ids = [lv.get("id") for lv in t.get("levels", [])]
        if not ids:
            err.append(f"{tid}: нет levels")
        for lv in t.get("levels", []):
            use = lv.get("use") or {}
            for g, v in use.items():
                if g not in tg:
                    err.append(f"{tid}.{lv['id']}: группа {g} не в шаблоне")
                elif v not in tg[g].get("variants", []):
                    err.append(f"{tid}.{lv['id']}: вариант {g}.{v} не в шаблоне")
            miss = req - set(use)
            if miss:
                err.append(f"{tid}.{lv['id']}: уровень без обязательной группы {sorted(miss)}")
        ns = t.get("next_step")
        if ns:
            if ns.get("kind") not in KINDS["next_step"]:
                err.append(f"{tid}: next_step kind {ns.get('kind')!r} неизвестен")
            if ns.get("before_level") and ns["before_level"] not in ids:
                err.append(f"{tid}: next_step.before_level {ns['before_level']} нет в levels")
        lw = t.get("label_without")
        if lw and lw.get("group") not in tg:
            err.append(f"{tid}: label_without.group {lw.get('group')} не в шаблоне")
    return err


def purpose_key(purpose: str | None, child_age: str | None = None) -> str:
    return f"{purpose}:{child_age}" if purpose == "child" and child_age else (purpose or "")


def template_for(room_type: str, purpose: str | None, child_age: str | None = None) -> dict | None:
    """Шаблон назначения (меньший priority — раньше); детская — сперва `child:<возраст>`, потом `child`."""
    doc = load(room_type)
    keys = [purpose_key(purpose, child_age), purpose or ""]
    for k in keys:
        got = sorted((t for t in doc.get("templates", []) if k in t.get("purpose", [])), key=lambda t: t.get("priority", 100))
        if got:
            return got[0]
    return None


def group_of(room_type: str, role_base: str) -> str | None:
    """Группа роли (роль — базовая, без «2» и псевдонимов) по паспорту комнаты; вне групп — None."""
    for g, spec in (load(room_type).get("groups") or {}).items():
        if role_base in spec.get("roles", ()):
            return g
    return None


def variants(tpl: dict, group: str) -> list[str]:
    return next((list(g.get("variants", [])) for g in tpl.get("groups", []) if g["id"] == group), [])


def level_of(tpl: dict, found: dict) -> tuple[int, str | None]:
    """Уровень состава: первый по порядку, чей `use` целиком есть в раскладке (лишние группы не мешают).
    found — {группа: вариант} фактической раскладки → (индекс, id); не подошёл ни один — (len(levels), None)."""
    for i, lv in enumerate(tpl.get("levels", [])):
        if all(found.get(g) == v for g, v in (lv.get("use") or {}).items()):
            return i, lv["id"]
    return len(tpl.get("levels", [])), None


def best_possible(tpl: dict, group: str, variant: str | None) -> int:
    """Лучший уровень, достижимый при данном варианте группы (уровни без этой группы — тоже) — для ранней остановки."""
    for i, lv in enumerate(tpl.get("levels", [])):
        use = lv.get("use") or {}
        if group not in use or use[group] == variant:
            return i
    return len(tpl.get("levels", []))


def level_index(tpl: dict, level_id: str | None) -> int | None:
    return next((i for i, lv in enumerate(tpl.get("levels", [])) if lv["id"] == level_id), None)
