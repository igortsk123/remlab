#!/usr/bin/env python3
"""Мерка «угол прямой кромки силуэта: рендер камеры 04 ↔ фото» (T-20261124-18, перекос ТВ-тумбы 7736).

Зачем: цель подгонки камеры 04 — IoU силуэта; клин вдоль верхней кромки (±40 px на 1000 px = 2°) почти не меняет IoU, но этап 06 переносит фото по этой камере, и на форме
появляется «кривая» полоса цвета верха (фасад съезжает вдоль кромки). Здесь сравнивается УГОЛ прямой кромки силуэта (верх, лево, право) у рендера и у фото — в кадре камеры 04.

Кромка берётся по маске столбцов/строк средних 70 % габарита; прямая — по Тейлу–Сену (устойчива к ручкам и ножкам); «прямая» = остаток по прямой ≤ straight_px, иначе кромка не меряется
(кривой верх стула, лампа, вогнутость — не наша мерка, не отказ). Сторона без прямых кромок → measured=False (n/a, не 0).
Пороги — только из rules/camera-check.json: edge_angle (гипотеза до знаменателя на кругах; enforce=false: пишется, не отбраковывает). Чистый numpy.

    python tools/scout/silhouette_edge_angle.py --selftest
"""
import json
import os

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULTS = {'enabled': True, 'enforce': False, 'max_abs_deg': 0.5, 'span': [0.15, 0.85], 'straight_px': 3.0, 'min_len_frac': 0.35, 'min_len_px': 40, 'report_top_deg': 1.0}


def rules(R: dict | None = None) -> dict:
    """Блок `edge_angle` из camera-check.json (R — весь файл или сам блок; None — прочитать файл)."""
    if R is None:
        try:
            R = json.load(open(os.path.join(HERE, "..", "..", "rules", "camera-check.json"), encoding='utf-8'))
        except (OSError, ValueError):
            R = {}
    blk = R.get('edge_angle', R) if isinstance(R, dict) else {}
    return {**DEFAULTS, **{k: v for k, v in blk.items() if k in DEFAULTS}}


