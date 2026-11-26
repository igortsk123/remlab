#!/usr/bin/env python3
"""Лист «со всех сторон» браузером (tools/assets/sides_sheet.py, T-20261123-27/1): виды из правил sides-sheet.json, подмена съёмки, настоящий ящик (REMLAB_SHEET_E2E=1: node + Playwright + сеть для CDN).
Без ID товаров, чисел видов/размеров в коде нет. Запуск: python tools/assets/tests/test_sides_sheet.py      (numpy + Pillow)"""
import json
import os
import shutil
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
    fp = SS.batch([dict(items[0], id='fp', photo=os.path.join(t, 'x', '07-fill', 'frame-photo.png'))], os.path.join(t, 'sheets-fp'), render_fn=fake_render)
    ok(fp['fp']['ok'] is False and 'frame-photo' in fp['fp']['notes'][0], 'лист: в колонке ФОТО frame-photo.png (кадр-рендер 07, не фото товара) → отказ с причиной (T-21)')

# 2б. свет листа = свет сайта: числа в sides-sheet.json — зеркало window-light.ts:LIGHT и позиций света в viewer.ts (разошлись — красный)
ROOT = os.path.join(ASSETS, '..', '..')
wl = open(os.path.join(ROOT, 'lib', 'viewer3d', 'window-light.ts'), encoding='utf-8').read()
vw = open(os.path.join(ROOT, 'lib', 'viewer3d', 'viewer.ts'), encoding='utf-8').read()
body = wl[wl.index('export const LIGHT'):]
body = body[:body.index('};')]


def ts_num(key):
    m = re.search(r'\b' + key + r':\s*(0x[0-9a-fA-F]+|[0-9.]+)', body)
    return None if not m else (int(m.group(1), 16) if m.group(1).startswith('0x') else float(m.group(1)))


site = SH.get('site', {})
Lj = site.get('light', {})
keys = ['exposure', 'env', 'hemi', 'hemiSky', 'hemiGround', 'sun', 'sunColor', 'fill']
ok(isinstance(site.get('enabled'), bool) and all(ts_num(k) is not None and ts_num(k) == Lj.get(k) for k in keys), 'свет листа: числа sides-sheet.json site.light = window-light.ts:LIGHT (' + ', '.join(f'{k} {Lj.get(k)} / {ts_num(k)}' for k in keys if ts_num(k) != Lj.get(k)) + ')')
ms = re.search(r'sun\.position\.set\((-?[0-9.]+),\s*(-?[0-9.]+),\s*(-?[0-9.]+)\)', vw)
mf = re.search(r'fill\.position\.set\((-?[0-9.]+),\s*(-?[0-9.]+),\s*(-?[0-9.]+)\)', vw)
mfc = re.search(r'new THREE\.DirectionalLight\((0x[0-9a-fA-F]+),\s*LIGHT\.fill\)', vw)
ok(ms and mf and mfc and [float(x) for x in ms.groups()] == Lj.get('sunPos') and [float(x) for x in mf.groups()] == Lj.get('fillPos') and int(mfc.group(1), 16) == Lj.get('fillColor'), 'свет листа: позиции солнца/подсветки и цвет подсветки = viewer.ts')
ok('three@' in site.get('libs', {}).get('three', '') and re.search(r'"three": "0\.', open(os.path.join(ROOT, 'package.json'), encoding='utf-8').read()) is not None, 'свет листа: three в правилах (версия из CDN-адреса) и в package.json есть')
sp = SS.build_spec(dict(SH, site=dict(site, enabled=True)), 'x', [], False)
sp_off = SS.build_spec(dict(SH, site=dict(site, enabled=False)), 'x', [], False)
ok(sp['site'] is not None and sp['site']['light'] == Lj and sp_off['site'] is None, 'свет листа: ОБА режима — enabled=true: spec несёт site.light (свет сайта); enabled=false: site нет → model-viewer (свет подгонки)')
sp_def = SS.build_spec(SH, 'x', [], False)
ok(site.get('enabled') is True and sp_def['site'] is not None and sp_def['site']['light'] == Lj, 'свет листа: БЕЗ ФЛАГА лист снят СВЕТОМ САЙТА (директор 26.11, T-99/11): site.enabled=true, spec несёт site.light; свет подгонки — только явным --light fit')
ok(SS.light_name(SH) == 'свет сайта' and SS.light_name(SS.light_rules(SH, 'fit')) == 'свет подгонки', 'свет листа: подпись на листе — «свет сайта» по умолчанию, «свет подгонки» при --light fit')
sp_fit0 = SS.build_spec(SS.light_rules(SH, 'fit'), 'x', [], False)
ok(sp_fit0['site'] is None, 'свет листа: --light fit — явный флаг для отладки, site нет → model-viewer')
sp_fit = SS.build_spec(SS.light_rules(dict(SH, site=dict(site, enabled=True)), 'fit'), 'x', [], False)
sp_site = SS.build_spec(SS.light_rules(SH, 'site'), 'x', [], False)
ok(sp_fit['site'] is None and sp_site['site'] is not None and sp_site['site']['light'] == Lj and SS.light_rules(SH, None) is SH and SS.light_rules(SH, 'default') is SH, 'свет листа: --light fit|site переопределяет site.enabled на прогон, default — как в правилах')
try:
    SS.light_rules(SH, 'sun')
    bad_light = False
