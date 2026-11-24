#!/usr/bin/env python3
"""Вершинные нормали геометрий GLB для писателей этапов 06/07/08 (T-20261124-10/4).

ЗАЧЕМ. `load_geoms` не брал NORMAL из файла, а три `write_glb` строили Trimesh без нормалей → visible/filled/material.glb и web.glb без атрибута NORMAL, зритель шейдит плоскими гранями.
Здесь: (1) `file_normals(mesh)` — нормали файла, если они там были; (2) `recipe_normals(V, F)` — если нет: вершины сваривает ПО ПОЗИЦИИ (швы UV не рвут освещение),
вес = угол грани у вершины, складка > `CREASE_DEG` не сглаживается, вырожденные грани пропускаются, результат раздаётся всем дублям; число вершин и граней НЕ меняется (индексы те же);
(3) `seam_report` — согласованы ли нормали дублей одной позиции (мерка шва); (4) `geom_normals(g)` — выбор для писателя: g['VN'] → иначе рецепт.
Текстуру и геометрию не трогает; покраска 04/06/07/08 нормали файла не читает (только face_normals по геометрии) — проверено grep 24.11.
"""
from __future__ import annotations

import numpy as np

CREASE_DEG = 35.0        # ГИПОТЕЗА (директор/Fable 24.11): складка круче ~35° не сглаживается
WELD_DIGITS = 6          # позиция сваривается по округлению до 1e-6 от габарита
MIN_AREA_REL = 1e-12     # грань с площадью < MIN_AREA_REL·(габарит²) — вырожденная


def _weld_ids(V: np.ndarray) -> np.ndarray:
    span = float(max(np.ptp(V, axis=0).max(), 1e-12))
    q = np.round((V - V.min(axis=0)) / span * 10 ** WELD_DIGITS).astype(np.int64)
    _, inv = np.unique(q, axis=0, return_inverse=True)
    return np.asarray(inv, np.int64).reshape(-1)


SEAM_REF_DEG = 20.0      # дубли позиции с опорными нормалями в пределах 20° — один гладкий шов


def _unify_seam_refs(wid: np.ndarray, ref: np.ndarray, rarea: np.ndarray, has: np.ndarray) -> np.ndarray:
    """Каждому индексу — опора самого крупного (по площади опорной грани) из дублей своей позиции, чья опора ≤ SEAM_REF_DEG от его собственной."""
    idx = np.nonzero(has)[0]
    if len(idx) == 0:
        return ref
    order = idx[np.argsort(wid[idx], kind='stable')]
    w = wid[order]
    cnt = np.bincount(w)
    k = cnt[w]
    multi = k > 1
    if not multi.any():
        return ref
    o = order[multi]
    wm = w[multi]
    km = k[multi]
    startg = np.concatenate([[0], np.cumsum(km)[:-1]])
    first = np.concatenate([[True], wm[1:] != wm[:-1]])
    gstart = np.maximum.accumulate(np.where(first, np.arange(len(wm)), 0))      # позиция начала группы для каждого элемента
    rep = np.repeat(np.arange(len(o)), km)
    offs = np.arange(len(rep)) - np.repeat(np.cumsum(km) - km, km)
    mate = gstart[rep] + offs                                                    # напарники по группе
    cosr = np.einsum('ij,ij->i', ref[o[rep]], ref[o[mate]])
    near = cosr >= np.cos(np.radians(SEAM_REF_DEG))
    score = np.where(near, rarea[o[mate]], -1.0)
    # лучший напарник на каждый элемент: максимум score, при равенстве — меньший индекс вершины
    key = np.lexsort((o[mate], -score, rep))
    rs, ms = rep[key], mate[key]
    firstk = np.concatenate([[True], rs[1:] != rs[:-1]])
    pick = np.full(len(o), -1, np.int64)
    pick[rs[firstk]] = ms[firstk]
    out = ref.copy()
    ok = pick >= 0
    out[o[ok]] = ref[o[pick[ok]]]
    return out


