#!/usr/bin/env python3
"""Лист «со всех сторон» браузером (tools/assets/sides_sheet.py, T-20261123-27/1): виды из правил sides-sheet.json, подмена съёмки, настоящий ящик (REMLAB_SHEET_E2E=1: node + Playwright + сеть для CDN).
Без ID товаров, чисел видов/размеров в коде нет. Запуск: python tools/assets/tests/test_sides_sheet.py      (numpy + Pillow)"""
import json
import os
import re
import struct
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, '..')
sys.path.insert(0, ASSETS)
sys.path.insert(0, os.path.join(HERE, '..', '..', 'scout'))
import numpy as np  # noqa: E402
import remlab_tmp  # noqa: E402
remlab_tmp.use('test_sides_sheet')
import sides_sheet as SS  # noqa: E402
from PIL import Image  # noqa: E402

SH = SS.load_rules()
FAIL = 0


def ok(cond, name):
    global FAIL
    print(('  ✓ ' if cond else '  ✗ ') + name)
    FAIL += 0 if cond else 1


def box_glb(path, rgba):
    p = [(-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1), (-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1)]
    idx = [0, 2, 1, 0, 3, 2, 4, 5, 6, 4, 6, 7, 0, 1, 5, 0, 5, 4, 3, 7, 6, 3, 6, 2, 0, 4, 7, 0, 7, 3, 1, 2, 6, 1, 6, 5]
    pos = b''.join(struct.pack('<3f', *v) for v in p)
    ind = struct.pack(f'<{len(idx)}H', *idx) + b'\x00' * (-len(idx) * 2 % 4)
    binc = pos + ind
    js = {'asset': {'version': '2.0'}, 'scene': 0, 'scenes': [{'nodes': [0]}], 'nodes': [{'mesh': 0}],
          'meshes': [{'primitives': [{'attributes': {'POSITION': 0}, 'indices': 1, 'material': 0}]}],
          'materials': [{'pbrMetallicRoughness': {'baseColorFactor': list(rgba), 'metallicFactor': 0, 'roughnessFactor': 1}}],
          'accessors': [{'bufferView': 0, 'componentType': 5126, 'count': 8, 'type': 'VEC3', 'min': [-1, -1, -1], 'max': [1, 1, 1]},
                        {'bufferView': 1, 'componentType': 5123, 'count': len(idx), 'type': 'SCALAR'}],
          'bufferViews': [{'buffer': 0, 'byteOffset': 0, 'byteLength': len(pos)}, {'buffer': 0, 'byteOffset': len(pos), 'byteLength': len(idx) * 2}],
          'buffers': [{'byteLength': len(binc)}]}
    j = json.dumps(js).encode()
    j += b' ' * (-len(j) % 4)
    data = struct.pack('<4sII', b'glTF', 2, 12 + 8 + len(j) + 8 + len(binc)) + struct.pack('<I4s', len(j), b'JSON') + j + struct.pack('<I4s', len(binc), b'BIN\x00') + binc
    open(path, 'wb').write(data)


# 1. правила и код
src_ss = open(os.path.join(ASSETS, 'sides_sheet.py'), encoding='utf-8').read()
src_js = open(os.path.join(ASSETS, 'sides_sheet.js'), encoding='utf-8').read()
ok(len(SH['views']) == 6 and SH['views'][0]['dtheta'] == 0 and all(k in v for v in SH['views'] for k in ('name', 'dtheta', 'elev')), 'лист: 6 видов в правилах sides-sheet.json (имя, поворот, высота)')
ok(not re.search(r'\b(420|172|270)\b', src_ss) and not re.search(r"'(перед|зад|бок)'", src_ss), 'лист: чисел видов и названий видов в коде нет')
ok(not re.search(r"\b(420|600)\b", src_js) and 'material_stage' not in src_ss and 'frame_render' not in src_ss, 'лист: чисел съёмки в JS нет; от шага 08-frames и рецептов материала не зависит')
orbs = SS.orbits_for(SH, 350.0)
ok(orbs[1]['orbit'].startswith('30.0deg ') and orbs[0]['orbit'].startswith('350.0deg ') and orbs[5]['orbit'].split()[1] == f"{90 - SH['views'][5]['elev']:g}deg", f"лист: перед = азимут фото, остальные от него по кругу ({orbs[0]['orbit']} … {orbs[1]['orbit']})")

