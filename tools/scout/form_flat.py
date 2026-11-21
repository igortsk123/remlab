#!/usr/bin/env python3
"""Предупреждение этапа 01 «пропорции формы не те, что у карточки» (T-172, 21.11.2026) — ВХОЛОСТУЮ: ничего не блокирует, пишет поле `form_flat` в verdict.json.

Зачем: `salad/apply_repairs.slab_excess` ловит форму ШИРЕ карточки (лишняя подложка, >15 %). Обратное — форма, СПЛЮЩЕННАЯ относительно карточки
(лампа с плафоном: Hunyuan дал два тонких листа вместо короба, глубина 7,5 см при карточке 16 см) — не ловил никто. Здесь — пара мер:
  масштаб формы по ВЫСОТЕ карточки; горизонтальные оси формы (по главным осям x–z, перцентили pct_lo…pct_hi по точкам поверхности) сортируются a ≥ b;
  карточка — w×d или диаметр (круг: обе оси = диаметр); wide = a_формы / a_карточки, thin = b_формы / b_карточки, ratio = thin / wide.
  ratio < flat_ratio_warn → warn: форма «тоньше/длиннее себя самой», чем карточка (общий масштаб не мешает: форма целиком меньше или больше — ratio ≈ 1).
Не ловит: тонкую «ленту» с верным габаритом рамки (торшер-лента: габарит 20×22 при диаметре 20, форма — одна S-линия) — нужна проверка по силуэту фото (кандидат в журнале паспорта).
Пороги — `rules/form-flat.json` (с калибровкой). Без trimesh в ядре: `ratio_from_points` — numpy; glb читает `measure_glb` (trimesh, как slab_excess).
Запуск: python form_flat.py --selftest | python form_flat.py <model.glb> --dims w=16,d=24,h=39 [--dia 20]"""
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RULES = os.path.join(HERE, 'rules', 'form-flat.json')


def rules(path: str = RULES) -> dict:
    return json.load(open(path, encoding='utf-8'))


def card_axes(dims: dict | None, square: bool = False) -> tuple[float, float, float] | None:
    """(большая, меньшая горизонтальные оси карточки, высота) в см; None — сравнивать не с чем (нет высоты или горизонтали)."""
    d0 = dims or {}
    h = d0.get('h')
    w = d0.get('w')
    dd = d0.get('d') or (w if square else None)
    dia = d0.get('dia')
    if not h:
        return None
    if w and dd:
        return float(max(w, dd)), float(min(w, dd)), float(h)
    if dia:
        return float(dia), float(dia), float(h)
    return None


def ratio_from_points(P: np.ndarray, dims: dict | None, R: dict | None = None, square: bool = False) -> dict:
    """P — точки формы (N×3, Y вверх, любые единицы). Возвращает {'verdict': 'ok'|'warn'|'na', 'wide', 'thin', 'ratio', 'dry_run', 'text'}."""
    R = R or rules()
    out: dict = {'dry_run': bool(R.get('dry_run', True)), 'warn_below': R['flat_ratio_warn']}
    card = card_axes(dims, square)
    P = np.asarray(P, float)
    if card is None or len(P) < 50:
        out['verdict'] = 'na'
        return out
    ca, cb, ch = card
    H = np.asarray(P[:, [0, 2]], float)
    H = H - H.mean(0)
    _, vec = np.linalg.eigh(np.cov(H.T))
    Q = H @ vec
    lo, hi = np.percentile(Q, [R['pct_lo'], R['pct_hi']], axis=0)
    ylo, yhi = np.percentile(P[:, 1], [R['pct_lo'], R['pct_hi']])
    height = float(yhi - ylo)
    if height <= 1e-9:
        out['verdict'] = 'na'
        return out
    s = ch / height                                  # см на единицу формы
    fa, fb = sorted([float(x) * s for x in (hi - lo)], reverse=True)
    wide, thin = fa / ca, fb / cb
    ratio = thin / wide if wide > 0 else 0.0
    out.update(wide=round(wide, 2), thin=round(thin, 2), ratio=round(ratio, 2))
    out['verdict'] = 'warn' if ratio < R['flat_ratio_warn'] else 'ok'
    if out['verdict'] == 'warn':
        out['text'] = (f"пропорции формы не те, что у карточки: меньшая ось ×{thin:.2f}, большая ×{wide:.2f} (отношение {ratio:.2f} < {R['flat_ratio_warn']:g}) — "
                       f"вхолостую, ничего не блокирует; посмотреть форму глазами")
    return out


def surface_points(glb: str, n: int = 60000) -> np.ndarray:
    """Точки поверхности glb (все части сцены), площадь-взвешенно; seed фиксирован — замер повторяем."""
    import trimesh
    sc = trimesh.load(glb, force='scene')
    geos = [g for g in sc.dump() if hasattr(g, 'faces') and len(g.faces)]
    rng = np.random.default_rng(0)
    parts = []
    areas = [float(g.area) for g in geos]
    tot = sum(areas) or 1.0
    for g, a in zip(geos, areas):
        k = max(int(n * a / tot), 200)
        tri = g.triangles
        w = g.area_faces / max(float(g.area_faces.sum()), 1e-12)
        fi = rng.choice(len(tri), size=k, p=w)
        u, v = rng.random(k), rng.random(k)
        flip = u + v > 1
        u[flip], v[flip] = 1 - u[flip], 1 - v[flip]
        t = tri[fi]
        parts.append(t[:, 0] + (t[:, 1] - t[:, 0]) * u[:, None] + (t[:, 2] - t[:, 0]) * v[:, None])
    return np.vstack(parts)


