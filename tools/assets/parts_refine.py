"""Доводка частей этапа 3 (paint-photo-fill-01, T-20261121-169/2): тонкие стойки — отдельно от объёмных частей, пёстрые мелкие куски — по цвету в соседа.

ЗАЧЕМ. SAM2 по кадрам иногда склеивает тонкую ножку/стойку/царгу с обивкой (одна красная часть у спинки и задней ножки кресла) и рвёт край на мозаику из мелких кусков
одного цвета. Заливка невидимого (этап 7) идёт строго внутри части: склеенная ножка получит цвет обивки, мозаика — разные цвета. Общее правило на все типы мебели, без ID товаров:
  ① форма: грани каждой части классифицируются `part_shapes.face_shapes` (linear — тонкая стойка/трубка, planar — панель, blob — объём; доли наибольшего габарита);
     в части, где большинство граней НЕ linear, связные куски linear-граней (от `thin_min_share` всех граней) уходят в новую часть — «тонкая»;
  ② цвет: малая часть (< `colour_merge_max_share`) того же вида (тонкая с тонкой, объёмная с объёмной) и почти того же цвета (ΔE76 медианы Lab < `colour_merge_de`)
     вливается в соседа с самой длинной общей границей; потом малые (< `region.min_part_face_share`) — в соседа того же вида по границе.
Мерка `linear_in_blob_part_share` — доля linear-граней, оставшихся в объёмной части (до и после доводки); в check.json этапа 3.
Пороги доводки — `data/flat3d/parts-sam-rules.json` → `refine`; пороги формы — `data/flat3d/material-recipes.json` → `geometry` (общие с этапом 08, `load_shape_cfg`).
"""
from __future__ import annotations

import json
import os

import numpy as np

import part_shapes as shp

RECIPES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "flat3d", "material-recipes.json")


def load_shape_cfg(path: str = RECIPES) -> dict:
    """Пороги формы — ТОТ ЖЕ блок `geometry` в material-recipes.json, что читает этап 08 (один источник истины; р.7 и этап 3 видят одни числа)."""
    return json.load(open(path, encoding="utf-8"))["geometry"]


def shape_cfg(rules: dict, path: str = RECIPES) -> dict:
    """Общие пороги формы + ТОЛЬКО перечисленные в `refine.shape_override` (радиус и отношение для мебельных ножек: на мебели радиус 0.05·L даёт 0 linear-граней
    даже у тонких ножек — замер T-169/2 на кресле: см. отчёт; прочие ключи — строго общие)."""
    return {**load_shape_cfg(path), **rules["refine"].get("shape_override", {})}


def _onehot(part: np.ndarray, n: int):
    from scipy import sparse

    lab = np.nonzero(part >= 0)[0]
    return sparse.csr_matrix((np.ones(len(lab), dtype=np.float32), (lab, part[lab])), shape=(len(part), n))


def part_kinds(part: np.ndarray, kind: np.ndarray, linear_majority: float = 0.5) -> dict[int, str]:
    """Вид части: thin — большинство граней linear; иначе body."""
    out = {}
    for p in np.unique(part[part >= 0]):
        out[int(p)] = "thin" if float((kind[part == p] == shp.LINEAR).mean()) >= linear_majority else "body"
    return out


def linear_in_blob_share(part: np.ndarray, kind: np.ndarray, linear_majority: float = 0.5, min_part_share: float = 0.10) -> float:
    """Доля linear-граней, лежащих в КРУПНОЙ объёмной части (от `min_part_share` всех граней, linear в ней — меньшинство): ножка/стойка в одной части с обивкой.
    Малые части (подлокотник, ручка) не считаются: они уже отдельные, даже если у них часть граней linear."""
    lin = (kind == shp.LINEAR) & (part >= 0)
    if not lin.any():
        return 0.0
    kinds = part_kinds(part, kind, linear_majority)
    is_body = np.zeros(int(part.max()) + 1, dtype=bool)
    for p, k in kinds.items():
        is_body[p] = k == "body" and float((part == p).mean()) >= min_part_share
    return round(float(is_body[part[lin]].mean()), 4)


