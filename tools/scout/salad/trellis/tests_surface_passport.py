#!/usr/bin/env python3
"""Тесты паспорта поверхностей `surface_passport.py` (T-20261123-09/1, m4 «один материал — один тон», П1.147): синтетика на квадратах, без видеокарты и сети; нужны numpy, scipy.
Проверяется: плоскость, разрезанная двумя частями 03 → один тон на невидимом; контрастная дверца → своя группа (не слита); серый рисунок → класс «узор», не выравнивается;
известное не меняется; «фасад на зад не идёт» (зад берёт тон корпуса); выключатель UltraTex false → ut.glb не нужен и не читается; зерно группы без тёмных швов.

  python3 tools/scout/salad/trellis/tests_surface_passport.py
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.normpath(os.path.join(HERE, '..', '..')))
import remlab_tmp  # noqa: E402
remlab_tmp.use('tests_surface_passport')
import numpy as np  # noqa: E402
import tex_coverage as TC  # noqa: E402
import tex_fill as TF  # noqa: E402
import surface_passport as SP  # noqa: E402

bad = 0
T = 256


def ok(cond, name, extra=''):
    global bad
    print(('  ✓ ' if cond else '  ✗ ') + name + (f' — {extra}' if extra and not cond else ''))
    bad += 0 if cond else 1


class Quads:
    """Одна геометрия из четырёхугольников; у каждого своя плитка развёртки (u0, v0, u1, v1); часть задаётся по четырёхугольнику (sub клеток по стороне — части режут плоскость по клеткам)."""

    def __init__(self):
        self.V, self.F, self.UV, self.part = [], [], [], []

    def quad(self, corners, tile, part=0, sub=1, part_of=None):
        n0 = len(self.V)
        u0, v0, u1, v1 = tile
        c = np.array(corners, float)
        uv = np.array([[u0, v0], [u1, v0], [u1, v1], [u0, v1]], float)
        for j in range(sub + 1):
            for i in range(sub + 1):
                s_, t_ = i / sub, j / sub
                w = np.array([(1 - s_) * (1 - t_), s_ * (1 - t_), s_ * t_, (1 - s_) * t_])
                self.V.append(list(w @ c))
                self.UV.append(list(w @ uv))
        for j in range(sub):
            for i in range(sub):
                a_ = n0 + j * (sub + 1) + i
                b_, c_, d_ = a_ + 1, a_ + sub + 2, a_ + sub + 1
                self.F += [[a_, b_, c_], [a_, c_, d_]]
                p = part_of(i, j) if part_of else part
                self.part += [p, p]
        return n0

    def geom(self, tex):
        return {'name': 'q', 'V': np.array(self.V, float), 'F': np.array(self.F, np.int64), 'UV': np.array(self.UV, float), 'tex': tex}


def tile_mask(tile):
    m = np.zeros((T, T), bool)
    u0, v0, u1, v1 = tile
    m[int((1 - v1) * T):int((1 - v0) * T), int(u0 * T):int(u1 * T)] = True
    return m


def lab_L(tex, mask):
    return TF.rgb2lab(tex[mask].reshape(-1, 3))[:, 0]


def lab_rgb(L, a=0.0, b=0.0):
    return TF.lab2rgb(np.array([[L, a, b]], float))[0]


def de(a, b):
    a, b = np.atleast_2d(np.asarray(a, float)), np.atleast_2d(np.asarray(b, float))
    return float(TC.de2000_v(a, np.broadcast_to(b, a.shape)).mean())


def grain(shape, sigma, seed):
    from scipy.ndimage import gaussian_filter
    n = gaussian_filter(np.random.RandomState(seed).randn(*shape), 1.2)
    return n / max(float(n.std()), 1e-9) * sigma


def scene_plane_two_parts(part_split=True):
    """Большая плоскость лицом +Z (сетка 8×8; левая половина — часть 0, правая — часть 1). Известное — полоса слева в каждой половине: оба тона одной краски (ΔE ≈ 1) с зерном.
    Невидимое каждой части залито «как p5»: часть 0 светлее, часть 1 темнее (рваный стык частей). → (geom, tex, known, parts, tone_known)."""
    q = Quads()
    q.quad([[-1, 0, 0], [1, 0, 0], [1, 1, 0], [-1, 1, 0]], (0, 0, 1, 1), sub=8, part_of=(lambda i, j: 0 if i < 4 else 1) if part_split else None)
    base = lab_rgb(62.0, -2.0, 4.0)
    tex = np.zeros((T, T, 3), np.uint8)
    L = 62.0 + grain((T, T), 1.6, 1)
    lab = np.stack([L, np.full((T, T), -2.0), np.full((T, T), 4.0)], -1)
    full = TF.lab2rgb(lab.reshape(-1, 3)).reshape(T, T, 3)
    tex[:] = full
    xs = np.arange(T)[None, :].repeat(T, 0)
    known = (xs < 56) | ((xs >= 128) & (xs < 184))                                                  # полосы слева в обеих половинах
    left_unk = (~known) & (xs < 128)
    right_unk = (~known) & (xs >= 128)
    tex[left_unk] = lab_rgb(72.0, -2.0, 4.0)                                                         # часть 0: заливка светлее на 10
    tex[right_unk] = lab_rgb(54.0, -2.0, 4.0)                                                        # часть 1: темнее на 8
    g = q.geom(tex)
    parts = [np.array(q.part, np.int32)]
    return g, tex, known, parts, base


def run(g, tex, known, parts, roles=None, hook_keep=None, product_role=None, card_role='шкаф'):
    R = dict(TF.RULES['surface_groups'], _card_role=card_role)                      # роль товара: по умолчанию корпусной тип (paint.hidden_pattern = body); body_override действует только у него
    pas, ctx = SP.build([g], [tex], [known], parts, roles, R, TF.FILL, TF)
    if hook_keep is not None:
        ctx['hook_keep'] = hook_keep
    if product_role is not None:
        ctx['paint_policy'] = TF.paint_policy_for({'top_card': {'role': product_role}})          # как в 07: роль карточки → политика типа до apply
    k0 = [known & ~TF.unpainted_mask(tex)]
    out, rep = SP.apply_groups([g], [tex], k0, pas, ctx, R, TF)
    return pas, ctx, out, rep, k0


def test_split_plane_one_tone():
    print('панель, разрезанная двумя частями 03, красится одним тоном:')
    g, tex, known, parts, base = scene_plane_two_parts()
    pas, ctx, out, rep, k0 = run(g, tex, known, parts)
    gr = [x for x in pas['groups'] if x.get('applied') and 'virtual_for' not in x]
    ok(len(gr) == 1 and sorted(gr[0]['parts']) == [0, 1], f'части 0 и 1 слились в одну группу: {[(x["parts"], x["class"]) for x in pas["groups"]]}')
    ok(any(m['parts'] == [0, 1] and 'плоскость' in m['why'] for m in pas['merges']), 'причина слияния записана (одна плоскость, тона совместимы)')
    xs = np.arange(T)[None, :].repeat(T, 0)
    lu = (~known) & (xs < 128) & (xs > 70)
    ru = (~known) & (xs >= 128) & (xs > 200)
    ml = np.median(TF.rgb2lab(out[0][lu].reshape(-1, 3)), 0)
    mr = np.median(TF.rgb2lab(out[0][ru].reshape(-1, 3)), 0)
    ok(de(ml, mr) <= 3.0, f'медианы невидимого двух частей ближе 3 ΔE00 ({de(ml, mr):.2f}); до правки — 10+ ({de(TF.rgb2lab(tex[lu].reshape(-1, 3)).mean(0), TF.rgb2lab(tex[ru].reshape(-1, 3)).mean(0)):.1f})')
    kb = TF.rgb2lab(tex[known].reshape(-1, 3))
    ok(de(ml, np.median(kb, 0)) <= 3.0, 'базовый тон залитого ≈ тон видимого (≤3 ΔE00)')
    ok(np.array_equal(out[0][known], tex[known]), 'известное не изменилось (побайтно)')
    ok(pas['groups'][0].get('class') in ('тон + зерно', 'свет'), f'класс — тон+зерно/свет: {pas["groups"][0].get("class")}')


def test_contrast_door_own_group():
    print('контрастная дверца — своя группа, двухтонность не слита:')
    q = Quads()
    corners_a = [[-1, 0, 0], [0, 0, 0], [0, 1, 0], [-1, 1, 0]]
    corners_b = [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]]
    q.quad(corners_a, (0, 0, .5, 1), part=0, sub=10)
    q.quad(corners_b, (.5, 0, 1, 1), part=1, sub=10)                                                   # общее ребро x=0 — части касаются плоскостью
    tex = np.zeros((T, T, 3), np.uint8)
    xs = np.arange(T)[None, :].repeat(T, 0)
    L = 66.0 + grain((T, T), 1.5, 2)
    tex[xs < 128] = TF.lab2rgb(np.stack([L, np.full((T, T), 0.0), np.full((T, T), 3.0)], -1).reshape(-1, 3)).reshape(T, T, 3)[xs < 128]
    Ld = 28.0 + grain((T, T), 1.0, 3)
    tex[xs >= 128] = TF.lab2rgb(np.stack([Ld, np.full((T, T), 0.0), np.full((T, T), 1.0)], -1).reshape(-1, 3)).reshape(T, T, 3)[xs >= 128]
    known = ((xs < 70) | ((xs >= 128) & (xs < 200)))
    tex[(~known) & (xs < 128)] = lab_rgb(66.0, 0.0, 3.0)
    tex[(~known) & (xs >= 128)] = lab_rgb(28.0, 0.0, 1.0)
    g = q.geom(tex)
    parts = [np.array(q.part, np.int32)]
    pas, ctx, out, rep, k0 = run(g, tex, known, parts)
    grp = [x for x in pas['groups'] if x.get('applied')]
    ok(len(grp) == 2 and sorted(sorted(x['parts']) for x in grp) == [[0], [1]], f'две группы (светлая и тёмная): {[(x["parts"], x.get("tone_lab")) for x in pas["groups"]]}')
    ok(any(r['parts'] == [0, 1] and 'контраст' in r['why'] for r in pas['refusals']), 'причина отказа записана (контрастные тона — другой материал)')
    dark_unk = (~known) & (xs >= 128) & (xs > 215)
    ok(abs(float(np.median(lab_L(out[0], dark_unk))) - 28.0) < 3.0, f'тёмная дверца осталась тёмной ({np.median(lab_L(out[0], dark_unk)):.1f})')


def test_gray_pattern_not_flattened():
    print('серый узор → класс «узор», невидимое не выравнивается в один тон:')
    q = Quads()
    q.quad([[-1, 0, 0], [1, 0, 0], [1, 1, 0], [-1, 1, 0]], (0, 0, 1, 1), part=0, sub=4)
    ys, xs = np.mgrid[0:T, 0:T]
    chk = (((xs // 10) + (ys // 10)) % 2).astype(bool)                                              # шахматка 10 px: L 40 / 70
    L = np.where(chk, 70.0, 40.0) + grain((T, T), 0.5, 4)
    tex = TF.lab2rgb(np.stack([L, np.zeros((T, T)), np.zeros((T, T))], -1).reshape(-1, 3)).reshape(T, T, 3)
    known = xs < 128
    unk = ~known
    tex[unk] = tex[unk]                                                                              # невидимое: рисунок продолжен (как после заливки)
    g = q.geom(tex)
    parts = [np.array(q.part, np.int32)]
    pas, ctx, out, rep, k0 = run(g, tex, known, parts)
    cls = [x['class'] for x in pas['groups'] if x.get('applied')]
    ok(cls == ['узор'], f'класс «узор»: {cls} ({[x.get("class_why") for x in pas["groups"]]})')
    s0 = float(np.std(lab_L(tex, unk & (xs > 150))))
    s1 = float(np.std(lab_L(out[0], unk & (xs > 150))))
    ok(s1 >= 0.8 * s0, f'рисунок на невидимом не выровнен: σL {s0:.1f} → {s1:.1f}')
    ok(np.array_equal(out[0][known], tex[known]), 'известное не изменилось (побайтно)')


def test_back_is_body_not_facade():
    print('«фасад на зад не идёт»: зад берёт тон корпуса, а не фасада:')
    q = Quads()
    q.quad([[-1, 0, 1], [1, 0, 1], [1, 1, 1], [-1, 1, 1]], (0, 0, .5, 1), part=0, sub=4)               # лицо (фасад) +Z, видно
    q.quad([[-1, 0, -1], [1, 0, -1], [1, 1, -1], [-1, 1, -1]], (.5, 0, 1, .5), part=0, sub=4)          # зад: та же часть 0 (как у «Drawer»), на фото не виден
    q.quad([[-1, 1, -1], [1, 1, -1], [1, 1, 1], [-1, 1, 1]], (.5, .5, 1, 1), part=1, sub=4)            # верх — корпус (часть 1), с видимой кромкой
    tex = np.zeros((T, T, 3), np.uint8)
    face = tile_mask((0, 0, .5, 1))
    back = tile_mask((.5, 0, 1, .5))
    top = tile_mask((.5, .5, 1, 1))
    Lf = 30.0 + grain((T, T), 1.0, 5)
    Lt = 64.0 + grain((T, T), 1.5, 6)
    f_rgb = TF.lab2rgb(np.stack([Lf, np.zeros((T, T)), np.zeros((T, T))], -1).reshape(-1, 3)).reshape(T, T, 3)
    t_rgb = TF.lab2rgb(np.stack([Lt, np.full((T, T), 3.0), np.full((T, T), 18.0)], -1).reshape(-1, 3)).reshape(T, T, 3)
    tex[face] = f_rgb[face]
    tex[top] = t_rgb[top]
    tex[back] = lab_rgb(30.0, 0.0, 0.0)                                                              # заливка p5: зад графитовый, как фасад
    known = face.copy()
    ys, xs = np.mgrid[0:T, 0:T]
    known |= top & (ys < int(T * .25 + T * .0)) & (xs >= 128)                                          # кромка верха видна — тон корпуса надёжен
    known |= top & (xs >= 128) & (ys < 70)
    g = q.geom(tex)
    parts = [np.array(q.part, np.int32)]
    pas, ctx, out, rep, k0 = run(g, tex, known, parts)
    bo = pas.get('body_override', {})
    ok(any(r.get('fired') for r in bo.get('rules', [])), f'правило «зад — корпус» сработало: {bo.get("rules")}')
    Lb = float(np.median(lab_L(out[0], back & ~known)))
    ok(abs(Lb - 64.0) < 6.0, f'зад теперь тоном корпуса ({Lb:.1f}), не фасада (30)')
    Lface_unk = lab_L(out[0], face & ~known)
    ok(len(Lface_unk) == 0 or abs(float(np.median(Lface_unk)) - 30.0) < 4.0, 'фасад остался графитовым')
    ok(np.array_equal(out[0][known], tex[known]), 'известное не изменилось (побайтно)')
    # контроль: одноцветный предмет — правило молчит
    tex2 = tex.copy()
    tex2[top] = f_rgb[top]
    tex2[back] = lab_rgb(30.0, 0.0, 0.0)
    pas2, _, out2, _, _ = run(q.geom(tex2), tex2, known, parts)
    ok(not any(r.get('fired') for r in pas2['body_override']['rules']), 'одноцветный предмет (корпус того же тона) — правило не срабатывает')


def test_body_override_only_for_body_type():
    print('роль панели «корпус»: только у типа paint.hidden_pattern = body (кресло 6070: обивка не «фасад», невидимое не отдаём дереву рамы):')
    q = Quads()
    q.quad([[-1, 0, 1], [1, 0, 1], [1, 1, 1], [-1, 1, 1]], (0, 0, .5, 1), part=0, sub=4)
    q.quad([[-1, 0, -1], [1, 0, -1], [1, 1, -1], [-1, 1, -1]], (.5, 0, 1, .5), part=0, sub=4)
    q.quad([[-1, 1, -1], [1, 1, -1], [1, 1, 1], [-1, 1, 1]], (.5, .5, 1, 1), part=1, sub=4)
    tex = np.zeros((T, T, 3), np.uint8)
    face, back, top = tile_mask((0, 0, .5, 1)), tile_mask((.5, 0, 1, .5)), tile_mask((.5, .5, 1, 1))
    tex[face] = lab_rgb(30.0, 0.0, 0.0)
    tex[top] = lab_rgb(64.0, 3.0, 18.0)
    tex[back] = lab_rgb(30.0, 0.0, 0.0)
    ys, xs = np.mgrid[0:T, 0:T]
    known = face.copy() | (top & (xs >= 128) & (ys < 70))
    g = q.geom(tex)
    parts = [np.array(q.part, np.int32)]
    for role, want in (('комод', True), ('шкаф', True), ('кресло', False), ('диван', False), (None, False)):
        pas, ctx, out, rep, k0 = run(g, tex, known, parts, card_role=role)
        bo = pas.get('body_override', {})
        fired = any(r.get('fired') for r in bo.get('rules', []))
        ok(fired == want, f'роль «{role}»: body_override {"сработал" if fired else "не сработал"} (ожидали {"да" if want else "нет"}); {bo.get("skipped_by_type", "")}')


def test_back_not_tiny_contrast():
    print('«зад — корпус»: контрастная мелочь (ниша, ручка) корпусом не становится (T-28/1, шкаф с нишей: зад стал тёмно-рыжим):')
    q = Quads()
    q.quad([[-1, 0, 1], [1, 0, 1], [1, 0.5, 1], [-1, 0.5, 1]], (0, 0, .5, .5), part=0, sub=4)          # фасад (часть 0), виден целиком
    q.quad([[1, 0, 1], [1, 0, -1], [1, 1, -1], [1, 1, 1]], (0, .5, .5, 1), part=2, sub=4)              # боковина — крупный корпус (часть 2), тон близок к фасаду, виден целиком
    q.quad([[-1, 0, -1], [1, 0, -1], [1, 1, -1], [-1, 1, -1]], (.5, 0, 1, .5), part=0, sub=4)          # зад: часть 0, на фото не виден
    q.quad([[-1, 1, -1], [1, 1, -1], [1, 1, 1], [-1, 1, 1]], (.5, .5, .5 + 56 / T, .5 + 56 / T), part=1, sub=4)            # «ниша» (часть 1): контрастный тон, мелкая (≈6 % площади; порог теста 10 %), видна целиком
    tex = np.zeros((T, T, 3), np.uint8)
    face, side = tile_mask((0, 0, .5, .5)), tile_mask((0, .5, .5, 1))
    back, top = tile_mask((.5, 0, 1, .5)), tile_mask((.5, .5, .5 + 56 / T, .5 + 56 / T))
    tex[face] = lab_rgb(30.0)
    tex[side] = lab_rgb(36.0)
    tex[top] = lab_rgb(64.0, 3.0, 18.0)
    tex[back] = lab_rgb(30.0)
    ys, xs = np.mgrid[0:T, 0:T]
    known = face | side | top
    g = q.geom(tex)
    parts = [np.array(q.part, np.int32)]
    BO = TF.RULES['surface_groups']['body_override']
    old = BO.get('body_min_area_frac')
    BO['body_min_area_frac'] = 0.10
    try:
        pas, ctx, out, rep, k0 = run(g, tex, known, parts)
    finally:
        BO['body_min_area_frac'] = old
    bo = pas.get('body_override', {})
    ok(not any(r.get('fired') for r in bo.get('rules', [])), f'мелкая контрастная группа не даёт «корпус»: {bo.get("rules")}')
    ok(bool(bo.get('rejected_tiny')), f'отказ записан в паспорт: {bo.get("rejected_tiny")}')
    Lb = float(np.median(lab_L(out[0], back & ~known)))
    ok(abs(Lb - 64.0) > 15.0, f'зад не тоном мелочи ({Lb:.1f}, не 64)')


def test_top_follows_group():
    print('верх (Ш3в) без фото с тоном, далёким от однотонной группы, следует группе (T-28/1):')
    R = dict(TF.RULES['surface_groups'])
    R['top_follow'] = {'enabled': True, 'max_photo_share': 0.10, 'min_de00': 8.0, 'classes': ['тон + зерно', 'свет']}
    pas = {'groups': [{'id': 0, 'applied': True, 'class': 'тон + зерно', 'tone_lab': [70.7, -3.3, -0.6], 'texels_known': 100000},
                      {'id': 5, 'applied': True, 'class': 'узор', 'tone_lab': [40.0, 10.0, 20.0], 'texels_known': 3000}]}
    top = {'applied': True, 'tone_lab': [77.7, 3.6, 20.3], 'n_top': 57284, 'photo_top_n': 0, 'other_material_hint': False}
    r = SP.top_follows_group(top, pas, R)
    ok(r['follow'] and r['de00'] > 8.0, f'без фото, ΔE00 {r.get("de00")} от тона группы → следует группе')
    ok(not SP.top_follows_group(dict(top, photo_top_n=20000), pas, R)['follow'], 'верх виден на фото (35 %) — Ш3в остаётся')
    ok(not SP.top_follows_group(dict(top, other_material_hint=True), pas, R)['follow'], '«другой материал» по кромке≠плоскости — Ш3в остаётся')
    ok(not SP.top_follows_group(dict(top, tone_lab=[72.0, -3.0, 0.0]), pas, R)['follow'], 'тон Ш3в близок к группе (ΔE00 ≤ 8) — Ш3в остаётся')
    pas2 = {'groups': [dict(pas['groups'][0], **{'class': 'узор'})]}
    ok(not SP.top_follows_group(top, pas2, R)['follow'], 'класс «узор» не трогаем')
    R2 = dict(R, top_follow=dict(R['top_follow'], enabled=False))
    ok(not SP.top_follows_group(top, pas, R2)['follow'], 'top_follow.enabled=false — прежнее поведение')


def test_edge_body_tone():
    print('корпус по фото-текселям не-фасадных граней (T-28/1, шкаф 10887: фасад серо-голубой, кромки — светлое дерево):')
    E = {'enabled': True, 'min_texels': 600}
    rng = np.random.default_rng(3)
    wood = np.clip(np.array([77.7, 3.6, 20.3]) + rng.normal(0, 1.5, (900, 3)), -100, 100)
    r = SP.edge_body_tone(wood, [70.7, -3.3, -0.6], E, 12.0)
    ok(r['ok'] and abs(r['tone'][0] - 77.7) < 1.0 and r['de00'] > 12.0, f'900 фото-текселей дерева против серо-голубого → корпус ≈ дерево (ΔE00 {r.get("de00")})')
    ok(not SP.edge_body_tone(wood[:300], [70.7, -3.3, -0.6], E, 12.0)['ok'], 'мало текселей (300 < 600) — не срабатывает')
    same = np.clip(np.array([70.0, -3.0, -0.5]) + rng.normal(0, 1.0, (900, 3)), -100, 100)
    ok(not SP.edge_body_tone(same, [70.7, -3.3, -0.6], E, 12.0)['ok'], 'не-фасад того же тона (тот же материал) — не срабатывает')


def test_light_floor():
    print('светлое не темнеет: группа «свет» L≥90 — невидимое не темнее тона больше чем на 4 (T-28/1):')
    F = {'enabled': True, 'min_L': 90.0, 'max_darker_dL': 4.0}
    tgt = np.array([99.0, 92.0, 80.0, 70.0])
    out = SP.light_floor(tgt, np.full(4, 99.5), 'свет', F)
    ok(float(out.min()) >= 95.5 - 1e-9 and out[0] == 99.0, f'белая группа: min {out.min():.1f} ≥ 95.5, светлое не тронуто')
    ok(np.array_equal(SP.light_floor(tgt, np.full(4, 80.0), 'свет', F), tgt), 'тон группы L80 < 90 — не трогаем')
    ok(np.array_equal(SP.light_floor(tgt, np.full(4, 99.5), 'узор', F), tgt), 'класс «узор» не трогаем')
    ok(np.array_equal(SP.light_floor(tgt, np.full(4, 99.5), 'свет', dict(F, enabled=False)), tgt), 'enabled=false — прежнее поведение')


def test_rebuild_body_gates():
    print('корпус по тону верха (Ш3в): условия включения (T-28/1):')
    R = {'body_override': {'enabled': True, 'edge_body': {'enabled': True, 'min_texels': 600, 'use_top_tone': True}}}
    top = {'applied': True, 'tone_lab': [77.7, 3.6, 20.3], 'top_source': 'same_part_inference', 'other_material_hint': False}
    pas = {'groups': [{'id': 0, 'applied': True}, {'id': 100000, 'virtual_for': 0}]}
    ok(not SP.rebuild_body_from_top(pas, {}, [], R, None, top)['rebuilt'], 'виртуальный корпус уже есть — не пересобираем')
    pas0 = {'groups': [{'id': 0, 'applied': True}]}
    ok(not SP.rebuild_body_from_top(pas0, {}, [], R, None, dict(top, other_material_hint=True))['rebuilt'], '«другой материал» — не берём тон верха')
    ok(not SP.rebuild_body_from_top(pas0, {}, [], R, None, dict(top, top_source='trellis_prior'))['rebuilt'], 'источник не «по кромке той же части» — не берём')
    ok(not SP.rebuild_body_from_top(pas0, {}, [], R, None, dict(top, applied=False))['rebuilt'], 'Ш3в не применён — не берём')
    R2 = {'body_override': {'enabled': True, 'edge_body': {'enabled': True, 'min_texels': 600, 'use_top_tone': False}}}
    ok(not SP.rebuild_body_from_top(pas0, {}, [], R2, None, top)['rebuilt'], 'use_top_tone=false — прежнее поведение')


def test_facade_relief_and_release_weak():
    O = {'relief_depth_frac': 0.12, 'relief_margin_frac': 0.03}
    # плоскость фасада x∈[0,1], y∈[0,1], глубина z; опорные грани — сетка на z=0
    g = np.array([[x, y, 0.0] for x in np.linspace(0.05, 0.95, 10) for y in np.linspace(0.05, 0.95, 10)])
    sup = np.concatenate([np.ones(len(g), bool), np.zeros(3, bool)])
    cen = np.concatenate([g, np.array([[0.5, 0.5, 0.02], [0.0, 0.5, 0.02], [0.5, 0.5, 0.9]])])   # щель внутри / стенка на границе / глубоко
    side = np.concatenate([np.zeros(len(g), bool), np.ones(3, bool)])
    dep = cen[:, 2]
    r = SP.facade_relief(cen, np.array([[1.0, 0], [0, 1.0], [0, 0]]), dep, 0.0, 1.0, side, sup, O)
    ok(bool(r[-3]) and not bool(r[-2]) and not bool(r[-1]), 'щель внутри контура — рельеф; стенка на краю и глубокая грань — нет')
    ok(not SP.facade_relief(cen, np.array([[1.0, 0], [0, 1.0], [0, 0]]), dep, 0.0, 1.0, side, sup, {}).any(), 'правило выключено (нет relief_depth_frac) — рельефа нет')
    R = {'body_override': {'release_weak_known': {'enabled': True}}}
    k = [np.array([[True, True], [True, False]])]
    w = [np.array([[True, False], [True, False]])]
    o = [np.array([[0, 0], [-1, -1]])]
    nk, n = SP.release_weak_known(k, w, o, R)
    ok(n == 1 and not bool(nk[0][0, 0]) and bool(nk[0][0, 1]) and bool(nk[0][1, 0]), 'слабое фото на корпусной грани освобождено; прямое и слабое вне корпуса остались')
    nk2, n2 = SP.release_weak_known(k, w, o, {'body_override': {'release_weak_known': {'enabled': False}}})
    ok(n2 == 0 and nk2 is k, 'правило выключено — известное не меняется')


def test_type_allows_body():
    print('роль панели — только по типу: paint.hidden_pattern == body (T-28/1, владелец TG 2306: всё по типам):')
    import mesh_type_passports as MTP
    reg = MTP.load()                                                           # реальный реестр (А1 р.6): шкаф/комод — body, диван — same_fabric, стул — plain
    R = {'body_override': {'edge_body': {'require_hidden_pattern': 'body'}}}
    ok(SP.type_allows_body(dict(R, _card_role='шкаф'), reg)[0], 'шкаф (body) — правило действует')
    ok(not SP.type_allows_body(dict(R, _card_role='диван'), reg)[0], 'диван (same_fabric) — не действует')
    ok(not SP.type_allows_body(dict(R, _card_role='стул'), reg)[0], 'стул (plain) — не действует')
    ok(not SP.type_allows_body(dict(R, _card_role='неведомое'), reg)[0], 'типа нет в паспортах (unknown) — воздерживаемся')
    ok(not SP.type_allows_body(R, reg)[0], 'нет роли товара — не действует')
    ok(SP.type_allows_body({'body_override': {'edge_body': {}}}, reg)[0], 'require_hidden_pattern не задан — без ограничения по типу')


def test_grain_no_dark_seams():
    print('зерно группы — без тёмных швов пула блоков:')
    g, tex, known, parts, base = scene_plane_two_parts()
    tex2 = tex.copy()
    xs = np.arange(T)[None, :].repeat(T, 0)
    unk = ~known
    blocks = unk & ((xs % 32) < 2)                                                                  # «тёмные трещинки» на стыках блоков заливки
    tex2[blocks] = lab_rgb(20.0, 0.0, 0.0)
    pas, ctx, out, rep, k0 = run(g, tex2, known, parts)
    L = lab_L(out[0], unk & (((xs > 80) & (xs < 128)) | (xs > 205)))                                  # дальше растушёвки (seam_px) от известного
    ok(float(np.quantile(L, 0.001)) > 62.0 - 14.0, f'тёмных швов на невидимом нет: 0,1-й перцентиль L {np.quantile(L, 0.001):.1f}')


def test_gradient_continues():
    print('градиент (тёмный верх → светлый низ): класс «градиент», на невидимом продолжаем зависимость, не одну медиану:')
    q = Quads()
    q.quad([[-1, 0, 0], [1, 0, 0], [1, 1, 0], [-1, 1, 0]], (0, 0, 1, 1), part=0, sub=8)           # плоскость лицом +Z; Y вверх; v вверх
    ys, xs = np.mgrid[0:T, 0:T]
    yv = 1.0 - ys / (T - 1.0)                                                                       # 1 вверху, 0 внизу
    Lt = 35.0 + 35.0 * (1.0 - yv) + grain((T, T), 1.0, 8)                                           # верх L 35 → низ L 70
    tex = TF.lab2rgb(np.stack([Lt, np.full((T, T), 2.0), np.full((T, T), 5.0)], -1).reshape(-1, 3)).reshape(T, T, 3)
    known = xs < 120                                                                                # слева видно, справа — нет
    tex2 = tex.copy()
    tex2[~known] = lab_rgb(52.0, 2.0, 5.0)                                                          # заливка p5: один тон (медиана) — градиент потерян
    g = q.geom(tex2)
    parts = [np.array(q.part, np.int32)]
    pas, ctx, out, rep, k0 = run(g, tex2, known, parts)
    cls = [x['class'] for x in pas['groups'] if x.get('applied')]
    ok(cls == ['градиент'], f'класс «градиент»: {cls} ({[x.get("class_why") for x in pas["groups"]]})')
    top = (~known) & (ys < 40) & (xs > 150)
    bot = (~known) & (ys > T - 40) & (xs > 150)
    lt, lb = float(np.median(lab_L(out[0], top))), float(np.median(lab_L(out[0], bot)))
    ok(lb - lt > 20.0, f'на невидимом верх темнее низа, как на видимом: верх {lt:.1f}, низ {lb:.1f} (видимое 35 → 70; до правки 52 / 52)')
    ok(abs(lt - float(np.median(lab_L(tex, (xs < 120) & (ys < 40))))) < 8.0, 'верх невидимого ≈ верх видимого')
    ok(np.array_equal(out[0][known], tex2[known]), 'известное не изменилось (побайтно)')
    # контроль: ровная поверхность — не градиент
    gg, tx, kn, prt, _ = scene_plane_two_parts()
    pas2, _, _, _, _ = run(gg, tx, kn, prt)
    ok(all(x['class'] != 'градиент' for x in pas2['groups']), 'ровная поверхность — класс не «градиент»')


def test_outlier_replaced():
    print('выброс невидимого (контур двери, бежевые точки) — заливается тоном группы с зерном, не зажимается; видимое не трогается:')
    q = Quads()
    q.quad([[-1, 0, 0], [1, 0, 0], [1, 1, 0], [-1, 1, 0]], (0, 0, 1, 1), part=0, sub=8)
    ys, xs = np.mgrid[0:T, 0:T]
    known = xs < 120
    Lt = 60.0 + grain((T, T), 1.5, 3)
    lab = np.stack([Lt, np.full((T, T), 1.0), np.full((T, T), 3.0)], -1)
    tex = TF.lab2rgb(lab.reshape(-1, 3)).reshape(T, T, 3)
    tex2 = tex.copy()
    base = tex.copy()
    inv = ~known
    line = inv & (np.abs(xs - 200) <= 1) & (ys > 40) & (ys < 200)                                       # тёмная линия двери на заду
    tex2[line] = lab_rgb(25.0, 1.0, 3.0)
    dots = inv & ((xs - 160) ** 2 + (ys - 120) ** 2 < 16)                                               # бежевая точка
    tex2[dots] = lab_rgb(70.0, 12.0, 28.0)
    tex2[inv & ~line & ~dots] = lab_rgb(60.0, 1.0, 3.0)
    g = q.geom(tex2)
    pas, ctx, out, rep, k0 = run(g, tex2, known, [np.array(q.part, np.int32)])
    far = inv & ((np.abs(xs - 200) > 25) | (np.abs(xs - 160) > 25))
    Lo = lab_L(out[0], line & (ys > 60) & (ys < 180))
    ok(float(np.median(Lo)) > 52.0, f'линия на заду больше не тёмная: медиана L {np.median(Lo):.1f} (было 25)')
    Do = lab_L(out[0], dots)
    ok(abs(float(np.median(Do)) - 60.0) < 6.0, f'бежевая точка ушла в тон группы: L {np.median(Do):.1f}')
    ok(np.array_equal(out[0][known], tex2[known]), 'известное не изменилось (побайтно)')


def test_orphan_attached():
    print('часть без видимого тона (сирота) берёт тон соседа с самой длинной границей, а не остаётся светлой заплаткой:')
    g, tex, known, parts, base = scene_plane_two_parts()
    xs = np.arange(T)[None, :].repeat(T, 0)
    known2 = known & (xs < 128)                                                                      # у правой половины (часть 1) видимого нет совсем
    tex2 = tex.copy()
    tex2[xs >= 128] = lab_rgb(75.0, 0.0, 0.0)                                                        # заливка p5 — светлая заплатка (ΔE00 к тону группы ~9 < apply_de)
    pas, ctx, out, rep, k0 = run(g, tex2, known2, parts)
    gr = [x for x in pas['groups'] if x.get('applied') and 'virtual_for' not in x]
    ok(len(gr) == 1 and sorted(gr[0]['parts']) == [0, 1], f'сирота в группе соседа: {[(x["parts"], x["class"]) for x in pas["groups"]]}')
    right = (xs >= 128) & (xs < 230)
    ok(abs(float(np.median(lab_L(out[0], right))) - 62.0) < 5.0, f'правая половина в тон видимого: L {np.median(lab_L(out[0], right)):.1f} (заплатка была 75)')
    ok(any('attach_orphans' in m.get('why', '') or 'донора' in m.get('why', '') for m in pas['merges']), 'причина записана')


def test_orphan_guards():
    print('сирота: свой видимый тон другого материала — не сливается; без соседа — тон предмета; счётчик до/после:')
    xs = np.arange(T)[None, :].repeat(T, 0)
    # (а) у части 1 есть немного своего видимого (тёмного) → другой материал, остаётся своим
    g, tex, known, parts, base = scene_plane_two_parts()
    known2 = (known & (xs < 128)) | ((xs >= 128) & (xs < 150) & (np.arange(T)[:, None] < 30))      # 22×30=660 текселей своего видимого
    tex2 = tex.copy()
    tex2[xs >= 128] = lab_rgb(30.0, 0.0, 0.0)
    pas, ctx, out, rep, k0 = run(g, tex2, known2, parts)
    ok(not any(sorted(x['parts']) == [0, 1] for x in pas['groups']), f'со своим тёмным видимым не слито: {[(x["parts"], x["class"]) for x in pas["groups"]]}')
    # (б) отдельный четырёхугольник (часть 2), нигде не касающийся и без видимого → тон предмета
    q = Quads()
    q.quad([[-1, 0, 0], [0, 0, 0], [0, 1, 0], [-1, 1, 0]], (0, 0, 0.5, 1), part=0, sub=4)
    q.quad([[2, 0, 0], [3, 0, 0], [3, 1, 0], [2, 1, 0]], (0.5, 0, 1, 1), part=2, sub=4)
    tex3 = np.zeros((T, T, 3), np.uint8)
    L = 62.0 + grain((T, T), 1.6, 1)
    tex3[:] = TF.lab2rgb(np.stack([L, np.full((T, T), -2.0), np.full((T, T), 4.0)], -1).reshape(-1, 3)).reshape(T, T, 3)
    kn3 = (xs < 60)
    tex3[xs >= 128] = lab_rgb(70.0, 0.0, 0.0)
    g3 = q.geom(tex3)
    pas, ctx, out, rep, k0 = run(g3, tex3, kn3, [np.array(q.part, np.int32)])
    ok(len([x for x in pas['groups'] if x.get('applied') and 'virtual_for' not in x]) == 1, f'сирота без соседа — в группе предмета: {[(x["parts"], x["class"]) for x in pas["groups"]]}')
    o = pas['orphans']
    ok(o['before']['parts'] == [2] and o['after']['parts'] == [] and o['before']['texels_share_pct'] > 0, f'счётчик сирот до/после: {o["before"]} → {o["after"]}')
    right = (xs >= 140) & (xs < 250)
    ok(abs(float(np.median(lab_L(out[0], right))) - 62.0) < 5.0, 'сирота в тон видимого предмета')


def test_orphan_keeps_hook_tone():
    print('сирота, которой хуки уже дали далёкий тон (верх комода — дуб при графитовых фасадах), остаётся своей, а не уходит в группу:')
    g, tex, known, parts, base = scene_plane_two_parts()
    xs = np.arange(T)[None, :].repeat(T, 0)
    known2 = known & (xs < 128)
    tex2 = tex.copy()
    tex2[xs >= 128] = lab_rgb(85.0, 6.0, 20.0)                                                       # «дуб» от top_prior: ΔE00 ≫ apply_de от серой группы
    pas, ctx, out, rep, k0 = run(g, tex2, known2, parts)
    right = (xs >= 128) & (xs < 240)
    ok(abs(float(np.median(lab_L(out[0], right))) - 85.0) < 3.0, f'правая часть осталась со своим тоном: L {np.median(lab_L(out[0], right)):.1f}')
    ok(any(k['part'] == 1 for k in pas['orphans'].get('kept_own', [])) and 1 in pas['orphans']['after']['parts'], f'в счётчике: осталась своей {pas["orphans"].get("kept_own")}')


def test_hook_keep_top():
    print('текселы, окрашенные хуком верха (top_prior), группа не перекрашивает:')
    g, tex, known, parts, base = scene_plane_two_parts()
    xs = np.arange(T)[None, :].repeat(T, 0)
    known2 = known & (xs < 128)
    tex2 = tex.copy()
    tex2[xs >= 128] = lab_rgb(85.0, 6.0, 20.0)
    pas, ctx, out, rep, k0 = run(g, tex2, known2, parts, hook_keep=[(xs >= 128) & ~known2])
    right = (xs >= 128) & (xs < 240)
    ok(abs(float(np.median(lab_L(out[0], right))) - 85.0) < 3.0, f'верх остался: L {np.median(lab_L(out[0], right)):.1f}')


def test_ultratex_switch_off():
    print('выключатель UltraTex (rules ultratex.enabled=false): ut.glb не нужен и не читается:')
    import tempfile
    ok(TF.RULES['ultratex']['enabled'] is False, 'по умолчанию выключен (одна строка в rules/paint-fill.json)')
    g, tex, known, parts, base = scene_plane_two_parts()
    was_load = TC.load_geoms
    reads = []

    def spy(path, *a, **k):
        reads.append(path)
        return was_load(path, *a, **k)
    with tempfile.TemporaryDirectory() as td:
        TF.write_glb([g], [tex], os.path.join(td, 'in.glb'))
        TC.load_geoms = spy
        try:
            r = TF.run_stage_once(td, 'sku:ut', os.path.join(td, 'in.glb'), known=[known], parts=parts, cfg={'gutter': 0}, mirror=False, ut_glb=os.path.join(td, 'нет-такого-ut.glb'))
        finally:
            TC.load_geoms = was_load
    ok(not any('ut.glb' in str(p) for p in reads), f'ut.glb не читался: {[os.path.basename(str(p)) for p in reads]}')
    ut = r['report']['ultratex']
    ok(ut['enabled'] is False and ut['used'] is False, f'в отчёте: UltraTex выключен, не использован ({ut})')
    ok(r['report']['surface_groups']['enabled'] is True and 'after' in r['report']['surface_groups'], 'паспорт построен и применён без UltraTex')
    ok('sg_dE_base' in r['check']['metrics'] and 'sg_jump_p95' in r['check']['metrics'], 'мерки групп записаны в check.json (справочные: gate=false)')
    ok(r['check']['metrics']['known_changed_share_pct']['value'] == 0.0, 'известное этапу 6 не изменилось (known_changed_share_pct = 0)')


def test_hidden_pattern_by_type():
    print('рисунок на невидимое — по ТИПУ товара (паспорт типов, paint.hidden_pattern/mode; без ID; 07 читает политику до build, пишет её в check.json):')
    import mesh_type_passports as MTP
    ok(MTP.validate(MTP.load()) == [], 'реестр типов проходит схему')
    pf = TF.paint_policy_for({'top_card': {'role': 'шкаф'}})
    ok(pf['hidden_pattern'] == 'body' and pf['type'] == 'шкаф' and pf['digest'] == MTP.digest('шкаф') and pf['reason'] is None and pf['role'] == 'шкаф', f'07: роль карточки → политика типа с digest паспорта: {pf}')
    ok(TF.paint_policy_for({})['reason'] == 'no_role' and TF.paint_policy_for({'top_card': {'role': 'неведомая вещь'}})['reason'] == 'no_type', '07: нет роли → no_role; нет типа → no_type (воздержание с кодом причины)')
    q = Quads()
    q.quad([[-1, 0, 0], [1, 0, 0], [1, 1, 0], [-1, 1, 0]], (0, 0, 1, 1), part=0, sub=4)
    ys, xs = np.mgrid[0:T, 0:T]
    L = np.where((((xs // 10) + (ys // 10)) % 2).astype(bool), 70.0, 40.0) + grain((T, T), 0.5, 4)
    tex = TF.lab2rgb(np.stack([L, np.zeros((T, T)), np.zeros((T, T))], -1).reshape(-1, 3)).reshape(T, T, 3)
    known = xs < 128
    g = q.geom(tex)
    parts = [np.array(q.part, np.int32)]
    got = {}
    for role in ('ваза', 'шкаф', 'кресло', 'стул', 'картина', 'пуф', 'неведомая вещь', 'комод', 'витрина', 'стеллаж', 'кровать', 'диван'):
        pas, ctx, out, rep, k0 = run(g, tex, known, parts, product_role=role)
        sy = [r.get('synth') for r in rep.values() if r.get('synth')]
        got[role] = sy[0] if sy else None
    ok(got['ваза'] and got['ваза']['hidden_pattern'] == 'continue' and got['ваза']['mode'] != 'skip', f'ваза (continue): рисунок продолжается, синтез идёт: {got["ваза"]}')
    ok(got['кресло'] and got['кресло']['hidden_pattern'] == 'same_fabric' and got['кресло']['mode'] != 'skip', f'кресло (same_fabric): ткань без деталей лица, синтез идёт: {got["кресло"]}')
    for role, hp in (('шкаф', 'body'), ('стул', 'plain'), ('картина', 'not_applicable')):
        ok(got[role] and got[role]['mode'] == 'skip' and got[role]['hidden_pattern'] == hp, f'{role} ({hp}): узор лица не переносится, прежнее зерно: {got[role]}')
    ok(all(got[r] and got[r]['mode'] == 'skip' and got[r]['hidden_pattern'] == 'body' for r in ('комод', 'витрина', 'стеллаж')), 'комод/витрина/стеллаж (body): узорный фасад на зад не переносится')
    ok(all(got[r] and got[r]['hidden_pattern'] == 'same_fabric' and got[r]['mode'] != 'skip' for r in ('кровать', 'диван')), 'кровать/диван (same_fabric): ткань, синтез идёт')
    ok(got['пуф'] and got['пуф']['mode'] == 'skip' and 'observe' in got['пуф']['why'], f'пуф: политика в режиме observe — записана, не применяется: {got["пуф"]}')
    ok(got['неведомая вещь'] and got['неведомая вещь']['mode'] == 'skip' and got['неведомая вещь']['hidden_pattern'] == 'unknown' and 'no_type' in got['неведомая вещь']['why'], f'неизвестный тип → воздержание с кодом no_type (не «обычная мебель»): {got["неведомая вещь"]}')
    pas, ctx, out, rep, k0 = run(g, tex, known, parts)
    sy0 = [r.get('synth') for r in rep.values() if r.get('synth')]
    ok(sy0 and sy0[0]['mode'] == 'skip' and 'no_policy_in_ctx' in sy0[0]['why'], f'политики в контексте нет → воздержание: {sy0}')
    sg = TF.RULES['surface_groups']['synth']
    ok(sg['by_hidden_pattern']['same_fabric']['clip_k'] <= 3.0, 'same_fabric режет выбросы-детали (clip_k ≤ 3), пороги — в rules')


def test_blur_caches():
    print('кэши по маске (T-157/В): знаменатель размытия и расстояние до известного = прямой расчёт; разные маски не путаются; только чтение:')
    from scipy.ndimage import distance_transform_edt, gaussian_filter
    rng = np.random.default_rng(2)
    k1 = rng.random((96, 96)) > 0.6
    k2 = k1.copy()
    k2[10, 10] = ~k2[10, 10]
    img = rng.normal(50, 9, (96, 96, 3))
    SP._BLUR_CACHE.clear()
    SP._BLUR_BYTES[0] = 0
    for k in (k1, k2, k1):
        want = np.stack([gaussian_filter(img[..., c] * k.astype(float), 3.0, mode='nearest') for c in range(3)], -1) / np.maximum(gaussian_filter(k.astype(float), 3.0, mode='nearest'), 1e-9)[..., None]
        ok(np.array_equal(SP._blur_norm(img, k, 3.0), want), 'нормированное размытие совпало с прямым (бит в бит)')
    ok(np.array_equal(SP._edt(k1), distance_transform_edt(~k1)) and np.array_equal(SP._edt(k2), distance_transform_edt(~k2)) and not np.array_equal(SP._edt(k1), SP._edt(k2)), 'расстояние до известного по маске; другая маска — свой результат')
    e0 = np.zeros((96, 96), bool)
    ok(np.array_equal(SP._edt(e0), np.full((96, 96), 1e6)), 'пустая маска → 1e6 (как раньше)')
    ok(not SP._den(k1, 3.0).flags.writeable, 'из кэша отдаётся только для чтения')
    ok(not np.array_equal(SP._den(k1, 3.0), SP._den(k1, 4.0)), 'другое σ — другое значение')
    h0 = SP._BLUR_STATS['hit']
    SP._den(k1, 3.0)
    ok(SP._BLUR_STATS['hit'] == h0 + 1, 'повтор — из кэша')
    os.environ['REMLAB_BLUR_CACHE'] = '0'
    try:
        h1, m1 = SP._BLUR_STATS['hit'], SP._BLUR_STATS['miss']
        ok(np.array_equal(SP._den(k1, 3.0), gaussian_filter(k1.astype(float), 3.0, mode='nearest')) and SP._BLUR_STATS['hit'] == h1 and SP._BLUR_STATS['miss'] == m1, 'REMLAB_BLUR_CACHE=0 — без кэша, значения те же')
    finally:
        del os.environ['REMLAB_BLUR_CACHE']


def main() -> int:
    for f in (test_blur_caches, test_split_plane_one_tone, test_contrast_door_own_group, test_gray_pattern_not_flattened, test_back_is_body_not_facade, test_back_not_tiny_contrast, test_top_follows_group, test_edge_body_tone, test_light_floor, test_rebuild_body_gates, test_type_allows_body, test_body_override_only_for_body_type, test_facade_relief_and_release_weak, test_grain_no_dark_seams, test_gradient_continues, test_outlier_replaced, test_orphan_attached, test_orphan_guards, test_orphan_keeps_hook_tone, test_hook_keep_top, test_ultratex_switch_off, test_hidden_pattern_by_type):
        f()
    print(f'tests_surface_passport: ошибок {bad}')
    return 1 if bad else 0


if __name__ == '__main__':
    raise SystemExit(main())