def theil_sen(a: np.ndarray, b: np.ndarray, max_pairs: int = 4000) -> tuple[float, float]:
    """Прямая b = k·a + c, устойчивая к выбросам (медиана попарных наклонов; пары — детерминированная подвыборка)."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    n = len(a)
    if n < 3:
        return 0.0, float(b.mean()) if n else 0.0
    rng = np.random.default_rng(0)
    i = rng.integers(0, n, max_pairs)
    j = rng.integers(0, n, max_pairs)
    ok = np.abs(a[i] - a[j]) > 1e-9
    k = float(np.median((b[i][ok] - b[j][ok]) / (a[i][ok] - a[j][ok]))) if ok.any() else 0.0
    return k, float(np.median(b - k * a))


def _boundary(mask: np.ndarray, side: str, span: tuple) -> tuple[np.ndarray, np.ndarray, float] | None:
    """Точки кромки (a — вдоль кромки, b — поперёк) по средним `span` габарита; side: top | left | right. → (a, b, длина габарита вдоль кромки) | None."""
    m = np.asarray(mask, bool)
    if side in ('left', 'right'):
        m = m.T
    ys, xs = np.nonzero(m)
    if len(xs) < 50:
        return None
    x0, x1, y0, y1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
    L = float(x1 - x0)
    lo, hi = int(x0 + span[0] * L), int(x0 + span[1] * L)
    A, B = [], []
    for x in range(lo, hi):
        col = np.nonzero(m[:, x])[0]
        if len(col):
            A.append(x)
            B.append(col.min() if side != 'right' else col.max())
    if len(A) < 10:
        return None
    return np.array(A, float), np.array(B, float), L


def edge_angle(mask: np.ndarray, side: str, R: dict | None = None) -> dict:
    """Угол прямой кромки (градусы; верх — наклон y по x, бока — наклон x по y). {'ok': False, 'why'} — кромка не прямая/короткая."""
    r = rules(R)
    bd = _boundary(mask, side, tuple(r['span']))
    if bd is None:
        return {'ok': False, 'why': 'нет кромки'}
    a, b, L = bd
    if L < r['min_len_px'] or (a.max() - a.min() + 1) < r['min_len_frac'] * L:
        return {'ok': False, 'why': 'кромка короткая'}
    k, c = theil_sen(a, b)
    res = np.abs(b - (k * a + c))
    inl = res <= r['straight_px']
    if inl.mean() < 0.7:
        return {'ok': False, 'why': f'не прямая: {100 * (1 - inl.mean()):.0f} % точек дальше {r["straight_px"]} px'}
    k2, _c2 = theil_sen(a[inl], b[inl])
    return {'ok': True, 'deg': float(np.degrees(np.arctan(k2))), 'n': int(len(a)), 'inlier': round(float(inl.mean()), 3)}


def compare(render_mask: np.ndarray, photo_mask: np.ndarray, R: dict | None = None) -> dict:
    """Δугла по сторонам (фото − рендер) в кадре камеры 04. measured=False, если ни одна сторона не прямая у ОБОИХ. max_abs_deg — по меряемым; passed — против порога (None, если не меряется)."""
    r = rules(R)
    out, sides = {}, []
    for side in ('top', 'left', 'right'):
        a, b = edge_angle(render_mask, side, r), edge_angle(photo_mask, side, r)
        if a['ok'] and b['ok']:
            d = b['deg'] - a['deg']
            out[side] = {'render_deg': round(a['deg'], 2), 'photo_deg': round(b['deg'], 2), 'delta_deg': round(d, 2)}
            sides.append(abs(d))
        else:
            out[side] = {'skip': a.get('why') if not a['ok'] else 'фото: ' + str(b.get('why'))}
    res = {'sides': out, 'measured': bool(sides), 'max_abs_deg': round(max(sides), 2) if sides else None, 'threshold_deg': r['max_abs_deg'], 'enforce': bool(r['enforce'])}
    res['passed'] = (res['max_abs_deg'] <= r['max_abs_deg']) if sides else None
    t = out.get('top', {}).get('delta_deg')                                  # порог ОТЧЁТА (директор 24.11): верх 1,0°, бока — пока только число
    res['top_over_report'] = None if t is None else bool(abs(t) > r['report_top_deg'])
    res['report_top_deg'] = r['report_top_deg']
    return res


def selftest() -> int:
    import sys
    bad = 0

    def ok(c, name):
        nonlocal bad
        print(('  ✓ ' if c else '  ✗ ') + name)
        bad += 0 if c else 1

    H = 600
    yy, xx = np.mgrid[0:H, 0:H]

    def box(k_deg=0.0):
        top = 150 + (xx - 100) * np.tan(np.radians(k_deg))
        return (xx >= 100) & (xx < 500) & (yy >= top) & (yy < 400)

    a = edge_angle(box(0.0), 'top')
    ok(a['ok'] and abs(a['deg']) < 0.05, f'ровный верх → 0° ({a})')
    a = edge_angle(box(2.0), 'top')
    ok(a['ok'] and abs(a['deg'] - 2.0) < 0.15, f'верх 2° → 2° ({a})')
    c = compare(box(0.6), box(-1.8))
    ok(c['measured'] and abs(c['sides']['top']['delta_deg'] + 2.4) < 0.2 and c['passed'] is False, f'клин −2,4° на верхней кромке не проходит порог 0,5° ({c["sides"]["top"]})')
    ok(compare(box(0.0), box(-1.4))['top_over_report'] is True and compare(box(0.0), box(-0.7))['top_over_report'] is False, 'отчёт по верху: 1,4° — да, 0,7° — нет')
    c = compare(box(0.3), box(0.5))
    ok(c['passed'] is True, f'Δ 0,2° в пороге ({c["max_abs_deg"]})')
    arc = ((xx - 300) ** 2 + (yy - 500) ** 2) < 320 ** 2                     # купол — верх не прямой
    ok(not edge_angle(arc & (yy < 520), 'top')['ok'], 'круглый верх не меряется')
    c = compare(arc, arc)
    ok(c['sides']['top'].get('skip') and 'passed' in c, 'нет прямых кромок → skip, не отказ')
    leg = box(1.0).copy()
    leg[395:, 150:170] = True                                                  # ножки/ручки не ломают верх
    leg[150:156, 300:310] = False                                              # выем в верхней кромке (ручка)
    a = edge_angle(leg, 'top')
    ok(a['ok'] and abs(a['deg'] - 1.0) < 0.2, f'выем ≤ 30 % точек не ломает прямую ({a})')
    print('silhouette_edge_angle: ошибок %d' % bad)
    return 1 if bad else 0


if __name__ == '__main__':
    import sys
    sys.exit(selftest() if '--selftest' in sys.argv else 0)
