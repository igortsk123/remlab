#!/usr/bin/env python3
"""Тесты ref_zone (Ш8м, T-187/4): тот же меш, решения по свойствам с not_applicable, гейт по свойству, продолжение зон по сваренным вершинам и отказ при споре.
  python3 tools/scout/salad/trellis/tests_ref_zone.py"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ref_zone as RZ  # noqa: E402

FAILS = []


def ok(cond, msg):
    print(('  ✓ ' if cond else '  ✗ ') + msg)
    if not cond:
        FAILS.append(msg)


def strip(n_quads: int, split: bool):
    """Полоса из 2n треугольников; split=True — у каждой грани свои вершины (как у GLB, разрезанного по швам UV)."""
    V, F = [], []
    for i in range(n_quads + 1):
        V += [[i, 0, 0], [i, 1, 0]]
    for i in range(n_quads):
        F += [[2 * i, 2 * i + 1, 2 * i + 2], [2 * i + 1, 2 * i + 3, 2 * i + 2]]
    V, F = np.array(V, float), np.array(F)
    if split:
        V = V[F].reshape(-1, 3)
        F = np.arange(len(V)).reshape(-1, 3)
    return V, F


def agg(hf=2.0, pat=0.0, period=None, ang=None, uni=5.0, n=10):
    return {'n': n, 'hf': hf, 'macro': 3.0 if pat else 0.2, 'pat_share': pat, 'period': period, 'dir_share': 1.0 if ang is not None else 0.0, 'ang': ang, 'uniform': uni, 'meanL': 50.0}


def test_same_mesh():
    print('образец = наш меш:')
    V, F = strip(3, False)
    g = {'V': V, 'F': F, 'UV': np.random.default_rng(0).random((len(V), 2))}
    h = {k: v.copy() for k, v in g.items()}
    ok(RZ.same_mesh([g], [h])['same'], 'те же вершины, грани и UV — тот же меш')
    h2 = dict(h, UV=h['UV'] + 0.01)
    ok(not RZ.same_mesh([g], [h2])['same'], 'сдвиг UV — другой меш')
    h3 = dict(h, F=F[:-1])
    ok(not RZ.same_mesh([g], [h3])['same'], 'другое число граней — другой меш')


def test_decide():
    print('решения по свойствам, not_applicable, воздержание:')
    d = RZ.decide(None, agg())
    ok(all(v['decision'] == 'unknown' for v in d.values()), 'мало окон с видимой стороны — всё unknown')
    d = RZ.decide(agg(hf=2.0), agg(hf=2.2))
    ok(d['texture']['decision'] == 'same', 'сила фактуры 2,0 и 2,2 — texture same')
    ok(d['pattern']['decision'] == 'same' and d['scale']['decision'] == 'not_applicable' and d['direction']['decision'] == 'not_applicable', 'мотива нет с обеих сторон — масштаб и направление not_applicable')
    d = RZ.decide(agg(hf=2.0), agg(hf=0.3))
    ok(d['texture']['decision'] == 'different', 'фактура 2,0 против 0,3 (ниже пола шума) — texture different')
    d = RZ.decide(agg(pat=0.0), agg(pat=0.9, period=20.0, ang=10.0))
    ok(d['pattern']['decision'] == 'different' and d['scale']['decision'] == 'not_applicable', 'мотив только с одной стороны — pattern different, масштаб not_applicable')
    d = RZ.decide(agg(pat=0.9, period=20.0, ang=10.0), agg(pat=0.9, period=21.0, ang=15.0))
    ok(d['scale']['decision'] == 'same' and d['direction']['decision'] == 'same', 'период 20 и 21, угол 5° — масштаб и направление same')
    d = RZ.decide(agg(pat=0.9, period=20.0, ang=10.0), agg(pat=0.9, period=50.0, ang=100.0))
    ok(d['scale']['decision'] == 'different' and d['direction']['decision'] == 'different', 'период 20 и 50, угол 90° — different')


def test_gate_per_property():
    print('голос образца по свойству: провал выключает только это свойство:')
    g = RZ.gate(agg(hf=2.0, pat=0.0, uni=5.0), agg(hf=2.1, pat=0.9, period=20.0, uni=5.2))
    ok(g['pattern'][0] is False, 'на фото мотив есть, у образца нет — pattern выключен')
    ok(g['texture'][0] and g['uniform'][0], 'texture и uniform остаются включёнными')
    g2 = RZ.gate(None, agg())
    ok(not any(v[0] for v in g2.values()), 'мало окон для сверки с фото — все выключены')


def test_propagate():
    print('продолжение зон по сваренным вершинам, спор → -1:')
    for split in (False, True):
        V, F = strip(12, split)
        fz = np.full(len(F), -1, np.int32)
        fz[0], fz[-1] = 0, 1
        out = RZ.propagate_zones(V, F, fz, None)
        ok(out[1] == 0 and out[-2] == 1, f'split={split}: грани рядом с ярлыком берут его зону')
        mid = len(F) // 2
        ok(out[mid] in (0, 1) and (out >= 0).all(), f'split={split}: грань на равном расстоянии от двух зон берёт ОДНУ из них (смеси нет, -1 нет)')
    V, F = strip(12, False)
    fz = np.full(len(F), -1, np.int32)
    fz[0], fz[-1], fz[-2], fz[-3] = 0, 1, 1, 1
    out, info = RZ.propagate_zones(V, F, fz, None, return_info=True)
    mid = len(F) // 2 + 1
    ok(info['disputed'] >= 1 and out[mid] == 1, f'спорная грань берёт зону с большей площадью видимого (1: 3 грани против 1): {info}')
    V, F = strip(6, True)
    fz = np.full(len(F), -1, np.int32)
    fz[0] = 0
    out = RZ.propagate_zones(V, F, fz, None)
    ok((out == 0).all(), 'один ярлык на всю связную часть — все грани получают его (острова UV сварены)')
    parts = np.zeros(len(F), np.int32)
    parts[6:] = 1
    ok((RZ.propagate_zones(V, F, fz, parts)[6:] == -1).all(), 'другая геометрическая часть — зона не переходит')


def box(nx=4, ny=3, nz=4, w=2.0, h=1.0, d=1.0):
    """Коробка из сетки квадратов (общие вершины в пределах грани), нормали наружу; боковые грани ±x с одинаковой диагональю — зеркальны. → V, F, сторона каждой грани ('front'+z, 'back'-z, 'right'+x, 'left'-x, 'top'+y, 'bottom'-y)."""
    V, F, side = [], [], []

    def face(axis, sign, a, b):
        # сетка по осям a,b; третья ось = ±половина размера
        dims = {0: w, 1: h, 2: d}
        na, nb = (nx, ny, nz)[a], (nx, ny, nz)[b]
        base = len(V)
        for ib in range(nb + 1):
            for ia in range(na + 1):
                p = [0.0, 0.0, 0.0]
                p[a] = (ia / na - 0.5) * dims[a]
                p[b] = (ib / nb - 0.5) * dims[b]
                p[axis] = sign * dims[axis] / 2
                V.append(p)
        for ib in range(nb):
            for ia in range(na):
                v0 = base + ib * (na + 1) + ia
                v1, v2, v3 = v0 + 1, v0 + na + 1, v0 + na + 2
                for tri in ([v0, v1, v3], [v0, v3, v2]):
                    pa, pb, pc = (np.array(V[k]) for k in tri)
                    nn = np.cross(pb - pa, pc - pa)
                    if nn[axis] * sign < 0:
                        tri = [tri[0], tri[2], tri[1]]
                    F.append(tri)
                    side.append({(2, 1): 'front', (2, -1): 'back', (0, 1): 'right', (0, -1): 'left', (1, 1): 'top', (1, -1): 'bottom'}[(axis, sign)])

    face(2, 1, 0, 1)
    face(2, -1, 0, 1)
    face(0, 1, 2, 1)
    face(0, -1, 2, 1)
    face(1, 1, 0, 2)
    face(1, -1, 0, 2)
    return np.array(V), np.array(F), np.array(side)


BASIS = (np.array([1.0, 0, 0]), np.array([0, 1.0, 0]), np.array([0, 0, -1.0]))      # right, up, fwd: камера смотрит вдоль -z, лицо — грани +z


def rot_y(V, deg):
    a = np.radians(deg)
    R_ = np.array([[np.cos(a), 0, np.sin(a)], [0, 1, 0], [-np.sin(a), 0, np.cos(a)]])
    return V @ R_.T


def test_object_basis():
    print('оси предмета при камере под углом:')
    V, F, side = box()
    for deg in (0, 25, -33):
        Vr = rot_y(V, deg)
        b, delta = RZ.object_basis(Vr, F, BASIS)
        ok(abs(abs(delta) - abs(deg)) < 2.0 and np.allclose(np.linalg.norm(b[0]), 1.0), f'поворот {deg}°: найден δ={delta:.1f}°')
        sc = RZ.mirror_score(Vr, F, b[0], 0.015)[0]
        ok(sc > 0.9, f'поворот {deg}°: симметрия по осям предмета {sc:.2f} (по осям камеры была бы ниже)')
        sd = RZ.face_sides(Vr, F, b)
        ok((sd[side == 'front'] == -1).all() and (sd[side == 'back'] == 0).all() and (sd[side == 'right'] == 1).all() and (sd[side == 'left'] == 2).all(), f'поворот {deg}°: стороны лицо/зад/правый/левый определены верно')
    Vr = rot_y(V, 25)
    fz = np.full(len(F), -1, np.int32)
    fz[side == 'front'] = 0
    fz[side == 'left'] = 1
    out = RZ.panel_zones(Vr, F, fz, None, BASIS)
    ok((out[side == 'right'] == 1).all() and (out[side == 'back'] == 1).all(), 'коробка под углом 25°: бок по симметрии и зад по боковым панелям работают')


def test_inconsistent_winding():
    print('меши TRELLIS: обмотка граней не согласована (≈50 % нормалей внутрь) — результат тот же:')
    V, F, side = box()
    rng = np.random.default_rng(3)
    Fz = F.copy()
    flip = rng.random(len(F)) < 0.5
    Fz[flip] = Fz[flip][:, [0, 2, 1]]
    fz = np.full(len(F), -1, np.int32)
    fz[side == 'front'] = 0
    fz[side == 'left'] = 1
    a = RZ.panel_zones(V, F, fz, None, BASIS)
    b = RZ.panel_zones(V, Fz, fz, None, BASIS)
    ok((a == b).all(), 'случайно перевёрнутая обмотка не меняет зоны (панели, стороны, симметрия — без знака нормали)')
    sd = RZ.face_sides(V, Fz, BASIS)
    ok((sd[side == 'front'] == -1).all() and (sd[side == 'back'] == 0).all(), 'стороны лицо/зад по положению, не по знаку нормали')


def test_outer_only():
    print('сторона — только у внешнего края (стенки рельефа на лице ≠ бок):')
    V, F, side = box()
    sd = RZ.face_sides(V, F, BASIS)
    ok((sd[side == 'left'] == 2).all() and (sd[side == 'right'] == 1).all(), 'настоящие боковые грани — бок')
    # стенка внутри: вертикальная грань в середине лицевой плоскости, нормаль вдоль x
    Vi = np.array([[0.0, -0.2, 0.5], [0.0, 0.2, 0.5], [0.0, 0.2, 0.3]], np.float64)
    Fi = np.array([[0, 1, 2]], np.int32)
    Vc = np.vstack([V, Vi])
    Fc = np.vstack([F, Fi + len(V)])
    sc = RZ.face_sides(Vc, Fc, BASIS)
    ok(sc[-1] == -2, 'стенка рельефа с нормалью вбок у центра габарита → не бок (−2)')
    ok((sc[:-1] == sd).all(), 'остальные грани не изменились')


def test_panel_with_bottom():
    print('панель «бок + днище» (слитая) не блокирует зеркало и зад:')
    V, F, side = box()
    fz = np.full(len(F), -1, np.int32)
    fz[side == 'front'] = 0
    fz[side == 'left'] = 1
    # сливаем правый бок и низ в одну панель: общие вершины по ребру + одинаковая плоскость не нужна — проверяем на уровне пары (pid подменой)
    orig = RZ.panel_ids
    try:
        def merged(V_, F_, parts_):
            pid = np.asarray(orig(V_, F_, parts_)).copy()
            m = (side == 'right') | (side == 'bottom')
            pid[m] = pid[side == 'right'][0]
            return pid
        RZ.panel_ids = merged
        out = RZ.panel_zones(V, F, fz, None, BASIS)
    finally:
        RZ.panel_ids = orig
    ok((out[side == 'right'] == 1).all(), 'правый бок в слитой панели — зона по симметрии')
    ok((out[side == 'bottom'] == -1).all(), 'низ той же панели — unknown')


def test_panels():
    print('зоны по панелям (Б): метки в панели, симметрия бока, зад от боков, остальное unknown:')
    V, F, side = box()
    fz = np.full(len(F), -1, np.int32)
    fz[side == 'front'] = 0
    fz[side == 'left'] = 1                                     # левый бок виден на фото, правый и зад нет
    out, info = RZ.panel_zones(V, F, fz, None, BASIS, return_info=True)
    ok((out[side == 'front'] == 0).all(), 'лицо — зона по меткам фото')
    ok(info['sym_score'] is not None and info['sym_score'] >= 0.8, f'коробка симметрична плоскостью лево↔право (score {info["sym_score"]})')
    ok((out[side == 'right'] == 1).all(), 'невидимый правый бок — зона видимого левого (по симметрии)')
    ok((out[side == 'back'] == 1).all(), 'зад без меток — зона боковых панелей (обе стороны зона 1)')
    ok((out[side == 'top'] == -1).all() and (out[side == 'bottom'] == -1).all(), 'крышка и низ без меток — unknown (-1), в зоны не берутся')
    ok(set(np.unique(out)) <= {-1, 0, 1}, 'никакой смеси: только зоны фото или -1')
    # два бока разных зон → зад unknown
    fz2 = fz.copy()
    fz2[side == 'right'] = 2
    out2 = RZ.panel_zones(V, F, fz2, None, BASIS)
    ok((out2[side == 'back'] == -1).all(), 'бока разных зон — зад unknown, а не «бо́льшая зона»')
    # несимметричная форма → невидимый бок unknown
    V3 = V.copy()
    V3[:, 1] += np.where(V3[:, 0] > 0, 0.4, 0.0) * (V3[:, 1] > 0)         # правая верхняя часть сдвинута — двойников у части граней нет
    V3[V3[:, 0] > 0.0, 0] *= 1.6
    out3, info3 = RZ.panel_zones(V3, F, fz, None, BASIS, return_info=True)
    ok(info3['sym_score'] < 0.8 and (out3[side == 'right'] == -1).all(), f'форма несимметрична (score {info3["sym_score"]}) — невидимый бок unknown')
    # панель с видимой частью: метки внутри панели не перетекают на другую панель
    fz4 = np.full(len(F), -1, np.int32)
    k = np.flatnonzero(side == 'front')[:3]
    fz4[k] = 0
    out4 = RZ.panel_zones(V, F, fz4, None, BASIS)
    ok((out4[side == 'front'] == 0).all() and (out4[side == 'top'] == -1).all(), 'метки лица закрывают лицо целиком (одна панель) и не уходят через излом 90° на крышку')


def test_apply_to_fill():
    print('хук 07: different лишает невидимые тексели фактуры; фото-тексели, зеркало и trellis_relief не обходят:')
    sys.path[:0] = [os.path.join(HERE, '..'), os.path.join(HERE, '..', '..')]
    T = 64
    rng = np.random.default_rng(1)
    V = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]], float)
    geom = {'V': V, 'F': np.array([[0, 1, 2], [0, 2, 3]]), 'UV': np.array([[0, 1], [1, 1], [1, 0], [0, 0]], float), 'tex': np.zeros((T, T, 3), np.uint8)}
    base = np.full((T, T, 3), 120.0)
    noisy = np.clip(base + rng.normal(0, 25, (T, T, 3)), 0, 255).astype(np.uint8)       # «после заливки»: шум на невидимой половине (зеркало/relief/узор)
    known = np.zeros((T, T), bool)
    known[:, : T // 2] = True
    fz, fs = np.array([0, 0]), np.array([0, 0])
    amap = {0: {'back': {'texture': 'different'}}}
    out, rep = RZ.apply_to_fill([geom], [noisy], [known], fz, fs, amap, [0])
    o = out[0].astype(float)
    unk = ~known
    ok((out[0][known] == noisy[known]).all(), 'фото-тексели (known) не изменились')
    ok(o[unk].std() < 0.35 * noisy.astype(float)[unk].std(), f'шум невидимой стороны подавлен ({noisy.astype(float)[unk].std():.1f} → {o[unk].std():.1f}): zerkalo/relief-тексели тоже не known — не обходят different')
    amap2 = {0: {'back': {'texture': 'same'}}}
    out2, _ = RZ.apply_to_fill([geom], [noisy], [known], fz, fs, amap2, [0])
    ok((out2[0] == noisy).all(), 'texture = same — заливка не тронута')
    out3, _ = RZ.apply_to_fill([geom], [noisy], [known], fz, np.array([1, 1]), amap, [0])
    ok((out3[0] == noisy).all(), 'different для другой стороны (back) не трогает правый бок')
    import tex_fill as TF
    ok(not RZ.APPLY, 'по умолчанию флаг apply_to_fill выключен (rules/ref-zone.json)')
    out4, rep4 = TF.apply_ref_zone_map([geom], [noisy], [known], {'ref_zone_map': {'face_zone': fz, 'face_side': fs, 'map': amap, 'offs': [0]}})
    ok((out4[0] == noisy).all() and rep4['applied'] is False, 'хук в tex_fill при выключенном флаге — ничего не меняет')
    out5, rep5 = TF.apply_ref_zone_map([geom], [noisy], [known], {'ref_zone_map': {'face_zone': fz, 'face_side': fs, 'map': amap, 'offs': [0]}}, force=True)
    ok(rep5['applied'] and rep5['texels_detextured'] > 0 and out5[0].astype(float)[unk].std() < 0.35 * noisy.astype(float)[unk].std(), 'хук в tex_fill с включённым флагом — применяет карту')


def test_relief_source():
    print('источник запасной фактуры: UltraTex (тот же меш), TRELLIS — иначе:')
    sys.path[:0] = [os.path.join(HERE, '..'), os.path.join(HERE, '..', '..')]
    import tempfile

    import tex_fill as TF
    V, F = strip(3, False)
    g = {'V': V, 'F': F, 'UV': np.random.default_rng(0).random((len(V), 2)), 'tex': np.zeros((8, 8, 3), np.uint8)}
    orig = TF.TC.load_geoms
    try:
        with tempfile.NamedTemporaryFile(suffix='.glb') as ut, tempfile.NamedTemporaryFile(suffix='.glb') as dr:
            TF.TC.load_geoms = lambda path: [dict(g)]
            ok(TF.pick_relief_draft([g], dr.name, ut.name, 'ultratex')[:2] == (ut.name, 'ultratex'), 'тот же меш → UltraTex')
            ok(TF.pick_relief_draft([g], dr.name, None, 'ultratex')[:2] == (dr.name, 'trellis'), 'UltraTex нет → TRELLIS')
            ok(TF.pick_relief_draft([g], None, None, 'ultratex')[1] is None, 'нет ни того, ни другого → источника нет (7 этап сам откажется)')
            ok(TF.pick_relief_draft([g], dr.name, ut.name, 'trellis')[:2] == (dr.name, 'trellis'), 'правило texture_source=trellis → TRELLIS')
            g2 = dict(g, UV=g['UV'] + 0.01)
            TF.TC.load_geoms = lambda path: [g2]
            ok(TF.pick_relief_draft([g], dr.name, ut.name, 'ultratex')[:2] == (dr.name, 'trellis'), 'другой меш (UV) → TRELLIS')
    finally:
        TF.TC.load_geoms = orig
    ok(TF.RULES['trellis_relief']['texture_source'] == 'ultratex', 'по умолчанию в rules/paint-fill.json — ultratex')


def test_ultratex_full():
    print('«суть целиком»: невидимое = наш тон + средние/высокие частоты UltraTex, фото не трогаем, мерка риска:')
    sys.path[:0] = [os.path.join(HERE, '..'), os.path.join(HERE, '..', '..')]
    T = 64
    rng = np.random.default_rng(2)
    V = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]], float)
    base_g = {'V': V, 'F': np.array([[0, 1, 2], [0, 2, 3]]), 'UV': np.array([[0, 1], [1, 1], [1, 0], [0, 0]], float)}
    ramp = np.tile(np.linspace(60, 200, T)[None, :], (T, 1))                                   # относительная яркость перёд↔зад: плавный градиент — уходит в низкий пас
    ut = np.clip(np.repeat((ramp + rng.normal(0, 14, (T, T)))[..., None], 3, 2), 0, 255).astype(np.uint8)
    flat = np.full((T, T, 3), 120, np.uint8)
    known = np.zeros((T, T), bool)
    known[:, : T // 2] = True
    out, rep = RZ.ultratex_full([dict(base_g, tex=flat)], [flat], [known], [dict(base_g, tex=ut)], [np.zeros(2, np.int32)])
    o = out[0].astype(float).mean(2)
    ok((out[0][known] == flat[known]).all(), 'фото-тексели не изменились')
    ok(o[~known].std() > 4.0, f'невидимое получило рисунок UltraTex (σ {o[~known].std():.1f})')
    ok(abs(o[~known].mean() - 120) < 8, f'средний тон остался нашим ({o[~known].mean():.0f}), градиент яркости перёд↔зад не перенесён')
    ok(rep['risky_parts'] == [0] and rep['parts'][0]['ratio'] > 2.0, f'на видимой стороне фото гладкое, UltraTex рябит — риск отмечен (ratio {rep["parts"][0]["ratio"]})')
    ut_box = ut.copy()
    ut_box[20:44, 36:60] = 250                                                              # «ручка/шов ДВП»: яркий прямоугольник с резкими краями на невидимой стороне
    _o, rep_b = RZ.ultratex_full([dict(base_g, tex=flat)], [flat], [known], [dict(base_g, tex=ut_box)], [np.zeros(2, np.int32)])
    ok(not rep['sharp_parts'][0]['sharp'] and rep_b['sharp_parts'][0]['edge_share'] > rep['sharp_parts'][0]['edge_share'], f'мерка резких линий: шум не считается, прямоугольник даёт рост доли ({rep["sharp_parts"][0]["edge_share"]} → {rep_b["sharp_parts"][0]["edge_share"]})')
    ph = np.clip(flat.astype(float) + rng.normal(0, 14, flat.shape), 0, 255).astype(np.uint8)
    out2, rep2 = RZ.ultratex_full([dict(base_g, tex=ph)], [ph], [known], [dict(base_g, tex=ut)], [np.zeros(2, np.int32)])
    ok(rep2['risky_parts'] == [] and rep2['parts'][0]['ratio'] < 2.0, f'на фото та же рябь — риска нет (ratio {rep2["parts"][0]["ratio"]})')


def box_uv_geom(T: int = 192):
    """Коробка `box()` с UV: у каждой из 6 сторон свой тайл сетки 3×2. → геометрия, сторона граней, маски тайлов."""
    V, F, side = box()
    names = ['front', 'back', 'right', 'left', 'top', 'bottom']
    axis_of = {'front': 2, 'back': 2, 'right': 0, 'left': 0, 'top': 1, 'bottom': 1}
    UV = np.zeros((len(V), 2))
    lo, hi = V.min(0), V.max(0)
    for fi, f in enumerate(F):
        ti = names.index(side[fi])
        cx, cy = ti % 3, ti // 3
        ax = [a for a in range(3) if a != axis_of[side[fi]]]
        for vi in f:
            u = (V[vi, ax[0]] - lo[ax[0]]) / (hi[ax[0]] - lo[ax[0]])
            v = (V[vi, ax[1]] - lo[ax[1]]) / (hi[ax[1]] - lo[ax[1]])
            UV[vi] = [(cx + 0.05 + 0.9 * u) / 3.0, 1.0 - (cy + 0.05 + 0.9 * (1.0 - v)) / 2.0]
    masks = {}
    for ti, n in enumerate(names):
        m = np.zeros((T, T), bool)
        cx, cy = ti % 3, ti // 3
        m[cy * T // 2 + 6:(cy + 1) * T // 2 - 6, cx * T // 3 + 6:(cx + 1) * T // 3 - 6] = True
        masks[n] = m
    return {'V': V, 'F': F, 'UV': UV}, side, masks


def test_own_panel_tone():
    print('невидимые панели: донор по оттенку И фактуре UltraTex (L не сравнивается) — тон и куски фото донора; нет донора — своя зона + суть UltraTex:')
    sys.path[:0] = [os.path.join(HERE, '..'), os.path.join(HERE, '..', '..')]
    import cv2
    T = 192
    g, side, mk = box_uv_geom(T)
    rng = np.random.default_rng(7)

    def tile(l, a, b, sd):
        lab = np.stack([np.clip(l + rng.normal(0, sd, (T, T)), 0, 100), np.full((T, T), a), np.full((T, T), b)], -1).astype(np.float32)
        return np.clip(cv2.cvtColor(lab, cv2.COLOR_Lab2RGB) * 255 + 0.5, 0, 255).astype(np.uint8)

    photo = tile(50, 0, 0, 0)
    noisy = tile(50, 0, 0, 10)                                       # чужая фактура от заливки на невидимом
    wood = tile(55, 14, 30, 6)
    photo[mk['front']] = wood[mk['front']]
    for n in ('back', 'right', 'left', 'top', 'bottom'):
        photo[mk[n]] = noisy[mk[n]]
    ut = tile(50, 0, 0, 0)
    ut[mk['front']] = tile(60, 14, 30, 6)[mk['front']]                # перёд: дерево с зерном
    ut[mk['right']] = tile(35, 15, 28, 6)[mk['right']]                # правый: тот же оттенок и зерно, но темнее (свет UltraTex) — донор
    ut[mk['left']] = tile(60, 15, 28, 0)[mk['left']]                  # левый: оттенок тот же, гладкий — фактура не совпала
    ut[mk['back']] = tile(50, -10, -35, 0)[mk['back']]                # зад: синий — оттенка нет
    known = [mk['front']]
    out, rep = RZ.own_panel_tone([dict(g, tex=photo)], [photo], known, [dict(g, tex=ut)], None)
    o = out[0]
    lab_o = cv2.cvtColor(o.astype(np.float32) / 255.0, cv2.COLOR_RGB2Lab)
    lw = cv2.cvtColor(wood.astype(np.float32) / 255.0, cv2.COLOR_RGB2Lab)[mk['front']].mean(0)
    ok((o[mk['front']] == photo[mk['front']]).all(), 'фото-тексели (фасад) не изменились')
    r = lab_o[mk['right']]
    rm = r.reshape(-1, 3).mean(0)
    ok(np.abs(rm[1:] - lw[1:]).max() < 4.0 and abs(rm[0] - 50.0) < 2.5 and 3.0 < r[..., 0].std() < 9.0,
       f'правый (оттенок и фактура совпали) = оттенок и зерно фасада с фото, светлота НАША (ADR-0464): L {rm[0]:.0f} (своя 50, у фасада {lw[0]:.0f}); a,b {rm[1]:.0f},{rm[2]:.0f} (фасад {lw[1]:.0f},{lw[2]:.0f}); σ L {r[..., 0].std():.1f}')
    lf = lab_o[mk['left']]
    ok(abs(lf[..., 0].mean() - 50) < 3 and lf[..., 0].std() < 2.0 and abs(lf[..., 1].mean()) < 3, f'левый (оттенок совпал, фактура нет) — тон своей зоны (серый), дерево не берёт и шум заливки снят (σ L {lf[..., 0].std():.1f})')
    bk = lab_o[mk['back']]
    ok(abs(bk[..., 0].mean() - 50) < 3 and bk[..., 0].std() < 2.0 and abs(bk[..., 1].mean()) < 3 and abs(bk[..., 2].mean()) < 3, 'зад (оттенка нет) — тон своей зоны без шума и без фактуры фасада')
    pr = rep['panels']
    don = [v for v in pr.values() if v['tone_from'] == 'donor']
    own_hue = [v for v in pr.values() if v.get('hue_only_panel') is not None]
    ok(len(don) == 1 and don[0]['hue_dE_ab'] < 4.0 and don[0]['texture'] == 'куски донора (квилт)', f'в отчёте один донор (панелей с донором {len(don)}), с ΔE_ab {don[0]["hue_dE_ab"] if don else None}')
    ok(len(own_hue) == 1 and own_hue[0]['why'] == 'оттенок совпал, фактура нет', 'в отчёте левый: оттенок совпал, фактура нет')
    out2, rep2 = RZ.own_panel_tone([dict(g, tex=photo)], [photo], known, None, None)
    ok(rep2['with_donor'] == 0 and all(v['tone_from'] == 'own' and v['why'] == 'нет UltraTex' for v in rep2['panels'].values()), 'нет UltraTex — у всех тон своей зоны')
    ut_rough = ut.copy()
    ut_rough[mk['back']] = tile(50, -10, -35, 8)[mk['back']]
    out4, rep4 = RZ.own_panel_tone([dict(g, tex=photo)], [photo], known, [dict(g, tex=ut_rough)], None)
    ok(cv2.cvtColor(out4[0].astype(np.float32) / 255.0, cv2.COLOR_RGB2Lab)[..., 0][mk['back']].std() > 4.0, 'нет донора, но у UltraTex на заду есть зерно — суть UltraTex на месте (ΔL)')


def test_align_ut():
    print('UltraTex в позу фото: поворот вокруг вертикали по совпадению детали с фото; симметричный/без детали — не используется:')
    sys.path[:0] = [os.path.join(HERE, '..'), os.path.join(HERE, '..', '..')]
    import cv2
    T = 192
    g, side, mk = box_uv_geom(T)
    rng = np.random.default_rng(11)
    cw, ch = T // 3, T // 2
    stripes = np.full((ch, cw), 110.0)
    stripes[:, ::8] = 190.0
    stripes[::16, :] = 60.0                                          # «двери и швы»: вертикальные полосы и горизонтальные линии
    stripes[10:30, 4:20] = 220.0                                     # «ручка» слева сверху: тайл не зеркально-симметричен
    base = np.stack([np.clip(stripes + rng.normal(0, 2, stripes.shape), 0, 255)] * 3, -1).astype(np.uint8)
    photo = np.full((T, T, 3), 90, np.uint8)
    photo[0:ch, 0:cw] = base                                         # перёд (тайл 0,0)
    known = [mk['front']]
    ut_same = np.full((T, T, 3), 100, np.uint8)
    ut_same[0:ch, 0:cw] = base                                       # UltraTex: перёд там же, где фото
    ut_rot = np.full((T, T, 3), 100, np.uint8)
    ut_rot[0:ch, cw:2 * cw] = base[:, ::-1]                          # UltraTex повернут на 180°: «перёд» лежит на задней стороне (u зеркален)
    al0, r0 = RZ.align_ut([dict(g, tex=photo)], [photo], known, [dict(g, tex=ut_same)])
    ok(r0['status'] == 'identity' and r0['yaw_deg'] == 0, f'UltraTex уже в позе фото → поворот 0 ({r0["status"]}, корреляции {r0["corr"]})')
    al1, r1 = RZ.align_ut([dict(g, tex=photo)], [photo], known, [dict(g, tex=ut_rot)])
    ok(r1['status'] == 'aligned' and r1['yaw_deg'] == 180, f'UltraTex повернут на 180° → найден поворот 180 ({r1["status"]}, {r1["yaw_deg"]}, корреляции {r1["corr"]})')
    if al1:
        fr = al1[0]['tex'][mk['front']].astype(float).mean(1)
        ok(np.corrcoef(fr.ravel(), photo[mk['front']].astype(float).mean(1).ravel())[0, 1] > 0.8, 'после поворота UltraTex на лице совпадает с фото')
    flat_ut = np.full((T, T, 3), 100, np.uint8)
    al2, r2 = RZ.align_ut([dict(g, tex=photo)], [photo], known, [dict(g, tex=flat_ut)])
    ok(al2 is None and r2['status'] == 'uncertain', f'у UltraTex нет детали — не уверены, UltraTex не используется ({r2["status"]})')
    ok(RZ.align_ut([dict(g, tex=photo)], [photo], known, None)[0] is None, 'нет UltraTex — None')


def test_own_panel_clean_detail():
    print('«суть UltraTex»: край панели, блики и выбросы режутся (кляксы на заду):')
    sys.path[:0] = [os.path.join(HERE, '..'), os.path.join(HERE, '..', '..')]
    import cv2
    T = 192
    g, side, mk = box_uv_geom(T)
    rng = np.random.default_rng(5)
    lab = np.stack([50 + rng.normal(0, 3, (T, T)), np.full((T, T), 1.0), np.full((T, T), 2.0)], -1).astype(np.float32)
    ut_img = np.clip(cv2.cvtColor(lab, cv2.COLOR_Lab2RGB) * 255 + 0.5, 0, 255).astype(np.uint8)
    blue = np.clip(cv2.cvtColor(np.array([[[50.0, -10.0, -35.0]]], np.float32), cv2.COLOR_Lab2RGB)[0, 0] * 255 + 0.5, 0, 255).astype(np.uint8)
    ut_img[mk['front']] = blue                                                               # у UltraTex перёд другого оттенка → донора нет, на заду «суть» UltraTex
    bk = mk['back']
    ys, xs = np.nonzero(bk)
    ut_bl = ut_img.copy()
    ut_bl[ys.min() + 30:ys.min() + 45, xs.min() + 20:xs.min() + 40] = 8                      # тёмная клякса (шов/ручка ДВП)
    photo = np.full((T, T, 3), 90, np.uint8)
    wood = np.clip(cv2.cvtColor(np.stack([np.full((T, T), 55.0), np.full((T, T), 14.0), np.full((T, T), 30.0)], -1).astype(np.float32), cv2.COLOR_Lab2RGB) * 255 + 0.5, 0, 255).astype(np.uint8)
    photo[mk['front']] = wood[mk['front']]
    out_a, _ = RZ.own_panel_tone([dict(g, tex=photo)], [photo], [mk['front']], [dict(g, tex=ut_img)], None)
    out_b, _ = RZ.own_panel_tone([dict(g, tex=photo)], [photo], [mk['front']], [dict(g, tex=ut_bl)], None)
    La = cv2.cvtColor(out_a[0].astype(np.float32) / 255.0, cv2.COLOR_RGB2Lab)[..., 0][bk]
    Lb = cv2.cvtColor(out_b[0].astype(np.float32) / 255.0, cv2.COLOR_RGB2Lab)[..., 0][bk]
    ok(Lb.min() > La.min() - 12, f'тёмная клякса UltraTex не переносится в полную силу (мин L {Lb.min():.0f}, без кляксы {La.min():.0f}, клякса была L≈8)')


def test_own_panel_smooth_no_quilt():
    print('две гладкие панели по UltraTex не дают куски фасада (22.11, ТВ-тумба): тон донора плоско, без зерна фото:')
    sys.path[:0] = [os.path.join(HERE, '..'), os.path.join(HERE, '..', '..')]
    import cv2
    T = 192
    g, side, mk = box_uv_geom(T)
    rng = np.random.default_rng(9)

    def tile(l, a, b, sd):
        lab = np.stack([np.clip(l + rng.normal(0, sd, (T, T)), 0, 100), np.full((T, T), a), np.full((T, T), b)], -1).astype(np.float32)
        return np.clip(cv2.cvtColor(lab, cv2.COLOR_Lab2RGB) * 255 + 0.5, 0, 255).astype(np.uint8)

    photo = tile(50, 0, 0, 0)
    groove = tile(55, 14, 30, 8)                                      # на фото перёд с бороздками
    photo[mk['front']] = groove[mk['front']]
    ut = tile(50, 0, 0, 0)
    ut[mk['front']] = tile(60, 14, 30, 0)[mk['front']]                # у UltraTex перёд гладкий (бороздок не видно)
    ut[mk['right']] = tile(35, 15, 28, 0)[mk['right']]                # правый: тот же оттенок, тоже гладкий
    out, rep = RZ.own_panel_tone([dict(g, tex=photo)], [photo], [mk['front']], [dict(g, tex=ut)], None)
    lab_o = cv2.cvtColor(out[0].astype(np.float32) / 255.0, cv2.COLOR_RGB2Lab)
    r = lab_o[mk['right']]
    ok(r[..., 0].std() < 2.0, f'правый — плоский тон донора без бороздок фасада (σ L {r[..., 0].std():.1f}, у фото фасада 8)')
    txt = [x.get('texture') for x in rep['panels'].values() if x.get('tone_from') == 'donor']
    ok(txt and all('квилт' not in str(x) for x in txt), f'в отчёте нет квилта: {txt}')


def test_own_panel_keeps_our_L():
    print('донор плоско: светлота L НАША (медиана своей заливки панели), от донора только оттенок a,b; ровное при фактурном фото донора видно в отчёте (flat_share_pct, р.7 23.11):')
    sys.path[:0] = [os.path.join(HERE, '..'), os.path.join(HERE, '..', '..')]
    import cv2
    T = 192
    g, side, mk = box_uv_geom(T)
    rng = np.random.default_rng(21)

    def tile(l, a, b, sd):
        lab = np.stack([np.clip(l + rng.normal(0, sd, (T, T)), 0, 100), np.full((T, T), a), np.full((T, T), b)], -1).astype(np.float32)
        return np.clip(cv2.cvtColor(lab, cv2.COLOR_Lab2RGB) * 255 + 0.5, 0, 255).astype(np.uint8)

    photo = tile(65, 3, 6, 0)
    photo[mk['front']] = tile(74, 14, 30, 6)[mk['front']]            # донор: светлый, с зерном
    ut = tile(50, 0, 0, 0)
    ut[mk['front']] = tile(60, 14, 30, 0)[mk['front']]               # у UltraTex оба гладкие → плоский тон
    ut[mk['right']] = tile(40, 15, 28, 0)[mk['right']]
    out, rep = RZ.own_panel_tone([dict(g, tex=photo)], [photo], [mk['front']], [dict(g, tex=ut)], None)
    lab_o = cv2.cvtColor(out[0].astype(np.float32) / 255.0, cv2.COLOR_RGB2Lab)
    r = lab_o[mk['right']]
    ok(abs(r[..., 0].mean() - 65.0) < 2.0, f'L панели — своя 65, не донора 74: {r[..., 0].mean():.1f}')
    ok(abs(r[..., 1].mean() - 14.0) < 3.0 and abs(r[..., 2].mean() - 30.0) < 3.0, f'оттенок a,b — донора: {r[..., 1].mean():.1f},{r[..., 2].mean():.1f}')
    pr = [v for v in rep['panels'].values() if v.get('tone_from') == 'donor']
    ok(pr and pr[0].get('L_policy') == 'наша' and pr[0].get('photo_sigma_L', 0) >= 2.0, f'в отчёте L_policy и σ L фото донора: {pr[0].get("L_policy") if pr else None} / {pr[0].get("photo_sigma_L") if pr else None}')
    ok(rep['flat_share_pct'] > 0.0, f'ровное при фактурном фото донора учтено: flat_share_pct {rep["flat_share_pct"]}')


def test_own_panel_neutral_donor_needs_L():
    print('нейтральные цвета: чёрное не берёт донором светло-бежевое, хотя a,b почти равны (Б, 23.11):')
    sys.path[:0] = [os.path.join(HERE, '..'), os.path.join(HERE, '..', '..')]
    import cv2
    T = 192
    g, side, mk = box_uv_geom(T)
    rng = np.random.default_rng(31)

    def tile(l, a, b, sd):
        lab = np.stack([np.clip(l + rng.normal(0, sd, (T, T)), 0, 100), np.full((T, T), a), np.full((T, T), b)], -1).astype(np.float32)
        return np.clip(cv2.cvtColor(lab, cv2.COLOR_Lab2RGB) * 255 + 0.5, 0, 255).astype(np.uint8)

    photo = tile(65, 2, 6, 0)
    photo[mk['front']] = tile(72, 2, 6, 5)[mk['front']]                  # беж с зерном на фото
    ut = tile(50, 0, 0, 0)
    ut[mk['front']] = tile(70, 2, 6, 5)[mk['front']]                      # UltraTex: беж, светло
    ut[mk['right']] = tile(12, 1, 3, 5)[mk['right']]                      # правый: чёрный, a,b почти те же (ΔE_ab ~3)
    out, rep = RZ.own_panel_tone([dict(g, tex=photo)], [photo], [mk['front']], [dict(g, tex=ut)], None)
    pr = [v for v in rep['panels'].values() if v.get('tone_from') == 'donor']
    ok(len(pr) == 0, f'чёрный правый не получил светлого донора (панелей с донором {len(pr)})')
    ut2 = ut.copy()
    ut2[mk['right']] = tile(62, 1, 5, 5)[mk['right']]                     # светлота близкая → донор допустим
    out2, rep2 = RZ.own_panel_tone([dict(g, tex=photo)], [photo], [mk['front']], [dict(g, tex=ut2)], None)
    pr2 = [v for v in rep2['panels'].values() if v.get('tone_from') == 'donor']
    ok(len(pr2) == 1, f'при близкой светлоте донор допустим (панелей с донором {len(pr2)})')


def test_sub_tone():
    print('подчасть по цвету 06 (Б, 23.11): тёмная нейтральная невидимая панель против светлой доминанты — остаётся тёмной; светлая/цветная и известные тексели — нет:')
    sys.path[:0] = [os.path.join(HERE, '..'), os.path.join(HERE, '..', '..')]
    import cv2
    T = 192
    g, side, mk = box_uv_geom(T)

    def solid(l, a, b):
        lab = np.full((T, T, 3), (l, a, b), np.float32)
        return np.clip(cv2.cvtColor(lab, cv2.COLOR_Lab2RGB) * 255 + 0.5, 0, 255).astype(np.uint8)

    before = solid(70, 2, 8)
    before[mk['back']] = solid(12, 0, 0)[mk['back']]                      # в 06 зад (панель) тёмный нейтральный — как ножки
    before[mk['top']] = solid(45, 30, 20)[mk['top']]                      # цветная панель (красная): не «тёмное нейтральное» — не трогаем
    after = solid(70, 2, 8)                                               # 07 покрасил всю часть одним беж-тоном
    known = np.zeros((T, T), bool)
    known[mk['front']] = True
    parts = np.zeros(len(g['F']), np.int32)
    side = np.asarray(side)
    parts[side == 'right'] = 1
    old = RZ.R.get('sub_tone')
    RZ.R['sub_tone'] = {'area_max': 0.3, 'min_texels': 100}
    try:
        out, rep = RZ.sub_tone([g], [before], [after], [known], [parts])
    finally:
        if old is None:
            RZ.R.pop('sub_tone', None)
        else:
            RZ.R['sub_tone'] = old
    lab = cv2.cvtColor(out[0].astype(np.float32) / 255.0, cv2.COLOR_RGB2Lab)
    ok(float(np.median(lab[mk['back']][:, 0])) < 25, f'зад (тёмный в 06) остался тёмным: L {np.median(lab[mk["back"]][:, 0]):.1f}; отчёт {rep["parts"]}')
    ok(abs(float(np.median(lab[mk['left']][:, 0])) - 70) < 3, f'левый (обычный) не тронут: L {np.median(lab[mk["left"]][:, 0]):.1f}')
    ok(abs(float(np.median(lab[mk['top']][:, 0])) - 70) < 3, f'цветная панель не «подчасть» (тёмное нейтральное — только): L {np.median(lab[mk["top"]][:, 0]):.1f}')
    ok(bool((out[0][known] == after[known]).all()), 'известные (фото) тексели не изменились')
    ok(rep['texels_changed'] > 0 and 0 < rep['subtone_share_pct'] < 50, f'в отчёте доля подчасти: {rep["subtone_share_pct"]} %')


def test_align_tied():
    print('коробка с двумя равными поворотами (UltraTex одинаков на лице и на заду): ничья → tied с ties, yaw задан — перенос без оценки:')
    sys.path[:0] = [os.path.join(HERE, '..'), os.path.join(HERE, '..', '..')]
    T = 192
    g, side, mk = box_uv_geom(T)
    rng = np.random.default_rng(13)
    cw, ch = T // 3, T // 2
    stripes = np.full((ch, cw), 110.0)
    stripes[:] = 110.0 + rng.normal(0, 25, stripes.shape)                                   # зерно с ровной энергией: повороты 0 и 180 неразличимы
    base = np.stack([np.clip(stripes + rng.normal(0, 2, stripes.shape), 0, 255)] * 3, -1).astype(np.uint8)
    full = np.tile(base, (T // ch + 1, T // cw + 1, 1))[:T, :T]
    photo = np.full((T, T, 3), 90, np.uint8)
    photo[mk['front']] = full[mk['front']]
    ut = np.full((T, T, 3), 100, np.uint8)
    for n in ("front", "back"):
        ut[mk[n]] = np.clip(110.0 + rng.normal(0, 25, (T, T, 1)) + np.zeros((T, T, 3)), 0, 255).astype(np.uint8)[mk[n]]
    al, r = RZ.align_ut([dict(g, tex=photo)], [photo], [mk['front']], [dict(g, tex=ut)])
    ok(r['status'] == 'tied' and sorted(r.get("ties", [])) == [0, 180], f'ничья между 0 и 180 → tied {r.get("ties")} (оценки {r["corr"]})')
    ok(al is None, 'при ничьей геометрий нет (выбор — у вызывающего)')
    al2, r2 = RZ.align_ut([dict(g, tex=photo)], [photo], [mk['front']], [dict(g, tex=ut)], yaw=180)
    ok(al2 is not None and r2['status'] == 'forced' and r2["yaw_deg"] == 180, 'yaw=180 задан — UltraTex перенесён без оценки')


def main():
    for f in (test_sub_tone, test_own_panel_neutral_donor_needs_L, test_own_panel_keeps_our_L, test_align_tied, test_own_panel_smooth_no_quilt, test_align_ut, test_own_panel_clean_detail, test_own_panel_tone, test_same_mesh, test_decide, test_gate_per_property, test_propagate, test_object_basis, test_inconsistent_winding, test_outer_only, test_panel_with_bottom, test_panels, test_apply_to_fill, test_relief_source, test_ultratex_full):
        f()
    print(f'tests_ref_zone: ошибок {len(FAILS)}')
    return 1 if FAILS else 0


if __name__ == '__main__':
    raise SystemExit(main())
