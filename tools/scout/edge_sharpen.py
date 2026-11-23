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


# ───────────────────────── режим «задняя панель» (T-20261123-41; план paint-cycles-1123 строка 7) ─────────────────────────
def _axis_frame(V, vn, va, front_dir, br: dict):
    """Ось глубины: средняя нормаль «лица» (вершины, у которых нормаль в пределах `front_cos_min` от направления на камеру), прижатая к ближайшей координатной оси, если ближе `axis_snap_deg`.
    → (a — наружу к камере, u, v — оси плоскости кадра)."""
    d = np.asarray(front_dir, np.float64)
    d /= np.linalg.norm(d)
    m = (vn @ d) > br["front_cos_min"]
    if m.sum() < 50:
        return None
    a = (vn[m] * va[m, None]).sum(0)
    a /= np.linalg.norm(a)
    k = int(np.abs(a).argmax())
    if abs(a[k]) >= np.cos(np.radians(br["axis_snap_deg"])):
        a = np.eye(3)[k] * np.sign(a[k])
    up = np.array([0.0, 1.0, 0.0]) if abs(a[1]) < 0.9 else np.array([0.0, 0.0, 1.0])
    v = up - (up @ a) * a
    v /= np.linalg.norm(v)
    u = np.cross(v, a)
    return a, u, v


def _cells(V, u, v, lo, hi, G):
    iu = np.clip(((V @ u - lo[0]) / (hi[0] - lo[0]) * G).astype(int), 0, G - 1)
    iv = np.clip(((V @ v - lo[1]) / (hi[1] - lo[1]) * G).astype(int), 0, G - 1)
    return iv * G + iu


def _skin(t, c, sel, G, tol, outer_min: bool):
    """Внешняя кожа: из `sel` — вершины, лежащие не глубже 2 допусков от самой внешней в своей клетке кадра (внутренние стенки полостей и «двойные» слои не считаются).
    outer_min=True — внешняя = наименьшее t (зад), False — наибольшее (лицо)."""
    ext = np.full(G * G, np.inf if outer_min else -np.inf)
    (np.minimum if outer_min else np.maximum).at(ext, c[sel], t[sel])
    return sel & ((t <= ext[c] + 2 * tol) if outer_min else (t >= ext[c] - 2 * tol))


def _relief_map(t, c, skin, G, sign):
    m = np.full(G * G, np.nan)
    m[c[skin]] = sign * t[skin]
    m = m.reshape(G, G)
    return m - np.nanmedian(m)


def _smooth_nan(m, sigma):
    from scipy.ndimage import gaussian_filter
    ok = np.isfinite(m).astype(float)
    num, den = gaussian_filter(np.where(np.isfinite(m), m, 0.0), sigma), gaussian_filter(ok, sigma)
    out = np.where(den > 0.2, num / np.maximum(den, 1e-9), np.nan)
    out[gaussian_filter(ok, sigma * 2) <= 0.05] = np.nan
    return out


def _corr(a, b, min_cells):
    ok = np.isfinite(a) & np.isfinite(b)
    if ok.sum() < min_cells:
        return None
    x, y = a[ok], b[ok]
    sx, sy = x.std(), y.std()
    if sx < 1e-12 or sy < 1e-12:
        return None
    return float(((x - x.mean()) * (y - y.mean())).mean() / (sx * sy))


