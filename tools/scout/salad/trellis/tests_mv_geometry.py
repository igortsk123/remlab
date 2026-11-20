"""Тест `mv_geometry.py` (T-20261120-147/1): геометрия кадра MV-Adapter для сторожа покраски — константы апстрима, кадр формы, камера вида 0.
Без сети и тяжёлых зависимостей (numpy). Запуск: python tools/scout/salad/trellis/tests_mv_geometry.py"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import numpy as np  # noqa: E402
import mv_geometry as G  # noqa: E402

FAILS = []


def ok(name, cond, extra=''):
    print(('OK   ' if cond else 'FAIL ') + name + (f' — {extra}' if extra and not cond else ''))
    if not cond:
        FAILS.append(name)


ok('константы апстрима: ортография 1,1; азимуты видов [−90, 0, 90, 180, 90, 90]', G.MV_ORTHO == 1.1 and G.MV_AZ == [-90, 0, 90, 180, 90, 90], str(G.MV_AZ))

# кадр формы: габарит 2×1×0,5 со смещением → центр в нуле, наибольшая сторона 0,99999
V = np.array([[10, 5, 3], [12, 5, 3], [12, 6, 3.5], [10, 6, 3.5]], dtype=np.float64)
p, c, s, R = G.to_cube(V)
ok('to_cube: наибольшая сторона = 0,99999', abs(float((p.max(0) - p.min(0)).max()) - 0.99999) < 1e-9)
ok('to_cube: центр габарита в нуле', np.allclose((p.max(0) + p.min(0)) / 2, 0, atol=1e-9))
ok('to_cube: обратное (p / s + c) даёт исходные вершины', np.allclose((p / s + c) @ R, V))

# yaw кратный 90° — точный (без плавающей ошибки), поворот на 90° переводит +Z в +X
R90 = G.rot_y(90)
ok('rot_y(90) точный: единицы и нули', np.array_equal(R90, np.array([[0.0, 0.0, 1.0], [0.0, 1.0, 0.0], [-1.0, 0.0, 0.0]])))
ok('rot_y(360) = единица', np.array_equal(G.rot_y(360), np.eye(3)))
ok('rot_x(0) = единица; rot_x(90) переводит +Y в +Z', np.array_equal(G.rot_x(0), np.eye(3)) and np.allclose(G.rot_x(90) @ [0, 1, 0], [0, 0, 1]))
ok('yaw 180: ширина по X сохраняется, X и Z отражены', np.allclose(G.to_cube(V, 180)[0][:, 0], -G.to_cube(V, 0)[0][:, 0], atol=1e-9))

try:
    G.to_cube([[1, 1, 1], [1, 1, 1]])
    ok('вырожденная форма — ValueError', False)
except ValueError:
    ok('вырожденная форма — ValueError', True)

# камера вида 0: центр куба — середина кадра, +X вправо, +Y вверх (v уменьшается), края ±0,55 → 0 и 1
u, v = G.mv_ortho_uv(np.array([[0, 0, 0], [0.55, 0.55, 0], [-0.55, -0.55, 0]], dtype=np.float64))
ok('mv_ortho_uv: центр → (0,5; 0,5)', abs(u[0] - 0.5) < 1e-12 and abs(v[0] - 0.5) < 1e-12)
ok('mv_ortho_uv: +X вправо, +Y вверх; края ±0,55 → 1/0', abs(u[1] - 1.0) < 1e-12 and abs(v[1] - 0.0) < 1e-12 and abs(u[2]) < 1e-12 and abs(v[2] - 1.0) < 1e-12)

print('итог:', 'OK' if not FAILS else f'FAIL ({len(FAILS)})')
sys.exit(1 if FAILS else 0)
