"""Признаки частей меша для шага «роль части» (T-20261120-169/3; правки по Codex 21.11).

ЗАЧЕМ. Роль части (ножки, ручки, плафон, видимый каркас…) решают правила `tools/scout/rules/part-roles.json` по ЧИСЛАМ части, а не по ID товара. Здесь — только числа.
Все веса — по ПЛОЩАДИ граней (не по их числу: иначе зависит от плотности сетки); размеры — доли габарита модели (работает при любом масштабе). Ось вверх — Y (glTF).
Признаки части:
  area_share, up_q10/up_q90 (площадные перцентили высоты), up_min (самая низкая вершина), up_q02, kind (thin/mid/body), is_largest;
  obb{L,W,T,thin_ratio=T/L,slab} — ориентированная рамка по главным осям; plate_horizontal/plate_vertical — доля площади с вертикальной / горизонтальной нормалью;
  contacts — соседние части (общая граница ИЛИ близость ≤ `contact_eps`·габарит: части касаются и без общих вершин); contacts_main;
  floor_contact (up_min ≤ `floor_eps`), floor_near/supports_near_body (то же с допуском ×`floor_near_factor`: для осторожного вето), supports_body (касается пола И главной части, а главная от пола оторвана: опора соединяет корпус с полом);
  symmetry_group — сколько частей той же формы и высоты (или одного нижнего слоя: оба у пола, объёмные (body), та же толщина, ширина и верх любые; ножки и каркас сюда не входят) (4 ножки = 4, пара подлокотников = 2), symmetry_members — какие именно (движок ролей из них строит группы повторов: одна группа — одна роль);
  front/right/front_facing_share — из камеры фото (`cam_az`, pose.json этапа 4 ТОЛЬКО со статусом passed; фото магазина почти всегда спереди → направление на камеру = перёд).
  Нет камеры — эти три = None, и правила, требующие фронт, не срабатывают (unknown лучше неверной роли);
  agree/seen — доверие этапа 3 (порог воздержания); delta_e_main — ТОЛЬКО для отчёта, в роль не идёт.
"""
from __future__ import annotations

import numpy as np

import part_shapes as shp


