#!/usr/bin/env python3
"""Тесты `pose_shape_qa.py` (T-183/Ш2б): чистые функции аудита «поза или форма» на синтетике. Нужны numpy, scipy, opencv-python-headless.

  python3 tools/scout/salad/trellis/tests_pose_shape_qa.py
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.normpath(os.path.join(HERE, '..', '..')))
import numpy as np  # noqa: E402
import pose_shape_qa as Q  # noqa: E402

bad = 0


def check(name: str, ok: bool, extra: str = '') -> None:
    global bad
    if not ok:
        bad += 1
    print(('ok   ' if ok else 'FAIL ') + name + (f'  [{extra}]' if extra else ''))


R = Q.load_rules()
TH = R['thresholds']
H = W = 200


def rect(y0, y1, x0, x1):
    m = np.zeros((H, W), bool)
    m[y0:y1, x0:x1] = True
    return m


# — перёд/зад и вердикт позы —
a, b = {'az': 20.0}, {'az': 200.0}
check('az_flip: +180° — да', Q.az_flip(a, b, 30.0))
check('az_flip: +90° — нет', not Q.az_flip(a, {'az': 110.0}, 30.0))
check('az_flip: переход через 360°', Q.az_flip({'az': 350.0}, {'az': 175.0}, 30.0))
check('pose: почти равный старт через 180° → ORIENTATION_AMBIGUOUS', Q.pose_verdict(0.005, 0.0, 0.0, TH) == 'ORIENTATION_AMBIGUOUS')
check('pose: большой сдвиг проекций → POSE_UNCERTAIN', Q.pose_verdict(0.3, 0.2, 0.0, TH) == 'POSE_UNCERTAIN')
check('pose: нет стартов-соперников → GOOD', Q.pose_verdict(None, 0.0, 0.0, TH) == 'GOOD')
st = [{'cam': {'az': 10.0}, 'score': 0.9}, {'cam': {'az': 190.0}, 'score': 0.85}, {'cam': {'az': 100.0}, 'score': 0.5}]
best, nb = Q.near_best(st, 0.03)
gap, fl = Q.flip_gap(st, best, 30.0)
check('flip_gap: считает отставание «через 180°»', gap == 0.05 and fl['cam']['az'] == 190.0, str(gap))

# — расхождение поверхности под пикселем (не корзины) —
cent = np.array([[0.0, 0, 0], [0.01, 0, 0], [1.0, 0, 0]])
ia = np.array([[0, 0], [0, -1]])
check('поверхность: та же грань → 0', Q.region_disagreement(ia, ia, cent, 1.0) == 0.0)
check('поверхность: соседняя грань (0,01 диагонали) → мало', Q.region_disagreement(ia, np.array([[1, 1], [1, -1]]), cent, 1.0) < 0.02)
check('поверхность: далёкая грань → велико', Q.region_disagreement(ia, np.array([[2, 2], [2, -1]]), cent, 1.0) > 0.9)
check('поверхность: нет общих пикселей → 1', Q.region_disagreement(ia, np.full((2, 2), -1), cent, 1.0) == 1.0)

# — растр: честный z-buffer против порядка по средней глубине —
# две пересекающиеся грани: длинная A (почти вдоль луча, средняя глубина большая, но в части пикселей ближе) и малая B
V = np.array([[-1, -1, 4.0], [1, -1, 4.0], [0, 1, 4.0],            # B: плоскость Z=4
              [-1, -1, 1.0], [1, -1, 7.0], [0, 1.0, 4.0]], float)  # A: наклонная, средняя глубина 4, в левой части ближе B
F = np.array([[0, 1, 2], [3, 4, 5]], np.int64)
geo = {'V': V, 'F': F, 'N': np.zeros_like(V), 'UV': np.zeros((6, 2))}
cam = {'az': 0.0, 'el': 0.0, 'd': 1e-3, 'f': 0.0, 'cx': 0.5, 'cy': 0.5}
# камера в начале куба: свой простой проектор — проверяем render_zbuf через эквивалентную камеру
import pose_fit as PF  # noqa: E402
cam = {'az': 0.0, 'el': 0.0, 'd': 10.0, 'f': 3.0, 'cx': 0.5, 'cy': 0.5}
V2 = V.copy()
V2[:, 2] = 10.0 - V[:, 2]                                           # камера на +Z с d=10 смотрит вдоль −Z: глубина = 10 − z
V2[:, 2] = V2[:, 2]
geo2 = {'V': np.stack([V[:, 0], V[:, 1], 10.0 - V[:, 2]], 1), 'F': F, 'N': np.zeros_like(V), 'UV': np.zeros((6, 2))}
Rz = Q.render_zbuf(geo2, cam, 128)
Rp = PF.render_persp(geo2, cam, 128)
fb = np.zeros(len(F), np.int64)
fb[1] = 1
chk = Q.zbuf_check(Rp, Rz, fb)
check('z-buffer: оба растра покрывают кадр одинаково (cover_diff мал)', chk['cover_diff'] < 0.2, str(chk))
check('z-buffer: на пересечении порядок по средней глубине даёт другие id', chk['id_diff'] > 0.05, str(chk))
check('z-buffer: есть пиксели обеих граней', set(np.unique(Rz['ids'])) >= {0, 1}, str(np.unique(Rz['ids'])))

# — остаток и сдвиг —
A = rect(40, 160, 50, 150)
S_shift = rect(46, 166, 56, 156)                                    # вся фигура сдвинута на (6,6)
sh = Q.global_shift_explained(S_shift, A, R)
check('сдвиг: общий сдвиг снимает почти весь XOR', sh['explained'] > 0.8, str(sh))
S_local = A.copy()
S_local[135:160, 50:150] = False                                    # нет «ножек»: местная ошибка внизу
sh2 = Q.global_shift_explained(S_local, A, R)
res = Q.residual_components(S_local, A, R)
check('сдвиг: местная ошибка сдвигом не снимается', sh2['explained'] < 0.5, str(sh2))
check('остаток: компонента в зоне «низ»', res['bottom_share'] > 0.05 and res['non_bottom_share'] < 0.02, str(res))

# — вердикты и рекомендации —
res_ok = Q.residual_components(A.copy(), A, R)
v, ev = Q.shape_verdict('GOOD', 0.97, res_ok, {'explained': 0.0}, None, TH, False)
check('форма: чистый кадр → LIKELY_OK', v == 'LIKELY_OK')
probe = {'best': {'G_heldout': 0.5, 'pen': 0.1}, 'cam': {'G_heldout': 0.05}}
v2, ev2 = Q.shape_verdict('GOOD', 0.80, res, sh2, probe, TH, False)
check('форма: без калибровки SHAPE_MISMATCH_LIKELY не выдаётся никогда', v2 == 'INDETERMINATE', v2)
v3, ev3 = Q.shape_verdict('GOOD', 0.80, res, sh2, probe, TH, True)
check('форма: с калибровкой, остатком и выигрышем над перефитом камеры → SHAPE_MISMATCH_LIKELY', v3 == 'SHAPE_MISMATCH_LIKELY', str(ev3))
probe_cam = {'best': {'G_heldout': 0.5, 'pen': 0.1}, 'cam': {'G_heldout': 0.5}}
v4, _ = Q.shape_verdict('GOOD', 0.80, res, sh2, probe_cam, TH, True)
check('форма: камера выигрывает не меньше деформации → не «форма»', v4 == 'INDETERMINATE', v4)
v5, _ = Q.shape_verdict('POSE_UNCERTAIN', 0.80, res, sh2, probe, TH, True)
check('форма: поза неустойчива → форму не судим', v5 == 'INDETERMINATE', v5)
rec, safe, zone = Q.recommendation('GOOD', 'INDETERMINATE', res, sh2, TH)
check('рекомендация: корпус лёг, ошибка внизу → LIMIT_PROJECTION, зона body', rec == 'LIMIT_PROJECTION' and zone == 'body' and not safe, f'{rec} {zone}')
rec2, safe2, _ = Q.recommendation('GOOD', 'LIKELY_OK', res_ok, {'explained': 0.0}, TH)
check('рекомендация: чисто → OK, projection_safe', rec2 == 'OK' and safe2)
rec3, _, _ = Q.recommendation('GOOD', 'INDETERMINATE', Q.residual_components(S_shift, A, R), sh, TH)
check('рекомендация: общий сдвиг → REFINE', rec3 == 'REFINE', rec3)
rec4, _, _ = Q.recommendation('ORIENTATION_AMBIGUOUS', 'INDETERMINATE', res, sh2, TH)
check('рекомендация: поза неоднозначна → REVIEW_POSE', rec4 == 'REVIEW_POSE')

# — деформация —
Pt = np.array([[0, 0.0, 0], [0, 0.1, 0], [0, 0.5, 0], [0, 1.0, 0]])
Dd = Q.deform_legs(Pt, 0.5, 0.0, 1.0, 0.2)
check('ножки: выше крепления точки не двигаются, ниже — сжимаются', np.allclose(Dd[2:, 1], Pt[2:, 1]) and Dd[1, 1] > 0.1 and Dd[0, 1] == 0.1 * 0 + Dd[0, 1], str(Dd[:, 1]))
Db = Q.deform_bands(Pt + np.array([1.0, 0, 0]), np.array([1.0, 1.0, 1.0]), 0.0, 1.0, np.zeros(3), np.array([1.0, 0, 0]))
check('полосы: единичные масштабы — тождество', np.allclose(Db, Pt + np.array([1.0, 0, 0])))

# — калибровка —
reps = [{'max_disp': 0.01 * i, 'max_region_dis': 0.05 * i, 'residual': {'local_share': 0.01 * i}, 'evidence': {'gain_over_cam': 0.001 * i}} for i in range(1, 9)]
cal = Q.calibrate(reps, R)
check('калибровка: порог не ниже пола и не ниже нулевого максимума', cal['thresholds']['disp_max'] >= TH['disp_max_floor'] and cal['thresholds']['disp_max'] >= 0.08, str(cal['thresholds']))
check('калибровка: число нулей записано', cal['calibration']['n_null'] == 8)

print('FAIL: %d' % bad if bad else 'всё ок')
sys.exit(1 if bad else 0)
