#!/usr/bin/env python3
"""Класс материала мебели для рендера (render-materials-01, шаг 2, T-20261117-14).

ЗАЧЕМ. Все меши — один материал на весь предмет (Hunyuan3D). Чтобы рендер дал рогожке «ткань», дереву «дерево», стеклу «стекло»,
нужно знать, из чего товар. Это берётся из ДАННЫХ товара, без AI-оценки по фото: автоматически на тысячи товаров, с причиной и
уверенностью. Меш и цвет товара не меняются — класс только выбирает слой для рендера (шаги 3–4 плана).

ПОРЯДОК (правила — `data/flat3d/material-classes.json`, код их только исполняет):
    1. характеристики товара (`params`: «Материал обивки», «Материал фасада», «Материал столешницы» … — ключи по роли предмета);
    2. слова названия, с отрицаниями («под кожу» не кожа; цвет «Дуб» — не материал);
    3. роль предмета — запасной класс с низкой уверенностью.
Первая стадия, давшая класс, решает; расхождение стадий — `conflict`, уверенность ниже; `needsReview` — всё, что надо глазами.

Результат на каждый меш — `data/flat3d/material-class-assign.json`: класс, уверенность, стадия, причина (какое поле и значение),
запасные классы, части (ножки, ручки, плафон). ID товаров в код не попадают — только в этот файл-данные.

Запуск (из корня репо; `--input` — выгрузка названий и характеристик, см. `build --help`):
    python3 tools/assets/material_class.py build --input products.json --roles roles.json --names names.json [--report out.md]
    python3 tools/assets/material_class.py check     # правила целы и результат совпадает с правилами (CI)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
RULES_PATH = os.path.join(ROOT, "data", "flat3d", "material-classes.json")
ASSIGN_PATH = os.path.join(ROOT, "data", "flat3d", "material-class-assign.json")

# латинские буквы-двойники кириллических: в слове с кириллицей меняем («Cтекло» → «стекло»)
_LAT2CYR = str.maketrans({"c": "с", "a": "а", "e": "е", "o": "о", "p": "р", "x": "х", "y": "у", "k": "к", "m": "м", "h": "н", "t": "т", "b": "в"})
_CYR = re.compile(r"[а-яё]")


def norm(text: object) -> str:
    """Нижний регистр, ё→е, латинские двойники в кириллических словах → кириллица."""
    s = str(text or "").lower().replace("ё", "е")
    words = []
    for w in re.split(r"(\s+)", s):
        words.append(w.translate(_LAT2CYR) if _CYR.search(w) else w)
    return "".join(words)


def load_rules(path: str = RULES_PATH) -> dict:
    with open(path, encoding="utf-8") as f:
        rules = json.load(f)
    rules["_byId"] = {c["id"]: c for c in rules["classes"]}
    rules["_roleGroup"] = {r: g for g, spec in rules["groups"].items() for r in spec["roles"]}
    return rules


def rules_sha(path: str = RULES_PATH) -> str:
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()[:16]


def find_hits(text: str, patterns: list[dict]) -> list[tuple[int, int, str, str]]:
    """Классы, чьи слова есть в тексте: (позиция первого слова, номер правила, класс, найденный кусок). По одному на класс."""
    t = norm(text)
    out: dict[str, tuple[int, int, str, str]] = {}
    for idx, p in enumerate(patterns):
        if any(re.search(n, t) for n in p.get("not", [])):
            continue
        for rx in p["any"]:
            m = re.search(rx, t)
            if m and (p["class"] not in out or m.start() < out[p["class"]][0]):
                out[p["class"]] = (m.start(), idx, p["class"], m.group(0))
    return sorted(out.values())


def _matches_prefer(rules: dict, cls: str, prefer: list[str]) -> int:
    fam = rules["_byId"][cls]["family"]
    for i, want in enumerate(prefer):
        if want == cls or want == fam:
            return i
    return len(prefer)


def pick(rules: dict, hits: list[tuple[int, int, str, str]], prefer: list[str]) -> list[tuple[int, int, str, str]]:
    """Порядок кандидатов: общий «ткань» уступает названному виду ткани; затем предпочтения роли, затем порядок в тексте."""
    byid = rules["_byId"]
    specific = [h for h in hits if not byid[h[2]].get("generic")]
    textile_specific = any(byid[h[2]]["family"] == "textile" for h in specific)
    keep = [h for h in hits if not (byid[h[2]].get("generic") and textile_specific)]
    return sorted(keep, key=lambda h: (_matches_prefer(rules, h[2], prefer), h[0], h[1]))


def _param(params: dict, key: str) -> str | None:
    for k, v in params.items():
        if norm(k).strip() == norm(key).strip() and v not in (None, ""):
            return str(v)
    return None


def stage_params(rules: dict, role: str, params: dict) -> dict | None:
    group = rules["groups"].get(rules["_roleGroup"].get(role, ""))
    if not group or not params:
        return None
    conf = rules["confidence"]
    ignore = {norm(k).strip() for k in rules["ignore_keys"]}
    prefer = group["prefer"]
    generic: dict | None = None
    for key in group["keys"]:
        if norm(key).strip() in ignore:
            continue
        val = _param(params, key)
        if val is None:
            continue
        ordered = pick(rules, find_hits(val, rules["value_patterns"]), prefer)
        if not ordered:
            continue
        top = ordered[0]
        is_generic = rules["_byId"][top[2]].get("generic", False)
        cand = {"class": top[2], "key": key, "value": val, "alt": [h[2] for h in ordered[1:]],
                "confidence": conf["params_generic"] if is_generic else (conf["params_single"] if len(ordered) == 1 else conf["params_multi"])}
        if not is_generic:
            # общее «ткань» уже найдено в обивке: каркас и прочие ключи его не перебивают — берём только названный вид из предпочтительных
            if generic is None or _matches_prefer(rules, cand["class"], prefer) < len(prefer):
                return cand
            continue
        generic = generic or cand
        if not prefer:
            return cand
    return generic


def stage_name(rules: dict, role: str, name: str) -> dict | None:
    if not name:
        return None
    group = rules["groups"].get(rules["_roleGroup"].get(role, ""), {})
    ordered = pick(rules, find_hits(name, rules["name_patterns"]), group.get("prefer", []))
    if not ordered:
        return None
    top = ordered[0]
    return {"class": top[2], "word": top[3], "alt": [h[2] for h in ordered[1:]], "confidence": rules["confidence"]["name"]}


def stage_role(rules: dict, role: str) -> dict:
    d = rules["role_defaults"].get(role)
    conf = rules["confidence"]
    if not d:
        return {"class": "neutral", "reason": "роль не из списка правил", "confidence": conf["role_neutral"]}
    return {"class": d["class"], "reason": d["reason"],
            "confidence": conf["role_neutral"] if d["class"] == "neutral" else conf["role"]}


def stage_parts(rules: dict, role: str, params: dict) -> dict:
    group = rules["groups"].get(rules["_roleGroup"].get(role, ""))
    out: dict[str, dict] = {}
    if not group or not params:
        return out
    for part, keys in group.get("parts", {}).items():
        for key in keys:
            val = _param(params, key)
            if val is None:
                continue
            hits = pick(rules, find_hits(val, rules["value_patterns"]), [])
            if hits:
                out[part] = {"class": hits[0][2], "reason": f"{key}={val}"}
                break
    return out


def classify(rules: dict, rec: dict) -> dict:
    """Класс материала одного товара. rec: role, name (может быть пусто), params (может быть пусто)."""
    role = rec.get("role") or ""
    name = rec.get("name") or ""
    params = rec.get("params") or {}
    conf = rules["confidence"]
    byid = rules["_byId"]
    p = stage_params(rules, role, params)
    n = stage_name(rules, role, name)
    out: dict
    if p:
        out = {"class": p["class"], "stage": "params", "confidence": p["confidence"], "reason": f"{p['key']}={p['value']}"}
        if p["alt"]:
            out["alt"] = p["alt"]
        p_generic = byid[p["class"]].get("generic", False)
        if n and p_generic and byid[n["class"]]["family"] == "textile" and not byid[n["class"]].get("generic"):
            out = {"class": n["class"], "stage": "params+name", "confidence": conf["name"] + conf["agree_bonus"] * 4,
                   "reason": f"{p['key']}={p['value']}; название: «{n['word']}»"}
        elif n and n["class"] != p["class"] and not p_generic:
            out["conflict"] = {"name": n["class"], "word": n["word"]}
            out["confidence"] = round(out["confidence"] - conf["conflict_penalty"], 2)
        elif n and n["class"] == p["class"]:
            out["confidence"] = round(min(0.97, out["confidence"] + conf["agree_bonus"]), 2)
    elif n:
        out = {"class": n["class"], "stage": "name", "confidence": n["confidence"], "reason": f"слово названия «{n['word']}»"}
        if n["alt"]:
            out["alt"] = n["alt"]
    else:
        r = stage_role(rules, role)
        out = {"class": r["class"], "stage": "role", "confidence": r["confidence"], "reason": r["reason"]}
        if not name and not params:
            out["evidenceGap"] = "нет названия и характеристик в доступных данных"
        elif not params:
            out["evidenceGap"] = "нет характеристик, название материала не называет"
    parts = stage_parts(rules, role, params)
    if parts:
        out["parts"] = parts
    out["role"] = role
    out["needsReview"] = bool(out.get("conflict")) or out["confidence"] < conf["review_below"] or "evidenceGap" in out
    return out


def build(rules: dict, products: list[dict], roles: dict[str, str], names: dict[str, str]) -> dict:
    meshes: dict[str, dict] = {}
    for rec in sorted(products, key=lambda r: r["sid"]):
        sid = rec["sid"]
        row = {"role": roles.get(sid) or rec.get("role") or "", "name": rec.get("name") or names.get(sid) or "", "params": rec.get("params") or {}}
        res = classify(rules, row)
        res["named"] = bool(row["name"])
        res["hasParams"] = bool(row["params"])
        meshes[sid] = res
    return {"_about": "Собрано tools/assets/material_class.py build по data/flat3d/material-classes.json — руками не править.",
            "version": rules["version"], "rulesSha": rules_sha(), "meshes": meshes}


def report(assign: dict, rules: dict) -> str:
    byid = rules["_byId"]
    ms = assign["meshes"]
    lines = [f"# Классы материала — охват {len(ms)} мешей (правила `{assign['rulesSha']}`)", ""]
    by_class: dict[str, list[str]] = {}
    for sid, m in ms.items():
        by_class.setdefault(m["class"], []).append(sid)
    lines += ["| класс | всего | по характеристикам | по названию | по роли | на проверку |", "|---|---|---|---|---|---|"]
    for cid in [c["id"] for c in rules["classes"]]:
        sids = by_class.get(cid, [])
        if not sids:
            continue
        st = lambda k: sum(1 for s in sids if ms[s]["stage"].startswith(k))  # noqa: E731
        lines.append(f"| {byid[cid]['titleRu']} (`{cid}`) | {len(sids)} | {st('params')} | {st('name')} | {st('role')} | {sum(1 for s in sids if ms[s]['needsReview'])} |")
    stages = {k: sum(1 for m in ms.values() if m["stage"].startswith(k)) for k in ("params", "name", "role")}
    lines += ["", f"По стадиям: характеристики {stages['params']}, название {stages['name']}, роль {stages['role']}. "
              f"На проверку: {sum(1 for m in ms.values() if m['needsReview'])}.", ""]
    return "\n".join(lines)


def check() -> int:
    """CI: правила читаются, классы известны, регулярки компилируются, результат совпадает с правилами (rulesSha)."""
    rules = load_rules()
    ids = set(rules["_byId"])
    problems: list[str] = []
    for section in ("value_patterns", "name_patterns"):
        for p in rules[section]:
            if p["class"] not in ids:
                problems.append(f"{section}: класс {p['class']} не описан")
            for rx in p["any"] + p.get("not", []):
                try:
                    re.compile(rx)
                except re.error as e:
                    problems.append(f"{section}: регулярка {rx!r}: {e}")
    for r, d in rules["role_defaults"].items():
        if d["class"] not in ids:
            problems.append(f"role_defaults[{r}]: класс {d['class']} не описан")
    if os.path.exists(ASSIGN_PATH):
        with open(ASSIGN_PATH, encoding="utf-8") as f:
            a = json.load(f)
        if a.get("rulesSha") != rules_sha():
            problems.append(f"material-class-assign.json собран по другим правилам ({a.get('rulesSha')} ≠ {rules_sha()}) — пересобрать `build`")
        for sid, m in a["meshes"].items():
            if m["class"] not in ids:
                problems.append(f"{sid}: класс {m['class']} не описан")
    for p in problems:
        print("ОШИБКА:", p)
    print("material_class check:", "ок" if not problems else f"{len(problems)} замечаний")
    return 1 if problems else 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="собрать data/flat3d/material-class-assign.json")
    b.add_argument("--input", required=True, help="JSON-список {sid, name, role, params} из каталога (дев-БД `products`)")
    b.add_argument("--roles", help="JSON {sid: роль} — роль меша из манифеста генерации (главнее роли каталога)")
    b.add_argument("--names", help="JSON {sid: название} — названия из других источников (витрина, конфигуратор) для товаров не из БД")
    b.add_argument("--ids", help="файл со списком sid (по строке) — набор мешей; нет — все из --input")
    b.add_argument("--report", help="путь для отчёта (markdown)")
    b.add_argument("--out", default=ASSIGN_PATH)
    sub.add_parser("check", help="проверка правил и результата (CI)")
    a = ap.parse_args(argv)
    if a.cmd == "check":
        return check()
    rules = load_rules()
    with open(a.input, encoding="utf-8") as f:
        products = json.load(f)
    roles = json.load(open(a.roles, encoding="utf-8")) if a.roles else {}
    names = json.load(open(a.names, encoding="utf-8")) if a.names else {}
    if a.ids:
        want = [s.strip() for s in open(a.ids, encoding="utf-8") if s.strip()[:1].isdigit()]
        have = {r["sid"] for r in products}
        products += [{"sid": s} for s in want if s not in have]
        products = [r for r in products if r["sid"] in set(want)]
    assign = build(rules, products, roles, names)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(assign, f, ensure_ascii=False, indent=1, sort_keys=True)
        f.write("\n")
    rep = report(assign, rules)
    if a.report:
        with open(a.report, "w", encoding="utf-8") as f:
            f.write(rep)
    print(rep)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