def back_panel_analyze(V, F, front_dir, rules: dict | None = None, ctx: dict | None = None) -> dict:
    """Мерки задней панели без изменения формы. Внешняя кожа зада (вершины, обращённые от камеры, самые внешние в клетке кадра) → уровень задней плоскости (самая площадная мода глубины) →
    доли кожи в допуске плоскости и в `depth` от неё; справочно — корреляция рельефа зада с лицом (как есть и зеркально; на замере 7 товаров НЕ разделяет дубль и чистое — в решение не входит).
    `apply` — по правилу `back_panel`: у зада есть плоскость (доля в `depth` ≥ plane_share_min) и на ней есть рельеф (доля вне допуска ≥ relief_share_min)."""
    rules = rules or load_rules()
    br = rules["back_panel"]
    V = np.asarray(V, np.float64)
    F = np.asarray(F, np.int64)
    ctx = ctx or context(V, F, rules)
    diag, vn, va = ctx["diag"], ctx["vn"], ctx["va"]
    rep = {"apply": False, "reason": ""}
    fr = _axis_frame(V, vn, va, front_dir, br)
    if fr is None:
        rep["reason"] = "лицо к камере не найдено"
        return rep
    a, u, v = fr
    t = V @ a
    tol = rules["tol_plane"] * diag
    depth = br["depth"] * diag
    P = np.stack([V @ u, V @ v], 1)
    lo, hi = P.min(0), P.max(0)
    G = int(br["grid"])
    c = _cells(V, u, v, lo, hi, G)
    ok_v = va > 0
    back = ((vn @ a) < -br["back_cos_min"]) & ok_v
    front = ((vn @ a) > br["back_cos_min"]) & ok_v
    if back.sum() < 200 or front.sum() < 200:
        rep["reason"] = "нет зада или лица"
        return rep
    skin = _skin(t, c, back, G, tol, True)
    tb, wb = t[skin], va[skin]
    h, e = np.histogram(tb, bins=max(int(np.ceil(np.ptp(tb) / tol)), 1), weights=wb)
    k = int(h.argmax())
    in_bin = (tb >= e[k]) & (tb <= e[k + 1])
    level = float((tb[in_bin] * wb[in_bin]).sum() / max(wb[in_bin].sum(), 1e-12))
    near = skin & (np.abs(t - level) <= depth)
    # склоны рельефа: нормаль не «от камеры», но вершина в клетке внутри следа зада (не у его края — там боковая стенка корпуса) и не дальше `depth` от плоскости
    foot = np.zeros(G * G, bool)
    foot[c[skin]] = True
    foot = foot.reshape(G, G)
    for _ in range(int(br["rim_cells"])):
        e = foot.copy()
        e[1:, :] &= foot[:-1, :]
        e[:-1, :] &= foot[1:, :]
        e[:, 1:] &= foot[:, :-1]
        e[:, :-1] &= foot[:, 1:]
        e[0, :] = e[-1, :] = False
        e[:, 0] = e[:, -1] = False
        foot = e
    slope = (~back) & ok_v & ((vn @ a) < br["slope_cos_max"]) & foot.reshape(-1)[c] & (t >= level - depth) & (t <= level + depth)
    flat = skin & (np.abs(t - level) <= tol)
    plane_share = float(va[near].sum() / max(va[skin].sum(), 1e-12))
    relief_share = float(1.0 - va[flat].sum() / max(va[near].sum(), 1e-12)) if near.any() else 0.0
    rep.update({"axis": [round(float(x), 4) for x in a], "back_level": round(level, 5), "plane_share": round(plane_share, 3), "relief_share": round(relief_share, 3),
                "flat_share": round(float(va[flat].sum() / max(va[skin].sum(), 1e-12)), 3), "back_verts_in_depth": int(near.sum())})
    fsk = _skin(t, c, front, G, tol, False)
    ob = _smooth_nan(_relief_map(t, c, skin, G, -1.0), br["corr_smooth_cells"])
    of = _smooth_nan(_relief_map(t, c, fsk, G, +1.0), br["corr_smooth_cells"])
    cs, cf = _corr(ob, of, int(br["min_cells"])), _corr(ob, of[:, ::-1], int(br["min_cells"]))
    rep["corr_same"], rep["corr_flip"] = (None if x is None else round(x, 3) for x in (cs, cf))
    if plane_share < br["plane_share_min"]:
        rep["reason"] = f"у зада нет плоскости (доля кожи в {br['depth']} диагонали от неё {plane_share:.2f} < {br['plane_share_min']}) — не корпусной зад, не трогаем"
    elif relief_share < br["relief_share_min"]:
        rep["reason"] = f"на заду рельефа нет (доля вне допуска {relief_share:.3f} < {br['relief_share_min']}) — уже плоский"
    else:
        rep["apply"] = True
    rep["_near"] = near | slope
    rep["_level"] = level
    rep["_a"] = a
    return rep


