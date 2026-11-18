"""РАЗБОР GLB БЕЗ ГЛУБОКОЙ КОПИИ (T-20261118-10/3 ❶): `mesh_render.load_parts` больше не копирует геометрию (`geom.copy()` вместе с декодом и копией текстуры стоила ≈0,15–0,3 с на меш).
Паритет с прежней версией (копия) на синтетическом GLB: вершины, грани, UV, пиксели текстур, число и порядок частей — те же. Сеть и реальные меши не нужны.
python tools/scout/tests/test_load_parts_nocopy.py"""
import os
import sys
import tempfile

import numpy as np
import trimesh
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
import mesh_render as MR  # noqa: E402

fails = []


def check(name, cond):
    print(('OK   ' if cond else 'FAIL ') + name)
    if not cond:
        fails.append(name)


def load_parts_with_copy(path):
    """Прежняя версия `load_parts` — с `geom.copy()` — как эталон."""
    scene = trimesh.load(path, force='scene')
    parts = []
    for name, geom in scene.geometry.items():
        g = geom.copy()
        try:
            g.apply_transform(scene.graph.get(name)[0])
        except Exception:  # noqa: BLE001
            pass
        parts.append(g)
    allv = np.vstack([np.asarray(p.vertices, np.float64) for p in parts])
    centre = (allv.max(axis=0) + allv.min(axis=0)) / 2
    scale = 1.0 / max((allv.max(axis=0) - allv.min(axis=0)).max(), 1e-6)
    for p in parts:
        p.apply_translation(-centre)
        p.apply_scale(scale)
    return parts


rng = np.random.default_rng(11)
tmp = tempfile.mkdtemp(prefix='lp-')
sc = trimesh.Scene()
for k in range(3):
    m = trimesh.creation.icosphere(subdivisions=2) if k else trimesh.creation.box(extents=(1.0, 0.6, 0.4))
    uv = rng.random((len(m.vertices), 2))
    tex = Image.fromarray(rng.integers(0, 255, (32, 32, 3), dtype=np.uint8))
    mat = trimesh.visual.material.PBRMaterial(baseColorTexture=tex)
    if k == 1:
        mat.metallicRoughnessTexture = Image.fromarray(rng.integers(0, 255, (16, 16, 3), dtype=np.uint8))
    m.visual = trimesh.visual.TextureVisuals(uv=uv, material=mat)
    T = trimesh.transformations.translation_matrix((k * 1.5, 0.2 * k, -0.3 * k)) @ trimesh.transformations.rotation_matrix(0.4 * k, (0, 1, 0))
    sc.add_geometry(m, node_name=f'n{k}', geom_name=f'g{k}', transform=T)
glb = os.path.join(tmp, 't.glb')
sc.export(glb)

a, b = load_parts_with_copy(glb), MR.load_parts(glb)
check('то же число частей', len(a) == len(b) == 3)
check('вершины побитно те же', all(np.array_equal(np.asarray(x.vertices), np.asarray(y.vertices)) for x, y in zip(a, b)))
check('грани те же', all(np.array_equal(np.asarray(x.faces), np.asarray(y.faces)) for x, y in zip(a, b)))
check('UV те же', all(np.array_equal(np.asarray(x.visual.uv), np.asarray(y.visual.uv)) for x, y in zip(a, b)))
img = lambda p: np.asarray(p.visual.material.baseColorTexture.convert('RGB'))  # noqa: E731
check('пиксели текстуры те же', all(np.array_equal(img(x), img(y)) for x, y in zip(a, b)))
mr = lambda p: getattr(p.visual.material, 'metallicRoughnessTexture', None)  # noqa: E731
check('карта шероховатости/металла: есть там же и те же пиксели',
      all((mr(x) is None) == (mr(y) is None) and (mr(x) is None or np.array_equal(np.asarray(mr(x).convert('RGB')), np.asarray(mr(y).convert('RGB')))) for x, y in zip(a, b)))
allv = np.vstack([np.asarray(p.vertices) for p in b])
check('вписан в единичный куб по центру (как прежде)', abs((allv.max(0) - allv.min(0)).max() - 1.0) < 1e-9 and np.abs((allv.max(0) + allv.min(0)) / 2).max() < 1e-9)
# повторная загрузка того же файла не делит состояние с первой (сцена одноразовая)
c = MR.load_parts(glb)
check('вторая загрузка — независимые объекты, те же значения', c[0] is not b[0] and np.array_equal(np.asarray(c[0].vertices), np.asarray(b[0].vertices)))

print('итог:', 'чисто' if not fails else f'{len(fails)} падений')
sys.exit(1 if fails else 0)
