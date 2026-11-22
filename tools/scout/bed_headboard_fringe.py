#!/usr/bin/env python3
"""Сторож `bed_headboard_fringe` (кровать): гало цвета подушки над подушками на лицевой плоскости мягкого изголовья (T-20261119-106, П1.98).

ДЕФЕКТ. Родная покраска Hunyuan3D-2.1 печёт текстуру из нескольких видов; подушка закрывает изголовье — и белый цвет подушки «натекает» на
текселы плиты у подушек: в окне 3D и на фото «Сделать фото» над подушками светлые «облачка»/бахрома. Геометрия чистая (в сером материале
плита гладкая), поэтому мера — по ЦВЕТУ текселей, а не по вершинам (на плоской плите вершин мало, рисунок живёт в текстуре).

ПРАВИЛО v3 (mode: observe — только вердикт в отчёт, ничего не блокирует). Точки берутся по поверхности (цвет — из текстуры по UV);
плита = точки лицевой плоскости изголовья; полоса = от верха матраса (вдали от плиты) до верха подушки + `band_above_pillow_m` в каждой из
`bins` ячеек ширины; эталон = плита выше подушек. Признак ячейки — светлота L* полосы минус светлота эталона.
Флаг `fringe`: доля ячеек с ΔL ≥ `dl_min` ≥ `share_min` И разброс ΔL по ячейкам (p90−p10) ≥ `spread_min` (рваный/облачный вид, а не ровная
полоса дизайна) И эталон малоузорный (MAD светлоты ≤ `ref_mad_max`). Нет участка плиты выше подушек, нет подушек или ячеек мало —
`not_applicable` (это НЕ «чисто»: низкие/ажурные изголовья и платформы сторож не оценивает).

ТОЧНОСТЬ (31 кровать из mesh3d-cache, счёт глазами 22.11): явные 2/2 пойманы; ложных 1 из 22 оценённых «нет» (решётчатая вставка — на пороге MAD:
2,1 при пороге 3); слабые 0/2 (тёмная кайма и малый контраст не ловятся); `not_applicable` 11/31 ≈ 35 %. Пороги — ТОЛЬКО в `THRESHOLDS`.

  python tools/scout/bed_headboard_fringe.py --selftest
  python tools/scout/bed_headboard_fringe.py <model.glb> [...]       # вердикт JSON по каждому файлу (нужен trimesh)
"""
import json
import os
import sys

import numpy as np

MODE = 'observe'

# Единственное место порогов (ID товаров в коде нет).
THRESHOLDS = {
    'dl_min': 8.0,              # ΔL* полосы над эталоном, с которого ячейка «светлая»
    'share_min': 0.15,          # доля светлых ячеек для флага
    'spread_min': 8.0,          # разброс ΔL по ячейкам (p90−p10): рваное, не ровная полоса
    'ref_mad_max': 3.0,         # эталон малоузорный (MAD светлоты L*)
    'bins': 40,                 # ячеек по ширине изголовья
    'min_bins': 5,              # меньше оценённых ячеек — неприменимо
    'min_bin_pts': 30,          # точек в полосе ячейки
    'min_ref_pts': 100,         # точек эталона
    'plane_tol_m': 0.03,        # толщина слоя лицевой плоскости
    'prot_gap_m': 0.04,         # вынос от плоскости, с которого точка — матрас/подушка
    'far_gap_m': 0.5,           # «вдали от плиты» — для верха матраса
    'band_above_pillow_m': 0.05,
    'ref_above_pillow_m': 0.03,
    'upper_share': 0.62,        # «верх» изголовья — выше этой доли высоты
    'n_points': 400_000,
}


def _lstar(rgb):
    """CIE L* из sRGB 0–1 (N×3)."""
    c = np.asarray(rgb, float).reshape(-1, 3)
    lin = np.where(c > 0.04045, ((c + 0.055) / 1.055) ** 2.4, c / 12.92)
    y = lin @ np.array([0.2126729, 0.7151522, 0.0721750])
    f = np.where(y > 216 / 24389, np.cbrt(y), (24389 / 27 * y + 16) / 116)
    return 116 * f - 16


