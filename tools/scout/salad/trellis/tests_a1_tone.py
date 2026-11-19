#!/usr/bin/env python3
"""Тесты `a1_tone.py` (T-20261119-83/2): подмена карты в GLB без изменения формы (guard 1e-6), монотонная кривая по L* с наклоном в [0,8; 1,3], цвет a*b* не меняется,
кластеры материалов по a*b*. Без видеокарты и сети; GLB собирается вручную (четырёхугольник с картой 64×64). Нужны numpy, PIL, scipy (в CI есть).

  python3 tools/scout/salad/trellis/tests_a1_tone.py
"""
from __future__ import annotations

import io
import json
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.normpath(os.path.join(HERE, '..', '..')))
import numpy as np  # noqa: E402
import a1_tone as A  # noqa: E402
import pattern_metric as PM  # noqa: E402

bad = 0


def check(name: str, ok: bool, extra: str = '') -> None:
    global bad
    print(('ok   ' if ok else 'FAIL ') + name + (f'  {extra}' if extra else ''))
    if not ok:
        bad += 1


def png(arr: np.ndarray) -> bytes:
    from PIL import Image
    b = io.BytesIO()
    Image.fromarray(arr).save(b, format='PNG')
    return b.getvalue()


def make_glb(tex: np.ndarray) -> tuple[dict, bytes]:
    pos = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]], '<f4')
    uv = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], '<f4')
    idx = np.array([0, 1, 2, 0, 2, 3], '<u2')
    parts = [pos.tobytes(), uv.tobytes(), idx.tobytes(), png(tex)]
    out, views = bytearray(), []
    for p in parts:
        out += b'\0' * ((4 - len(out) % 4) % 4)
        views.append({'buffer': 0, 'byteOffset': len(out), 'byteLength': len(p)})
        out += p
    j = {'asset': {'version': '2.0'}, 'buffers': [{'byteLength': len(out)}], 'bufferViews': views,
         'accessors': [{'bufferView': 0, 'componentType': 5126, 'count': 4, 'type': 'VEC3', 'min': [0, 0, 0], 'max': [1, 1, 0]},
                       {'bufferView': 1, 'componentType': 5126, 'count': 4, 'type': 'VEC2'},
                       {'bufferView': 2, 'componentType': 5123, 'count': 6, 'type': 'SCALAR'}],
         'meshes': [{'primitives': [{'attributes': {'POSITION': 0, 'TEXCOORD_0': 1}, 'indices': 2, 'material': 0}]}],
         'materials': [{'pbrMetallicRoughness': {'baseColorTexture': {'index': 0}}}], 'textures': [{'source': 0}],
         'images': [{'bufferView': 3, 'mimeType': 'image/png'}], 'nodes': [{'mesh': 0}], 'scenes': [{'nodes': [0]}], 'scene': 0}
    return j, bytes(out)


rng = np.random.default_rng(3)
tex0 = rng.integers(40, 220, (64, 64, 3), dtype=np.uint8)
j0, b0 = make_glb(tex0)

# 1. подмена карты: форма, UV, индексы — те же байты; картинка — новая; файл читается обратно
tex1 = rng.integers(0, 255, (128, 128, 3), dtype=np.uint8)
j1, b1 = A.swap_texture(j0, b0, png(tex1))
g = A.geometry_guard(j0, b0, j1, b1)
check('guard: форма/UV/индексы не изменились', g['ok'] and g['max_abs_diff'] == 0.0 and g['accessors'] == 3, str(g))
p = os.path.join(os.environ.get('TMPDIR', '/tmp'), 'tests_a1_tone.glb')
A.write_glb(p, j1, b1)
j2, b2 = A.read_glb(p)
from PIL import Image  # noqa: E402
im = np.asarray(Image.open(io.BytesIO(A.view_bytes(j2, b2, j2['images'][0]['bufferView']))).convert('RGB'))
check('в GLB лежит новая карта 128×128 без потерь', im.shape == (128, 128, 3) and np.array_equal(im, tex1))
os.remove(p)

# 2. guard ловит сдвиг вершины и смену индексов
jb, bb = j1, bytearray(b1)
off = j1['bufferViews'][0]['byteOffset']
bb[off:off + 4] = struct.pack('<f', 1e-3)
check('guard: сдвиг вершины на 1e-3 — отказ', not A.geometry_guard(j0, b0, jb, bytes(bb))['ok'])
bb2 = bytearray(b1)
off2 = j1['bufferViews'][2]['byteOffset']
bb2[off2:off2 + 2] = struct.pack('<H', 3)
check('guard: другой индекс — отказ', not A.geometry_guard(j0, b0, j1, bytes(bb2))['ok'])
jj = json.loads(json.dumps(j1))
jj['accessors'][1]['count'] = 3
check('guard: другой JSON (accessors) — отказ', not A.geometry_guard(j0, b0, jj, b1)['ok'])
try:
    A.swap_texture({'bufferViews': [], 'buffers': [{'byteLength': 0}], 'images': []}, b'', b'x')
    check('swap_texture: нет картинки — отказ', False)
