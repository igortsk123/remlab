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
import struct
import subprocess
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
RECIPES_PATH = os.path.join(ROOT, "data", "flat3d", "material-recipes.json")
STAGE = "08-material"
BLENDER = os.environ.get("BLENDER", os.path.expanduser("~/opt/blender-4.5.9/blender"))
FRAME_SCRIPT = os.path.join(HERE, "material_frame_blender.py")
PROPS = ("roughness", "metallic", "sheen", "transmission")


def _siblings():
    sys.path.insert(0, HERE)
    import material_class as mc
    import material_parts as mp
    return mc, mp


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
        elif str(p.get("role", "")).startswith("shape:") and p is not main:
            r = _shape_class(p, cls, cat, recipes)
        elif p is main:
            r = {"class": cls["class"], "source": "catalog:" + cls["stage"], "confidence": round(cls["confidence"] * conf["main_part_scale"], 2), "reason": cls["reason"]}
            lost = [k for k, v in cat.items() if k not in ("legs", "frame") and v["class"] != cls["class"]]
            if not parts_known and lost:      # в каталоге есть плафон/ручки другого материала, а где они — без частей этапа 3 неизвестно
                r["confidence"] = min(r["confidence"], conf["no_parts_conflict"])
                r["reason"] += "; в каталоге есть " + ", ".join(f"{k} ({cat[k]['class']})" for k in lost) + ", частей этапа 3 нет — где они, не знаем"
        elif main_lab is not None and lab is not None and _de76(lab, main_lab) <= cl["same_material_dE"]:
            r = {"class": cls["class"], "source": "colour≈main", "confidence": conf["same_colour_as_main"],
                 "reason": f"цвет как у главной части (ΔE {_de76(lab, main_lab):.1f})"}
        else:
            why = "нет цвета части" if lab is None else f"цвет отличается от главной части (ΔE {_de76(lab, main_lab):.1f})" if main_lab is not None else "нет цвета главной части"
            r = {"class": fb, "source": "unsure", "confidence": conf["unsure"], "reason": f"нет метки, {why}"}
        r["confident"] = bool(r["confidence"] >= cl["confident_from"])
        out[int(p["id"])] = r
    return out


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
        if p["id"] != main and p.get("role") != "legs" and sh >= share_min:
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
            out[int(p)] = {"lab_median": [round(float(v), 1) for v in np.median(lab[sel], axis=0)], "faces_sampled": int(sel.sum())}
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


def bake_maps(lab: np.ndarray, table: list[str], recipes: dict) -> dict:
    """Растр классов → карты: metallicRoughness (G rough, B metal), sheenColor (серый = сила sheen, sRGB), transmission (R); скаляр sheenRoughness."""
    lut = {p: np.zeros(256, dtype=np.float64) for p in PROPS}
    lut_sr = np.zeros(256, dtype=np.float64)
    for i, cid in enumerate(table, start=1):
        r = recipes["recipes"][cid]
        for p in PROPS:
            lut[p][i] = r[p]
        lut_sr[i] = r["sheenRoughness"]
    lut["roughness"][0] = recipes["recipes"][recipes["fallback_class"]]["roughness"]
    rough, metal, sheen, trans = (lut[p][lab] for p in PROPS)
    to8 = lambda a: np.clip(np.round(a * 255.0), 0, 255).astype(np.uint8)  # noqa: E731
    mr = np.stack([np.full(lab.shape, 255, np.uint8), to8(rough), to8(metal)], axis=-1)
    sheen_srgb = to8(np.power(np.clip(sheen, 0, 1), 1 / 2.2))
    sheen_rgb = np.stack([sheen_srgb] * 3, axis=-1)
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


def patch_glb(src: str, dst: str, maps: dict) -> dict:
    """Копия GLB с новыми картами материала 0: metallicRoughness заменена (на месте), sheenColor и transmission добавлены расширениями. Цвет и геометрия не тронуты."""
    doc, binb = read_glb(src)
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


