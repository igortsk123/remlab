"""Эскизная копия меша (`mesh_render.lite_parts`, T-20261105-51/2): флаг LITE_TEXTURE_SAFE — меш с текстурой, который без
защиты границы не ужать, рисуется полным (иначе UV тянутся через швы атласа — пятна чужого цвета); по умолчанию флаг выключен
и поведение прежнее. Без сети и файлов: меш синтетический (20 тыс. отдельных треугольников — граница весь меш).
    ~/venvs/scout/bin/python tools/scout/tests/test_mesh_lite.py"""
import os
import sys

import numpy as np
import trimesh
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
import mesh_render as MR  # noqa: E402

fails = 0


def check(name, cond):
    global fails
    print(('OK   ' if cond else 'FAIL ') + name)
    fails += 0 if cond else 1


def soup(n: int, textured: bool) -> trimesh.Trimesh:
    """n отдельных треугольников на сетке: у каждого все рёбра — граница."""
    g = int(np.ceil(np.sqrt(n)))
    i = np.arange(n)
    o = np.column_stack([(i % g).astype(float), (i // g).astype(float), np.zeros(n)])
    V = np.concatenate([o, o + [0.9, 0, 0], o + [0, 0.9, 0]]).reshape(3, n, 3).transpose(1, 0, 2).reshape(-1, 3)
    F = np.arange(3 * n).reshape(n, 3)
    m = trimesh.Trimesh(vertices=V, faces=F, process=False)
    if textured:
        m.visual = trimesh.visual.TextureVisuals(uv=V[:, :2] / g, material=trimesh.visual.material.SimpleMaterial(
            image=Image.new('RGB', (8, 8), (200, 120, 40))))
    return m


def lite(textured: bool, safe: bool, border_ok: bool = False) -> list:
    m = soup(20000, textured) if not border_ok else trimesh.creation.icosphere(subdivisions=6)
    if border_ok and textured:
        m.visual = trimesh.visual.TextureVisuals(uv=m.vertices[:, :2] * 0.5 + 0.5, material=trimesh.visual.material.SimpleMaterial(
            image=Image.new('RGB', (8, 8), (200, 120, 40))))
    MR.load_parts = lambda p: [m]
    MR.LITE_TEXTURE_SAFE = safe
    MR._LITE_CACHE.clear()
    return MR.lite_parts(f'/x/{textured}-{safe}-{border_ok}.glb'), m


try:
    import fast_simplification  # noqa: F401
except ImportError:
    print('SKIP: нет fast_simplification')
    sys.exit(0)

check('флаг по умолчанию выключен', os.environ.get('LITE_TEXTURE_SAFE', '0') != '0' or MR.LITE_TEXTURE_SAFE is False)
out, m = lite(True, False)
check('без флага: граница не даёт ужать → упрощаем без неё (как было)', len(out[0].faces) < len(m.faces) * 0.7)
out, m = lite(True, True)
check('флаг: у меша текстура → полный меш, тот же объект', out[0] is m)
out, m = lite(False, True)
check('флаг: без текстуры — упрощаем как было (цвета граней швов не боятся)', len(out[0].faces) < len(m.faces) * 0.7)
out, m = lite(True, True, border_ok=True)
check('флаг: граница даёт ужать — эскиз упрощён как было', len(out[0].faces) < len(m.faces) and out[0] is not m)
k = list(MR._LITE_CACHE)[0]
check('флаг — в ключе кэша (иначе включение не меняло бы кадр до перезапуска)', True in k[2:] and len(k) == 4)
print('итог:', 'FAIL' if fails else 'OK')
sys.exit(1 if fails else 0)
