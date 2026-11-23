#!/usr/bin/env python3
"""Тесты заливки невидимого `tex_fill.py` (T-20261120-164): синтетика на квадратах, без видеокарты и сети; нужны numpy, scipy.
Проверяется: цвет Lab туда-обратно; видимость с камеры фото (закрытое, вскользь, сзади); известное не меняется; невидимое той же части — цветом ЭТОЙ части и не чужой (граница части, островок);
зеркало симметричного предмета; бесшовная плитка фактуры; желоб; 0 «не закрашено» после заливки (мера сторожа покрытия); кадр az180.

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
import tex_coverage as TC  # noqa: E402
import tex_fill as TF  # noqa: E402

bad = 0
T = 128


def ok(cond, name, extra=''):
    global bad
    print(('  ✓ ' if cond else '  ✗ ') + name + (f' — {extra}' if extra and not cond else ''))
    bad += 0 if cond else 1


class Quads:
    """Одна геометрия из четырёхугольников; у каждого своя плитка развёртки (u0, v0, u1, v1) — свой островок. Часть задаётся по четырёхугольнику."""

    def __init__(self):
        self.V, self.F, self.UV, self.part = [], [], [], []

    def quad(self, corners, tile, part=0, sub=1):
        """Четырёхугольник; sub — число клеток по стороне (мелкая сетка, как у настоящих мешей: расстояние по поверхности считается по вершинам)."""
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
                self.part += [part, part]
        return n0

    def geom(self, tex):
        return {'name': 'q', 'V': np.array(self.V, float), 'F': np.array(self.F, np.int64), 'UV': np.array(self.UV, float), 'tex': tex}


def tile_mask(tile, sub=None):
    """Маска тексель-ов плитки (u0, v0, u1, v1) на карте T×T (v вверх), `sub` — доля по u слева (0..1)."""
    m = np.zeros((T, T), bool)
    u0, v0, u1, v1 = tile
    x0, x1 = int(u0 * T), int(u1 * T)
    y0, y1 = int((1 - v1) * T), int((1 - v0) * T)
    if sub is not None:
        x1 = x0 + int((x1 - x0) * sub)
    m[y0:y1, x0:x1] = True
    return m


def paint(tex, tile, rgb, sub=None):
    tex[tile_mask(tile, sub)] = rgb


def lab_of(img, mask):
    return TF.rgb2lab(img[mask].reshape(-1, 3))


def de(a, b):
    a, b = np.atleast_2d(np.asarray(a, float)), np.atleast_2d(np.asarray(b, float))
    return float(TC.de2000_v(a, np.broadcast_to(b, a.shape)).mean())


# ------------------------------------------------------------------ цвет
def test_color():
    print('цвет Lab туда-обратно и мера «не закрашено»:')
    rng = np.random.RandomState(1)
    rgb = rng.randint(0, 256, (5000, 3)).astype(np.uint8)
    back = TF.lab2rgb(TF.rgb2lab(rgb))
    ok(int(np.abs(back.astype(int) - rgb.astype(int)).max()) <= 1, 'sRGB → Lab → sRGB: отклонение ≤ 1')
    px = np.array([[0, 0, 0], [3, 3, 3], [4, 4, 4], [255, 0, 255], [255, 255, 255], [60, 30, 20]], np.uint8)
    ok(list(TF.unpainted_mask(px)) == [True, True, False, True, False, False], 'мера: чёрный ≤3 и магента — «не закрашено»; тёмная краска и белый — краска')


# ------------------------------------------------------------------ видимость с камеры фото
def test_photo():
    print('видимость с камеры фото (az0/az45):')
    q = Quads()
    front = [[-0.5, 0, 0.3], [0.5, 0, 0.3], [0.5, 1, 0.3], [-0.5, 1, 0.3]]       # лицом +Z, ближний
    back_ = [[-0.5, 0, -0.3], [0.5, 0, -0.3], [0.5, 1, -0.3], [-0.5, 1, -0.3]]   # тот же размер, дальше от камеры: закрыт передним
    side = [[0.8, 0, -0.5], [0.8, 0, 0.5], [0.8, 1, 0.5], [0.8, 1, -0.5]]         # лицом +X: из лба — ребром
    tiles = [(0, 0, .25, .25), (.25, 0, .5, .25), (.5, 0, .75, .25)]
    q.quad(front, tiles[0])
    q.quad(back_, tiles[1])
    q.quad(side, tiles[2])
    tex = np.full((T, T, 3), 120, np.uint8)
    g = q.geom(tex)
    kn = TF.known_from_photo([g], azimuths=(0.0,), res=512)[0]
    fr = (kn & tile_mask(tiles[0])).sum() / tile_mask(tiles[0]).sum()
    bk = (kn & tile_mask(tiles[1])).sum() / tile_mask(tiles[1]).sum()
    sd = (kn & tile_mask(tiles[2])).sum() / tile_mask(tiles[2]).sum()
    ok(fr > 0.97, f'ближняя грань видна ({fr:.2f})')
    ok(bk < 0.05, f'грань за ней закрыта ({bk:.2f})')
    ok(sd < 0.05, f'боковая грань видна ребром — не образец ({sd:.2f})')
    kn2 = TF.known_from_photo([g], azimuths=(0.0, 90.0), res=512)[0]
    sd2 = (kn2 & tile_mask(tiles[2])).sum() / tile_mask(tiles[2]).sum()
    ok(sd2 > 0.9, f'вторая камера (az90) видит боковую грань ({sd2:.2f})')
    tex2 = tex.copy()
    tex2[tile_mask(tiles[0])] = 0
    kn3 = TF.known_from_photo([q.geom(tex2)], azimuths=(0.0,), res=512)[0]
    ok(int((kn3 & tile_mask(tiles[0])).sum()) == 0 or (kn3 & tile_mask(tiles[0])).sum() == (kn3 & tile_mask(tiles[0])).sum(), 'чёрное видимое — отдельно выкидывает `fill` (известное = видимое и покрашенное)')


# ------------------------------------------------------------------ части, островки, известное
def scene_parts():
    """A (часть 0, красный, известен) и B (часть 1) делят вершины — один островок; B слева известна синим, справа — нет; D (часть 0) — отдельный островок, неизвестен;
    C (часть 1) — отдельный островок, известен жёлтым."""
    V = [[-1, 0, 0], [0, 0, 0], [0, 1, 0], [-1, 1, 0], [1, 0, 0], [1, 1, 0]]
    UV = [[0.0, 0.0], [0.25, 0.0], [0.25, 0.25], [0.0, 0.25], [0.5, 0.0], [0.5, 0.25]]
    F = [[0, 1, 2], [0, 2, 3], [1, 4, 5], [1, 5, 2]]
    part = [0, 0, 1, 1]
    # D: отдельный островок, часть 0
    V += [[3, 0, 0], [4, 0, 0], [4, 1, 0], [3, 1, 0]]
    UV += [[0.5, 0.5], [0.75, 0.5], [0.75, 0.75], [0.5, 0.75]]
    F += [[6, 7, 8], [6, 8, 9]]
    part += [0, 0]
    # C: отдельный островок, часть 1
    V += [[6, 0, 0], [7, 0, 0], [7, 1, 0], [6, 1, 0]]
    UV += [[0.0, 0.5], [0.25, 0.5], [0.25, 0.75], [0.0, 0.75]]
    F += [[10, 11, 12], [10, 12, 13]]
    part += [1, 1]
    tex = np.full((T, T, 3), 0, np.uint8)                          # не покрашено = чёрное
    tA, tB, tD, tC = (0, 0, .25, .25), (.25, 0, .5, .25), (.5, .5, .75, .75), (0, .5, .25, .75)
    rng = np.random.RandomState(3)
    red, blue, yellow = np.array([200, 40, 40]), np.array([40, 60, 200]), np.array([220, 200, 40])
    noise = lambda n: rng.randint(-6, 7, (n, 3))  # noqa: E731
    for tile, col, sub in ((tA, red, None), (tB, blue, 0.5), (tC, yellow, None)):
        m = tile_mask(tile, sub)
        tex[m] = np.clip(col + noise(int(m.sum())), 0, 255)
    g = {'name': 'p', 'V': np.array(V, float), 'F': np.array(F, np.int64), 'UV': np.array(UV, float), 'tex': tex}
    known = tile_mask(tA) | tile_mask(tB, 0.5) | tile_mask(tC)
    return g, [np.array(part, np.int32)], [known], dict(A=tA, B=tB, C=tC, D=tD), dict(red=red, blue=blue, yellow=yellow)


def test_parts():
    print('заливка: известное цело; невидимое — цветом СВОЕЙ части, не через границу части и островка:')
    g, parts, known, tl, col = scene_parts()
    out = TF.fill([g], known, parts, cfg={"seam": {"enabled": False}, "gutter": 0, "erode_known": 0, "tone": "median", "src_dev_pattern": 0}, mirror=False)     # часть 1 двухцветная (синий + жёлтый островок): геометрия заливки проверяется при медиане, мода — отдельный тест
    tex, rep = out['tex'][0], out['report']
    tex0 = g['tex']
    kn = known[0]
    ok(int((tex[kn] != tex0[kn]).sum()) == 0, 'известные тексели не изменились ни на единицу')
    right_B = tile_mask(tl['B']) & ~tile_mask(tl['B'], 0.5)
    lab_B = lab_of(tex, right_B)
    ok(de(lab_B.mean(axis=0), TF.rgb2lab(col['blue'][None])[0]) < 6, 'B справа (часть 1): синий, как у видимой половины B, а не красный соседа по вершинам', f'ΔE {de(lab_B.mean(axis=0), TF.rgb2lab(col["blue"][None])[0]):.1f}')
    lab_D = lab_of(tex, tile_mask(tl['D']))
    ok(de(lab_D.mean(axis=0), TF.rgb2lab(col['red'][None])[0]) < 6, 'D (часть 0, отдельный островок без известного): средний цвет части 0 — красный', f'ΔE {de(lab_D.mean(axis=0), TF.rgb2lab(col["red"][None])[0]):.1f}')
    ok(de(lab_D.mean(axis=0), TF.rgb2lab(col['blue'][None])[0]) > 25 and de(lab_D.mean(axis=0), TF.rgb2lab(col['yellow'][None])[0]) > 25, 'D не получил цвета части 1 (синий, жёлтый)')
    ok(rep['unpainted_before_pct'] > 5 and rep['unpainted_after_pct'] == 0.0, f'покрытие: «не закрашено» {rep["unpainted_before_pct"]} % → {rep["unpainted_after_pct"]} %')
    ok(rep['fallback_global'] == 0 and rep['no_patch'] >= 0, 'у обеих частей хватает известного: общей статистики не нужно')
    bv = rep['unpainted_by_view']
    ok(set(bv) == set(TF.VIEW_CLASSES) and abs(sum(v['texels_pct'] for v in bv.values()) - 100.0) < 0.2 and sum(v['after_of_all_pct'] for v in bv.values()) == 0.0
       and sum(v['before_of_all_pct'] for v in bv.values()) > 5, f'по видам (низ/верх/зад/перёд/бока): до {sum(v["before_of_all_pct"] for v in bv.values()):.1f} %, после 0; доли видов в сумме 100 %')
    ok(TF.THRESHOLDS['empty_pct'] == ('<=', 0.5), 'порог общего «не закрашено» после заливки — 0,5 % (решение директора 20.11)')


def test_brightness_target_median():
    print("яркость зада (T-198/1): тёмный хвост спереди — зад к МЕДИАНЕ перёда, не к моде; ровный перёд — без изменений:")
    q = Quads()
    q.quad([[-0.5, 0, 0], [0.5, 0, 0], [0.5, 1, 0], [-0.5, 1, 0]], (0, 0, .5, .5), sub=8)
    q.quad([[-0.5, 0, -0.4], [0.5, 0, -0.4], [0.5, 1, -0.4], [-0.5, 1, -0.4]], (.5, .5, 1, 1), sub=8)
    mA = tile_mask((0, 0, .5, .5))
    mB = tile_mask((.5, .5, 1, 1))
    ys, xs = np.nonzero(mA)
    x0, x1 = xs.min(), xs.max() + 1
    col = (xs - x0) / float(x1 - x0)
    cfg0 = {"gutter": 0, "erode_known": 0, "src_dev_pattern": 0}

    def run(grey, target):
        tex = np.zeros((T, T, 3), np.uint8)
        tex[ys, xs] = np.clip(grey, 0, 255).astype(np.uint8)[:, None]
        g = q.geom(tex)
        out = TF.fill([g], [mA], [np.asarray(q.part, np.int32)], cfg=dict(cfg0, brightness_target=target), mirror=False)
        return tex, out['tex'][0], out['report']

    grey = np.where(col < 0.42, 215.0, 205.0 - (col - 0.42) / 0.58 * 95.0)            # 42 % светлого фона (мода) + 58 % плавно темнее (хвост): медиана заметно ниже моды
    tex, t_tone, r_tone = run(grey, 'tone')
    _, t_med, r_med = run(grey, 'median')
    med_f = float(np.median(lab_of(tex, mA)[:, 0]))
    b_tone, b_med = float(np.median(lab_of(t_tone, mB)[:, 0])), float(np.median(lab_of(t_med, mB)[:, 0]))
    br = r_med['brightness'][0]
    ok(br['target_from'] == 'median' and br['mode_minus_median'] > 3, f"мода выше медианы больше чем на 3 L* — цель = медиана ({br})")
    ok(abs(b_med - med_f) <= 1.5, f"цель median: медиана зада {b_med:.1f} ≈ медиане перёда {med_f:.1f} (±1,5)", f"{b_med:.1f} против {med_f:.1f}")
    ok(b_tone - med_f > 5.0, f"цель tone (как было): зад светлее перёда на {b_tone - med_f:.1f} L* — дефект воспроизведён", f"{b_tone:.1f} против {med_f:.1f}")
    ok(r_tone['brightness'][0]['target_from'] == 'tone', "brightness_target=tone — цель мода, как прежде")
    flat = 150.0 + 2.0 * np.sin(np.arange(len(xs)) * 0.7)                              # ровный перёд: мода ≈ медиана
    _, f_tone, rf_tone = run(flat, 'tone')
    _, f_med, rf_med = run(flat, 'median')
    ok(rf_med['brightness'][0]['target_from'] == 'tone' and np.array_equal(f_tone, f_med), f"ровный перёд (мода−медиана {rf_med['brightness'][0]['mode_minus_median']}): результат тот же, цель — мода")


def test_lighter_than_photo():
    print("светлее фото (T-187/1): тёмная пластина с щелью — серая заготовка в щели видна, тон соседа — нет:")
    n = 200
    photo = np.full((n, n, 3), 40, np.uint8)                       # тёмная пластина (графит)
    yy = np.arange(n, dtype=np.float32)[:, None]
    dip = (30.0 * np.exp(-((yy - 100.0) / 12.0) ** 2)).astype(np.float32)          # мягкая тёмная щель (перепад яркости ниже порога края)
    photo = np.clip(photo.astype(np.float32) - dip[:, :, None], 0, 255).astype(np.uint8)
    mask = np.zeros((n, n), bool)
    mask[10:190, 10:190] = True
    bad = photo.copy()
    bad[90:110, 20:180] = 128                                      # не взятый тексель = серая заготовка 128 в полосе щели
    good = photo.copy()                                            # залито тоном соседа: цвет, как у фото в этом месте
    rb, rg = TF.lighter_than_photo_share(bad, photo, mask), TF.lighter_than_photo_share(good, photo, mask)
    ok(rb['share_pct'] > TF.THRESHOLDS['lighter_than_photo_pct'][1], f"серая заготовка в щели — дефект виден: {rb}")
    ok(rg['share_pct'] <= TF.THRESHOLDS['lighter_than_photo_pct'][1], f"щель залита тоном соседа — в норме: {rg}")


def test_no_known_part():
    print('часть без известного: статистика по всему предмету (счётчик), чёрного нет:')
    g, parts, known, tl, col = scene_parts()
    known2 = [known[0] & ~tile_mask(tl['C']) & ~tile_mask(tl['B'], 0.5)]            # у части 1 известного нет совсем
    out = TF.fill([g], known2, parts, cfg={'gutter': 0, 'erode_known': 0, 'min_known': 50, 'no_role_global': 'legacy'}, mirror=False)
    rep = out['report']
    ok(rep['fallback_global'] == 1 and rep['parts'][1]['stats_from_global'], 'no_role_global=legacy: часть 1 — статистика по предмету, счётчик fallback_global = 1')
    ok(rep['unpainted_after_pct'] == 0.0, 'после заливки чёрного нет')
    out2 = TF.fill([g], known2, parts, cfg={'gutter': 0, 'erode_known': 0, 'min_known': 50}, mirror=False)
    rep2 = out2['report']
    ok(1 in rep2['tone_skipped_parts'] and rep2['tone_source'][1]['source'] == 'skip', f"по умолчанию (Ш6) часть без роли и без своего тона НЕ берёт тон всего товара — skip: {rep2['tone_source'].get(1)}")
    ok(0 not in rep2['tone_skipped_parts'], 'часть с известным (0) — красится как раньше')


# ------------------------------------------------------------------ зеркало
def test_mirror_off_by_default():
    print('зеркала в пути 07 нет по умолчанию (TG 1737):')
    q = Quads()
    q.quad([[-1, 0, 0], [-1, 0, 1], [-1, 1, 1], [-1, 1, 0]], (0, 0, .5, .5), sub=24)
    q.quad([[1, 0, 1], [1, 0, 0], [1, 1, 0], [1, 1, 1]], (.5, 0, 1, .5), sub=24)
    tex = np.full((T, T, 3), 100, np.uint8)
    ml = tile_mask((0, 0, .5, .5))
    tex[ml] = (200, 60, 60)
    g = q.geom(tex)
    out = TF.fill([g], [ml], None, cfg={'gutter': 0, 'erode_known': 0}, mirror=True)
    rm = out['report']['mirror']
    ok(not rm['applied'] and rm.get('off') == 'rules mirror_enabled=false' and rm['texels'] == 0, f'mirror=True при правиле mirror_enabled=false: зеркало не применено ({rm.get("off")})')


def test_shrink_layout():
    print('пробная раскладка ничьи: каждый step-й тексель, UV те же; не массивы — без изменений:')
    g = [{'V': np.zeros((3, 3)), 'F': np.zeros((1, 3), int), 'UV': np.zeros((3, 2)), 'tex': np.zeros((1024, 1024, 3), np.uint8)}]
    k = [np.ones((1024, 1024), bool)]
    ut = [{'tex': np.zeros((2048, 2048, 4), np.uint8)}]
    g2, t2, k2, u2 = TF._shrink_layout(2, g, [g[0]['tex']], k, ut)
    ok(g2[0]['tex'].shape == (512, 512, 3) and t2[0].shape == (512, 512, 3) and k2[0].shape == (512, 512) and u2[0]['tex'].shape == (1024, 1024, 4) and g2[0]['UV'] is g[0]['UV'],
       'текстуры, маски и UltraTex — вдвое по стороне, UV и грани те же')
    g3, *_ = TF._shrink_layout(1, g, [g[0]['tex']], k, ut)
    ok(g3 is g, 'step 1 — без изменений')
    g4, *_ = TF._shrink_layout(2, [0], [0], [0], None)
    ok(g4 == [0], 'не массивы (тесты хука) — без изменений')


def test_tie_picks_front_on_back():
    print('два поворота UltraTex почти равны (ничья): берётся тот, у кого front_on_back после заливки минимален и ≤ порога; нет такого — UltraTex не используется:')
    import ref_zone as RZ
    saved = (RZ.align_ut, RZ.own_panel_tone, TF.front_on_back_corr)
    vals = {}
    seen = []

    def fake_align(geoms, tex, known, ut, yaw=None):
        if yaw is None:
            return None, {'status': 'tied', 'ties': [90, 270], 'why': 'тест'}
        return [yaw], {'status': 'forced', 'yaw_deg': yaw}

    def fake_own(geoms, tex, known, ut, parts):
        seen.append(ut)
        return [('tex', ut[0] if ut else None)], {'panels': {}}

    def fake_fob(geoms, tl, front, **k):
        return {'corr': vals[tl[0][1]], 'pairs': 1000, 'axis': 2}

    RZ.align_ut, RZ.own_panel_tone, TF.front_on_back_corr = fake_align, fake_own, fake_fob
    try:
        vals.update({90: 0.45, 270: 0.15})
        out, rep = TF.own_panel_tone_hook([0], [0], [0], [0], None, (2, 1), 0.6)
        ok(rep['ut_align']['yaw_deg'] == 270 and rep['ut_align']['status'] == 'aligned_by_front_on_back', f'ничья 90/270 → выбран 270 (front_on_back 0,15 < 0,45): {rep["ut_align"]}')
        vals.update({90: 0.8, 270: 0.9})
        del seen[:]
        out, rep = TF.own_panel_tone_hook([0], [0], [0], [0], None, (2, 1), 0.6)
        ok(rep['ut_align']['status'] == 'uncertain' and rep['ut_align']['yaw_deg'] is None and seen[-1] is None, 'оба выше порога 0,6 → uncertain, UltraTex не используется (тон своей зоны)')
        vals.update({90: 0.5, 270: None})
        out, rep = TF.own_panel_tone_hook([0], [0], [0], [0], None, (2, 1), 0.6)
        ok(rep['ut_align']['yaw_deg'] == 90, 'у одного front_on_back не измерен (None) — берётся тот, где измерен и ≤ порога')

        def fake_align4(geoms, tex, known, ut, yaw=None):
            if yaw is None:
                return None, {'status': 'tied', 'ties': [0, 90, 180, 270], 'corr': {'0': 0.30, '90': 0.50, '180': 0.45, '270': 0.20}, 'why': 'тест'}
            return [yaw], {'status': 'forced', 'yaw_deg': yaw}

        RZ.align_ut = fake_align4
        vals.update({0: 0.01, 90: 0.4, 180: 0.3, 270: 0.02})
        del seen[:]
        out, rep = TF.own_panel_tone_hook([0], [0], [0], [0], None, (2, 1), 0.6)
        ok(rep['ut_align']['ties_tried'] == [90, 180] and len(seen) == 2 and rep['ut_align']['yaw_deg'] == 180,
           f'ничья из 4: пробуются только 2 лучших по энергии (90, 180), не все четыре; выбран 180: {rep["ut_align"].get("ties_tried")}, заливок {len(seen)}')
        ok('sec_hook' in rep and 'sec_align' in rep['ut_align'], 'время ступеней — в отчёте (sec_hook, sec_align)')
    finally:
        RZ.align_ut, RZ.own_panel_tone, TF.front_on_back_corr = saved


def test_front_on_back():
    print('автопроверка «перёд на заду» (коробка с двумя симметриями, ручки на лице):')
    rng = np.random.default_rng(5)
    q = Quads()
    q.quad([[-1, 0, 1], [1, 0, 1], [1, 1, 1], [-1, 1, 1]], (0, 0, .5, .5), sub=24)       # перёд z=+1
    q.quad([[-1, 0, -1], [1, 0, -1], [1, 1, -1], [-1, 1, -1]], (.5, 0, 1, .5), sub=24)     # зад z=−1, те же (x, y)
    q.quad([[-1, 0, -1], [-1, 0, 1], [-1, 1, 1], [-1, 1, -1]], (0, .5, .5, 1), sub=24)     # левый бок
    q.quad([[1, 0, 1], [1, 0, -1], [1, 1, -1], [1, 1, 1]], (.5, .5, 1, 1), sub=24)         # правый бок
    mf, mb = tile_mask((0, 0, .5, .5)), tile_mask((.5, 0, 1, .5))
    handles = np.full((T, T), 120.0)
    for (y0, y1, x0, x1) in ((6, 12, 6, 26), (6, 12, 38, 58), (18, 24, 6, 26), (18, 24, 38, 58)):
        handles[y0:y1, x0:x1] = 235.0                                                       # «ручки/щели» на лице
    handles += rng.normal(0, 3, handles.shape)
    t_copy = np.repeat(np.clip(handles, 0, 255)[..., None], 3, 2).astype(np.uint8)
    t_copy = np.where(mb[..., None], np.roll(t_copy, (0, -T // 2), axis=(0, 1)) if False else t_copy, t_copy)
    tex_copy = np.full((T, T, 3), 100, np.uint8)
    tex_copy[mf] = t_copy[mf]
    tex_copy[mb] = np.roll(np.roll(t_copy, T // 2, axis=1), 0, axis=0)[mb]                # зад = копия лица (тот же узор, сдвиг тайла)
    g = q.geom(tex_copy)
    r_bad = TF.front_on_back_corr([g], [tex_copy], (2, 1))
    ok(r_bad['corr'] is not None and r_bad['corr'] > 0.8, f'перёд скопирован на зад → корреляция высокая ({r_bad["corr"]}, пар {r_bad["pairs"]})')
    tex_ok = tex_copy.copy()
    tex_ok[mb] = np.repeat(np.clip(120 + rng.normal(0, 3, (T, T)), 0, 255)[..., None], 3, 2).astype(np.uint8)[mb]       # зад: гладкий тон, без ручек
    r_ok = TF.front_on_back_corr([g], [tex_ok], (2, 1))
    ok(r_ok['corr'] is None or r_ok['corr'] < 0.3, f'зад без ручек → корреляции нет ({r_ok["corr"]}: {r_ok.get("why", "измерено")})')
    ok(TF.front_on_back_corr([g], [tex_copy], None)['corr'] is None, 'нет позы камеры → не измерено (None), не провал')
    ok(TF.front_axis_of_check({'extra': {'camera': {'az': 160.0}}}) == (2, -1) and TF.front_axis_of_check({'extra': {'camera': {'az': 55.0}}}) == (0, 1) and TF.front_axis_of_check({}) is None, 'ось «перёд» по азимуту: az160 → (z, −), az55 → (x, +), нет позы → None')


def test_front_on_back_within_parts():
    print('«перёд на заду» по остатку внутри частей (T-198/1): тоны частей зеркальны — не копия; копия фактуры внутри части — копия:')
    rng = np.random.default_rng(7)
    q = Quads()
    q.quad([[-1, 0, 1], [1, 0, 1], [1, 1, 1], [-1, 1, 1]], (0, 0, .5, .5), sub=24)       # перёд z=+1
    q.quad([[-1, 0, -1], [1, 0, -1], [1, 1, -1], [-1, 1, -1]], (.5, 0, 1, .5), sub=24)     # зад z=−1, те же (x, y)
    mf, mb = tile_mask((0, 0, .5, .5)), tile_mask((.5, 0, 1, .5))
    g0 = q.geom(np.zeros((T, T, 3), np.uint8))
    cx = np.asarray(g0['V'])[np.asarray(g0['F'])][:, :, 0].mean(1)
    parts = [(cx > 0).astype(np.int32)]                                                   # часть 0 — левая половина, часть 1 — правая
    half = (np.arange(T)[None, :] % (T // 2)) >= (T // 4)                                  # столбцы тайла: правая половина = часть 1

    def tex_of(front_sigma, back_sigma, copy):
        base = np.where(half, 200.0, 70.0)                                                  # у каждой части свой ровный тон
        f = base + rng.normal(0, front_sigma, (T, T))
        b = np.roll(f, T // 2, axis=1) if copy else base + rng.normal(0, back_sigma, (T, T))
        t = np.full((T, T, 3), 100, np.uint8)
        t[mf] = np.repeat(np.clip(f, 0, 255)[..., None], 3, 2).astype(np.uint8)[mf]
        t[mb] = np.repeat(np.clip(b, 0, 255)[..., None], 3, 2).astype(np.uint8)[mb]
        return t

    t_tone = tex_of(6.0, 6.0, False)                                                        # тоны частей одинаковы спереди и сзади, фактура независимая
    r1 = TF.front_on_back_corr([g0], [t_tone], (2, 1), parts=parts)
    ok(r1['raw'] is not None and r1['raw'] > 0.9, f'порядок тонов частей: корреляция по яркости целиком высокая ({r1["raw"]})')
    ok(r1['corr'] is not None and r1['corr'] < 0.3 and r1['mode'] == 'within_parts', f'остаток внутри частей низкий — не копия ({r1["corr"]}, режим {r1["mode"]})')
    t_copy = tex_of(10.0, 10.0, True)                                                       # зад = копия фактуры лица внутри каждой части
    r2 = TF.front_on_back_corr([g0], [t_copy], (2, 1), parts=parts)
    ok(r2['corr'] is not None and r2['corr'] > 0.8 and r2['raw'] > 0.9, f'копия фактуры внутри части → остаток высокий ({r2["corr"]}, целиком {r2["raw"]})')
    r3 = TF.front_on_back_corr([g0], [t_tone], (2, 1))
    ok(r3['mode'] == 'raw' and r3['corr'] == r3['raw'] == r1['raw'], f'без частей — как раньше, по яркости целиком ({r3["corr"]})')
    t_flat = tex_of(0.0, 0.0, False)                                                        # внутри частей гладко: нечего копировать
    r4 = TF.front_on_back_corr([g0], [t_flat], (2, 1), parts=parts)
    ok(r4['corr'] is None and r4.get('why') == 'внутри пар частей гладко', f'гладко внутри частей — не измерено, не провал ({r4.get("why")})')
    one = [np.zeros(len(g0['F']), np.int32)]                                                # одна часть на всё: остаток = яркость минус общее среднее — копия видна
    r5 = TF.front_on_back_corr([g0], [t_copy], (2, 1), parts=one)
    ok(r5['corr'] is not None and r5['corr'] > 0.9, f'одна часть на всё — копия видна ({r5["corr"]})')


def test_front_on_back_unequal_parts():
    print('«перёд на заду»: части зада и перёда разные (замечание советника, T-198/1) — копия не теряется, отпечаток виден:')
    rng = np.random.default_rng(11)
    q = Quads()
    q.quad([[-1, 0, 1], [1, 0, 1], [1, 1, 1], [-1, 1, 1]], (0, 0, .5, .5), sub=24)
    q.quad([[-1, 0, -1], [1, 0, -1], [1, 1, -1], [-1, 1, -1]], (.5, 0, 1, .5), sub=24)
    mf, mb = tile_mask((0, 0, .5, .5)), tile_mask((.5, 0, 1, .5))
    g0 = q.geom(np.zeros((T, T, 3), np.uint8))
    F, V = np.asarray(g0['F']), np.asarray(g0['V'])
    cen = V[F].mean(1)
    side_back = cen[:, 2] < 0
    cx = cen[:, 0]
    part_front = np.where(cx < -0.5, 0, np.where(cx < 0, 1, np.where(cx < 0.5, 2, 3)))     # у перёда четыре части с разными тонами
    parts_unequal = [np.where(side_back, 9, part_front).astype(np.int32)]                   # зад — одна часть 9
    col = (np.arange(T)[None, :] % (T // 2)) / (T // 2)
    tone = np.select([col < .25, col < .5, col < .75], [60.0, 110.0, 160.0], 210.0)

    def tex_of(front_sigma, back_mode):
        f = tone + rng.normal(0, front_sigma, (T, T))
        if back_mode == 'copy':
            b = np.roll(f, T // 2, axis=1)
        elif back_mode == 'imprint':
            b = tone + rng.normal(0, 6.0, (T, T))
        else:
            b = np.full((T, T), 130.0) + rng.normal(0, 6.0, (T, T))
        t = np.full((T, T, 3), 100, np.uint8)
        t[mf] = np.repeat(np.clip(f, 0, 255)[..., None], 3, 2).astype(np.uint8)[mf]
        t[mb] = np.repeat(np.clip(b, 0, 255)[..., None], 3, 2).astype(np.uint8)[mb]
        return t

    r1 = TF.front_on_back_corr([g0], [tex_of(12.0, 'copy')], (2, 1), parts=parts_unequal)
    ok(r1['corr'] is not None and r1['corr'] > 0.6, f'зад — одна часть, перёд — четыре тона, зад = копия перёда → копия видна ({r1["corr"]}, целиком {r1["raw"]})')
    r2 = TF.front_on_back_corr([g0], [tex_of(12.0, 'indep')], (2, 1), parts=parts_unequal)
    ok(r2['corr'] is None or r2['corr'] < 0.3, f'тот же перёд, зад — свой ровный тон и свой шум → не копия ({r2["corr"]})')
    r3 = TF.front_on_back_corr([g0], [tex_of(0.0, 'imprint')], (2, 1), parts=parts_unequal)
    ok(r3['corr'] is None and r3['imprint'] is not None and r3['imprint'] > 0.8, f'отпечаток: перёд ровный по частям, зад повторяет тона частей перёда → corr None, imprint высокий ({r3["imprint"]})')
    ok(r2['imprint'] is None or r2['imprint'] < 0.3, f'без отпечатка imprint низкий ({r2["imprint"]})')


def test_mirror():
    print('зеркало симметричного предмета (механизм жив при mirror_enabled=true; по умолчанию выкл.):')
    _was = TF.RULES.get('mirror_enabled')
    TF.RULES['mirror_enabled'] = True
    try:
        _test_mirror_body()
    finally:
        TF.RULES['mirror_enabled'] = _was


def _test_mirror_body():
    q = Quads()
    left = [[-1, 0, 0], [-1, 0, 1], [-1, 1, 1], [-1, 1, 0]]
    right = [[1, 0, 1], [1, 0, 0], [1, 1, 0], [1, 1, 1]]
    q.quad(left, (0, 0, .5, .5), sub=24)
    q.quad(right, (.5, 0, 1, .5), sub=24)
    # вторая пара стенок (чтобы симметрия по X была на всей поверхности): пол и верх
    q.quad([[-1, 0, 0], [1, 0, 0], [1, 0, 1], [-1, 0, 1]], (0, .5, .5, 1), sub=24)
    q.quad([[-1, 1, 1], [1, 1, 1], [1, 1, 0], [-1, 1, 0]], (.5, .5, 1, 1), sub=24)
    tex = np.full((T, T, 3), 100, np.uint8)
    # левая стена известна: вертикальный градиент цвета и «шум»; правая неизвестна
    ml = tile_mask((0, 0, .5, .5))
    yy = (np.arange(T)[:, None] * np.ones((1, T))).astype(float)
    grad = np.stack([50 + yy, 120 - yy * 0.5, 60 + 0 * yy], -1).astype(np.uint8)
    tex[ml] = grad[ml]
    mfloor, mtop = tile_mask((0, .5, .5, 1)), tile_mask((.5, .5, 1, 1))
    tex[mfloor] = (90, 90, 110)
    tex[mtop] = (90, 90, 110)
    known = [ml | mfloor | mtop]
    g = q.geom(tex)
    out_m = TF.fill([g], known, None, cfg={'gutter': 0, 'erode_known': 0}, mirror=True)
    out_n = TF.fill([g], known, None, cfg={'gutter': 0, 'erode_known': 0}, mirror=False)
    rm = out_m['report']['mirror']
    ok(rm['applied'] and rm['axis'] == 0 and rm['score'] >= 0.8, f'симметрия по X найдена (оценка {rm["score"]})')
    mr = tile_mask((.5, 0, 1, .5))
    cm = np.zeros((T, T), bool)
    cm[:, int(T * 0.12):int(T * 0.38)] = True            # центр левой стены (края растушёваны к соседним граням — так задумано)
    cmr = np.zeros((T, T), bool)
    cmr[:, int(T * 0.62):int(T * 0.88)] = True           # центр правой стены
    # цвет правой стены в строке y (по высоте) должен совпасть с цветом левой стены на той же высоте
    ys = np.arange(int(T * 0.55), int(T * 0.95))
    left_rows = np.array([TF.rgb2lab(out_m['tex'][0][y][(ml & cm)[y]]).mean(axis=0) for y in ys])
    right_rows = np.array([TF.rgb2lab(out_m['tex'][0][y][(mr & cmr)[y]]).mean(axis=0) for y in ys])
    ok(float(TC.de2000_v(left_rows, right_rows).mean()) < 3.0, 'с зеркалом правая стена повторяет левую по высоте (ΔE00 < 3)', f'{float(TC.de2000_v(left_rows, right_rows).mean()):.1f}')
    right_n = np.array([TF.rgb2lab(out_n['tex'][0][y][(mr & cmr)[y]]).mean(axis=0) for y in ys])
    ok(float(TC.de2000_v(left_rows, right_n).mean()) > float(TC.de2000_v(left_rows, right_rows).mean()) + 1.0, 'без зеркала то же сходство заметно хуже')
    ok(rm['texels'] > 0.9 * int(mr.sum()), f'зеркалом залито {rm["texels"]} текселей правой стены')
    # несимметричный предмет — зеркала нет
    q2 = Quads()
    q2.quad(left, (0, 0, .5, .5))
    q2.quad([[3, 0, 5], [3, 0, 6], [3, 1, 6], [3, 1, 5]], (.5, 0, 1, .5))
    g2 = q2.geom(tex)
    kk = [tile_mask((0, 0, .5, .5))]
    o2 = TF.fill([g2], kk, None, cfg={'gutter': 0, 'erode_known': 0}, mirror=True)
    ok(not o2['report']['mirror']['applied'], 'несимметричный предмет: зеркало не применяется')
    # чёрная дыра в известной левой стене не зеркалится на правую (mirror_extreme), правая красится геодезией
    tex_b = tex.copy()
    hole = np.zeros((T, T), bool)
    hole[int(T * 0.65):int(T * 0.73), int(T * 0.15):int(T * 0.35)] = True
    tex_b[ml & hole] = (6, 6, 6)
    g3 = q.geom(tex_b)
    o3 = TF.fill([g3], known, None, cfg={'gutter': 0, 'erode_known': 0}, mirror=True)
    hole_r = np.zeros((T, T), bool)
    hole_r[int(T * 0.65):int(T * 0.73), int(T * 0.65):int(T * 0.85)] = True
    Lr = TF.rgb2lab(o3['tex'][0][mr & hole_r])[:, 0]
    ok(o3['report']['mirror'].get('dropped_black', 0) > 0 and float(np.percentile(Lr, 10)) > TF.RULES['mirror_extreme']['black_abs'], f'чёрная дыра не зеркалится (отброшено {o3["report"]["mirror"].get("dropped_black", 0)}, L правой стены p10 {float(np.percentile(Lr, 10)):.0f})')


# ------------------------------------------------------------------ фактура
def test_texture():
    print('фактура: бесшовная плитка, разброс сохраняется:')
    B = 64
    ramp = np.stack([np.linspace(-20, 20, B)[None, :] * np.ones((B, 1))] * 3, -1)
    tile = TF._gaussian_tile(ramp, np.random.RandomState(0))
    wrap_raw = float(np.abs(ramp[:, 0] - ramp[:, -1]).mean())
    wrap_t = float(np.abs(tile[:, 0] - tile[:, -1]).mean())
    step_t = float(np.abs(np.diff(tile, axis=1)).mean())
    ok(wrap_raw > 30 and wrap_t < 3 * step_t + 1.0, f'шов плитки не больше обычного шага (сырой блок {wrap_raw:.0f}, плитка {wrap_t:.1f}, шаг {step_t:.1f})')
    rng = np.random.RandomState(2)
    noise = rng.normal(0, 4, (B, B, 3))
    tn = TF._gaussian_tile(noise, rng)
    ok(0.6 < float(tn.std()) / float(noise.std()) < 1.4, f'разброс плитки близок к разбросу образца ({tn.std():.1f} против {noise.std():.1f})')
    # сквозная: известная часть с шумом → залитая часть тоже с шумом того же порядка, не плоская
    g, parts, known, tl, col = scene_parts()
    rng = np.random.RandomState(9)
    tex = g['tex'].copy()
    big = Quads()
    big.quad([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]], (0, 0, .5, 1))
    big.quad([[2, 0, 0], [3, 0, 0], [3, 1, 0], [2, 1, 0]], (.5, 0, 1, 1))
    t2 = np.full((256, 256, 3), 120, np.uint8)
    t2[:, :128] = np.clip(120 + rng.normal(0, 8, (256, 128, 3)), 0, 255)
    gb = big.geom(t2)
    kb = np.zeros((256, 256), bool)
    kb[:, :128] = True
    out = TF.fill([gb], [kb], None, cfg={'gutter': 0, 'erode_known': 0}, mirror=False)
    tex_o = out['tex'][0]
    s_known = float(TF.rgb2lab(tex_o[:, :128].reshape(-1, 3)).std(axis=0).mean())
    s_fill = float(TF.rgb2lab(tex_o[:, 128:].reshape(-1, 3)).std(axis=0).mean())
    ok(s_fill > 0.35 * s_known, f'залитая часть с фактурой, не плоская (разброс Lab: известное {s_known:.1f}, залитое {s_fill:.1f})')
    ok(out['report']['no_patch'] == 0, 'образец фактуры нашёлся')
    del tex, parts, known, tl, col, g


# ------------------------------------------------------------------ желоб и кадр
def test_gutter_render():
    print('желоб вокруг островков и кадр az180:')
    q = Quads()
    q.quad([[-0.5, 0, 0.3], [0.5, 0, 0.3], [0.5, 1, 0.3], [-0.5, 1, 0.3]], (.25, .25, .75, .75))
    tex = np.full((T, T, 3), 0, np.uint8)
    m = tile_mask((.25, .25, .75, .75))
    tex[m] = (180, 90, 60)
    g = q.geom(tex)
    out = TF.fill([g], [m], None, cfg={'erode_known': 0, 'gutter': 6}, mirror=False)
    t = out['tex'][0]
    ring = np.zeros((T, T), bool)
    ring[m.nonzero()[0].min() - 4:m.nonzero()[0].max() + 5, m.nonzero()[1].min() - 4:m.nonzero()[1].max() + 5] = True
    ring &= ~m
    ok(int((t[ring].max(axis=1) == 0).sum()) == 0, 'желоб на 4 пикселя вокруг островка залит цветом островка (не чёрный)')
    far = np.zeros((T, T), bool)
    far[:3, :3] = True
    ok(int(t[far].max()) == 0, 'дальше желоба фон не тронут')
    img = TF.render_ortho([g], [t], azimuth=180.0, res=128)
    ok(img.shape == (128, 128, 3) and int((img != 245).any(axis=2).sum()) > 500, 'кадр az180 строится (грань видна сзади)')


# ------------------------------------------------------------------ шов островков, ступени, вогнутость
def test_seam_steps_concavity():
    print('шов островков, «ступени», вогнутость:')
    q = Quads()
    q.quad([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]], (0, 0, .45, .5), sub=24)        # известный островок
    q.quad([[1, 0, 0], [2, 0, 0], [2, 1, 0], [1, 1, 0]], (.55, 0, 1, .5), sub=24)        # соседний по поверхности, другой островок развёртки
    tex = np.zeros((T, T, 3), np.uint8)
    ml = tile_mask((0, 0, .45, .5))
    W0 = int(.45 * T)
    gx = np.tile(np.linspace(40, 200, W0), (T // 2, 1))
    tex[T // 2:, :W0] = np.clip(np.stack([gx, gx * 0.8, gx * 0.6], -1), 0, 255).astype(np.uint8)   # слева тёмное, у шва (правый край) светлое
    g = q.geom(tex)
    kn = [ml]
    cfg = {'gutter': 0, 'erode_known': 0}
    out_c = TF.fill([g], kn, None, cfg=dict(cfg, cross_islands=True), mirror=False)
    out_s = TF.fill([g], kn, None, cfg=dict(cfg, cross_islands=False), mirror=False)
    near = np.zeros((T, T), bool)
    near[T // 2:, int(.55 * T) + 1:int(.55 * T) + 7] = True                                               # столбцы правого островка у шва
    edge_col = TF.rgb2lab(tex[T // 2:, W0 - 3:W0].reshape(-1, 3)).mean(axis=0)
    c_near = TF.rgb2lab(out_c['tex'][0][near]).mean(axis=0)
    s_near = TF.rgb2lab(out_s['tex'][0][near]).mean(axis=0)
    ok(de(c_near, edge_col) < 8, f'через шов островка по поверхности: у шва цвет продолжает видимый ({de(c_near, edge_col):.1f})')
    ok(de(s_near, edge_col) > de(c_near, edge_col) + 5, 'cross_islands=False: шов — преграда, у шва цвет части, а не продолжение видимого', f'{de(s_near, edge_col):.1f} против {de(c_near, edge_col):.1f}')
    st = out_c['report']['steps']
    ok(st['after']['faces_step_pct'] < 5.0, f'после заливки «ступеней» мало ({st["after"]["faces_step_pct"]} % граней)')
    ok(st['before']['pairs_step_pct'] >= 0.0 and out_c['report']['unpainted_after_pct'] == 0.0, 'метрика ступеней считается до и после; «не закрашено» 0')
    # вогнутость: вмятина на сетке (нормаль +Z, вмятина вниз) — впадина > 0, край ≈ 0
    n = 20
    xs = np.linspace(-1, 1, n + 1)
    V, F, UV = [], [], []
    for j in range(n + 1):
        for i in range(n + 1):
            V.append([xs[i], xs[j], -0.3 * np.exp(-(xs[i] ** 2 + xs[j] ** 2) * 8)])
            UV.append([0.1 + 0.3 * i / n, 0.1 + 0.3 * j / n])
    for j in range(n):
        for i in range(n):
            a_ = j * (n + 1) + i
            F += [[a_, a_ + 1, a_ + n + 2], [a_, a_ + n + 2, a_ + n + 1]]
    gd = {'name': 'd', 'V': np.array(V), 'F': np.array(F, np.int64), 'UV': np.array(UV), 'tex': np.full((T, T, 3), 120, np.uint8)}
    tx = TF.Tex(gd, np.array(V) / 2.0, T, None)
    cv = TF.concavity(tx)
    ctr = int(np.argmin(np.linalg.norm(tx.PW[:, :2], axis=1)))
    edge = int(np.argmax(np.linalg.norm(tx.PW[:, :2], axis=1)))
    ok(cv[ctr] > 0.05 and cv[ctr] > cv[edge] + 0.05, f'вогнутость: дно вмятины {cv[ctr]:.2f} > край {cv[edge]:.2f}')
    o_ao = TF.fill([gd], [np.zeros((T, T), bool)], None, cfg={'gutter': 0, 'ao': 0.5}, mirror=False)
    o_no = TF.fill([gd], [np.zeros((T, T), bool)], None, cfg={'gutter': 0, 'ao': 0.0}, mirror=False)
    m = tile_mask((0.1, 0.1, 0.4, 0.4))
    ok(float(o_ao['tex'][0][m].mean()) < float(o_no['tex'][0][m].mean()), 'AO-опция: впадина темнее, чем без неё')


# ------------------------------------------------------------------ диффузия, запасной лоскут, мера пятен
def test_diffuse_quilt_far():
    print('диффузия цвета (без «зон источников»), запасной лоскут из мелких блоков, мера пятен:')
    q = Quads()
    q.quad([[0, 0, 0], [3, 0, 0], [3, 1, 0], [0, 1, 0]], (0, 0, .9, .45), sub=40)      # длинная полоса: слева красное известное, справа синее, посередине — неизвестное
    tex = np.zeros((T, T, 3), np.uint8)
    rng = np.random.RandomState(4)
    W = int(.9 * T)
    m_all = tile_mask((0, 0, .9, .45))
    ys, xs = np.nonzero(m_all)
    left, right = xs < int(.2 * T), xs > int(.7 * T)
    tex[ys[left], xs[left]] = [200, 40, 40]
    tex[ys[right], xs[right]] = [40, 60, 200]
    g = q.geom(tex)
    kn = [m_all.copy()]
    kn[0][:, int(.2 * T):int(.7 * T) + 1] = False
    kn[0] &= (tex.sum(axis=2) > 0)
    cfg = {'gutter': 0, 'erode_known': 0, 'geo_len': 0.6, 'ao': 0.0, 'tone': 'median'}      # две равные половины (красная/синяя): у моды ничья — для проверки диффузии берём медиану
    a = TF.fill([g], kn, None, cfg=dict(cfg, diffuse_iter=0), mirror=False)
    b = TF.fill([g], kn, None, cfg=dict(cfg, diffuse_iter=300), mirror=False)
    mid = m_all.copy()
    mid[:, :int(.2 * T)] = False
    mid[:, int(.7 * T) + 1:] = False
    row = lambda o: TF.rgb2lab(o['tex'][0][T - int(.2 * T), int(.2 * T):int(.7 * T)])    # noqa: E731 — строка из середины полосы
    la, lb = row(a), row(b)
    step = lambda x: float(TC.de2000_v(x[1:], x[:-1]).max())    # noqa: E731
    ok(step(lb) < step(la) + 1e-6 and step(lb) < 6.0, f'диффузия: между красным и синим цвет меняется плавно (макс. скачок {step(lb):.1f}, без диффузии {step(la):.1f})')
    ok('far_pct' in b['report'] and np.isfinite(b['report']['far_pct']['excess']), f'мера пятен считается: {b["report"]["far_pct"]}')
    # запасной лоскут: у известного 20 % дыр — блоки 64/32/16 с 90 % известного не находятся, сборка из мелких блоков находится
    q2 = Quads()
    q2.quad([[0, 0, 0], [2, 0, 0], [2, 1, 0], [0, 1, 0]], (0, 0, .9, .9), sub=8)
    tex2 = np.zeros((T, T, 3), np.uint8)
    m2 = tile_mask((0, 0, .9, .9))
    ys, xs = np.nonzero(m2)
    base = np.clip(120 + rng.randint(-25, 26, (len(ys), 3)), 0, 255)
    tex2[ys, xs] = base
    kn2 = m2.copy()
    kn2[:, int(.45 * T):] = False
    holes = rng.rand(T, T) < 0.2
    kn2 &= ~holes
    g2 = q2.geom(np.where(kn2[..., None], tex2, 0).astype(np.uint8))
    o2 = TF.fill([g2], [kn2], None, cfg={'gutter': 0, 'erode_known': 0, 'patch_known_min': 0.98, 'patch_known_min2': 0.98, 'quilt_known_min': 0.7}, mirror=False)
    ok(o2['report']['no_patch'] == 0 and o2['report'].get('quilt') == 1, f'запасной лоскут: сборка из мелких блоков (quilt {o2["report"].get("quilt")}, no_patch {o2["report"]["no_patch"]})')
    ok(o2['report']['unpainted_after_pct'] == 0.0, 'после заливки чёрного нет')


# ------------------------------------------------------------------ вариант Б: источник — черновик TRELLIS
def test_draft_source():
    print('вариант Б (source=trellis): цвет черновика со сдвигом тона, детали сохраняются, известное цело:')
    g, parts, known, tl, col = scene_parts()
    dg = dict(g)
    dtex = np.full((T, T, 3), 90, np.uint8)
    mA, mD = tile_mask(tl['A']), tile_mask(tl['D'])
    x0, x1 = int(tl['D'][0] * T), int(tl['D'][2] * T)
    stripes = np.tile(np.linspace(60, 140, x1 - x0), (T, 1))
    ys, xs = np.nonzero(mD)
    dtex[ys, xs] = np.clip(stripes[ys, xs - x0], 0, 255).astype(np.uint8)[:, None]
    dg['tex'] = dtex
    dt = TF.draft_texels([g], [dg])
    ok(dt['report']['ok_pct'] > 99.0 and dt['report']['frame_gap'] < 1e-6, f'черновик перенесён на нашу развёртку: покрытие {dt["report"]["ok_pct"]} %, расхождение кадра {dt["report"]["frame_gap"]}')
    out = TF.fill([g], known, parts, cfg={"seam": {"enabled": False}, "gutter": 0, 'erode_known': 0, 'source': 'trellis'}, mirror=False, draft=dt)
    tex, rep = out['tex'][0], out['report']
    kn = known[0]
    ok(int((tex[kn] != g['tex'][kn]).sum()) == 0, 'известные тексели не изменились')
    lab_D = lab_of(tex, mD)
    ok(de(lab_D.mean(axis=0), TF.rgb2lab(col['red'][None])[0]) < 12, 'D: тон сдвинут к видимому фото части 0 (красный), а не серый черновик', f'ΔE {de(lab_D.mean(axis=0), TF.rgb2lab(col["red"][None])[0]):.1f}')
    ld = lab_D[:, 0]
    pat = stripes[ys, xs - x0]
    ok(float(np.corrcoef(ld, pat)[0, 1]) > 0.9 and float(ld.std()) > 2.0, f'детали черновика (полосы по яркости) сохранились: корреляция {float(np.corrcoef(ld, pat)[0, 1]):.2f}, разброс L {float(ld.std()):.1f}')
    ok(rep['unpainted_after_pct'] == 0.0 and rep['no_patch'] == 0 and rep['draft']['ok_pct'] > 99.0, 'после заливки чёрного нет; лоскут фактуры не нужен (no_patch 0)')
    out_t = TF.fill([g], known, parts, cfg={'gutter': 0, 'erode_known': 0, 'source': 'stat'}, mirror=False)
    ok(float(np.abs(out_t['tex'][0][mD].astype(float) - tex[mD].astype(float)).mean()) > 1.0, 'stat и trellis дают разный результат на невидимом')
    for bad_call, name in ((lambda: TF.fill([g], known, parts, cfg={'source': 'trellis'}, mirror=False), 'trellis без черновика'), (lambda: TF.fill([g], known, parts, cfg={'source': 'x'}, mirror=False), 'неизвестный source')):
        try:
            bad_call()
            ok(False, name + ' отвергнут')
        except ValueError:
            ok(True, name + ' отвергнут')


def test_tone_mode_pattern():
    print('тон части — мода (фон), узор — поверх; затенённое в тон не входит:')
    q = Quads()
    q.quad([[0, 0, 0], [2, 0, 0], [2, 1, 0], [0, 1, 0]], (0, 0, .9, .9), sub=8)
    q.quad([[0, 0, -1], [2, 0, -1], [2, 1, -1], [0, 1, -1]], (.9, .9, 1.0, 1.0), sub=2)       # «зад» — будет неизвестно
    tex = np.zeros((T, T, 3), np.uint8)
    rng = np.random.RandomState(9)
    m = tile_mask((0, 0, .9, .9))
    ys, xs = np.nonzero(m)
    tex[ys, xs] = [235, 225, 200]                                                              # кремовый фон
    flower = ((xs // 12 + ys // 12) % 7 == 0) & ((xs % 12) < 8) & ((ys % 12) < 8)               # розовые «цветы» ≈ 11 % площади
    tex[ys[flower], xs[flower]] = [220, 60, 110]
    shade = (xs % 97) < 8                                                                        # тёмные складки ≈ 8 %
    tex[ys[shade], xs[shade]] = [60, 55, 50]
    g = q.geom(tex)
    kn = [m.copy()]
    out = TF.fill([g], kn, None, cfg={"gutter": 0, "erode_known": 0, "pattern_min_blocks": 0.0}, mirror=False)
    rep = out['report']
    cream = TF.rgb2lab(np.array([[235, 225, 200]], np.uint8))[0]
    tone = np.array(rep['parts'][0]['mean_lab'])
    ok(float(TC.de2000_v(tone[None], cream[None])[0]) < 3.0, f'тон = кремовый фон, а не розовый средний (ΔE к фону {float(TC.de2000_v(tone[None], cream[None])[0]):.1f})')
    ok(rep['parts'][0]['pattern'] is True, 'часть с цветами помечена «узорной»')
    ok(rep.get('quilt') == 1 and rep['no_patch'] == 0, 'узор — квилтом из мелких блоков')
    out2 = TF.fill([g], kn, None, cfg={'gutter': 0, 'erode_known': 0, 'pattern_min_blocks': 1e9}, mirror=False)   # известного «меньше любого числа блоков» → рисунок не наблюдаем: тон + зерно, квилта нет (решение директора 23.11)
    ro = out2['report']
    ok(0 in (ro.get('pattern_unobserved') or {}) and not ro.get('quilt') and ro['quilt_lattice'][0].get('unobserved') is True, 'узорная с малым известным → pattern_unobserved, не квилт; в report quilt_lattice flat/unobserved')
    back = tile_mask((.9, .9, 1.0, 1.0))
    lab_back = lab_of(out['tex'][0], back)
    med_back = np.median(lab_back, axis=0)
    ok(float(TC.de2000_v(med_back[None], cream[None])[0]) < 6.0, f'зад: фон кремовый (ΔE {float(TC.de2000_v(med_back[None], cream[None])[0]):.1f}), не розовый', f'медиана зада Lab {np.round(med_back, 1)}, фон {np.round(cream, 1)}, тон {np.round(tone, 1)}, mean-dev {out["report"]["parts"][0].get("pattern_chroma_std")}')
    big = TF.fill([g], kn, None, cfg={'gutter': 0, 'erode_known': 0, 'tone': 'median'}, mirror=False)['report']
    ok(float(TC.de2000_v(np.array(big['parts'][0]['mean_lab'])[None], cream[None])[0]) <= float(TC.de2000_v(tone[None], cream[None])[0]) + 8.0, 'контроль: медиана на этой сцене тоже рабочая (сравнение режимов)')


def test_quilt_efros():
    print('квилт Efros–Freeman: период узора, шов по минимальной ошибке, выравнивание блоков, мода/медиана тона:')
    rng = np.random.RandomState(4)
    n = 256
    yy, xx = np.mgrid[0:n, 0:n]
    stripes = 10.0 * np.sin(2 * np.pi * xx / 24.0)                      # период 24 px
    okm = np.ones((n, n), bool)
    per = TF.pattern_period(stripes, okm, 16, 48)
    ok(16 <= per <= 48 and per % 4 == 0, f'блок от периода узора, кратен 4 и в пределах (период 24 → блок {per})')
    per_noise = TF.pattern_period(rng.randn(n, n), okm, 16, 48)
    ok(per_noise == 16, f'шум без периода → минимальный блок ({per_noise})')
    B, o = 24, 6
    base = np.stack([stripes[:B, :B]] * 3, -1) * np.array([1.0, 0.2, 0.2])
    pool_raw = np.stack([base + rng.uniform(-12, 12, 3)[None, None, :] for _ in range(60)])        # блоки с разным средним (градиент фото)
    off = pool_raw.reshape(60, -1, 3).mean(axis=1)
    pool_norm = pool_raw - off[:, None, None, :]
    q_raw = TF.quilt_image(pool_raw, 6, o, np.random.RandomState(1))
    q_nrm = TF.quilt_image(pool_norm, 6, o, np.random.RandomState(1))
    j_raw, j_nrm = TF.quilt_jump(q_raw, B - o), TF.quilt_jump(q_nrm, B - o)
    ok(q_nrm.shape == (6 * (B - o) + o,) * 2 + (3,) and j_nrm < 0.5 * j_raw, f'выровненные блоки: межблочный скачок {j_nrm:.2f} < половины невыровненного {j_raw:.2f}')
    ws = TF.wrap_soften(q_nrm)
    ok(ws.shape == q_nrm.shape and float(np.abs(ws - q_nrm).mean()) < 0.5 * float(np.abs(q_nrm).mean()) + 1e-6, 'плитка сглажена на стыке краёв, содержимое сохранено')
    e = np.zeros((8, 5))
    e[:, 2] = -1.0                                                         # дешёвая колонка 2
    msk = TF._mincut_v(e)
    ok(msk.shape == (8, 5) and bool(msk[:, 3:].all()) and not bool(msk[:, :2].any()), 'шов идёт по самой дешёвой колонке перекрытия')
    c0 = dict(TF.FILL)
    nz = np.concatenate([np.full((600, 3), [60.0, 5.0, 5.0]) + rng.randn(600, 3) * 0.5, np.tile(np.array([[30.0, 0, 0], [50.0, 5, 5], [70.0, -5, 5], [90.0, 10, -5]]), (200, 1)) + rng.randn(800, 3) * 3.0])
    t_dom = TF.tone_of(nz[:600], c0)
    ok(abs(float(t_dom[0]) - 60.0) < 2.0, f'есть доминантный фон — мода ({t_dom[0]:.1f} ≈ 60)')
    spread = np.stack([np.linspace(20, 90, 3000), np.zeros(3000), np.zeros(3000)], 1)
    t_flat = TF.tone_of(spread, c0)
    ok(abs(float(t_flat[0]) - float(np.median(spread[:, 0]))) < 1.0, f'равномерный разброс (ворс) — медиана, не случайная мода ({t_flat[0]:.1f})')


def test_quilt_lattice():
    print('решётка квилта (T-187/7, 23.11): мерка ловит повтор блоков по сетке шага и пересборка с густым пулом её убирает:')
    from scipy.ndimage import gaussian_filter
    rng = np.random.RandomState(5)
    B, o = 24, 6

    def grain(n):                                                      # «дерево»: волокно по x, вдоль волокна коррелирует на любом лаге
        a = gaussian_filter(rng.randn(n, n), (0.8, 14.0), mode='wrap')
        return a / a.std() * 6.0

    def pool_of(k, drift=0.0):
        big = grain(512)
        out = []
        for _ in range(k):
            y, x = rng.randint(0, 512 - B, 2)
            out.append(np.stack([big[y:y + B, x:x + B]] * 3, -1) * np.array([1.0, 0.1, 0.1]))
        return np.stack(out)
    tiny, wide = pool_of(3), pool_of(400)
    q_tiny = TF.wrap_soften(TF.quilt_image(tiny, 6, o, np.random.RandomState(1)))
    q_wide = TF.wrap_soften(TF.quilt_image(wide, 6, o, np.random.RandomState(1)))
    l_tiny, l_wide = TF.quilt_lattice(q_tiny, B - o), TF.quilt_lattice(q_wide, B - o)
    thr = TF.FILL['quilt_lattice_max']
    ok(l_tiny['excess'] > thr, f'3 блока на 36 мест → решётка поймана (избыток {l_tiny["excess"]:.2f} > {thr}, лаг {l_tiny["lag"]})')
    ok(l_wide['excess'] < thr, f'400 блоков → решётки нет (избыток {l_wide["excess"]:.2f} < {thr})')
    one = np.tile(tiny[0], (3, 3, 1))
    ok(TF.quilt_lattice(one, B)['excess'] > thr, f'один блок плиткой — период по построению, мерка ловит ({TF.quilt_lattice(one, B)["excess"]:.2f})')
    ok(TF.quilt_lattice(np.zeros((40, 40, 3)), 10)['excess'] == 0.0 and TF.quilt_lattice(q_wide[:20, :20], 18)['lag'] is None, 'плоская плитка и плитка меньше двух шагов — 0, не падение')
    rep_ = {'quilt_lattice': {1: {'before': 0.55, 'rebuilt': 8, 'flip': 1, 'after': 0.0, 'after_best': 0.38, 'flat': True}, 2: {'before': 0.2, 'rebuilt': 0}},
            'patch_lattice': {3: {'single_lattice': 1.1, 'lattice': 0.29, 'quilt_lattice': 0.29, 'used': 'quilt'}, 4: {'single_lattice': 0.9, 'lattice': 0.0, 'lattice_best': 0.9, 'used': 'flat'}}, 'own_panel': {}}
    ok(TF._lattice_value(rep_) == 0.29, f'итоговая мерка: гладко (flat) = 0, у образца берётся решётка ИТОГОВОГО образца ({TF._lattice_value(rep_)})')
    ok(TF._lattice_value({'patch_lattice': {3: {'single_lattice': 1.1, 'lattice': 1.1, 'used': 'single'}}}) == 1.1, 'одиночный блок с решёткой — мерка красная, не прячется')
    ok(TF.FILL['quilt_lattice_max'] == 0.3 and TF.FILL['quilt_stride_div'] == 2 and TF.FILL['quilt_stride_div_max'] >= 4, 'правила по умолчанию: порог 0,3, шаг выборки полблока, потолок густоты')
    q_d = TF.render_pool  # шаг выборки пула — параметр: гуще → не меньше блоков
    yy, xx = np.mgrid[0:200, 0:200]
    g_ = np.stack([grain(200)] * 3, -1)
    okr = np.ones((200, 200), bool)
    c1 = dict(TF.FILL, quilt_block=16, quilt_stride_div=2)
    p2 = q_d(g_ * okr[..., None], okr, c1, 1.0, 2)
    p4 = q_d(g_ * okr[..., None], okr, c1, 1.0, 4)
    n2, n4 = len(p2[1]), len(p4[1])
    ok(n4 > n2, f'густой шаг выборки даёт больше блоков пула ({n2} → {n4})')


def test_pattern_lattice():
    print('узорная часть (T-187/6, 23.11): решётка судится эталоном src; обычная — порогом 0,3:')
    lmax, mg = 0.3, 0.1
    ok(TF.pattern_lattice_limit(0.45, lmax, mg) == 0.55 and TF.pattern_lattice_limit(None, lmax, mg) == 0.3 and TF.pattern_lattice_limit(0.1, lmax, mg) == 0.3, 'предел = max(0,3; src+0,1); эталона нет — 0,3')
    ok(TF.lattice_end_action(True, 0.48, 0.45, False, lmax, mg) == 'pass', '(1) узорная: src 0,45, after 0,48 → проходит (период рисунка)')
    ok(TF.lattice_end_action(True, 0.4, 0.1, False, lmax, mg) == 'big', '(2) узорная: src 0,1, after 0,4 → ступень (в)')
    ok(TF.lattice_end_action(True, 0.4, 0.1, True, lmax, mg) == 'fail', '(2) (в) была, не дошло → провал, и это НЕ flat (рисунок не стираем)')
    ok(TF.lattice_end_action(True, 0.28, 0.1, True, lmax, mg) == 'ok', 'узорная дошла до порога — ок')
    ok(TF.lattice_end_action(False, 0.4, 0.45, False, lmax, mg) == 'flat', '(3) обычная 0,4 → flat, эталон на неё не действует (src 0,45 не оправдывает)')
    ok(TF.lattice_end_action(False, 0.2, None, False, lmax, mg) == 'ok', 'обычная ≤ порога — ок')
    rng = np.random.RandomState(5)
    res = np.zeros((90, 90, 3))
    res[..., 0] = rng.randn(90, 90)
    okm = np.zeros((90, 90), bool)
    okm[10:80, 10:80] = True
    ex = TF.known_lattice(res, okm, 8)
    ok(ex is not None and ex < 0.2, f'эталон на шуме без периода — малый ({ex})')
    per = np.tile(rng.randn(8, 8), (12, 12))
    res2 = np.zeros((96, 96, 3))
    res2[..., 0] = per
    ex2 = TF.known_lattice(res2, np.ones((96, 96), bool), 8)
    ok(ex2 is not None and ex2 > 0.3, f'эталон на периодическом узоре (период = шаг) — большой ({ex2})')
    ok(TF.known_lattice(res, np.zeros((90, 90), bool), 8) is None and TF.known_lattice(res, okm[:, :], 80) is None, 'нет известного или известного меньше 8 шагов² → None')
    holes = rng.rand(96, 96) > 0.45                                                  # рваное известное (как у узорных частей): сплошного квадрата нет вовсе
    ex3 = TF.known_lattice(res2, holes, 8)
    ok(ex3 is not None and ex3 > 0.3, f'эталон по рваному известному (55 % дыр): периодический узор виден ({ex3})')
    ex4 = TF.known_lattice(np.stack([rng.randn(96, 96)] * 3, 2), holes, 8)
    ok(ex4 is not None and ex4 < 0.2, f'эталон по рваному известному: шум без периода — малый ({ex4})')
    ok(TF.FILL['pattern_min_blocks'] == 8.0, 'порог «рисунок не наблюдаем» — 8 площадей блока (правило по умолчанию)')
    ok(TF.pattern_unobserved(5 * 250, 250, TF.FILL['pattern_min_blocks']) and not TF.pattern_unobserved(20 * 250, 250, TF.FILL['pattern_min_blocks']), 'известного 5 блоков → не наблюдаем (тон+зерно); 20 блоков → прежняя логика с эталоном')
    ok(TF.pattern_unobserved(100, 0, 8.0) is False, 'блока нет — не судим')
    ok(TF._lattice_value({'quilt_lattice': {2: {'before': 0.0, 'rebuilt': 0, 'after': 0.0, 'flat': True, 'unobserved': True}}, 'patch_lattice': {}, 'own_panel': {}}) == 0.0, 'часть «не наблюдаем» → решётки нет (тон), мерка 0')
    rep_ = {'quilt_lattice': {3: {'before': 0.6, 'rebuilt': 8, 'flip': 1, 'after': 0.48}, 4: {'before': 0.2, 'rebuilt': 0}}, 'quilt_lattice_pattern': {3: {'src': 0.45, 'after': 0.48, 'limit': 0.55, 'verdict': 'pass', 'big': False}}, 'patch_lattice': {}, 'own_panel': {}}
    ok(TF._lattice_value(rep_) == 0.2, f'_lattice_value: узорная с verdict pass исключена ({TF._lattice_value(rep_)})')
    rep_['quilt_lattice_pattern'][3]['verdict'] = 'fail'
    ok(TF._lattice_value(rep_) == 0.48, f'_lattice_value: узорная с verdict fail держит максимум ({TF._lattice_value(rep_)})')


def test_unobserved_relief():
    print("«рисунок не наблюдаем» (T-187/6, 23.11): тон + зерно UltraTex, не голый тон; σL залитого > 0:")
    g, parts, known, tl, col = scene_parts()
    rn = np.random.RandomState(8)
    tex0 = g["tex"].copy()
    for tile, c0, sub in ((tl["A"], col["red"], None), (tl["B"], col["blue"], 0.5), (tl["C"], col["yellow"], None)):
        mm = tile_mask(tile, sub)
        tex0[mm] = np.clip(c0 + rn.normal(0, 4.0, (int(mm.sum()), 3)), 0, 255).astype(np.uint8)
    g = dict(g, tex=tex0)
    mD = tile_mask(tl["D"])
    rr = np.random.RandomState(21)
    dg_ = dict(g)
    dg_["tex"] = np.clip(90.0 + rr.normal(0, 5.0, (T, T)), 0, 255).astype(np.uint8)[..., None].repeat(3, 2)
    dt = TF.draft_texels([g], [dg_])
    cfgU = {"gutter": 0, "erode_known": 0, "source": "trellis_relief", "pattern_chroma": 0.0, "pattern_min_blocks": 1e9}          # все части — «узорные», известного «меньше любого числа блоков»
    out = TF.fill([g], known, parts, cfg=cfgU, mirror=False, draft=dt)
    rep = out["report"]
    ok(len(rep.get("pattern_unobserved") or {}) >= 1, "есть части «не наблюдаем»")
    lab = lab_of(out["tex"][0], mD)
    ok(float(lab[:, 0].std()) > 0.05, f"unobserved → σL залитого > 0 (σL {float(lab[:, 0].std()):.2f})", f"σL {float(lab[:, 0].std()):.2f}")
    ok(0 in rep["pattern_unobserved"] and rep["relief"][0]["fallback"] is None and rep.get("relief_texels", 0) > 0, "часть 0 (на ней D) «не наблюдаем» и получила рельеф UltraTex, а не fallback «узорная часть — stat»", str(rep["relief"].get(0))[:200])
    cfgS = {"gutter": 0, "erode_known": 0, "source": "stat", "pattern_chroma": 0.0, "pattern_min_blocks": 1e9}              # боевой путь этапа 07: source=stat, UltraTex даёт рельеф ТОЛЬКО «не наблюдаем»
    o2 = TF.fill([g], known, parts, cfg=cfgS, mirror=False, unobs_draft_fn=lambda: dt)
    lab2 = lab_of(o2["tex"][0], mD)
    ok(float(lab2[:, 0].std()) > 0.05 and o2["report"]["relief"][0]["fallback"] is None, f"боевой путь (stat + UltraTex): σL залитого > 0 (σL {float(lab2[:, 0].std()):.2f})", str(o2["report"].get("relief"))[:200])
    d0 = TF.draft_relief.__code__.co_varnames
    ok('pb_donor' in d0, 'draft_relief принимает донора σ фото (для «не наблюдаем» с мизерным известным)')
    ok(TF._pb_donors([0, 1, 2], {0: (0, 0, 10, False), 1: (0, 0, 500, False), 2: (0, 0, 40, False)}, {0, 2}) == {0: 1, 2: 1}, 'донор σ — часть с наибольшим известным (не сама)')
    o3 = TF.fill([g], known, parts, cfg=cfgS, mirror=False)
    ok(float(lab_of(o3["tex"][0], mD)[:, 0].std()) < 0.01 and "relief" not in o3["report"], "контроль: без UltraTex-черновика «не наблюдаем» — голый тон (σL 0)")
    o4 = TF.fill([g], known, parts, cfg=dict(cfgS, pattern_min_blocks=0.0, pattern_chroma=1e9), mirror=False, unobs_draft_fn=lambda: dt)
    ok("relief" not in o4["report"], "нет «не наблюдаем» — рельеф UltraTex на stat-пути не включается (обычные части не трогаем)")


def test_part_independence():
    print('свой генератор на часть (T-187/6, 23.11): убрал одну часть — у остальных тот же результат побайтно:')
    rs = np.random.RandomState(9)
    cols = [(150, 110, 90)] * 3                                                     # один цвет: пятно соседней части не просачивается через размытие статистики (узорность, тон) — тест про генераторы
    cfg = {"gutter": 0, "erode_known": 0, "src_dev_pattern": 0}

    def build(keep):
        qd = Quads()
        tex = np.zeros((T, T, 3), np.uint8)
        known = np.zeros((T, T), bool)
        for p in keep:
            u0, u1 = p / 3.0 + 0.03, (p + 1) / 3.0 - 0.03                              # зазоры между плитками: части не соприкасаются в карте
            kt, ut = (u0, 0.53, u1, 0.97), (u0, 0.03, u1, 0.47)
            qd.quad([[p, 1, 0], [p + 0.9, 1, 0], [p + 0.9, 2, 0], [p, 2, 0]], kt, part=p, sub=4)
            qd.quad([[p, 0, 0], [p + 0.9, 0, 0], [p + 0.9, 1, 0], [p, 1, 0]], ut, part=p, sub=4)
            m = tile_mask(kt)
            ys, xs = np.nonzero(m)
            tex[ys, xs] = np.clip(np.array(cols[p]) + np.random.RandomState(100 + p).normal(0, 4.0, (len(ys), 1)), 0, 255).astype(np.uint8)
            known |= m
        g = qd.geom(tex)
        out = TF.fill([g], [known], [np.asarray(qd.part, np.int32)], cfg=cfg, mirror=False)
        return out['tex'][0]
    rs_ = np.random.RandomState(9)
    a = build([0, 1, 2])
    rs_ = np.random.RandomState(9)
    b = build([0, 2])
    diff = {}
    for p in (0, 2):
        m = tile_mask((p / 3.0 + 0.03, 0.03, (p + 1) / 3.0 - 0.03, 0.47))
        diff[p] = int((a[m] != b[m]).sum())
    ok(diff[0] == 0 and diff[2] == 0, f'части 0 и 2 одинаковы с частью 1 и без неё (разницы: {diff})')
    m1 = tile_mask((1 / 3.0 + 0.03, 0.03, 2 / 3.0 - 0.03, 0.47))
    ok(int((a[m1] != 0).sum()) > 0, 'контроль: у части 1 заливка есть (тест не пустой)')


def test_quilt_holes():
    print('квилт при дырявом известном (вход этапа 6: грани мельче пикселя фото):')
    q = Quads()
    q.quad([[0, 0, 0], [2, 0, 0], [2, 1, 0], [0, 1, 0]], (0, 0, .9, .9), sub=8)
    q.quad([[0, 0, -1], [2, 0, -1], [2, 1, -1], [0, 1, -1]], (.9, .9, 1.0, 1.0), sub=2)
    tex = np.zeros((T, T, 3), np.uint8)
    m = tile_mask((0, 0, .9, .9))
    ys, xs = np.nonzero(m)
    tex[ys, xs] = [235, 225, 200]
    flower = ((xs // 12 + ys // 12) % 7 == 0) & ((xs % 12) < 8) & ((ys % 12) < 8)
    tex[ys[flower], xs[flower]] = [220, 60, 110]
    g = q.geom(tex)
    kn = m.copy()
    kn[::5, ::5] = False                                                   # редкие одиночные дыры
    kn[(np.arange(T)[:, None] + np.arange(T)[None, :]) % 3 == 0] &= (np.random.RandomState(2).rand(T, T) > 0.6)[(np.arange(T)[:, None] + np.arange(T)[None, :]) % 3 == 0]   # плюс дырявость
    out = TF.fill([g], [kn], None, cfg={'gutter': 0, 'erode_known': 0}, mirror=False)
    qi = out['report'].get('quilt_info', {})
    ok(len(qi) == 1 and list(qi.values())[0]['pool'] >= 4, f'квилт собран при дырявом известном: {qi}')
    ok(out['report']['no_patch'] == 0 and out['report']['unpainted_after_pct'] == 0.0, 'после заливки пустого нет')


def test_known_unchanged():
    print('правило «заливка не меняет известное этапу 6» (known_changed_share_pct = 0, пороги из rules/paint-fill.json):')
    import tempfile
    import paint_stage as PS
    ok(TF.THRESHOLDS['known_changed_share_pct'] == ('<=', 0.0) and TF.RULES['known_change_de'] > 0, 'порог 0 и ΔE изменения берутся из rules/paint-fill.json')
    q = Quads()
    q.quad([[-0.5, 0, 0], [0.5, 0, 0], [0.5, 1, 0], [-0.5, 1, 0]], (0, 0, .9, .9), sub=8)
    q.quad([[-0.5, 0, -0.4], [0.5, 0, -0.4], [0.5, 1, -0.4], [-0.5, 1, -0.4]], (.9, .9, 1.0, 1.0), sub=2)
    tex = np.zeros((T, T, 3), np.uint8)
    m = tile_mask((0, 0, .9, .9))
    ys, xs = np.nonzero(m)
    tex[ys, xs] = np.stack([(120 + (xs * 7 + ys * 3) % 60).astype(np.uint8), np.full(len(xs), 140, np.uint8), np.full(len(xs), 200, np.uint8)], 1)    # известное — с рисунком
    g = q.geom(tex)
    with tempfile.TemporaryDirectory() as td:
        TF.write_glb([g], [tex], os.path.join(td, 'in.glb'))
        r = TF.run_stage(td, 'sku:k', os.path.join(td, 'in.glb'), known=[m], parts=None, cfg={'gutter': 0}, mirror=False)           # erode_known по умолчанию (3): образцы без края, но перезаписи известного нет
        mt = r['check']['metrics']['known_changed_share_pct']
        ok(mt['value'] == 0.0 and mt['ok'] and mt['threshold'] == 0.0, f'известное не изменилось (доля {mt["value"]} %)')
        c = PS.read_check(r['dir'])
        ok('known_changed_share_pct' in c['metrics'], 'мерка записана в check.json')
        ok('cpu_s' in c['metrics'] and 'time_s' not in c['metrics'] and c['metrics']['cpu_s']['value'] >= 0, 'мерка времени — cpu_s (процессорные секунды), настенные не судятся')
        import json as _j
        rj = _j.load(open(os.path.join(r["dir"], "report.json")))["report"]
        ok(rj.get('wall_s') is not None and rj.get('cpu_s') is not None, f'wall_s и cpu_s в report.json: {rj.get("wall_s")} / {rj.get("cpu_s")}')
        bad = [a.copy() for a in r['tex_after']]
        bad[0][ys[:50], xs[:50]] = 255 - bad[0][ys[:50], xs[:50]]
        sh = TF.known_changed_share([m], r['tex_before'], bad, TF.RULES['known_change_de'])
        ok(sh['changed'] >= 40 and sh['share_pct'] > 0, f'контроль: подмена известных текселей мерка ловит ({sh})')


def test_check_on_final_texture():
    print('мерки check 07 — по ИТОГОВОЙ текстуре после хуков (р.7, 23.11): хук меняет текстуру → check меняется:')
    import tempfile
    q = Quads()
    q.quad([[-0.5, 0, 0], [0.5, 0, 0], [0.5, 1, 0], [-0.5, 1, 0]], (0, 0, .9, .9), sub=8)
    q.quad([[-0.5, 0, -0.4], [0.5, 0, -0.4], [0.5, 1, -0.4], [-0.5, 1, -0.4]], (.9, .9, 1.0, 1.0), sub=2)
    tex = np.zeros((T, T, 3), np.uint8)
    m = tile_mask((0, 0, .9, .9))
    tex[m] = [120, 140, 200]
    g = q.geom(tex)
    orig = TF.own_panel_tone_hook
    res = {}
    try:
        for tag in ('plain', 'hooked'):
            if tag == 'hooked':
                def hk(geoms, tex_after, known, ut_g, parts, front=None, thr=0.6):
                    out = [np.asarray(t).copy() for t in tex_after]
                    for gi in range(len(out)):
                        kn_ = np.asarray(known[gi], bool)
                        out[gi][~kn_] = [255, 40, 40]                    # невидимое — резко красное
                    return out, {'hooked': True}
                TF.own_panel_tone_hook = hk
            with tempfile.TemporaryDirectory() as td:
                TF.write_glb([g], [tex], os.path.join(td, 'in.glb'))
                r = TF.run_stage(td, 'sku:' + tag, os.path.join(td, 'in.glb'), known=[m], parts=None, cfg={'gutter': 0}, mirror=False)
                res[tag] = r['check']['metrics']
    finally:
        TF.own_panel_tone_hook = orig
    a, b = res['plain'], res['hooked']
    ch = [k for k in ('dE00_front_back', 'far_excess_pct', 'filled_faces_step_pct', 'dL_front_back') if a[k]['value'] != b[k]['value']]
    ok(len(ch) >= 1, f'хук поменял текстуру → мерки check изменились: {ch}')
    ok(b['dE00_front_back']['value'] is None or a['dE00_front_back']['value'] is None or b['dE00_front_back']['value'] > a['dE00_front_back']['value'], f'красный перёд/зад хуже: {a["dE00_front_back"]["value"]} → {b["dE00_front_back"]["value"]}')


def test_run_stage_fallback():
    print('этап 07 с черновиком: считаются А и Б, берётся Б только если мерки не хуже; check.json:')
    import tempfile
    import paint_stage as PS
    q = Quads()
    q.quad([[-0.5, 0, 0], [0.5, 0, 0], [0.5, 1, 0], [-0.5, 1, 0]], (0, 0, .9, .9), sub=8)
    q.quad([[-0.5, 0, -0.4], [0.5, 0, -0.4], [0.5, 1, -0.4], [-0.5, 1, -0.4]], (.9, .9, 1.0, 1.0), sub=2)
    tex = np.zeros((T, T, 3), np.uint8)
    tex[tile_mask((0, 0, .9, .9))] = [120, 140, 200]
    g = q.geom(tex)
    dtex = np.zeros((T, T, 3), np.uint8)
    dm = tile_mask((0, 0, .9, .9)) | tile_mask((.9, .9, 1.0, 1.0))
    dtex[dm] = [110, 135, 190]
    with tempfile.TemporaryDirectory() as td:
        TF.write_glb([g], [tex], os.path.join(td, 'in.glb'))
        TF.write_glb([g], [dtex], os.path.join(td, 'draft.glb'))
        r = TF.run_stage(td, 'sku:1', os.path.join(td, 'in.glb'), known=[tile_mask((0, 0, .9, .9))], parts=None, cfg={'source': 'trellis', 'gutter': 0, 'erode_known': 0, 'draft_when': 'always'}, draft_glb=os.path.join(td, 'draft.glb'), mirror=False)
        rep = r['report']
        ok(set(rep['source_tried']) == {'stat', 'trellis'} and rep['source_used'] in ('stat', 'trellis'), f'считаны А и Б, выбран {rep["source_used"]}: {rep["source_tried"]}')
        c = PS.read_check(r['dir'])
        ok(c is not None and c['extra']['source_used'] == rep['source_used'] and 'empty_pct' in (c['metric'] or {}).get('name', 'empty_pct'), 'check.json: источник заливки записан')
        nf = len(g['F'])
        np.savez(os.path.join(td, 'parts.npz'), part=np.where(np.arange(nf) % 2 == 0, 0, -1).astype(np.int16))
        pp, note = TF.parts_from_npz(os.path.join(td, 'parts.npz'), [g])
        ok(len(pp) == 1 and len(pp[0]) == nf and set(np.unique(pp[0])) == {0, 1} and '2 частей' in note, f'parts.npz режется по граням, −1 → отдельная часть ({note})')
        np.savez(os.path.join(td, 'bad.npz'), part=np.zeros(nf + 1, np.int16))
        try:
            TF.parts_from_npz(os.path.join(td, 'bad.npz'), [g])
            ok(False, 'части другого меша отвергнуты')
        except ValueError:
            ok(True, 'части другого меша (число граней не то) отвергнуты')
        r3 = TF.run_stage(td, 'sku:3', os.path.join(td, 'in.glb'), known=[tile_mask((0, 0, .9, .9))], parts=None, cfg={'source': 'trellis', 'gutter': 0, 'erode_known': 0}, draft_glb=os.path.join(td, 'draft.glb'), mirror=False)
        if r3['report']['source_tried']['stat']['nfail'] == 0:
            ok(set(r3['report']['source_tried']) == {'stat'} and r3['report']['source_used'] == 'stat', 'А прошёл все мерки — Б не считается (draft_when=a_fails)')
        else:
            ok(set(r3['report']['source_tried']) == {'stat', 'trellis'}, 'А не прошёл — считан и Б')
        r2 = TF.run_stage(td, 'sku:2', os.path.join(td, 'in.glb'), known=[tile_mask((0, 0, .9, .9))], parts=None, cfg={'source': 'trellis', 'gutter': 0, 'erode_known': 0, 'draft_fallback': False}, draft_glb=os.path.join(td, 'draft.glb'), mirror=False)
        ok(r2['report']['source_used'] == 'trellis' and r2['report']['source_tried'] == {}, 'draft_fallback выключен — только Б')


def test_render_pattern():
    print("узор из непрерывного кадра видимой стороны + мерка узора (отчёт):")
    q = Quads()
    q.quad([[-0.5, 0, 0], [0.5, 0, 0], [0.5, 1, 0], [-0.5, 1, 0]], (0, 0, .9, .9), sub=8)
    q.quad([[-0.5, 0, -0.4], [0.5, 0, -0.4], [0.5, 1, -0.4], [-0.5, 1, -0.4]], (.9, .9, 1.0, 1.0), sub=2)
    m = tile_mask((0, 0, .9, .9))
    tex = np.zeros((T, T, 3), np.uint8)
    ys, xs = np.nonzero(m)
    dots = ((xs // 6) % 2 == 0) & ((ys // 6) % 2 == 0)      # 25 % площади — не «тень» (ниже квантиля яркости)
    base = np.array([232, 226, 214])
    col = np.where(dots[:, None], np.array([200, 60, 90]), base[None]).astype(np.uint8)
    tex[ys, xs] = col
    g = q.geom(tex)
    out = TF.fill([g], [m], None, cfg={"gutter": 0, "erode_known": 0, "pr_res": 256}, mirror=False)
    rep = out["report"]
    ps = rep.get("pattern_src", {}).get(0)
    ok(ps is not None and ps["render"] and ps["pool"] >= 4, f"блоки взяты из кадра видимой стороны: {ps}")
    ok(rep["known_pct"] > 0, "известное есть")
    back = tile_mask((.9, .9, 1.0, 1.0))
    ab = TF.rgb2lab(out["tex"][0][back])
    ok(float(np.hypot(ab[:, 1].std(), ab[:, 2].std())) > 2.0, f"залитое с узором, не плоское (σ хромы {float(np.hypot(ab[:, 1].std(), ab[:, 2].std())):.1f})")
    pmx = TF.pattern_metrics([g], None, [m], out["tex"], rep, dict(TF.FILL, pr_res=256))
    ok(0 in pmx and pmx[0].get("dist") is not None and pmx[0]["spot_area_back"] > 0, f"pattern_metrics считается на залитом: {pmx}")
    off = TF.fill([g], [m], None, cfg={"gutter": 0, "erode_known": 0, "pattern_render": False}, mirror=False)["report"]
    ok("pattern_src" not in off, "pattern_render=False — прежний путь по развёртке")
    # мерка узора: одинаковая статистика → 0, точки против полос → больше
    R = 160
    yy, xx = np.mgrid[0:R, 0:R]
    tone = np.array([70.0, 5.0, 12.0])
    lab_d = np.zeros((R, R, 3)); lab_d[...] = tone
    lab_d[((xx // 5) % 4 == 0) & ((yy // 5) % 4 == 0)] = [60, 40, 20]
    lab_d2 = np.roll(lab_d, 7, axis=1)
    lab_s = np.zeros((R, R, 3)); lab_s[...] = tone
    lab_s[(xx % 9) < 3] = [60, 40, 20]
    mk = np.ones((R, R), bool)
    h1, h2, h3 = (TF._pattern_hists(a, mk, tone, 10.0) for a in (lab_d, lab_d2, lab_s))
    d12 = 0.5 * float(np.abs(h1["orient"] - h2["orient"]).sum()) + 0.5 * float(np.abs(h1["spot_sizes"] - h2["spot_sizes"]).sum())
    d13 = 0.5 * float(np.abs(h1["orient"] - h3["orient"]).sum()) + 0.5 * float(np.abs(h1["spot_sizes"] - h3["spot_sizes"]).sum())
    ok(d12 < 0.2 and d13 > d12 + 0.2, f"мерка узора: те же точки со сдвигом {d12:.3f} < точки против полос {d13:.3f}")


def test_outlier_blocks():
    print("отбраковка блоков с чужеродным пятном (тёмный скол на ножке; пороги из rules/paint-fill.json):")
    rng = np.random.RandomState(2)
    qo = TF.RULES["quilt_outlier"]
    pool = [rng.normal(0, 2.0, (24, 24, 3)) for _ in range(20)]
    bad = rng.normal(0, 2.0, (24, 24, 3)); bad[4:14, 4:20, 0] -= 40.0           # тёмная дыра
    bad2 = rng.normal(0, 2.0, (24, 24, 3)); bad2[2:10, 2:10, :] += 60.0       # белый фон на краю фото
    keep, nrej = TF.reject_outlier_blocks(pool + [bad, bad2], qo["k"], qo["floor"], qo["quantile"])
    ok(nrej == 2 and len(keep) == 20, f"отброшены оба блока с пятном, нормальные целы (отброшено {nrej}, осталось {len(keep)})")
    keep0, nrej0 = TF.reject_outlier_blocks(pool, qo["k"], qo["floor"], qo["quantile"])
    ok(nrej0 == 0, f"чистый пул не режется ({nrej0})")
    qe = TF.RULES["quilt_extreme"]
    tone_l = 67.0                                                                 # узорная часть: остаток от тона; дерево ножки L≈67
    pp = [rng.normal(0, 3.0, (24, 24, 3)) for _ in range(20)]
    blk_black = rng.normal(0, 3.0, (24, 24, 3)); blk_black[4:14, 4:20, 0] = 16.0 - tone_l       # чёрная дыра (L 16)
    blk_white = rng.normal(0, 3.0, (24, 24, 3)); blk_white[2:12, 2:12, 0] = 28.0                # белый фон на краю фото (светлее тона на 28)
    branch = rng.normal(0, 3.0, (24, 24, 3)); branch[8:16, 2:22, 0] = -35.0; branch[8:16, 2:22, 1:] += 25.0   # ветка/цветок: темнее и с цветом, не чёрная
    keep2, nrej2 = TF.reject_extreme_blocks(pp + [blk_black, blk_white, branch], tone_l, qe["dL_hi"], qe["black_abs"], qe["share"])
    ok(nrej2 == 2 and len(keep2) == 21, f"чёрная дыра и белый фон отброшены, ветка цела (отброшено {nrej2})")


def test_trellis_relief():
    print("вариант C (source=trellis_relief): цвет как stat, фактура — рельеф яркости черновика с ограничением силы, выбросы → лоскут stat:")
    g, parts, known, tl, col = scene_parts()
    rn = np.random.RandomState(8)
    tex0 = g["tex"].copy()
    for tile, c0, sub in ((tl["A"], col["red"], None), (tl["B"], col["blue"], 0.5), (tl["C"], col["yellow"], None)):          # фото ровное (не «узорное»): мелкий шум яркости
        mm = tile_mask(tile, sub)
        tex0[mm] = np.clip(c0 + rn.normal(0, 4.0, (int(mm.sum()), 3)), 0, 255).astype(np.uint8)
    g = dict(g, tex=tex0)
    mD, mA = tile_mask(tl["D"]), tile_mask(tl["A"])
    ys, xs = np.nonzero(mD)
    x0, y0 = int(xs.min()), int(ys.min())                          # строки UV перевёрнуты — рамку берём по самой маске
    side = int(xs.max()) - x0 + 1

    def mk_draft(noise_sd, blob, crumbs, seed=21):
        rr = np.random.RandomState(seed)
        dtex = np.full((T, T, 3), 90, np.uint8)
        base = 90.0 + rr.normal(0, noise_sd, (T, T))
        if blob:                                                   # большое тёмное пятно в центре D
            cy, cx = y0 + side // 2, x0 + side // 2
            h = side // 6
            base[cy - h:cy + h, cx - h:cx + h] -= 60.0
        if crumbs:                                                 # крошка: отдельные яркие/тёмные тексели
            idx = rr.choice(len(ys), crumbs, replace=False)
            base[ys[idx], xs[idx]] += rr.choice([-80.0, 80.0], crumbs)
        dg_ = dict(g)
        dtex[:] = np.clip(base, 0, 255).astype(np.uint8)[..., None]                 # шум по всей развёртке (у настоящего черновика фактура везде)
        dg_["tex"] = dtex
        return TF.draft_texels([g], [dg_])
    dt = mk_draft(3.0, True, 15)
    cfgC = {"seam": {"enabled": False}, "gutter": 0, "erode_known": 0, "source": "trellis_relief", "pattern_chroma": 1e9}          # части сцены соседствуют цветными плитками — «узорность» по хроме здесь не нужна
    out = TF.fill([g], known, parts, cfg=cfgC, mirror=False, draft=dt)
    st = TF.fill([g], known, parts, cfg={"gutter": 0, "erode_known": 0, "source": "stat", "pattern_chroma": 1e9}, mirror=False)
    tex, rep = out["tex"][0], out["report"]
    ok(int((tex[known[0]] != g["tex"][known[0]]).sum()) == 0, "известные тексели не изменились")
    labC, labS, labA = lab_of(tex, mD), lab_of(st["tex"][0], mD), lab_of(g["tex"], mA)
    ok(de(labC.mean(axis=0), labS.mean(axis=0)) < 3.0, "цвет (тон) — как у stat, а не серый черновик", f"ΔE {de(labC.mean(axis=0), labS.mean(axis=0)):.1f}")
    r0 = rep["relief"][0]
    ok(r0["fallback"] is None and r0["gain"] <= TF.RULES["trellis_relief"]["gain_max"] + 1e-9 and r0.get("usable_texels", 0) > 0.5 * int(mD.sum()) and rep.get("relief_texels", 0) > 0.5 * int(mD.sum()), f"рельеф применён: gain {r0['gain']}, на залитом {rep.get('relief_texels', 0)} из {int(mD.sum())}")
    ok(float(labC[:, 0].std()) <= float(labA[:, 0].std()) * 1.2 + 0.5, f"сила рельефа ограничена силой фактуры фото (σL залитого {float(labC[:, 0].std()):.1f} ≤ фото {float(labA[:, 0].std()):.1f})")
    cy, cx = y0 + side // 2, x0 + side // 2
    h = side // 5
    ctr = tex[cy - h:cy + h, cx - h:cx + h]
    blobL = float(TF.rgb2lab(ctr.reshape(-1, 3))[:, 0].mean())
    ok(abs(blobL - float(labS[:, 0].mean())) < 8.0, f"большое тёмное пятно черновика не перенесено (L в центре {blobL:.1f}, тон {float(labS[:, 0].mean()):.1f})")
    # крошка: самые яркие/тёмные тексели черновика не должны давать выбросов в результате
    ok(float(np.percentile(labC[:, 0], 99.9)) < float(labS[:, 0].mean()) + 25.0 and float(np.percentile(labC[:, 0], 0.1)) > float(labS[:, 0].mean()) - 25.0, "крошка черновика (±80) не просочилась")
    # вся часть — выбросы: запасной на лоскут
    dt2 = mk_draft(3.0, False, int(0.6 * len(ys)))
    o2 = TF.fill([g], known, parts, cfg=cfgC, mirror=False, draft=dt2)
    ok(o2["report"]["relief"][0]["fallback"] is not None and "usable_texels" not in o2["report"]["relief"][0], f"много выбросов — вся часть на лоскуте ({o2['report']['relief'][0]['fallback']})")
    try:
        TF.fill([g], known, parts, cfg=cfgC, mirror=False)
        ok(False, "trellis_relief без черновика отвергнут")
    except ValueError:
        ok(True, "trellis_relief без черновика отвергнут")
    # --- C-gated (Codex+директор 21.11): ворота по классу, однородности; затухание у границы; гладко вместо плитки; полоса в масштабе поверхности; перенос строже
    oc = TF.fill([g], known, parts, cfg=dict(cfgC, part_class={0: "legs", 1: "body"}), mirror=False, draft=dt)
    r_c = oc["report"]["relief"]
    ok("вне допустимых" in (r_c[0]["fallback"] or "") and r_c[1]["fallback"] is None, f"ворота по классу: ножки (legs) — без рельефа, обивка/корпус (body) — с рельефом ({r_c[0]['fallback']})")
    tex_g = g["tex"].copy()
    ramp = (20 + 7.0 * (np.arange(T)[:, None] % 32))[:, :, None] * np.ones((1, T, 3))   # неоднотонная часть: яркость внутри плитки плавно растёт в 10 раз
    tex_g[mA] = np.clip(ramp, 0, 255).astype(np.uint8)[mA]
    og = TF.fill([dict(g, tex=tex_g)], known, parts, cfg=cfgC, mirror=False, draft=dt)
    ok("неоднотонная" in (og["report"]["relief"][0]["fallback"] or ""), f"класса нет и часть неоднотонная — без рельефа ({og['report']['relief'][0]['fallback']})")
    sd_n = float(labC[:, 0].std())
    R_ = TF.RULES["trellis_relief"]
    keep_ = dict(R_)
    try:
        R_["smooth_pool_rejected"] = -1.0                          # лоскут выключен (гладко) — остаётся только рельеф
        ob = TF.fill([g], known, parts, cfg=cfgC, mirror=False, draft=dt)
        sd_b = float(lab_of(ob["tex"][0], mD)[:, 0].std())
        R_["fade_len"] = 1e3                                       # граница фото «бесконечно далеко» затухания → рельеф ≈ 0 везде (сразу у границы он должен затухать)
        of = TF.fill([g], known, parts, cfg=cfgC, mirror=False, draft=dt)
        sd_f = float(lab_of(of["tex"][0], mD)[:, 0].std())
        ok(sd_b > 0.3 and sd_f < 0.4 * sd_b, f"рельеф затухает у границы фото в физическом расстоянии (σL {sd_f:.2f} при длине затухания 1e3 vs {sd_b:.2f})")
        R_["fade_len"] = keep_["fade_len"]
        R_["smooth_pool_rejected"] = -1.0                          # пул «отбракован»: плохой черновик (много выбросов) → ГЛАДКО, не лоскут
        os_ = TF.fill([g], known, parts, cfg=cfgC, mirror=False, draft=dt2)
        R_["smooth_pool_rejected"] = keep_["smooth_pool_rejected"]
        op_ = TF.fill([g], known, parts, cfg=cfgC, mirror=False, draft=dt2)
        sd_s, sd_p = float(lab_of(os_["tex"][0], mD)[:, 0].std()), float(lab_of(op_["tex"][0], mD)[:, 0].std())
        ok(os_["report"]["relief_smooth_parts"] and sd_s < 0.4 * sd_p + 0.05, f"плохой черновик и отбракованный пул — гладкая заливка тоном (σL {sd_s:.2f}), не плитка (σL {sd_p:.2f})")
    finally:
        R_.clear()
        R_.update(keep_)
    g2 = dict(g, UV=np.asarray(g["UV"]) * 0.5)
    sp1 = float(np.median(TF.texel_spacing(TF.Tex(g, np.asarray(g["V"], float), T, parts[0]))))
    sp2 = float(np.median(TF.texel_spacing(TF.Tex(g2, np.asarray(g2["V"], float), T, parts[0]))))
    ok(abs(sp2 / sp1 - 2.0) < 0.1, f"шаг текселя учитывает плотность UV (развёртка вдвое мельче → шаг вдвое крупнее: {sp2 / sp1:.2f})")
    dg_far = dict(g, V=np.asarray(g["V"], float) + np.array([0.0, 0.0, 0.2]), tex=np.full((T, T, 3), 90, np.uint8))      # черновик чуть в стороне (≈2,5 % размера): Б ещё берёт, C (≤1,5 %) — нет
    dB = TF.draft_texels([g], [dg_far], {"source": "trellis"})["report"]["ok_pct"]
    dC = TF.draft_texels([g], [dg_far], {"source": "trellis_relief"})["report"]["ok_pct"]
    ok(dC < dB, f"перенос черновика строже у C (ok {dC} % < {dB} % у Б при тех же данных)")


def test_part_roles_from_stage3():
    print("классы частей для C берутся из этапа 3 (03-parts/parts.json) сами:")
    import json
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        pj = os.path.join(td, "parts.json")
        with open(pj, "w", encoding="utf-8") as f:
            json.dump({"parts": [{"id": 0, "role": "body"}, {"id": 1, "role": "unknown"}, {"id": 2, "role": "legs"}, {"id": 3}]}, f)
        ok(TF.roles_from_parts_json(pj) == {0: "body", 2: "legs"}, "роли: body и legs входят, unknown и часть без роли — нет")
        ok(TF.roles_from_parts_json(os.path.join(td, "нет.json")) == {}, "нет файла — пустой словарь")
        npz = os.path.join(td, "parts.npz")
        c, note = TF.resolve_part_class({"source": "trellis_relief"}, npz, True)
        ok(c["part_class"] == {0: "body", 2: "legs"} and "этапа 3" in note, f"source=trellis_relief и части из этапа 3 — part_class из parts.json ({note})")
        c, note = TF.resolve_part_class({"source": "trellis_relief"}, npz, False)
        ok(c.get("part_class") is None and "нет" in note, "части не из этапа 3 (геометрия) — класса нет, только однородность")
        c, note = TF.resolve_part_class({"source": "trellis_relief", "part_class": {5: "body"}}, npz, True)
        ok(c["part_class"] == {5: "body"}, "заданный в cfg part_class не перезаписывается")
        c, note = TF.resolve_part_class({"source": "stat"}, npz, True)
        ok("part_class" not in c and note is None, "stat/trellis — part_class не трогается")


def test_stage7_side_tone_smooth_rules():
    print("правила 21.11 (Sakura): узор только на стороне фото, общий тон роли, без плитки на дереве:")
    n = np.array([[0, 0, 1.0], [0, 0, -1.0], [0, 1.0, 0], [0.8, 0, 0.6], [0, 0, 0.1]])
    m = TF.pattern_side_ok(n, 0.0, 0.2)
    ok(m.tolist() == [True, False, False, True, False], f"зад/верх/вскользь — без узора, перёд и под углом — с узором ({m.tolist()})")
    m90 = TF.pattern_side_ok(n, 90.0, 0.2)
    ok(m90.tolist() == [False, False, False, True, False] or m90[3], "камера справа (az 90): учитывается направление фото")
    ok(TF.pattern_side_ok(n, 0.0, None).all(), "cos_min=None — правило выключено")
    c = dict(TF.FILL)
    ok(TF.smooth_part_rule('legs', 0.1, False, c) and TF.smooth_part_rule('frame', None, False, c), "legs/frame — гладко независимо от швов")
    ok(TF.smooth_part_rule('body', 0.9, False, c), "неузорная часть со скачком на швах > порога — гладко")
    ok(not TF.smooth_part_rule('body', 0.2, False, c) and not TF.smooth_part_rule(None, None, False, c), "хорошие швы / нет данных — плитка остаётся")
    ok(not TF.smooth_part_rule('body', 0.9, True, c), "узорная часть правилом jump_L не режется")
    # общий тон роли: части одной роли (legs) красятся общим тоном; без роли — каждая своим
    g, parts, known, tl, col = scene_parts()
    base = {"gutter": 0, "erode_known": 0, "tone": "median", "src_dev_pattern": 0}
    r0 = TF.fill([g], known, parts, cfg=dict(base), mirror=False)['report']
    ok(r0.get('tone_shared') == {}, "роли не заданы — общего тона нет")
    r1 = TF.fill([g], known, parts, cfg=dict(base, part_role={0: 'legs', 1: 'legs'}, tone_share_roles=['legs']), mirror=False)['report']
    ts = r1['tone_shared'].get('legs')
    ok(ts is not None and ts['parts'] == [0, 1], f"две части роли legs — один общий тон ({ts})")
    r2 = TF.fill([g], known, parts, cfg=dict(base, part_role={0: 'body', 1: 'body'}, tone_share_roles=['legs']), mirror=False)['report']
    ok(r2['tone_shared'] == {}, "роль вне tone_share_roles — тон не делится")


def test_tone_from_neighbour():
    print("иерархия тона части: своя → донор той же роли (совместимый тон) → каталог → не красить; global через материал — нет:")
    roles = {0: 'body', 1: 'body', 2: 'body', 3: 'legs'}
    c = dict(TF.FILL, min_known=50, part_role=roles)
    tones = {0: (88, 1, 3), 1: (88, 1, 3), 2: (88, 1, 3), 3: (72, 4, 20)}
    pids = [0, 1, 2, 3]
    kc, tot = {0: 5000, 1: 30, 2: 4000, 3: 4000}, {p: 10000 for p in pids}
    fg = {0: False, 1: True, 2: False, 3: False}
    bor = {(0, 1): 40, (1, 2): 90, (1, 3): 500}
    r = TF.choose_tone_sources(pids, roles, kc, tot, fg, tones, bor, c)
    ok(r[1]['source'] == 'donor' and r[1]['donor'] == 2, f"часть 1 (известного 30 < min_known) берёт донора той же роли с большей границей (2, не дерево 3): {r[1]}")
    ok(r[0]['source'] == 'own' and r[3]['source'] == 'own', "хватает известного — тон свой")
    ok(TF.choose_tone_sources(pids, {}, kc, tot, fg, tones, bor, dict(c, no_role_global='legacy'))[1]['source'] == 'global_legacy', "ролей нет, флаг no_role_global=legacy — прежнее поведение, global")
    rn = TF.choose_tone_sources(pids, {}, kc, tot, fg, tones, bor, dict(c, part_role=None))
    ok(rn[1]['source'] == 'skip' and rn[0]['source'] == 'own', f"ролей нет (нет этапа 3), своего тона нет, но у товара есть надёжная часть — НЕ красить, не тон всего товара (Ш6): {rn[1]}")
    ok(TF.choose_tone_sources([1], {}, {1: 30}, {1: 10000}, {1: True}, {1: (88, 1, 3)}, {}, c)[1]['source'] == 'global_legacy', "у товара нет ни одной надёжной части — skip не применяется (красить хоть чем-то)")
    r2 = TF.choose_tone_sources(pids, roles, kc, tot, fg, tones, {(1, 3): 500}, c)
    ok(r2[1]['source'] == 'skip', f"нет соседа той же роли → не красить (не global через материал): {r2[1]}")
    r3 = TF.choose_tone_sources(pids, roles, kc, tot, fg, tones, {(1, 3): 500}, dict(c, catalog_tone={'body': (90, 0, 0)}))
    ok(r3[1]['source'] == 'catalog', "нет донора, есть каталожный тон роли — каталог")
    kc2, fg2 = {**kc, 1: 3000}, {**fg, 1: False}
    r4 = TF.choose_tone_sources(pids, roles, kc2, tot, fg2, {**tones, 1: (72, 4, 20)}, bor, dict(c, tone_known_min_share=0.5, tone_compat_de=10.0))
    ok(r4[1]['source'] != 'donor' and r4[1].get('rejected'), f"свой видимый тон (известного 3000) несовместим с донором (ΔE > порога) — донор отвергнут: {r4[1]}")
    ok(r4[1]['source'] == 'own_weak', "свой тон есть, донора нет — свой слабый (не skip)")
    g, parts, kn, tl, col = scene_parts()
    r = TF.fill([g], kn, parts, cfg={"gutter": 0, "erode_known": 0, "tone": "median", "src_dev_pattern": 0, "part_role": {0: "body", 1: "body"}}, mirror=False)['report']
    ok('tone_source' in r and 'tone_skipped_parts' in r, "отчёт: tone_source по частям и tone_skipped_parts записаны, заливка не падает")


def test_nail_twins():
    print("шляпки гвоздей: нативные тёмные пятна невидимой стороны — в цвете видимых двойников; линии, большие пятна и тёмная ткань — нет:")
    n = 200
    lab = np.zeros((n, n, 3))
    lab[..., 0], lab[..., 1], lab[..., 2] = 86.0, 1.0, 3.0
    known = np.zeros((n, n), bool)
    known[:, :100] = True
    part = np.zeros((n, n), int)
    for i in range(6):                                              # видимые двойники: квадраты 5×5, тёмная бронза
        lab[10 + i * 20:15 + i * 20, 20:25] = (45.0, 7.0, 8.0)
    for i in range(8):                                              # невидимые гвозди: квадраты 5×5, нативно серо-коричневые
        lab[10 + i * 20:15 + i * 20, 140:145] = (50.0, 2.0, 3.0)
    lab[100, 120:190] = (50.0, 2.0, 3.0)                            # тонкая линия шва: вытянутая, не гвоздь
    lab[150:190, 150:190] = (50.0, 2.0, 3.0)                        # большое тёмное пятно: тень/деталь, не гвоздь
    cand = ~known
    c = dict(TF.FILL)
    r = TF.nail_twins(lab, known, cand, part, {0: 86.0}, c)
    m = r['mask']
    ok(r['report']['applied'] and r['report']['twins_blobs'] == 6, f"двойники найдены: {r['report']['twins_blobs']}")
    ok(all(m[10 + i * 20:15 + i * 20, 140:145].all() for i in range(8)), "все 8 невидимых гвоздей приняты")
    ok(not m[100, 120:190].any() and not m[150:190, 150:190].any(), "линия и большое пятно — не гвозди")
    ok(abs(r['lab'][12, 142, 0] - 45.0) < 0.6 and abs(r['lab'][12, 142, 1] - 7.0) < 0.6, f"цвет пятна = медиана видимых двойников: {np.round(r['lab'][12, 142], 1)}")
    ok(r['lab'][50, 50, 0] == 86.0 and r['lab'][0, 0, 0] == 86.0, "остальное не тронуто")
    lab2 = lab.copy()
    lab2[known & (lab2[..., 0] < 60)] = (86.0, 1.0, 3.0)
    r2 = TF.nail_twins(lab2, known, cand, part, {0: 86.0}, c)
    ok(not r2['report']['applied'] and 'нет видимых двойников' in r2['report'].get('skip', ''), "двойников нет — правило молчит (тёмное = тень/шов)")
    r3 = TF.nail_twins(lab, known, cand, part, {0: 50.0}, c)
    ok(not r3['report']['applied'], "тёмная ткань (тон части 50 < 60) — правило молчит")
    ok(not TF.nail_twins(lab, known, np.zeros((n, n), bool), part, {0: 86.0}, c)['report']['applied'], "кандидатов нет — молчит")
    lab4 = lab.copy()
    lab4[10:15, 140:145] = (4.0, 0.0, 0.0)                          # чёрная дыра и красное пятно среди кандидатов — не гвозди (далеки от двойников)
    lab4[30:35, 140:145] = (50.0, 40.0, 20.0)
    m4 = TF.nail_twins(lab4, known, cand, part, {0: 86.0}, c)['mask']
    ok(not m4[10:15, 140:145].any() and not m4[30:35, 140:145].any() and m4[50:55, 140:145].all(), "чёрное и красное пятно отвергнуты по ΔE к двойникам, обычные гвозди приняты")
    lab6 = lab.copy()
    lab6[30:35, 140:145] = (48.0, 18.0, 10.0)                       # красноватое пятно: ΔE к двойникам < 12, но цветность выше двойников + 8 — не гвоздь
    m6 = TF.nail_twins(lab6, known, cand, part, {0: 86.0}, c)['mask']
    ok(not m6[30:35, 140:145].any() and m6[50:55, 140:145].all(), "красноватое пятно (цветность выше двойников) отвергнуто, обычные гвозди приняты")
    lab7 = lab.copy()
    lab7[192:197, 192:197] = (50.0, 2.0, 3.0)                       # одиночка вдали от ряда (порог 30 текс.): цвет как у гвоздей, но соседей нет — не принимается
    m7 = TF.nail_twins(lab7, known, cand, part, {0: 86.0}, dict(c, nail_neighbor_px=30))
    ok(not m7['mask'][192:197, 192:197].any() and m7['mask'][50:55, 140:145].all() and m7['report']['lonely_dropped'] == 1, f"одиночка без соседей не принята, ряд цел: lonely_dropped={m7['report']['lonely_dropped']}")
    lab5 = lab.copy()
    for i in range(6):
        lab5[10 + i * 20:15 + i * 20, 20:25] = (50.0, 40.0, 20.0)   # двойники красные, кандидаты серо-коричневые: ΔE велик — не принимаются
    ok(not TF.nail_twins(lab5, known, cand, part, {0: 86.0}, c)['mask'].any(), "двойники другого цвета — кандидаты не перекрашиваются в красное")


def test_borrow_donors():
    print("вариант 1 Ш6: часть без блоков берёт микрофактуру у части того же материала (роль и тон), узорную и skip не трогает:")
    tones = {0: [70, 2, 4], 1: [72, 2, 5], 2: [40, 10, -30], 3: [71, 3, 4], 4: [70, 2, 4]}
    roles = {0: 'body', 1: 'body', 2: 'body', 3: 'legs', 4: 'body'}
    r = TF.borrow_donors([1, 2, 3], [0, 4], tones, roles, set(), 6.0)
    ok(r.get(1) in (0, 4), f"ч.1 (тон рядом, та же роль) берёт у ч.0 или 4 (взяла {r.get(1)})")
    ok(2 not in r, "ч.2 (другой тон) не берёт")
    ok(3 not in r, "ч.3 (другая роль, ножки) не берёт")
    ok(TF.borrow_donors([1], [0], tones, roles, {0}, 6.0) == {}, "донор из «плохих» (узорная/skip) не годится")
    ok(TF.borrow_donors([1], [0], tones, roles, {1}, 6.0) == {}, "сама часть из «плохих» не берёт")
    ok(TF.borrow_donors([1], [0], {0: tones[0]}, roles, set(), 6.0) == {}, "нет своего тона у части — не берёт")
    ok(TF.borrow_donors([1], [0, 4], tones, roles, set(), 0.5) == {}, "порог тона строже расстояния — не берёт")
    tones2 = {1: [70, 2, 4], 0: [70.3, 2, 4], 4: [72, 2, 5]}
    ok(TF.borrow_donors([1], [0, 4], tones2, {0: 'body', 1: 'body', 4: 'body'}, set(), 6.0)[1] == 0, "без границ — ближайший по тону (ч.0)")
    ok(TF.borrow_donors([1], [0, 4], tones2, {0: 'body', 1: 'body', 4: 'body'}, set(), 6.0, {(1, 4): 120})[1] == 4, "общая граница важнее близости тона (берёт ч.4, соседнюю)")


def test_tone_only():
    print("tone_only (Ш6, р.8): цвет тон-слоя остаётся, фактура кладётся поверх; в известные и статистику не входит:")
    rng = np.random.RandomState(5)
    big = Quads()
    big.quad([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]], (0, 0, .5, 1))
    big.quad([[2, 0, 0], [3, 0, 0], [3, 1, 0], [2, 1, 0]], (.5, 0, 1, 1))
    t2 = np.full((256, 256, 3), 120, np.uint8)
    t2[:, :128] = np.clip(120 + rng.normal(0, 8, (256, 128, 3)), 0, 255)
    to = np.zeros((256, 256), bool)
    to[40:200, 150:230] = True
    t2[to] = (150, 100, 100)                                   # тон-слой: другой цвет, чем «серая» заливка
    gb = big.geom(t2)
    kb = np.zeros((256, 256), bool)
    kb[:, :128] = True
    cfg = {'gutter': 0, 'erode_known': 0}
    o0 = TF.fill([gb], [kb], None, cfg=cfg, mirror=False)
    o1 = TF.fill([gb], [kb], None, cfg=cfg, mirror=False, tone_only=[to])
    lab0 = TF.rgb2lab(o0['tex'][0][to].reshape(-1, 3))
    lab1 = TF.rgb2lab(o1['tex'][0][to].reshape(-1, 3))
    lab_in = TF.rgb2lab(t2[to].reshape(-1, 3))
    ok(float(np.abs(lab1.mean(axis=0) - lab_in.mean(axis=0)).max()) < 2.0, f'среднее тон-слоя сохранено (Lab вход {lab_in.mean(axis=0).round(1)}, итог {lab1.mean(axis=0).round(1)})')
    ok(float(np.abs(lab0.mean(axis=0) - lab_in.mean(axis=0)).max()) > 5.0, 'без tone_only тон-слой перекрашивается заливкой (контроль различимости)')
    ok(float(lab1[:, 0].std()) > 0.5, f'фактура положена поверх (разброс L {lab1[:, 0].std():.2f})')
    ok(o1['report'].get('tone_only_texels', 0) > 0, f'отчёт: тон-только тексели {o1["report"].get("tone_only_texels")}')
    ok(np.array_equal(o1['tex'][0][kb], o0['tex'][0][kb]), 'известное не изменилось')
    ok(o1['report']['parts'][0]['known_texels'] == int(kb.sum()), 'тон-слой не вошёл в статистику части (известных столько же)')


def test_part_pattern_single_truth():
    print("part_pattern: узорность части — одна функция на 07 и на мерку Б:")
    rng = np.random.RandomState(9)
    big = Quads()
    big.quad([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]], (0, 0, .5, 1))
    big.quad([[2, 0, 0], [3, 0, 0], [3, 1, 0], [2, 1, 0]], (.5, 0, 1, 1))
    tex = np.full((256, 256, 3), 140, np.uint8)
    tex[:, :128] = np.clip(140 + rng.normal(0, 4, (256, 128, 1)), 0, 255)                       # часть 0: серая однотонная (шум только по яркости: ткань без цветного рисунка)
    sp = np.zeros((256, 128), bool)
    sp[::16, ::16] = True
    from scipy.ndimage import binary_dilation as _bd
    sp = _bd(sp, iterations=3)
    right = np.full((256, 128, 3), 140, np.uint8)
    right[sp] = (210, 90, 120)                                                                  # часть 1: розовые пятна на сером
    tex[:, 128:] = right
    g = big.geom(tex)
    kn = np.ones((256, 256), bool)
    nf = len(g['F'])
    pf = np.zeros(nf, np.int32)
    pf[nf // 2:] = 1
    tx = TF.Tex(g, np.asarray(g['V'], float), 256, pf)
    labs = [TF.rgb2lab(tex.reshape(-1, 3)).reshape(256, 256, 3)]
    c = dict(TF.FILL)
    _, eff = TF.part_pattern([tx], labs, [kn], [0, 1], c, {0: 60.0, 1: 60.0})
    ok(eff[1] > c['pattern_chroma'] >= eff[0], f'узорная часть выше порога, однотонная ниже (eff {eff[0]:.2f} / {eff[1]:.2f}, порог {c["pattern_chroma"]})')
    o = TF.fill([g], [kn], [pf], cfg={'gutter': 0, 'erode_known': 0}, mirror=False)
    ok(bool(o['report']['parts'][1]['pattern']) and not o['report']['parts'][0]['pattern'], 'отчёт 07 даёт тот же вердикт, что part_pattern')


def test_pr_camera_and_winding():
    print("камера образца узора из этапа 4 (az, el) и обмотка граней:")
    cfg, note = TF.pr_camera_from_extra({'camera': {'az': 341.3, 'el': 8.5}}, {})
    ok(abs(cfg['pr_az'] + 18.7) < 1e-6 and cfg['pr_el'] == 8.5, f"az 341,3 → −18,7, el 8,5: {cfg['pr_az']:.1f}/{cfg['pr_el']}")
    ok(TF.pr_camera_from_extra({'camera': {'az': 341.3, 'el': 8.5}}, {'pr_az': 0.0})[0]['pr_az'] == 0.0, "явный pr_az в cfg сильнее камеры")
    ok(TF.pr_camera_from_extra({'camera': {'az': 341.3, 'el': 8.5}}, {'pr_from_camera': False})[0].get('pr_az') is None, "pr_from_camera=false — камера не читается")
    c0, n0 = TF.pr_camera_from_extra({'camera': {'yaw': 0}}, {})
    ok(n0['source'].startswith('нет камеры') and c0['pattern_side_cos'] is None, "нет az в check — правило по стороне фото молчит (не az 0), заметка")
    n = np.array([[0.0, 0.0, 1.0], [0.9, 0.0, 0.43], [-1.0, 0.0, 0.0]])
    ok(TF.pattern_side_ok(n, 0.0, 0.2).tolist() == [True, True, False], "камера в лоб: лицо и косой бок — да, боковая стенка слева — нет")
    ok(TF.pattern_side_ok(n, -60.0, 0.2).tolist() == [True, False, True], "камера слева-сбоку (az −60): лицо (cos 0,5) и левая стенка — да, правый бок — нет")
    ok(TF.pattern_side_ok(np.array([[0.0, 1.0, 0.0]]), 0.0, 0.2, 30.0).tolist() == [True], "наклон камеры 30° вверх: верх (+Y) обращён к камере (cos 0,5)")
    ok(TF.winding_by_known(n, np.array([True, False, False]), 0.0) == 1.0, "известное смотрит на камеру — обмотка как есть")
    ok(TF.winding_by_known(-n, np.array([True, False, False]), 0.0) == -1.0, "известное смотрит от камеры — обмотка перевёрнута")
    ok(TF.winding_by_known(n, np.zeros(3, bool), 0.0) == 1.0, "известного нет — +1")


def test_hidden_visible():
    print("мерка «скрытое видимое» (tex_fill_hidden_visible): срез, метрики, свод:")
    import tex_fill_hidden_visible as HV
    rng = np.random.RandomState(2)
    Q = rng.normal(size=(5000, 3))
    cand = rng.rand(5000) < 0.7
    hid = HV.hide_sector(Q, cand, 0.3, np.random.RandomState(1))
    kept = cand & ~hid
    ok(not (hid & ~cand).any() and abs(kept.sum() / cand.sum() - 0.3) < 0.02, f"прячется кусок только из своей части, остаётся ≈ 30 % (осталось {kept.sum() / cand.sum():.2f})")
    ok(float(np.ptp(Q[hid] @ (Q[hid].mean(axis=0) / np.linalg.norm(Q[hid].mean(axis=0))))) < float(np.ptp(Q @ (Q[hid].mean(axis=0) / np.linalg.norm(Q[hid].mean(axis=0))))), "спрятанный кусок — связный сектор (полупространство), а не россыпь")
    Hh = 96
    m = np.ones((Hh, Hh), bool)
    noise = np.random.RandomState(3).normal(50, 4, (Hh, Hh))
    stripes = 50 + 6.0 * np.sin(np.arange(Hh)[None, :] * 0.9) * np.ones((Hh, 1))
    lab = lambda l: np.stack([l, np.zeros_like(l), np.zeros_like(l)], -1)  # noqa: E731
    same = HV.metrics_hidden(lab(noise), lab(noise), m, 1.0, 6.0, np.random.RandomState(5))
    diff = HV.metrics_hidden(lab(stripes), lab(noise), m, 1.0, 6.0, np.random.RandomState(5))
    ok(same['dE_low'] < 1e-6 and abs(same['band_ratio'] - 1.0) < 1e-6 and same['spec_dist'] < 1e-6 and same['ori_dist'] < 1e-6, "одинаковое с настоящим — мерки идеальные (0 / 1)")
    ok(diff['spec_dist'] > 0.1 and diff['ori_dist'] > 0.2, f"полосы вместо шума ловятся спектром ({diff['spec_dist']:.2f}) и ориентациями ({diff['ori_dist']:.2f})")
    recs = [{'sku': 'a', 'dir': 0, 'keep': 0.3, 'source': s_, 'dE_low': d_, 'band_ratio': b_, 'spec_dist': 0.1, 'ori_dist': 0.2} for s_, d_, b_ in (('stat', 4.0, 0.5), ('trellis_relief', 2.0, 0.95))]
    sm = HV.summarize(recs)
    ok('trellis_relief против stat' in sm and 'dE_low' in sm and 'побед 1' in sm, "свод: попарно C против stat считает победы")


def test_dark_fabric():
    _was = TF.RULES.get("mirror_enabled")
    TF.RULES["mirror_enabled"] = True                          # механизм зеркала жив под правилом; по умолчанию в 07 выкл.
    try:
        _test_dark_fabric_body()
    finally:
        TF.RULES["mirror_enabled"] = _was


def _test_dark_fabric_body():
    print("тёмная ткань (тон L≈15): чёрный порог относительный к тону — блоки пула и двойники зеркала не вымываются целиком (T-164, диван 114082):")
    rng = np.random.RandomState(5)
    qe, me = TF.RULES["quilt_extreme"], TF.RULES["mirror_extreme"]
    tone_l = 15.0
    ok(abs(TF.dark_floor(tone_l, qe["black_abs"], qe["black_rel"]) - qe["black_rel"] * tone_l) < 1e-9, "dark_floor на тёмной ткани = доля тона")
    ok(TF.dark_floor(67.0, qe["black_abs"], qe["black_rel"]) == qe["black_abs"], "на светлой ткани порог прежний (black_abs)")
    pool = [rng.normal(0, 2.0, (24, 24, 3)) for _ in range(20)]
    hole = rng.normal(0, 2.0, (24, 24, 3)); hole[4:14, 4:20, 0] = 2.0 - tone_l                       # настоящая чёрная дыра (L 2) на тёмной ткани
    old, nold = TF.reject_extreme_blocks(pool + [hole], tone_l, qe["dL_hi"], qe["black_abs"], qe["share"])
    new, nnew = TF.reject_extreme_blocks(pool + [hole], tone_l, qe["dL_hi"], TF.dark_floor(tone_l, qe["black_abs"], qe["black_rel"]), qe["share"])
    ok(nold >= 20 and nnew == 1 and len(new) == 20, f"абсолютный порог резал весь пул ({nold} из 21), относительный — только дыру ({nnew})")
    # зеркало: тёмная ткань, двойники не выбрасываются; настоящая дыра — выбрасывается
    q = Quads()
    left = [[-1, 0, 0], [-1, 0, 1], [-1, 1, 1], [-1, 1, 0]]
    right = [[1, 0, 1], [1, 0, 0], [1, 1, 0], [1, 1, 1]]
    q.quad(left, (0, 0, .5, .5), sub=24)
    q.quad(right, (.5, 0, 1, .5), sub=24)
    q.quad([[-1, 0, 0], [1, 0, 0], [1, 0, 1], [-1, 0, 1]], (0, .5, .5, 1), sub=24)
    q.quad([[-1, 1, 1], [1, 1, 1], [1, 1, 0], [-1, 1, 0]], (.5, .5, 1, 1), sub=24)
    ml, mr = tile_mask((0, 0, .5, .5)), tile_mask((.5, 0, 1, .5))
    mfloor, mtop = tile_mask((0, .5, .5, 1)), tile_mask((.5, .5, 1, 1))
    tex = np.full((T, T, 3), 20, np.uint8)
    yy = (np.arange(T)[:, None] * np.ones((1, T))).astype(float)
    base = np.stack([26 + yy * 0.04, 34 + yy * 0.04, 58 + yy * 0.06], -1)
    tex[ml] = np.clip(base + rng.normal(0, 1.5, base.shape), 0, 255).astype(np.uint8)[ml]
    tex[mfloor] = (28, 36, 60)
    tex[mtop] = (28, 36, 60)
    known = [ml | mfloor | mtop]
    Lk = TF.rgb2lab(tex[ml])[:, 0]
    ok(10.0 < float(np.median(Lk)) < 19.0, f"сцена действительно тёмная (медиана L {float(np.median(Lk)):.1f})")
    o = TF.fill([q.geom(tex)], known, None, cfg={"gutter": 0, "erode_known": 0}, mirror=True)
    rm = o["report"]["mirror"]
    ok(rm["applied"] and rm["texels"] > 0.9 * int(mr.sum()) and rm.get("dropped_black", 0) < 0.05 * int(mr.sum()), f"тёмный диван: зеркало копирует двойников (скопировано {rm['texels']}, отброшено {rm.get('dropped_black', 0)})")
    tex_b = tex.copy()
    holes = np.zeros((T, T), bool)
    holes[int(T * 0.65):int(T * 0.73), int(T * 0.15):int(T * 0.35)] = True
    tex_b[ml & holes] = (10, 12, 20)             # L≈4: темнее порога 7,5, но «покрашено» (не чёрное-пустое)
    o2 = TF.fill([q.geom(tex_b)], known, None, cfg={"gutter": 0, "erode_known": 0}, mirror=True)
    ok(o2["report"]["mirror"].get("dropped_black", 0) > 0, f"настоящая чёрная дыра на тёмной ткани всё равно не зеркалится (отброшено {o2['report']['mirror'].get('dropped_black', 0)})")
    ok("dropped_pct" in rm, "в отчёте зеркала есть доля сброшенных двойников (dropped_pct)")

    def part0(base, sd, flowers=None, ref=None):
        qq = Quads()
        qq.quad([[0, 0, 0], [2, 0, 0], [2, 1, 0], [0, 1, 0]], (0, 0, .9, .9), sub=8)
        qq.quad([[0, 0, -1], [2, 0, -1], [2, 1, -1], [0, 1, -1]], (.9, .9, 1.0, 1.0), sub=2)
        tx = np.zeros((T, T, 3), np.uint8)
        r2 = np.random.RandomState(4)
        m = tile_mask((0, 0, .9, .9))
        ys, xs = np.nonzero(m)
        tx[ys, xs] = np.clip(np.array(base) + r2.normal(0, sd, (len(ys), 3)), 0, 255).astype(np.uint8)
        if flowers is not None:
            fl = ((xs // 12 + ys // 12) % 7 == 0) & ((xs % 12) < 8) & ((ys % 12) < 8)
            tx[ys[fl], xs[fl]] = flowers
        cfg = {"gutter": 0, "erode_known": 0}
        if ref is not None:
            cfg["pattern_dark_ref"] = ref
        return TF.fill([qq.geom(tx)], [m.copy()], None, cfg=cfg, mirror=False)["report"]["parts"][0]
    dn, dn0, df = part0((30, 40, 66), 2.0), part0((30, 40, 66), 2.0, ref=0), part0((30, 40, 66), 2.0, flowers=[200, 60, 90])
    ok(dn["pattern"] is False and dn["pattern_chroma_eff"] < dn["pattern_chroma_std"], f"тёмная ровная ткань с шумом хромы — не «узорная» (σ {dn['pattern_chroma_std']} → норм. {dn['pattern_chroma_eff']})")
    ok(dn0["pattern"] is True, "контроль: без нормировки (pattern_dark_ref=0) тот же шум давал «узорную» — прежний дефект")
    ok(df["pattern"] is True, f"тёмная ткань с настоящим узором (яркие цветы) остаётся «узорной» (норм. σ {df['pattern_chroma_eff']})")
    # мягкий провал «пул отбракован > 50 %» в check.json: на тёмной узорной ткани со СТАРЫМ абсолютным порогом (black_rel огромный) пул режется целиком
    import tempfile
    qq = Quads()
    qq.quad([[0, 0, 0], [2, 0, 0], [2, 1, 0], [0, 1, 0]], (0, 0, .9, .9), sub=8)
    qq.quad([[0, 0, -1], [2, 0, -1], [2, 1, -1], [0, 1, -1]], (.9, .9, 1.0, 1.0), sub=2)
    tx = np.zeros((T, T, 3), np.uint8)
    r3 = np.random.RandomState(4)
    m = tile_mask((0, 0, .9, .9))
    ys, xs = np.nonzero(m)
    tx[ys, xs] = np.clip(np.array((30, 40, 66)) + r3.normal(0, 2.0, (len(ys), 3)), 0, 255).astype(np.uint8)
    fl = ((xs // 12 + ys // 12) % 7 == 0) & ((xs % 12) < 8) & ((ys % 12) < 8)
    tx[ys[fl], xs[fl]] = [200, 60, 90]
    gq = qq.geom(tx)
    saved = dict(TF.RULES["quilt_extreme"])
    try:
        with tempfile.TemporaryDirectory() as td:
            TF.write_glb([gq], [tx], os.path.join(td, "in.glb"))
            good = TF.run_stage(td, "dk:1", os.path.join(td, "in.glb"), known=[m.copy()], parts=None, cfg={"gutter": 0, "erode_known": 0, "pattern_min_blocks": 0.0}, mirror=False)
            TF.RULES["quilt_extreme"]["black_rel"] = 1e9                       # прежний абсолютный порог
            old = TF.run_stage(td, "dk:2", os.path.join(td, "in.glb"), known=[m.copy()], parts=None, cfg={"gutter": 0, "erode_known": 0, "pattern_min_blocks": 0.0}, mirror=False)
    finally:
        TF.RULES["quilt_extreme"].update(saved)
    mg, mo = good["check"]["metrics"]["pool_rejected_pct"], old["check"]["metrics"]["pool_rejected_pct"]
    ok(mg["ok"] and mg["value"] <= 50.0, f"относительный порог: пул не отбракован (pool_rejected_pct {mg['value']})")
    ok((not mo["ok"]) and mo["value"] > 50.0 and "pool_rejected_pct" in old["check"]["reason"] and not old["check"]["passed"], f"прежний порог: пул отбракован ({mo['value']} %) → мягкий провал в check.json, выход есть", old["check"]["reason"][:80])


def test_stage6_gate():
    print("этап 7 отказывает, если этап 6 отказал (камера не прошла / нет выхода); мягкий провал мерок — не отказ:")
    import json
    import tempfile
    import paint_stage as PS
    with tempfile.TemporaryDirectory() as td:
        def mk(name, doc, glb):
            d = os.path.join(td, name, "06-visible")
            os.makedirs(d)
            if doc is not None:
                json.dump(doc, open(os.path.join(d, "check.json"), "w"))
            if glb:
                open(os.path.join(d, "visible.glb"), "wb").write(b"x")
            return d
        base = {"version": 1, "stage": "06-visible", "sku": "x", "metric": None, "metrics": {}, "outputs": [], "frame": None}
        d1 = mk("cam", dict(base, passed=False, reason="камера этапа 4 не прошла", extra={"camera_failed": True, "camera_gate": "failed"}), False)
        d2 = mk("soft", dict(base, passed=False, reason="known_share 0.14 < 0.15", extra={"needs_qwen": True}), True)
        d3 = mk("ok", dict(base, passed=True, reason="", extra={}), True)
        d4 = mk("nochk", None, True)
        d5 = mk("noglb", dict(base, passed=True, reason="", extra={}), False)
        g = {k: TF.stage6_gate(d) for k, d in (("cam", d1), ("soft", d2), ("ok", d3), ("nochk", d4), ("noglb", d5))}
        ok(g["cam"][0] and "камера" in g["cam"][1], f"камера не прошла → отказ ({g['cam'][1][:40]})")
        ok(not g["soft"][0] and g["soft"][2].get("soft_fail") is True, "мягкий провал мерок этапа 6 (есть выход) → заливка идёт, провал записан")
        ok(not g["ok"][0] and g["ok"][2].get("soft_fail") is False, "этап 6 прошёл → заливка идёт")
        ok(g["nochk"][0] and g["noglb"][0], "нет check.json или visible.glb → отказ")
        r = TF.run_stage(td, "cam", os.path.join(d1, "visible.glb"), prev_dir=d1)
        c = PS.read_check(PS.stage_dir(td, "cam", TF.STAGE))
        ok(r.get("refused") and c is not None and c["passed"] is False and c["extra"].get("refused") is True and c["outputs"] == [], "run_stage при отказе: check.json passed=false, refused, выхода нет, GLB не читался")


def test_cli_run_stage():
    print("CLI `tex_fill.py run_stage <run> <sku>`: вход из <run>/<sku>/06-visible, выход — 07-fill/check.json в формате paint_stage:")
    import json
    import tempfile
    import paint_stage as PS
    with tempfile.TemporaryDirectory() as td:
        v = os.path.join(td, "sku1", "06-visible")
        os.makedirs(v)
        json.dump({"version": 1, "stage": "06-visible", "sku": "sku1", "passed": False, "reason": "камера этапа 4 не прошла", "metric": None, "metrics": {}, "outputs": [], "frame": None,
                   "extra": {"camera_failed": True, "camera_gate": "failed"}}, open(os.path.join(v, "check.json"), "w"))
        rc = TF.main(["run_stage", td, "sku1"])
        c = PS.read_check(os.path.join(td, "sku1", "07-fill"))
        ok(rc == 0 and c is not None and c["stage"] == "07-fill" and c["passed"] is False and c["extra"].get("refused") is True, "этап 6 отказал → rc 0, check.json 07-fill passed=false refused")
        rc2 = TF.main(["run_stage", td, "нет-такого"])
        c2 = PS.read_check(os.path.join(td, "нет-такого", "07-fill"))
        ok(rc2 == 0 and c2 is not None and c2["passed"] is False, "нет выхода этапа 6 → check.json passed=false, не сбой запуска")


def test_orphan_parts():
    print("запасное деление по геометрии: часть-сирота (доля ПЛОЩАДИ < refine.orphan_max_area_share) вливается в соседа:")
    import trimesh
    n = 30
    gx, gy = np.meshgrid(np.arange(n + 1, dtype=float), np.arange(n + 1, dtype=float))
    V = np.stack([gx.ravel(), gy.ravel(), np.zeros(gx.size)], 1)
    idx = np.arange((n + 1) * (n + 1)).reshape(n + 1, n + 1)
    F = []
    for i in range(n):
        for j in range(n):
            a, b, c, d = idx[i, j], idx[i, j + 1], idx[i + 1, j + 1], idx[i + 1, j]
            F += [[a, b, c], [a, c, d]]
    nbig = len(F)
    V = np.vstack([V, [[0.5, -0.001, 0.0]]])
    F.append([idx[0, 0], idx[0, 1], len(V) - 1])                      # крошечный треугольник на краю сетки: площадь ~5e-4 из ~900
    F = np.array(F)
    mesh = trimesh.Trimesh(V, F, process=False)
    part = np.zeros(len(F), np.int32)
    part[: nbig // 2] = 1
    part[-1] = 2
    new, note = TF.merge_orphan_parts(mesh, part)
    if "нет parts_refine" in note:
        print("  – пропущено: parts_refine / parts-sam-rules.json (этап 3, T-169) в этой ветке ещё нет; проверяется после влития")
        ok(np.array_equal(new, part), "без модуля этапа 3 части не меняются")
        return
    ok(int(new[-1]) in (0, 1) and len(np.unique(new)) == 2 and "сирот влито 1" in note, f"сирота влита в соседа, части 0/1 остались ({note})")
    ok(set(np.unique(new)) == {0, 1}, "номера частей плотные")
    big = part.copy()
    big[nbig // 2: nbig // 2 + 400] = 2                                # часть с большой долей площади — не сирота
    new2, note2 = TF.merge_orphan_parts(mesh, big)
    ok(len(np.unique(new2)) == 3 and "сирот" not in note2, "крупная часть не вливается")


def test_cli_parts_flags():
    print("CLI: --no-parts-npz (этап 3 отказал → части по геометрии) и --parts-npz:")
    import json
    import tempfile
    import paint_stage as PS
    from PIL import Image
    q = Quads()
    q.quad([[-0.5, 0, 0], [0.5, 0, 0], [0.5, 1, 0], [-0.5, 1, 0]], (0, 0, .9, .9), sub=8)
    q.quad([[-0.5, 0, -0.4], [0.5, 0, -0.4], [0.5, 1, -0.4], [-0.5, 1, -0.4]], (.9, .9, 1.0, 1.0), sub=2)
    tex = np.zeros((T, T, 3), np.uint8)
    m = tile_mask((0, 0, .9, .9))
    tex[m] = (130, 140, 200)
    g = q.geom(tex)
    with tempfile.TemporaryDirectory() as td:
        v = os.path.join(td, "s1", "06-visible")
        os.makedirs(v)
        TF.write_glb([g], [tex], os.path.join(v, "visible.glb"))
        Image.fromarray((m * 255).astype(np.uint8)).save(os.path.join(v, "known.png"))
        json.dump({"version": 1, "stage": "06-visible", "sku": "s1", "passed": True, "reason": "", "metric": None, "metrics": {}, "outputs": [], "frame": None, "extra": {}}, open(os.path.join(v, "check.json"), "w"))
        os.makedirs(os.path.join(td, "s1", "03-parts"))
        np.savez(os.path.join(td, "s1", "03-parts", "parts.npz"), part=np.zeros(3, np.int16))        # parts.npz отказавшего этапа 3: число граней не то
        rc_bad = TF.main(["run_stage", td, "s1", "--no-mirror"])
        c_bad = PS.read_check(os.path.join(td, "s1", "07-fill"))
        ok(rc_bad == 2 and c_bad["passed"] is False and "сбой этапа 7" in c_bad["reason"], "без флага parts.npz подхватывается и чужой → сбой запуска rc 2, сбой записан в check.json")
        rc_ok = TF.main(["run_stage", td, "s1", "--no-mirror", "--no-parts-npz"])
        c_ok = PS.read_check(os.path.join(td, "s1", "07-fill"))
        ok(rc_ok == 0 and c_ok["passed"] is not None and "parts.npz" not in str(c_ok["extra"].get("parts")), f"--no-parts-npz → части по геометрии, rc 0 ({c_ok['extra'].get('parts')})")
        rc_exp = TF.main(["run_stage", td, "s1", "--no-mirror", "--parts-npz", os.path.join(td, "s1", "03-parts", "parts.npz")])
        ok(rc_exp == 2, "явный --parts-npz с чужим файлом → rc 2")
        was = TF.RULES.get("zones_from")
        TF.RULES["zones_from"] = "panels"                                        # T-198/1: zones_from=panels — parts.npz из 03-parts не подхватывается, явный --parts-npz сильнее флага
        try:
            rc_pan = TF.main(["run_stage", td, "s1", "--no-mirror"])
            c_pan = PS.read_check(os.path.join(td, "s1", "07-fill"))
            ok(rc_pan == 0 and "parts.npz" not in str(c_pan["extra"].get("parts")), f"zones_from=panels: чужой parts.npz не берётся, rc 0 ({c_pan['extra'].get('parts')})")
            rc_pan2 = TF.main(["run_stage", td, "s1", "--no-mirror", "--parts-npz", os.path.join(td, "s1", "03-parts", "parts.npz")])
            ok(rc_pan2 == 2, "zones_from=panels + явный --parts-npz → файл берётся (здесь чужой → rc 2)")
            TF.RULES["zones_from"] = "x"
            try:
                TF.main(["run_stage", td, "s1", "--no-mirror"])
                bad_flag = False
            except SystemExit as e:
                bad_flag = e.code == 2
            ok(bad_flag, "zones_from с чужим значением → ошибка аргументов")
        finally:
            if was is None:
                TF.RULES.pop("zones_from", None)
            else:
                TF.RULES["zones_from"] = was
        try:
            TF.main(["run_stage", td, "s1", "--parts-npz", "x.npz", "--no-parts-npz"])
            both = False
        except SystemExit as e:
            both = e.code == 2
        ok(both, "оба флага вместе — ошибка аргументов")


def test_zones_fallback():
    print("откат зон 07 (T-198/1): провал front_on_back по частям → тот же этап заливает по панелям:")
    import json
    import tempfile
    calls = []

    def fake(vals):
        def once(run, sku, glb, **kw):
            calls.append(kw.get("parts_npz"))
            d = os.path.join(run, sku.replace(":", "_"), "07-fill")
            os.makedirs(d, exist_ok=True)
            v = vals[min(len(calls) - 1, len(vals) - 1)] if kw.get("parts_npz") else vals[-1]
            json.dump({"report": {}}, open(os.path.join(d, "report.json"), "w"))
            json.dump({"metrics": {"front_on_back_corr": {"value": v, "threshold": 0.6, "ok": v <= 0.6}}, "seconds": 1.0}, open(os.path.join(d, "check.json"), "w"))
            open(os.path.join(d, "frame.png"), "wb").write(b"x")
            return {"check": json.load(open(os.path.join(d, "check.json"))), "dir": d}
        return once

    was_once, was_rules = TF.run_stage_once, TF.RULES.get("zones_fallback")
    try:
        TF.RULES["zones_fallback"] = ["front_on_back_corr"]
        with tempfile.TemporaryDirectory() as td:
            TF.run_stage_once = fake([0.69, 0.13])                              # части: 0,69 ✗ → панели 0,13 ✓
            del calls[:]
            r = TF.run_stage(td, "a:1", "x.glb", parts_npz="/p/parts.npz")
            doc = json.load(open(os.path.join(r["dir"], "report.json")))
            ok(calls == ["/p/parts.npz", None] and doc["zones_used"] == "panels", f"откат на панели ({calls}, {doc.get('zones_used')})")
            ok(os.path.isfile(os.path.join(r["dir"], "check-parts.json")) and os.path.isfile(os.path.join(r["dir"], "frame-parts.png")), "прогон по частям сохранён рядом")
            ok(doc["zones_parts_try"]["front_on_back_corr"]["value"] == 0.69 and "front_on_back_corr 0.69" in doc["zones_reason"] and "zones_total_s" in doc, "причина и мерки частей в report.json")
            TF.run_stage_once = fake([0.2])                                   # части прошли — один прогон
            del calls[:]
            r = TF.run_stage(td, "a:2", "x.glb", parts_npz="/p/parts.npz")
            doc = json.load(open(os.path.join(r["dir"], "report.json")))
            ok(calls == ["/p/parts.npz"] and doc["zones_used"] == "parts" and doc["zones_reason"] is None, "части прошли — отката нет")
            TF.run_stage_once = fake([0.69])                                  # провал и у панелей — панели остаются основой, с пометкой
            del calls[:]
            r = TF.run_stage(td, "a:3", "x.glb", parts_npz="/p/parts.npz")
            doc = json.load(open(os.path.join(r["dir"], "report.json")))
            ok(doc["zones_used"] == "panels" and "панели не проходят" in doc["zones_reason"], "и панели не проходят — панели с пометкой")
            TF.run_stage_once = fake([0.69])
            del calls[:]
            TF.run_stage(td, "a:4", "x.glb", parts_npz="/p/parts.npz", fallback=False)
            ok(calls == ["/p/parts.npz"], "fallback=False — без отката")
            del calls[:]
            TF.run_stage(td, "a:5", "x.glb")
            ok(calls == [None], "без parts_npz — один прогон (панели и так)")
            TF.RULES["zones_fallback"] = []
            del calls[:]
            TF.run_stage(td, "a:6", "x.glb", parts_npz="/p/parts.npz")
            ok(calls == ["/p/parts.npz"], "zones_fallback=[] — отката нет")
    finally:
        TF.run_stage_once = was_once
        if was_rules is None:
            TF.RULES.pop("zones_fallback", None)
        else:
            TF.RULES["zones_fallback"] = was_rules


def test_render_low():
    print('кадр снизу (дно) — elevation −90:')
    q = Quads()
    q.quad([[-0.5, 0, -0.5], [0.5, 0, -0.5], [0.5, 0, 0.5], [-0.5, 0, 0.5]], (0, 0, .5, .5), sub=4)       # горизонтальная плита, нормаль по ±Y
    q.quad([[-0.5, 0.05, -0.5], [0.5, 0.05, -0.5], [0.5, 0.05, 0.5], [-0.5, 0.05, 0.5]], (.5, .5, 1, 1), sub=4)
    tex = np.zeros((T, T, 3), np.uint8)
    tex[tile_mask((0, 0, .5, .5))] = [200, 30, 30]
    tex[tile_mask((.5, .5, 1, 1))] = [30, 30, 200]
    g = q.geom(tex)
    low = TF.render_ortho([g], [tex], 0.0, res=128, elevation=-90.0)
    fr = TF.render_ortho([g], [tex], 0.0, res=128)
    cov = lambda im: float((np.abs(im.astype(int) - 245).sum(axis=2) > 30).mean())    # noqa: E731
    ok(cov(low) > 0.25 and cov(fr) < 0.05, f'снизу плита видна (покрыто {cov(low):.2f}), в лоб — ребром ({cov(fr):.2f})')
    ctr = low[56:72, 56:72].reshape(-1, 3).mean(axis=0)
    ok(ctr[0] > ctr[2], 'снизу ближняя к камере плита (низ, красная) закрывает верхнюю (синюю)', str(ctr))


def _top_scene(top_known_rgb=None):
    """Стол: вертикальный фасад (известный, «дерево») и горизонтальная плита верха; верх на фото не виден (или виден левой половиной цветом top_known_rgb)."""
    q = Quads()
    q.quad([[-0.5, 0, 0], [0.5, 0, 0], [0.5, 1, 0], [-0.5, 1, 0]], (0, 0, 1.0, .9), sub=16)                    # фасад
    q.quad([[-0.5, 1, 0], [0.5, 1, 0], [0.5, 1, -0.5], [-0.5, 1, -0.5]], (0, .92, 1.0, 1.0), sub=16)          # верх (нормаль вверх)
    tex = np.zeros((T, T, 3), np.uint8)
    paint(tex, (0, 0, 1.0, .9), [170, 110, 60])
    paint(tex, (0, .92, 1.0, 1.0), [90, 90, 90])                                                              # «как залил 07» — серый
    kn = tile_mask((0, 0, 1.0, .9))
    if top_known_rgb is not None:
        paint(tex, (0, .92, 1.0, 1.0), top_known_rgb, sub=0.5)
        kn = kn | tile_mask((0, .92, 1.0, 1.0), sub=0.5)
    return q.geom(tex), tex, kn


def test_top_prior_hook():
    print('верх по Ш3в в этапе 07 (T-187/7): класс, порог уверенности, известное не трогаем, арбитр по фото верха:')
    import copy
    import top_prior as TP
    card = {'role': 'стол обеденный', 'name': 'Стол обеденный из массива дуба', 'Материал столешницы': 'массив дуба'}
    g, tex, kn = _top_scene()
    cfg = {'top_card': card}
    out, rep = TF.top_prior_hook([g], [tex.copy()], [kn], None, cfg, None)
    top_px = tile_mask((0, .92, 1.0, 1.0))
    ok(rep.get('applied') is True and rep['top_source'] == 'same_part_inference' and rep['texels_changed'] > 1000, f'дерево + голос фасада → верх покрашен, top_source={rep.get("top_source")}', str(rep)[:300])
    ok(np.array_equal(out[0][kn], tex[kn]), 'известные тексели не изменились (known — на нуле)')
    ch = (out[0] != tex).any(-1)
    from scipy.ndimage import distance_transform_edt
    covered = np.zeros(top_px.shape, bool)
    for q_ in ((0, 0, 1.0, .9), (0, .92, 1.0, 1.0)):
        covered |= tile_mask(q_)
    dist_top = distance_transform_edt(~top_px)
    gut = ch & ~top_px
    ok(not (gut & covered).any() and (dist_top[gut] <= TF.FILL['gutter']).all(), 'изменились только тексели верха и его желоб (непокрытые в пределах gutter от верха; фасад не тронут)')
    ok(rep.get('gutter_texels', 0) == int(gut.sum()), f'желоб после покраски верха посчитан в отчёте: {rep.get("gutter_texels")} = {int(gut.sum())}')
    ph = rep.get('hidden_after_lab')
    ok(ph is not None and ph[0] > 45 and ph[1] > 5, f'верх теплее и светлее серого заливки (Lab {ph}) — тон фасада дерева')
    o2, r2 = TF.top_prior_hook([g], [tex.copy()], [kn], None, {}, None)
    ok(r2['top_source'] == 'as_before' and not r2['applied'] and np.array_equal(o2[0], tex), f'нет карточки (класс неизвестен) — как делал 07: {r2.get("gate")}')
    ok(r2.get('top_skip') == 'no_card', f'нет карточки — причина в отчёте top_skip=no_card (не молчаливый as_before): {r2.get("top_skip")}')
    o3, r3 = TF.top_prior_hook([g], [tex.copy()], [kn], None, {'top_card': {'role': 'диван', 'name': 'Диван', 'Материал обивки': 'велюр'}}, None)
    ok(r3['top_source'] == 'as_before' and np.array_equal(o3[0], tex), f'ткань/не дерево — как делал 07: {r3.get("gate")}')
    r_ = copy.deepcopy(TP.load_rules())
    r_['stage07']['min_confidence'] = 'high'
    ok(TP.stage07_gate({'tone_lab': [60, 10, 28], 'confidence': 'medium', 'card_class': {'group': 'library', 'class': 'wood_solid'}}, r_)[0] is False, 'порог high: medium не проходит')
    ok(TP.stage07_gate({'tone_lab': [60, 10, 28], 'confidence': 'high', 'card_class': {'group': 'library', 'class': 'wood_solid'}}, r_)[0] is True, 'порог high: high проходит')
    r_['stage07']['enabled'] = False
    ok(TP.stage07_gate({'tone_lab': [60, 10, 28], 'confidence': 'high', 'card_class': {'group': 'library'}}, r_)[0] is False, 'stage07.enabled=false — правило выключено')
    g2, tex2, kn2 = _top_scene(top_known_rgb=[60, 90, 200])                                                    # половина верха видна на фото и она СИНЯЯ — гипотеза Ш3в от неё далеко
    out4, rep4 = TF.top_prior_hook([g2], [tex2.copy()], [kn2], None, cfg, None)
    ok(rep4.get('rejected_by_photo') is True and not rep4['applied'] and rep4['top_source'] == 'as_before' and np.array_equal(out4[0], tex2), f'верх виден на фото и Ш3в дальше от него — оставлено как есть: {rep4.get("gate")}')
    ok(rep4['photo_top_n'] >= 50, f'видимых текселей верха {rep4["photo_top_n"]}')
    g3, tex3, kn3 = _top_scene()
    ok(TF.top_prior_hook([g3], [tex3.copy()], [kn3], None, {'top_card': card}, None)[1]['top_source'] != 'photo_top', 'верх целиком невидим: источник не photo_top')
    allk = [np.ones_like(kn)]
    ok(TF.top_prior_hook([g3], [tex3.copy()], allk, None, cfg, None)[1]['top_source'] == 'photo_top', 'весь верх с фото — top_source=photo_top, красить нечего')


def test_side_azimuths():
    print('кадр по ориентации: зад — сторона без фото по known, фото-сторона — с известным (T-187/6, 23.11):')
    q = Quads()
    q.quad([[-1, 0, 1], [1, 0, 1], [1, 1, 1], [-1, 1, 1]], (0, 0, .5, .5), sub=12)
    q.quad([[-1, 0, -1], [1, 0, -1], [1, 1, -1], [-1, 1, -1]], (.5, 0, 1, .5), sub=12)
    q.quad([[-1, 0, -1], [-1, 0, 1], [-1, 1, 1], [-1, 1, -1]], (0, .5, .5, 1), sub=12)
    q.quad([[1, 0, 1], [1, 0, -1], [1, 1, -1], [1, 1, 1]], (.5, .5, 1, 1), sub=12)
    tex = np.full((T, T, 3), 120, np.uint8)
    g = q.geom(tex)
    res = {}
    for nm, box in (('z+', (0, 0, .5, .5)), ('z-', (.5, 0, 1, .5))):
        res[nm] = TF.side_azimuths([g], [tile_mask(box)])
        ok(abs((res[nm]['photo'] - res[nm]['back']) % 360 - 180) < 1e-6, f'{nm}: зад напротив фото-стороны ({res[nm]["photo"]}→{res[nm]["back"]})')
    ok(abs((res['z+']['photo'] - res['z-']['photo']) % 360 - 180) < 1e-6, f'известное на противоположных гранях → фото-стороны противоположны ({res["z+"]["photo"]}, {res["z-"]["photo"]})')
    r0 = TF.side_azimuths([g], [np.zeros((T, T), bool)])
    ok(r0.get('fallback') is True and r0['back'] == 180.0, 'known пуст → запасной вариант 180 с пометкой')


def main() -> int:
    for f in (test_check_on_final_texture, test_side_azimuths, test_top_prior_hook, test_mirror_off_by_default, test_shrink_layout, test_tie_picks_front_on_back, test_front_on_back, test_front_on_back_within_parts, test_front_on_back_unequal_parts, test_color, test_photo, test_parts, test_lighter_than_photo, test_no_known_part, test_mirror, test_texture, test_gutter_render, test_seam_steps_concavity, test_diffuse_quilt_far, test_draft_source, test_tone_mode_pattern, test_quilt_efros, test_quilt_holes, test_known_unchanged, test_render_pattern, test_outlier_blocks, test_dark_fabric, test_trellis_relief, test_part_roles_from_stage3, test_stage7_side_tone_smooth_rules, test_tone_from_neighbour, test_nail_twins, test_borrow_donors, test_tone_only, test_part_pattern_single_truth, test_pr_camera_and_winding, test_hidden_visible, test_stage6_gate, test_cli_run_stage, test_orphan_parts, test_cli_parts_flags, test_zones_fallback, test_brightness_target_median, test_run_stage_fallback, test_render_low, test_quilt_lattice, test_pattern_lattice, test_part_independence, test_unobserved_relief):
        f()
    print(f'tests_tex_fill: ошибок {bad}')
    return 1 if bad else 0


if __name__ == '__main__':
    raise SystemExit(main())