def run_stage(glb: str, run: str, sku: str, product: dict, parts_dir: str | None = None, frame: bool = True) -> dict:
    """Этап 08 одного товара → `<run>/<sku>/08-material/`. Возвращает check.json (словарь)."""
    ps = _paint_stage()
    mc, mp = _siblings()
    t0 = time.time()
    recipes = load_recipes()
    sdir = ps.stage_dir(run, sku, STAGE)
    fail = lambda why, **kw: ps.write_check(sdir, STAGE, sku, passed=False, reason=why, seconds=time.time() - t0, **kw)  # noqa: E731
    mesh = _load_mesh(glb)
    nf = len(mesh.faces)
    uv = getattr(mesh.visual, "uv", None)
    if uv is None:
        return fail("в модели нет развёртки UV — рецепт некуда запекать", faces=nf)
    rules = mc.load_rules()
    cls = mc.classify(rules, {"role": product.get("role") or "", "name": product.get("name") or "", "params": product.get("params") or {}})
    pdir = parts_dir or os.path.join(run, ps.safe_name(sku), "03-parts")
    npz = os.path.join(pdir, "parts.npz")
    shape_rep = None
    if os.path.exists(npz):
        part = np.load(npz)["part"].astype(np.int64)
        info = json.load(open(os.path.join(pdir, "parts.json"), encoding="utf-8"))
        parts = info["parts"]
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
    res = resolve_parts(parts, cls, recipes, parts_known=True)   # части по этапу 3 или по форме — материалы по ним разведены; «где плафон» не гадаем
    part, inherited = inherit_unseen(mesh, part, list(res))
    fb = recipes["fallback_class"]
    cls_of_face = np.full(nf, fb, dtype=object)
    for pid, r in res.items():
        cls_of_face[part == pid] = r["class"]
    table = class_table(recipes, list(dict.fromkeys(cls_of_face.tolist())))
    label_of = {c: i for i, c in enumerate(table, start=1)}
    face_label = np.array([label_of[c] for c in cls_of_face], dtype=np.int64)
    lab = rasterize_labels(np.asarray(uv, dtype=np.float64), np.asarray(mesh.faces), face_label, recipes["bake"]["mapSize"])
    maps = bake_maps(lab, table, recipes)
    out_glb = os.path.join(sdir, "material.glb")
    pinfo = patch_glb(glb, out_glb, maps)
    covered = part >= 0
    known = np.isin(part, [pid for pid in res])
    recipe_share = float((covered & known).sum()) / nf
    inherited_share = float(inherited.sum()) / nf
    conf_ids = [pid for pid, r in res.items() if r["confident"]]
    confident_share = float(np.isin(part, conf_ids).sum()) / nf
    c = recipes["check"]
    color_same = image_sha(glb, "baseColor") == image_sha(out_glb, "baseColor")
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
    reason = ""
    if frame and not frame_name:
        reason = "кадр не получен: " + why_frame
    elif inherited_share > c["inherited_share_max"]:
        reason = f"{inherited_share:.0%} граней без части (порог {c['inherited_share_max']:.0%}): класс по соседним граням — слишком много угадано"
    elif confident_share < c["confident_share_min"]:
        reason = "не уверен: " + "; ".join(unsure)[:400]
    doc = ps.write_check(
        sdir, STAGE, sku, passed=None if not reason else False,
        metric={"name": "confident_share", "value": round(confident_share, 4), "threshold": c["confident_share_min"], "op": ">="},
        metrics={"recipe_share": {"value": round(recipe_share, 4), "threshold": c["recipe_share_min"], "op": ">="},
                 "inherited_share": {"value": round(inherited_share, 4), "threshold": c["inherited_share_max"], "op": "<="},
                 "color_unchanged": {"value": bool(color_same), "threshold": True, "op": "=="},
                 "geometry_unchanged": {"value": bool(geom_same), "threshold": True, "op": "=="},
                 "seconds": {"value": round(time.time() - t0, 1), "threshold": c["max_seconds"], "op": "<="}},
        reason=reason, seconds=time.time() - t0, outputs=["material.glb"], frame=frame_name,
        faces=nf, parts_source=parts_source, shape=shape_rep, catalog_parts_not_located=not_located, product_class={"class": cls["class"], "stage": cls["stage"], "confidence": cls["confidence"], "reason": cls["reason"], "parts": cls.get("parts")},
        parts=parts_rep, classes=table, sheen=maps["hasSheen"], transmission=maps["hasTransmission"], recipes_sha=recipes_sha(), glb=pinfo)
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
    for cid in recipes["recipes"]:
        if cid not in rules["_byId"]:
            bad.append(f"рецепт {cid}: такого класса нет в material-classes.json")
    if recipes["fallback_class"] not in recipes["recipes"]:
        bad.append("fallback_class без рецепта")
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
        items = [{"sku": a.sku, "glb": a.glb, "product": json.load(open(a.product, encoding="utf-8")), "parts_dir": a.parts_dir}]
    else:
        items = json.load(open(a.items, encoding="utf-8"))
    bad = 0
    for it in items:
        try:
            d = run_stage(it["glb"], a.run, it["sku"], it["product"], it.get("parts_dir"), not a.no_frame)
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
