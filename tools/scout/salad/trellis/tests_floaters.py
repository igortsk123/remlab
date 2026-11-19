#!/usr/bin/env python3
"""Тесты общего шага `mesh_floaters.py` (убрать осколки после генерации формы, T-20261119-94/2). Нужны trimesh/numpy/scipy; без них — пропуск."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.normpath(os.path.join(HERE, '..', '..')))
import remlab_tmp  # noqa: E402
remlab_tmp.use('tests_floaters')
import mesh_floaters as F  # noqa: E402

bad = 0


def ok(name, cond):
    global bad
    print(('  ✓ ' if cond else '  ✗ ') + name)
    bad += 0 if cond else 1


def raises(fn):
    try:
        fn()
    except ValueError:
        return True
    return False


print('1. порог по площади (чистая часть)')
r = F.component_report([100.0, 0.5, 2.0, 0.99, 1.0], 0.01)
ok('при 1 %: уходят куски меньше 1,0 (0,5 и 0,99), 1,0 остаётся', r['drop_idx'] == [1, 3] and r['kept'] == 3 and r['dropped'] == 2)
ok('доля убранной площади посчитана', abs(r['area_share_dropped'] - (1.49 / 104.49)) < 1e-9)
ok('порог 0 — ничего не уходит; плохой frac → ValueError', F.component_report([1, 2], 0)['dropped'] == 0 and raises(lambda: F.component_report([1], 1.0)) and raises(lambda: F.component_report([], 0.1)))

try:
    import numpy as np
    import trimesh
except ImportError:
    print('  (trimesh/numpy нет — часть с настоящим мешем пропущена)')
else:
    print('2. настоящий меш: большой куб + осколок + приросший «ушко»')
    big = trimesh.creation.box(extents=(1, 1, 1))
    chip = trimesh.creation.box(extents=(0.05, 0.05, 0.05)); chip.apply_translation((2, 0, 0))            # отдельный осколок
    m = trimesh.util.concatenate([big, chip])
    out, rep = F.remove_floaters(m, 0.01)
    ok('осколок убран, куб цел (12 граней), счётчики верны', rep['dropped'] == 1 and rep['kept'] == 1 and len(out.faces) == 12 and rep['faces_dropped'] == 12)
    ok('вершины осколка вычищены, габарит стал кубом', len(out.vertices) == 8 and np.allclose(out.bounds, [[-.5, -.5, -.5], [.5, .5, .5]]))
    out2, rep2 = F.remove_floaters(m, 0.0)
    ok('порог 0: ничего не убрано', rep2['dropped'] == 0 and len(out2.faces) == 24)
    ok('исходный меш не изменён', len(m.faces) == 24)
    # текстурный меш: вершины раздвоены по швам — не считать швы осколками
    cube = trimesh.creation.box(extents=(1, 1, 1))
    v = np.asarray(cube.vertices); f = np.asarray(cube.faces)
    v2 = np.concatenate([v[f[:, i]] for i in range(3)]); f2 = np.arange(len(v2)).reshape(3, -1).T       # каждая грань со своими вершинами (максимально раздвоено)
    tm = trimesh.Trimesh(vertices=v2, faces=f2, process=False)
    _, rep3 = F.remove_floaters(tm, 0.01)
    ok('раздвоенные вершины склеиваются по положению: один кусок, а не 12', rep3['parts'] == 1)

print(f'\nИТОГО: {"всё в норме" if not bad else f"упало {bad}"}')
sys.exit(1 if bad else 0)
