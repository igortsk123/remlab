#!/usr/bin/env python3
"""Тесты `ab_tint.py` (T-20261119-87): сдвиг a*b* к цели, L* не меняется, предел срабатывает, guard формы, без инверсий оттенка. Без видеокарты и сети, без ID товаров (синтетика).
Нужны numpy, PIL, scipy (в CI есть).

  python3 tools/scout/salad/trellis/tests_ab_tint.py
"""
from __future__ import annotations

import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.normpath(os.path.join(HERE, '..', '..')))
import numpy as np  # noqa: E402
import a1_tone as A  # noqa: E402
import ab_tint as T  # noqa: E402
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


rng = np.random.default_rng(5)

# 1. сдвиг кластера: к цели; предел длины; предел цветности
s, i = T.cluster_shift(np.array([4.0, 14.0]), np.array([1.0, 9.0]))
check('сдвиг до цели (в пределах предела)', np.allclose(s, [-3.0, -5.0], atol=1e-6) and not i['limited_by_max_shift'], str(s))
s, i = T.cluster_shift(np.array([0.0, 0.0]), np.array([30.0, 40.0]))
check('предел длины: сдвиг 50 → 10 в сторону цели', abs(float(np.hypot(*s)) - T.MAX_SHIFT) < 1e-6 and i['limited_by_max_shift'] and np.allclose(s / np.hypot(*s), [0.6, 0.8]), str(s))
s, i = T.cluster_shift(np.array([5.0, 5.0]), np.array([5.0, 5.0]))
check('рендер = фото: сдвиг 0', float(np.hypot(*s)) < 1e-9)
s, i = T.cluster_shift(np.array([10.0, 0.0]), np.array([12.0, 3.0]), max_shift=100.0)
check('цветность результата не выше max(фото, рендер)', float(np.hypot(*(np.array([10.0, 0.0]) + s))) <= max(np.hypot(12, 3), 10.0) + 1e-6)

# 2. карта: два материала; сдвиг a*b* к цели, L* не меняется, a*b* второго кластера почти прежний
tex = np.zeros((96, 96, 3), np.uint8)
tex[:, :48] = (190, 150, 90)                      # тёплый
tex[:, 48:] = (90, 100, 110)                      # холодный серый
tex = np.clip(tex.astype(np.int16) + rng.integers(-3, 3, tex.shape), 0, 255).astype(np.uint8)
lab0 = PM.rgb_to_lab(tex)
cent = A.find_clusters(lab0[..., 1:].reshape(-1, 2))
check('два материала — два кластера', len(cent) == 2)
k_warm = int(np.argmax(cent[:, 1]))
sh = np.zeros((2, 2))
sh[k_warm] = [-4.0, -6.0]                         # теплый материал чуть холоднее и менее жёлтый
new, info = T.apply_shifts(tex, cent, sh)
lab1 = PM.rgb_to_lab(new)
left = lab0[:, :40]
check('тёплый материал: a*b* сдвинулись к цели (медиана Δ ≈ сдвиг ±0,6)',
      np.allclose(np.median((lab1[:, :40, 1:] - left[..., 1:]).reshape(-1, 2), 0), [-4.0, -6.0], atol=0.6),
      str(np.median((lab1[:, :40, 1:] - left[..., 1:]).reshape(-1, 2), 0)))
check('L* не меняется (медиана |ΔL| ≤ 0,3, p99 ≤ 1,5)', float(np.median(np.abs(lab1[..., 0] - lab0[..., 0]))) <= 0.3 and float(np.percentile(np.abs(lab1[..., 0] - lab0[..., 0]), 99)) <= 1.5,
      f'{float(np.median(np.abs(lab1[..., 0] - lab0[..., 0]))):.3f}')
check('второй материал не тронут (медиана |Δa*b*| ≤ 0,6)', float(np.median(np.abs(lab1[:, 56:, 1:] - lab0[:, 56:, 1:]))) <= 0.6)
zero, _ = T.apply_shifts(tex, cent, np.zeros((2, 2)))
check('нулевой сдвиг — карта прежняя (±1 уровень)', int(np.abs(zero.astype(int) - tex.astype(int)).max()) <= 1)

# 3. без инверсии оттенка: серый текстель при большом сдвиге не получает противоположный знак a*b*
grey = np.full((64, 64, 3), (131, 128, 125), np.uint8)       # почти серый, слабый тёплый оттенок (a*b* ≈ +1,2/+2,8)
grey[:, 32:] = (150, 130, 110)
cg = np.array([[0.0, 0.0], [10.0, 17.0]])
sg = np.array([[-8.0, -8.0], [0.0, 0.0]])          # сдвиг «против» цвета серого
new_g, ig = T.apply_shifts(grey, cg, sg)
lg0, lg1 = PM.rgb_to_lab(grey), PM.rgb_to_lab(new_g)
dot = (lg1[:, :20, 1:] * lg0[:, :20, 1:]).sum(-1)
check('без инверсии: вектор a*b* не меняет направление (скалярное произведение ≥ −0,5)', float(dot.min()) >= -0.5, f'{float(dot.min()):.3f}; масштабировано {ig["texels_scaled_by_no_inversion_share"]}')
check('ограничитель действительно сработал на левой половине', ig['texels_scaled_by_no_inversion_share'] > 0.3, str(ig))

# 4. guard формы
jc, bc = make_glb(tex)
t2 = T.read_texture(jc, bc)
check('read_texture читает карту GLB', t2.shape == tex.shape and np.array_equal(t2, tex))
jn, bn = A.swap_texture(jc, bc, png(new))
g = A.geometry_guard(jc, bc, jn, bn)
check('guard: форма/UV/индексы после подмены карты — те же', g['ok'] and g['max_abs_diff'] == 0.0, str(g))
import struct  # noqa: E402
bb = bytearray(bn)
off = jn['bufferViews'][0]['byteOffset']
bb[off:off + 4] = struct.pack('<f', 1e-3)
check('guard: сдвиг вершины — отказ', not A.geometry_guard(jc, bc, jn, bytes(bb))['ok'])

print('\n' + ('FAIL: ' + str(bad) if bad else 'all ok'))
sys.exit(1 if bad else 0)
