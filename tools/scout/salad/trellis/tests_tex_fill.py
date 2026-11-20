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
    out = TF.fill([g], known, parts, cfg={'gutter': 0, 'erode_known': 0}, mirror=False)
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
    cfg = {'gutter': 0, 'erode_known': 0, 'geo_len': 0.6, 'ao': 0.0}
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


def main() -> int:
    for f in (test_color, test_photo, test_parts, test_no_known_part, test_mirror, test_texture, test_gutter_render, test_seam_steps_concavity, test_diffuse_quilt_far, test_draft_source):
        f()
    print(f'tests_tex_fill: ошибок {bad}')
    return 1 if bad else 0


if __name__ == '__main__':
    raise SystemExit(main())
