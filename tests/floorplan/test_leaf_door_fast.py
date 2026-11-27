"""leaf_door и gap_components после ускорения (T-20261127-169/4): результат побайтно как у эталона до правки.

1. np.rint (в `bench._hit_at`) ↔ питоновский round (в `at` эталона): половинки x.5 (чётное), отрицательные, −0,5, большие, соседи
   половинок (nextafter), точки q + d·k для косых направлений.
2. `bench._hit_at` ↔ скалярный `at` (границы листа, дробные точки).
3. `bench.leaf_door` ↔ `leaf_door_ref` на синтетических проёмах (дуга, пара направлений, косые направления, стрелка в проёме,
   `inside`, транспонирование) — те же кортежи (cx, cy, R, quad, доля), None там же.
4. `fpcore.label_px` ↔ `np.nonzero(lab == i)`; `gap_components` ↔ копия прежнего цикла (по всему листу)."""
import math
import sys
import types
from pathlib import Path

import cv2
import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools' / 'floorplan'))
sys.path.insert(1, str(ROOT / 'tests' / 'floorplan'))
import bench  # noqa: E402
import fpcore as fc  # noqa: E402
from leaf_door_ref import leaf_door_ref  # noqa: E402


def test_rint_equals_round_on_halves():
    base = [k + 0.5 for k in range(-6, 7)] + [-0.5, 0.5, 1e6 + 0.5, -1e6 - 0.5, 2.5, 3.5, 1234567.5, 0.0, -0.0, 7.0, -7.0]
    near = [v for b in base for v in (b, float(np.nextafter(b, np.inf)), float(np.nextafter(b, -np.inf)))]
    rng = np.random.default_rng(7)
    vals = np.array(near + rng.uniform(-50, 3000, 20000).tolist() + (rng.integers(-40, 400, 5000) + 0.5).tolist(), np.float64)
    ref = [round(v) for v in vals]                        # как в `at`: round(np.float64) — питоновский int
    got = np.rint(vals).astype(np.int64).tolist()
    assert got == ref


@pytest.mark.parametrize('ang', [0.0, 90.0, 180.0, 30.0, 45.0, 17.3, 123.4, 270.0])
def test_rint_equals_round_on_ray_points(ang):
    d = np.array([math.cos(math.radians(ang)), math.sin(math.radians(ang))])
    rng = np.random.default_rng(int(ang * 10) + 1)
    q = rng.integers(0, 400, (300, 2)).astype(float)
    for k in (1, 2, 5, 17, 63, 110):
        p = q + d * k                                      # скалярная форма `at(q + d * k)`
        ref = [[round(v) for v in row] for row in p]
        vec = np.stack([q[:, 0] + d[0] * float(k), q[:, 1] + d[1] * float(k)], 1)
        assert np.array_equal(p, vec)                      # та же арифметика, что в `_hit_at(.., xf + d[0] * kk ..)`
        assert np.rint(vec).astype(np.int64).tolist() == ref


def test_hit_at_equals_scalar_at():
    rng = np.random.default_rng(3)
    H, W = 37, 53
    solid = rng.random((H, W)) < 0.4

    def at(p):
        xi, yi = int(round(p[0])), int(round(p[1]))
        return 0 <= xi < W and 0 <= yi < H and bool(solid[yi, xi])

    halves = np.arange(-3.5, W + 3.5, 1.0)                 # x.5 — на границе округления
    X = np.concatenate([rng.uniform(-6, W + 6, 3000), halves, [-0.5, W - 0.5, W + 0.5, 0.4999999, 0.5000001]])
    Y = np.concatenate([rng.uniform(-6, H + 6, 3000), rng.permutation(halves) - 0.0, [-0.5, H - 0.5, H + 0.5, 0.4999999, 0.5000001]])
    got = bench._hit_at(solid, X, Y)
    ref = np.array([at((x, y)) for x, y in zip(X.tolist(), Y.tolist())])
    assert np.array_equal(got, ref)
    got2 = bench._hit_at(solid, X[:10, None] + np.arange(4)[None, :], Y[:10, None] + np.arange(4)[None, :])   # 2-мерные входы
    assert got2.shape == (10, 4)


