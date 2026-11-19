#!/usr/bin/env python3
"""Тесты `tex_fill.py` (T-20261119-50/1): заливка дыр по поверхности меша внутри своей материальной области. Без сети, видеокарты и MV-Adapter: синтетические плоскости с готовой картой классов.
Главное: цвет хороших текселей НЕ меняется (diff = 0), красное не течёт на синее, нет донора — отказ с причиной (цвет прежний), форма и развёртка после записи GLB те же.

  python3 tools/scout/salad/trellis/tests_tex_fill.py
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.normpath(os.path.join(HERE, '..', '..')))
import remlab_tmp  # noqa: E402
remlab_tmp.use('tests_tex_fill')
import numpy as np  # noqa: E402
import tex_fill as TF  # noqa: E402

bad = 0
T = 128


def ok(name, cond, extra=''):
    global bad
    print(('  ✓ ' if cond else '  ✗ ') + name + (f' — {extra}' if extra and not cond else ''))
    bad += 0 if cond else 1


def plane(x0=0.0, x1=2.0, z=0.0, y0=0.0, y1=1.0, u0=0.0, u1=1.0):
    """Плоскость z=const из двух треугольников, развёртка — квадрат [u0,u1]×[0,1] (линейно по x и y). Нормаль +Z."""
    V = np.array([(x0, y0, z), (x1, y0, z), (x1, y1, z), (x0, y1, z)], np.float64)
    F = np.array([(0, 1, 2), (0, 2, 3)], np.int64)
    UV = np.array([(u0, 0), (u1, 0), (u1, 1), (u0, 1)], np.float64)
    return V, F, UV


def two_colour_tex(split_col=T // 2, left=(200, 30, 30), right=(30, 30, 200)):
    t = np.zeros((T, T, 3), np.uint8)
    t[:, :split_col] = left
    t[:, split_col:] = right
    return t


def main() -> int:
    global bad
    bad = 0
    # --- цвет: Lab ↔ sRGB, k-means
    from tex_coverage import rgb2lab
    probe = np.array([[200, 30, 30], [30, 30, 200], [10, 200, 90], [128, 128, 128]], np.uint8)
    ok('lab2rgb обратна rgb2lab (±1)', int(np.abs(TF.lab2rgb(rgb2lab(probe)).astype(int) - probe.astype(int)).max()) <= 1)
    X = np.vstack([np.random.RandomState(1).normal(m, 0.5, (200, 3)) for m in ((10, 0, 0), (60, 40, 20), (90, -30, 50))])
    C = TF.kmeans(X, 3, 10)
    ok('k-means находит 3 разных центра', len({int(np.argmin(((C - m) ** 2).sum(1))) for m in ((10, 0, 0), (60, 40, 20), (90, -30, 50))}) == 3)

    # --- заливка по поверхности внутри материала
    V, F, UV = plane()
    tex = two_colour_tex()
    cls = np.ones((T, T), np.uint8)
    cls[40:60, 50:62] = 2            # слева от границы (красная область: колонки < 64)
    cls[40:60, 66:78] = 2            # справа (синяя)
    cls[90:100, 20:30] = 4           # «unpainted» в красной
    tex[cls == 2] = (0, 0, 0)
    tex[cls == 4] = (255, 255, 255)
    new, st, act = TF.fill_geom(V, F, UV, tex, cls)
    ok('залито всё плохое, отказов нет', st['filled'] == st['bad_before'] and st['refused_total'] == 0, str(st))
    gd = TF.good_diff(tex, new, cls)
    ok('хорошие тексели не изменились (diff = 0, ΔE00 = 0)', gd['changed'] == 0 and gd['de00_max'] == 0.0 and gd['good'] > 0, str(gd))
    left = new[40:60, 50:62].reshape(-1, 3).astype(int)
    right = new[40:60, 66:78].reshape(-1, 3).astype(int)
    ok('в красной области залито красным, в синей — синим (не течёт сквозь границу материала)',
       np.abs(left - [200, 30, 30]).max() <= 2 and np.abs(right - [30, 30, 200]).max() <= 2, f'{left.mean(0)} {right.mean(0)}')
    ok('unpainted залит цветом области', np.abs(new[90:100, 20:30].reshape(-1, 3).astype(int) - [200, 30, 30]).max() <= 2)
    ok('карта действий: залито = 1', int((act == 1).sum()) == st['bad_before'])

    # --- пятно ровно на границе материалов берёт цвет ближней стороны (голосование по 1/d²)
    cls2 = np.ones((T, T), np.uint8)
    cls2[50:60, 58:63] = 2           # центр на колонке 60.5 — ближе к красной стороне (граница 64)
    tex2 = two_colour_tex()
    tex2[cls2 == 2] = (0, 0, 0)
    new2, st2, _ = TF.fill_geom(V, F, UV, tex2, cls2)
    ok('пятно у границы — цвет ближней стороны, чистый красный без примеси синего', np.abs(new2[50:60, 58:63].reshape(-1, 3).astype(int) - [200, 30, 30]).max() <= 2,
       str(new2[50:60, 58:63].reshape(-1, 3).mean(0)))

    # --- нет донора: радиус
    cls3 = np.zeros((T, T), np.uint8)
    cls3[:, :] = 1
    cls3[10:100, 10:100] = 2         # почти всё плохо; хорошие — только по краям
    new3, st3, act3 = TF.fill_geom(V, F, UV, tex, cls3, params={'radius': 0.01})
    ok('донор дальше радиуса — отказ с причиной, цвет прежний', st3['refused']['no_donor_radius'] > 0 and st3['refused_total'] == st3['refused']['no_donor_radius']
       and np.array_equal(new3[50, 50], tex[50, 50]) and (act3 == 3).any(), str(st3))
    ok('отказы и залитое в сумме дают плохое', st3['filled'] + st3['blended'] + st3['refused_total'] == st3['bad_before'])

    # --- нет донора: только чужая часть формы
    VA, FA, UVA = plane(0, 1, 0, 0, 1, 0.0, 0.5)
    VB, FB, UVB = plane(1.01, 2, 0, 0, 1, 0.5, 1.0)
    V2 = np.vstack([VA, VB])
    F2 = np.vstack([FA, FB + 4])
    UV2 = np.vstack([UVA, UVB])
    tex4 = np.zeros((T, T, 3), np.uint8)
    tex4[:] = (90, 160, 90)
    cls4 = np.ones((T, T), np.uint8)
    cls4[:, :T // 2] = 2             # вся часть A плохая; донор рядом — только часть B (радиус большой, но другая часть формы)
    new4, st4, _ = TF.fill_geom(V2, F2, UV2, tex4, cls4, params={'cross_radius': 0})
    ok('донор есть только на другой части формы (ярус 3 выключен) — отказ no_donor_component', st4['refused']['no_donor_component'] > 0 and st4['filled'] == 0, str(st4['refused']))
    new4b, st4b, _ = TF.fill_geom(V2, F2, UV2, tex4, cls4)
    ok('ярус 3: чужая часть формы рядом (≤ cross_radius) — залито, счётчик «чужая часть»; дальше — отказ по радиусу',
       st4b['filled_other_part'] > 0 and st4b['refused']['no_donor_radius'] > 0 and st4b['filled'] == st4b['filled_other_part'], str(st4b))

    # --- другая сторона: ярус 2 (внутренняя сторона берёт цвет с наружной), и запрет при any_side=False
    Vt = np.array([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0), (0, 0, 0.02), (1, 0, 0.02), (1, 1, 0.02), (0, 1, 0.02)], np.float64)
    Ft = np.array([(0, 1, 2), (0, 2, 3), (4, 6, 5), (4, 7, 6), (0, 4, 5), (0, 5, 1)], np.int64)        # две пластины с нормалями +Z и -Z и боковая лента (склеивает в одну часть формы)
    UVt = np.array([(0, 0), (0.5, 0), (0.5, 1), (0, 1), (0.5, 0), (1, 0), (1, 1), (0.5, 1)], np.float64)
    UVt[:, 0] *= 1.0
    texT = np.zeros((T, T, 3), np.uint8)
    texT[:] = (150, 120, 60)
    clsT = np.ones((T, T), np.uint8)
    clsT[:, T // 2 + 2:] = 2         # развёртка второй пластины целиком плохая
    newT, stT, _ = TF.fill_geom(Vt, Ft, UVt, texT, clsT)
    ok('внутренняя сторона (нормали навстречу) заливается доноров другой стороны той же части, счётчик «другая сторона»', stT['filled_other_side'] > 0 and stT['refused_total'] < stT['bad_before'], str(stT))
    newT2, stT2, _ = TF.fill_geom(Vt, Ft, UVt, texT, clsT, params={'any_side': False, 'cross_radius': 0})
    ok('any_side=False — доноров другой стороны нет, отказ no_donor_normal', stT2['refused']['no_donor_normal'] > 0, str(stT2['refused']))

    # --- grazing: смешивание по весу угла
    clsG = np.ones((T, T), np.uint8)
    clsG[40:60, 40:60] = 3
    texG = np.zeros((T, T, 3), np.uint8)
    texG[:] = (100, 100, 100)
    texG[40:60, 40:60] = (200, 200, 200)
    newG, stG, _ = TF.fill_geom(V, F, UV, texG, clsG, views=[(np.array([0.0, 0.0, 1.0]), None, None)])
    ok('grazing с cos=1 (смотрит на вид) — исходный цвет остаётся', np.abs(newG[40:60, 40:60].astype(int) - 200).max() == 0 and stG['blended'] > 0, str(stG))
    newG0, stG0, _ = TF.fill_geom(V, F, UV, texG, clsG, views=[(np.array([1.0, 0.0, 0.0]), None, None)])
    ok('grazing с cos=0 (ребром) — цвет донора', np.abs(newG0[40:60, 40:60].astype(int) - 100).max() <= 1)
    newGm, _, _ = TF.fill_geom(V, F, UV, texG, clsG, views=[(np.array([0.2, 0.0, 0.0]) / 0.2 * 0 + np.array([np.sqrt(1 - 0.2 ** 2), 0.0, 0.2]), None, None)])
    mid = float(newGm[50, 50, 0])
    ok('grazing с cos=0,2 — смесь между донором и исходным', 100 < mid < 200, str(mid))

    # --- крупные области unpainted — настоящий цвет, не трогаем
    clsU = np.ones((T, T), np.uint8)
    clsU[:, T // 2:] = 4             # половина карты «фон» — это чёрный/белый материал, а не дыры
    clsU[10:14, 10:14] = 4           # малое пятно — дыра
    texU = np.zeros((T, T, 3), np.uint8)
    texU[:, :T // 2] = (200, 30, 30)
    texU[:, T // 2:] = (255, 255, 255)
    texU[10:14, 10:14] = (255, 255, 255)
    newU, stU, _ = TF.fill_geom(V, F, UV, texU, clsU)
    ok('большая область unpainted не залита (настоящий цвет), малое пятно — залито', stU['unpainted_big_kept'] > 0 and np.array_equal(newU[:, T // 2:], texU[:, T // 2:])
       and np.abs(newU[10:14, 10:14].astype(int) - [200, 30, 30]).max() <= 2, str(stU))

    # --- нет плохих / нет хороших
    new5, st5, _ = TF.fill_geom(V, F, UV, tex, np.ones((T, T), np.uint8))
    ok('плохих нет — текстура та же', np.array_equal(new5, tex) and st5['bad_before'] == 0)
    new6, st6, _ = TF.fill_geom(V, F, UV, tex, np.full((T, T), 2, np.uint8))
    ok('хороших нет — отказ no_good', st6['refused']['no_good'] == st6['bad_before'] and np.array_equal(new6, tex))

    # --- резкость: энергия высоких частот по хорошим текселям вокруг залитого — до и после равна
    rng = np.random.RandomState(2)
    texH = (rng.rand(T, T, 3) * 255).astype(np.uint8)
    clsH = np.ones((T, T), np.uint8)
    clsH[50:70, 50:70] = 2
    newH, stH, actH = TF.fill_geom(V, F, UV, texH, clsH)
    h0, h1 = TF.hf_energy(texH, clsH, actH), TF.hf_energy(newH, clsH, actH)
    ok('энергия высоких частот у залитого до = после (принт не размыт)', h0['hf_energy'] is not None and h0['hf_energy'] == h1['hf_energy'] and h0['texels'] > 0, f'{h0} {h1}')
    ok('мерка видит размытие (контроль): размытые хорошие тексели дают другое число', TF.hf_energy(__import__('scipy.ndimage', fromlist=['x']).gaussian_filter(texH.astype(float), (2, 2, 0)).astype(np.uint8), clsH, actH)['hf_energy'] != h0['hf_energy'])

    # --- сторож формы
    import trimesh
    from PIL import Image
    from trimesh.visual import TextureVisuals
    from trimesh.visual.material import PBRMaterial
    mesh = trimesh.Trimesh(vertices=V, faces=F, process=False)
    mesh.visual = TextureVisuals(uv=UV, material=PBRMaterial(baseColorTexture=Image.fromarray(tex), metallicFactor=0.0, roughnessFactor=1.0))
    import tempfile
    tmpd = tempfile.mkdtemp(prefix='tex_fill_')
    src = os.path.join(tmpd, 'a.glb')
    trimesh.Scene([mesh]).export(src)
    import tex_coverage as TC
    g0 = TC.load_geoms(src)
    dst = os.path.join(tmpd, 'a-fill.glb')
    TF.write_glb(g0, [new], dst)
    g1 = TC.load_geoms(dst)
    gg = TF.guard_geometry(g0, g1)
    ok('после записи GLB вершины, грани и UV те же (1e-6)', gg['ok'], str(gg))
    ok('после записи GLB хорошие тексели те же (чтение из файла)', TF.good_diff(g0[0]['tex'], g1[0]['tex'], cls)['changed'] == 0)
    g2 = [dict(g1[0], V=g1[0]['V'] + np.array([0, 0, 1e-3]))]
    ok('сторож ловит сдвиг вершины на 1e-3', not TF.guard_geometry(g0, g2)['ok'])
    g3 = [dict(g1[0], UV=g1[0]['UV'] + 1e-3)]
    ok('сторож ловит сдвиг развёртки на 1e-3', not TF.guard_geometry(g0, g3)['ok'])
    print('ИТОГ: ' + ('всё ok' if not bad else f'ошибок {bad}'))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
