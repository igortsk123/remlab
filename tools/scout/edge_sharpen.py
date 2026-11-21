#!/usr/bin/env python3
"""Выпрямление плоскостей и кромок корпусной мебели у черновиков TRELLIS (T-20261121-175, этап 02-prep пути покраски; план `~/remlab-logs/t175-1121/plan.md`).

ЗАЧЕМ. Форма TRELLIS — вокселльная: плоскость остаётся плоской только по расстоянию (волна 1–2 вокселя), нормали соседних граней разбегаются на десятки градусов; кромка
(стык двух плоскостей) волнистая и «съедена» (замер на HD-комоде: волна кромки 0,12 % диагонали у родной, 0,20 % после Таубина и упрощения до 150 тыс. граней).
Владелец (TG 538): «кромки ящиков и столешницы шершавые». Правило общее: найти крупные плоские куски корпусной вещи, прижать их вершины к плоскостям, а у кромок —
к линии пересечения соседних плоскостей (Sharpen&Bend / Edge-Sharpener, Attene и др., arXiv 2311.18494, упрощённо: топология не меняется, двигаются только вершины).

КАК.
1) плоскости ищутся ПО РАССТОЯНИЮ (последовательный RANSAC по вершинам + нормаль вершины, сглаженная по кольцам, ≤ 30° + самая большая СВЯЗНАЯ часть + уточнение SVD):
   по углу между соседними гранями плоскостей нет (замер: крупнейшая область 0,3 % площади);
2) кромка = пара плоскостей с углом ≥ `edge_angle_min_deg`, у которой по обе стороны есть вершины у линии пересечения L; вершина в полосе `edge_band` от L сдвигается на БЛИЖАЙШУЮ из двух
   плоскостей, а если после этого она оказалась за гранью (по ту сторону второй плоскости) — на саму L; сдвиг ≤ `max_shift`; вершина, чья сглаженная нормаль не согласована с плоскостью
   (орнамент, ручка), не двигается;
3) вершины плоскости вне кромок — к плоскости с весом (1 внутри `full_within`·допуска, дальше линейно до 0 на допуске: рельеф глубже допуска остаётся);
4) защита: перевёрнутые грани → вершины возвращаются; форма «не корпусная» (площадь в плоскостях < `flat_share_min`) — не трогаем, причина в отчёте.
Права: тип товара из каталога (`cat_role`) ∈ `roles` правила; ни одного ID товара. Все пороги — `tools/scout/rules/edge-sharpen.json`.

API (чистый numpy — работает и в python Blender, где нет scipy):
    planes, ctx = find_planes(V, F, rules)                  # плоскости (наружу нормалью) и контекст формы
    V2, kind, rep = sharpen(V, F, planes, rules)             # новые вершины, kind на вершину (0 нет, 1 плоскость, 2 кромка: Таубин с маской и веса упрощения), отчёт
    m = measure(V, F, planes, rules)                         # мерки на ЛЮБОЙ форме по ТЕМ ЖЕ плоскостям (было → стало)
    role_allowed(role, rules)
Запуск: python3 tools/scout/edge_sharpen.py check   # правила целы (CI)
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RULES_PATH = os.path.join(HERE, "rules", "edge-sharpen.json")
sys.path.insert(0, HERE)
import plate_strip as _ps  # noqa: E402  (components без scipy)


def load_rules(path: str = RULES_PATH) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def role_allowed(role: str, rules: dict | None = None) -> bool:
    """Выпрямляем только типы товара из правила (данные, не код). Пустая роль — нельзя."""
    rules = rules or load_rules()
    return bool(role) and role.strip().lower() in {r.strip().lower() for r in rules.get("roles", [])}


def weld(V: np.ndarray, F: np.ndarray, tol_rel: float = 1e-6):
    """Склеить вершины по положению (glTF режет вершину по швам); → (V, F) без вырожденных граней."""
    V = np.asarray(V, np.float64)
    key = np.round(V / (np.ptp(V, axis=0).max() * tol_rel)).astype(np.int64)
    _, first, inv = np.unique(key, axis=0, return_index=True, return_inverse=True)
    inv = inv.reshape(-1)
    F2 = inv[np.asarray(F)]
    F2 = F2[(F2[:, 0] != F2[:, 1]) & (F2[:, 1] != F2[:, 2]) & (F2[:, 0] != F2[:, 2])]
    return V[first], F2


def _accum(F: np.ndarray, per_face: np.ndarray, nv: int) -> np.ndarray:
    out = np.zeros((nv, 3))
    for c in range(3):
        for k in range(3):
            out[:, c] += np.bincount(F[:, k], weights=per_face[:, c], minlength=nv)
    return out


def context(V: np.ndarray, F: np.ndarray, rules: dict) -> dict:
    """Площади, сглаженные нормали вершин (кольца `smooth_rings`: шум вокселей гаснет), диагональ."""
    V = np.asarray(V, np.float64)
    F = np.asarray(F, np.int64)
    nv = len(V)
    nf = np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]])
    area = np.linalg.norm(nf, axis=1) / 2
    va = np.bincount(F.ravel(), weights=np.repeat(area / 3, 3), minlength=nv)
    vn = _accum(F, nf, nv)
    for _ in range(int(rules.get("smooth_rings", 8))):
        vn = _accum(F, vn[F].sum(axis=1), nv)
    vn /= np.maximum(np.linalg.norm(vn, axis=1, keepdims=True), 1e-12)
    vn0 = _accum(F, nf, nv)
    vn0 /= np.maximum(np.linalg.norm(vn0, axis=1, keepdims=True), 1e-12)
    e = np.concatenate([F[:, [0, 1]], F[:, [1, 2]]])
    spacing = float(np.median(np.linalg.norm(V[e[:, 0]] - V[e[:, 1]], axis=1)))
    return {"va": va, "vn": vn, "vn0": vn0, "area": area, "total": float(va.sum()), "diag": float(np.linalg.norm(np.ptp(V, axis=0))), "nv": nv, "spacing": spacing}


def _largest_part(V, F, ctx, inl: np.ndarray) -> np.ndarray:
    """Самая большая (по площади вершин) связная часть множества вершин: связность — по рёбрам сетки, у которых обе вершины в множестве."""
    if len(inl) < 3:
        return inl
    is_in = np.zeros(ctx["nv"], bool)
    is_in[inl] = True
    e = np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]])
    e = e[is_in[e[:, 0]] & is_in[e[:, 1]]]
    if len(e) == 0:
        return inl[:0]
    f3 = np.stack([e[:, 0], e[:, 1], e[:, 1]], 1)
    lab = _ps._components_numpy(f3, ctx["nv"])
    w = np.bincount(lab[inl], weights=ctx["va"][inl], minlength=ctx["nv"])
    best = int(w.argmax())
    return inl[lab[inl] == best]


def _fit(V, ctx, vid):
    P = V[vid]
    w = ctx["va"][vid]
    c = (P * w[:, None]).sum(0) / w.sum()
    _, _, vt = np.linalg.svd((P - c) * np.sqrt(w)[:, None], full_matrices=False)
    n = vt[2]
    if (ctx["vn"][vid] @ n).mean() < 0:
        n = -n
    return c, n


def find_planes(V, F, rules: dict | None = None):
    """Последовательный RANSAC по расстоянию. → (planes, ctx); plane = {p0, n (наружу), vid (вершины), share (доля площади)}."""
    rules = rules or load_rules()
    V = np.asarray(V, np.float64)
    F = np.asarray(F, np.int64)
    ctx = context(V, F, rules)
    diag = ctx["diag"]
    tol = rules["tol_plane"] * diag
    cos_min = rules["normal_cos_min"]
    rng = np.random.default_rng(int(rules.get("seed", 7)))
    alive = np.ones(len(V), bool)
    planes = []
    for _ in range(int(rules["max_planes"])):
        idx = np.nonzero(alive & (ctx["va"] > 0))[0]
        if len(idx) < 200:
            break
        best = None
        for _t in range(int(rules["ransac_trials"])):
            s = rng.choice(idx, 3, replace=False)
            p = V[s]
            nn = np.cross(p[1] - p[0], p[2] - p[0])
            ln = np.linalg.norm(nn)
            if ln < 1e-12:
                continue
            nn /= ln
            sub = idx[rng.integers(0, len(idx), int(rules["ransac_sample"]))]
            ok = (np.abs((V[sub] - p[0]) @ nn) < tol) & (np.abs(ctx["vn"][sub] @ nn) > cos_min)
            sc = ctx["va"][sub][ok].sum()
            if best is None or sc > best[0]:
                best = (sc, p[0], nn)
        if best is None:
            break
        _, p0, nn = best
        inl = idx[(np.abs((V[idx] - p0) @ nn) < tol) & (np.abs(ctx["vn"][idx] @ nn) > cos_min)]
        inl = _largest_part(V, F, ctx, inl)
        for _r in range(2):
            if len(inl) < 10:
                break
            p0, nn = _fit(V, ctx, inl)
            inl2 = idx[(np.abs((V[idx] - p0) @ nn) < tol) & (np.abs(ctx["vn"][idx] @ nn) > cos_min)]
            inl = _largest_part(V, F, ctx, inl2)
        if len(inl) < 10:
            break
        share = float(ctx["va"][inl].sum() / ctx["total"])
        if share < rules["min_plane_share"]:
            break
        p0, nn = _fit(V, ctx, inl)
        planes.append({"p0": p0, "n": nn, "vid": inl, "share": share})
        alive[inl] = False
    return planes, ctx


def assign(V, F, ctx, plane: dict, rules: dict) -> np.ndarray:
    """Вершины ЛЮБОЙ формы, относящиеся к уже найденной плоскости (те же уравнения: расстояние < допуск, нормаль согласована, самая большая связная часть)."""
    tol = rules["tol_plane"] * ctx["diag"]
    d = (V - plane["p0"]) @ plane["n"]
    ok = (np.abs(d) < tol) & (np.abs(ctx["vn"] @ plane["n"]) > rules["normal_cos_min"]) & (ctx["va"] > 0)
    return _largest_part(V, F, ctx, np.nonzero(ok)[0])


def edge_pairs(planes, rules: dict):
    """Пары плоскостей с углом между нормалями ≥ порога → [(i, j, p0_on_L, dir_L)]."""
    out = []
    smin = np.sin(np.radians(rules["edge_angle_min_deg"]))
    for i in range(len(planes)):
        for j in range(i + 1, len(planes)):
            A, B = planes[i], planes[j]
            dv = np.cross(A["n"], B["n"])
            ln = np.linalg.norm(dv)
            if ln < smin:
                continue
            dv /= ln
            M = np.array([A["n"], B["n"], dv])
            p0 = np.linalg.solve(M, np.array([A["n"] @ A["p0"], B["n"] @ B["p0"], 0.0]))
            out.append((i, j, p0, dv))
    return out


def _surface_points(V, F, ctx, vid: np.ndarray, n_total: int, total_area: float, rng) -> np.ndarray:
    """Точки на гранях, у которых все три вершины в множестве `vid` (площадно равномерно): число пропорционально площади куска."""
    is_in = np.zeros(ctx["nv"], bool)
    is_in[vid] = True
    fm = np.nonzero(is_in[F].all(axis=1))[0]
    if len(fm) == 0:
        return V[vid]
    ar = ctx["area"][fm]
    k = int(max(3000, n_total * ar.sum() / max(total_area, 1e-12)))
    pick = fm[np.searchsorted(np.cumsum(ar), rng.random(k) * ar.sum())]
    u, v = rng.random(k), rng.random(k)
    fl = u + v > 1
    u[fl], v[fl] = 1 - u[fl], 1 - v[fl]
    return V[F[pick, 0]] * (1 - u - v)[:, None] + V[F[pick, 1]] * u[:, None] + V[F[pick, 2]] * v[:, None]


def edge_stats(V, F, ctx, planes, rules: dict, pairs=None, rng=None):
    """Мерка кромок БЕЗ членства вершин (оно зависит от сглаженных нормалей, которые у кромки смешиваются): по плотным точкам ПОВЕРХНОСТИ вокруг линии пересечения L.
    В каждой корзине вдоль L (1 % диагонали) g = самое малое расстояние от L до точек поверхности (острая кромка → поверхность проходит через L → g ≈ 0; съеденная/скруглённая → g = глубина
    съедания; волнистая → g гуляет). Мерки: g_mean (съеденность), g_std (волна вдоль кромки), % диагонали. `pairs` — какие кромки считать (список (i, j)); None — найти (по числу точек
    поверхности у L рядом с обеими плоскостями) и вернуть, чтобы ТЕ ЖЕ кромки мерить на других стадиях."""
    diag = ctx["diag"]
    tol = rules["tol_plane"] * diag
    rng = rng or np.random.default_rng(13)
    cand = edge_pairs(planes, rules)
    out, used = [], []
    for i, j, p0, dv in cand:
        if pairs is not None and [i, j] not in pairs:
            continue
        w = V - p0
        dL_v = np.linalg.norm(w - np.outer(w @ dv, dv), axis=1)
        fm = np.nonzero((dL_v[F] < 0.03 * diag).any(axis=1))[0]
        if len(fm) < 50:
            continue
        ar = ctx["area"][fm]
        k = int(min(120000, max(20000, ar.sum() / (0.0004 * diag) ** 2 / 2)))
        pick = fm[np.searchsorted(np.cumsum(ar), rng.random(k) * ar.sum())]
        u, v = rng.random(k), rng.random(k)
        fl = u + v > 1
        u[fl], v[fl] = 1 - u[fl], 1 - v[fl]
        P = V[F[pick, 0]] * (1 - u - v)[:, None] + V[F[pick, 1]] * u[:, None] + V[F[pick, 2]] * v[:, None]
        wq = P - p0
        t = wq @ dv
        dq = np.linalg.norm(wq - np.outer(t, dv), axis=1)
        near = dq < 0.015 * diag
        sa = np.abs((P - planes[i]["p0"]) @ planes[i]["n"])
        sb = np.abs((P - planes[j]["p0"]) @ planes[j]["n"])
        if pairs is None and ((near & (sa < tol)).sum() < 100 or (near & (sb < tol)).sum() < 100):
            continue
        tn, dn = t[near], dq[near]
        if len(tn) < 100:
            continue
        tb = np.floor((tn - tn.min()) / (0.01 * diag)).astype(int)
        g = np.array([dn[tb == b_].min() for b_ in range(tb.max() + 1) if (tb == b_).sum() >= 5])
        if len(g) < 8 or (tn.max() - tn.min()) < rules["edge_min_len"] * diag:
            continue
        out.append((g.mean() / diag * 100, g.std() / diag * 100, np.percentile(g, 95) / diag * 100))
        used.append([int(i), int(j)])
    if not out:
        return {"edge_gap_mean_pct": None, "edge_wave_std_pct": None, "edge_gap_p95_pct": None, "edges": 0, "edge_list": used}
    o = np.array(out)
    return {"edge_gap_mean_pct": round(float(o[:, 0].mean()), 4), "edge_wave_std_pct": round(float(o[:, 1].mean()), 4), "edge_gap_p95_pct": round(float(o[:, 2].mean()), 4), "edges": len(out), "edge_list": used}


def measure(V, F, planes, rules: dict | None = None, edges=None) -> dict:
    """Мерки на форме по ТЕМ ЖЕ плоскостям (% диагонали): шершавость плоскостей (ст.откл. ТОЧЕК на поверхности кусков плоскостей от плоскости; не по вершинам: после упрощения их вдвое меньше),
    доля площади в плоскостях и мерки кромок (`edge_stats`; `edges` — список пар, найденный на первой стадии)."""
    rules = rules or load_rules()
    V = np.asarray(V, np.float64)
    F = np.asarray(F, np.int64)
    ctx = context(V, F, rules)
    diag = ctx["diag"]
    rng = np.random.default_rng(11)
    rip, share, ndev = [], 0.0, []
    for p in planes:
        vid = assign(V, F, ctx, p, rules)
        if len(vid) < 10:
            continue
        ndev.append(np.degrees(np.arccos(np.clip(np.abs(ctx["vn0"][vid] @ p["n"]), 0, 1))))
        P = _surface_points(V, F, ctx, vid, int(rules.get("measure_points", 400000)), ctx["total"], rng)
        rip.append(float(((P - p["p0"]) @ p["n"]).std() / diag * 100))
        share += float(ctx["va"][vid].sum() / ctx["total"])
    es = edge_stats(V, F, ctx, planes, rules, edges)
    nd = np.concatenate(ndev) if ndev else np.zeros(1)
    return {"flat_share": round(share, 4), "ripple_std_pct": round(float(np.mean(rip)), 4) if rip else None, "flat_normal_mean_deg": round(float(nd.mean()), 2), "flat_normal_p95_deg": round(float(np.percentile(nd, 95)), 2), **es, "planes": len(planes), "faces": int(len(F))}


def _face_flips(V0, V1, F):
    n0 = np.cross(V0[F[:, 1]] - V0[F[:, 0]], V0[F[:, 2]] - V0[F[:, 0]])
    n1 = np.cross(V1[F[:, 1]] - V1[F[:, 0]], V1[F[:, 2]] - V1[F[:, 0]])
    return (n0 * n1).sum(axis=1) < 0


def sharpen(V, F, planes, rules: dict | None = None, ctx: dict | None = None):
    """→ (V2, kind, rep). kind (int8 на вершину): 0 — не тронута, 1 — на плоскости, 2 — в полосе кромки (для Таубина с маской и весов упрощения). Топология не меняется."""
    rules = rules or load_rules()
    V = np.asarray(V, np.float64)
    F = np.asarray(F, np.int64)
    ctx = ctx or context(V, F, rules)
    diag = ctx["diag"]
    tol = rules["tol_plane"] * diag
    band = rules["edge_band"] * diag
    cap = rules["max_shift"] * diag
    cosv = rules["edge_normal_cos_min"]
    Vn = V.copy()
    claimed = np.zeros(len(V), bool)
    n_edge = 0
    edges_used = []
    # 1) кромки: кандидат (вершина, пара) → новое положение; на вершину берётся самый малый сдвиг
    cand_v, cand_p, cand_s = [], [], []
    for i, j, p0, dv in edge_pairs(planes, rules):
        A, B = planes[i], planes[j]
        w = V - p0
        t = w @ dv
        perp = w - np.outer(t, dv)
        dL = np.linalg.norm(perp, axis=1)
        near = np.nonzero((dL < band) & (ctx["va"] > 0))[0]
        if len(near) == 0:
            continue
        a_n = np.intersect1d(near, A["vid"]).size
        b_n = np.intersect1d(near, B["vid"]).size
        if a_n < rules["edge_min_verts"] or b_n < rules["edge_min_verts"]:
            continue
        tt = t[near]
        if (tt.max() - tt.min()) < rules["edge_min_len"] * diag:
            continue
        Pn = V[near]
        sA = (Pn - A["p0"]) @ A["n"]
        sB = (Pn - B["p0"]) @ B["n"]
        ab = float(A["n"] @ B["n"])
        useA = np.abs(sA) <= np.abs(sB)
        # проекция на выбранную плоскость и проверка «за гранью» по второй
        pA = Pn - np.outer(sA, A["n"])
        pB = Pn - np.outer(sB, B["n"])
        newp = np.where(useA[:, None], pA, pB)
        other_s = np.where(useA, sB - sA * ab, sA - sB * ab)            # расстояние до второй плоскости у нового положения
        beyond = (other_s > 0) | (dL[near] < min(rules.get("snap_spacing_frac", 0.3) * ctx["spacing"], band))
        onL = p0 + np.outer(tt, dv)
        newp = np.where(beyond[:, None], onL, newp)
        nrm_ok = np.where(useA, ctx["vn"][near] @ A["n"], ctx["vn"][near] @ B["n"]) > cosv
        shift = np.linalg.norm(newp - Pn, axis=1)
        ok = nrm_ok & (shift <= cap)
        if not ok.any():
            continue
        cand_v.append(near[ok])
        cand_p.append(newp[ok])
        cand_s.append(shift[ok])
        n_edge += 1
        edges_used.append([int(i), int(j)])
    if cand_v:
        cv, cp, cs = np.concatenate(cand_v), np.concatenate(cand_p), np.concatenate(cand_s)
        order = np.lexsort((cs, cv))
        cv, cp = cv[order], cp[order]
        first = np.r_[True, cv[1:] != cv[:-1]]
        Vn[cv[first]] = cp[first]
        claimed[cv[first]] = True
    # 2) плоскости: вершины вне кромок — к плоскости с весом
    flat = np.zeros(len(V), bool)
    for pl in planes:
        vid = pl["vid"][~claimed[pl["vid"]]]
        d = (V[vid] - pl["p0"]) @ pl["n"]
        wgt = np.clip((tol - np.abs(d)) / (tol * (1 - rules["full_within"])), 0, 1)
        Vn[vid] = V[vid] - (wgt * d)[:, None] * pl["n"]
        flat[vid] = True
    kind = np.where(claimed, 2, np.where(flat, 1, 0)).astype(np.int8)          # 0 — не тронута, 1 — плоскость, 2 — кромка (полоса)
    # 3) защита: перевёрнутые грани → вершины их граней назад (до 3 раз)
    reverted = 0
    for _ in range(8):
        fl = _face_flips(V, Vn, F)
        if not fl.any():
            break
        bad = np.unique(F[fl])
        bad = bad[kind[bad] > 0]
        Vn[bad] = V[bad]
        kind[bad] = 0
        reverted += len(bad)
    sh = np.linalg.norm(Vn - V, axis=1)
    rep = {"planes": len(planes), "edges": n_edge, "edge_pairs": edges_used, "verts_edge": int(claimed.sum()), "verts_flat": int((flat & ~claimed).sum()),
           "flat_share": round(float(sum(p["share"] for p in planes)), 4), "shift_max_pct": round(float(sh.max() / diag * 100), 4), "shift_mean_pct": round(float(sh[kind > 0].mean() / diag * 100), 4) if (kind > 0).any() else 0.0,
           "flips_reverted": int(reverted), "flipped_after": int(_face_flips(V, Vn, F).sum())}
    return Vn, kind, rep


def analyze(V, F, rules: dict | None = None, role: str | None = None):
    """Целиком для этапа 02: права по роли (role=None — не проверять, проба) + доля плоского; → (V2 | None, kind | None, planes, ctx, rep).
    Нет прав или форма не корпусная → V2 None, причина в rep['refused']."""
    rules = rules or load_rules()
    if role is not None and not role_allowed(role, rules):
        return None, None, [], None, {"refused": f"тип товара «{role}» не в правиле — не трогаем"}
    planes, ctx = find_planes(V, F, rules)
    share = float(sum(p["share"] for p in planes))
    if share < rules["flat_share_min"]:
        return None, None, planes, ctx, {"refused": f"плоского {share:.2f} < {rules['flat_share_min']} — форма не корпусная, не трогаем", "flat_share": round(share, 4), "planes": len(planes)}
    V2, kind, rep = sharpen(V, F, planes, rules, ctx)
    rep["refused"] = ""
    return V2, kind, planes, ctx, rep


def check() -> int:
    r = load_rules()
    need = ["roles", "tol_plane", "min_plane_share", "max_planes", "normal_cos_min", "ransac_trials", "ransac_sample", "smooth_rings", "edge_angle_min_deg", "edge_band", "edge_min_verts",
            "edge_min_len", "edge_normal_cos_min", "max_shift", "full_within", "flat_share_min", "seed"]
    miss = [k for k in need if k not in r]
    if miss:
        print("edge-sharpen: в правилах нет", miss)
        return 1
    if not (0 < r["tol_plane"] < 0.02 and 0 < r["edge_band"] <= 0.05 and r["max_shift"] >= r["tol_plane"] and 0 < r["full_within"] < 1 and r["roles"]):
        print("edge-sharpen: пороги вне разумного")
        return 1
    print("edge-sharpen: правила целы")
    return 0


if __name__ == "__main__":
    sys.exit(check() if len(sys.argv) > 1 and sys.argv[1] == "check" else 2)