# 2. весь путь на подмене съёмки
with tempfile.TemporaryDirectory() as t:
    glb = os.path.join(t, 'a.glb'); box_glb(glb, (0.8, 0.5, 0.2, 1))
    ph = os.path.join(t, 'photo.png'); Image.new('RGBA', (300, 200), (200, 50, 50, 255)).save(ph)
    chk = os.path.join(t, 'check.json'); json.dump({'extra': {'camera': {'az': 33.0}}}, open(chk, 'w'))
    items = [{'id': 'good', 'glb': glb, 'photo': ph, 'az': 12.0}, {'id': 'noaz', 'glb': glb, 'photo': ph}, {'id': 'noglb', 'glb': os.path.join(t, 'нет.glb'), 'photo': ph, 'az': 0},
             {'id': 'bycheck', 'glb': glb, 'photo': ph, 'check06': chk}]
    seen = {}

    def fake_render(sp):
        spec = json.load(open(sp))
        rep = {}
        for it in spec['items']:
            seen[it['id']] = it['orbits'][0]['orbit']
            os.makedirs(os.path.join(spec['out'], it['id']), exist_ok=True)
            tags = [o['tag'] for o in it['orbits']][:-1]                      # последний вид «не вышел»
            for tg in tags:
                Image.new('RGB', (SH['size'], SH['size']), (255, 255, 255)).save(os.path.join(spec['out'], it['id'], tg + '.png'))
            rep[it['id']] = {'ok': False, 'tags': tags, 'notes': ['фейк'], 'seconds': 1.0}
        json.dump(rep, open(os.path.join(spec['out'], 'items.json'), 'w'))
        return type('R', (), {'stdout': 'x', 'stderr': ''})()
    out = os.path.join(t, 'sheets')
    tm = SS.batch(items, out, render_fn=fake_render)
    ok(tm['noaz']['ok'] is False and 'азимут' in tm['noaz']['notes'][0] and tm['noglb']['ok'] is False and not os.path.exists(os.path.join(out, 'noaz.png')), 'лист: нет азимута / нет GLB → не вышел с причиной, PNG не пишется')
    ok(seen['good'].startswith('12.0deg ') and seen['bycheck'].startswith('33.0deg ') and 'noaz' not in seen, 'лист: азимут из items.json или из 06-visible/check.json; без азимута товар в съёмку не идёт')
    sheet = Image.open(os.path.join(out, 'good.png'))
    ok(sheet.size == (SH['size'] * (len(SH['views']) + 1), SH['size'] + SH['header_px']) and not os.path.isdir(os.path.join(out, '_work')), f'лист: одна PNG {sheet.size}, фото + виды, рабочая папка убрана; частично снятый товар собран, не «ok»')
    ok(tm['good']['ok'] is False, 'лист: не все виды нарисованы → ok=False (код возврата 1)')
    tm2 = SS.batch([items[0]], out, render_fn=fake_render)
    ok('noaz' in tm2 and 'good' in tm2 and tm2['_total']['items'] == 1, 'лист: повторный запуск на части списка дополняет times.json, не стирает')

# 3. настоящая съёмка (Chromium + model-viewer), в CI включена
if os.environ.get('REMLAB_SHEET_E2E') == '1':
    with tempfile.TemporaryDirectory() as t:
        glb = os.path.join(t, 'a.glb'); box_glb(glb, (0.8, 0.5, 0.2, 1))
        ph = os.path.join(t, 'photo.png'); Image.new('RGB', (300, 200), (200, 50, 50)).save(ph)
        tm = SS.batch([{'id': 'box', 'glb': glb, 'photo': ph, 'az': 20.0}], os.path.join(t, 'o'))
        im = np.asarray(Image.open(os.path.join(t, 'o', 'box.png')).convert('RGB')).astype(int)
        S, hp = SH['size'], SH['header_px']
        cells = [im[hp:, (i + 1) * S:(i + 2) * S] for i in range(len(SH['views']))]
        dark = [int(((c.sum(axis=2)) < 700).sum()) for c in cells]
        ok(tm['box']['ok'] is True and all(d > 500 for d in dark), f"настоящая съёмка ящика: все {len(SH['views'])} видов с предметом на белом (пикселей предмета {dark})")
else:
    print('  · настоящая съёмка пропущена: REMLAB_SHEET_E2E=1 (нужны node, Playwright с Chromium, сеть) — в CI включена')

print(f'итог: {"FAIL (%d)" % FAIL if FAIL else "ВСЁ ЗЕЛЁНОЕ 0"}')
sys.exit(1 if FAIL else 0)