def measure_glb(glb: str, dims: dict | None, square: bool = False, R: dict | None = None) -> dict | None:
    """Замер по файлу; сбой — None (приёмка идёт дальше, как у grey_top_field)."""
    try:
        return ratio_from_points(surface_points(glb), dims, R, square)
    except Exception as e:  # noqa: BLE001 — замер не должен ронять приёмку
        print(f'  форма против карточки: не замерена ({type(e).__name__}: {str(e)[:80]})', flush=True)
        return None


def _box(a: float, b: float, h: float, n: int = 4000, seed: int = 0) -> np.ndarray:
    """Облако точек на поверхности коробки a (x) × h (y) × b (z) — синтетическая «форма» для самопроверки."""
    rng = np.random.default_rng(seed)
    P = rng.random((n, 3)) * np.array([a, h, b])
    face = rng.integers(0, 6, n)
    ax = face // 2
    P[np.arange(n), ax] = np.where(face % 2 == 0, 0.0, np.array([a, h, b])[ax])
    return P - np.array([a / 2, 0, b / 2])


def _selftest() -> int:
    bad = []

    def ok(name, cond):
        print(('OK   ' if cond else 'FAIL ') + name)
        if not cond:
            bad.append(name)
    R = rules()
    card = {'w': 16, 'd': 24, 'h': 39}
    r = ratio_from_points(_box(24.3, 14.9, 39), card, R)
    ok(f"лампа 24×15×39 при карточке 16×24×39 (как TRELLIS.2: меньшая ось ×0,93) → ok, отношение {r.get('ratio')}", r['verdict'] == 'ok' and r['ratio'] > 0.8)
    r = ratio_from_points(_box(24.3, 7.5, 39), card, R)
    ok(f"лампа с плафоном-листом 24×7,5×39 (Hunyuan: меньшая ось ×0,47) → warn, отношение {r.get('ratio')}", r['verdict'] == 'warn' and r['ratio'] < 0.6 and 'вхолостую' in r['text'])
    r = ratio_from_points(_box(12, 8, 19.5), card, R)
    ok('вся форма вдвое меньше (масштаб — по высоте карточки, пропорции те же) → ok: общий масштаб не мешает', r['verdict'] == 'ok')
    rng = np.random.default_rng(3)
    ang = rng.random(6000) * 2 * np.pi
    cyl = np.stack([12.1 * np.cos(ang), rng.random(6000) * 39, 12.1 * np.sin(ang)], 1)         # цилиндр Ø24,2 × 39
    r = ratio_from_points(cyl, {'dia': 24, 'h': 39}, R)
    ok('круглая по диаметру (форма Ø24, карточка Диаметр 24) → ok, обе оси ≈ ×1', r['verdict'] == 'ok' and abs(r['thin'] - 1.0) < 0.05 and abs(r['wide'] - 1.0) < 0.05)
    r = ratio_from_points(_box(24, 6, 39), {'dia': 24, 'h': 39}, R)
    ok('круглая карточка, форма — тонкий лист → warn', r['verdict'] == 'warn')
    r = ratio_from_points(_box(24, 24, 39), {'w': 20, 'h': 39}, R, square=True)
    ok('глубина пуста у роли «симметричная в плане» → d = w (как slab_excess)', r['verdict'] == 'ok')
    r = ratio_from_points(_box(24, 24, 39), {'w': 20, 'h': 39}, R, square=False)
    ok('глубина пуста, роль не квадратная → na (сравнивать не с чем)', r['verdict'] == 'na')
    ok('нет высоты в карточке → na', ratio_from_points(_box(24, 24, 39), {'w': 20, 'd': 20}, R)['verdict'] == 'na')
    ok('нет карточки → na', ratio_from_points(_box(24, 24, 39), None, R)['verdict'] == 'na')
    two = np.vstack([_box(69, 68, 79, seed=1), _box(69, 68, 30, seed=2) + np.array([0, 0, 140.0])])
    r = ratio_from_points(two, {'w': 69, 'd': 68, 'h': 79}, R)
    ok(f"кресло + лишний пуф в 2 м (форма вытянута в одну ось ×3,5) → warn, отношение {r.get('ratio')}", r['verdict'] == 'warn')
    ok('замер повторяем (одно облако — одни числа)', ratio_from_points(_box(24.3, 7.5, 39), card, R) == ratio_from_points(_box(24.3, 7.5, 39), card, R))
    ok('правила: порог в JSON, вхолостую', R['dry_run'] is True and 0 < R['flat_ratio_warn'] < 1 and 'version' in R)
    print('ВСЁ ЗЕЛЁНОЕ' if not bad else f'ПАДЕНИЯ: {bad}')
    return 1 if bad else 0


def main(argv: list[str]) -> int:
    if '--selftest' in argv:
        return _selftest()
    if len(argv) < 2:
        print(__doc__)
        return 2
    dims = {}
    for i, a in enumerate(argv):
        if a == '--dims' and i + 1 < len(argv):
            for tok in argv[i + 1].split(','):
                k, v = tok.split('=')
                dims[k] = float(v)
    print(json.dumps(measure_glb(argv[1], dims), ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