def analyze(P, rgb, th=None):
    """P — точки поверхности (N×3, Y вверх), rgb — их цвет (N×3, 0–1). → dict: verdict ('fringe'|'ok'|'not_applicable'), поля меры."""
    th = {**THRESHOLDS, **(th or {})}
    P = np.asarray(P, float)
    L = _lstar(rgb)
    lo, hi = P.min(0), P.max(0)
    H = float(hi[1] - lo[1])
    if H <= 0:
        return {'verdict': 'not_applicable', 'why': 'нет высоты'}
    y = (P[:, 1] - lo[1]) / H
    up = y > th['upper_share']
    if up.sum() < 50:
        return {'verdict': 'not_applicable', 'why': 'нет верха изголовья'}
    ax = 0 if np.ptp(P[up, 0]) < np.ptp(P[up, 2]) else 2     # ось глубины изголовья — где верх тоньше
    hx = 2 if ax == 0 else 0
    p = float(np.median(P[up, ax]))
    mid = (y > 0.25) & (y < 0.5)
    sgn = 1.0 if P[mid, ax].mean() > p else -1.0              # сторона кровати
    d = sgn * (P[:, ax] - p)
    dfront = float(np.percentile(d[up], 90))                  # лицевая плоскость
    plane = (np.abs(d - dfront) < th['plane_tol_m']) & (y > 0.2)
    prot = (d > dfront + th['prot_gap_m']) & (y < 0.8)        # матрас и подушки
    nb = int(th['bins'])
    edges = np.linspace(lo[hx], hi[hx], nb + 1)
    bi = np.clip(np.digitize(P[:, hx], edges) - 1, 0, nb - 1)
    top = np.full(nb, np.nan)
    for b in range(nb):
        m = prot & (bi == b)
        if m.sum() > 20:
            top[b] = P[m, 1].max()
    if not np.isfinite(top).any():
        return {'verdict': 'not_applicable', 'why': 'нет подушек/матраса'}
    gtop = float(np.nanmax(top))
    far = (d > dfront + th['far_gap_m']) & (y > 0.25) & (y < 0.8)
    ytm = float(np.percentile(P[far, 1], 95)) if far.sum() > 100 else float(lo[1] + 0.4 * H)   # верх матраса вдали от плиты
    ref_m = plane & (P[:, 1] > gtop + th['ref_above_pillow_m'])
    if ref_m.sum() < th['min_ref_pts']:
        return {'verdict': 'not_applicable', 'why': 'нет плиты выше подушек для эталона'}
    ref = float(np.median(L[ref_m]))
    ref_mad = float(1.4826 * np.median(np.abs(L[ref_m] - ref)))
    dls = []
    for b in range(nb):
        if not np.isfinite(top[b]):
            continue
        m = plane & (bi == b) & (P[:, 1] > ytm) & (P[:, 1] < top[b] + th['band_above_pillow_m'])
        if m.sum() < th['min_bin_pts']:
            continue
        dls.append(float(np.median(L[m]) - ref))
    if len(dls) < th['min_bins']:
        return {'verdict': 'not_applicable', 'why': 'мало оценённых ячеек', 'bins_used': len(dls)}
    s = np.sort(dls)
    n = len(s)
    share = float((s >= th['dl_min']).mean())
    spread = float(s[(9 * n) // 10] - s[n // 10])
    flag = share >= th['share_min'] and spread >= th['spread_min'] and ref_mad <= th['ref_mad_max']
    return {'verdict': 'fringe' if flag else 'ok', 'share_light': round(share, 3), 'spread_dl': round(spread, 1),
            'ref_mad_l': round(ref_mad, 2), 'ref_l': round(ref, 1), 'bins_used': n}


def scan_glb(path, th=None):
    """Вердикт по GLB: точки по поверхности (seed фиксирован), цвет из текстуры по UV (trimesh)."""
    import trimesh
    s = trimesh.load(path)
    gs = list(s.geometry.values()) if hasattr(s, 'geometry') else [s]
    g = trimesh.util.concatenate(gs) if len(gs) > 1 else gs[0]
    n = int((th or {}).get('n_points', THRESHOLDS['n_points']))
    P, fi = trimesh.sample.sample_surface(g, n, seed=1)
    V = np.asarray(g.vertices)
    bc = trimesh.triangles.points_to_barycentric(V[g.faces[fi]], P)
    uv = (bc[:, :, None] * np.asarray(g.visual.uv)[g.faces[fi]]).sum(1)
    rgb = np.asarray(g.visual.material.to_color(uv))[:, :3].astype(float) / 255
    return analyze(P, rgb, th)


def _synthetic(band_light, band_ragged=False, openwork=False, seed=0):
    """Синтетическая кровать (м, Y вверх, глубина Z): плита изголовья z≈0, матрас вдоль +Z до 2 м, две подушки у плиты."""
    r = np.random.default_rng(seed)
    pts, cols = [], []

    def add(n, x, yy, z, rgb):
        pts.append(np.column_stack([r.uniform(*x, n), r.uniform(*yy, n), r.uniform(*z, n)]))
        cols.append(np.tile(rgb, (n, 1)) if not callable(rgb) else rgb(pts[-1]))

    grey = (0.55, 0.55, 0.55)
    if openwork:      # ажурное изголовье: плиты нет, только две тонкие стойки до 1,2 м
        for x in (-0.8, 0.8):
            add(30, (x, x), (0.0, 1.2), (0.0, 0.0), grey)
    else:
        add(40000, (-0.8, 0.8), (0.0, 1.2), (0.0, 0.0), grey)                      # плита (лицо z=0)
    add(30000, (-0.8, 0.8), (0.4, 0.4), (0.0, 2.0), (0.8, 0.8, 0.8))               # верх матраса
    for x0, x1 in ((-0.7, -0.05), (0.05, 0.7)):
        add(8000, (x0, x1), (0.55, 0.55), (0.05, 0.45), (0.95, 0.95, 0.95))         # верх подушек, до y=0.55
        add(6000, (x0, x1), (0.4, 0.55), (0.45, 0.45), (0.95, 0.95, 0.95))          # лицевой торец подушки (вынос от плиты)
        add(6000, (x0, x1), (0.4, 0.55), (0.05, 0.05), (0.95, 0.95, 0.95))          # торец подушки у плиты (вне плиты: z>0)
    # светлая полоса на плите над матрасом, до верха подушек и чуть выше
    if band_light:
        def paint(p):
            c = np.tile(grey, (len(p), 1))
            on = np.ones(len(p), bool) if not band_ragged else (np.floor((p[:, 0] + 0.8) / 1.6 * 40) % 2 == 0)
            c[on] = (0.85, 0.85, 0.85)
            return c
        add(12000, (-0.8, 0.8), (0.41, 0.58), (0.0, 0.0), paint)
    return np.vstack(pts), np.vstack(cols)


def selftest():
    fails = 0

    def ok(name, cond):
        nonlocal fails
        print(('ok   ' if cond else 'FAIL ') + name)
        fails += 0 if cond else 1

    P, C = _synthetic(band_light=False)
    ok('чистая плита → ok', analyze(P, C)['verdict'] == 'ok')
    P, C = _synthetic(band_light=True, band_ragged=False)
    r = analyze(P, C)
    ok('ровная светлая полоса → нет флага', r['verdict'] == 'ok' and r['spread_dl'] < THRESHOLDS['spread_min'])
    P, C = _synthetic(band_light=True, band_ragged=True)
    ok('рваная светлая полоса → fringe', analyze(P, C)['verdict'] == 'fringe')
    P, C = _synthetic(band_light=True, band_ragged=True, openwork=True)
    r = analyze(P, C)
    ok('ажурное изголовье, нет плиты для эталона → not_applicable (не ok)', r['verdict'] == 'not_applicable')
    ok('пороги заданы словарём (ID товаров нет)', all(isinstance(v, (int, float)) for v in THRESHOLDS.values()) and MODE == 'observe')
    print('FAILS:', fails)
    return fails


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        sys.exit(1 if selftest() else 0)
    for f in sys.argv[1:]:
        try:
            print(json.dumps({'file': os.path.basename(f), 'mode': MODE, **scan_glb(f)}, ensure_ascii=False))
        except Exception as e:
            print(json.dumps({'file': os.path.basename(f), 'mode': MODE, 'error': repr(e)[:160]}, ensure_ascii=False))