def recipe_normals(V: np.ndarray, F: np.ndarray, crease_deg: float = CREASE_DEG, return_ref: bool = False):
    """Сглаженные нормали на вершину (форма как V). Складка — относительно нормали самой крупной грани ЭТОГО индекса вершины."""
    V = np.asarray(V, np.float64)
    F = np.asarray(F, np.int64)
    n = len(V)
    out = np.zeros((n, 3))
    if n == 0 or len(F) == 0:
        return (out, out.copy()) if return_ref else out
    a, b, c = V[F[:, 0]], V[F[:, 1]], V[F[:, 2]]
    cr = np.cross(b - a, c - a)
    area2 = np.linalg.norm(cr, axis=1)
    span = float(max(np.ptp(V, axis=0).max(), 1e-12))
    ok = area2 > 2.0 * MIN_AREA_REL * span * span
    fn = np.zeros_like(cr)
    fn[ok] = cr[ok] / area2[ok, None]
    # угол грани при каждом из трёх углов
    ang = np.zeros((len(F), 3))
    for k in range(3):
        p, q, r = V[F[:, k]], V[F[:, (k + 1) % 3]], V[F[:, (k + 2) % 3]]
        u, w = q - p, r - p
        nu, nw = np.linalg.norm(u, axis=1), np.linalg.norm(w, axis=1)
        d = np.einsum('ij,ij->i', u, w) / np.maximum(nu * nw, 1e-30)
        ang[:, k] = np.arccos(np.clip(d, -1.0, 1.0))
    ang[~ok] = 0.0
    wid = _weld_ids(V)
    ng = int(wid.max()) + 1
    # углы (грань, угол) → группы сварки
    cg = wid[F].reshape(-1)                      # группа каждого угла
    cf = np.repeat(np.arange(len(F)), 3)         # грань угла
    cw = ang.reshape(-1)                         # вес угла
    keep = cw > 0
    cg, cf, cw = cg[keep], cf[keep], cw[keep]
    order = np.argsort(cg, kind='stable')
    cg, cf, cw = cg[order], cf[order], cw[order]
    cnt = np.bincount(cg, minlength=ng)
    start = np.concatenate([[0], np.cumsum(cnt)[:-1]])
    # опорная нормаль индекса вершины = нормаль самой крупной его грани
    vi = F.reshape(-1)
    vf = np.repeat(np.arange(len(F)), 3)
    vok = ok[vf]
    best = np.full(n, -1, np.int64)
    # сортируем по (индекс, площадь) и берём последнюю запись индекса — самая крупная грань
    idx = np.nonzero(vok)[0]
    key = np.lexsort((area2[vf[idx]], vi[idx]))
    idx = idx[key]
    last = np.ones(len(idx), bool)
    last[:-1] = vi[idx][1:] != vi[idx][:-1]
    best[vi[idx][last]] = vf[idx][last]
    has = best >= 0
    ref = np.zeros((n, 3))
    ref[has] = fn[best[has]]
    # дубли ГЛАДКОГО шва (опорные нормали ≤ SEAM_REF_DEG) берут одну опору — у самой крупной опорной грани: тогда их наборы граней и нормали совпадают точно
    rarea = np.zeros(n)
    rarea[has] = area2[best[has]]
    ref = _unify_seam_refs(wid, ref, rarea, has)
    cos_min = np.cos(np.radians(crease_deg))
    vg = wid
    k = cnt[vg]                                   # сколько углов в группе вершины
    ids = np.nonzero(has)[0]
    rep = np.repeat(ids, k[ids])
    base = np.repeat(start[vg[ids]], k[ids])
    offs = np.arange(len(rep)) - np.repeat(np.cumsum(k[ids]) - k[ids], k[ids])
    pos = base + offs
    f2 = cf[pos]
    use = np.einsum('ij,ij->i', fn[f2], ref[rep]) >= cos_min
    np.add.at(out, rep[use], fn[f2[use]] * cw[pos[use], None])
    ln = np.linalg.norm(out, axis=1)
    bad = ln < 1e-12
    out[~bad] /= ln[~bad, None]
    out[bad] = ref[bad]                           # нет ни одной годной грани (редко) — опорная; у вершин без годных граней вовсе — +Y, чтобы NORMAL был единичным
    nolen = np.linalg.norm(out, axis=1) < 1e-12
    out[nolen] = (0.0, 1.0, 0.0)
    return (out, ref) if return_ref else out


