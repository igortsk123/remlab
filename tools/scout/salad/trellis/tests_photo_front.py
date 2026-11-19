#!/usr/bin/env python3
"""Тесты шага 2 цепочки (`photo_front.py`) на синтетике, без товаров и без сети (T-20261119-88).

  python tools/scout/salad/trellis/tests_photo_front.py   # нужны numpy, scipy, opencv, trimesh (venv scout)
"""
from __future__ import annotations

import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import photo_front as PF  # noqa: E402


def t_angle_weight():
    cos = np.array([0.0, 0.2, PF.COS_LO, 0.55, PF.COS_HI, 0.95, 1.0], np.float32)
    w = PF.angle_weight(cos)
    assert w[0] == 0 and w[1] == 0 and w[2] == 0, w                # касательные и косые — ноль
    assert w[4] == 1 and w[5] == 1 and w[6] == 1, w                # фронтальные — единица
    assert np.all(np.diff(w) >= 0), w                              # монотонно
    assert 0 < w[3] < 1, w


def t_surface_fade():
    n = 200
    ok = np.zeros((n, n), bool)
    ok[40:160, 40:160] = True
    f1 = PF.surface_fade(ok, np.ones((n, n), np.float32), 400.0)       # R = FADE_FRAC·400 = 4.8 px
    assert f1[~ok].max() == 0.0, 'вне зоны вес должен быть 0'
    assert f1[100, 100] == 1.0, 'в глубине зоны вес 1'
    row = f1[100, 40:60]
    assert np.all(np.diff(row) >= -1e-6) and row[0] < 0.2 and row[-1] == 1.0, row   # плавный подъём от границы
    # косая поверхность: длина вдоль поверхности больше → до полного веса ближе (в пикселях кадра)
    f2 = PF.surface_fade(ok, np.full((n, n), 0.5, np.float32), 400.0)
    assert f2[100, 42] > f1[100, 42] + 1e-3, (f2[100, 42], f1[100, 42])


def _relief_scene(shift: int, dense_photo: bool = False, flat: bool = False):
    """Кадр 400²: рельеф — квадрат-ступенька (наклон на краях); фото — квадрат с кромками там же (shift=0) или со сдвигом."""
    n = 400
    mask = np.ones((n, n), bool)
    depth = np.zeros((n, n), np.float32)
    if not flat:
        depth[100:300, 100:300] = 1.0                              # ступенька высотой 1 на пиксельную длину 0,05 → наклон на краях ≫ REL_T
    rel = PF.depth_edges(depth, mask, 0.05)
    L = np.full((n, n), 50.0, np.float32)
    L[100 + shift:300 + shift, 100 + shift:300 + shift] = 80.0
    L += 1.5 * np.random.RandomState(7).rand(n, n).astype(np.float32)          # слабая фактура, как у настоящего фото (иначе порог по процентилю садится на нули)
    if dense_photo:
        L = 50 + 25 * np.random.RandomState(1).rand(n, n).astype(np.float32)
    ph_edge = PF.photo_edges(L, mask, float(n))
    return rel, ph_edge, mask, n


def t_gate_aligned_accepts():
    rel, pe, mask, n = _relief_scene(0)
    gate, st = PF.gate_map(rel, pe, mask, float(n))
    assert st['patches_with_relief'] > 0 and st['patches_refused'] == 0, st
    assert st['mask_share_refused'] == 0.0, st
    assert gate.min() > 0.99, gate.min()


def t_gate_shifted_refuses():
    rel, pe, mask, n = _relief_scene(40)                            # кромки фото в 40 px от кромок рельефа (>> допуска) — двойной узор
    gate, st = PF.gate_map(rel, pe, mask, float(n))
    assert st['patches_with_relief'] > 0 and st['patches_refused'] == st['patches_with_relief'], st
    assert st['mask_share_refused'] > 0.05, st
    edge = gate[100:300:20, 100]                                    # на самой кромке рельефа гейт ниже 0,5 — пиксель вне зоны «можно класть» (там `fade` = 0)
    assert edge.max() < 0.5, edge


