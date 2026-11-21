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


def _face_areas(vertices: np.ndarray, faces: np.ndarray) -> np.ndarray:
    v = np.asarray(vertices, np.float64)
    f = np.asarray(faces)
    return 0.5 * np.linalg.norm(np.cross(v[f[:, 1]] - v[f[:, 0]], v[f[:, 2]] - v[f[:, 0]]), axis=1)


def _onehot(part: np.ndarray, n: int):
    from scipy import sparse

    lab = np.nonzero(part >= 0)[0]
    return sparse.csr_matrix((np.ones(len(lab), dtype=np.float32), (lab, part[lab])), shape=(len(part), n))


def part_kinds(part: np.ndarray, kind: np.ndarray, linear_majority: float = 0.5, mid_share: float = 0.15) -> dict[int, str]:
    """Вид части: thin — большинство граней linear (ножка, стойка); mid — заметная доля linear (подлокотник, звено царги); иначе body (объём)."""
    out = {}
    for p in np.unique(part[part >= 0]):
        sh = float((kind[part == p] == shp.LINEAR).mean())
        out[int(p)] = "thin" if sh >= linear_majority else ("mid" if sh >= mid_share else "body")
    return out


def compatible(a: str | None, b: str | None) -> bool:
    """Сливать можно части одного вида; тонкая и «средняя» (звенья одной ножки/перекладины) — тоже; объём с ними — никогда."""
    return a == b or {a, b} <= {"thin", "mid"}


def linear_in_blob_share(part: np.ndarray, kind: np.ndarray, linear_majority: float = 0.5, min_part_share: float = 0.10, min_linear_faces: int = 0, legs_mask: np.ndarray | None = None) -> float:
    """Доля linear-граней, лежащих в КРУПНОЙ объёмной части (от `min_part_share` всех граней, linear в ней — меньшинство): ножка/стойка в одной части с обивкой.
    Малые части (подлокотник, ручка) не считаются: они уже отдельные, даже если у них часть граней linear."""
    lin = (kind == shp.LINEAR) & (part >= 0)
    if legs_mask is not None:
        lin = lin & legs_mask                                                   # «ножки» — linear-грани в нижней части по высоте (рёбра корпуса и перекладины выше не считаются)
    if lin.sum() < min_linear_faces:                                           # linear-граней меньше, чем можно вырезать, — это шум классификатора, а не ножки
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
            cand = [j for j in np.argsort(-bnd[i]) if bnd[i, j] > 0 and compatible(kinds.get(int(j)), kinds.get(int(i)))]
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


def merge_orphans(part: np.ndarray, adj, area: np.ndarray, max_area_share: float, agree: np.ndarray | None = None) -> tuple[np.ndarray, list[dict]]:
    """Крошечная часть-«сирота» (доля ПЛОЩАДИ < `max_area_share`, не граней: узкая щепка с кучей мелких граней всё равно мала) — в соседа с самой длинной общей границей,
    ВНЕ зависимости от вида (у сироты нет своего смысла: свой цвет заливка этапа 7 возьмёт только с неё же, а у неё нет текселей с фото, и она красится тоном соседа/целого).
    Равная граница → сосед с большим средним согласием кадров, затем с большей площадью (роли на этом шаге ещё нет — они ставятся после доводки).
    Возвращает (части, след: [{faces, area_share, into_face0}] — `into_face0` — грань соседа-приёмника, по ней после перенумерации находится итоговый номер)."""
    part = part.copy()
    nf = len(part)
    tot = float(area.sum()) or 1.0
    trace = []
    for _ in range(500):
        ids = np.unique(part[part >= 0])
        if len(ids) < 2:
            break
        remap = {int(p): i for i, p in enumerate(ids)}
        dense = np.array([remap.get(int(x), -1) for x in part])
        oh = _onehot(dense, len(ids))
        bnd = (oh.T @ adj @ oh).toarray()
        np.fill_diagonal(bnd, 0)
        ar = np.asarray(oh.T @ area).ravel() / tot
        sm = [i for i in np.argsort(ar) if ar[i] < max_area_share and bnd[i].max() > 0]
        if not sm:
            break
        i = sm[0]
        top = bnd[i].max()
        cand = [j for j in range(len(ids)) if bnd[i, j] >= top - 1e-9 and j != i]
        if len(cand) > 1:
            def key(j):
                a = float(agree[dense == j].mean()) if agree is not None else 0.0
                return (a, ar[j])
            cand.sort(key=key, reverse=True)
        j = cand[0]
        trace.append({"faces": int((dense == i).sum()), "area_share": round(float(ar[i]), 6), "into_face0": int(np.nonzero(dense == j)[0][0])})
        part[dense == i] = ids[j]
    return part, trace


