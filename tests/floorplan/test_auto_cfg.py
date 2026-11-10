"""Выбор маски стен без настройки (T-20261110-08): синие штрихи — стены, только если они не тоньше тёмных.
Наш /try-план: стены тёмно-серые 12 px, а синие — обводки выделенных комнат и окна 4 px → маска тёмная (иначе
одна комната на весь лист); лист A: синие стены 12 px, тёмное — только текст → маска синяя."""
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools' / 'floorplan'))
import bench  # noqa: E402

BLUE = (215, 110, 40)          # BGR: тон ~104, насыщенность высокая
DARK = (90, 95, 90)            # тёмно-серая стена (серый < 125)


def sheet(wall_color, wall_t, line_color=None, line_t=0, text_color=None):
    """Лист 600×800: прямоугольник квартиры, разделённый на 3 комнаты стенами wall_t; по контуру каждой комнаты —
    обводка line_t (если line_color); text_color — строки «текста» тонкими штрихами внутри комнат."""
    img = np.full((600, 800, 3), 255, np.uint8)
    x0, y0, x1, y1 = 60, 60, 740, 540
    cv2.rectangle(img, (x0, y0), (x1, y1), wall_color, wall_t)
    for x in (300, 520):
        cv2.line(img, (x, y0), (x, y1), wall_color, wall_t)
    if line_color is not None:
        h = wall_t // 2 + line_t // 2 + 1
        for a, b in ((x0, 300), (300, 520), (520, x1)):
            cv2.rectangle(img, (a + h, y0 + h), (b - h, y1 - h), line_color, line_t)
    if text_color is not None:
        for k, cx in enumerate((180, 410, 630)):
            for j in range(3):
                cv2.putText(img, 'Room 12.5', (cx - 70, 250 + 40 * j), cv2.FONT_HERSHEY_SIMPLEX, 1.0, text_color, 5)
    return img


def test_thin_blue_outlines_on_dark_walls_choose_dark():
    img = sheet(DARK, 12, BLUE, 4)
    cfg = bench.auto_cfg(img)
    assert cfg['mask'][0] == 'dark', cfg


def test_thick_blue_walls_with_dark_text_choose_blue():
    img = sheet(BLUE, 12, text_color=(40, 40, 40))
    cfg = bench.auto_cfg(img)
    assert cfg['mask'] == ('blue',), cfg


def test_dark_walls_without_blue_unchanged():
    cfg = bench.auto_cfg(sheet(DARK, 12))
    assert cfg['mask'][0] == 'dark'
