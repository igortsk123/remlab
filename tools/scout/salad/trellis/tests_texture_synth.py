#!/usr/bin/env python3
"""Тесты синтеза фактуры невидимого `texture_synth.py` (T-20261123-39): синтетика, без сети и видеокарты, ID товаров нет.
Проверяется: энергия синтеза ≈ энергии фото (0,5–1,5); направление полос донора сохраняется; поворот цели (угол «вверх мира») поворачивает полосы; масштаб плотности атласа меняет длину волны;
швы не крупнее собственного градиента донора; нет чистого донора → гладко (0), не шум; выбросы-детали не попадают в донор (у узора — остаются); одинаковый seed → тот же результат;
карта «вверх мира» по граням (вертикальная — угол, горизонтальная — nan); пороги — в rules/paint-fill.json (surface_groups.synth).

  python3 tools/scout/salad/trellis/tests_texture_synth.py"""
from __future__ import annotations

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.normpath(os.path.join(HERE, '..', '..')))
import remlab_tmp  # noqa: E402
remlab_tmp.use('tests_texture_synth')
import numpy as np  # noqa: E402
import texture_synth as TS  # noqa: E402

bad = 0


def ok(cond, name, extra=''):
    global bad
    print(('  ✓ ' if cond else '  ✗ ') + name + (f' — {extra}' if extra and not cond else ''))
    bad += 0 if cond else 1


T = 256
CFG = {'low_px': 6.0, 'patch_px': 32, 'overlap_px': 8, 'min_donor_px': 4000, 'donor_erode_px': 3, 'clip_k': 3.0, 'chroma_max': 8.0, 'n_cand': 24, 'tol': 0.1, 'min_cover': 0.9}


def blur_norm(img, known, sigma):
    from scipy.ndimage import gaussian_filter
    w = known.astype(np.float64)
    den = gaussian_filter(w, sigma, mode='nearest')
    return np.stack([gaussian_filter(img[..., k] * w, sigma, mode='nearest') for k in range(img.shape[-1])], -1) / np.maximum(den, 1e-9)[..., None]


def stripes(theta_deg: float, lam: float = 9.0, amp: float = 3.0) -> np.ndarray:
    """Остаток L: полосы, чьё ГРАДИЕНТНОЕ направление — theta (градусы, от оси x к y в пикселях)."""
    y, x = np.mgrid[0:T, 0:T].astype(np.float64)
    th = np.radians(theta_deg)
    return amp * np.sin(2 * np.pi * (x * np.cos(th) + y * np.sin(th)) / lam)


def lab_of(res_L, tone=(60.0, 5.0, 10.0)):
    lab = np.zeros((T, T, 3), np.float64)
    lab[..., 0], lab[..., 1], lab[..., 2] = tone[0] + res_L, tone[1], tone[2]
    return lab


def grad_angle(img_L, mask) -> float:
    """Доминантное направление градиента (структурный тензор), градусы по модулю 180."""
    gy, gx = np.gradient(img_L)
    m = mask
    jxx, jyy, jxy = (gx[m] ** 2).sum(), (gy[m] ** 2).sum(), (gx[m] * gy[m]).sum()
    return float(np.degrees(0.5 * np.arctan2(2 * jxy, jxx - jyy)) % 180.0)


def adiff(a, b) -> float:
    d = abs(a - b) % 180.0
    return min(d, 180.0 - d)


