#!/usr/bin/env python3
"""Щели 1–2 px у кромки маски (T-20261119-104/2): пунктир светлого на белом закрывается, настоящие просветы остаются. Без сети и моделей.
  python tools/scout/salad/tests_edge_gap.py"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import components as C  # noqa: E402

H, W = 300, 400
BOX = (60, 80, 340, 260)     # x0, y0, x1, y1 — тело


def body():
    a = np.zeros((H, W), np.float32)
    x0, y0, x1, y1 = BOX
    a[y0:y1, x0:x1] = 1.0
    return a


def rgb_for(a):
    r = np.full((H, W, 3), 255, np.uint8)
    r[a > 0.5] = (90, 60, 40)          # тело тёмно-коричневое, фон белый — чтобы видеть, откуда взят цвет заплатки
    return r


def dashed_top(a):
    """Верхняя кромка «пунктиром»: щели 1 и 2 px шириной, глубиной 2 px — как у светлого комода/шкафа на белом."""
    a = a.copy()
    y0 = BOX[1]
    for x in range(100, 300, 20):
        a[y0:y0 + 2, x:x + 1] = 0      # щель 1 px
    for x in range(110, 300, 20):
        a[y0:y0 + 2, x:x + 2] = 0      # щель 2 px (с соседними не сливаются: между ними ≥ 8 px тела)
    return a


def test_dash_closed_and_control():
    a = dashed_top(body())
    y0 = BOX[1]
    gaps_before = int((a[y0:y0 + 2, 100:300] == 0).sum())
    assert gaps_before > 20, f'контроль: у синтетики нет щелей ({gaps_before}) — тест ничего не проверяет'
    out, rgb, info = C.close_edge_gaps(a, rgb_for(a), gap_px=2)
    gaps_after = int((out[y0:y0 + 2, 100:300] <= 0.5).sum())
    assert gaps_after == 0, f'щели у кромки остались: {gaps_after} px'
    assert info['edge_gap_closed'] == gaps_before, info
    # цвет заплатки — от тела, а не белый фон
    assert (rgb[y0, 100] == (90, 60, 40)).all(), f'заплатка белая, а не цвета тела: {rgb[y0, 100]}'
    # выключено (0) — маска не тронута (плюс-контроль «без правки тест падает»)
    same, _, off = C.close_edge_gaps(a, rgb_for(a), gap_px=0)
    assert (same == a).all() and off.get('edge_gap_off'), off
    assert int((same[y0:y0 + 2, 100:300] == 0).sum()) == gaps_before


def test_real_clearances_kept():
    a = body()
    x0, y0, x1, y1 = BOX
    a[y0:y0 + 12, 200:204] = 0         # просвет 4 px у кромки (щель между ножками/планками) — настоящий
    a[150:153, 150:153] = 0            # внутренняя дырка 3×3 (ручка/отверстие)
    a[200:206, 250:256] = 0            # внутренняя дырка 6×6
    before = a.copy()
    out, _, info = C.close_edge_gaps(a, rgb_for(a), gap_px=2)
    assert (out[y0:y0 + 12, 200:204] <= 0.5).all(), 'просвет 4 px у кромки закрыт'
    assert (out[150:153, 150:153] <= 0.5).all(), 'дырка 3×3 закрыта'
    assert (out[200:206, 250:256] <= 0.5).all(), 'дырка 6×6 закрыта'
    assert (out == before).all() and info['edge_gap_closed'] == 0, info


def test_deep_pinhole_not_touched():
    """Одиночная точка-дырка 1 px глубоко внутри (не у кромки) — не трогаем: правило только у кромки."""
    a = body()
    a[170, 200] = 0
    out, _, info = C.close_edge_gaps(a, rgb_for(a), gap_px=2)
    assert out[170, 200] <= 0.5 and info['edge_gap_closed'] == 0, info


def test_product_at_frame_edge_and_empty():
    a = np.zeros((H, W), np.float32)
    a[:, 100:300] = 1.0                # тело упирается в верх и низ кадра
    a[0:2, 150] = 0
    out, _, _ = C.close_edge_gaps(a, rgb_for(a), gap_px=2)
    assert out.shape == a.shape and out[10, 150] > 0.5
    e = np.zeros((H, W), np.float32)
    out2, _, info = C.close_edge_gaps(e, rgb_for(e), gap_px=2)
    assert (out2 == 0).all() and info['edge_gap_closed'] == 0


def test_alpha_values_kept():
    """Мягкая альфа вне щелей не меняется (правило пишет 1.0 только в добавленные пиксели)."""
    a = body()
    a[100:110, 100:110] = 0.8
    a = dashed_top(a)
    out, _, _ = C.close_edge_gaps(a, rgb_for(a), gap_px=2)
    assert np.allclose(out[100:110, 100:110], 0.8)


if __name__ == '__main__':
    bad = 0
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            try:
                fn()
                print('  ok ', name)
            except AssertionError as e:
                bad += 1
                print('  FAIL', name, '-', e)
    print('итог:', 'OK' if not bad else f'{bad} провалов')
    sys.exit(1 if bad else 0)