def scene(rng, kind):
    """два куска стены толщиной t с проёмом R и дугой створки; → (thin, dark, arr, g, t, ppm, inside)."""
    H, W, t, ppm = 220, 300, 8, 60.0
    dark = np.zeros((H, W), np.uint8)
    thin = np.zeros((H, W), np.uint8)
    arr = np.zeros((H, W), np.uint8)
    R = int(rng.integers(30, 62))
    y0 = int(rng.integers(70, 120))
    xl = int(rng.integers(60, 110))
    cv2.rectangle(dark, (10, y0), (xl, y0 + t - 1), 255, -1)
    cv2.rectangle(dark, (xl + R + 1, y0), (xl + R + 90, y0 + t - 1), 255, -1)
    if kind in ('arc', 'arrow', 'inside', 'skew'):
        s = 1 if rng.random() < 0.5 else -1
        yh = y0 + (t // 2 if s > 0 else t // 2)
        cv2.ellipse(thin, (xl, yh), (R, R), 0, 0 if s > 0 else -90, 90 if s > 0 else 0, 255, 1)
    if kind == 'noise':
        thin[rng.random((H, W)) < 0.04] = 255
    if kind == 'arrow':
        cv2.circle(arr, (xl + R // 2, y0 + t // 2), 3, 255, -1)
    gx, gy = xl + R / 2.0 + float(rng.uniform(-2, 2)), y0 + t / 2.0 + float(rng.uniform(-2, 2))
    inside = None
    if kind == 'inside':
        inside = np.zeros((H, W), np.uint8)
        inside[y0 - 4:y0 + t + 4, xl:xl + R + 2] = 1 if rng.random() < 0.8 else 0
    if rng.random() < 0.4:                                  # транспонирование: стены вертикальные
        thin, dark, arr = thin.T.copy(), dark.T.copy(), arr.T.copy()
        gx, gy = gy, gx
        if inside is not None:
            inside = inside.T.copy()
    return thin, dark, arr, types.SimpleNamespace(cx=gx, cy=gy), t, ppm, inside


def same(a, b):
    if a is None or b is None:
        return a is None and b is None
    return len(a) == len(b) and all((np.array_equal(x, y) if isinstance(x, np.ndarray) else x == y) for x, y in zip(a, b))


def test_leaf_door_equals_ref_on_synthetic():
    rng = np.random.default_rng(11)
    found = 0
    for i in range(48):
        kind = ('arc', 'arc', 'arrow', 'inside', 'noise', 'skew')[i % 6]
        thin, dark, arr, g, t, ppm, inside = scene(rng, kind)
        for angles in ((0.0, 90.0), (0.0, 90.0, 33.0), (12.5, 102.5)):
            a = leaf_door_ref(g, thin, dark, arr, t, ppm, angles, inside)
            b = bench.leaf_door(g, thin, dark, arr, t, ppm, angles, inside)
            assert same(a, b), (i, kind, angles, a, b)
            found += a is not None
    assert found >= 10                                      # сверка не пустая: двери действительно находятся


def test_leaf_door_equals_ref_at_sheet_edge_and_small_ppm():
    rng = np.random.default_rng(5)
    thin, dark, arr, g, t, ppm, inside = scene(rng, 'arc')
    for gx, gy, pp in ((2.0, 2.0, 60.0), (298.0, 218.0, 60.0), (150.0, 100.0, 8.0), (150.0, 100.0, 0.5), (150.0, 100.0, 300.0)):
        g2 = types.SimpleNamespace(cx=gx, cy=gy)
        assert same(leaf_door_ref(g2, thin, dark, arr, t, pp), bench.leaf_door(g2, thin, dark, arr, t, pp))


def test_label_px_equals_nonzero():
    rng = np.random.default_rng(2)
    for _ in range(20):
        m = (cv2.GaussianBlur(rng.random((120, 160)).astype(np.float32), (0, 0), 3) > 0.52).astype(np.uint8)
        m[0, :5] = 1
        m[-1, -7:] = 1
        n, lab, st, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
        for i in range(1, n):
            y1, x1 = np.nonzero(lab == i)
            y2, x2 = fc.label_px(lab, i, st[i, :4])
            assert y1.dtype == y2.dtype and x1.dtype == x2.dtype
            assert np.array_equal(y1, y2) and np.array_equal(x1, x2)
    y1, x1 = np.nonzero(lab == 1)
    for bad in (None, (0, 0, 0, 0), (-1, 0, 5, 5), 'x'):          # кривая рамка — весь лист, как раньше
        y2, x2 = fc.label_px(lab, 1, bad)
        assert np.array_equal(y1, y2) and np.array_equal(x1, x2)
    y3, x3 = fc.label_px(lab, 10_000, (0, 0, 5, 5))               # нет такой метки — пусто
    assert len(y3) == 0 and len(x3) == 0


def gap_components_ref(add, dark, outside):
    """прежний цикл `fpcore.gap_components` (np.nonzero по всему листу)."""
    n, lab, st, cen = cv2.connectedComponentsWithStats(add.astype(np.uint8), connectivity=8)
    out = []
    near_out = cv2.dilate(outside.astype(np.uint8), np.ones((5, 5), np.uint8)) if outside is not None else None
    for i in range(1, n):
        ys, xs = np.nonzero(lab == i)
        if len(xs) < 3:
            continue
        (cx, cy), (w, h), _ = cv2.minAreaRect(np.column_stack([xs, ys]).astype(np.float32))
        length, depth = max(w, h) + 1, min(w, h) + 1
        glaze = fc.frame_coverage(ys, xs, dark)
        ext = bool(near_out[ys, xs].any()) if near_out is not None else False
        out.append(fc.Gap(i, float(cx), float(cy), float(length), float(depth), '', glaze, ext, tuple(int(v) for v in st[i, :4])))
    return lab, out


def test_gap_components_equals_ref():
    rng = np.random.default_rng(9)
    for k in range(8):
        add = np.zeros((140, 180), np.uint8)
        for _ in range(int(rng.integers(3, 12))):
            x, y = int(rng.integers(0, 170)), int(rng.integers(0, 130))
            cv2.rectangle(add, (x, y), (x + int(rng.integers(1, 30)), y + int(rng.integers(1, 9))), 1, -1)
        add[0:2, 0:9] = 1
        add[-1, -12:] = 1
        dark = (rng.random(add.shape) < 0.3).astype(np.uint8)
        outside = None if k % 3 == 0 else (rng.random(add.shape) < 0.5)
        l1, g1 = gap_components_ref(add, dark, outside)
        l2, g2 = fc.gap_components(add, dark, outside)
        assert np.array_equal(l1, l2)
        assert repr(g1) == repr(g2)
