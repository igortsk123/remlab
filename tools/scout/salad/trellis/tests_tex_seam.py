#!/usr/bin/env python3
"""Тесты сведения шва «фото | заливка» `tex_seam.py` (T-196/1/1, П1.136): синтетика — плоская панель 200×200 мм слева «фото», справа «заливка» со сдвигом тона и другой фактурой.
Без видеокарты и сети; нужны numpy, scipy. Проверяется: расстояние по ПОВЕРХНОСТИ (через сгиб, не по прямой); тон заливки у границы подтянут к фото (скачок ΔE00 было→стало),
середина фото 1:1, дальняя заливка и чужая зона не тронуты; контраст фактуры заливки приводится к фото, плоскую заливку не оживляем; сомнительные краевые тексели фото заменяются
заливкой, надёжные — нет; запасной вход без карты доверия; сквозной `tex_fill.fill`: известное 1:1 и отчёт шва; правила — в rules-json.

  python3 tools/scout/salad/trellis/tests_tex_seam.py
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.normpath(os.path.join(HERE, '..', '..')))
import remlab_tmp  # noqa: E402
remlab_tmp.use('tests_tex_seam')
import numpy as np  # noqa: E402
import tex_coverage as TC  # noqa: E402
import tex_fill as TF  # noqa: E402
import tex_seam as TS  # noqa: E402

bad = 0
T = 128
SEAM = dict(TF.RULES['seam'], feather_mm=0.0, min_panel_faces=4, tone_decay_mm=25.0, reach_mm=30.0, cell_mm=10.0, min_cell=6, contrast_decay_mm=25.0, pair_mm=4.0, probe_mm=10.0)


def ok(cond, name, extra=''):
    global bad
    print(('  ✓ ' if cond else '  ✗ ') + name + (f' — {extra}' if extra and not cond else ''))
    bad += 0 if cond else 1


def panel(n=32, width_mm=200.0, fold=False, tex=None):
    """Плоская панель (или Г-образный сгиб из двух панелей) мелкой сеткой; одна плитка развёртки. → (геометрия, tx, размер_мм_кадра, x∈[0,1] по занятым текселям)."""
    V, UV, Fc = [], [], []
    for j in range(n + 1):
        for i in range(n + 1):
            u, v = i / n, j / n
            V.append([u, v, 0.0] if not fold or u <= 0.5 else [0.5, v, u - 0.5])
            UV.append([u, v])
    for j in range(n):
        for i in range(n):
            a = j * (n + 1) + i
            Fc += [[a, a + 1, a + n + 2], [a, a + n + 2, a + n + 1]]
    g = {'V': np.array(V, float) * [width_mm, width_mm, width_mm], 'F': np.array(Fc), 'UV': np.array(UV, float), 'tex': tex if tex is not None else np.full((T, T, 3), 128, np.uint8)}
    ctr, size = TF.frame_of([g])
    P = (g['V'] - ctr) / size
    tx = TF.Tex(g, P, T, None, True)
    size_mm = float(size)                       # вершины заданы в мм: нормированная единица = size мм
    x = (tx.Q[:, 0] * size + ctr[0]) / width_mm
    return g, tx, size_mm, x


def lab_field(tx, x, split, l_photo, l_fill, sig_photo, sig_fill, seed=3):
    """Lab по занятым текселям: слева от split — фото (L≈l_photo + фактура σ), справа — заливка (L≈l_fill + фактура σ); фактура — мелкий шум, a=b=0."""
    rs = np.random.RandomState(seed)
    noise = rs.randn(len(x))
    from scipy.ndimage import gaussian_filter
    img = np.zeros(T * T)
    img[tx.ti] = noise
    img = gaussian_filter(img.reshape(T, T), 1.0).reshape(-1)[tx.ti]
    img = img / max(img.std(), 1e-9)
    L = np.where(x < split, l_photo + sig_photo * img, l_fill + sig_fill * img)
    return np.stack([L, np.zeros_like(L), np.zeros_like(L)], 1)


def test_surface_dist():
    print('расстояние по поверхности — через сгиб, не по прямой; дальше предела — inf:')
    g, tx, smm, x = panel(n=32, width_mm=200.0, fold=True)
    ctr, size = TF.frame_of([g])
    pos = tx.Q * size + ctr                                         # мм
    src = pos[:, 0] < 4.0                                           # у левого края первой полки
    d = TS.surface_dist(tx, src, smm, 1000.0)
    far = int(np.argmax(pos[:, 2]))                                 # дальний конец второй полки (вдоль z)
    chord = float(np.linalg.norm(pos[far] - pos[np.argmin(pos[:, 0])]))
    ok(np.isfinite(d[far]) and d[far] > chord * 1.2, 'по поверхности больше, чем по прямой через сгиб', f'{d[far]:.1f} vs хорда {chord:.1f}')
    ok(abs(d[far] - 200.0) < 12.0, 'длина пути вдоль двух полок ≈ 200 мм', f'{d[far]:.1f}')
    ok(np.all(d[src] == 0.0), 'у самих источников — 0')
    ok(np.isinf(TS.surface_dist(tx, src, smm, 20.0)[far]), 'дальше cap — inf')


def run_blend(photo_l, fill_l, sig_p, sig_f, conf=None, cfg=None, parts=None):
    g, tx, smm, x = panel()
    if parts is not None:
        xv = tx.P[:, 0]
        fx = (xv[tx.F].mean(axis=1) - xv.min()) / (xv.max() - xv.min())
        tx.part_f = parts(fx).astype(np.int32)
        tx.part = tx.part_f[tx.f]
    lab = lab_field(tx, x, 0.5, photo_l, fill_l, sig_p, sig_f)
    k0 = x < 0.5
    c = dict(SEAM, **(cfg or {}))
    cf = None if conf is None else conf(x)
    r = TS.blend_seam(tx, lab.copy(), lab.copy(), k0, cf, np.zeros(len(x), bool), c, smm)
    return tx, x, lab, k0, r, c, smm


def metric(tx, lab, solid, s_in, s_out, c, smm):
    tmm = TS.texel_mm(tx, smm)
    img = TS.atlas_with_gutter(tx, TF.lab2rgb(lab), 8)
    return TS.seam_metric(tx, TS.panel_zone(tx, c['crease_deg'], c['normal_smooth_iters'], c['min_panel_faces']), lab, TS.mip1_lab(tx, img, TF.rgb2lab), solid, s_in, s_out, c, smm, tmm, TC.de2000_v)


def test_tone():
    print('② тон: скачок у границы убран, середина фото 1:1, дальняя заливка не тронута:')
    tx, x, lab, k0, r, c, smm = run_blend(50.0, 62.0, 2.0, 2.0)
    s_out0 = TS.surface_dist(tx, k0, smm, 1000.0)
    s_in0 = TS.surface_dist(tx, ~k0, smm, 1000.0)
    m0 = metric(tx, lab, k0, s_in0, s_out0, c, smm)
    m1 = metric(tx, r['lab'], r['solid'], r['s_in'], r['s_out'], c, smm)
    ok(m0['dE00_median'] is not None and m0['dE00_median'] > 6.0, 'до: скачок ΔE00 > 6', str(m0))
    ok(m1['dE00_median'] is not None and m1['dE00_median'] < 2.0, 'после: скачок ΔE00 < 2', str(m1))
    ok(m1['dE00_p95'] < m0['dE00_p95'] / 2, 'p95 вдвое меньше', f"{m0['dE00_p95']} → {m1['dE00_p95']}")
    mid = k0 & (x < 0.4)
    ok(np.array_equal(r['lab'][mid], lab[mid]), 'середина фото 1:1 (ни одной единицы)')
    ok(bool(r['keep'][mid].all()), 'середина фото в «оставить» (keep)')
    far = x > 0.95
    ok(float(np.abs(r['lab'][far, 0] - lab[far, 0]).max()) < 1.0, 'дальняя заливка (> 95 мм от границы) не сдвинута > 1 L', f"{float(np.abs(r['lab'][far, 0] - lab[far, 0]).max()):.2f}")
    near = (x > 0.5) & (x < 0.53)
    ok(abs(float(r['lab'][near, 0].mean() - lab[~near & k0, 0].mean())) < 3.0, 'заливка у границы по тону = фото', f"{float(r['lab'][near, 0].mean()):.1f} vs {float(lab[k0, 0].mean()):.1f}")


def test_crease():
    print('излом панели > crease_deg: поле тона через излом не идёт (другая панель — другой свет); плоская — идёт:')
    g, tx, smm, x = panel(n=32, width_mm=200.0, fold=True)
    ctr, size = TF.frame_of([g])
    pos = tx.Q * size + ctr
    z = TS.panel_zone(tx, 15.0, 3, 4)
    ok(len(np.unique(z)) == 2, 'сгиб 90° — две панели', str(len(np.unique(z))))
    ok(len(np.unique(TS.panel_zone(panel()[1], 15.0, 3, 4))) == 1, 'плоская панель — одна')
    lab = np.zeros((len(pos), 3))
    lab[:, 0] = np.where(pos[:, 0] < 60.0, 50.0, 62.0)             # фото — только на первой полке (x < 60 мм), заливка светлее везде дальше
    k0 = pos[:, 0] < 60.0
    smm_ = smm
    r = TS.blend_seam(tx, lab.copy(), lab.copy(), k0, np.ones(len(pos)), np.zeros(len(pos), bool), dict(SEAM, crease_deg=15.0), smm_)
    arm1 = (~k0) & (pos[:, 2] < 1.0) & (pos[:, 0] < 95.0)
    arm2 = pos[:, 2] > 20.0                                         # вторая полка за изломом
    ok(float(np.abs(r['lab'][arm1, 0] - 62.0).mean()) > 4.0, 'та же панель: заливка подтянута к фото')
    ok(float(np.abs(r['lab'][arm2, 0] - 62.0).max()) < 1e-9, 'за изломом другой панели: не тронута')
    r2 = TS.blend_seam(tx, lab.copy(), lab.copy(), k0, np.ones(len(pos)), np.zeros(len(pos), bool), dict(SEAM, crease_deg=120.0), smm_)
    ok(float(np.abs(r2['lab'][arm2, 0] - 62.0).max()) > 1.0, 'контроль: порог излома 120° — поле идёт и за сгиб')


def test_other_zone():
    print('чужая материальная зона: не граничит с фото — поле не пересекает:')
    tx, x, lab, k0, r, c, smm = run_blend(50.0, 62.0, 2.0, 2.0, parts=lambda x_: np.where(x_ < 0.75, 0, 1).astype(np.int32))
    z2 = x >= 0.75
    ok(float(np.abs(r['lab'][z2] - lab[z2]).max()) < 1e-9, 'зона 1 (вдали от фото) не изменена вовсе')
    z1 = (x > 0.5) & (x < 0.54)
    ok(float(np.abs(r['lab'][z1, 0] - lab[z1, 0]).mean()) > 5.0, 'зона 0 (у границы) подтянута к фото')


def test_contrast():
    print('③ контраст фактуры: заливка приводится к фото; плоскую заливку не оживляем:')
    tx, x, lab, k0, r, c, smm = run_blend(50.0, 50.0, 4.0, 1.5)
    s_out0, s_in0 = TS.surface_dist(tx, k0, smm, 1000.0), TS.surface_dist(tx, ~k0, smm, 1000.0)
    m0 = metric(tx, lab, k0, s_in0, s_out0, c, smm)
    m1 = metric(tx, r['lab'], r['solid'], r['s_in'], r['s_out'], c, smm)
    ok(m0['contrast_ratio'] is not None and m0['contrast_ratio'] < 0.6, 'до: фактура заливки заметно тише фото', str(m0['contrast_ratio']))
    ok(m1['contrast_ratio'] is not None and abs(1.0 - m1['contrast_ratio']) < abs(1.0 - m0['contrast_ratio']) - 0.15, 'после: отношение контраста ближе к 1',
       f"{m0['contrast_ratio']} → {m1['contrast_ratio']}")
    rg = r['report']['contrast']
    ok(all(v['gain'] <= c['contrast_gmax'] + 1e-9 for v in rg.values()), 'усиление не больше contrast_gmax')
    tx2, x2, lab2, k02, r2, c2, smm2 = run_blend(50.0, 50.0, 4.0, 0.0)
    far2 = x2 > 0.6
    ok(float(np.abs(r2['lab'][far2, 0] - lab2[far2, 0]).max()) < 1e-9 and r2['report'].get('contrast', {}) == {} or all(v['gain'] == 1.0 for v in r2['report']['contrast'].values()),
       'плоская заливка не оживляется (gain=1)')


def test_confidence():
    print('① доверие: сомнительные краевые тексели фото заменяются заливкой, надёжные — нет:')
    def conf(x_):
        return np.where((x_ > 0.44) & (x_ < 0.5), 0.1, 1.0)
    tx, x, lab, k0, r, c, smm = run_blend(50.0, 62.0, 2.0, 2.0, conf=conf)
    rim = k0 & (x > 0.44) & (x < 0.5)
    ok(not r['keep'][rim].any(), 'краевые тексели (доверие 0,1) не в «оставить»')
    ok(float(np.abs(r['lab'][rim, 0] - lab[rim, 0]).mean()) > 3.0, 'их цвет заменён (заливка + сдвиг тона)')
    mid = k0 & (x < 0.4)
    ok(np.array_equal(r['lab'][mid], lab[mid]) and r['keep'][mid].all(), 'доверенная середина фото — 1:1')
    ok(r['report']['demoted_texels'] == int(rim.sum()), 'в отчёте число заменённых', str(r['report']['demoted_texels']))
    tx3, x3, lab3, k03, r3, c3, smm3 = run_blend(50.0, 62.0, 2.0, 2.0, conf=lambda x_: np.full(len(x_), 0.55))
    ok(0 < r3['report']['demoted_texels'] == int(k03.sum()) and bool(((r3['lab'][k03, 0] > 50.0 - 12.0)).all()), 'промежуточное доверие — плавное смешивание, не скачок')


def test_fallback_conf():
    print('запасной вход (карты этапа 6 нет): край известного ненадёжен на edge_mm:')
    tx, x, lab, k0, r, c, smm = run_blend(50.0, 62.0, 2.0, 2.0, conf=None, cfg={'edge_mm': 6.0})
    rim = k0 & (x > 0.48)
    ok(r['report']['demoted_texels'] > 0 and not r['keep'][rim & (x > 0.495)].any(), 'тексели у границы известного заменены')
    ok(r['keep'][k0 & (x < 0.4)].all(), 'дальше edge_mm — 1:1')


def test_fill_end_to_end():
    print('сквозной tex_fill.fill: известное (с полным доверием) 1:1, отчёт шва, выключатель в правилах:')
    rs = np.random.RandomState(5)
    base = np.clip(np.stack([np.full((T, T), 150.0)] * 3, -1) + rs.randn(T, T, 1) * 6.0, 0, 255).astype(np.uint8)
    g, tx, smm, x = panel(tex=base)
    known = np.zeros((T, T), bool)
    known.reshape(-1)[tx.ti[x < 0.5]] = True
    g2 = dict(g)
    g2['tex'] = base.copy()
    out = TF.fill([g2], [known], None, cfg={'gutter': 0, 'erode_known': 0, 'seam': {'enabled': True, 'size_mm': smm, 'tone_decay_mm': 25.0}}, mirror=False)
    sm = out['report']['seam']
    ok(sm['enabled'] and len(sm['geoms']) == 1 and sm['geoms'][0]['after']['pairs'] > 0, 'отчёт шва: есть пары до/после', str(sm)[:200])
    mid = np.zeros((T, T), bool)
    mid.reshape(-1)[tx.ti[x < 0.4]] = True
    ok(np.array_equal(out['tex'][0][mid], base[mid]), 'середина фото 1:1 после fill')
    ok(bool(out['keep'][0].reshape(-1)[tx.ti[x < 0.4]].all()), 'keep содержит середину фото')
    off = TF.fill([g2], [known], None, cfg={'gutter': 0, 'erode_known': 0, 'seam': {'enabled': False}}, mirror=False)
    ok(off['report']['seam'] == {'enabled': False}, 'seam.enabled=false — шов не трогаем, прежнее поведение')


def test_feather():
    print('граница по мм: лесенка блоков фото-растра сглаживается, середина фото 1:1, выключено — прежнее:')
    g, tx, smm, x = panel(n=96, width_mm=400.0)
    col, row = tx.ti % T, tx.ti // T
    cw = 400.0 / T                                                       # мм на тексел (панель = вся развёртка T×T)
    step = ((row // 6) % 2).astype(int)                                  # блоки по 6 строк: граница по колонке 64 или 67 (лесенка ≈ 9 мм)
    k0 = col < 64 + 3 * step
    lab = np.zeros((len(col), 3))
    lab[:, 0] = np.where(k0, 50.0, 62.0)
    base = dict(SEAM, feather_mm=0.0)
    off = TS.blend_seam(tx, lab.copy(), lab.copy(), k0, np.ones(len(col)), np.zeros(len(col), bool), base, smm)
    ro = off['report']
    ok(ro['rough_before']['rough_rms_mm'] > 3.0, 'лесенка есть: шероховатость границы до > 3 мм', str(ro['rough_before']))
    ok(abs(ro['rough_after']['rough_rms_mm'] - ro['rough_before']['rough_rms_mm']) < 1e-6, 'feather_mm=0 — граница как была', str(ro['rough_after']))
    on = TS.blend_seam(tx, lab.copy(), lab.copy(), k0, np.ones(len(col)), np.zeros(len(col), bool), dict(base, feather_mm=10.0), smm)
    rn = on['report']
    ok(rn['rough_after']['rough_rms_mm'] < 0.7 * rn['rough_before']['rough_rms_mm'], 'с feather: шероховатость границы упала > 30 %', f"{rn['rough_before']['rough_rms_mm']} -> {rn['rough_after']['rough_rms_mm']}")
    deep = col < 30
    ok(float(np.abs(on['lab'][deep, 0] - 50.0).max()) < 1e-9 and bool(on['keep'][deep].all()), 'середина фото (далеко от границы) 1:1 и в keep')
    far = col > 100
    ok(float(np.abs(on['lab'][far, 0] - lab[far, 0]).max()) < 2.0, 'далёкая заливка не тронута feather')
    mid = (col >= 64) & (col < 66) & (step == 0)
    ok(float(on['lab'][mid, 0].mean()) < 62.0 - 1.0, 'заливка у границы плавно подтянута к фото (вытяжка фото в заливку)', f"{float(on['lab'][mid, 0].mean()):.1f}")


def test_reflect():
    print('фактура фото продолжается в гладкую заливку (отражение через границу), живая заливка и дальняя часть не трогаются:')
    g, tx, smm, x = panel(n=96, width_mm=400.0)
    col = tx.ti % T
    rng = np.random.default_rng(5)
    k0 = col < 64
    lab = np.zeros((len(col), 3))
    lab[:, 0] = np.where(k0, 55.0 + rng.normal(0, 4.0, len(col)), 55.0)          # слева фото с фактурой, справа гладкая заливка
    cw = 400.0 / T
    c = dict(SEAM, feather_mm=0.0, reflect=True, reflect_reach_mm=40.0, contrast_decay_mm=40.0, contrast_gmin=1.0, contrast_gmax=1.0, tone_max=[0.0, 0.0, 0.0])
    out = TS.blend_seam(tx, lab.copy(), lab.copy(), k0, np.ones(len(col)), np.zeros(len(col), bool), c, smm)
    rp = out['report'].get('reflect') or {}
    ok(rp.get('applied', 0) > 0, 'отражение нашло пары по ту сторону границы', str(rp))
    near = (col >= 64) & (col < 64 + int(15.0 / cw))
    far = col >= 64 + int(60.0 / cw)
    ok(float(out['lab'][near, 0].std()) > 1.0, 'гладкая заливка у границы получила фактуру', f"{float(out['lab'][near, 0].std()):.2f}")
    ok(float(np.abs(out['lab'][far, 0] - 55.0).max()) < 1e-9, 'далёкая заливка не тронута отражением')
    ok(float(np.abs(out['lab'][k0, 0] - lab[k0, 0]).max()) < 1e-9, 'середина фото не тронута')
    c2 = dict(c, reflect=False)
    off = TS.blend_seam(tx, lab.copy(), lab.copy(), k0, np.ones(len(col)), np.zeros(len(col), bool), c2, smm)
    ok(float(np.abs(off['lab'][near, 0] - 55.0).max()) < 1e-9, 'reflect=false — заливка как была')


def test_rules():
    print('правила — в rules/paint-fill.json:')
    s = TF.RULES['seam']
    ok(all(k in s for k in ('conf_min', 'conf_full', 'probe_mm', 'tone_decay_mm', 'contrast_gmax', 'de_bad', 'poisson', 'feather_mm', 'rough_sigma_mm', 'reflect', 'accept_p95_abs')), 'блок seam полон')
    ok(s['poisson'] is False, 'Пуассон выключен (только если скачок остаётся после ③)')
    ok(0.0 < s['conf_min'] < s['conf_full'] <= 1.0, 'conf_min < conf_full')


def main():
    for f in (test_surface_dist, test_tone, test_crease, test_other_zone, test_contrast, test_confidence, test_fallback_conf, test_fill_end_to_end, test_feather, test_reflect, test_rules):
        print(f.__name__)
        f()
    print(f'tests_tex_seam: ошибок {bad}')
    return 1 if bad else 0


if __name__ == '__main__':
    raise SystemExit(main())