except ValueError:
    bad_light = True
ok(bad_light, 'свет листа: неизвестный свет — ошибка, а не тихий default')
ok('RoomEnvironment' in src_js and 'toneMapping = THREE.NeutralToneMapping' in src_js and not re.search(r'\b0\.(9|42|8)\b|1\.05', src_js), 'свет листа: JS собирает сцену как сайт (RoomEnvironment + Neutral), чисел света в нём нет')

# 2в. node_fallback: нет node_modules/playwright рядом — NODE_PATH основной копии из правил + строка в журнал; есть — не трогаем
with tempfile.TemporaryDirectory() as t:
    root = os.path.join(t, 'wt'); main_nm = os.path.join(t, 'main', 'nm')
    os.makedirs(os.path.join(root, 'tools')); os.makedirs(os.path.join(main_nm, 'playwright'))
    rules_fb = {'node_fallback': {'paths': [os.path.join(t, 'нет-такого'), main_nm]}}
    e1, l1 = SS.node_env(rules_fb, root, {'PATH': '/bin'})
    ok(e1.get('NODE_PATH') == main_nm and l1 and 'node_fallback' in l1, 'node: в worktree нет node_modules → NODE_PATH = основная копия (первый существующий путь), строка в журнал')
    os.makedirs(os.path.join(root, 'node_modules', 'playwright'))
    e2, l2 = SS.node_env(rules_fb, root, {'PATH': '/bin'})
    ok('NODE_PATH' not in e2 and l2 is None, 'node: node_modules/playwright рядом — окружение не трогаем')
    shutil.rmtree(os.path.join(root, 'node_modules'))
    e3, l3 = SS.node_env(rules_fb, root, {'NODE_PATH': main_nm})
    ok(e3['NODE_PATH'] == main_nm and l3 is None, 'node: свой NODE_PATH с playwright — не трогаем')
    e4, l4 = SS.node_env({'node_fallback': {'paths': []}}, root, {})
    ok('NODE_PATH' not in e4 and l4 and 'не найден' in l4, 'node: ничего не нашли — честная строка, а не тихий провал')
ok(SS.load_rules().get('node_fallback', {}).get('paths'), 'правила: node_fallback.paths заданы в sides-sheet.json, а не в коде')

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
        tc = SS.batch([{'id': 'boxc', 'glb': glb, 'photo': ph, 'az': 20.0}], os.path.join(t, 'oc'), clay=True)
        cl = np.asarray(Image.open(os.path.join(t, 'oc', 'boxc.clay.png')).convert('RGB')).astype(int)
        ccells = [cl[hp:, (i + 1) * S:(i + 2) * S] for i in range(len(SH['views']))]
        gr = [float(np.abs(c[..., 0] - c[..., 2]).mean()) for c in ccells]
        ok(tc['boxc']['ok'] is True and all(g_ < 8 for g_ in gr), f'лист «глина»: белый материал без цвета ящика (разброс R−B {[round(g_, 1) for g_ in gr]})')
else:
    print('  · настоящая съёмка пропущена: REMLAB_SHEET_E2E=1 (нужны node, Playwright с Chromium, сеть) — в CI включена')

print(f'итог: {"FAIL (%d)" % FAIL if FAIL else "ВСЁ ЗЕЛЁНОЕ 0"}')
sys.exit(1 if FAIL else 0)