def back_panel(V, F, front_dir, rules: dict | None = None, ctx: dict | None = None, protect: np.ndarray | None = None):
    """Режим «задняя панель»: рельеф лица, повторённый на заду (TRELLIS дублирует его сквозь тело), → плоскость. Берутся вершины, обращённые от камеры и лежащие не глубже
    `depth` от задней плоскости и входящие во внешнюю кожу зада; они садятся на неё (топология не меняется). Зад без плоскости (не корпусной) и уже плоский зад не трогаем.
    `protect` — маска вершин, которые не трогаем НИКОГДА (сторона с фото этапа 6): они выпадают из `near` до сдвига; rep['photo_touched'] — сколько защищённых всё же сдвинулось (должно быть 0).
    → (V2, moved — маска сдвинутых вершин, rep). Допуск по ТИПУ — снаружи (`back_panel_gate`: политика паспорта типа)."""
    rules = rules or load_rules()
    V = np.asarray(V, np.float64)
    rep = back_panel_analyze(V, F, front_dir, rules, ctx)
    near, level, a = rep.pop("_near", None), rep.pop("_level", None), rep.pop("_a", None)
    moved = np.zeros(len(V), bool)
    if protect is not None and near is not None:
        rep["protected_in_near"] = int((near & protect).sum())
        near = near & ~np.asarray(protect, bool)
    if not rep["apply"]:
        return V.copy(), moved, rep
    V2 = V.copy()
    br = rules["back_panel"]
    dt = level - V[near] @ a
    w = np.clip((br["depth"] * np.linalg.norm(np.ptp(V, axis=0)) - np.abs(dt)) / (br["depth"] * np.linalg.norm(np.ptp(V, axis=0)) * (1 - br["full_within"])), 0, 1)   # у края глубины вес спадает: стенки рельефа не рвутся
    V2[near] += np.outer(w * dt, a)
    moved[near] = True
    Fi = np.asarray(F, np.int64)
    for _ in range(8):                                                   # защита: перевёрнутые грани → вершины возвращаются
        fl = _face_flips(V, V2, Fi)
        if not fl.any():
            break
        bad = np.unique(Fi[fl])
        V2[bad] = V[bad]
        moved[bad] = False
    rep["verts_moved"] = int(moved.sum())
    rep["photo_touched"] = int((moved & protect).sum()) if protect is not None else None
    rep["shift_max_pct"] = round(float(np.linalg.norm(V2 - V, axis=1).max() / np.linalg.norm(np.ptp(V, axis=0)) * 100), 4)
    rep["flipped_after"] = int(_face_flips(V, V2, np.asarray(F, np.int64)).sum())
    return V2, moved, rep


def back_panel_gate(role: str | None, reg: dict | None = None, rules: dict | None = None) -> dict:
    """Допуск `back_panel` по ТИПУ товара (А1 type-rules-code-01): политика паспорта `mesh_type_passports.paint_policy(роль)` обязана совпасть с `back_panel.paint_gate` правил
    (hidden_pattern и mode). Своего списка ролей у режима нет (список был дублем политики и убран). → {allowed, reason, policy}. Нет роли/типа/политики → не allowed с кодом причины."""
    import mesh_type_passports as MTP
    g = (rules or load_rules())["back_panel"].get("paint_gate") or {}
    pol = MTP.paint_policy(role, reg)
    want_hp, want_mode = g.get("hidden_pattern"), g.get("mode")
    if not want_hp or not want_mode:
        return {"allowed": False, "reason": "нет back_panel.paint_gate в rules/edge-sharpen.json", "policy": pol}
    if pol["hidden_pattern"] != want_hp:
        return {"allowed": False, "reason": f"тип «{pol.get('type')}»: hidden_pattern={pol['hidden_pattern']} ({pol.get('reason') or 'policy'}), нужен {want_hp}", "policy": pol}
    if pol["mode"] != want_mode:
        return {"allowed": False, "reason": f"тип «{pol.get('type')}»: paint.mode={pol['mode']}, нужен {want_mode}", "policy": pol}
    return {"allowed": True, "reason": "", "policy": pol}


def camera_dir(az_deg: float, el_deg: float) -> np.ndarray:
    """Направление от предмета на камеру в осях GLB для азимута/высоты камеры фото (этап 4, `06-visible/check.json: extra.camera`): так же, как `camera-orbit` у model-viewer (az 0 — со стороны +Z)."""
    a, e = np.radians(az_deg), np.radians(el_deg)
    return np.array([np.sin(a) * np.cos(e), np.sin(e), np.cos(a) * np.cos(e)])


def pose_edge_min() -> float:
    """Порог согласия внутренних кромок камеры этапа 4 — тот же, что у самого этапа (`camera-check.json: edge_ref`), одним источником."""
    with open(os.path.join(os.path.dirname(RULES_PATH), "camera-check.json"), encoding="utf-8") as f:
        return float(json.load(f)["edge_ref"])


def photo_faces(visible_glb: str, prov_png: str, values):
    """Грани этапа 6 с фото-текселями (prov ∈ values) → (позиции вершин этих граней (N,3), средняя нормаль по площади, число граней). Нужны trimesh и Pillow."""
    import trimesh
    from PIL import Image
    m = trimesh.load(visible_glb, force="mesh")
    prov = np.asarray(Image.open(prov_png))
    prov = prov if prov.ndim == 2 else prov[..., 0]
    uv = np.asarray(m.visual.uv).reshape(-1, 2)
    f = np.asarray(m.faces)
    c = uv[f].mean(1)
    t = prov.shape[0]
    p = prov[np.clip(((1 - c[:, 1]) * t).astype(int), 0, t - 1), np.clip((c[:, 0] * t).astype(int), 0, t - 1)]
    sel = np.isin(p, list(values))
    if not sel.any():
        return np.zeros((0, 3)), np.zeros(3), 0
    n = (m.face_normals[sel] * m.area_faces[sel, None]).sum(0)
    return np.asarray(m.vertices)[np.unique(f[sel])], n / (np.linalg.norm(n) + 1e-12), int(sel.sum())


