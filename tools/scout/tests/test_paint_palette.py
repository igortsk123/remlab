#!/usr/bin/env python3
"""Сторож палитры итоговой текстуры (T-20261121-174/1): малиновая заглушка вне палитры фото. Синтетика: свой GLB с атласом из временной папки, без сети и платного.
Запуск: python3 tools/scout/tests/test_paint_palette.py   (нужны numpy, Pillow, trimesh)"""
import json
import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'assets'))
import remlab_tmp  # noqa: E402
remlab_tmp.use('test_paint_palette')
import numpy as np  # noqa: E402
import trimesh  # noqa: E402
from PIL import Image  # noqa: E402
import paint_palette as PP  # noqa: E402

RULES = os.path.join(HERE, '..', 'rules', 'stablegen-view-guard.json')
G = PP.load_guard()                       # общие правила малинового: один файл на виды и атлас
P = G['magenta_baked']
FAIL = 0


def ok(cond, name):
    global FAIL
    print(('  ✓ ' if cond else '  ✗ ') + name)
    FAIL += 0 if cond else 1


def px(c):
    return np.array([[list(c)]], dtype=np.uint8)


# ---- оттенок: заглушка (в т.ч. потемневшая после запекания) ловится, законные цвета — нет
for name, c, want in [('чистая (255,0,255)', (255, 0, 255), True), ('потемневшая с кровати (158,11,115)', (158, 11, 115), True),
                      ('сиреневая заглушка (180,21,206)', (180, 21, 206), True), ('дерево (200,160,100)', (200, 160, 100), False),
                      ('винный (110,20,40): синего мало', (110, 20, 40), False), ('светло-розовый (255,150,200): зелёного много', (255, 150, 200), False),
                      ('тёмный (60,0,50): слишком тёмный', (60, 0, 50), False), ('серый/чёрный фон (0,0,0)', (0, 0, 0), False), ('красный (220,20,30)', (220, 20, 30), False),
                      ('синий (30,40,200)', (30, 40, 200), False)]:
    ok(bool(PP.texel_mask(px(c), P)[0, 0]) == want, f'оттенок: {name} → {"малиновое" if want else "не малиновое"}')


def glb_two_quads(path, mag_quad_area=1.0, grey_quad_area=3.0, atlas_mag=True):
    """Два прямоугольника: первый (площадь mag_quad_area) смотрит на левую половину атласа, второй — на правую. Левая — малиновая (если atlas_mag), правая — серая."""
    atlas = np.zeros((64, 64, 3), np.uint8)
    atlas[:, :32] = (158, 11, 115) if atlas_mag else (120, 120, 120)
    atlas[:, 32:] = (120, 120, 120)
    w1, w2 = mag_quad_area, grey_quad_area
    v = np.array([[0, 0, 0], [w1, 0, 0], [w1, 1, 0], [0, 1, 0], [2, 0, 0], [2 + w2, 0, 0], [2 + w2, 1, 0], [2, 1, 0]], float)
    f = np.array([[0, 1, 2], [0, 2, 3], [4, 5, 6], [4, 6, 7]])
    uv = np.array([[0.05, 0.1], [0.45, 0.1], [0.45, 0.9], [0.05, 0.9], [0.55, 0.1], [0.95, 0.1], [0.95, 0.9], [0.55, 0.9]], float)
    mat = trimesh.visual.material.PBRMaterial(baseColorTexture=Image.fromarray(atlas))
    m = trimesh.Trimesh(v, f, visual=trimesh.visual.TextureVisuals(uv=uv, material=mat), process=False)
    open(path, 'wb').write(trimesh.Scene(m).export(file_type='glb'))


