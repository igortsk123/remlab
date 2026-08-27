#!/usr/bin/env python3
"""Селфтест конвенции ориентаций (план viz-mesh-orientation, q22): фикстура строится КОДОМ
(асимметричное тело с «носом» на фронте и маркером справа), никаких товарных мешей и golden-PNG.

Три инварианта:
  1. выравнивание: ry(front_yaw) ставит фронт фикстуры на +Z;
  2. мир: front_world(rot) = (sin rot, 0, cos rot) для 0/90/180/270; det(R)=+1 (без зеркал);
  3. кадр: «нос» предмета, стоящего лицом К камере, проецируется НИЖЕ центра тела
     (ближе к камере), маркер правой стороны — в правой половине кадра.

Урок 28.08: конвенции, выведенные «на бумаге», дважды оказались неверны — истина только
исполняемым тестом. Запуск: ~/venvs/scout/bin/python tools/scout/orient_selftest.py
"""
import math
import sys

import numpy as np
import trimesh

sys.path.insert(0, __file__.rsplit('/', 1)[0])
from scene_mesh import front_world, ry, world_vertices  # noqa: E402


def fixture() -> list:
    """Тело 40×80×30 (Ш×В×Г) + «нос» на фронте (+Z) + маркер на правой грани (+X)."""
    body = trimesh.creation.box(extents=[40, 80, 30])
    nose = trimesh.creation.box(extents=[8, 8, 14])
    nose.apply_translation([0, -20, 15 + 7])            # нос внизу фронта
    right = trimesh.creation.box(extents=[10, 6, 6])
    right.apply_translation([20 + 5, 30, 0])            # маркер справа сверху
    return [body, nose, right]


class P:                                                # минимальный placement
    def __init__(self, x, y, rot, w, d, h):
        self.x, self.y, self.rot, self.elev_cm = x, y, rot, 0.0

        class I:                                        # noqa: E742
            pass
        self.item = I()
        self.item.w_cm, self.item.d_cm, self.item.h_cm = w, d, h
        self.item.role = 'фикстура'
        self.item.name = 'фикстура'


def fail(msg):
    print('СЕЛФТЕСТ ПРОВАЛЕН:', msg)
    sys.exit(1)


def main():
    # 2а. мировая конвенция фронта
    for rot, exp in ((0, (0, 0, 1)), (90, (1, 0, 0)), (180, (0, 0, -1)), (270, (-1, 0, 0))):
        f = front_world(rot)
        if not np.allclose(f, exp, atol=1e-5):
            fail(f'front_world({rot}) = {f}, ожидалось {exp}')
    # 2б. det=+1 — зеркал нет
    for a in (0, 37, 90, 213):
        if abs(np.linalg.det(ry(a)) - 1.0) > 1e-5:
            fail(f'det(ry({a})) != +1')
    # 1+3. фикстура: нос предмета с rot=180 (лицом на юг, к камере с юга) ближе к югу,
    # маркер правой стороны — восточнее центра; низ на полу
    parts = fixture()
    worlds, Ra, R, h_src, aniso = world_vertices(parts, P(100, 100, 180, 40, 30, 80),
                                                 front_yaw=0)
    allw = np.vstack(worlds)
    if allw[:, 1].min() < -0.5 or allw[:, 1].min() > 0.5:
        fail(f'низ не на полу: {allw[:, 1].min():.2f}')
    nose_w = worlds[1].mean(axis=0)
    body_w = worlds[0].mean(axis=0)
    if not nose_w[2] < body_w[2] - 5:
        fail(f'нос при rot=180 должен быть южнее тела: nose z={nose_w[2]:.1f}, '
             f'body z={body_w[2]:.1f}')
    right_w = worlds[2].mean(axis=0)
    if not right_w[0] < body_w[0] - 5:                   # rot=180: «правая» грань уходит на запад
        fail(f'маркер правой грани при rot=180 должен быть западнее: {right_w[0]:.1f}')
    # габариты по мировым осям при rot=0: X≈w, Z≈d
    worlds0, *_ = world_vertices(parts, P(0, 0, 0, 40, 30, 80), front_yaw=0)
    aw = np.vstack(worlds0)
    ex = aw.max(axis=0) - aw.min(axis=0)
    if abs(ex[0] - 40) > 2 or abs(ex[2] - 30) > 2 or abs(ex[1] - 80) > 2:
        fail(f'габариты по осям при rot=0: {ex}, ожидалось ~(40,80,30)')
    # выравнивание: тот же нос, заданный со смещённым фронтом (front_yaw=90), обязан встать так же
    rotated = [m.copy() for m in fixture()]
    for m in rotated:                      # нос уводим в ry(90)·Z — фронт «виден при yaw=90»
        m.apply_transform(np.vstack([np.hstack([ry(90), [[0], [0], [0]]]), [0, 0, 0, 1]]))
    worlds90, *_ = world_vertices(rotated, P(100, 100, 180, 40, 30, 80), front_yaw=90)
    n90 = worlds90[1].mean(axis=0)
    if not np.allclose(n90, nose_w, atol=2.0):
        fail(f'выравнивание front_yaw=90 разошлось: {n90} против {nose_w}')
    print('СЕЛФТЕСТ КОНВЕНЦИИ: ок (фронт, det=+1, пол, габариты, выравнивание)')


if __name__ == '__main__':
    main()