def cap_parts(part: np.ndarray, kind: np.ndarray, adj, lab: np.ndarray | None, max_parts: int, de_cap: float) -> np.ndarray:
    """Частей больше потолка (`check.max_parts`) — самая малая часть вливается в соседа ТОГО ЖЕ вида (тонкая — в тонкую, объёмная — в объёмную) с самой длинной границей;
    сначала только при близком цвете (ΔE76 < `refine.colour_cap_de`), если таких нет — по границе без цвета. Тонкие части (ножки) в объёмные не вливаются никогда."""
    part = part.copy()
    nf = len(part)
    for _ in range(200):
        ids = np.unique(part[part >= 0])
        if len(ids) <= max_parts:
            break
        remap = {int(p): i for i, p in enumerate(ids)}
        dense = np.array([remap.get(int(x), -1) for x in part])
        oh = _onehot(dense, len(ids))
        bnd = (oh.T @ adj @ oh).toarray()
        np.fill_diagonal(bnd, 0)
        size = np.asarray(oh.sum(axis=0)).ravel()
        kinds = part_kinds(dense, kind)
        med = _part_lab_median(dense, lab) if lab is not None else None
        done = False
        for use_colour in ((True, False) if med is not None else (False,)):
            for i in np.argsort(size):
                cand = [j for j in np.argsort(-bnd[i]) if bnd[i, j] > 0 and compatible(kinds.get(int(j)), kinds.get(int(i)))]
                if use_colour:
                    cand = [j for j in cand if float(np.linalg.norm(med[int(i)] - med[int(j)])) < de_cap]
                if cand:
                    part[dense == i] = ids[cand[0]]
                    done = True
                    break
            if done:
                break
        if not done:
            break
    return part


def absorb_islands(part: np.ndarray, vertices: np.ndarray, faces: np.ndarray, seen: np.ndarray | None, cfg: dict, kind_f: np.ndarray | None = None) -> tuple[np.ndarray, dict]:
    """Крошка на границе частей: малый связный кусок части (< `max_faces` граней, не главный кусок части, не больше `max_rel_main` главного куска — настоящие ножки/подушки сравнимы
    по размеру, крошка нет), >= `foreign` граничных рёбер которого уходят в ОДНУ другую часть, — вливается в неё. `side`: hidden — только куски, где < 50 % граней видны хоть одной
    камерой этапа 3 (на видимых границах решает разбиение по голосам); visible — наоборот; both — все. `kind_f` (виды граней формы): вливать только в часть СОВМЕСТИМОГО вида
    (`compatible`: тонкая ножка/стойка в объём — никогда; иначе дерево ножки утекло бы в обивку). Возвращает (части, отчёт: куски/грани по сторонам)."""
    import scipy.sparse as sp
    import scipy.sparse.csgraph as cg

    n = len(faces)
    v = np.round(np.asarray(vertices) * 1e5).astype(np.int64)
    _, inv = np.unique(v, axis=0, return_inverse=True)
    f = inv.reshape(-1)[np.asarray(faces).reshape(-1)].reshape(np.asarray(faces).shape)
    e = np.concatenate([f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]]])
    fid = np.tile(np.arange(n), 3)
    e.sort(axis=1)
    key = e[:, 0] * (e.max() + 1) + e[:, 1]
    order = np.argsort(key, kind="stable")
    ks, fs = key[order], fid[order]
    same = ks[1:] == ks[:-1]
    i, j = fs[:-1][same], fs[1:][same]
    part = part.copy()
    rep = {"islands": 0, "faces": 0, "hidden": 0, "visible": 0}
    sn = np.zeros(n, dtype=bool) if seen is None else seen.astype(bool)
    for _ in range(int(cfg.get("passes", 2))):
        eq = (part[i] == part[j]) & (part[i] >= 0)
        g = sp.coo_matrix((np.ones(int(eq.sum()), dtype=np.int8), (i[eq], j[eq])), shape=(n, n))
        nc, lab = cg.connected_components(g, directed=False)
        size = np.bincount(lab, minlength=nc)
        cpart = np.zeros(nc, dtype=np.int64)
        cpart[lab] = part
        cseen = np.bincount(lab, weights=sn.astype(np.float64), minlength=nc) / np.maximum(size, 1)
        main = {}
        for c in range(nc):
            p = cpart[c]
            if p >= 0 and (p not in main or size[c] > size[main[p]]):
                main[p] = c
        is_main = np.zeros(nc, dtype=bool)
        is_main[list(main.values())] = True
        diff = (part[i] != part[j]) & (part[i] >= 0) & (part[j] >= 0)
        P = int(part.max()) + 2
        a = np.concatenate([lab[i[diff]], lab[j[diff]]])
        b = np.concatenate([part[j[diff]], part[i[diff]]])
        cnt = np.bincount(a * P + b, minlength=nc * P).reshape(nc, P)
        tot = cnt.sum(axis=1)
        top = cnt.argmax(axis=1)
        frac = cnt.max(axis=1) / np.maximum(tot, 1)
        mainsize = np.array([size[main[int(p)]] if p in main else 1 for p in cpart])
        side = cfg.get("side", "hidden")
        sidem = (cseen < 0.5) if side == "hidden" else (cseen >= 0.5) if side == "visible" else np.ones(nc, dtype=bool)
        if kind_f is not None:
            pk = part_kinds(part, kind_f)
            okk = np.array([compatible(pk.get(int(cpart[c])), pk.get(int(top[c]))) for c in range(nc)])
        else:
            okk = np.ones(nc, dtype=bool)
        psize = np.bincount(part[part >= 0]) if (part >= 0).any() else np.zeros(1, dtype=np.int64)
        pshare = np.array([psize[int(q)] if 0 <= q < len(psize) else 1 for q in cpart], dtype=np.float64)
        lim = cfg["max_part_share"] * pshare if cfg.get("max_part_share") else np.full(nc, float(cfg["max_faces"]))   # размер крошки — доля СВОЕЙ части (не зависит от плотности меша)
        sel = okk & (~is_main) & (cpart >= 0) & (size < lim) & (size <= cfg.get("max_rel_main", 0.2) * mainsize) & (tot > 0) & (frac >= cfg.get("foreign", 0.8)) & sidem
        en = cfg.get("enclosed") or {}
        if en.get("enabled") and kind_f is not None:                                   # накладка: крупнее крошки, но ОКРУЖЕНА одной частью и не стоит на полу — не ножка
            fy = np.asarray(vertices)[np.asarray(faces)][:, :, 1].min(axis=1)
            cmin = np.full(nc, np.inf)
            np.minimum.at(cmin, lab, fy)
            ymin = float(np.asarray(vertices)[:, 1].min())
            hgt = max(float(np.asarray(vertices)[:, 1].max()) - ymin, 1e-9)
            thin_to_body = np.array([pk.get(int(cpart[c])) == "thin" and pk.get(int(top[c])) == "body" for c in range(nc)])
            sel2 = (~sel) & thin_to_body & (~is_main) & (cpart >= 0) & (size <= en.get("max_part_share", 0.10) * pshare) & (size <= en.get("max_rel_main", 0.3) * mainsize) & (tot >= en.get("min_border", 20)) & (frac >= en.get("foreign", 0.95)) & ((cmin - ymin) / hgt > en.get("floor_gap", 0.1)) & sidem
            rep["enclosed"] = rep.get("enclosed", 0) + int(sel2.sum())
            sel = sel | sel2
        if not sel.any():
            break
        for c in np.where(sel)[0]:
            part[lab == c] = top[c]
            rep["islands"] += 1
            rep["faces"] += int(size[c])
            rep["hidden" if cseen[c] < 0.5 else "visible"] += 1
    return part, rep