def face_areas_normals(vertices: np.ndarray, faces: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    t = vertices[faces]
    cr = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
    ln = np.linalg.norm(cr, axis=1)
    return ln / 2, cr / np.maximum(ln, 1e-12)[:, None]


def wquantile(x: np.ndarray, w: np.ndarray, q: float) -> float:
    o = np.argsort(x)
    cw = np.cumsum(w[o])
    return float(x[o][min(np.searchsorted(cw, q * cw[-1]), len(x) - 1)])


def _obb(pts: np.ndarray, w: np.ndarray, scale: float) -> dict:
    """Рамка по главным осям центров граней (взвешены площадью); L ≥ W ≥ T в долях габарита модели."""
    if len(pts) < 4:
        return {"L": 0.0, "W": 0.0, "T": 0.0, "thin_ratio": 1.0, "slab": False}
    mu = np.average(pts, axis=0, weights=w)
    cov = np.cov((pts - mu).T, aweights=w)
    _, vec = np.linalg.eigh(cov)
    prj = (pts - mu) @ vec
    d = np.sort(prj.max(axis=0) - prj.min(axis=0))[::-1] / scale
    L, W, T = (float(d[0]), float(d[1]), float(d[2]))
    return {"L": round(L, 3), "W": round(W, 3), "T": round(T, 3), "thin_ratio": round(T / max(L, 1e-9), 3), "slab": bool(T / max(W, 1e-9) <= 0.25)}


def _obb_components(idx: np.ndarray, c: np.ndarray, area: np.ndarray, adj, scale: float, min_share: float = 0.05) -> dict:
    """Рамка по СВЯЗНЫМ кускам части: две ножки в одной части не должны давать «толстую» рамку между ними. L/W/T — у самого крупного куска,
    thin_ratio — среднее по кускам (весом площади, куски < `min_share` площади части не считаются), slab — у самого крупного, `n_components` — число кусков."""
    from scipy.sparse.csgraph import connected_components

    if adj is None or len(idx) < 2:
        return {**_obb(c[idx], area[idx], scale), "n_components": 1}
    n, lab = connected_components(adj[idx][:, idx], directed=False)
    comps = [(float(area[idx[lab == k]].sum()), idx[lab == k]) for k in range(n)]
    tot = sum(a for a, _ in comps)
    comps = [(a, m) for a, m in comps if a >= min_share * tot] or comps
    obbs = [(a, _obb(c[m], area[m], scale)) for a, m in comps]
    big = max(obbs, key=lambda t: t[0])[1]
    wsum = sum(a for a, _ in obbs)
    return {**big, "thin_ratio": round(sum(a * o["thin_ratio"] for a, o in obbs) / wsum, 3), "n_components": len(obbs)}


def part_features(part: np.ndarray, vertices: np.ndarray, faces: np.ndarray, kind: np.ndarray, kinds: dict[int, str],
                  lab: np.ndarray | None = None, cam_az: float | None = None, adj=None,
                  agree: np.ndarray | None = None, seen: np.ndarray | None = None,
                  floor_eps: float = 0.04, floor_near_factor: float = 2.0, contact_eps: float = 0.02, sym_tol: float = 0.15, sym_h_tol: float = 0.08) -> dict[int, dict]:
    """Признаки каждой части {id: {...}}. `kind` — вид граней (part_shapes), `kinds` — вид частей (parts_refine.part_kinds), `adj` — соседство граней (parts_vote.weld_adjacency)."""
    from scipy.spatial import cKDTree

    area, nrm = face_areas_normals(vertices, faces)
    c = vertices[faces].mean(axis=1)
    lo, hi = vertices.min(axis=0), vertices.max(axis=0)
    ext = np.maximum(hi - lo, 1e-9)
    scale = float(ext.max())
    up = (c[:, 1] - lo[1]) / ext[1]
    mid = (lo + hi) / 2
    half = ext / 2
    tot = float(area.sum())
    ids = [int(p) for p in np.unique(part[part >= 0])]
    asum = {p: float(area[part == p].sum()) for p in ids}
    largest = max(ids, key=lambda p: asum[p]) if ids else None
    med = {p: np.median(lab[part == p], axis=0) for p in ids} if lab is not None else {}
    if cam_az is not None:
        a_ = np.radians(cam_az)
        to_cam = np.array([np.sin(a_), np.cos(a_)])            # (x, z): pose_fit.cam_basis, C ∝ (sin az·cos el, ·, cos az·cos el)
        right = np.array([np.cos(a_), -np.sin(a_)])
        half_f = max(abs(to_cam[0]) * half[0] + abs(to_cam[1]) * half[2], 1e-9)
        half_r = max(abs(right[0]) * half[0] + abs(right[1]) * half[2], 1e-9)
        out_n = nrm * np.sign(((c - mid) * nrm).sum(1))[:, None]                       # нормаль «наружу» (порядок обхода в мешах ненадёжен)
        facing = (out_n[:, [0, 2]] @ to_cam) > 0.3
    out: dict[int, dict] = {}
    for p in ids:
        m = part == p
        w = area[m]
        pts = c[m]
        vp = vertices[faces[m]].reshape(-1, 3)
        upv = (vp[:, 1] - lo[1]) / ext[1]
        f = {
            "area_share": round(asum[p] / tot, 4),
            "up_q10": round(wquantile(up[m], w, 0.10), 3),
            "up_q90": round(wquantile(up[m], w, 0.90), 3),
            "up_min": round(float(upv.min()), 3),
            "up_q02": round(wquantile(up[m], w, 0.02), 3),
            "kind": kinds.get(p, "body"),
            "is_largest": p == largest,
            "obb": _obb_components(np.nonzero(m)[0], c, area, adj, scale),
            "plate_horizontal": round(float(w[np.abs(nrm[m][:, 1]) >= 0.8].sum() / w.sum()), 3),
            "plate_vertical": round(float(w[np.abs(nrm[m][:, 1]) <= 0.3].sum() / w.sum()), 3),
            "planar_share": round(float(w[kind[m] == shp.PLANAR].sum() / w.sum()), 3),
            "delta_e_main": round(float(np.linalg.norm(med[p] - med[largest])), 1) if med else None,
            "agree": round(float(agree[m & (seen if seen is not None else True)].mean()), 3) if agree is not None and (m & (seen if seen is not None else True)).any() else None,
            "seen": round(float((seen[m]).mean()), 3) if seen is not None else None,
        }
        if cam_az is not None:
            xz = pts[:, [0, 2]] - mid[[0, 2]]
            f["front"] = round(float(np.clip(np.average(xz @ to_cam, weights=w) / half_f, -1, 1)), 3)
            f["right"] = round(float(np.clip(np.average(xz @ right, weights=w) / half_r, -1, 1)), 3)
            f["front_facing_share"] = round(float(w[facing[m]].sum() / w.sum()), 3)
        else:
            f["front"] = f["right"] = f["front_facing_share"] = None
        out[p] = f
    # контакты: общая граница (соседство граней) ИЛИ близость вершин
    contacts: dict[int, set[int]] = {p: set() for p in ids}
    if adj is not None:
        coo = adj.tocoo()
        pa, pb = part[coo.row], part[coo.col]
        for a, b in set(zip(pa[pa != pb].tolist(), pb[pa != pb].tolist())):
            if a >= 0 and b >= 0:
                contacts[a].add(b)
    trees = {}
    for p in ids:
        vp = vertices[faces[part == p]].reshape(-1, 3)
        trees[p] = cKDTree(vp[np.random.RandomState(0).permutation(len(vp))[:4000]])
    eps = contact_eps * scale
    for i, p in enumerate(ids):
        for q in ids[i + 1:]:
            if q in contacts[p]:
                continue
            small, big = (q, p) if len(trees[q].data) <= len(trees[p].data) else (p, q)      # меньшую часть ищем в большей
            d, _ = trees[big].query(trees[small].data[:1500], distance_upper_bound=eps)
            if np.isfinite(d).any():
                contacts[p].add(q)
                contacts[q].add(p)
    main_up_min = out[largest]["up_q02"] if ids else 0                       # у главной части одна шальная вершина у пола не в счёт: берём 2-й площадный перцентиль
    for p in ids:
        out[p]["floor_near"] = out[p]["up_min"] <= floor_near_factor * floor_eps               # «почти у пола»: допуск шире, нужен для осторожного вето (support_unclear) и для слоя основания
    for p in ids:
        f = out[p]
        f["contacts"] = sorted(contacts[p])
        f["contacts_main"] = largest in contacts[p]
        f["floor_contact"] = f["up_min"] <= floor_eps
        f["supports_near_body"] = bool(p != largest and f["floor_near"] and f["contacts_main"] and main_up_min > floor_eps)
        f["supports_body"] = bool(p != largest and f["floor_contact"] and f["contacts_main"] and main_up_min > floor_eps)
        g = 1
        mem = []
        o = f["obb"]
        for q in ids:
            if q == p:
                continue
            oq = out[q]["obb"]
            same_h = abs(f["up_q10"] - out[q]["up_q10"]) <= sym_h_tol and abs(f["up_q90"] - out[q]["up_q90"]) <= sym_h_tol
            same_box = all(abs(o[k] - oq[k]) <= sym_tol * max(o[k], oq[k], 1e-9) + 0.005 for k in ("L", "W", "T"))
            # нижний слой: модули основания разной ширины и высоты верха (сегментация режет их по-разному), но оба объёмные (не ножки) у пола, та же толщина — один слой, одна роль
            same_layer = f["floor_near"] and out[q]["floor_near"] and f["kind"] == out[q]["kind"] == "body" \
                and abs(o["T"] - oq["T"]) <= sym_tol * max(o["T"], oq["T"], 1e-9) + 0.005
            if (same_h and same_box) or same_layer:
                g += 1
                mem.append(q)
        f["symmetry_group"] = g
        f["symmetry_members"] = mem                                                # попарно похожие части (размеры рамки и высота): из них движок строит группы повторов
    return out
