"""Чистка меток ролей ДО покраски + три мерки границ ролей (T-20261124-64, Ш1; ответ советника Fable 24.11, п.А1–А7). Вхолостую: в покраску не подключено.

ЗАЧЕМ. Меш сшит из неровных граней: роль, поставленная по граням, даёт зубчатую границу и мелкие острова — на них краска «нахлёстывает» (бок крашен тоном фасада). Правило советника: каждая грань — ровно одна роль;
чистим метки до покраски, после покраски только проверяем по кадру.

ЧИСТКА (`clean_roles`, правила — `tools/scout/rules/part-role-cleanup.json`, ID товаров нет):
  1. острова — связный кусок роли < `island_share` площади этой роли (и не самый большой кусок) вливается в соседа с самой длинной общей границей; роли из `keep_roles` (ручки, ножки, каркас, плафон, стекло — мелкое
     и контрастное по смыслу) НЕ вливаются никогда (п.А4: наконечники ножек, ручки, деревянные подлокотники не перекрашиваем);
  2. зубцы — фильтр большинства ТОЛЬКО по пологим рёбрам (излом < `sharp_deg`) и только в узкой полосе (`smooth_iters` шагов): грань берёт роль, за которую ≥ `vote_min` её соседей, если эта роль не из keep_roles;
     по острым рёбрам (стык панелей, угол корпуса) границы не трогаем — они и так ровные (п.А2: жёсткую мебель режем по плоскости, не по зубчатым меткам);
  3. рамка в плоскости фасада и фасад-«рисунок» не делятся: чистка не создаёт новых ролей и не делит куски — только вливает мелкое в соседнее и сглаживает полосу.
МЕРКИ (`boundary_metrics`, на роли с `known`; пороги стартовые, на 29 не подгонять — п.А6): доля длины границы на остром ребре (жёсткая ≥ `sharp_share_min` = 0,8); рваность = длина границы ÷ длина её упрощённого контура
(Дуглас–Пекер, допуск `ragged_tol_diag` диагонали меша; > `ragged_max` = 1,3 — брак; цепочка — отрезок границы между развилками); острова < 1 % площади роли — число и доля (цель 0).
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RULES = os.path.join(HERE, "..", "scout", "rules", "part-role-cleanup.json")
TRELLIS = os.path.join(HERE, "..", "scout", "salad", "trellis")


def load_rules(path: str = RULES) -> dict:
    with open(path, encoding="utf-8") as fh:
        r = json.load(fh)
    if not (0 < r["island_share"] < 0.5) or not (0 < r["sharp_deg"] < 90) or not (0.5 < r["vote_min"] <= 1) or r["smooth_iters"] < 0:
        raise ValueError("part-role-cleanup.json: пороги вне допустимых пределов")
    return r


def _weld_ids(vertices):
    import numpy as np

    for p in (TRELLIS, os.path.dirname(TRELLIS), os.path.dirname(os.path.dirname(TRELLIS))):
        p = os.path.abspath(p)
        if p not in sys.path:
            sys.path.insert(0, p)
    import ref_zone as rz

    q = np.round(np.asarray(vertices, np.float64) / rz.WELD).astype(np.int64)
    _u, inv = np.unique(q, axis=0, return_inverse=True)
    return np.asarray(inv).reshape(-1)


def edge_graph(vertices, faces) -> dict:
    """Общие рёбра граней по сваренным вершинам: fa, fb (грани), ua, ub (сваренные вершины ребра), length, fold (градусы между плоскостями граней, 0…90 — обмотка мешей не согласована, знак не берём)."""
    import numpy as np

    V = np.asarray(vertices, np.float64)
    F = np.asarray(faces, np.int64)
    w = _weld_ids(V)
    Fw = w[F]
    e = np.concatenate([Fw[:, [0, 1]], Fw[:, [1, 2]], Fw[:, [2, 0]]])
    eo = np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]])
    fi = np.tile(np.arange(len(F)), 3)
    ok = e[:, 0] != e[:, 1]
    e, eo, fi = e[ok], eo[ok], fi[ok]
    key = np.sort(e, axis=1)
    kk = key[:, 0].astype(np.int64) * (int(w.max()) + 1) + key[:, 1]
    o = np.argsort(kk, kind="stable")
    kk, fi, key, eo = kk[o], fi[o], key[o], eo[o]
    same = kk[1:] == kk[:-1]
    fa, fb = fi[:-1][same], fi[1:][same]
    keep = fa != fb
    fa, fb = fa[keep], fb[keep]
    ua, ub = key[:-1][same][keep, 0], key[:-1][same][keep, 1]
    ev = eo[:-1][same][keep]
    length = np.linalg.norm(V[ev[:, 0]] - V[ev[:, 1]], axis=1)
    t = V[F]
    n = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
    n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
    fold = np.degrees(np.arccos(np.clip(np.abs((n[fa] * n[fb]).sum(axis=1)), 0.0, 1.0)))
    area = np.linalg.norm(np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0]), axis=1) / 2
    return {"fa": fa, "fb": fb, "ua": ua, "ub": ub, "length": length, "fold": fold, "area": area, "V": V, "n_faces": len(F), "_w": w, "_wf": F}


def _components(n, a, b, mask=None):
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components

    import numpy as np

    if mask is not None:
        a, b = a[mask], b[mask]
    g = coo_matrix((np.ones(2 * len(a)), (np.concatenate([a, b]), np.concatenate([b, a]))), shape=(n, n)).tocsr()
    return connected_components(g, directed=False)[1]


def _dp_len(pts, tol):
    """Длина упрощённой ломаной (Дуглас–Пекер, итеративно) в точках pts (k×3)."""
    import numpy as np

    k = len(pts)
    if k < 3:
        return float(np.linalg.norm(pts[-1] - pts[0])) if k == 2 else 0.0
    keep = np.zeros(k, bool)
    keep[0] = keep[-1] = True
    st = [(0, k - 1)]
    while st:
        i, j = st.pop()
        if j <= i + 1:
            continue
        a, b = pts[i], pts[j]
        ab = b - a
        L2 = float(ab @ ab)
        seg = pts[i + 1:j]
        d = np.linalg.norm(np.cross(seg - a, ab), axis=1) / max(np.sqrt(L2), 1e-12) if L2 > 1e-18 else np.linalg.norm(seg - a, axis=1)
        m = int(np.argmax(d))
        if d[m] > tol:
            keep[i + 1 + m] = True
            st += [(i, i + 1 + m), (i + 1 + m, j)]
    q = pts[keep]
    return float(np.linalg.norm(np.diff(q, axis=0), axis=1).sum())


def _chains(ua, ub):
    """Цепочки границы: пути между вершинами со степенью ≠ 2 (развилки, концы) и замкнутые петли → список списков вершин."""
    adj: dict = {}
    for k, (u, v) in enumerate(zip(ua.tolist(), ub.tolist())):
        adj.setdefault(u, []).append((v, k))
        adj.setdefault(v, []).append((u, k))
    used: set = set()
    out = []

    def walk(start, first):
        path = [start]
        cur, k = first
        while True:
            used.add(k)
            path.append(cur)
            if len(adj[cur]) != 2:
                break
            nxt = [x for x in adj[cur] if x[1] not in used]
            if not nxt:
                break
            cur, k = nxt[0]
        return path

    for u, nb in adj.items():
        if len(nb) != 2:
            for first in nb:
                if first[1] not in used:
                    out.append(walk(u, first))
    for u, nb in adj.items():
        for first in nb:
            if first[1] not in used:
                out.append(walk(u, first))
    return out


def boundary_metrics(eg: dict, role, known, rules: dict) -> dict:
    """Три мерки до покраски по ролям граней `role` (строки) на графе рёбер `eg`; границы — только между двумя известными ролями (`known` — множество ролей).
    → {'boundary_len', 'sharp_share', 'ragged_ratio', 'ragged_share', 'islands': {'count', 'area_share'}, 'ok': {...}}."""
    import numpy as np

    fa, fb, ln, fold = eg["fa"], eg["fb"], eg["length"], eg["fold"]
    kn = np.isin(role, list(known))
    bd = (role[fa] != role[fb]) & kn[fa] & kn[fb]
    L = float(ln[bd].sum())
    out = {"boundary_len": round(L, 4), "sharp_share": None, "ragged_ratio": None, "ragged_share": None}
    if L > 0:
        out["sharp_share"] = round(float(ln[bd & (fold >= rules["sharp_deg"])].sum() / L), 4)
        diag = float(np.linalg.norm(eg["V"].max(0) - eg["V"].min(0)))
        tol = rules["ragged_tol_diag"] * diag
        pos = _weld_positions(eg)
        tot = simp = rag = 0.0
        for ch in _chains(eg["ua"][bd], eg["ub"][bd]):
            pts = pos[ch]
            lc = float(np.linalg.norm(np.diff(pts, axis=0), axis=1).sum())
            ls = _dp_len(pts, tol)
            tot += lc
            simp += min(ls, lc) if ls > 0 else lc
            if ls > 0 and lc / ls > rules["ragged_max"]:
                rag += lc
        out["ragged_ratio"] = round(tot / simp, 4) if simp > 0 else None
        out["ragged_share"] = round(rag / tot, 4) if tot > 0 else 0.0
    keep = set(rules["keep_roles"])
    cnt, share = islands(eg, role, kn, rules["island_share_metric"], skip=keep)
    cnt_all, _sh = islands(eg, role, kn, rules["island_share_metric"])
    out["islands"] = {"count": cnt, "area_share": round(share, 4), "kept_small_roles": cnt_all - cnt}      # keep-роли (ручки, ножки…) чистка не трогает — считаем отдельно
    out["ok"] = {"sharp": None if out["sharp_share"] is None else out["sharp_share"] >= rules["sharp_share_min"],
                 "ragged": None if out["ragged_ratio"] is None else out["ragged_ratio"] <= rules["ragged_max"],
                 "islands": cnt == 0}
    return out


def _weld_positions(eg):
    """Положение сваренной вершины = положение первой попавшейся исходной (сварка — допуск ref_zone.WELD, различие ничтожно)."""
    import numpy as np

    pos = eg.get("_pos")
    if pos is None:
        w = eg["_w"]
        pos = np.zeros((int(w.max()) + 1, 3))
        pos[w] = eg["V"]
        eg["_pos"] = pos
    return pos


def _comp_stats(eg, role, kn):
    """Связные куски роли (по общим рёбрам одной роли): метка куска по граням, площадь куска, роль куска, «самый большой кусок своей роли», площадь роли."""
    import numpy as np

    fa, fb = eg["fa"], eg["fb"]
    lab = _components(eg["n_faces"], fa, fb, (role[fa] == role[fb]) & kn[fa])
    ncomp = int(lab.max()) + 1
    carea = np.bincount(lab, weights=eg["area"], minlength=ncomp)
    first = np.zeros(ncomp, dtype=np.int64)
    first[lab[::-1]] = np.arange(len(lab))[::-1]                                    # первая грань куска
    crole = role[first]
    cknown = kn[first]
    rid = {r: i for i, r in enumerate(np.unique(crole[cknown]))} if cknown.any() else {}
    big = np.zeros(ncomp, bool)
    rtot = {}
    for r in rid:
        cs = np.nonzero((crole == r) & cknown)[0]
        rtot[r] = float(carea[cs].sum())
        big[cs[np.argmax(carea[cs])]] = True
    return lab, carea, crole, cknown, big, rtot


def islands(eg: dict, role, kn, share_max: float, skip=()):
    """Острова: связные куски одной роли (по общим рёбрам), кроме самого большого куска роли, с площадью < share_max площади роли. → (число, доля площади меша)."""
    import numpy as np

    lab, carea, crole, cknown, big, rtot = _comp_stats(eg, role, kn)
    tot = float(eg["area"].sum())
    cnt, ar = 0, 0.0
    for c in np.nonzero(cknown & ~big)[0]:
        if crole[c] in skip:
            continue
        if carea[c] < share_max * rtot[crole[c]]:
            cnt += 1
            ar += float(carea[c])
    return cnt, ar / tot if tot else 0.0


def clean_roles(eg: dict, role, known, rules: dict):
    """Чистка меток роли по граням (см. модуль): острова → сосед с самой длинной границей; зубцы — большинство по пологим рёбрам в узкой полосе. → (новые роли, отчёт {'islands_merged', 'faces_smoothed', 'kept_small_roles'})."""
    import numpy as np

    role = np.array(role, dtype=object).astype(str).copy()
    keep = set(rules["keep_roles"])
    kn = np.isin(role, list(known))
    fa, fb, ln, fold = eg["fa"], eg["fb"], eg["length"], eg["fold"]
    area = eg["area"]
    rep = {"islands_merged": 0, "faces_smoothed": 0, "kept_small_roles": 0}
    # 1. острова (до 3 проходов: слив острова может создать новый маленький кусок соседа)
    for _pass in range(3):
        kn = np.isin(role, list(known))
        lab, carea, crole, cknown, big, rtot = _comp_stats(eg, role, kn)
        small = np.zeros(len(carea), bool)
        for c in np.nonzero(cknown & ~big)[0]:
            if carea[c] < rules["island_share"] * rtot[crole[c]]:
                if crole[c] in keep:
                    rep["kept_small_roles"] += 1 if _pass == 0 else 0
                else:
                    small[c] = True
        if not small.any():
            break
        # соседи малых кусков: длина общей границы по ролям соседей
        la, lb = lab[fa], lab[fb]
        cross = la != lb
        rows = []
        for x, y in ((la, lb), (lb, la)):
            m = cross & small[x] & kn[np.where(x is la, fb, fa)]
            rows.append((x[m], role[np.where(x is la, fb, fa)][m], ln[m]))
        cs = np.concatenate([r_[0] for r_ in rows])
        nr = np.concatenate([r_[1] for r_ in rows])
        w = np.concatenate([r_[2] for r_ in rows])
        merged_now = 0
        if len(cs):
            keyr = {r: i for i, r in enumerate(np.unique(nr))}
            names = list(keyr)
            ki = np.array([keyr[x] for x in nr])
            tot_cr = np.bincount(cs * len(names) + ki, weights=w, minlength=len(carea) * len(names)).reshape(len(carea), len(names))
            for c in np.nonzero(small & (tot_cr.sum(axis=1) > 0))[0]:
                tw = tot_cr[c].copy()
                for j, nm_ in enumerate(names):
                    if nm_ == crole[c]:
                        tw[j] = 0.0
                if tw.max() <= 0:
                    continue
                role[lab == c] = names[int(np.argmax(tw))]
                rep["islands_merged"] += 1
                merged_now += 1
        if not merged_now:
            break
    # 2. зубцы: большинство в окрестности (соседи и соседи соседей) по пологим рёбрам, узкая полоса — `smooth_iters` шагов
    from scipy.sparse import coo_matrix

    flat = fold < rules["sharp_deg"]
    n = eg["n_faces"]
    sel0 = flat
    A1 = coo_matrix((np.ones(2 * int(sel0.sum())), (np.concatenate([fa[sel0], fb[sel0]]), np.concatenate([fb[sel0], fa[sel0]]))), shape=(n, n)).tocsr()
    A1.data[:] = 1.0
    A2 = (A1 @ A1)
    A2.data[:] = 1.0
    M = (A1 + A2).tocsr()
    M.data[:] = 1.0
    M.setdiag(0)
    M.eliminate_zeros()
    for _ in range(int(rules["smooth_iters"])):
        kn = np.isin(role, list(known))
        roles_k = [r for r in np.unique(role[kn])]
        new = role.copy()
        changed = 0
        tot = np.asarray(M @ kn.astype(float)).ravel()
        for r in roles_k:
            if r in keep:
                continue
            v = np.asarray(M @ (role == r).astype(float)).ravel()
            flip = kn & (role != r) & (tot > 0) & (v >= rules["vote_min"] * tot) & ~np.isin(role, list(keep))
            new[flip] = r
            changed += int(flip.sum())
        role = new
        rep["faces_smoothed"] += changed
        if not changed:
            break
    return role, rep