def back_panel_glb(src: str, dst: str, az_deg: float, el_deg: float, rules: dict | None = None, pose_edge: float | None = None, photo: tuple | None = None) -> dict:
    """GLB (одна геометрия, float32-позиции) → GLB с выровненным задом: двигаются только положения вершин (и нормали вершин сдвинутых граней — пересчитаны по новой форме), всё остальное байт в байт.
    Расчёт — на склеенной по положению форме (glTF режет вершины по швам), результат раздаётся обратно по всем копиям вершины. → отчёт `back_panel` + {'written': bool}.
    Защиты (T-20261123-41/2): `pose_edge` — согласие кромок камеры этапа 4; ниже порога этапа (`camera-check.json: edge_ref`) азимуту не верим (по силуэту «перед» и «зад» корпусной не различить) → не трогаем;
    `photo=(visible.glb, prov.png)` этапа 6 — сторона с фото-текселями никогда не двигается, а её нормаль должна совпасть с камерой (иначе отказ)."""
    import struct
    rules = rules or load_rules()
    with open(src, "rb") as fh:
        data = fh.read()
    jl, _ = struct.unpack_from("<II", data, 12)
    js = json.loads(data[20:20 + jl])
    bo = 20 + jl + 8
    blen = struct.unpack_from("<I", data, 20 + jl)[0]
    buf = bytearray(data[bo:bo + blen])
    prims = [p for m in js["meshes"] for p in m["primitives"]]
    if len(prims) != 1:
        return {"apply": False, "reason": f"геометрий {len(prims)}, нужна одна", "written": False}
    pr = prims[0]
    if pose_edge is not None and pose_edge < pose_edge_min():
        return {"apply": False, "reason": f"камере не верим: согласие кромок {pose_edge:.3f} < {pose_edge_min():g} (по силуэту перед и зад не различить) — зад не трогаем", "written": False}

    def view(i, dt, n):
        a = js["accessors"][i]
        bv = js["bufferViews"][a["bufferView"]]
        off = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
        if bv.get("byteStride") not in (None, n * np.dtype(dt).itemsize):
            raise ValueError("чересстрочные атрибуты не поддержаны")
        return np.frombuffer(buf, dt, a["count"] * n, off).reshape(-1, n)
    pos = view(pr["attributes"]["POSITION"], np.float32, 3)
    ia = js["accessors"][pr["indices"]]
    F = view(pr["indices"], {5123: np.uint16, 5125: np.uint32}[ia["componentType"]], 1).reshape(-1, 3).astype(np.int64)
    V = pos.astype(np.float64)
    key = np.round(V / (np.ptp(V, axis=0).max() * 1e-6)).astype(np.int64)
    _, first, inv = np.unique(key, axis=0, return_index=True, return_inverse=True)
    inv = inv.reshape(-1)
    Vw = V[first]
    Fw = inv[F]
    Fw = Fw[(Fw[:, 0] != Fw[:, 1]) & (Fw[:, 1] != Fw[:, 2]) & (Fw[:, 0] != Fw[:, 2])]
    cam = camera_dir(az_deg, el_deg)
    prot = None
    ph_info = {}
    if photo is not None:
        pv, pn, pf = photo_faces(photo[0], photo[1], rules["back_panel"]["photo_prov"])
        ph_info = {"photo_faces": pf, "photo_n_cam": round(float(pn @ cam), 3) if pf else None}
        if pf == 0:
            return {"apply": False, "reason": "на этапе 6 нет граней с фото — сторону с фото не определить", "written": False, **ph_info}
        if float(pn @ cam) < rules["back_panel"]["photo_cos_min"]:
            return {"apply": False, "reason": f"сторона с фото (cos {float(pn @ cam):.2f}) не совпадает с камерой — не трогаем", "written": False, **ph_info}
        scale = np.ptp(V, axis=0).max() * 1e-6
        kw = np.round(Vw / scale).astype(np.int64)
        kp = np.round(pv / scale).astype(np.int64)
        _, ii = np.unique(np.concatenate([kw, kp]), axis=0, return_inverse=True)
        ii = ii.reshape(-1)
        prot = np.isin(ii[:len(kw)], ii[len(kw):])
        ph_info["photo_verts"] = int(prot.sum())
    V2w, moved_w, rep = back_panel(Vw, Fw, cam, rules, protect=prot)
    rep.update(ph_info)
    rep["written"] = False
    if not rep["apply"]:
        return rep
    pos[:] = V2w[inv].astype(np.float32)
    mv = moved_w[inv]
    if "NORMAL" in pr["attributes"]:
        nrm = view(pr["attributes"]["NORMAL"], np.float32, 3)
        a_ = np.asarray(rep["axis"])                                                                   # нормали на выровненном заду — «от камеры» (хранимые нормали рельефа иначе рисуют его тенью)
        vn_old = context(Vw, Fw, rules)["vn"]
        fix = moved_w | ((np.abs(V2w @ a_ - rep["back_level"]) <= 2 * rules["tol_plane"] * np.linalg.norm(np.ptp(Vw, axis=0))) & (vn_old @ a_ < -0.3))
        nrm[fix[inv]] = (-a_).astype(np.float32)
    a_pos = js["accessors"][pr["attributes"]["POSITION"]]
    a_pos["min"], a_pos["max"] = pos.min(0).astype(float).tolist(), pos.max(0).astype(float).tolist()
    jb = json.dumps(js, ensure_ascii=False, separators=(",", ":")).encode()
    jb += b" " * (-len(jb) % 4)
    out = struct.pack("<4sII", b"glTF", 2, 12 + 8 + len(jb) + 8 + len(buf)) + struct.pack("<I4s", len(jb), b"JSON") + jb + struct.pack("<I4s", len(buf), b"BIN\x00") + bytes(buf)
    with open(dst, "wb") as f:
        f.write(out)
    rep["written"] = True
    return rep


