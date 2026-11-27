"""Круг 6, продолжение (T-171/vhod, директор 27.11 22:18): угол без линий страницы, вид «перспектива», четверть по буквам.

Синтетика без внешних файлов и без OCR (идёт в CI):
  • `drop_page_lines`: отрезок длиннее половины хорды листа (линия страницы, рамка) отбрасывается, стена плана и длинная косая стена — нет;
  • план из ТОНКИХ линий под 20° + толстая чёрная полоса поперёк листа (как линейки/рамка скана): по умолчанию (отсев линий страницы + запасной проход) угол ≈ 20°;
    сломал — покраснело: page=False, fallback=False (как в замере 27.11 22:30) → угла нет или он тянется к 0°;
  • перспектива: план в трапеции (верх уже низа) → `perspective` = True; поворот на 10° и прямой лист → False;
  • четверть: `letters_score` считает только кириллические слова ≥ 3 букв; `choose_hybrid` решает буквами, когда их хватает, иначе — символами;
    цифровой лист (букв нет), перевёрнутый на 180°: решают символы при OCR без автоповорота строк; ничья/неясность → 0; `quarter_turn` принимает оценщика, возвращающего (символы, буквы)."""
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools' / 'floorplan'))
sys.path.insert(0, str(ROOT / 'tests' / 'floorplan'))
import cleanup as cl  # noqa: E402
import quarter_turn as Q  # noqa: E402
import test_cleanup as TC  # noqa: E402
import test_deskew as TD  # noqa: E402


def _gray(img):
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)


def thin_grid(W=1200, H=900):
    """план из тонких (1 px) линий: сетка комнат"""
    img = np.full((H, W, 3), 255, np.uint8)
    for y in (200, 400, 600):
        cv2.line(img, (150, y), (1050, y), (60, 60, 60), 1)
    for x in (150, 450, 750, 1050):
        cv2.line(img, (x, 200), (x, 600), (60, 60, 60), 1)
    return img


def rotate_like_td(img, deg):
    h, w = img.shape[:2]
    M = cv2.getRotationMatrix2D((w / 2, h / 2), -deg, 1.0)
    c, s = abs(M[0, 0]), abs(M[0, 1])
    nW, nH = int(np.ceil(h * s + w * c)), int(np.ceil(h * c + w * s))
    M[0, 2] += nW / 2 - w / 2
    M[1, 2] += nH / 2 - h / 2
    return cv2.warpAffine(img, M, (nW, nH), flags=cv2.INTER_CUBIC, borderValue=(255, 255, 255))


def test_drop_page_lines_keeps_walls_drops_rules():
    shape = (900, 1200)
    segs = np.array([[0, 100, 1199, 100],           # на всю ширину — линия страницы
                     [100, 300, 500, 300],          # стена 1/3 ширины
                     [100, 100, 100, 880],          # вертикаль почти на всю высоту — страница
                     [100, 200, 100, 500],          # вертикальная стена
                     [100, 100, 600, 300]], np.float64)   # косая 538 px при хорде ≈ 1 265 px — стена
    kept = cl.drop_page_lines(segs, shape)
    assert [list(map(int, s)) for s in kept] == [[100, 300, 500, 300], [100, 200, 100, 500], [100, 100, 600, 300]]
    assert len(cl.drop_page_lines(np.zeros((0, 4)), shape)) == 0


def test_tilted_thin_plan_found_despite_page_bar():
    img = rotate_like_td(thin_grid(), 20.0)
    cv2.line(img, (0, 40), (img.shape[1] - 1, 40), (0, 0, 0), 14)         # чёрная полоса листа поперёк, как на kazan-13345066
    g = _gray(img)
    th, info = cl.main_angle(g)
    assert th is not None and abs(th - 20.0) < 1.5, (th, info)
    old, oinfo = cl.main_angle(g, page=False, fallback=False)             # −контроль: как в замере 27.11 22:30
    assert old is None or abs(old - 20.0) > 5.0, (old, oinfo)


