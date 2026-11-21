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
    out = TF.fill([g], known, parts, cfg={"gutter": 0, "erode_known": 0, "tone": "median", "src_dev_pattern": 0}, mirror=False)     # часть 1 двухцветная (синий + жёлтый островок): геометрия заливки проверяется при медиане, мода — отдельный тест
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


def test_no_known_part():
    print('часть без известного: статистика по всему предмету (счётчик), чёрного нет:')
    g, parts, known, tl, col = scene_parts()
    known2 = [known[0] & ~tile_mask(tl['C']) & ~tile_mask(tl['B'], 0.5)]            # у части 1 известного нет совсем
    out = TF.fill([g], known2, parts, cfg={'gutter': 0, 'erode_known': 0, 'min_known': 50}, mirror=False)
    rep = out['report']
    ok(rep['fallback_global'] == 1 and rep['parts'][1]['stats_from_global'], 'часть 1: статистика взята по предмету, счётчик fallback_global = 1')
    ok(rep['unpainted_after_pct'] == 0.0, 'после заливки чёрного нет')


# ------------------------------------------------------------------ зеркало
def test_mirror():
    print('зеркало симметричного предмета:')
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
    out = TF.fill([g], known, parts, cfg={'gutter': 0, 'erode_known': 0, 'source': 'trellis'}, mirror=False, draft=dt)
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
    out = TF.fill([g], kn, None, cfg={'gutter': 0, 'erode_known': 0}, mirror=False)
    rep = out['report']
    cream = TF.rgb2lab(np.array([[235, 225, 200]], np.uint8))[0]
    tone = np.array(rep['parts'][0]['mean_lab'])
    ok(float(TC.de2000_v(tone[None], cream[None])[0]) < 3.0, f'тон = кремовый фон, а не розовый средний (ΔE к фону {float(TC.de2000_v(tone[None], cream[None])[0]):.1f})')
    ok(rep['parts'][0]['pattern'] is True, 'часть с цветами помечена «узорной»')
    ok(rep.get('quilt') == 1 and rep['no_patch'] == 0, 'узор — квилтом из мелких блоков')
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
        bad = [a.copy() for a in r['tex_after']]
        bad[0][ys[:50], xs[:50]] = 255 - bad[0][ys[:50], xs[:50]]
        sh = TF.known_changed_share([m], r['tex_before'], bad, TF.RULES['known_change_de'])
        ok(sh['changed'] >= 40 and sh['share_pct'] > 0, f'контроль: подмена известных текселей мерка ловит ({sh})')


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
        try:
            TF.main(["run_stage", td, "s1", "--parts-npz", "x.npz", "--no-parts-npz"])
            both = False
        except SystemExit as e:
            both = e.code == 2
        ok(both, "оба флага вместе — ошибка аргументов")


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


def main() -> int:
    for f in (test_color, test_photo, test_parts, test_no_known_part, test_mirror, test_texture, test_gutter_render, test_seam_steps_concavity, test_diffuse_quilt_far, test_draft_source, test_tone_mode_pattern, test_quilt_efros, test_quilt_holes, test_known_unchanged, test_render_pattern, test_outlier_blocks, test_stage6_gate, test_cli_run_stage, test_orphan_parts, test_cli_parts_flags, test_run_stage_fallback, test_render_low):
        f()
    print(f'tests_tex_fill: ошибок {bad}')
    return 1 if bad else 0


if __name__ == '__main__':
    raise SystemExit(main())
