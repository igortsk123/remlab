"""Граница частей плоскостью (T-20261124-64 продолжение, совет Fable А2 «жёсткую мебель режем плоскостью, не зубчатыми метками граней»). Вхолостую: в покраску не подключено.

ЗАЧЕМ. Меш TRELLIS не плоский: у верха шкафа тысячи мелких «панелей» (излом ≤15° их не склеивает), роль по граням даёт зубчатую границу. Плоская стенка предмета — одна роль целиком.

`merge_planes` — склейка почти копланарных граней в крупные плоскости (функция р.2, T-69/2: `~/remlab-logs/t2469-1124/planes.py`; перенесена без изменения смысла, соседство граней — из `parts_role_cleanup.edge_graph`).
`plane_vote` — снап ролей к плоскостям: у каждой значимой плоскости известные роли голосуют по площади; победила роль с долей ≥ `vote_min` — все её грани с другой известной ролью переходят к победителю
   (граница роли ложится на край плоскости, а не поперёк неё). Не трогаем: роли `keep_roles` чистки (ручки, ножки, каркас, плафон, стекло — рамка в плоскости фасада остаётся рамкой) и `unknown` (не выдумываем роль);
   плоскость без явного победителя (<`vote_min`) не меняется. Новых ролей не создаётся.
`snap_and_clean` — снап, затем обычная чистка (`parts_role_cleanup.clean_roles`), чтобы острова и зубцы вне плоскостей тоже ушли.
Правила — `tools/scout/rules/part-role-planes.json` (пороги стартовые, под 29 не подгонять). ID товаров и имён частей нет. Мерки до/после — `parts_role_cleanup.boundary_metrics`.
"""
from __future__ import annotations

import json
import os
import sys
from collections import deque
from dataclasses import dataclass

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import parts_role_cleanup as prc  # noqa: E402

RULES = os.path.join(HERE, "..", "scout", "rules", "part-role-planes.json")


def load_rules(path: str = RULES) -> dict:
    with open(path, encoding="utf-8") as fh:
        r = json.load(fh)
    if not (0 < r["ang_deg"] < 45) or not (0 < r["tol_rel"] < 0.1) or not (0 < r["min_share"] < 0.5) or not (0.5 < r["vote_min"] <= 1):
        raise ValueError("part-role-planes.json: пороги вне допустимых пределов")
    return r


@dataclass
class Planes:
    face_plane: object      # (m,) id плоскости на грань; -1 — не плоскость (кривая/осколок)
    normal: object          # (k,3) единичная нормаль (площадно-средняя)
    offset: object          # (k,)  n·x = d
    area: object            # (k,)
    n_faces: object         # (k,)
    rms: object             # (k,) СКО расстояния центров граней до плоскости
    significant: object     # (k,) bool: площадь ≥ min_share