def file_normals(mesh) -> np.ndarray | None:
    """Нормали, которые были в файле (trimesh кладёт их в кэш при загрузке; нет атрибута — None, считать ему нечего)."""
    try:
        cache = getattr(mesh, '_cache', None)
        v = cache.cache.get('vertex_normals') if cache is not None else None
    except Exception:  # noqa: BLE001
        return None
    if v is None:
        return None
    v = np.asarray(v, np.float64)
    if v.shape != (len(mesh.vertices), 3) or not np.isfinite(v).all():
        return None
    ln = np.linalg.norm(v, axis=1)
    if (ln < 0.5).mean() > 0.01:
        return None
    return v / np.maximum(ln[:, None], 1e-12)


def seam_report(V: np.ndarray, N: np.ndarray, REF: np.ndarray | None = None) -> dict:
    """Мерка шва UV. Дубли одной позиции делятся на: «перевёрнутые» (опорные нормали граней разошлись > 150° — остров TRELLIS с обратным обходом, нормаль честно противоположна),
    «складка» (опорные нормали разошлись 20–150° — шов лежит на изломе, нормали вправе различаться) и «гладкий шов» (≤ 20°). Нормали ГЛАДКОГО шва обязаны совпасть:
    для них — наибольший угол между нормалями дублей (p50, p99, доля > 5°). REF — опорные нормали граней по индексам (рецепт отдаёт `return_ref`)."""
    V = np.asarray(V, np.float64)
    N = np.asarray(N, np.float64)
    R = N if REF is None else np.asarray(REF, np.float64)
    wid = _weld_ids(V)
    order = np.argsort(wid, kind='stable')
    w, N, R = wid[order], N[order], R[order]
    cnt = np.bincount(w)
    multi = cnt[w] > 1
    out = {'dup_vertices': int(multi.sum())}
    if not multi.any():
        return out
    w, N, R = w[multi], N[multi], R[multi]
    first = np.concatenate([[True], w[1:] != w[:-1]])
    gid = np.cumsum(first) - 1
    ng = int(gid.max()) + 1
    rang = np.degrees(np.arccos(np.clip(np.einsum('ij,ij->i', R, R[first][gid]), -1, 1)))
    nang = np.degrees(np.arccos(np.clip(np.einsum('ij,ij->i', N, N[first][gid]), -1, 1)))
    gr = np.zeros(ng)
    np.maximum.at(gr, gid, rang)
    gn = np.zeros(ng)
    np.maximum.at(gn, gid, nang)
    flip, smooth = gr > 150, gr <= 20
    crease = ~flip & ~smooth
    out.update({'groups': ng, 'flipped_share': round(float(flip.mean()), 4), 'crease_share': round(float(crease.mean()), 4), 'smooth_share': round(float(smooth.mean()), 4)})
    if smooth.any():
        g = gn[smooth]
        out.update({'smooth_p50_deg': round(float(np.percentile(g, 50)), 3), 'smooth_p99_deg': round(float(np.percentile(g, 99)), 3), 'smooth_max_deg': round(float(g.max()), 3), 'smooth_share_gt5': round(float((g > 5).mean()), 4)})
    return out


SEAM_OK_SHARE = 0.01     # нормали файла годятся, если на гладких швах > 5° расходится не больше 1 % швов (иначе рецепт)


def geom_normals(g: dict) -> np.ndarray:
    """Нормали для писателя GLB. g['VN'] (нормали файла) берём, только если они согласованы на гладких швах UV (мерка `seam_report`, порог SEAM_OK_SHARE);
    иначе и когда NORMAL в файле не было — рецепт по геометрии (у TRELLIS нормали файла на швах расходятся: Марти-2, 02 — 23,6 % гладких швов > 5°)."""
    rn, ref = recipe_normals(g['V'], g['F'], return_ref=True)
    vn = g.get('VN')
    if vn is not None and len(vn) == len(g['V']):
        rep = seam_report(g['V'], vn, ref)
        if rep.get('smooth_share_gt5', 0.0) <= SEAM_OK_SHARE:
            return np.asarray(vn, np.float64)
    return rn