def split_thin(part: np.ndarray, kind: np.ndarray, adj, rules: dict) -> np.ndarray:
    """Связные куски linear-граней в объёмной части (от `thin_min_share` всех граней) — в новые части."""
    from scipy.sparse.csgraph import connected_components

    rf = rules["refine"]
    part = part.copy()
    nf = len(part)
    minf = max(1, int(round(rf["thin_min_share"] * nf)))
    kinds = part_kinds(part, kind)
    nxt = int(part.max()) + 1
    for p, k in kinds.items():
        if k != "body" or float((part == p).mean()) < rf["thin_split_min_part_share"]:
            continue                                                             # малую часть (подлокотник, ручка) не режем: она уже отдельная
        sel = (part == p) & (kind == shp.LINEAR)
        if sel.sum() < minf:
            continue
        idx = np.nonzero(sel)[0]
        sub = adj[idx][:, idx]
        n, lab = connected_components(sub, directed=False)
        for c in range(n):
            members = idx[lab == c]
            if len(members) >= minf:
                part[members] = nxt
                nxt += 1
    return part


def _part_lab_median(part: np.ndarray, lab: np.ndarray) -> dict[int, np.ndarray]:
    return {int(p): np.median(lab[part == p], axis=0) for p in np.unique(part[part >= 0])}


def merge_small(part: np.ndarray, kind: np.ndarray, adj, lab: np.ndarray | None, rules: dict, max_share: float, de_max: float | None,
                agree: np.ndarray | None = None, seen: np.ndarray | None = None) -> np.ndarray:
    """Малая часть → сосед того же вида с самой длинной общей границей; при `de_max` — только если цвет соседа близок (ΔE76 медианы Lab < de_max).
    Если даны `agree`/`seen` — сливаются только НЕНАДЁЖНЫЕ части («мозаика»: среднее согласие кадров по увиденным граням < `refine.agree_merge_max`
    или увиденных граней < `refine.min_seen_share`): настоящая малая часть (подлокотник, ножка) кадры согласованно видят, её цвет схож с соседом, но сливать нельзя."""
    part = part.copy()
    nf = len(part)
    for _ in range(200):
        ids = np.unique(part[part >= 0])
        if len(ids) < 2:
            break
        remap = {int(p): i for i, p in enumerate(ids)}
        dense = np.array([remap.get(int(x), -1) for x in part])
        oh = _onehot(dense, len(ids))
        bnd = (oh.T @ adj @ oh).toarray()
        np.fill_diagonal(bnd, 0)
        size = np.asarray(oh.sum(axis=0)).ravel() / nf
        kinds = part_kinds(dense, kind)
        med = _part_lab_median(dense, lab) if (lab is not None and de_max is not None) else None
        changed = False
        for i in np.argsort(size):
            if size[i] >= max_share:
                break
            if agree is not None and seen is not None:
                m_i = dense == i
                sn = m_i & seen
                rf_ = rules["refine"]
                weak = (sn.sum() < rf_["min_seen_share"] * m_i.sum()) or float(agree[sn].mean()) < rf_["agree_merge_max"]
                if not weak:
                    continue
            cand = [j for j in np.argsort(-bnd[i]) if bnd[i, j] > 0 and kinds.get(int(j)) == kinds.get(int(i))]
            if med is not None:
                cand = [j for j in cand if float(np.linalg.norm(med[int(i)] - med[int(j)])) < de_max]
            if not cand:
                continue
            part[dense == i] = ids[cand[0]]
            changed = True
            break                                                                # после слияния размеры изменились — пересчёт
        if not changed:
            break
    return part


def refine(part: np.ndarray, vertices: np.ndarray, faces: np.ndarray, adj, lab_face: np.ndarray | None, rules: dict,
           agree: np.ndarray | None = None, seen: np.ndarray | None = None) -> tuple[np.ndarray, dict]:
    """Доводка: срез тонкого → слияние пёстрых по цвету → малые в соседа. Возвращает (новые части без дыр в нумерации, отчёт с меркой)."""
    from parts_vote import renumber

    kind, up, rep = shp.face_shapes(vertices, faces, shape_cfg(rules))
    rf = rules["refine"]
    before = linear_in_blob_share(part, kind, 0.5, rf["thin_split_min_part_share"])
    n_before = int(len(np.unique(part[part >= 0])))
    new = split_thin(part, kind, adj, rules)
    n_split = int(len(np.unique(new[new >= 0]))) - n_before
    new = merge_small(new, kind, adj, lab_face, rules, rf["colour_merge_max_share"], rf["colour_merge_de"] if lab_face is not None else None, agree, seen)
    new = merge_small(new, kind, adj, None, rules, rules["region"]["min_part_face_share"], None)
    new = renumber(new)
    after = linear_in_blob_share(new, kind, 0.5, rf["thin_split_min_part_share"])
    report = {"shape_share": rep["share"], "linear_in_blob_part_share_before": before, "linear_in_blob_part_share": after,
              "parts_before": n_before, "parts_split_off": n_split, "parts_after": int(len(np.unique(new[new >= 0])))}
    return new, report
