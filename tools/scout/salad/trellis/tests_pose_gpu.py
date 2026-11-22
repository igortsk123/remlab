#!/usr/bin/env python3
"""Тест бэкенда pose_gpu (T-185/1) на torch-CPU против numpy/cv2 на синтетической форме (коробка с «спинкой»): силуэт точек — побитно; кадр поиска — маска расходится не больше порога.
Видеокарта не нужна: тот же код на 'cuda' даёт то же (проверяется пробой на Salad по compare_pose, не здесь). Нужны numpy, opencv, torch (CPU-колесо достаточно)."""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
fails = 0


def ok(cond, name, extra=''):
    global fails
    print(('  ✓ ' if cond else '  ✗ ') + name + ('' if cond else f' — {extra}'))
    fails += 0 if cond else 1


import importlib.util  # noqa: E402

if importlib.util.find_spec("torch") is None:
    print('torch не установлен — тест бэкенда пропущен (в CI ставится CPU-колесо)')
    sys.exit(0)
import pose_fit as PF  # noqa: E402
import pose_gpu as PG  # noqa: E402


def box_geo(sx=0.6, sy=0.3, sz=0.35, back=True):
    """Куб-коробка (12 граней) + при `back` доска-«спинка» сзади: V, F, UV, N как в to_cube_geo."""
    def one(c, s):
        x0, y0, z0 = c[0] - s[0] / 2, c[1] - s[1] / 2, c[2] - s[2] / 2
        x1, y1, z1 = c[0] + s[0] / 2, c[1] + s[1] / 2, c[2] + s[2] / 2
        V = np.array([[x0, y0, z0], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0], [x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1]], np.float64)
        F = np.array([[0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7], [0, 1, 5], [0, 5, 4], [3, 7, 6], [3, 6, 2], [0, 4, 7], [0, 7, 3], [1, 2, 6], [1, 6, 5]])
        return V, F
    V, F = one((0, 0, 0), (sx, sy, sz))
    if back:
        V2, F2 = one((0, 0.25, -sz / 2 + 0.03), (sx, 0.45, 0.06))
        F = np.vstack([F, F2 + len(V)])
        V = np.vstack([V, V2])
    P = V - V.mean(0)
    P = P / np.abs(P).max() * 0.35
    N = np.zeros((len(F), 3))
    for i, f in enumerate(F):
        n = np.cross(P[f[1]] - P[f[0]], P[f[2]] - P[f[0]])
        N[i] = n / (np.linalg.norm(n) or 1.0)
    UV = np.zeros((len(P), 2))
    return {'V': P, 'F': F, 'UV': UV, 'N': N}


geo = box_geo()
rng = np.random.default_rng(3)
pts = np.vstack([geo['V'][geo['F']].mean(1)] + [geo['V'][geo['F']][:, k] * w + geo['V'][geo['F']][:, (k + 1) % 3] * (1 - w) for k in range(3) for w in (0.3, 0.7)])
pts = np.vstack([pts, rng.uniform(-0.15, 0.15, (4000, 3))])
be = PG.Backend('cpu')
bad_splat, bad_render, worst = 0, 0, 0.0
for az, el, d in ((30.0, 15.0, 2.2), (-40.0, 25.0, 1.9), (75.0, 8.0, 2.6), (160.0, 35.0, 2.0), (0.0, 0.0, 2.4)):
    cam = {'az': az, 'el': el, 'd': d, 'f': 1.1, 'cx': 0.01, 'cy': -0.02}
    a = PF.splat_mask(pts, cam, 256)
    PF._BACKEND = be
    try:
        b = PF.splat_mask(pts, cam, 256)
    finally:
        PF._BACKEND = None
    bad_splat += int((a != b).sum())
    r0, r1 = PF.render_persp(geo, cam, 256), be.render(geo, cam, 256)
    frac = float((r0['mask'] ^ r1['mask']).sum()) / max(1, int(r0['mask'].sum()))
    worst = max(worst, frac)
    bad_render += int(frac > 0.02 or r0['mask'].sum() == 0)
ok(bad_splat == 0, 'splat_mask на torch-CPU совпадает с numpy/cv2 побитно (5 камер)', f'расхождений {bad_splat} px')
ok(bad_render == 0, f'кадр поиска: маска расходится ≤ 2 % площади (худший {worst:.4f}, 5 камер)', f'худший {worst:.4f}')
PF.set_backend('cpu')
ok(PF._BACKEND is not None, 'set_backend("cpu") включает бэкенд')
PF.set_backend(None)
ok(PF._BACKEND is None, 'set_backend(None) возвращает numpy/cv2 (по умолчанию — прежний путь)')
print('ИТОГО: ' + ('всё в норме' if not fails else f'провалов {fails}'))
sys.exit(1 if fails else 0)