def t_gate_dense_photo_not_trivial():
    rel, pe, mask, n = _relief_scene(0, dense_photo=True)           # шумное фото: кромки везде — «совпадение» случайное, поправка должна отказать
    gate, st = PF.gate_map(rel, pe, mask, float(n))
    assert st['patches_refused'] >= 0.85 * st['patches_with_relief'], st      # единичные случайные пропуски возможны, массово — отказ


def t_gate_flat_surface_passes_everything():
    rel, pe, mask, n = _relief_scene(40, flat=True)                 # рельефа нет → риска двойного узора нет → класть
    gate, st = PF.gate_map(rel, pe, mask, float(n))
    assert st['patches_with_relief'] == 0 and st['patches_refused'] == 0 and st['mask_share_refused'] == 0.0, st
    assert gate.min() > 0.99


def t_depth_from_texels():
    """3D-точки текселей → глубина кадра: холм по центру плоскости даёт положительную глубину в центре и ≈ 0 у краёв; длина пикселя ≈ шаг сетки."""
    m = 17
    gx, gy = np.meshgrid(np.linspace(0, 1, m), np.linspace(0, 1, m))
    bump = 0.2 * np.exp(-(((gx - 0.5) ** 2 + (gy - 0.5) ** 2) / 0.02))
    V = np.stack([gx.ravel(), gy.ravel(), bump.ravel()], 1)
    UV = np.stack([gx.ravel(), 1.0 - gy.ravel()], 1)                # строка текселя = (1 − v)·T = gy·T
    F = []
    for i in range(m - 1):
        for j in range(m - 1):
            a, b, c, d = i * m + j, i * m + j + 1, (i + 1) * m + j, (i + 1) * m + j + 1
            F += [[a, b, d], [a, d, c]]
    F = np.array(F)
    T = 64
    pos, valid = PF.texel_positions(V, F, UV, T)
    assert valid[8:56, 8:56].all(), 'внутренность карты должна быть покрыта'
    yy, xx = np.mgrid[0:T, 0:T]
    uv = np.stack([(xx + 0.5) / T, (yy + 0.5) / T], -1).astype(np.float32)   # кадр = карта (тождественное отображение)
    mask = np.zeros((T, T), bool)
    mask[4:60, 4:60] = True
    depth, px_len = PF.frame_depth(pos, valid, uv, mask)
    assert abs(px_len - 1.0 / T) < 0.1 / T, px_len
    assert depth[32, 32] > 0.12, depth[32, 32]
    assert abs(depth[6, 6]) < 0.05, depth[6, 6]


def t_splat_apply():
    """Тождественная развёртка: цвет фото ложится на покрытые тексели с весом = уверенность; без уверенности — карта не меняется."""
    n = 64
    yy, xx = np.mgrid[0:n, 0:n]
    uv = np.stack([(xx + 0.5) / n, (yy + 0.5) / n], -1).astype(np.float32)
    mask = np.zeros((n, n), bool)
    mask[8:56, 8:56] = True
    conf = np.zeros((n, n), np.float32)
    conf[8:56, 8:32] = 1.0                                          # левая половина — полная уверенность
    conf[8:56, 32:56] = 0.5                                         # правая — половинная
    col = np.zeros((n, n, 3), np.uint8)
    col[...] = (200, 100, 50)
    tex = np.zeros((n, n, 3), np.uint8)
    tex[...] = (0, 0, 0)
    sp = PF.splat(uv, n, mask, col, conf)
    out, info = PF.apply_photo(tex, sp)
    assert np.abs(out[30, 16].astype(int) - np.array([200, 100, 50])).max() <= 2, out[30, 16]
    assert np.abs(out[30, 44].astype(int) - np.array([100, 50, 25])).max() <= 2, out[30, 44]   # половинный вес
    assert out[2, 2].tolist() == [0, 0, 0] and out[60, 60].tolist() == [0, 0, 0]                # вне кадра/маски — как было
    assert info['texels_covered'] > 1500, info


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith('t_') and callable(v)]
    for t in tests:
        t()
        print('ok', t.__name__)
    print('all ok')
    return 0


if __name__ == '__main__':
    sys.exit(main())
