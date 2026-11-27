"""Угол листа — по длинным ТОЛСТЫМ штрихам (T-171/vhod, Fable otvet-36, круг 6): тонкие косые линейки/штриховка угол плана не определяют.
Синтетика (идёт в CI): прямой план из толстых стен (test_cleanup.plan) + много тонких линий под 8° (1 px) — как линейки/штриховка/рамка скана.
  • по толстым штрихам главный угол ≈ 0 (< 1,5°), лист «ровный», довороту не подлежит;
  • сломал — покраснело: `thick=False` (все линии, как до otvet-36) → тонкие косые линии перетягивают угол (|θ| заметно больше), лист ушёл бы в доворот зря;
  • настоящий наклон при тех же тонких линиях найден (план повёрнут на 10° — главный угол ≈ 10°);
  • `thick_ink` убирает штрихи тоньше ядра и оставляет стену."""
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools' / 'floorplan'))
sys.path.insert(0, str(ROOT / 'tests' / 'floorplan'))
import cleanup as cl  # noqa: E402
import test_cleanup as TC  # noqa: E402
import test_deskew as TD  # noqa: E402


def add_thin_slanted(img, deg=8.0, n=40):
    out = img.copy()
    h, w = out.shape[:2]
    t = np.tan(np.radians(deg))
    for i in range(n):
        y0 = int(h * (i + 0.5) / n)
        cv2.line(out, (0, y0), (w - 1, int(y0 + (w - 1) * t)), (90, 90, 90), 1)
    return out


def test_thin_slanted_lines_do_not_set_the_angle():
    img = add_thin_slanted(TC.plan(3, fill=False))
    th, info = cl.main_angle(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY))
    assert th is not None and abs(th) < cl.DESKEW_MIN and info['share'] > 0.9, (th, info)   # по толстому — план прямой, угол определён уверенно
    old, oinfo = cl.main_angle(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), thick=False, page=False, fallback=False)
    assert old is None and oinfo['share'] < cl.DESKEW_SHARE_MIN, (old, oinfo)    # −контроль: по всем линиям тонкие косые тонут/перетягивают — «главного угла нет» (так терялись листы до otvet-36)


def test_real_tilt_found_among_thin_lines():
    img, _ = TD.rotated(10.0)
    img = add_thin_slanted(img, deg=-6.0)
    th, info = cl.main_angle(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY))
    assert th is not None and abs(th - 10.0) < 1.0, (th, info)


def test_thick_ink_keeps_wall_drops_hairline():
    g = np.full((600, 800), 255, np.uint8)
    cv2.line(g, (50, 100), (750, 100), 0, 1)                              # волосяная линия
    cv2.line(g, (50, 300), (750, 300), 0, 9)                              # стена
    out = cl.thick_ink(g)
    assert out[100, 400] == 255 and out[300, 400] == 0