def test_perspective_flag_on_keystone_not_on_rotation_or_straight():
    img = TC.plan(3, fill=False)
    h, w = img.shape[:2]
    src = np.float32([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]])
    dst = np.float32([[w * 0.18, 0], [w * 0.82, 0], [w - 1, h - 1], [0, h - 1]])      # верх уже низа на 36 %: линии сходятся
    key = cv2.warpPerspective(img, cv2.getPerspectiveTransform(src, dst), (w, h), borderValue=(255, 255, 255))
    flag, info = cl.perspective(_gray(key))
    assert flag is True and info['worst'] >= cl.PERSP_MIN, info
    rot, _ = TD.rotated(10.0)
    assert cl.perspective(_gray(rot))[0] is False                          # чистый поворот — не перспектива
    assert cl.perspective(_gray(img))[0] is False                          # прямой лист — тоже


def test_perspective_sheet_is_not_rotated_but_rotated_sheet_is(monkeypatch):
    rot, _ = TD.rotated(6.0)
    h, w = rot.shape[:2]
    src = np.float32([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]])
    dst = np.float32([[w * 0.18, 0], [w * 0.82, 0], [w - 1, h - 1], [0, h - 1]])
    key = cv2.warpPerspective(rot, cv2.getPerspectiveTransform(src, dst), (w, h), borderValue=(255, 255, 255))
    out, info = cl.deskew_lines(key)
    assert out is None and info['reason'].startswith('перспектива'), info   # лист в трапеции — перспектива, доворот не делаем
    out, info = cl.deskew_lines(rot)
    assert out is not None and info['ok'] and not info['perspective'], info   # просто повёрнутый — доворот как раньше
    monkeypatch.setattr(cl, 'DESKEW_PERSP_VETO', False)                      # −контроль: запрет выключен — причина «перспектива» не звучит
    out, info = cl.deskew_lines(key)
    assert not str(info.get('reason', '')).startswith('перспектива'), info


def test_letters_score_counts_only_cyrillic_words():
    items = [('Кухня', 0.95, None), ('12,3', 0.99, None), ('ванная 4,2', 0.9, None), ('wc', 0.9, None), ('Ку', 0.99, None), ('Комната', 0.3, None)]
    assert Q.letters_score(items) == pytest.approx(5 * 0.95 + 6 * 0.9)       # цифры, латиница, слова < 3 букв и неуверенные не в счёт


def test_hybrid_decides_by_letters_when_enough_else_by_chars():
    k, info = Q.choose_hybrid({0: 80.0, 1: 40.0, 2: 90.0, 3: 30.0}, {0: 2.0, 1: 1.0, 2: 60.0, 3: 0.0})
    assert k == 2 and info['mode'] == 'буквы'                              # символы почти равны, а слова читаются только при 180°
    k, info = Q.choose_hybrid({0: 80.0, 1: 40.0, 2: 90.0, 3: 30.0}, {0: 70.0, 1: 3.0, 2: 10.0, 3: 0.0})
    assert k == 0 and info['mode'] == 'буквы'                              # слова читаются на исходном — не трогаем
    k, info = Q.choose_hybrid({0: 50.0, 1: 60.0, 2: 300.0, 3: 55.0}, {0: 0.0, 1: 0.0, 2: 4.0, 3: 0.0})
    assert k == 2 and info['mode'] == 'символы'                            # букв нет (одни цифры) — по символам
    k, info = Q.choose_hybrid({0: 100.0, 1: 150.0, 2: 90.0, 3: 120.0}, {0: 0.0, 1: 0.0, 2: 0.0, 3: 0.0})
    assert k == 0 and info['mode'] == 'символы'                            # ничья — не трогаем


def test_quarter_turn_accepts_chars_letters_scorer():
    img = np.full((200, 300, 3), 255, np.uint8)
    out, info = Q.quarter_turn(img, lambda k, im: (100.0, 80.0) if k == 3 else (20.0, 0.0))
    assert out is not None and info['k'] == 3 and info['mode'] == 'буквы'
    out, info = Q.quarter_turn(img, lambda k, im: (20.0, 0.0))
    assert out is None and info['ok'] is False
