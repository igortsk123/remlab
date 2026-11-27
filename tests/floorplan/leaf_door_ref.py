"""Эталон: leaf_door до векторизации (T-20261127-169/4, копия tools/floorplan/bench.py main e861dcdc3). Только для побайтной сверки
в tests/floorplan/test_leaf_door_fast.py; в боевой код не входит."""
from __future__ import annotations

import math

import numpy as np

import fpcore as fc  # noqa: F401
from bench import DOOR_EV, IN_R, IN_TH, LEAF_EMPTY, LEAF_JAMB_T, LEAF_R_M, _door_quad  # noqa: F401


def leaf_door_ref(g, thin, dark, arr, t, ppm, angles=(0.0, 90.0), inside=None):
    """T-20261111-13/4: одиночный короткий разрыв у стрелки, но рядом на листе — дуга створки (rgK p0 Family ↔ Utility: разрыв
    13 px между стрелкой и проёмом 86 см; p2 Bedroom 8 ↔ Playroom: разрыв у стрелки ступеней в 40 см от настоящей двери).
    Проём: от грани торца стены (по направлениям стен панели `angles`, не дальше R от разрыва) до встречной стены — пусто на R
    (LEAF_R_M), за ним стена; за гранью торца стена узкая (≤ LEAF_JAMB_T·t поперёк). Дуга створки 0–90° радиуса R — с петлёй у
    торца или у встречной стены (Family: петля на грани поперечной стены) — тонкие линии листа ≥ DOOR_EV. Разрыв — в зоне двери
    (до R от линии проёма). `dark` — тёмное листа, а не маска разбора: в ней проём бывает уже закрыт стеной (Family), а у торца со
    ступенькой в скелете нет конца (`fpcore.wall_ends` его не видит). → (cx, cy, R, quad, доля дуги) — дверь шириной R, или None."""
    H, W = thin.shape
    gc = np.array([g.cx, g.cy], float)
    r0, r1 = LEAF_R_M[0] * ppm, LEAF_R_M[1] * ppm
    th = np.radians(np.arange(0, 91, 5))
    solid = (dark > 0) & (arr == 0)
    jw = LEAF_JAMB_T * float(t)

    def near(m, p):
        xi, yi = int(round(p[0])), int(round(p[1]))
        y0, y1, x0, x1 = max(0, yi - 2), min(H, yi + 3), max(0, xi - 2), min(W, xi + 3)
        return y1 > y0 and x1 > x0 and bool(m[y0:y1, x0:x1].any())

    def at(p):
        xi, yi = int(round(p[0])), int(round(p[1]))
        return 0 <= xi < W and 0 <= yi < H and bool(solid[yi, xi])

    def dot(m, p):                                     # окно 3×3
        xi, yi = int(round(p[0])), int(round(p[1]))
        y0, y1, x0, x1 = max(0, yi - 1), min(H, yi + 2), max(0, xi - 1), min(W, xi + 2)
        return y1 > y0 and x1 > x0 and bool(m[y0:y1, x0:x1].any())

    def run(p, v, lim):
        k = 0
        while k < lim and at(p + v * (k + 1)):
            k += 1
        return k

    dirs = []
    for a in angles:
        v = np.array([math.cos(math.radians(a)), math.sin(math.radians(a))])
        for d in (v, -v, np.array([-v[1], v[0]]), np.array([v[1], -v[0]])):
            if all(float(d @ e) < 0.99 for e in dirs):
                dirs.append(d)
    R1 = int(r1 + t) + 2
    y0, y1, x0, x1 = max(0, int(gc[1]) - R1), min(H, int(gc[1]) + R1 + 1), max(0, int(gc[0]) - R1), min(W, int(gc[0]) + R1 + 1)
    ys, xs = np.nonzero(solid[y0:y1, x0:x1])
    best = None
    for d in dirs:
        nrm = np.array([-d[1], d[0]])
        for qx, qy in zip((xs + x0).tolist(), (ys + y0).tolist()):
            q = np.array([qx, qy], float)
            if at(q + d):
                continue                               # не грань в сторону d
            k = 1
            while k <= r1 + 1 and not at(q + d * k):
                k += 1
            R = float(k - 1)                           # пусто до встречной стены
            if k > r1 + 1 or R < r0:
                continue
            b = q - d * float(t)
            if not at(b) or 1 + run(b, nrm, jw) + run(b, -nrm, jw) > jw:
                continue                               # за гранью не узкий торец, а длинная стена
            seg = q + d * np.clip((gc - q) @ d, 0.0, R)
            if np.hypot(*(gc - seg)) > R:
                continue                               # разрыв не в зоне этой двери
            if inside is not None and not dot(inside, q + d * (R + 1.0) / 2.0):
                continue                               # T-20261112-48: середина двери — внутри заданного куска
            for s in (nrm, -nrm):
                for hc, dd in ((q, d), (q + d * (R + 1.0), -d)):    # петля у торца / у встречной стены
                    pts = hc[None, :] + R * (np.cos(th)[:, None] * dd[None, :] + np.sin(th)[:, None] * s[None, :])
                    sc = float(np.mean([near(thin, p) for p in pts]))
                    if sc < DOOR_EV or (best is not None and sc <= best[0] + 1e-9):
                        continue
                    ins = hc[None, :] + R * IN_R[:, None] * (np.cos(IN_TH)[:, None] * dd[None, :] +
                                                            np.sin(IN_TH)[:, None] * s[None, :])
                    if np.mean([dot(thin, p) for p in ins]) <= LEAF_EMPTY:   # внутри дуги пусто: не ступени/штриховка
                        best = (sc, q, d, nrm, R)
    if best is None:
        return None
    sc, q, d, nrm, R = best

    def face(v):                                       # грань торца вдоль ±nrm от q: стена, перед ней пусто
        k = 0
        while k < jw and at(q + v * (k + 1)) and not at(q + v * (k + 1) + d):
            k += 1
        return k
    jp, jm = face(nrm), face(-nrm)
    mid = q + nrm * (jp - jm) / 2.0
    quad = _door_quad(mid, d, nrm, 1.0, R, (jp + jm + 1) / 2.0 + 1.0)
    m = mid + d * (R + 1.0) / 2.0
    return float(m[0]), float(m[1]), R, quad, sc
