#!/usr/bin/env python3
"""Маска частей мебели для рендера (render-materials-01, шаг 3, T-20261117-14/3): где у меша ткань/обивка, а где ножки.

ЗАЧЕМ. Меш Hunyuan3D — ОДИН материал на весь предмет. Слой «рогожка» или «велюр» (шаг 4) без маски лёг бы и на деревянные ножки.
Маска по яркости цвета ненадёжна (светлая ножка, тёмная ткань), поэтому части отделяются ГЕОМЕТРИЕЙ меша: ножки — отдельные малые
пятна, которыми предмет стоит на полу; выше они уходят в тело. Не уверены — слой не кладём.

КАК. Меш → занятость сетки (точки на поверхности → клетки; поверхность у мешей НЕ замкнута, поэтому срезы не заливаем). Пятна касания пола
(нижние слои по высоте): одно большое — сплошное основание или цоколь (`whole`: ножек нет, вся поверхность обивка); 2–10 малых — ножки.
Высота разреза — где вне пятен ножек (с запасом расширения) появляется поверхность тела: всё ниже — ножки. Остальное — unsure.

РЕЗУЛЬТАТ на каждый меш — `data/flat3d/material-part-assign.json`: статус (`split` ножки отделены / `whole` вся поверхность обивка /
`unsure` слой не кладём / `skip` не мягкий), уверенность, ПРИЧИНА, высота разреза `cutFrac` (доля высоты меша от низа; грани ниже —
ножки) и следы пятен для проверки глазами. Правила и пороги — `data/flat3d/material-part-rules.json`; ID товаров в код не попадают.
Уверенность сверяется с товаром: есть ли у него «материал ножек» (`material-class-assign.json: parts.legs`) — согласие поднимает, спор снижает.

Запуск (из корня репо, нужны numpy, scipy, trimesh):
    python3 tools/assets/material_parts.py build --mesh-dir <папка с <id>.glb> [--fetch-missing] [--report out.md]
    python3 tools/assets/material_parts.py check     # правила целы, результат собран по этим правилам, форма записей (CI)
Применение (шаг 4): `legs_face_mask(mesh, rec)` — маска граней ножек; при `status` ∉ {split, whole} или уверенность < `confidence.apply` слой не кладём.
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
import os
import sys
import urllib.request

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
RULES_PATH = os.path.join(ROOT, "data", "flat3d", "material-part-rules.json")
CLASSES_PATH = os.path.join(ROOT, "data", "flat3d", "material-classes.json")
CLASS_ASSIGN_PATH = os.path.join(ROOT, "data", "flat3d", "material-class-assign.json")
ASSIGN_PATH = os.path.join(ROOT, "data", "flat3d", "material-part-assign.json")
PROD = "https://remont-lab.online/test/mesh-pilot10/{id}/model.glb"
STATUSES = ("split", "whole", "unsure", "skip")


def load_rules(path: str = RULES_PATH) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def rules_sha(path: str = RULES_PATH) -> str:
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()[:16]


def _occupancy(mesh, grid: dict) -> tuple[np.ndarray, float, np.ndarray]:
    """Занятость сетки [x, y, z]: точки на поверхности → клетки (без заливки: поверхность меша не замкнута). Возвращает (сетка, шаг, низ меша)."""
    lo, ext = mesh.bounds[0], mesh.extents
    pitch = float(ext.max()) / grid["cellsAlongLongestSide"]
    n_pts = int(max(20000, grid["surfacePointsPerCell"] * mesh.area / (pitch * pitch)))
    pts, _ = _sample(mesh, n_pts, grid["seed"])
    pts = np.vstack([pts, mesh.vertices])
    shape = np.maximum(1, np.ceil(ext / pitch).astype(int) + 1)
    idx = np.minimum(np.floor((pts - lo) / pitch).astype(int), shape - 1)
    occ = np.zeros(tuple(shape), dtype=bool)
    occ[idx[:, 0], idx[:, 1], idx[:, 2]] = True
    return occ, pitch, lo


def _sample(mesh, count: int, seed: int):
    import trimesh

    return trimesh.sample.sample_surface(mesh, count, seed=seed)[:2]


def analyze(mesh, rules: dict) -> dict:
    """Геометрия меша → запись маски ножек: status (split/whole/unsure), confidence БЕЗ учёта товара, причина, cutFrac, следы пятен."""
    from scipy import ndimage

    g, lg = rules["grid"], rules["legs"]
    occ, pitch, lo = _occupancy(mesh, g)
    nx, ny, nz = occ.shape
    ext = mesh.extents
    metrics = {"layers": ny, "pitchCm": round(pitch * 100, 2)}
    if ny < 12:
        return {"status": "unsure", "why": "меш слишком низкий для разбора по высоте", "metrics": metrics}
    # «плита-тень»: у части мешей снизу запечён плоский лист (тень на полу) — слой клеток во весь размер, в разы плотнее слоёв над ним; он не предмет
    cnt = occ.sum(axis=(0, 2)).astype(float)
    plate = 0
    while plate < lg["plateMaxLayers"] and plate + 4 < ny and cnt[plate] >= lg["plateFactor"] * max(1.0, float(cnt[plate + 2: plate + 5].mean())):
        plate += 1
    if plate:
        metrics["plateLayers"] = plate
    # пятна касания пола: поверхность в нижних слоях (над плитой), чуть расширенная (разрыв в 1 клетку не делит пятно)
    floor = occ[:, plate: plate + lg["floorLayers"], :].any(axis=1)
    lab, n = ndimage.label(ndimage.binary_dilation(floor, iterations=lg["floorDilate"]))
    islands = []
    for k in range(1, n + 1):
        xs, zs = np.where(lab == k)
        islands.append({"id": k, "x0": int(xs.min()), "x1": int(xs.max()) + 1, "z0": int(zs.min()), "z1": int(zs.max()) + 1, "cells": int(len(xs))})
    if not islands:
        return {"status": "unsure", "why": "у пола нет поверхности — меш не стоит на полу", "metrics": metrics}
    for i in islands:
        i["sx"], i["sz"] = (i["x1"] - i["x0"]) / nx, (i["z1"] - i["z0"]) / nz
    plinth_spans = [min(i["sx"], i["sz"]) for i in islands]
    metrics["maxIslandSpanPct"] = round(100 * max(max(i["sx"], i["sz"]) for i in islands))
    # одно большое пятно (цоколь, сплошное днище, юбка по периметру: широкое в ОБЕ стороны) — ножек нет, вся поверхность обивка
    if max(plinth_spans) >= lg["plinthSpanFrac"]:
        # крестовина или диск у пола с узкой опорой над ним — не цоколь: выше пола поверхность должна оставаться такой же широкой
        probe = occ[:, min(ny - 1, plate + lg["plinthProbeLayer"]), :]
        if probe.any():
            xs, zs = np.where(probe)
            pspan = max((xs.max() + 1 - xs.min()) / nx, (zs.max() + 1 - zs.min()) / nz)
            metrics["probeSpanPct"] = round(100 * pspan)
            if pspan < lg["plinthProbeSpanFrac"]:
                return {"status": "unsure", "why": f"у пола широкое пятно, а чуть выше опора уже ({metrics['probeSpanPct']}% размера) — крестовина или диск, не цоколь", "metrics": metrics}
        return {"status": "whole", "metrics": metrics}
    # узкая и длинная полоса (изголовье, боковина, спинка до пола) — часть тела, не ножка и не цоколь: из подсчёта ножек выходит, но зона вокруг неё не «тело»
    panels = [i for i in islands if max(i["sx"], i["sz"]) > lg["maxLegSpanFrac"] and min(i["sx"], i["sz"]) <= lg["panelThinFrac"]]
    legs = [i for i in islands if i not in panels]
    metrics["islands"] = len(legs)
    if panels:
        metrics["panels"] = len(panels)
    if any(max(i["sx"], i["sz"]) > lg["maxLegSpanFrac"] for i in legs):
        return {"status": "unsure", "why": f"у пола {len(legs)} пятен, среди них средние по размеру — не похоже на ножки", "metrics": metrics}
    if not (lg["minIslands"] <= len(legs) <= lg["maxIslands"]):
        return {"status": "unsure", "why": f"у пола {len(legs)} пятен (ножек ждём {lg['minIslands']}–{lg['maxIslands']})", "metrics": metrics}
    islands = legs
    total = sum(i["cells"] for i in islands) / float(nx * nz)
    metrics["legFootprintPct"] = round(100 * total, 1)
    if total > lg["maxLegFootprintFrac"]:
        return {"status": "unsure", "why": f"пятна у пола занимают {metrics['legFootprintPct']}% основания — для ножек много", "metrics": metrics}
    # высота разреза: первый слой, где ВНЕ ножек (пятна + запас) появляется поверхность тела
    legs_zone = ndimage.binary_dilation(lab > 0, iterations=lg["legMargin"])
    out = (occ & ~legs_zone[:, None, :]).sum(axis=(0, 2))
    out[:plate] = 0                       # плита-тень не тело
    need = max(lg["bodyStartMinCells"], int(lg["bodyStartFootprintFrac"] * nx * nz))
    start = next((y for y in range(ny) if out[y] >= need), None)
    if start is None:
        return {"status": "unsure", "why": "тело предмета над ножками не найдено", "metrics": metrics}
    metrics["bodyStartPct"] = round(100 * start / ny)
    if start < lg["minLegLayers"]:
        return {"status": "unsure", "why": f"тело начинается в {start} слоях от пола — ножки неразличимы", "metrics": metrics}
    if start / ny > lg["maxBodyStartFrac"]:
        return {"status": "unsure", "why": f"тело начинается слишком высоко ({metrics['bodyStartPct']}% высоты) — это не ножки", "metrics": metrics}
    boxes = [[round(i["x0"] * pitch / float(ext[0]), 3), round(i["x1"] * pitch / float(ext[0]), 3),
              round(i["z0"] * pitch / float(ext[2]), 3), round(i["z1"] * pitch / float(ext[2]), 3)] for i in islands]
    cut = (start - lg["cutMarginLayers"]) * pitch / float(ext[1])
    # дно тела: слой, где вне ножек поверхности уже ≥ `bodyBottomFrac` от её максимума (подушка сиденья, днище). Между `cutFrac` и дном — рейки,
    # царги или юбка: по геометрии не отличить дерево от обивки, поэтому эта полоса — нейтральная (слой не кладём)
    big = next((y for y in range(start, ny) if out[y] >= lg["bodyBottomFrac"] * float(out.max())), start)
    band = max(0, big - start)
    top = cut
    if band >= lg["bandMinLayers"]:
        top = (big - lg["cutMarginLayers"]) * pitch / float(ext[1])
        metrics["bandPct"] = round(100 * band / ny)
    return {"status": "split", "cutFrac": round(float(cut), 4), "bandTopFrac": round(float(top), 4), "islands": len(islands),
            "footprintBoxes": boxes, "metrics": metrics}


def judge(rec: dict, rules: dict, product_has_legs: bool | None) -> dict:
    """Дописывает уверенность (с учётом товара) и причину; слой кладётся только при уверенности ≥ `confidence.apply`."""
    c, r = rules["confidence"], rules["reasons"]
    m = rec.get("metrics", {})
    conf = 0.0
    if rec["status"] == "split":
        conf = c["splitBase"]
        lo, hi = c["splitIslandsTypical"]
        if lo <= rec["islands"] <= hi:
            conf += c["splitIslandsBonus"]
        if product_has_legs is True:
            conf += c["splitProductAgreesBonus"]
        rec["reason"] = r["split"].format(islands=rec["islands"], bodyStartPct=m.get("bodyStartPct"))
        if m.get("bandPct"):
            rec["reason"] += r["splitBand"].format(bandPct=m["bandPct"])
    elif rec["status"] == "whole":
        conf = c["wholeBase"]
        if product_has_legs is True:      # товар называет материал ножек, а геометрия их не показывает — спор, слой не кладём
            conf -= c["wholeProductDisagreesPenalty"]
        rec["reason"] = r["whole"].format(spanPct=m.get("maxIslandSpanPct"))
        if product_has_legs is True:
            rec["reason"] += r["wholeProductLegs"]
    elif rec["status"] == "unsure":
        rec["reason"] = r["unsure"].format(why=rec.pop("why", "—"))
    rec["confidence"] = round(max(0.0, min(1.0, conf)), 2)
    rec["productHasLegs"] = product_has_legs
    rec["apply"] = rec["status"] in ("split", "whole") and rec["confidence"] >= c["apply"]
    return rec


def _real_longest_cm(rules: dict, role: str | None, mesh_id: str | None, catalog: dict) -> tuple[float, str]:
    """Реальный размер большей стороны предмета, см: из каталога (`data/flat3d/furniture.json`, если меш там есть), иначе приор по роли из правил.
    Меш нормирован (большая сторона ≈ 2,0), поэтому порог «тонкого» в см переводится в единицы меша через этот размер."""
    dims = catalog.get(mesh_id or "")
    if dims:
        return float(max(dims)), "catalog"
    t = rules["thin"]
    return float(t["longestSideCm"].get(role or "", t["defaultLongestCm"])), "role"


def _catalog_dims() -> dict:
    p = os.path.join(ROOT, "data", "flat3d", "furniture.json")
    out: dict[str, tuple] = {}
    try:
        for o in json.load(open(p, encoding="utf-8")).get("options", []):
            a = o.get("asset") or {}
            if a.get("meshId") and a.get("wCm") and a.get("dCm") and a.get("hCm"):
                out[a["meshId"]] = (a["wCm"], a["dCm"], a["hCm"])
    except OSError:
        pass
    return out


def _clean_thin(mesh, mask: np.ndarray, thr: float, t: dict) -> np.ndarray:
    """Чистка: мажоритарный фильтр по соседним граням (крапинки у кромок пропадают), мелкие пятна — прочь, листовые пятна (сиденье, панель:
    плоские и сплошные) — не стойки и не рама, их не берём. Остаются стержни (мало в сечении) и решётки/рамы (плоские, но пустые внутри)."""
    from scipy import sparse
    from scipy.sparse.csgraph import connected_components

    adj = mesh.face_adjacency
    nf = len(mesh.faces)
    a = sparse.coo_matrix((np.ones(len(adj)), (adj[:, 0], adj[:, 1])), shape=(nf, nf))
    a = (a + a.T).tocsr()
    deg = np.maximum(1, np.asarray(a.sum(axis=1)).ravel())
    m = mask.copy()
    for _ in range(t["smoothIters"]):
        m = (a @ m.astype(float)) / deg >= t["majority"]
    area = mesh.area_faces
    total = float(area.sum())
    sub = a[m][:, m]
    n, lab = connected_components(sub, directed=False)
    idx = np.where(m)[0]
    keep = np.zeros(nf, dtype=bool)
    for c in range(n):
        ids = idx[lab == c]
        if float(area[ids].sum()) >= t["minPatchAreaFrac"] * total:
            keep[ids] = True
    return keep


def _bounded_width(pts: np.ndarray, nrm: np.ndarray, tree, mid: np.ndarray, cand: np.ndarray, thr: float, tol: float, t: dict, seed: int) -> np.ndarray:
    """Отличает стойку/рейку/раму от края сплошной массы: из середины тонкой стенки идём по касательным направлениям в обе стороны;
    у стержня и узкой планки найдётся направление, где материал заканчивается (встречная стенка) и туда, и сюда в пределах `boundedWidthMul`·порога.
    У сужающегося края сиденья или подушки в сторону массы материал не кончается — такая «тонкость» отпадает. Считаем по выборке (`boundedSampleCap`)."""
    from scipy.spatial import cKDTree

    ids = np.where(cand)[0]
    if len(ids) == 0:
        return cand
    rng = np.random.default_rng(seed)
    pick = ids if len(ids) <= t["boundedSampleCap"] else rng.choice(ids, t["boundedSampleCap"], replace=False)
    n = nrm[pick]
    ref = np.where(np.abs(n[:, [1]]) < 0.9, np.array([[0.0, 1.0, 0.0]]), np.array([[1.0, 0.0, 0.0]]))
    u1 = np.cross(n, ref)
    u1 /= np.maximum(np.linalg.norm(u1, axis=1, keepdims=True), 1e-9)
    u2 = np.cross(n, u1)
    m = mid[pick]
    reach = thr * t["boundedWidthMul"]
    steps = t["boundedSteps"]
    bounded = np.zeros(len(pick), dtype=bool)
    for ang in np.linspace(0.0, np.pi, t["boundedAngles"], endpoint=False):
        u = np.cos(ang) * u1 + np.sin(ang) * u2
        both = []
        for sgn in (1.0, -1.0):
            hit = np.zeros(len(pick), dtype=bool)
            for k in range(1, steps + 1):
                d, j = tree.query(m + sgn * u * (reach * k / steps), distance_upper_bound=tol)
                ok = np.isfinite(d)
                jj = np.where(ok, j, 0)
                hit |= ok & ((nrm[jj] * (sgn * u)).sum(axis=1) > t["opposingDot"])     # стенка, чья наружная нормаль смотрит ВДОЛЬ луча = выход из материала
            both.append(hit)
        bounded |= both[0] & both[1]
    sel = cKDTree(pts[pick])
    _, nn = sel.query(pts[ids])
    out = np.zeros(len(pts), dtype=bool)
    out[ids] = bounded[nn]
    return out


def thin_face_mask(mesh, rules: dict, longest_cm: float) -> tuple[np.ndarray, dict]:
    """Грани ТОНКИХ частей (стойка, рейка, рама, стержень толщиной < `thin.thinCm`): по локальной толщине меша, на любой высоте.
    Толщина точки поверхности — расстояние вглубь (против нормали) до противоположной стенки с обратной нормалью; не найдена в пределах порога —
    часть объёмная. Поверхность не замкнута, поэтому лучи не бросаем — ищем стенку по облаку точек (KD-дерево)."""
    from scipy.spatial import cKDTree

    t = rules["thin"]
    ext = float(mesh.extents.max())
    thr = t["thinCm"] / float(longest_cm) * ext
    spacing = thr / t["spacingDiv"]
    n = int(min(t["maxSamples"], max(20000, mesh.area / (spacing * spacing))))
    pts, fidx = _sample(mesh, n, rules["grid"]["seed"])
    nrm = np.asarray(mesh.face_normals)[fidx]
    tree = cKDTree(pts)
    tol = max(spacing, thr / t["steps"]) * t["tolMul"]

    def probe_thin(sign: float) -> tuple[np.ndarray, np.ndarray]:
        out = np.zeros(len(pts), dtype=bool)
        depth = np.zeros(len(pts))
        for k in range(1, t["steps"] + 1):
            d, j = tree.query(pts - sign * nrm * (thr * k / t["steps"]), distance_upper_bound=tol)
            ok = np.isfinite(d)
            jj = np.where(ok, j, 0)
            hit = ok & ((nrm[jj] * nrm).sum(axis=1) < -t["opposingDot"]) & ~out
            depth[hit] = thr * k / t["steps"]
            out |= hit
        return out, depth

    # намотка граней у открытых мешей ненадёжна (знак объёма врёт): «вглубь» — то направление, где тонких точек больше
    (inward, din), (outward, dout) = probe_thin(1.0), probe_thin(-1.0)
    if inward.sum() >= outward.sum():
        thin_pt, depth, sign = inward, din, 1.0
    else:
        thin_pt, depth, sign = outward, dout, -1.0
    mid = pts - sign * nrm * (depth[:, None] / 2.0)
    if t["boundedAngles"]:
        thin_pt = _bounded_width(pts, nrm, tree, mid, thin_pt, thr, tol * t["boundedTolMul"], t, rules["grid"]["seed"])
    # тонкость грани — по её собственным точкам (большая грань: ближайшая точка может лежать на соседней); без точек — по ближайшей
    cnt = np.bincount(fidx, minlength=len(mesh.faces)).astype(float)
    hit = np.bincount(fidx, weights=thin_pt.astype(float), minlength=len(mesh.faces))
    _, near = tree.query(mesh.triangles_center)
    face_thin = np.where(cnt > 0, hit >= 0.5 * np.maximum(cnt, 1.0), thin_pt[near])
    mask = _clean_thin(mesh, face_thin, thr, t)
    area = mesh.area_faces
    info = {"thinCm": t["thinCm"], "longestCm": round(float(longest_cm)), "thinAreaPct": round(100.0 * float(area[mask].sum()) / float(area.sum()), 1)}
    return mask, info


def _below_cut(mesh, rec: dict) -> np.ndarray:
    lo, hi = mesh.bounds[0][1], mesh.bounds[1][1]
    return mesh.triangles_center[:, 1] <= lo + rec["cutFrac"] * (hi - lo)


def _in_leg_footprint(mesh, rec: dict, margin: float = 0.02) -> np.ndarray:
    """Центр грани (в плане) попадает в пятно одной из ножек (+ запас в долях размера). Панель у пола (изголовье, боковина) — не ножка."""
    b0, ext = mesh.bounds[0], mesh.extents
    c = mesh.triangles_center
    fx = (c[:, 0] - b0[0]) / float(ext[0])
    fz = (c[:, 2] - b0[2]) / float(ext[2])
    ok = np.zeros(len(c), dtype=bool)
    for x0, x1, z0, z1 in rec.get("footprintBoxes", []):
        ok |= (fx >= x0 - margin) & (fx <= x1 + margin) & (fz >= z0 - margin) & (fz <= z1 + margin)
    return ok


def legs_face_mask(mesh, rec: dict) -> np.ndarray:
    """Маска граней ножек: ниже высоты разреза И над пятном ножки у пола. Не split — пусто."""
    if rec.get("status") != "split":
        return np.zeros(len(mesh.faces), dtype=bool)
    return _below_cut(mesh, rec) & _in_leg_footprint(mesh, rec)


def neutral_face_mask(mesh, rec: dict, thin: np.ndarray | None = None) -> np.ndarray:
    """Нейтральное — слой не кладём: тонкие части на любой высоте (`thin` — из `thin_face_mask`), для split ещё полоса между ножками и телом
    (рейки, царги, юбка) и низ панелей, стоящих на полу (изголовье, боковина: ниже разреза, но не над пятном ножки). Ножки (красные) не входят."""
    neu = np.zeros(len(mesh.faces), dtype=bool) if thin is None else np.asarray(thin, dtype=bool).copy()
    if rec.get("status") == "split":
        lo, hi = mesh.bounds[0][1], mesh.bounds[1][1]
        y = mesh.triangles_center[:, 1]
        top = max(rec.get("bandTopFrac", rec["cutFrac"]), rec["cutFrac"])
        neu |= ((y > lo + rec["cutFrac"] * (hi - lo)) & (y <= lo + top * (hi - lo))) | (_below_cut(mesh, rec) & ~_in_leg_footprint(mesh, rec))
    return neu & ~legs_face_mask(mesh, rec)


def upholstery_face_mask(mesh, rec: dict, thin: np.ndarray | None = None) -> np.ndarray:
    """Грани, на которые кладётся слой обивки: не ножки и не нейтральное (при `apply: false` слой не кладётся совсем)."""
    return ~(legs_face_mask(mesh, rec) | neutral_face_mask(mesh, rec, thin))


def _family_of(cls: str | None, classes: dict) -> str | None:
    return next((c["family"] for c in classes["classes"] if c["id"] == cls), None)


def load_mesh(path: str):
    import trimesh

    m = trimesh.load(path, force="mesh", process=False)
    return m


def _fetch(mid: str, cache: str) -> str | None:
    p = os.path.join(cache, mid + ".glb")
    if os.path.exists(p) and os.path.getsize(p) > 1000:
        return p
    try:
        req = urllib.request.Request(PROD.format(id=mid), headers={"user-agent": "material-parts"})
        with urllib.request.urlopen(req, timeout=60) as r, open(p, "wb") as f:
            f.write(r.read())
        return p
    except Exception as e:  # noqa: BLE001 — сеть: нет меша → запись unsure, прогон идёт дальше
        print(f"  нет меша {mid}: {str(e)[:80]}", file=sys.stderr)
        return None


def build(mesh_dirs: list[str], fetch: bool, only: set[str] | None, report: str | None) -> dict:
    rules = load_rules()
    classes = json.load(open(CLASSES_PATH, encoding="utf-8"))
    cls = json.load(open(CLASS_ASSIGN_PATH, encoding="utf-8"))["meshes"]
    out: dict[str, dict] = {}
    catalog = _catalog_dims()
    for mid in sorted(cls):
        if only and mid not in only:
            continue
        a = cls[mid]
        fam = _family_of(a.get("class"), classes)
        if fam not in rules["appliesToFamilies"]:
            out[mid] = {"status": "skip", "reason": rules["reasons"]["skip"].format(**{"class": a.get("class")}), "confidence": 1.0, "apply": False,
                        "productHasLegs": None, "role": a.get("role"), "class": a.get("class")}
            continue
        path = next((os.path.join(d, mid + ".glb") for d in mesh_dirs if os.path.exists(os.path.join(d, mid + ".glb"))), None)
        if not path and fetch:
            path = _fetch(mid, mesh_dirs[0])
        if not path:
            out[mid] = {"status": "unsure", "reason": "меш не найден в кэше — маска не считалась", "confidence": 0.0, "apply": False,
                        "productHasLegs": None, "role": a.get("role"), "class": a.get("class")}
            continue
        mesh = load_mesh(path)
        rec = analyze(mesh, rules)
        rec = judge(rec, rules, True if "legs" in (a.get("parts") or {}) else None)   # нет строки «материал ножек» — данных нет, не «ножек нет»
        rec["role"], rec["class"] = a.get("role"), a.get("class")
        if rec["status"] in ("split", "whole"):
            longest, src = _real_longest_cm(rules, a.get("role"), mid, catalog)
            _, info = thin_face_mask(mesh, rules, longest)
            info["scaleSource"] = src
            rec["thin"] = info
            rec["reason"] += rules["reasons"]["thin"].format(thinCm=info["thinCm"], thinAreaPct=info["thinAreaPct"])
        out[mid] = rec
        del mesh
        gc.collect()          # меши и облака точек большие: без явной сборки память растёт от меша к мешу (пик 23 ГБ на 170 мешах)
        print(f"  {mid}  {a.get('role'):10s} {rec['status']:6s} {rec['confidence']:.2f}  {rec['reason'][:90]}")
    doc = {"_about": "Собрано tools/assets/material_parts.py build по data/flat3d/material-part-rules.json — руками не править.",
           "rulesSha": rules_sha(), "meshes": out}
    if only is None:
        with open(ASSIGN_PATH, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=1, sort_keys=True)
            f.write("\n")
    if report:
        _report(doc, report)
    return doc


def _report(doc: dict, path: str) -> None:
    rows = doc["meshes"]
    by = {}
    for r in rows.values():
        by.setdefault((r.get("role") or "—", r["status"]), 0)
        by[(r.get("role") or "—", r["status"])] += 1
    lines = ["# Маска частей: охват", "", f"Всего мешей: {len(rows)}; правила `{doc['rulesSha']}`", "", "| роль | статус | число |", "|---|---|---|"]
    for (role, st), n in sorted(by.items()):
        lines.append(f"| {role} | {st} | {n} |")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def check() -> int:
    rules = load_rules()
    bad: list[str] = []
    if not os.path.exists(ASSIGN_PATH):
        bad.append("нет material-part-assign.json — запустить build")
    else:
        doc = json.load(open(ASSIGN_PATH, encoding="utf-8"))
        if doc.get("rulesSha") != rules_sha():
            bad.append("правила изменились после сборки результата — пересобрать build")
        cls = json.load(open(CLASS_ASSIGN_PATH, encoding="utf-8"))["meshes"]
        for mid, rec in doc["meshes"].items():
            if mid not in cls:
                bad.append(f"{mid}: нет в material-class-assign.json")
            if rec["status"] not in STATUSES or not rec.get("reason"):
                bad.append(f"{mid}: статус/причина")
            if rec["status"] == "split" and not (0 < rec["cutFrac"] < rules["legs"]["maxBodyStartFrac"] + 0.05):
                bad.append(f"{mid}: cutFrac вне границ")
            if rec.get("apply") and rec["confidence"] < rules["confidence"]["apply"]:
                bad.append(f"{mid}: apply при низкой уверенности")
    for b in bad:
        print("ОШИБКА:", b)
    print("ok" if not bad else f"{len(bad)} ошибок")
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--mesh-dir", action="append", required=True, help="папка с <id>.glb (первая — кэш для --fetch-missing)")
    b.add_argument("--fetch-missing", action="store_true", help="недостающие меши — с прода (0 ₽)")
    b.add_argument("--only", default="", help="через запятую: только эти id (файл результата не пишется)")
    b.add_argument("--report", default=None)
    sub.add_parser("check")
    a = ap.parse_args()
    if a.cmd == "check":
        return check()
    build([os.path.expanduser(d) for d in a.mesh_dir], a.fetch_missing, set(a.only.split(",")) if a.only else None, a.report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
