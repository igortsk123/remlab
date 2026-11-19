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


def t_threshold_adapts_to_rough_surface():
    """Гладкая плита: порог = REL_T. Шумная геометрия (мягкая мебель): порог растёт вместе с медианой наклона, чтобы «рельефом» не стала вся поверхность."""
    n = 300
    mask = np.ones((n, n), bool)
    flat = np.zeros((n, n), np.float32)
    flat[100:200, 100:200] = 1.0
    r = PF.depth_edges(flat, mask, 0.05)
    assert PF.relief_threshold(r, mask) == PF.REL_T
    rough = np.random.RandomState(3).rand(n, n).astype(np.float32) * 0.4              # шум геометрии: наклон ≫ REL_T везде
    rr = PF.depth_edges(rough, mask, 0.05)
    assert (rr >= PF.REL_T).mean() > 0.9, 'без адаптации «рельеф» везде'
    th = PF.relief_threshold(rr, mask)
    assert th > 5 * PF.REL_T and (rr >= th).mean() < 0.1, (th, (rr >= th).mean())


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


def t_splat_dense_map_is_covered():
    """Карта плотнее кадра в 4 раза по стороне (16 текселей на пиксель): фасад должен покрыться сплошь, а не 1–2 % (раньше абсолютный порог массы не набирался)."""
    f, size = 32, 128
    yy, xx = np.mgrid[0:f, 0:f]
    uv = np.stack([(xx + 0.5) / f, (yy + 0.5) / f], -1).astype(np.float32)
    mask = np.ones((f, f), bool)
    conf = np.ones((f, f), np.float32)
    col = np.zeros((f, f, 3), np.uint8)
    col[...] = (10, 200, 90)
    sp = PF.splat(uv, size, mask, col, conf)
    assert abs(sp['texels_per_pixel'] - 16.0) < 1.0, sp['texels_per_pixel']
    out, info = PF.apply_photo(np.zeros((size, size, 3), np.uint8), sp)
    inner = out[8:size - 8, 8:size - 8]
    assert (np.abs(inner.astype(int) - np.array([10, 200, 90])).max(-1) <= 3).mean() > 0.97, 'внутренность карты покрыта фото'
    assert info['texels_covered'] > 0.8 * size * size, info


def _pattern(n=300):
    """Фасад с узором: рамка, сетка, дуги — кромки в разных направлениях; L* ≈ 50 + 30·рисунок."""
    import cv2
    im = np.full((n, n), 50.0, np.float32)
    for k in range(40, n - 30, 60):
        cv2.line(im, (k, 30), (k, n - 30), 80.0, 3)
        cv2.line(im, (30, k), (n - 30, k), 80.0, 3)
    cv2.circle(im, (n // 2, n // 2), n // 5, 85.0, 4)
    cv2.circle(im, (n // 3, 2 * n // 3), n // 8, 20.0, 4)
    return im + 1.0 * np.random.RandomState(2).rand(n, n).astype(np.float32)


def t_register_recovers_scale_shift():
    """Фото = база, сжатая по x на 0,9 и сдвинутая на 25 px (как на комоде: узор сжат/сдвинут): ECC возвращает совпадение кромок с ~0 до высокого."""
    n = 300
    base = _pattern(n)
    H_true = np.array([[0.9, 0.0, 25.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]])
    import cv2
    ph = cv2.warpPerspective(base, H_true, (n, n), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    mask = np.ones((n, n), bool)
    mask[:20] = mask[-20:] = False
    mask[:, :20] = mask[:, -20:] = False
    before = PF.edge_agreement(ph, base, mask, float(n))['agree']
    Hm, st = PF.register_to_base(ph, base, mask, mask, float(n))
    after_img = PF.warp_by(Hm, ph, (n, n))
    after = PF.edge_agreement(after_img, base, mask, float(n))['agree']
    assert before < 0.5 and after > 0.8 and after > before + 0.3, (before, after, st)


def t_edge_agreement_chance_corrected():
    """Две независимые плотные картинки: «совпадение» после поправки на случайные попадания ≈ 0, а не 0,5+."""
    n = 300
    mask = np.ones((n, n), bool)
    a = 50 + 25 * np.random.RandomState(1).rand(n, n).astype(np.float32)
    b = 50 + 25 * np.random.RandomState(9).rand(n, n).astype(np.float32)
    assert PF.edge_agreement(a, b, mask, float(n))['agree'] < 0.25
    assert PF.edge_agreement(a, a, mask, float(n))['agree'] > 0.9


def t_color_gate_refuses_shifted_material():
    """База: дерево слева, серое справа, граница на x=150. Фото — тот же узор, граница сдвинута на 25 px: в полосе сдвига материалы разные → гейт 0; вдали от полосы → 1; общий сдвиг оттенка не мешает."""
    n = 300
    def img(edge, tint=0):
        im = np.zeros((n, n, 3), np.uint8)
        im[:, :edge] = (210 + tint, 170, 110)
        im[:, edge:] = (120, 120, 125)
        return im
    base, ph = img(150), img(175, tint=4)
    mask = np.ones((n, n), bool)
    g, st = PF.color_gate(ph, base, mask, float(n))
    assert g[150, 160] < 0.1, g[150, 160]                            # полоса сдвига (фото дерево, база серое)
    assert g[150, 40] > 0.9 and g[150, 260] > 0.9, (g[150, 40], g[150, 260])
    g0, _ = PF.color_gate(img(150, tint=4), base, mask, float(n))     # без сдвига узора, только общий оттенок — не отказывать
    assert g0.min() > 0.9, g0.min()


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith('t_') and callable(v)]
    for t in tests:
        t()
        print('ok', t.__name__)
    print('all ok')
    return 0


if __name__ == '__main__':
    sys.exit(main())