with tempfile.TemporaryDirectory() as td:
    g = os.path.join(td, 'bed.glb')
    glb_two_quads(g)
    r = PP.surface_share(g, P)
    ok(abs(r['share'] - 0.25) < 0.01, f"доля ПЛОЩАДИ: малиновая часть 1 из 4 → {r['share']:.3f} (≈0,25), а не доля атласа")
    ok(abs(r['atlas_share'] - 0.5) < 0.01, f"доля атласа отдельно: {r['atlas_share']:.3f} (≈0,5) — видно, что площадь и атлас разные меры")
    ok(r['rgb'] == [158, 11, 115], 'средний цвет заглушки записан для разбора')

    glb_two_quads(g, atlas_mag=False)
    ok(PP.surface_share(g, P)['share'] == 0.0, 'чистый атлас → доля 0')

    # огромный малиновый кусок атласа, на который не смотрит ни одна грань, — покупатель его не увидит: площадь 0
    glb_two_quads(g, mag_quad_area=1.0, grey_quad_area=3.0)
    a = np.zeros((64, 64, 3), np.uint8) + 120
    a[:, :10] = (255, 0, 255)
    v = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]], float)
    uv = np.array([[0.5, 0.1], [0.9, 0.1], [0.9, 0.9], [0.5, 0.9]], float)
    mat = trimesh.visual.material.PBRMaterial(baseColorTexture=Image.fromarray(a))
    m = trimesh.Trimesh(v, np.array([[0, 1, 2], [0, 2, 3]]), visual=trimesh.visual.TextureVisuals(uv=uv, material=mat), process=False)
    open(g, 'wb').write(trimesh.Scene(m).export(file_type='glb'))
    r = PP.surface_share(g, P)
    ok(r['share'] == 0.0 and r['atlas_share'] > 0.1, 'малиновое в неиспользуемом куске атласа: по площади 0 (не видно), по атласу >10 % — решает площадь')

    # без текстуры — не измерено (None), а не «чисто»
    m = trimesh.Trimesh(v, np.array([[0, 1, 2], [0, 2, 3]]), process=False)
    open(g, 'wb').write(trimesh.Scene(m).export(file_type='glb'))
    ok(PP.surface_share(g, P)['share'] is None, 'в GLB нет текстуры цвета → share None (не измерено)')

    # фото: доля малинового среди пикселей предмета; прозрачный фон не считается
    ph = os.path.join(td, 'photo.png')
    im = np.zeros((10, 10, 4), np.uint8)
    im[:5, :, 3] = 255
    im[:5, :, :3] = (120, 120, 120)
    im[:2, :, :3] = (200, 20, 170)
    Image.fromarray(im, 'RGBA').save(ph)
    ok(abs(PP.photo_share(ph, P) - 0.4) < 1e-6, 'фото: 2 из 5 рядов предмета малиновые → 0,4; прозрачная половина не считается')
    ok(PP.photo_share(None, P) == 0.0 and PP.photo_share(os.path.join(td, 'нет.png'), P) == 0.0, 'нет фото/файла → 0 (допуска нет, строже)')
    glb_two_quads(g)
    out = PP.run_palette(g, ph, G)
    ok(set(out) >= {'share', 'photo_share', 'atlas_share', 'rgb'} and abs(out['photo_share'] - 0.4) < 1e-6, 'run_palette: все поля для этапа 9')

# ---- правила: данные, не код; идентификаторов товаров нет ни в модуле, ни в правилах
src = open(os.path.join(HERE, '..', 'paint_palette.py'), encoding='utf-8').read() + open(RULES, encoding='utf-8').read()
ok(not re.search(r'\d{5,}_\d{6,}', src), 'ни в коде, ни в правилах нет id товаров (вида 99272_607007941975253599)')
hard, soft = PP.thresholds(G)
ok(0 < soft < hard < 0.1, 'пороги в данных: 0 < мягкий < жёсткий < 10 % площади')
ok(hard == G['magenta']['obj_frac_max'], 'жёсткий порог доли — тот же, что у сторожа видов (magenta.obj_frac_max): один источник')
# мерка видов (широкая) недоглядела бы потемневшую заглушку атласа, мерка атласа — нет (оттенок кровати №4)
v = G['magenta']
rv, gv, bv = 158, 11, 115
ok(not (rv > v['r_min'] and bv > v['b_min'] and gv < v['g_ratio_max'] * min(rv, bv)), 'потемневшая (158,11,115): широкая мерка видов её не видит (b 115 < 120) — потому у атласа свой блок magenta_baked')

print('итог: ' + ('чисто' if not FAIL else f'ПРОВАЛЕНО {FAIL}'))
sys.exit(1 if FAIL else 0)