def refine(part: np.ndarray, vertices: np.ndarray, faces: np.ndarray, adj, lab_face: np.ndarray | None, rules: dict,
           agree: np.ndarray | None = None, seen: np.ndarray | None = None) -> tuple[np.ndarray, dict]:
    """Доводка: срез тонкого → слияние пёстрых по цвету → малые в соседа → потолок числа частей. Возвращает (новые части без дыр в нумерации, отчёт с меркой)."""
    from parts_vote import renumber

    kind, up, rep = shp.face_shapes(vertices, faces, shape_cfg(rules))
    rf = rules["refine"]
    legs_mask = up <= rf["legs_up_max"]
    floor = max(1, int(round(rf["linear_noise_share"] * len(part))))
    before = linear_in_blob_share(part, kind, 0.5, rf["thin_split_min_part_share"], floor, legs_mask)
    n_before = int(len(np.unique(part[part >= 0])))
    new = split_thin(part, kind, adj, rules)
    n_split = int(len(np.unique(new[new >= 0]))) - n_before
    new = merge_small(new, kind, adj, lab_face, rules, rf["colour_merge_max_share"], rf["colour_merge_de"] if lab_face is not None else None, agree, seen)
    new = merge_small(new, kind, adj, None, rules, rules["region"]["min_part_face_share"], None)
    orphans = []
    if rf.get("orphan_max_area_share"):                                          # доля площади, не граней; 0/нет — правило выключено
        area = _face_areas(vertices, faces)
        new, orphans = merge_orphans(new, adj, area, rf["orphan_max_area_share"], agree)
    new = cap_parts(new, kind, adj, lab_face, rules["check"]["max_parts"], rf["colour_cap_de"])
    isl = rf.get("islands") or {}
    isl_rep = None
    if isl.get("enabled") and seen is not None:                                    # P-062: выключено, пока директор не посмотрел «было | стало»
        new, isl_rep = absorb_islands(new, vertices, faces, seen, isl, kind)
    new = renumber(new)
    for o in orphans:
        o["into"] = int(new[o.pop("into_face0")])                                # итоговый номер части-приёмника (после cap/перенумерации)
    after = linear_in_blob_share(new, kind, 0.5, rf["thin_split_min_part_share"], floor, legs_mask)
    report = {"shape_share": rep["share"], "linear_in_blob_part_share_before": before, "linear_in_blob_part_share": after,
              "parts_before": n_before, "parts_split_off": n_split, "parts_after": int(len(np.unique(new[new >= 0])))}
    if orphans:
        report["merged_orphan"] = orphans
    if isl_rep is not None:
        report["absorbed_islands"] = isl_rep
    return new, report