def merge_planes(V, F, ang_deg: float = 12.0, tol_rel: float = 0.005, min_share: float = 0.004, eg: dict | None = None) -> Planes:
    """Рост плоскостей от самых больших граней: грань берётся, если угол к СРЕДНЕЙ нормали плоскости ≤ ang_deg и расстояние центра до плоскости ≤ tol_rel·диагональ (сравнение со средней плоскостью, не
    с соседней гранью — плавный изгиб не «ползёт»); затем 3 прохода: мелкие осколки, примыкающие к большой плоскости, прикрепляются при допусках ×2."""
    import numpy as np

    V = np.asarray(V, np.float64)
    F = np.asarray(F, np.int64)
    scale = float(np.linalg.norm(V.max(0) - V.min(0)))
    tol = tol_rel * scale
    cosmin = np.cos(np.radians(ang_deg))
    eg = eg or prc.edge_graph(V, F)
    nb = [[] for _ in range(len(F))]
    for x, y in zip(eg["fa"].tolist(), eg["fb"].tolist()):
        nb[x].append(y)
        nb[y].append(x)
    A, B, C = V[F[:, 0]], V[F[:, 1]], V[F[:, 2]]
    cr = np.cross(B - A, C - A)
    area = 0.5 * np.linalg.norm(cr, axis=1)
    nf = cr / np.maximum(2 * area, 1e-30)[:, None]
    cen = (A + B + C) / 3.0
    fp = np.full(len(F), -1, np.int64)
    sums: list = []

    def plane_of(k):
        sn, sc, sa = sums[k]
        n = sn / max(np.linalg.norm(sn), 1e-30)
        return n, float(n @ (sc / sa))

    def grow(seed):
        k = len(sums)
        a = area[seed]
        sums.append([nf[seed] * a, cen[seed] * a, a])
        fp[seed] = k
        q = deque([seed])
        while q:
            f = q.popleft()
            for g in nb[f]:
                if fp[g] != -1:
                    continue
                n, d = plane_of(k)
                if nf[g] @ n >= cosmin and abs(n @ cen[g] - d) <= tol:
                    fp[g] = k
                    s = sums[k]
                    ag = area[g]
                    s[0] = s[0] + nf[g] * ag
                    s[1] = s[1] + cen[g] * ag
                    s[2] = s[2] + ag
                    q.append(g)
        return k

    for seed in np.argsort(-area).tolist():
        if fp[seed] == -1:
            grow(seed)
    k_all = len(sums)
    total = float(area.sum())
    ar_pl = np.array([s[2] for s in sums])
    big = ar_pl >= min_share * total
    cos2 = np.cos(np.radians(2 * ang_deg))
    for _ in range(3):
        changed = 0
        for f in np.nonzero(~big[fp])[0].tolist():
            best = None
            for g in nb[f]:
                kg = fp[g]
                if kg != fp[f] and big[kg]:
                    n, d = plane_of(kg)
                    if nf[f] @ n >= cos2 and abs(n @ cen[f] - d) <= 2 * tol:
                        sc = abs(n @ cen[f] - d)
                        if best is None or sc < best[0]:
                            best = (sc, kg)
            if best is not None:
                fp[f] = best[1]
                changed += 1
        if not changed:
            break
    ar = np.bincount(fp[fp >= 0], weights=area[fp >= 0], minlength=k_all)
    keep = np.nonzero(ar >= min_share * total)[0]
    remap = np.full(k_all, -1, np.int64)
    remap[keep] = np.arange(len(keep))
    out = np.where(fp >= 0, remap[np.clip(fp, 0, k_all - 1)], -1)
    nk = len(keep)
    normal, off, ar2, nfc, rms = np.zeros((nk, 3)), np.zeros(nk), np.zeros(nk), np.zeros(nk, np.int64), np.zeros(nk)
    for j in range(nk):
        m = out == j
        a = area[m]
        sn = (nf[m] * a[:, None]).sum(0)
        n = sn / max(np.linalg.norm(sn), 1e-30)
        d = float(n @ ((cen[m] * a[:, None]).sum(0) / a.sum()))
        normal[j], off[j], ar2[j], nfc[j] = n, d, a.sum(), m.sum()
        rms[j] = float(np.sqrt((a * (cen[m] @ n - d) ** 2).sum() / a.sum()))
    return Planes(out, normal, off, ar2, nfc, rms, ar2 >= min_share * total)


def plane_vote(face_plane, area, role, known, rules: dict, keep=()):
    """Снап ролей к плоскостям (см. модуль). → (новые роли, {'planes_voted', 'faces_snapped', 'planes_undecided'})."""
    import numpy as np

    role = np.array(role, dtype=object).astype(str).copy()
    fp = np.asarray(face_plane)
    kn = np.isin(role, [r for r in known if r not in keep])
    rep = {"planes_voted": 0, "faces_snapped": 0, "planes_undecided": 0}
    sel = kn & (fp >= 0)
    if not sel.any():
        return role, rep
    names = sorted({str(x) for x in role[sel]})
    ni = {n: i for i, n in enumerate(names)}
    rid = np.array([ni[x] for x in role[sel]])
    k = int(fp.max()) + 1
    W = np.bincount(fp[sel] * len(names) + rid, weights=np.asarray(area)[sel], minlength=k * len(names)).reshape(k, len(names))
    tot = W.sum(axis=1)
    best = W.argmax(axis=1)
    share = np.where(tot > 0, W.max(axis=1) / np.maximum(tot, 1e-30), 0.0)
    for p in np.nonzero((tot > 0) & ((W > 0).sum(axis=1) > 1))[0]:
        if share[p] >= rules["vote_min"]:
            m = sel & (fp == p) & (role != names[best[p]])
            role[m] = names[best[p]]
            rep["planes_voted"] += 1
            rep["faces_snapped"] += int(m.sum())
        else:
            rep["planes_undecided"] += 1
    return role, rep


def snap_and_clean(eg: dict, face_plane, role, known, plane_rules: dict, clean_rules: dict):
    """Снап к плоскостям, затем обычная чистка. → (роли, отчёт {'snap': …, 'clean': …})."""
    import numpy as np

    snapped, rs = plane_vote(face_plane, eg["area"], role, known, plane_rules, keep=set(clean_rules["keep_roles"]))
    new, rc = prc.clean_roles(eg, snapped, known, clean_rules)
    return new, {"snap": rs, "clean": rc, "changed_faces": int((new != np.asarray(role).astype(str)).sum())}
