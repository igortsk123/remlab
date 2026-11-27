#!/usr/bin/env python3
"""Этап 08 «материал» пути покраски (paint-photo-fill-01, T-20261121-170/1): у каждой части модели — свой PBR-рецепт по классу материала.

ЗАЧЕМ. Блеск, металл, ворс (sheen) и прозрачность НЕ берутся из RGB фото — на фото это свет съёмки (план, шаг 6). Они зависят от того, из чего часть:
ткань матовая с ворсом, ножки металлические, плафон стеклянный. ЦВЕТ этап не меняет: он один общий лист из фото и заливки (этапы 6–7); отдельных
слотов материала до покраски нет (T-161: белые ножки) — рецепт ложится маской частей по ОБЩЕМУ листу UV и запекается в общие карты GLB.

КАК. 1) класс товара — `material_class.classify` (характеристики → слова названия → роль), ничего не угадываем по фото;
2) части — `<run>/<sku>/03-parts/parts.npz` (этап 3: SAM2 + голосование на грани); нет этапа 3 — геометрия `material_parts` (ножки / тело);
3) грань без части этапа 3 — класс ближайшей грани с частью (inherited_share в check.json, предел в рецептах); нет этапа 3 — части по ФОРМЕ (`part_shapes.py`: стойка, корпус, плафон наверху; материал из каталога);
4) класс части: метка Qwen3-VL (`vl`, когда будет) → ножки с классом из каталога → главная часть = класс товара → часть без метки с цветом как у главной → иначе «не уверен»
(запасной рецепт neutral, причина в check.json); 5) рецепт класса (`data/flat3d/material-recipes.json`) растеризуется в UV общего листа →
карты metallicRoughness / sheenColor / transmission → GLB (`KHR_materials_sheen`, `KHR_materials_transmission`); карта цвета и геометрия — байт в байт как были.

Выход `<run>/<sku>/08-material/`: material.glb, check.json (общий формат `paint_stage.py`: доля граней с рецептом, доля уверенных, класс по частям с источником), frame.png (перёд, студийный свет).
Перевыпуск: этап 08 пересоздаёт material.glb целиком; руками файл не правится. ID товаров в код не попадают — только в данные запуска.

Запуск (venv ~/venvs/scout; кадр — Blender, тяжёлое — под heavy-slot):
    ~/venvs/scout/bin/python tools/assets/material_stage.py stage --glb model.glb --run RUN --sku SKU --product product.json [--parts-dir RUN/SKU/03-parts] [--no-frame]
    ~/venvs/scout/bin/python tools/assets/material_stage.py run --items items.json --run RUN
    ~/venvs/scout/bin/python tools/assets/material_stage.py check      # рецепты целы: все классы, диапазоны (CI)
`product.json`: {sid, name, role, params} как у `material_class.py build`; `items.json`: [{sku, glb, product, parts_dir?}].
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import struct
import subprocess
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
RECIPES_PATH = os.path.join(ROOT, "data", "flat3d", "material-recipes.json")
STAGE = "08-material"
STAGE_MARK_KEY = "remlab_stage"      # отметка «прошёл этап 08» в asset.extras GLB; её читает runtime_mesh (rules/rt-weight.json:material.stage_mark — те же key и value)
BLENDER = os.environ.get("BLENDER", os.path.expanduser("~/opt/blender-4.5.9/blender"))
FRAME_SCRIPT = os.path.join(HERE, "material_frame_blender.py")
PROPS = ("roughness", "metallic", "sheen", "transmission")


def _siblings():
    sys.path.insert(0, HERE)
    import material_class as mc
    import material_parts as mp
    return mc, mp


def _plate_guard(mesh) -> tuple[dict, dict]:
    """Сторож «плита осталась» (T-20261124-07; plate_strip.plate_left, пороги tools/scout/rules/plate-strip.json:left_check) → (отчёт, мерки check.json).
    Лист-подложка TRELLIS, дошедший до 08, на карте глянца — чёрное зеркало шире товара: этап не проходит (мерка plate_left ≤ 0), чинится срезом на 01/02 (plate_strip.py strip)."""
    sd = os.path.join(ROOT, "tools", "scout")
    if sd not in sys.path:
        sys.path.insert(0, sd)
    import plate_strip as P
    rep = P.plate_left(np.asarray(mesh.vertices), np.asarray(mesh.faces))
    return rep, P.left_metrics(rep)


def _paint_stage():
    """Общий модуль check.json этапов: в main (tools/scout) или рядом по пути worktree/окружению (пока ветка paint-fill не влита)."""
    cands = [os.path.join(ROOT, "tools", "scout"), os.environ.get("PAINT_STAGE_DIR", ""),
             os.path.join(os.path.expanduser("~"), "igor", "remlab", ".claude", "worktrees", "paint-fill-1120", "tools", "scout")]
    for d in cands:
        if d and os.path.exists(os.path.join(d, "paint_stage.py")):
            sys.path.insert(0, d)
            import paint_stage
            return paint_stage
    raise SystemExit("нет paint_stage.py: tools/scout или PAINT_STAGE_DIR")


# ───────────────────────────── правила ─────────────────────────────

def load_recipes(path: str = RECIPES_PATH) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def recipes_sha(path: str = RECIPES_PATH) -> str:
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()[:16]


# ───────────────────────── класс части ─────────────────────────

def _de76(a, b) -> float:
    return float(np.linalg.norm(np.asarray(a, dtype=float) - np.asarray(b, dtype=float)))


def _vl_class(label, recipes: dict):
    if not label:
        return None
    t = str(label).lower().replace("ё", "е")
    for word, cls in recipes["vl_labels"].items():
        if word in t:
            return cls
    return None


def resolve_parts(parts: list[dict], cls: dict, recipes: dict, parts_known: bool = True) -> dict[int, dict]:
    """Класс каждой части: {id: {class, source, confidence, reason, confident}}. `parts` — как в parts.json (id, face_share, role, vl, colour.lab_median);
    `cls` — результат `material_class.classify` товара (class, stage, confidence, reason, parts{legs,shade,handles…}).
    Метка Qwen → ножки с классом каталога → главная часть → цвет как у главной → «не уверен». Не угадываем: нет данных — запасной рецепт и низкая уверенность."""
    conf, cl = recipes["confidence"], recipes["classify"]
    fb = recipes["fallback_class"]
    cat = cls.get("parts") or {}
    has_shade = "shade" in cat
    pool = [p for p in parts if not (has_shade and str(p.get("role", "")) == "shape:blob-top")] or parts   # верхняя зона с плафоном в каталоге — не «главная часть», даже если самая большая
    main = max(pool, key=lambda p: p["face_share"])
    main_lab = ((main.get("colour") or {}).get("lab_median"))
    out: dict[int, dict] = {}
    for p in parts:
        vl = _vl_class(p.get("vl"), recipes)
        lab = (p.get("colour") or {}).get("lab_median")
        if vl:
            r = {"class": vl, "source": "vl", "confidence": conf["vl"], "reason": f"метка части «{p['vl']}»"}
        elif p.get("role") == "legs" and "legs" in cat:
            inferred = bool(cat["legs"].get("inferred"))      # своего поля «материал ножек» нет — класс по каркасу/основному материалу (дерево, металл)
            r = {"class": cat["legs"]["class"], "source": "catalog:legs-inferred" if inferred else "catalog:legs",
                 "confidence": conf["legs_catalog_inferred"] if inferred else conf["legs_catalog"],
                 "reason": f"ножки по геометрии; каталог{' (по каркасу, своего поля нет)' if inferred else ''}: {cat['legs']['reason']}"}
        elif p is not main and _role_class(p, cls, cat, recipes) is not None:
            r = _role_class(p, cls, cat, recipes)
        elif str(p.get("role", "")).startswith("shape:") and p is not main:
            r = _shape_class(p, cls, cat, recipes)
        elif p is main:
            r = {"class": cls["class"], "source": "catalog:" + cls["stage"], "confidence": round(cls["confidence"] * conf["main_part_scale"], 2), "reason": cls["reason"]}
            lost = [k for k, v in cat.items() if k not in ("legs", "frame") and v["class"] != cls["class"]]
            if not parts_known and lost:      # в каталоге есть плафон/ручки другого материала, а где они — без частей этапа 3 неизвестно
                r["confidence"] = min(r["confidence"], conf["no_parts_conflict"])
                r["reason"] += "; в каталоге есть " + ", ".join(f"{k} ({cat[k]['class']})" for k in lost) + ", частей этапа 3 нет — где они, не знаем"
        elif cls.get("group") in cl.get("body_inherit_groups", []) and not str(p.get("role", "")).startswith("shape:"):
            de = f" (ΔE {_de76(lab, main_lab):.1f})" if lab is not None and main_lab is not None else ""
            r = {"class": cls["class"], "source": "body-soft", "confidence": conf["body_inherit"],
                 "reason": f"мягкая мебель: часть корпуса — та же обивка по каталогу, цвет роли не решает{de}"}
        elif main_lab is not None and lab is not None and _de76(lab, main_lab) <= cl["same_material_dE"]:
            r = {"class": cls["class"], "source": "colour≈main", "confidence": conf["same_colour_as_main"],
                 "reason": f"цвет как у главной части (ΔE {_de76(lab, main_lab):.1f})"}
        else:
            why = "нет цвета части" if lab is None else f"цвет отличается от главной части (ΔE {_de76(lab, main_lab):.1f})" if main_lab is not None else "нет цвета главной части"
            r = {"class": fb, "source": "unsure", "confidence": conf["unsure"], "reason": f"нет метки, {why}", "main_id": int(main["id"]),
                 "de_main": round(float(_de76(lab, main_lab)), 1) if lab is not None and main_lab is not None else None}
        r = _compound_part(p, r, cls, recipes)
        _painted_metal(p, r, recipes)
        _gloss_finish(r, cls, recipes)
        _carry_tone(r, cls, cat)
        r["confident"] = bool(r["confidence"] >= cl["confident_from"])
        out[int(p["id"])] = r
    return out


def compound_of(rules: dict, cls: dict, recipes: dict) -> list[dict]:
    """Составное поле материала («Металл, Хрусталь»): список классов поля [{class, family}], если он из характеристик, в нём ≥ 2 семейств и среди них есть из `compound.families`.
    Иначе пусто. Список берётся из класса товара и его запасных классов (`alt`) — те же слова поля, что нашёл `material_class`."""
    cd = recipes.get("compound")
    if not cd or not str(cls.get("stage", "")).startswith("params"):
        return []
    ids = list(dict.fromkeys([cls["class"]] + list(cls.get("alt") or [])))
    ids = [c for c in ids if c in rules["_byId"] and not rules["_byId"][c].get("generic")]
    fams = {rules["_byId"][c]["family"] for c in ids}
    if len(fams) < 2 or not (fams & set(cd["families"])):
        return []
    return [{"class": c, "family": rules["_byId"][c]["family"]} for c in ids]


def _lab_chroma(lab) -> float:
    return float(np.hypot(lab[1], lab[2]))


def _compound_part(p: dict, r: dict, cls: dict, recipes: dict) -> dict:
    """Часть, чей класс — класс всего товара по составному полю («Металл, Хрусталь»), получает один материал из списка по форме и цвету (`compound`); не отнести уверенно — `unknown`.
    Ножки каталога, роли этапа 3 с каналом и метки Qwen не трогаем: у них свой источник класса."""
    cand = cls.get("compound") or []
    cd = recipes.get("compound")
    src = str(r.get("source", ""))
    if not cand or not cd or (r["class"] != cls["class"] and src != "unsure") or src == "vl" or (src.startswith(("catalog:legs", "role:")) and src != "role:main"):
        return r
    lab = (p.get("colour") or {}).get("lab_median")
    thin = p.get("role") in cd["thin_roles"]
    metals = [c["class"] for c in cand if c["family"] == "metal"]
    glasses = [c["class"] for c in cand if c["family"] == "glass"]
    rest = [c["class"] for c in cand if c["family"] not in ("metal", "glass")]
    cc = cd["confidence"]
    new = None
    if thin and metals:
        new = (metals[0], "compound:shape", cc["shape"], "тонкая часть по форме — металл из списка")
    elif not thin and glasses and lab is not None and lab[0] >= cd["glass_L_min"] and _lab_chroma(lab) <= cd["glass_C_max"]:
        new = (glasses[0], "compound:colour", cc["colour"], f"светлая бесцветная часть (L {lab[0]:.0f}, C {_lab_chroma(lab):.0f}) — стекло из списка")
    elif not thin and len(rest) == 1:
        new = (rest[0], "compound:single", cc["single"], "не тонкая; в списке единственный не металл и не стекло")
    if new is None:
        why = "нет цвета части" if lab is None else f"форма и цвет не решают (L {lab[0]:.0f}, C {_lab_chroma(lab):.0f}{', тонкая' if thin else ''})"
        new = ("unknown", "compound:unknown", cc["unknown"], f"в поле несколько материалов, {why} — часть не трогаем")
    return {**r, "class": new[0], "source": new[1], "confidence": new[2], "reason": f"{r['reason']}; поле составное ({', '.join(c['class'] for c in cand)}): {new[3]}", "compound": [c["class"] for c in cand]}


def _painted_metal(p: dict, r: dict, recipes: dict) -> None:
    """Металл с цветом по листу 07 не «хромовым» — крашеный (`painted_metal`): рецепт без зеркального блеска, цвет 07 тот же. Нет цвета части — остаётся металл."""
    pm = recipes.get("painted_metal")
    if not pm or r["class"] not in pm["from"]:
        return
    col = p.get("colour") or {}
    lab = col.get("lab_median")
    if not lab:
        return
    chroma = _lab_chroma(lab)
    spread = col.get("L_spread")
    saturated = chroma >= pm["chroma_min"]
    light_matte = lab[0] >= pm["light_L_min"] and spread is not None and spread <= pm["light_spread_max"]
    if saturated or light_matte:
        why = f"насыщенный тон (C {chroma:.0f} ≥ {pm['chroma_min']})" if saturated else f"светлый матовый (L {lab[0]:.0f}, разброс {spread} ≤ {pm['light_spread_max']})"
        r["painted_from"] = r["class"]
        r["class"] = pm["class"]
        r["reason"] += f"; крашеный металл: {why}"


RULE_GLOSS = "R-GLOSS-08"


def _rule_record():
    """`tools/scout/rule_record.py` (запись «правило применено / воздержалось» в extra.rules[]) — рядом с paint_stage; в срезе Salad он есть (stage_files.txt)."""
    _paint_stage()
    import rule_record
    return rule_record


def gloss_rule_entry(role: str | None, cls: dict, res: dict, recipes: dict) -> dict:
    """Запись правила R-GLOSS-08 для `08-material/check.json: extra.rules[]` (формат `rule_record.entry`; тип и digest — из паспорта по роли каталога).
    Применено — у товара есть часть класса из `gloss_finish.class_map` (щит, дерево): правило решило, матовая она или глянцевая (слово из `words` — глянец, иначе матовая по рецепту).
    Воздержание с причиной — нет таких частей (ткань, металл, стекло, кожа) или в рецептах нет `gloss_finish`; нет типа в паспортах — `no_type` (в `entry`)."""
    rr = _rule_record()
    gf = recipes.get("gloss_finish")
    if not gf:
        return rr.entry(RULE_GLOSS, role, False, "в рецептах нет gloss_finish")
    cm = gf.get("class_map") or {}
    touched = [r for r in res.values() if r.get("gloss_from") or r.get("class") in cm]
    if not touched:
        return rr.entry(RULE_GLOSS, role, False, "нет частей класса щита/дерева (class_map) — нечего решать про глянец")
    g = cls.get("gloss")
    return rr.entry(RULE_GLOSS, role, True, ("глянец: «%s» в %s" % (g["word"], g["where"])) if g else "матовый по рецепту: слов глянца нет")


def gloss_of(product: dict, recipes: dict) -> dict | None:
    """Товар назван глянцевым/лакированным? (`gloss_finish`: слова в названии или значениях характеристик, без слов матовости). → {word, where} или None."""
    gf = recipes.get("gloss_finish")
    if not gf:
        return None
    mc, _ = _siblings()
    fields = [("название", product.get("name"))] + [(f"«{k}»", v) for k, v in (product.get("params") or {}).items()]
    for where, val in fields:
        t = mc.norm(val)
        if not t or any(re.search(rx, t) for rx in gf["not_words"]):
            continue
        for rx in gf["words"]:
            m = re.search(rx, t)
            if m:
                return {"word": m.group(0), "where": where}
    return None


def _gloss_finish(r: dict, cls: dict, recipes: dict) -> None:
    """Глянцевый товар (`cls['gloss']`): часть щита/дерева (`class_map`) берёт рецепт глянца; без слова глянца щит и дерево остаются матовыми по своему рецепту."""
    gf, g = recipes.get("gloss_finish"), cls.get("gloss")
    if not gf or not g or r["class"] not in gf["class_map"]:
        return
    r["gloss_from"] = r["class"]
    r["class"] = gf["class_map"][r["class"]]
    r["reason"] += f"; глянец/лак: «{g['word']}» в {g['where']}"


def _carry_tone(r: dict, cls: dict, cat: dict) -> None:
    """Тон стекла (`glass_finish` классов материала) переходит на часть из ТОГО места каталога, откуда взят её класс: ножки → `legs`, плафон → `shade`, остальное → товар."""
    src = r.get("source", "")
    if src.startswith("catalog:legs"):
        ent = cat.get("legs")
    elif src.startswith("role:"):
        ent = cls if src == "role:main" else cat.get(src[5:])
    elif src == "geometry:top":
        ent = cat.get("shade")
    elif src == "geometry:linear":
        ent = cat.get("frame")
    elif src == "geometry:small":
        ent = cat.get("handles")
    elif src in ("geometry:body", "body-soft", "colour≈main") or src.startswith("catalog:"):
        ent = cls
    else:
        ent = None
    if ent and ent.get("tone") and ent.get("class") == r["class"]:
        r["tone"] = list(ent["tone"])
        if ent.get("tone_source"):
            r["tone_source"] = ent["tone_source"]


def unsure_parts_report(mesh, part: np.ndarray, parts_rep: list[dict], parts: list[dict], recipes: dict) -> list[dict]:
    """Для каждой неуверенной части — всё, по чему её можно назвать (вход этапу 3/р.1 для подписи ролей): доля граней и площади, ΔE к главной, цвет Lab,
    где она (по центроиду: высота верх/середина/низ в долях высоты модели, боковое смещение от оси: центр/сбоку/край в долях полуширины; ось Y вверх)."""
    rep = recipes["unsure_report"]
    v = np.asarray(mesh.vertices, dtype=np.float64)
    f = np.asarray(mesh.faces)
    tri = v[f]
    cen = tri.mean(axis=1)
    area = 0.5 * np.linalg.norm(np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]), axis=1)
    lo, hi = float(v[:, 1].min()), float(v[:, 1].max())
    mid = (v.min(axis=0) + v.max(axis=0)) / 2
    half = np.maximum((v.max(axis=0) - v.min(axis=0)) / 2, 1e-9)
    col = {int(p["id"]): (p.get("colour") or {}).get("lab_median") for p in parts}
    out = []
    for r in parts_rep:
        if r["confident"]:
            continue
        sel = part == r["id"]
        if not sel.any():
            continue
        c = np.average(cen[sel], axis=0, weights=np.maximum(area[sel], 1e-12))
        up = float((c[1] - lo) / max(hi - lo, 1e-9))
        off = float(max(abs(c[0] - mid[0]) / half[0], abs(c[2] - mid[2]) / half[2]))
        vert = "верх" if up >= rep["up_top"] else "низ" if up <= rep["up_bottom"] else "середина"
        side = "центр" if off <= rep["off_centre"] else "край" if off >= rep["off_edge"] else "сбоку"
        lab = col.get(int(r["id"]))
        out.append({"id": int(r["id"]), "role": r["role"], "face_share": round(float(sel.mean()), 4), "area_share": round(float(area[sel].sum() / max(area.sum(), 1e-12)), 4),
                    "de_main": r.get("de_main"), "main_id": r.get("main_id"), "lab": [round(float(x), 1) for x in lab] if lab else None,
                    "where": {"up": round(up, 2), "off": round(off, 2), "label": f"{vert}, {side}"}, "reason": r["reason"]})
    return sorted(out, key=lambda d: -d["area_share"])


def ensure_roles(parts: list[dict]) -> int:
    """Части этапа 3 без поля `role` (parts.json от PartLLM при выключенном мосте ролей `part-llm-roles.json`, mode=dry) — не падение (было KeyError 'role', T-99/7 26.11):
    общее правило «нет роли → role='unknown', канала нет» — дальше те же ветки, что у unknown (ножки/верх добираются геометрией, остальное — прежняя политика). → число частей, которым роль не дана
    (идёт в check.json `extra.parts_without_role`, чтобы переход на геометрию был виден в отчёте прогона)."""
    n = 0
    for p in parts:
        if "role" not in p or p["role"] in (None, ""):
            p["role"] = "unknown"
            p.setdefault("material_channel", None)
            n += 1
    return n


def merge_roles(parts: list[dict], path: str) -> int:
    """Роли частей этапа 3 лежат отдельным файлом `roles.json` (пересчёт ролей без пересчёта частей): {id части: {role, material_channel, …}}. Части, у которых роль
    с каналом уже в parts.json, не трогаем; остальным дописываем role/material_channel/role_conf/unknown_reason. → сколько частей получило роль. Нет файла — 0."""
    if not os.path.exists(path):
        return 0
    roles = json.load(open(path, encoding="utf-8"))
    n = 0
    for p in parts:
        r = roles.get(str(p["id"]))
        if not r or (p.get("material_channel") and p.get("role") not in (None, "unknown")):
            continue
        for k in ("role", "material_channel", "role_conf", "unknown_reason"):
            if k in r:
                p[k] = r[k]
        n += 1
    return n


def _role_class(p: dict, cls: dict, cat: dict, recipes: dict) -> dict | None:
    """Роль части от этапа 3 (`parts.json` → `role`, `material_channel`; правила — `part-roles.json`): канал материала `main` (body/top/facade) — основной класс товара
    (у стола — каталожный материал столешницы); канал legs/frame/handles/shade — материал этого канала в каталоге. Канала нет в каталоге, роль unknown/glass_mirror/прочее —
    None (дальше прежняя политика: форма, цвет, «не уверен»). Название роли и каналы — в JSON `roles` (рецепты), не здесь."""
    rl = recipes["roles"]
    role, ch = p.get("role"), p.get("material_channel")
    if role not in rl["known"] or not ch:
        return None
    sc = rl["confidence"]
    if ch == "main":
        return {"class": cls["class"], "source": "role:main", "confidence": sc["main"], "reason": f"роль «{role}» этапа 3 — основной материал товара: {cls['reason']}"}
    if ch in cat and ch in rl["channels"]:
        return {"class": cat[ch]["class"], "source": f"role:{ch}", "confidence": sc["channel"], "reason": f"роль «{role}» этапа 3 — канал «{ch}» каталога: {cat[ch]['reason']}"}
    return None


def _shape_class(p: dict, cls: dict, cat: dict, recipes: dict) -> dict:
    """Часть без этапа 3, выделенная по форме: материал берём из каталога, форма говорит, какой именно (`geometry` в material-recipes.json)."""
    g = recipes["geometry"]
    gc = g["confidence"]
    kind = p["role"].split(":", 1)[1]
    present = {cls["class"]} | {v["class"] for v in cat.values()}
    if kind == "linear":
        if "frame" in cat:
            return {"class": cat["frame"]["class"], "source": "geometry:linear", "confidence": gc["linear"], "reason": f"тонкая стойка по форме; каталог: {cat['frame']['reason']}"}
        if "metal" in present:
            return {"class": "metal", "source": "geometry:linear", "confidence": gc["linear"], "reason": "тонкая стойка по форме; в каталоге есть металл"}
    if kind == "blob-top" and "shade" in cat:
        return {"class": cat["shade"]["class"], "source": "geometry:top", "confidence": gc["blob_top"], "reason": f"объёмная часть наверху по форме; каталог: {cat['shade']['reason']}"}
    if kind == "blob" and "handles" in cat and p["face_share"] <= g["handles_max_share"]:
        return {"class": cat["handles"]["class"], "source": "geometry:small", "confidence": gc["blob_handles"], "reason": f"мелкая часть по форме; каталог: {cat['handles']['reason']}"}
    return {"class": cls["class"], "source": "geometry:body", "confidence": gc["other_main"], "reason": f"часть формы «{kind}», другого материала для неё в каталоге нет — материал корпуса: {cls['reason']}"}


def stand_near_axis(mesh, key: np.ndarray, up: np.ndarray, g: dict, linear_kind: int) -> np.ndarray:
    """Маска граней верхней зоны (key 3), лежащих у оси единственной тонкой стойки (ближе `stand_k`·радиус стойки): стык стойки с цоколем лампы, крышка.
    Ось и радиус — по linear-граням ниже `top_from` (вертикаль — Y); стойка должна быть одна и тонкой (радиус ≤ `stand_max_radius_frac` габарита): ножки по углам или
    толстая ножка стола — не стойка, тогда маска пустая. Нет `stand_k` в JSON — правило выключено."""
    none = np.zeros(len(key), dtype=bool)
    sk = g.get("stand_k")
    nf = len(key)
    low = (key == 1) & (up < g["top_from"])
    if not sk or low.sum() < max(10, int(g["min_part_share"] * nf)):
        return none
    c = np.asarray(mesh.vertices)[np.asarray(mesh.faces)].mean(axis=1)
    xz = c[:, [0, 2]]
    ax = np.median(xz[low], axis=0)
    r = float(np.median(np.linalg.norm(xz[low] - ax, axis=1)))
    ll = float((c.max(axis=0) - c.min(axis=0)).max())
    spread = float(np.linalg.norm(xz[low] - ax, axis=1).max())
    if r <= 0 or r > g["stand_max_radius_frac"] * ll or spread > g["stand_max_radius_frac"] * ll * 3:
        return none
    return (key == 3) & (np.linalg.norm(xz - ax, axis=1) <= sk * r)


def geometry_shape_parts(mesh, mp, cat_parts: dict, recipes: dict) -> tuple[np.ndarray, list[dict], dict]:
    """Части без этапа 3 по форме: ножки (геометрия `material_parts`) + остальное делится на planar / linear / blob / blob-top (`part_shapes`); мелкие группы (< min_part_share)
    вливаются в крупнейшую. → (part на грань, parts как в parts.json, отчёт формы)."""
    import part_shapes as psh
    g = recipes["geometry"]
    legs = legs_by_geometry(mesh, mp, cat_parts)
    kind, up, rep = psh.face_shapes(mesh.vertices, mesh.faces, g)
    nf = len(mesh.faces)
    # 0 planar, 1 linear, 2 blob, 3 top. Верхняя зона: всё, что не тонкая стойка, — «верх» (плафон; шар крупнее радиуса на вид «плоский» и дробился на пятна)
    key = np.where(kind == psh.LINEAR, 1, np.where(up >= g["top_from"], 3, np.where(kind == psh.BLOB, 2, 0)))
    names = {0: "planar", 1: "linear", 2: "blob", 3: "blob-top"}   # blob-top: классом плафона станет материал каталога (стекло, ткань…), не «стекло» вообще
    stand = stand_near_axis(mesh, key, up, g, psh.LINEAR)             # стык стойки с цоколем лампы в верхней зоне — стойка, не плафон
    key[stand] = 1
    key = np.where(legs, -1, key)
    shares = {k: float((key == k).sum()) / nf for k in (0, 1, 2, 3)}
    big = max(shares, key=shares.get)
    for k in (0, 1, 2, 3):
        if 0 < shares[k] < g["min_part_share"]:
            key[key == k] = big
    part = np.full(nf, -1, dtype=np.int16)
    parts = []
    pid = 0
    for k in (-1, 0, 1, 2, 3):
        sel = key == k
        if not sel.any():
            continue
        part[sel] = pid
        parts.append({"id": pid, "face_share": round(float(sel.mean()), 4), "role": "legs" if k == -1 else f"shape:{names[k]}", "vl": None, "colour": None})
        pid += 1
    return part, parts, rep


def horizontal_shares(mesh, part: np.ndarray, ids: list[int], recipes: dict) -> dict[int, float]:
    """Доля ПЛОЩАДИ горизонтальных граней у каждой части (|нормаль·вверх| ≥ `flat_top.min_cos`, вверх — Y): у столешницы высокая, у шара, стойки, дверцы низкая. Для `flat_top` (шероховатость широкой плоскости)."""
    v = np.asarray(mesh.vertices, dtype=np.float64)
    tri = v[np.asarray(mesh.faces)]
    cr = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    area = np.linalg.norm(cr, axis=1)
    horiz = np.abs(cr[:, 1]) >= recipes["flat_top"]["min_cos"] * np.maximum(area, 1e-18)
    return {int(pid): round(float(area[(part == pid) & horiz].sum() / max(area[part == pid].sum(), 1e-18)), 3) for pid in ids if (part == pid).any()}


def legs_by_geometry(mesh, mp, cat_parts: dict) -> np.ndarray:
    """Маска граней ножек по геометрии `material_parts` (split и уверенность ≥ порога); нет ножек — все False."""
    mpr = mp.load_rules()
    rec = mp.judge(mp.analyze(mesh, mpr), mpr, True if "legs" in cat_parts else None)
    if rec.get("apply") and rec["status"] == "split":
        return mp.legs_face_mask(mesh, rec)
    return np.zeros(len(mesh.faces), dtype=bool)


def geometry_parts(mesh, mp, cat_parts: dict) -> tuple[np.ndarray, list[dict]]:
    """Части без этапа 3: ножки по геометрии (id 1, role legs) и всё остальное (id 0)."""
    nf = len(mesh.faces)
    part = np.zeros(nf, dtype=np.int16)
    part[legs_by_geometry(mesh, mp, cat_parts)] = 1
    parts = []
    for pid in np.unique(part):
        parts.append({"id": int(pid), "face_share": round(float((part == pid).sum()) / nf, 4), "role": "legs" if pid == 1 else f"part-{int(pid)}", "vl": None, "colour": None})
    return part, parts


def mark_legs(parts: list[dict], part: np.ndarray, legs: np.ndarray, share_min: float) -> None:
    """Часть этапа 3, которая на ≥ `share_min` лежит на ножках по геометрии, получает роль legs (главная часть — никогда)."""
    main = max(parts, key=lambda p: p["face_share"])["id"]
    for p in parts:
        sel = part == p["id"]
        sh = float((legs & sel).sum()) / max(1, int(sel.sum()))
        p["legs_share"] = round(sh, 3)
        if p["id"] != main and p.get("role") != "legs" and sh >= share_min and not (p.get("material_channel") and p.get("role") != "unknown"):   # роль этапа 3 (с каналом) главнее геометрии
            p["role"] = "legs"


def inherit_unseen(mesh, part: np.ndarray, known_ids: list[int], max_points: int = 60000) -> tuple[np.ndarray, np.ndarray]:
    """Грань без части (−1 или номер, которого нет в parts.json) берёт часть ближайшей грани с частью (по центрам граней; пометка inherited).
    → (part с заполненными пропусками, маска унаследованных граней). Ни одной грани с частью — ValueError (нечего наследовать)."""
    part = np.asarray(part).copy()
    unseen = ~np.isin(part, known_ids)
    if not unseen.any():
        return part, unseen
    if unseen.all():
        raise ValueError("ни одной грани с частью: наследовать классу не от кого")
    from scipy.spatial import cKDTree
    c = np.asarray(mesh.vertices)[np.asarray(mesh.faces)].mean(axis=1)
    seen = np.flatnonzero(~unseen)
    if len(seen) > max_points:
        seen = seen[np.random.default_rng(0).choice(len(seen), size=max_points, replace=False)]
    _, nn = cKDTree(c[seen]).query(c[unseen], k=1)
    part[unseen] = part[seen[nn]]
    return part, unseen


def rgb_to_lab(rgb: np.ndarray) -> np.ndarray:
    """sRGB 0..255 (N×3) → CIE Lab (D65)."""
    c = rgb.astype(np.float64) / 255.0
    c = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    m = np.array([[0.4124564, 0.3575761, 0.1804375], [0.2126729, 0.7151522, 0.0721750], [0.0193339, 0.1191920, 0.9503041]])
    xyz = c @ m.T / np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 216 / 24389, np.cbrt(xyz), (24389 / 27 * xyz + 16) / 116)
    return np.stack([116 * f[:, 1] - 16, 500 * (f[:, 0] - f[:, 1]), 200 * (f[:, 1] - f[:, 2])], axis=1)


def part_colours(mesh, part: np.ndarray, min_faces: int = 30) -> dict[int, dict]:
    """Медиана Lab каждой части по листу цвета модели (текстура в центре граней; V вверх). Нет текстуры — пусто (часть без цвета — «не уверен»)."""
    mat = getattr(mesh.visual, "material", None)
    img = getattr(mat, "baseColorTexture", None) or getattr(mat, "image", None)
    uv = getattr(mesh.visual, "uv", None)
    if img is None or uv is None:
        return {}
    tex = np.asarray(img.convert("RGB"))
    h, w = tex.shape[:2]
    c = np.asarray(uv)[mesh.faces].mean(axis=1)
    x = np.clip((c[:, 0] * (w - 1)).round().astype(int), 0, w - 1)
    y = np.clip(((1 - c[:, 1]) * (h - 1)).round().astype(int), 0, h - 1)
    lab = rgb_to_lab(tex[y, x])
    out = {}
    for p in np.unique(part[part >= 0]):
        sel = part == p
        if int(sel.sum()) >= min_faces:
            out[int(p)] = {"lab_median": [round(float(v), 1) for v in np.median(lab[sel], axis=0)], "faces_sampled": int(sel.sum()),
                           "L_spread": round(float(np.percentile(lab[sel, 0], 90) - np.percentile(lab[sel, 0], 10)), 1)}      # разброс L: у хрома на листе блики — он большой
    return out


# ───────────────────────── запекание в UV ─────────────────────────

def class_table(recipes: dict, classes: list[str]) -> list[str]:
    """Номера классов в растре: 1..n (0 — пусто). Порядок — по первому появлению, детерминированно."""
    seen: list[str] = []
    for c in classes:
        if c not in seen:
            seen.append(c)
    for c in seen:
        if c not in recipes["recipes"]:
            raise KeyError(f"класс {c!r} без рецепта в material-recipes.json")
    return seen


def rasterize_labels(uv: np.ndarray, faces: np.ndarray, face_label: np.ndarray, size: int) -> np.ndarray:
    """Номер класса грани → UV-растр size². V вверх (как у trimesh после загрузки GLB): строка = (1 − v)·size. Пустое — ближайшим занятым (поля островов)."""
    from PIL import Image, ImageDraw
    from scipy import ndimage

    img = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(img)
    tri = uv[faces]
    xs = tri[:, :, 0] * size
    ys = (1.0 - tri[:, :, 1]) * size
    order = np.argsort(face_label, kind="stable")           # детерминированно: при перекрытии побеждает больший номер
    for i in order:
        d.polygon([(xs[i, 0], ys[i, 0]), (xs[i, 1], ys[i, 1]), (xs[i, 2], ys[i, 2])], fill=int(face_label[i]))
    lab = np.asarray(img)
    if (lab == 0).any() and (lab > 0).any():
        idx = ndimage.distance_transform_edt(lab == 0, return_distances=False, return_indices=True)
        lab = lab[idx[0], idx[1]]
    return lab


def tint_sheen(sheen: np.ndarray, albedo, st: dict) -> np.ndarray:
    """Цвет sheen = сила класса × цвет ткани (T-20261121-169, серость тёмного бархата): sheen_rgb = сила × lin(цвет) / max(макс.канал lin(цвет), floor), всё в линейном свете.
    Серый sheen поверх тёмного синего альбедо добавляет серый свет (L +12, хрома −3 у дивана Денди); ворс настоящего бархата окрашен цветом ткани. Нет альбедо или `on`=false — серый, как раньше.
    → (H×W×3 линейная сила 0..1)."""
    if albedo is None or not st.get("on"):
        return np.stack([sheen] * 3, axis=-1)
    from PIL import Image as _I
    a = albedo.convert("RGB") if hasattr(albedo, "convert") else albedo
    a = np.asarray(a.resize((sheen.shape[1], sheen.shape[0]), _I.BILINEAR), dtype=np.float64) / 255.0
    lin = np.power(a, 2.2)
    tint = lin / np.maximum(lin.max(axis=-1, keepdims=True), float(st["floor"]))
    return np.clip(sheen[..., None] * tint, 0.0, 1.0)


def bake_maps(lab: np.ndarray, table: list[str], recipes: dict, albedo=None, flat: np.ndarray | None = None) -> dict:
    """Растр классов → карты: metallicRoughness (G rough, B metal), sheenColor (сила sheen × цвет ткани, sRGB; серый — если `sheen_tint.on`=false или нет альбедо), transmission (R); скаляр sheenRoughness.
    `flat` (bool, как растр) — тексели широкой плоскости: шероховатость не ниже `flat_top.roughness_min`, кроме металла и прозрачного (T-20261123-14, блик на столешнице)."""
    lut = {p: np.zeros(256, dtype=np.float64) for p in PROPS}
    lut_sr = np.zeros(256, dtype=np.float64)
    for i, cid in enumerate(table, start=1):
        r = recipes["recipes"][cid]
        for p in PROPS:
            lut[p][i] = r[p]
        lut_sr[i] = r["sheenRoughness"]
    lut["roughness"][0] = recipes["recipes"][recipes["fallback_class"]]["roughness"]
    rough, metal, sheen, trans = (lut[p][lab] for p in PROPS)
    ft = recipes.get("flat_top")
    if flat is not None and ft:
        rough = np.where(flat & (metal <= ft["skip_metallic"]) & (trans <= ft["skip_transmission"]), np.maximum(rough, ft["roughness_min"]), rough)
    to8 = lambda a: np.clip(np.round(a * 255.0), 0, 255).astype(np.uint8)  # noqa: E731
    mr = np.stack([np.full(lab.shape, 255, np.uint8), to8(rough), to8(metal)], axis=-1)
    sheen_rgb = to8(np.power(tint_sheen(np.clip(sheen, 0, 1), albedo, recipes.get("sheen_tint") or {}), 1 / 2.2))
    trans_rgb = np.stack([to8(trans), np.zeros(lab.shape, np.uint8), np.zeros(lab.shape, np.uint8)], axis=-1)
    w = sheen.reshape(-1)
    sr = float((lut_sr[lab].reshape(-1) * w).sum() / w.sum()) if w.sum() > 0 else 0.5
    return {"mr": mr, "sheen": sheen_rgb, "trans": trans_rgb, "sheenRoughness": round(sr, 3),
            "hasSheen": bool(sheen.max() > 0.02), "hasTransmission": bool(trans.max() > 0.02)}


# ───────────────────────── GLB ─────────────────────────

def read_glb(path: str) -> tuple[dict, bytes]:
    with open(path, "rb") as f:
        data = f.read()
    magic, _ver, _total = struct.unpack_from("<III", data, 0)
    if magic != 0x46546C67:
        raise ValueError("не GLB")
    off, doc, binb = 12, None, b""
    while off + 8 <= len(data):
        ln, ct = struct.unpack_from("<II", data, off)
        body = data[off + 8: off + 8 + ln]
        if ct == 0x4E4F534A:
            doc = json.loads(body)
        elif ct == 0x004E4942:
            binb = body
        off += 8 + ln
    if doc is None:
        raise ValueError("нет JSON-чанка")
    return doc, binb


def write_glb(path: str, doc: dict, binb: bytes) -> None:
    js = json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    js += b" " * (-len(js) % 4)
    binb += b"\0" * (-len(binb) % 4)
    total = 12 + 8 + len(js) + 8 + len(binb)
    with open(path, "wb") as f:
        f.write(struct.pack("<III", 0x46546C67, 2, total))
        f.write(struct.pack("<II", len(js), 0x4E4F534A) + js)
        f.write(struct.pack("<II", len(binb), 0x004E4942) + binb)


def _png(arr: np.ndarray) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _view_bytes(doc: dict, binb: bytes, i: int) -> bytes:
    v = doc["bufferViews"][i]
    o = v.get("byteOffset", 0)
    return binb[o: o + v["byteLength"]]


def image_sha(path: str, which: str = "baseColor") -> str | None:
    """sha256 байтов картинки материала 0 (baseColor / metallicRoughness) — доказательство «цвет не тронут»."""
    doc, binb = read_glb(path)
    pbr = doc["materials"][0].get("pbrMetallicRoughness", {})
    ref = pbr.get("baseColorTexture" if which == "baseColor" else "metallicRoughnessTexture")
    if not ref:
        return None
    img = doc["images"][doc["textures"][ref["index"]]["source"]]
    return hashlib.sha256(_view_bytes(doc, binb, img["bufferView"])).hexdigest()


def geometry_sha(path: str) -> str:
    """sha256 буферов геометрии (атрибуты и индексы всех примитивов): форма и развёртка байт в байт."""
    doc, binb = read_glb(path)
    h = hashlib.sha256()
    for m in doc.get("meshes", []):
        for pr in m["primitives"]:
            ids = list(pr["attributes"].values()) + ([pr["indices"]] if "indices" in pr else [])
            for a in sorted(ids):
                acc = doc["accessors"][a]
                if "bufferView" in acc:
                    h.update(_view_bytes(doc, binb, acc["bufferView"]))
    return h.hexdigest()


# ───────────────────────── тон стекла ─────────────────────────

def photo_tone(photo: str, gt: dict) -> list[int] | None:
    """Медиана цвета предмета на фото (RGBA-вырезка) без верхних `highlight_trim` по L (блики) — тон цельного стекла. Вырезка чистая, если полупрозрачных пикселей
    (0 < альфа < alpha_min) не больше `semi_alpha_max` от предмета и непрозрачных не меньше min_pixels; нет файла / грязная вырезка — None."""
    from PIL import Image
    if not photo or not os.path.exists(photo):
        return None
    im = np.asarray(Image.open(photo).convert("RGBA"))
    a = im[..., 3]
    solid, semi = a >= gt["alpha_min"], (a > 10) & (a < gt["alpha_min"])
    if int(solid.sum()) < gt["min_pixels"] or semi.sum() > gt["semi_alpha_max"] * (solid.sum() + semi.sum()):
        return None
    px = im[solid][:, :3]
    L = rgb_to_lab(px.astype(np.float64))[:, 0]
    px = px[L <= np.quantile(L, 1.0 - gt["highlight_trim"])]
    if len(px) < gt["min_pixels"]:
        return None
    return [int(v) for v in np.median(px, axis=0)]


def reconcile_tone(cat_tone: list[int], photo_rgb: list[int] | None, gt: dict) -> dict:
    """Каталог называет цвет, фото (чистая вырезка, без бликов) решает: тон = фото. Расхождение ΔE76 > photo_max_dE не отменяет фото, а помечается
    `conflict = catalog:photo-conflict` (каталожные цвета бывают неточными: «бирюзовая» ваза на фото бледно-мятная). Нет фото / грязная вырезка — каталог."""
    if photo_rgb is None:
        return {"used": list(cat_tone), "source": "catalog", "catalogue": list(cat_tone), "photo": None, "dE": None, "conflict": None}
    de = float(np.linalg.norm(rgb_to_lab(np.array([cat_tone]))[0] - rgb_to_lab(np.array([photo_rgb]))[0]))
    return {"used": list(photo_rgb), "source": "photo", "catalogue": list(cat_tone), "photo": list(photo_rgb), "dE": round(de, 1),
            "conflict": "catalog:photo-conflict" if de > gt["photo_max_dE"] else None}


def _base_image(doc: dict, binb: bytes):
    from PIL import Image
    ref = doc["materials"][0].get("pbrMetallicRoughness", {}).get("baseColorTexture")
    if not ref:
        return None
    img = doc["images"][doc["textures"][ref["index"]]["source"]]
    return Image.open(io.BytesIO(_view_bytes(doc, binb, img["bufferView"]))).convert("RGBA")


def _raster_faces(uv: np.ndarray, faces: np.ndarray, idx: np.ndarray, size: tuple[int, int], fill=255, mode: str = "L"):
    """Растр граней UV (индексы `idx`) в картинку size: тот же метод заливки для всех наборов граней, чтобы «чужие» тексели совпадали с занятыми."""
    from PIL import Image, ImageDraw

    w, h = size
    im = Image.new(mode, (w, h), 0 if mode == "L" else (0, 0, 0))
    d = ImageDraw.Draw(im)
    for k in idx:
        t = uv[faces[k]]
        d.polygon([(t[0, 0] * w, (1.0 - t[0, 1]) * h), (t[1, 0] * w, (1.0 - t[1, 1]) * h), (t[2, 0] * w, (1.0 - t[2, 1]) * h)], fill=fill if mode == "L" else tuple(int(v) for v in fill[k]))
    return im


def tint_base_color(glb: str, uv: np.ndarray, faces: np.ndarray, face_tone: np.ndarray, gt: dict, face_neutral: np.ndarray | None = None,
                    group: np.ndarray | None = None) -> tuple[bytes | None, np.ndarray | None, list[dict]] | None:
    """Новая карта цвета: у граней с тоном стекла (face_tone N×3, nan — нет тона) цвет островов UV = тон; остальное байт в байт. → (PNG, маска изменённых текселей, отчёт).
    Нейтральная база (T-169/9в, советник Codex): стекло БЕЗ тона, у которого карта TRELLIS тёмная (медиана L его текселей < `dark_L_max`), получает нейтральный цвет
    (`face_neutral` N×3, nan — не нужно; `group` — номер части у грани): чёрная карта под прозрачным стеклом давала «чёрное непросвечивающее»; нетёмная карта (янтарь, молоко) не трогается.
    Поля островов (`patch_dilate_px`) — только в пустые тексели: тексели, занятые гранями БЕЗ тона, не перекрашиваются никогда (утечка в соседний остров исключена)."""
    from scipy import ndimage

    doc, binb = read_glb(glb)
    base = _base_image(doc, binb)
    if base is None:
        return None
    size = base.size
    ft = np.array(face_tone, dtype=np.float64)
    info: list[dict] = []
    if face_neutral is not None and group is not None:
        bl = rgb_to_lab(np.asarray(base)[..., :3].reshape(-1, 3).astype(np.float64))[:, 0].reshape(size[1], size[0])
        for g in sorted({int(x) for x in group[~np.isnan(face_neutral[:, 0])]}):
            gi = np.flatnonzero((group == g) & ~np.isnan(face_neutral[:, 0]) & np.isnan(ft[:, 0]))
            if not len(gi):
                continue
            occ = np.asarray(_raster_faces(uv, faces, gi, size)) > 0
            med = float(np.median(bl[occ])) if occ.any() else None
            use = med is not None and med < gt["dark_L_max"]
            info.append({"part": g, "source": "neutral-base", "applied": bool(use), "median_L": None if med is None else round(med, 1), "used": [int(v) for v in face_neutral[gi[0]]] if use else None})
            if use:
                ft[gi] = face_neutral[gi]
    sel = ~np.isnan(ft[:, 0])
    if not sel.any():
        return None, None, info                                  # перекрашивать нечего — карта байт в байт, но отчёт про нейтральную базу остаётся
    ta = np.asarray(_raster_faces(uv, faces, np.flatnonzero(sel), size, fill=np.nan_to_num(ft, nan=0).astype(int), mode="RGB"))
    km = gt.get("keep_map") or {}
    if km.get("on"):                                      # рисунок карты 07 (градиент, блики) остаётся: остров сдвигается в Lab так, чтобы медиана стала тоном; ровная карта — заливка
        ta = ta.copy()
        base_rgb = np.asarray(base)[..., :3]
        ftk = np.nan_to_num(ft, nan=-1).astype(int)
        for tone in sorted({tuple(int(v) for v in t) for t in ft[sel]}):
            tg = np.flatnonzero(sel & np.all(ftk == np.array(tone), axis=1))
            occ_t = np.asarray(_raster_faces(uv, faces, tg, size)) > 0
            if not occ_t.any():
                continue
            lab_t = rgb_to_lab(base_rgb[occ_t].astype(np.float64))
            sigma = float(np.percentile(lab_t[:, 0], 90) - np.percentile(lab_t[:, 0], 10))
            chroma = float(np.median(np.hypot(lab_t[:, 1], lab_t[:, 2])))
            kept = sigma > km["flat_sigma_max"] and chroma > km["neutral_C_max"]        # рисунок И цвет: серая/чёрная карта TRELLIS (хрома ≤ neutral_C_max) — тон стекла законно её заменяет
            info.append({"source": "keep-map" if kept else "flat-fill", "tone": list(tone), "sigma_L_07": round(sigma, 1), "median_L_07": round(float(np.median(lab_t[:, 0])), 1), "median_C_07": round(chroma, 1)})
            if not kept:
                continue
            ta[occ_t] = base_rgb[occ_t]                   # рисунок остаётся как есть: тексели острова — прежние (иначе ta стёр бы их тоном; цвет шаг 08 не меняет)
    occupied = np.asarray(_raster_faces(uv, faces, np.flatnonzero(sel), size)) > 0
    other = np.asarray(_raster_faces(uv, faces, np.flatnonzero(~sel), size)) > 0       # тексели граней без тона: неприкосновенны
    dist, idx = ndimage.distance_transform_edt(~occupied, return_indices=True)
    mask = (dist <= gt["patch_dilate_px"]) & ~other        # поля островов: билинейная выборка у шва не должна тянуть старый цвет — но не в чужой остров
    out = np.asarray(base).copy()
    out[mask, :3] = ta[idx[0], idx[1]][mask]
    return _png(out), mask, info


def pad_base_color(glb: str, uv: np.ndarray, faces: np.ndarray, base_png: bytes | None, mask: np.ndarray | None) -> tuple[bytes | None, np.ndarray | None, dict | None]:
    """Заливка непокрытых текселей карты цвета ПОСЛЕ последней покраски 08 (тон стекла, сдвиг части), перед записью (T-20261125-70; правило paint-fill.json → texel_fill, модуль tools/scout/texel_pad.py).
    → (PNG или прежний base_png, маска изменённых текселей = прежняя ∪ залитые, отчёт для check.json). Покрытое (центр внутри грани) не меняется; нет карты цвета/квадратной карты — отчёт None."""
    from PIL import Image
    sd = os.path.join(ROOT, "tools", "scout")
    if sd not in sys.path:
        sys.path.insert(0, sd)
    import texel_pad as TP

    base = _base_image(*read_glb(glb))
    if base is None:
        return base_png, mask, None
    cur = Image.open(io.BytesIO(base_png)).convert("RGBA") if base_png is not None else base
    arr = np.asarray(cur)
    if arr.shape[0] != arr.shape[1]:
        return base_png, mask, None
    cov = TP.coverage_from_uv(np.asarray(uv, dtype=np.float64), np.asarray(faces), arr.shape[0])
    out, rep = TP.pad_texture(arr, cov, TP.rules())
    changed = np.any(out != arr, axis=-1)
    if not changed.any():
        return base_png, mask, rep
    return _png(out), (changed if mask is None else (mask | changed)), rep


def lab_to_rgb(lab: np.ndarray) -> np.ndarray:
    """CIE Lab (D65, N×3) → sRGB 0..255 (uint8, с обрезкой)."""
    fy = (lab[:, 0] + 16) / 116
    fx, fz = fy + lab[:, 1] / 500, fy - lab[:, 2] / 200
    f = np.stack([fx, fy, fz], axis=1)
    xyz = np.where(f ** 3 > 216 / 24389, f ** 3, (116 * f - 16) / (24389 / 27)) * np.array([0.95047, 1.0, 1.08883])
    m = np.array([[0.4124564, 0.3575761, 0.1804375], [0.2126729, 0.7151522, 0.0721750], [0.0193339, 0.1191920, 0.9503041]])
    c = np.clip(xyz @ np.linalg.inv(m).T, 0.0, 1.0)
    c = np.where(c <= 0.0031308, 12.92 * c, 1.055 * np.power(c, 1 / 2.4) - 0.055)
    return np.clip(np.rint(c * 255), 0, 255).astype(np.uint8)


def fill_gate(stages_dir: str, c: dict) -> tuple[bool, str, dict]:
    """Заслон «08 только при наличии 07» (T-20261124-10/3, владелец TG 2484; `check.require_fill_present` в material-recipes.json) → (можно, причина, отчёт о 07).
    Читает `<stages_dir>/07-fill/check.json` того же товара. 07 ЕСТЬ, если файл читается и этап выдал результат (`outputs` не пуст): тогда 08 идёт, а красный вердикт 07 по порогам
    (dE00_front_back, time_s, filled_faces_step_pct…) попадает в отчёт замечанием (`fill_stage`) — ворота 07 с качеством не связаны (`~/remlab-logs/t2406-1124/gates-eval.md`), качество — автооценка.
    Нет файла/папки, файл нечитаем или этап не дал выхода (сбой, отказ входа) — путь мимо 06/07 оставляет родной цвет TRELLIS (урок 807) → нельзя. Правило выключено — всегда можно."""
    if not c.get("require_fill_present"):
        return True, "", {}
    f = os.path.join(stages_dir, "07-fill", "check.json")
    try:
        d = json.load(open(f, encoding="utf-8"))
    except (OSError, ValueError):
        return False, "нет check.json этапа 07 (заливка) того же товара: путь мимо 06/07 оставляет родной цвет TRELLIS — на этап 08 не пускаем", {}
    if not isinstance(d, dict):
        return False, "check.json этапа 07 нечитаем — на этап 08 не пускаем", {}
    if not d.get("outputs"):
        return False, "этап 07 (заливка) не дал результата (сбой или отказ входа): " + str(d.get("reason") or "причина не названа")[:140], {}
    note = {"passed": d.get("passed") is True, "reason": str(d.get("reason") or "")[:200]}
    return True, "", note


def photo_signal(stages_dir: str, pp: dict):
    """Вход «цвет части с фото» (T-20261121-169/9в ❷). Один источник «видимого» — этап 6 (камера этапа 4, z-буфер, угол к камере, отступ от края силуэта):
    тексели `known.png` и цвет фото в `visible.glb`. Новой проекции здесь нет. Ворота: этап 4 passed и `silhouette_iou` этапа 6 ≥ `iou_min` (иначе камере не верим);
    общий passed этапа 6 не нужен (known_share может быть мал, а видимые части — честные). → (инфо, known bool H×W | None, vis PIL RGBA | None)."""
    from PIL import Image

    def chk(st):
        f = os.path.join(stages_dir, st, "check.json")
        return json.load(open(f, encoding="utf-8")) if os.path.exists(f) else None

    c4, c6 = chk("04-camera"), chk("06-visible")
    if not c4 or not c4.get("passed"):
        return {"gate": "closed", "why": "этап 4 не passed — камере не верим"}, None, None
    m6 = (c6 or {}).get("metric") or {}
    iou = m6.get("value") if m6.get("name") == "silhouette_iou" else None
    if iou is None or iou < pp["iou_min"]:
        return {"gate": "closed", "why": f"silhouette_iou этапа 6 {iou} < {pp['iou_min']}", "silhouette_iou": iou}, None, None
    kp, vp = os.path.join(stages_dir, "06-visible", "known.png"), os.path.join(stages_dir, "06-visible", "visible.glb")
    if not (os.path.exists(kp) and os.path.exists(vp)):
        return {"gate": "closed", "why": "нет known.png/visible.glb этапа 6", "silhouette_iou": iou}, None, None
    vis = _base_image(*read_glb(vp))
    if vis is None:
        return {"gate": "closed", "why": "в visible.glb нет карты цвета", "silhouette_iou": iou}, None, None
    return {"gate": "open", "silhouette_iou": iou}, np.asarray(Image.open(kp).convert("L")) > 127, vis


def part_photo_colours(uv: np.ndarray, faces: np.ndarray, part: np.ndarray, pids: list[int], base, known: np.ndarray, vis, pp: dict) -> dict[int, dict]:
    """Цвет каждой части по «известным» текселям этапа 6 в её островах UV: отступ `inset_px` от стыка с другими частями/гранями без части и от края острова, без верхних
    `highlight_trim` по L (блики); меньше `min_pixels` — нет данных (честно, цвет не выдумываем). `was` — медиана карты цвета входа по тому же ядру острова.
    `L_spread` — разброс L* (p90−p10) известных текселей после среза бликов; → {часть: {island_px, core_px, photo_px, photo, was, dE, L_spread, island(маска острова: тексели только этой части)}}."""
    import cv2
    from PIL import Image

    size = base.size
    w, h = size
    kn = known if known.shape == (h, w) else np.asarray(Image.fromarray((known * 255).astype(np.uint8)).resize(size, Image.NEAREST)) > 127
    vi = np.asarray((vis if vis.size == size else vis.resize(size, Image.NEAREST)).convert("RGB"))
    bi = np.asarray(base.convert("RGB"))
    ids = sorted({int(x) for x in np.unique(part)})
    occ = {q: np.asarray(_raster_faces(uv, faces, np.flatnonzero(part == q), size)) > 0 for q in ids}
    cnt = np.zeros((h, w), np.int16)
    for q in ids:
        cnt += occ[q]
    ker = np.ones((2 * pp["inset_px"] + 1,) * 2, np.uint8)
    out: dict[int, dict] = {}
    for pid in pids:
        if pid not in occ:
            continue
        island = occ[pid] & ((cnt - occ[pid]) == 0)                  # тексели только этой части: чужие и «без части» исключены
        core = cv2.erode(island.astype(np.uint8), ker) > 0
        sel = core & kn
        rec: dict = {"island_px": int(island.sum()), "core_px": int(core.sum()), "photo_px": int(sel.sum()), "photo": None, "was": None, "dE": None, "island": island}
        if rec["core_px"] >= 1:
            px = bi[core]
            L = rgb_to_lab(px.astype(np.float64))[:, 0]
            rec["was"] = [int(v) for v in np.median(px[L <= np.quantile(L, 1.0 - pp["highlight_trim"])], axis=0)]
        if rec["photo_px"] >= pp["min_pixels"]:
            px = vi[sel]
            L = rgb_to_lab(px.astype(np.float64))[:, 0]
            px = px[L <= np.quantile(L, 1.0 - pp["highlight_trim"])]
            if len(px) >= pp["min_pixels"]:
                rec["photo"] = [int(v) for v in np.median(px, axis=0)]
                Lt = rgb_to_lab(px.astype(np.float64))[:, 0]
                rec["L_spread"] = round(float(np.percentile(Lt, 90) - np.percentile(Lt, 10)), 1)     # разброс света известных текселей: большой = смесь блика/тени/другого материала, медиане не верим
        if rec["photo"] and rec["was"]:
            rec["dE"] = round(float(np.linalg.norm(rgb_to_lab(np.array([rec["was"]], dtype=np.float64))[0] - rgb_to_lab(np.array([rec["photo"]], dtype=np.float64))[0])), 1)
        out[pid] = rec
    return out


def shift_part_colours(base_png: bytes | None, glb: str, targets: dict[int, dict]) -> tuple[bytes, np.ndarray]:
    """Сдвиг цвета островов частей к цвету с фото: в Lab добавляется разница (фото − было), рисунок внутри острова сохраняется. Меняются ТОЛЬКО тексели острова части
    (`island`: чужие части и «без части» не входят), без полей. → (PNG, маска изменённых текселей)."""
    from PIL import Image

    img = Image.open(io.BytesIO(base_png)).convert("RGBA") if base_png else _base_image(*read_glb(glb))
    arr = np.asarray(img).copy()
    mask = np.zeros(arr.shape[:2], bool)
    for rec in targets.values():
        isl = rec["island"]
        d = rgb_to_lab(np.array([rec["photo"]], dtype=np.float64))[0] - rgb_to_lab(np.array([rec["was"]], dtype=np.float64))[0]
        lab = rgb_to_lab(arr[isl][:, :3].astype(np.float64)) + d
        lab[:, 0] = np.clip(lab[:, 0], 0, 100)
        arr[isl, :3] = lab_to_rgb(lab)
        mask |= isl
    return _png(arr), mask


def _texel_metrics(rep: dict | None) -> dict:
    """Мерки заливки непокрытых текселей для check.json 08 (texel_pad.check_metrics); нет карты цвета — пусто."""
    if not rep:
        return {}
    import texel_pad as TP
    return TP.check_metrics(rep)


def colour_unchanged_outside(src_glb: str, dst_glb: str, mask: np.ndarray | None) -> bool:
    """Карта цвета не тронута везде, кроме текселей под тоном стекла и залитых непокрытых (mask). Нет маски — байт в байт."""
    if mask is None:
        return image_sha(src_glb, "baseColor") == image_sha(dst_glb, "baseColor")
    a, b = _base_image(*read_glb(src_glb)), _base_image(*read_glb(dst_glb))
    if a is None or b is None or a.size != b.size:
        return False
    return bool((np.asarray(a)[~mask] == np.asarray(b)[~mask]).all())


def stamp_glb(path: str) -> None:
    """Ставит в готовый GLB отметку «прошёл этап 08» (asset.extras[STAGE_MARK_KEY] = STAGE); геометрия, карты и их байты не тронуты. Зовёт run_stage ТОЛЬКО когда check.json вышел passed=true
    (T-20261124-07/2): красный этап отметки не получает — лёгкая копия для сайта не берёт у него карты материала (runtime_mesh.stage_passed)."""
    doc, binb = read_glb(path)
    doc.setdefault("asset", {"version": "2.0"}).setdefault("extras", {})[STAGE_MARK_KEY] = STAGE
    write_glb(path, doc, binb)


def patch_glb(src: str, dst: str, maps: dict, base_png: bytes | None = None, stage_mark: bool = True) -> dict:
    """Копия GLB с новыми картами материала 0: metallicRoughness заменена (на месте), sheenColor и transmission добавлены расширениями. Геометрия не тронута; цвет — тоже,
    кроме `base_png` (карта цвета с тоном стекла у стеклянных граней — `tint_base_color`; нет тона — None, байт в байт)."""
    doc, binb = read_glb(src)
    if stage_mark:                                  # по ней лёгкая копия для сайта узнаёт модель этапа 08 (не по ID); run_stage передаёт False и ставит её после зелёного check.json (stamp_glb)
        doc.setdefault("asset", {"version": "2.0"}).setdefault("extras", {})[STAGE_MARK_KEY] = STAGE
    else:                                           # исходник мог уже нести отметку (вход — готовый material.glb): красный этап её не наследует
        ex = (doc.get("asset") or {}).get("extras")
        if isinstance(ex, dict):
            ex.pop(STAGE_MARK_KEY, None)
    views = [bytearray(_view_bytes(doc, binb, i)) for i in range(len(doc["bufferViews"]))]
    mat = doc["materials"][0]
    pbr = mat.setdefault("pbrMetallicRoughness", {})
    doc.setdefault("images", [])
    doc.setdefault("textures", [])
    sampler = None
    if pbr.get("baseColorTexture"):
        sampler = doc["textures"][pbr["baseColorTexture"]["index"]].get("sampler")

    def add_texture(png: bytes) -> int:
        views.append(bytearray(png))
        doc["bufferViews"].append({"buffer": 0, "byteOffset": 0, "byteLength": len(png)})
        doc["images"].append({"mimeType": "image/png", "bufferView": len(views) - 1})
        t = {"source": len(doc["images"]) - 1}
        if sampler is not None:
            t["sampler"] = sampler
        doc["textures"].append(t)
        return len(doc["textures"]) - 1

    mr_png = _png(maps["mr"])
    old = pbr.get("metallicRoughnessTexture")
    if old:                                         # замена на месте: тот же индекс картинки, старые байты уходят
        bv = doc["images"][doc["textures"][old["index"]]["source"]]["bufferView"]
        views[bv] = bytearray(mr_png)
    else:
        pbr["metallicRoughnessTexture"] = {"index": add_texture(mr_png)}
    if base_png is not None and pbr.get("baseColorTexture"):
        bvb = doc["images"][doc["textures"][pbr["baseColorTexture"]["index"]]["source"]]["bufferView"]
        views[bvb] = bytearray(base_png)
    pbr["metallicFactor"] = 1.0
    pbr["roughnessFactor"] = 1.0
    ext = mat.setdefault("extensions", {})
    used = set(doc.get("extensionsUsed") or [])
    if maps["hasSheen"]:
        ext["KHR_materials_sheen"] = {"sheenColorFactor": [1.0, 1.0, 1.0], "sheenColorTexture": {"index": add_texture(_png(maps["sheen"]))},
                                      "sheenRoughnessFactor": maps["sheenRoughness"]}
        used.add("KHR_materials_sheen")
    if maps["hasTransmission"]:
        ext["KHR_materials_transmission"] = {"transmissionFactor": 1.0, "transmissionTexture": {"index": add_texture(_png(maps["trans"]))}}
        used.add("KHR_materials_transmission")
    if used:
        doc["extensionsUsed"] = sorted(used)
    out = bytearray()
    for i, v in enumerate(views):                   # пересборка BIN: каждый вид выровнен на 4 байта, смещения пересчитаны
        out += b"\0" * (-len(out) % 4)
        doc["bufferViews"][i]["byteOffset"] = len(out)
        doc["bufferViews"][i]["byteLength"] = len(v)
        out += v
    doc["buffers"] = [{"byteLength": len(out)}]
    write_glb(dst, doc, bytes(out))
    return {"extensions": sorted(used), "mrBytes": len(mr_png)}


# ───────────────────────── этап ─────────────────────────

def _load_mesh(path: str):
    import trimesh
    return trimesh.load(path, force="mesh", process=False)


def run_stage(glb: str, run: str, sku: str, product: dict, parts_dir: str | None = None, frame: bool = True, photo: str | None = None, stages_dir: str | None = None) -> dict:
    """Этап 08 одного товара → `<run>/<sku>/08-material/`. Возвращает check.json (словарь)."""
    ps = _paint_stage()
    mc, mp = _siblings()
    t0 = time.time()
    recipes = load_recipes()
    sdir = ps.stage_dir(run, sku, STAGE)
    fail = lambda why, **kw: ps.write_check(sdir, STAGE, sku, passed=False, reason=why, seconds=time.time() - t0,  # noqa: E731
                                            rules=[_rule_record().entry(RULE_GLOSS, product.get("role"), False, "этап 08 не дошёл до материалов: " + why[:120])], **kw)
    stale = os.path.join(sdir, "material.glb")
    if os.path.lexists(stale):                      # перевыпуск пересоздаёт material.glb целиком: прежний (с отметкой «прошёл») не должен пережить красный/упавший перевыпуск
        os.unlink(stale)
    mesh = _load_mesh(glb)
    nf = len(mesh.faces)
    uv = getattr(mesh.visual, "uv", None)
    if uv is None:
        return fail("в модели нет развёртки UV — рецепт некуда запекать", faces=nf)
    plate_rep, plate_mt = _plate_guard(mesh)
    rules = mc.load_rules()
    cls = mc.classify(rules, {"role": product.get("role") or "", "name": product.get("name") or "", "params": product.get("params") or {}})
    cls["group"] = rules["_roleGroup"].get(product.get("role") or "")          # группа каталога (seating/bed/…): от неё зависит политика для частей без метки
    cls["gloss"] = gloss_of(product, recipes)                                    # глянец/лак по словам названия и характеристик (`gloss_finish`)
    cls["compound"] = compound_of(rules, cls, recipes)                          # составное поле материала («Металл, Хрусталь») — список классов, части берут по одному из него
    pdir = parts_dir or os.path.join(run, ps.safe_name(sku), "03-parts")
    npz = os.path.join(pdir, "parts.npz")
    shape_rep = None
    parts_without_role = 0
    if os.path.exists(npz):
        part = np.load(npz)["part"].astype(np.int64)
        info = json.load(open(os.path.join(pdir, "parts.json"), encoding="utf-8"))
        parts = info["parts"]
        merge_roles(parts, os.path.join(pdir, "roles.json"))
        parts_without_role = ensure_roles(parts)                                   # нет роли → unknown (геометрия), не KeyError; число — в check.json
        parts_source = "stage3"
        if len(part) != nf:
            return fail(f"число граней частей этапа 3 ({len(part)}) ≠ меша ({nf}) — части считались на другой модели", faces=nf)
    else:
        part, parts, shape_rep = geometry_shape_parts(mesh, mp, cls.get("parts") or {}, recipes)
        part = part.astype(np.int64)
        parts_source = "geometry"
    if parts_source == "stage3":                    # этап 3 ножки называет редко: добираем геометрией; цвет частей — по листу цвета модели (этап 7)
        mark_legs(parts, part, legs_by_geometry(mesh, mp, cls.get("parts") or {}), recipes["classify"]["legs_part_share"])
    cols = part_colours(mesh, part)
    for p in parts:
        if not p.get("colour") or not p["colour"].get("lab_median"):
            p["colour"] = cols.get(p["id"])
        elif p["colour"].get("L_spread") is None and cols.get(p["id"]):
            p["colour"]["L_spread"] = cols[p["id"]]["L_spread"]
    res = resolve_parts(parts, cls, recipes, parts_known=True)   # части по этапу 3 или по форме — материалы по ним разведены; «где плафон» не гадаем
    part, inherited = inherit_unseen(mesh, part, list(res))
    np.savez_compressed(os.path.join(sdir, "parts08.npz"), part=part.astype(np.int16))        # часть на каждую грань (номера — как в check.json parts): нужна замерам и ревью кадров
    horiz = horizontal_shares(mesh, part, list(res), recipes) if recipes.get("flat_top") else {}
    for pid, sh in horiz.items():
        res[pid]["horizontal_share"] = sh
    fb = recipes["fallback_class"]
    cls_of_face = np.full(nf, fb, dtype=object)
    for pid, r in res.items():
        cls_of_face[part == pid] = r["class"]
    table = class_table(recipes, list(dict.fromkeys(cls_of_face.tolist())))
    label_of = {c: i for i, c in enumerate(table, start=1)}
    face_label = np.array([label_of[c] for c in cls_of_face], dtype=np.int64)
    lab = rasterize_labels(np.asarray(uv, dtype=np.float64), np.asarray(mesh.faces), face_label, recipes["bake"]["mapSize"])
    flat_mask = None
    ftop = recipes.get("flat_top")
    if ftop:
        flat_ids = {pid for pid, sh in horiz.items() if sh >= ftop["horizontal_min_share"]}
        if flat_ids:
            fl = np.where(np.isin(part, list(flat_ids)), 2, 1).astype(np.int64)
            flat_mask = rasterize_labels(np.asarray(uv, dtype=np.float64), np.asarray(mesh.faces), fl, recipes["bake"]["mapSize"]) == 2
    maps = bake_maps(lab, table, recipes, _base_image(*read_glb(glb)), flat_mask)
    out_glb = os.path.join(sdir, "material.glb")
    gt = recipes["glass_tone"]
    glass_cls = {c for c, d in rules["_byId"].items() if d["family"] == "glass"}
    tone_rep: list[dict] = []
    face_tone = np.full((nf, 3), np.nan)
    pp = recipes.get("part_photo")
    pp_rep = None                                                  # цвет частей с фото (этап 6): измерение всегда, применение — только `part_photo.apply`
    pp_cols: dict[int, dict] = {}
    if pp and parts_source == "stage3":
        sig, known_px, vis_img = photo_signal(stages_dir or os.path.join(run, ps.safe_name(sku)), pp)
        pp_rep = {"apply": bool(pp["apply"]), **sig, "parts": []}
        if known_px is not None:
            base0 = _base_image(*read_glb(glb))
            if base0 is not None:
                pp_cols = part_photo_colours(np.asarray(uv, dtype=np.float64), np.asarray(mesh.faces), part, [pid for pid in res], base0, known_px, vis_img, pp)
    glass_only = bool(res) and all(r["class"] in glass_cls for r in res.values())
    photo_rgb = photo_tone(photo, gt) if (photo and glass_only) else None      # фото сверяет тон только у цельностеклянного товара: плафон на фото от остального не отделить
    for pid, r in res.items():
        if r.get("tone") and r["class"] in glass_cls:
            prgb = photo_rgb if glass_only else ((pp_cols.get(pid) or {}).get("photo") if (pp and pp["apply"]) else None)     # составной товар: цвет части с этапа 6, только при apply
            rt = reconcile_tone(r["tone"], prgb, gt)
            r["tone"] = rt["used"]
            tone_rep.append({"part": int(pid), **rt, **({"tone_source": r["tone_source"]} if r.get("tone_source") else {})})
            face_tone[part == pid] = rt["used"]
    face_neutral = np.full((nf, 3), np.nan)
    group = np.full(nf, -1, dtype=np.int64)
    for pid, r in res.items():
        if r["class"] in glass_cls and not r.get("tone"):
            face_neutral[part == pid] = gt["neutral_rgb"].get(r["class"], gt["neutral_rgb"]["glass"])
            group[part == pid] = pid
    tinted = tint_base_color(glb, np.asarray(uv, dtype=np.float64), np.asarray(mesh.faces), face_tone, gt, face_neutral, group)
    if tinted:
        tone_rep.extend(tinted[2])
    base_png = tinted[0] if tinted else None
    mask_all = tinted[1] if tinted else None
    if pp_rep is not None:
        targets: dict[int, dict] = {}
        for pid, rec in pp_cols.items():
            r = res[pid]
            is_glass = r["class"] in glass_cls
            spread_bad = rec.get("L_spread") is not None and rec["L_spread"] > pp["l_spread_max"]          # ограничитель света: фото части — смесь света и тени, медиана неверна
            cand = (not is_glass) and rec["photo"] is not None and rec["was"] is not None and rec["dE"] is not None and rec["dE"] > pp["dE_apply"] and not spread_bad
            pp_rep["parts"].append({"part": int(pid), "role": next((p["role"] for p in parts if p["id"] == pid), None), "class": r["class"], **{k: v for k, v in rec.items() if k != "island"},
                                    "would_apply": bool(cand), "applied": bool(cand and pp["apply"]),
                                    **({"note": "стекло: цвет берёт тон стекла (reconcile_tone), не сдвиг карты"} if is_glass else {}),
                                    **({"skipped": f"разброс света фото {rec['L_spread']} > {pp['l_spread_max']}: медиане не верим"} if (spread_bad and not is_glass and rec["dE"] is not None and rec["dE"] > pp["dE_apply"]) else {})})
            if cand:
                targets[pid] = rec
        if pp["apply"] and targets:
            base_png, m2 = shift_part_colours(base_png, glb, targets)
            mask_all = m2 if mask_all is None else (mask_all | m2)
    base_png, mask_all, texel_rep = pad_base_color(glb, np.asarray(uv, dtype=np.float64), np.asarray(mesh.faces), base_png, mask_all)       # непокрытые тексели — цветом соседей (после всей покраски 08)
    pinfo = patch_glb(glb, out_glb, maps, base_png, stage_mark=False)
    covered = part >= 0
    known = np.isin(part, [pid for pid in res])
    recipe_share = float((covered & known).sum()) / nf
    inherited_share = float(inherited.sum()) / nf
    conf_ids = [pid for pid, r in res.items() if r["confident"]]
    confident_share = float(np.isin(part, conf_ids).sum()) / nf
    c = recipes["check"]
    fill_ok, fill_why, fill_note = fill_gate(stages_dir or os.path.join(run, ps.safe_name(sku)), c)
    color_same = colour_unchanged_outside(glb, out_glb, mask_all)
    sys.path.insert(0, os.path.join(ROOT, "tools", "scout", "salad", "trellis"))
    import stage_mask_gate as _smg                              # импорт вне try: нет модуля = отказ этапа
    allowed_file = None
    try:                                                       # контракт «маска разрешено менять» (T-20261124-23/в2): 08 красит только тон стекла / сдвиг цвета части — их маска `mask_all`; её нет — ничего менять нельзя (маска из нулей)
        _bi = _base_image(*read_glb(out_glb))
        _al = np.zeros((_bi.size[1], _bi.size[0]), bool) if mask_all is None else np.asarray(mask_all, bool)
        allowed_file = _smg.write_allowed(sdir, [_al])[0]
    except Exception as _e:  # noqa: BLE001 — маска не роняет этап: нет файла = «маска не заявлена» (ворота строгие)
        allowed_file = None
        tone_rep.append({"source": "changed-allowed", "error": f"{type(_e).__name__}: {_e}"[:200]})
    geom_same = geometry_sha(glb) == geometry_sha(out_glb)
    parts_rep = [{"id": pid, "role": next((p["role"] for p in parts if p["id"] == pid), None), "face_share": next((p["face_share"] for p in parts if p["id"] == pid), None),
                  "inherited_share": round(float(((part == pid) & inherited).sum()) / nf, 4), **r}
                 for pid, r in sorted(res.items(), key=lambda t: -next(p["face_share"] for p in parts if p["id"] == t[0]))]
    frame_name = None
    why_frame = ""
    if frame:
        frame_name, why_frame = render_frame(out_glb, os.path.join(sdir, "frame.png"), recipes)
    located = {"legs": any(p["role"] == "legs" for p in parts_rep), "shade": any(p["source"] == "geometry:top" for p in parts_rep),
               "handles": any(p["source"] == "geometry:small" for p in parts_rep), "frame": any(p["source"] == "geometry:linear" for p in parts_rep)}
    not_located = [k for k in (cls.get("parts") or {}) if parts_source == "geometry" and not located.get(k, False)]   # материал в каталоге есть, а где он — форма не нашла
    unsure = [f"{p['role']} ({p['face_share']:.0%}): {p['reason']}" for p in parts_rep if not p["confident"]]
    unsure_rep = unsure_parts_report(mesh, part, parts_rep, parts, recipes)
    reason = ""
    if frame and not frame_name:
        reason = "кадр не получен: " + why_frame
    elif inherited_share > c["inherited_share_max"]:
        reason = f"{inherited_share:.0%} граней без части (порог {c['inherited_share_max']:.0%}): класс по соседним граням — слишком много угадано"
    elif confident_share < c["confident_share_min"]:
        reason = "не уверен: " + "; ".join(unsure)[:400]
    elif not fill_ok:
        reason = fill_why
    doc = ps.write_check(
        sdir, STAGE, sku, passed=None if not reason else False,
        metric={"name": "confident_share", "value": round(confident_share, 4), "threshold": c["confident_share_min"], "op": ">="},
        metrics={"recipe_share": {"value": round(recipe_share, 4), "threshold": c["recipe_share_min"], "op": ">="},
                 "inherited_share": {"value": round(inherited_share, 4), "threshold": c["inherited_share_max"], "op": "<="},
                 "fill_present": {"value": bool(fill_ok), "threshold": True, "op": "=="},
                 "color_unchanged": {"value": bool(color_same), "threshold": True, "op": "=="},
                 **(_texel_metrics(texel_rep)),
                 "geometry_unchanged": {"value": bool(geom_same), "threshold": True, "op": "=="},
                 "seconds": {"value": round(time.time() - t0, 1), "threshold": c["max_seconds"], "op": "<="}, **plate_mt},
        reason=reason, seconds=time.time() - t0, outputs=["material.glb"] + ([allowed_file] if allowed_file else []), frame=frame_name, plate=plate_rep, fill_stage=fill_note, texel_fill=texel_rep,
        faces=nf, parts_source=parts_source, parts_without_role=parts_without_role, shape=shape_rep, catalog_parts_not_located=not_located, unsure_parts=unsure_rep, product_class={"class": cls["class"], "stage": cls["stage"], "confidence": cls["confidence"], "reason": cls["reason"], "parts": cls.get("parts")},
        parts=parts_rep, classes=table, compound=cls.get("compound") or [], untouched_share=round(float(np.isin(part, [pid for pid, r in res.items() if r["class"] == "unknown"]).sum()) / nf, 4),
        painted_metal_share=round(float(np.isin(part, [pid for pid, r in res.items() if r.get("painted_from")]).sum()) / nf, 4),
        gloss_finish_share=round(float(np.isin(part, [pid for pid, r in res.items() if r.get("gloss_from")]).sum()) / nf, 4), gloss_finish=cls.get("gloss"),
        rules=[gloss_rule_entry(product.get("role"), cls, res, recipes)],
        flat_top_parts=sorted(pid for pid, sh in horiz.items() if ftop and sh >= ftop["horizontal_min_share"]), glass_tone=tone_rep, part_photo=pp_rep, sheen=maps["hasSheen"], transmission=maps["hasTransmission"], recipes_sha=recipes_sha(), glb=pinfo)
    if doc["passed"]:                               # отметку «прошёл этап 08» получает только зелёный этап; check.json — истина, GLB её повторяет
        stamp_glb(out_glb)
    return doc


def render_frame(glb: str, out_png: str, recipes: dict) -> tuple[str | None, str]:
    """Кадр «перёд при студийном свете» в Blender (CPU, без окна). → (имя файла | None, причина)."""
    f = recipes["frame"]
    if not os.path.exists(BLENDER):
        return None, f"нет Blender: {BLENDER}"
    cmd = [BLENDER, "-b", "-P", FRAME_SCRIPT, "--", glb, out_png, "--size", str(f["size"]), "--samples", str(f["samples"]),
           "--az", str(f["azimuthDeg"]), "--el", str(f["elevationDeg"])]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=3000)
    if p.returncode != 0 or not os.path.exists(out_png):
        return None, (p.stderr or p.stdout)[-300:].replace("\n", " ")
    return os.path.basename(out_png), ""


def check() -> int:
    mc, _mp = _siblings()
    recipes = load_recipes()
    rules = mc.load_rules()
    bad: list[str] = []
    for cid in rules["_byId"]:
        r = recipes["recipes"].get(cid)
        if r is None:
            bad.append(f"класс {cid}: нет рецепта")
            continue
        for p in PROPS + ("sheenRoughness",):
            v = r.get(p)
            if not isinstance(v, (int, float)) or not 0.0 <= v <= 1.0:
                bad.append(f"{cid}.{p}: {v!r} вне 0..1")
    stage_only = set((recipes.get("stage_classes") or {}).get("ids", []))
    for cid in recipes["recipes"]:
        if cid not in rules["_byId"] and cid not in stage_only:
            bad.append(f"рецепт {cid}: такого класса нет в material-classes.json (и он не в stage_classes)")
    for cid in stage_only:
        if cid in rules["_byId"]:
            bad.append(f"stage_classes: {cid} уже есть в material-classes.json")
        if cid not in recipes["recipes"]:
            bad.append(f"stage_classes: {cid} без рецепта")
    for sec, keys in (("compound", ("glass_L_min", "glass_C_max")), ("painted_metal", ("chroma_min", "light_L_min", "light_spread_max")),
                      ("flat_top", ("horizontal_min_share", "min_cos", "roughness_min", "skip_metallic", "skip_transmission"))):
        for k in keys:
            v = (recipes.get(sec) or {}).get(k)
            if not isinstance(v, (int, float)) or v < 0:
                bad.append(f"{sec}.{k}: {v!r}")
    gf = recipes.get("gloss_finish")
    if gf is not None:
        for k in ("words", "not_words"):
            if not isinstance(gf.get(k), list) or (k == "words" and not gf[k]):
                bad.append(f"gloss_finish.{k}: {gf.get(k)!r} (нужен список регулярок, words непустой)")
            for rx in gf.get(k) or []:
                try:
                    re.compile(rx)
                except re.error as e:
                    bad.append(f"gloss_finish.{k}: регулярка {rx!r}: {e}")
        for a, b in (gf.get("class_map") or {}).items():
            for cid in (a, b):
                if cid not in recipes["recipes"]:
                    bad.append(f"gloss_finish.class_map: класс {cid} без рецепта")
        if not gf.get("class_map"):
            bad.append("gloss_finish.class_map пуст")
    for sec in ("compound", "painted_metal"):
        for cid in (recipes.get(sec) or {}).get("from", []) + [(recipes.get(sec) or {}).get("class")] * (sec == "painted_metal"):
            if cid and cid not in recipes["recipes"]:
                bad.append(f"{sec}: класс {cid} без рецепта")
    km = (recipes.get("glass_tone") or {}).get("keep_map") or {}
    if not isinstance(km.get("on"), bool) or not all(isinstance(km.get(k), (int, float)) for k in ("flat_sigma_max", "neutral_C_max")):
        bad.append(f"glass_tone.keep_map: {km!r} (нужно on bool, flat_sigma_max и neutral_C_max числа)")
    fg = recipes.get("frame_gate") or {}
    if not isinstance(fg.get("dE_max"), (int, float)) or not isinstance(fg.get("dC_min"), (int, float)) or fg["dE_max"] <= 0 or fg["dC_min"] >= 0:
        bad.append(f"frame_gate: {fg!r} (нужно dE_max > 0 и dC_min < 0)")
    if not isinstance(fg.get("min_mask_px"), int) or fg["min_mask_px"] < 1 or not isinstance(fg.get("mask_alpha_min"), int) or not 1 <= fg["mask_alpha_min"] <= 255:
        bad.append(f"frame_gate: min_mask_px/mask_alpha_min: {fg.get('min_mask_px')!r}/{fg.get('mask_alpha_min')!r} (нужны целые: пикселей ≥ 1, альфа 1…255)")
    if recipes["fallback_class"] not in recipes["recipes"]:
        bad.append("fallback_class без рецепта")
    gt = recipes.get("glass_tone") or {}
    for k in ("photo_max_dE", "alpha_min", "min_pixels", "patch_dilate_px", "highlight_trim", "semi_alpha_max", "dark_L_max"):
        if not isinstance(gt.get(k), (int, float)) or gt[k] < 0:
            bad.append(f"glass_tone.{k}: {gt.get(k)!r}")
    stt = recipes.get("sheen_tint") or {}
    if not isinstance(stt.get("on"), bool) or not isinstance(stt.get("floor"), (int, float)) or not 0 < stt["floor"] <= 1:
        bad.append(f"sheen_tint: {stt!r} (нужно on bool и floor 0..1)")
    pp = recipes.get("part_photo") or {}
    for k in ("iou_min", "inset_px", "min_pixels", "highlight_trim", "dE_apply", "l_spread_max"):
        if not isinstance(pp.get(k), (int, float)) or pp[k] < 0:
            bad.append(f"part_photo.{k}: {pp.get(k)!r}")
    if not isinstance(pp.get("apply"), bool):
        bad.append(f"part_photo.apply: {pp.get('apply')!r} (нужно true/false)")
    for word, cid in recipes["vl_labels"].items():
        if cid not in recipes["recipes"]:
            bad.append(f"vl_labels[{word}] → класс {cid} без рецепта")
    for p in bad:
        print("ОШИБКА:", p)
    print("material_stage check:", "ок" if not bad else f"{len(bad)} замечаний")
    return 1 if bad else 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("stage")
    s.add_argument("--glb", required=True)
    s.add_argument("--run", required=True)
    s.add_argument("--sku", required=True)
    s.add_argument("--product", required=True, help="JSON {sid,name,role,params}")
    s.add_argument("--parts-dir", default=None)
    s.add_argument("--photo", default=None, help="RGBA-вырезка фото магазина: сверка тона стекла у цельностеклянного товара (необязательно)")
    s.add_argument("--stages-dir", default=None, help="папка с 04-camera/ и 06-visible/ (по умолчанию <run>/<sku>)")
    s.add_argument("--no-frame", action="store_true")
    r = sub.add_parser("run")
    r.add_argument("--items", required=True)
    r.add_argument("--run", required=True)
    r.add_argument("--no-frame", action="store_true")
    sub.add_parser("check")
    a = ap.parse_args(argv)
    if a.cmd == "check":
        return check()
    if a.cmd == "stage":
        items = [{"sku": a.sku, "glb": a.glb, "product": json.load(open(a.product, encoding="utf-8")), "parts_dir": a.parts_dir, "photo": a.photo, "stages_dir": a.stages_dir}]
    else:
        items = json.load(open(a.items, encoding="utf-8"))
    bad = 0
    for it in items:
        try:
            d = run_stage(it["glb"], a.run, it["sku"], it["product"], it.get("parts_dir"), not a.no_frame, it.get("photo"), it.get("stages_dir"))
        except Exception as e:  # noqa: BLE001 — счётчик отказов обязателен: падение товара не роняет прогон
            bad += 1
            print(f"ОШИБКА {it['sku']}: {type(e).__name__}: {str(e)[:200]}", file=sys.stderr)
            continue
        print(f"{it['sku']}: {'ok' if d['passed'] else 'НЕ ПРОШЁЛ'} уверенных {d['metric']['value']:.0%} рецепт {d['metrics']['recipe_share']['value']:.0%} {d['seconds']} с {d['reason'][:120]}", flush=True)
        bad += 0 if d["passed"] else 1
    if a.cmd == "run":
        print(_paint_stage().summary(a.run))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