def peak_wavelength(img_L, mask) -> float:
    """Длина волны по пику спектра внутри прямоугольника, целиком лежащего в маске."""
    ys, xs = np.nonzero(mask)
    sub = img_L[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    n = min(sub.shape)
    sub = sub[:n, :n] - sub[:n, :n].mean()
    f = np.abs(np.fft.fftshift(np.fft.fft2(sub * np.hanning(n)[:, None] * np.hanning(n)[None, :])))
    f[n // 2, n // 2] = 0
    iy, ix = np.unravel_index(np.argmax(f), f.shape)
    fr = np.hypot((iy - n // 2) / n, (ix - n // 2) / n)
    return 1.0 / max(fr, 1e-9)


known = np.zeros((T, T), bool)
known[:, :120] = True
target = np.zeros((T, T), bool)
target[16:T - 16, 136:T - 16] = True                              # цель правее зазора: донор и цель не соприкасаются

print('1. квилтинг: энергия и направление полос сохраняются')
for th in (0.0, 35.0, 90.0):
    lab = lab_of(stripes(th))
    res, info = TS.synth_group(lab, known, target, None, CFG, blur_norm, seed=3)
    L = res[..., 0]
    done = L != 0
    er = info.get('energy_ratio')
    ok(info['mode'] == 'quilt' and er is not None and 0.5 <= er <= 1.5, f'th={th}: энергия синтеза / донора {er} (цель 0,5–1,5)', str(info))
    inner = target.copy()
    inner[:, :146] = False
    ok(adiff(grad_angle(L, inner), grad_angle(lab[..., 0], known)) < 15.0, f'th={th}: направление полос сохранено ({grad_angle(L, inner):.0f}° против {grad_angle(lab[..., 0], known):.0f}°)')
    ok(info['covered'] >= 0.9, f"th={th}: накрыто {info['covered']}")

print('2. швы не крупнее собственного градиента донора')
lab = lab_of(stripes(35.0))
res, info = TS.synth_group(lab, known, target, None, CFG, blur_norm, seed=3)
gy, gx = np.gradient(res[..., 0])
gm = np.hypot(gx, gy)
gd = np.hypot(*np.gradient(lab[..., 0] - blur_norm(lab, known, 6.0)[..., 0]))
inn = target.copy()
inn[:3] = inn[-3:] = False
inn[:, :140] = False
p95s, p95d = float(np.percentile(gm[inn], 95)), float(np.percentile(gd[known & (np.arange(T)[None, :] > 6)], 95))
ok(p95s <= 1.6 * p95d, f'p95 градиента синтеза {p95s:.2f} ≤ 1.6 × донора {p95d:.2f}')

print('3. поворот цели и масштаб плотности')
ang_d = np.full((T, T), 0.0)                                       # у донора «вверх» = 0°
ang_t = np.full((T, T), np.pi / 2)                                 # у цели «вверх» повёрнуто на 90° → полосы должны повернуться на 90°
dens = np.ones((T, T))
lab = lab_of(stripes(0.0))
ang_map = np.where(known, ang_d, ang_t)
res, info = TS.synth_group(lab, known, target, {'angle': ang_map, 'dens': dens}, CFG, blur_norm, seed=3)
inner = target.copy()
inner[:, :146] = False
a_s = grad_angle(res[..., 0], inner)
ok(adiff(a_s, 90.0) < 15.0, f'цель повёрнута на 90° → полосы {a_s:.0f}° (ожидалось ≈ 90°)')
dens2 = np.where(known, 1.0, 2.0)
res, info = TS.synth_group(lab, known, target, {'angle': np.zeros((T, T)), 'dens': dens2}, CFG, blur_norm, seed=3)
inner2 = np.zeros((T, T), bool)
inner2[24:88, 150:214] = True
lam_t = peak_wavelength(res[..., 0], inner2)
ok(abs(lam_t - 18.0) < 4.0, f'плотность цели вдвое выше → длина волны {lam_t:.1f} px (ожидалось ≈ 18 при 9 у донора)')

print('4. нет чистого донора → честно гладко')
small = np.zeros((T, T), bool)
small[100:110, 100:110] = True
res0, info0 = TS.synth_group(lab_of(stripes(0.0)), small, target, None, CFG, blur_norm)
ok(info0['mode'] == 'smooth' and not np.any(res0) and 'донора' in info0['why'], f"мало донора ({info0['donor_px']}) → остаток 0, mode smooth")
res0, info0 = TS.synth_group(lab_of(stripes(0.0)), known, np.zeros((T, T), bool), None, CFG, blur_norm)
ok(info0['mode'] == 'smooth' and 'нет невидимого' in info0['why'], 'нечего синтезировать → smooth')

print('4б. рваный донор (дырки от выбросов): куски нужного размера не находятся — недокрытое добирается мельче')
from scipy.ndimage import gaussian_filter  # noqa: E402
holes = gaussian_filter(np.random.RandomState(1).randn(T, T), 4) > 0.45
known_h = known & ~holes
cfg_big = dict(CFG, patch_px=96, overlap_px=24, min_donor_px=2000)
resh, infoh = TS.synth_group(lab_of(stripes(0.0)), known_h, target, None, cfg_big, blur_norm, seed=5)
ok(infoh['mode'] == 'quilt' and infoh['covered'] >= 0.9 and len(infoh['patch_levels_px']) >= 2, f"рваный донор: накрыто {infoh.get('covered')} кусками {infoh.get('patch_levels_px')}")
ok(0.5 <= infoh['energy_ratio'] <= 1.5, f"энергия при рваном доноре {infoh['energy_ratio']} (цель 0,5–1,5)")

print('5. выбросы-детали (контур ручки) не в доноре; у узора — остаются')
lab = lab_of(stripes(0.0))
lab[60:70, 40:50, 0] -= 40.0                                       # тёмная деталь на известном
res_d, clean, sig = TS.donor_residual(lab, known, 6.0, 3, 3.0, 8.0, False, blur_norm)
ok(not clean[62:68, 42:48].any() and clean[100:110, 60:70].any(), 'деталь исключена из чистого донора, окрестный фон остался')
res_d, clean_k, sig = TS.donor_residual(lab, known, 6.0, 3, 99.0, 8.0, True, blur_norm)
ok(clean_k[62:68, 42:48].any(), 'у узора (keep_detail) тёмная деталь остаётся в доноре')
lab_c = lab.copy()
lab_c[60:70, 40:50, 1] += 40.0
_, clean_c, _ = TS.donor_residual(lab_c, known, 6.0, 3, 99.0, 8.0, True, blur_norm)
ok(not clean_c[62:68, 42:48].any(), 'чужая цветность (бежевые точки) выбрасывается и у узора')

print('6. детерминированность')
lab = lab_of(stripes(20.0))
r1, _ = TS.synth_group(lab, known, target, None, CFG, blur_norm, seed=11)
r2, _ = TS.synth_group(lab, known, target, None, CFG, blur_norm, seed=11)
r3, _ = TS.synth_group(lab, known, target, None, CFG, blur_norm, seed=12)
ok(np.array_equal(r1, r2) and not np.array_equal(r1, r3), 'тот же seed — тот же результат, другой — другой')

print('7. карта «вверх мира» и плотности по граням')
V = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]], float)      # вертикальный квадрат в плоскости XY: u→X, v→Y (вверх)
F = np.array([[0, 1, 2], [0, 2, 3]])
UV = np.array([[0.25, 0.25], [0.75, 0.25], [0.75, 0.75], [0.25, 0.75]])
ids = np.full((64, 64), -1, np.int64)
ids[16:48, 16:32] = 0
ids[16:48, 32:48] = 1
mp = TS.uv_field_maps(V, F, UV, ids, 64)
a = mp['angle'][20:40, 20:28]
ok(np.allclose(a[~np.isnan(a)], -np.pi / 2, atol=0.05) and not np.isnan(a).any(), f'вертикальная грань: «вверх мира» в атласе — вверх по экрану (−90°): {np.nanmean(a):.2f} рад')
ok(abs(float(mp['dens'][30, 24]) - 32.0) < 1.0, f"плотность {float(mp['dens'][30, 24]):.1f} px на единицу (ожидалось 32)")
Vh = np.array([[0, 0, 0], [1, 0, 0], [1, 0, 1], [0, 0, 1]], float)      # горизонтальный квадрат (плоскость XZ): направления «вверх» нет
mph = TS.uv_field_maps(Vh, F, UV, ids, 64)
ok(np.isnan(mph['angle'][20:40, 20:28]).all(), 'горизонтальная грань → направления нет (nan), патч без поворота')

print('8. пороги — в данных, ID товаров нет')
RULES = os.path.normpath(os.path.join(HERE, '..', '..', 'rules', 'paint-fill.json'))
sg = json.load(open(RULES, encoding='utf-8'))['surface_groups']['synth']
need = ('low_px', 'patch_px', 'overlap_px', 'min_donor_px', 'donor_erode_px', 'clip_k', 'chroma_max', 'n_cand', 'tol', 'min_cover')
ok(sg['enabled'] is True and all(k in sg['common'] for k in need) and 'узор' in sg['by_class'], 'surface_groups.synth: common + by_class[узор], включено')
ok(sg['by_class']['узор']['patch_px'] > sg['common']['patch_px'], 'у узора кусок крупнее (рисунок крупнее зерна)')
src = open(os.path.join(HERE, 'texture_synth.py'), encoding='utf-8').read()
ok(not re.search(r'\b\d{5,6}_\d{6,}\b', src + open(RULES, encoding='utf-8').read()), 'ID товаров в коде и правилах нет')
print('tests_texture_synth: ошибок', bad)
sys.exit(1 if bad else 0)