def check() -> int:
    r = load_rules()
    need = ["roles", "tol_plane", "min_plane_share", "max_planes", "normal_cos_min", "ransac_trials", "ransac_sample", "smooth_rings", "edge_angle_min_deg", "edge_band", "edge_min_verts",
            "edge_min_len", "edge_normal_cos_min", "max_shift", "full_within", "flat_share_min", "seed", "back_panel"]
    miss = [k for k in need if k not in r]
    if miss:
        print("edge-sharpen: в правилах нет", miss)
        return 1
    if not (0 < r["tol_plane"] < 0.02 and 0 < r["edge_band"] <= 0.05 and r["max_shift"] >= r["tol_plane"] and 0 < r["full_within"] < 1 and r["roles"]):
        print("edge-sharpen: пороги вне разумного")
        return 1
    bp = r["back_panel"]
    if not all(k in bp for k in ("paint_gate", "front_cos_min", "axis_snap_deg", "back_cos_min", "depth", "full_within", "rim_cells", "slope_cos_max", "grid", "min_cells", "plane_share_min", "relief_share_min", "corr_smooth_cells", "photo_prov", "photo_cos_min")) or not (0 < bp["depth"] <= 0.2 and 0 < bp["plane_share_min"] <= 1):
        print("edge-sharpen: back_panel — нет порогов или они вне разумного")
        return 1
    try:
        pose_edge_min()
    except (OSError, KeyError, ValueError):
        print("edge-sharpen: нет edge_ref в camera-check.json (порог доверия азимуту)")
        return 1
    print("edge-sharpen: правила целы")
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "back-glb":                  # back-glb SRC DST AZ EL — выровнять зад GLB (проба; в конвейере — `back_panel`)
        ex = dict(a.split("=", 1) for a in sys.argv[6:])                 # необязательно: edge=<согласие кромок этапа 4> visible=<06 visible.glb> prov=<06 prov.png> role=<роль каталога — допуск по паспорту типа>
        if "role" in ex and not back_panel_gate(ex["role"])["allowed"]:
            print(json.dumps({"apply": False, "written": False, "reason": back_panel_gate(ex["role"])["reason"]}, ensure_ascii=False))
            sys.exit(0)
        r_ = back_panel_glb(sys.argv[2], sys.argv[3], float(sys.argv[4]), float(sys.argv[5]), pose_edge=float(ex["edge"]) if "edge" in ex else None,
                            photo=(ex["visible"], ex["prov"]) if "visible" in ex and "prov" in ex else None)
        print(json.dumps(r_, ensure_ascii=False))
        sys.exit(0)
    sys.exit(check() if len(sys.argv) > 1 and sys.argv[1] == "check" else 2)