except ValueError:
    check('swap_texture: нет картинки — отказ', True)

# 3. кривая: монотонна, наклон в [0,8; 1,3], медиана → медиана фото, за краями наклон 1
Lr = rng.normal(45, 6, 5000)
Lp = rng.normal(52, 14, 5000)                     # фото контрастнее и светлее: нужен наклон > 1,3 — зажимается
c = A.monotone_curve(Lr, Lp)
x, y = np.array(c['x']), np.array(c['y'])
sl = np.diff(y) / np.diff(x)
check('кривая монотонна и наклон в [0,8; 1,3]', bool((np.diff(x) > 0).all() and sl.min() >= A.SLOPE_MIN - 1e-3 and sl.max() <= A.SLOPE_MAX + 1e-3), f'{sl.min():.3f}..{sl.max():.3f}')
med_r = float(np.percentile(Lr, 50))
check('медиана рендера → медиана фото', abs(float(A.eval_curve(c, np.array([med_r]))[0]) - float(np.percentile(Lp, 50))) < 0.01)
check('за краями узлов наклон 1', abs(sl[0] - 1) < 1e-3 and abs(sl[-1] - 1) < 1e-3)
flat = A.monotone_curve(np.full(1000, 40.0), np.full(1000, 55.0))
check('плоский кластер: кривая конечна и монотонна', bool(np.isfinite(flat['y']).all() and (np.diff(flat['y']) > 0).all()))
ident = A.monotone_curve(Lr, Lr)
check('рендер = фото: кривая — тождество на данных', float(np.abs(A.eval_curve(ident, Lr) - Lr).max()) < 0.2)

# 4. применение к карте: a*b* не меняются, L* меняется в сторону кривой; тождество — карта та же (±1)
tex = np.zeros((96, 96, 3), np.uint8)
tex[:, :48] = (190, 150, 90)                      # тёплый
tex[:, 48:] = (90, 100, 110)                      # холодный серый
tex = np.clip(tex.astype(np.int16) + rng.integers(-3, 3, tex.shape), 0, 255).astype(np.uint8)
lab0 = PM.rgb_to_lab(tex)
cent = A.find_clusters(lab0[..., 1:].reshape(-1, 2))
check('два материала по a*b* — два кластера', len(cent) == 2, str(np.round(cent, 1).tolist()))
idc = {'x': [-100.0, 200.0], 'y': [-100.0, 200.0], 'slopes': [1.0]}
same, _ = A.apply_curves(tex, cent, [idc] * len(cent))
check('тождественная кривая — карта прежняя (±1 уровень)', int(np.abs(same.astype(int) - tex.astype(int)).max()) <= 1)
up = {'x': [-100.0, 200.0], 'y': [-90.0, 210.0], 'slopes': [1.0]}                  # +10 к L*
new, info = A.apply_curves(tex, cent, [up] * len(cent))
lab1 = PM.rgb_to_lab(new)
ok_mask = (lab0[..., 0] < 85) & (lab0[..., 0] > 15)
dab = np.abs(lab1[..., 1:] - lab0[..., 1:])[ok_mask]
check('a*b* не меняются (медиана |Δ| ≤ 0,5)', float(np.median(dab)) <= 0.5, f'медиана {float(np.median(dab)):.3f}, макс {float(dab.max()):.2f}')
check('L* вырос на ~10', abs(float(np.median((lab1[..., 0] - lab0[..., 0])[ok_mask])) - 10) < 0.6)
check('доля вышедших из гаммы — число', 0 <= info['gamut_clipped_share'] <= 1)

# 5. кластеры: почти один цвет — один материал; мелкая примесь сливается
mono = np.concatenate([rng.normal([2, 3], 1.0, (3000, 2)), rng.normal([3, 4], 1.0, (3000, 2))])
check('почти один цвет — один кластер', len(A.find_clusters(mono)) == 1)
pure = np.concatenate([rng.normal([2, 3], 0.5, (5000, 2)), rng.normal([30, -20], 0.5, (60, 2))])
check('примесь меньше 3 % сливается', len(A.find_clusters(pure)) == 1)
three = np.concatenate([rng.normal([0, 0], 0.7, (3000, 2)), rng.normal([5, 22], 0.7, (3000, 2)), rng.normal([-12, -10], 0.7, (2000, 2))])
check('три различимых материала — три кластера', len(A.find_clusters(three)) == 3)

print('\n' + ('FAIL: ' + str(bad) if bad else 'all ok'))
sys.exit(1 if bad else 0)
