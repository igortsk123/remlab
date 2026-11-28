"""Доворот повёрнутого листа (T-171/vhod, план Fable otvet-33 задача 6): шаг входа `deskew` (FP_CLEAN_DESKEW, по умолчанию ВЫКЛ).

Синтетика без внешних файлов (идёт в CI): план из толстых стен (test_cleanup.plan), повёрнутый кодом.
  • лист повёрнут на 10° (и на ±5°, ±20°) → после шага главный угол < 1°, угол в паспорте (`deskew_deg`, шаг 'deskew'), ответ ложится обратно на исходный лист (source_point);
  • прямой лист (0°, 0,5° скана) — тот же объект, ops == [], steps == [] (не тронут);
  • лист «под 45°» (> 30°) и лист без линий — не тронуты, причина в info;
  • сломал — покраснело: знак поворота наоборот → остаток ≥ 1° → откат (ops == []), поэтому проверка «ops == ['deskew']» без него красная; шаг выкл → лист остаётся повёрнутым;
  • флаг выкл — prepare() не пишет угол; FP_CLEAN_DESKEW=1 (и FP_INPUT_ALL=1) — пишет `inputDeskewDeg` и шаг в inputTransform.
"""
import os
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools' / 'floorplan'))
sys.path.insert(0, str(ROOT / 'tests' / 'floorplan'))
import apartment_cut as ac  # noqa: E402
import cleanup as cl  # noqa: E402
import input_step as ins  # noqa: E402
import test_cleanup as TC  # noqa: E402

FLAGS = ('FP_INPUT_ALL', 'FP_CLEAN_BG', 'FP_CLEAN_RECT', 'FP_CLEAN_GRID', 'FP_CLEAN_LINES', 'FP_CLEAN_LAYERS', 'FP_CLEAN_DESKEW', 'FP_CUT_APT')


def _clear(monkeypatch):
    for k in FLAGS:
        monkeypatch.delenv(k, raising=False)


def _pil(img):
    from PIL import Image
    return Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))


def rotated(deg, seed=3):
    """прямой план, повёрнутый на deg (+ = по часовой на картинке: линии идут вниз вправо), холст расширен, поле белое"""
    img = TC.plan(seed, fill=False)
    h, w = img.shape[:2]
    M = cv2.getRotationMatrix2D((w / 2, h / 2), -deg, 1.0)          # cv2: + = против часовой → «по часовой» = минус
    c, s = abs(M[0, 0]), abs(M[0, 1])
    nW, nH = int(np.ceil(h * s + w * c)), int(np.ceil(h * c + w * s))
    M[0, 2] += nW / 2 - w / 2
    M[1, 2] += nH / 2 - h / 2
    return cv2.warpAffine(img, M, (nW, nH), flags=cv2.INTER_CUBIC, borderValue=(255, 255, 255)), (M, (w, h))


def angle_of(img):
    th, info = cl.main_angle(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY))
    return th, info


@pytest.mark.parametrize('deg', [10.0, -10.0, 5.0, -5.0, 20.0, -20.0])
def test_rotated_sheet_comes_out_straight(monkeypatch, deg):
    _clear(monkeypatch)
    img, _ = rotated(deg)
    th0, _ = angle_of(img)
    assert th0 is not None and abs(th0 - deg) < 1.0, (th0, deg)                   # вход: угол найден верно, знак тот же
    r = ins.run(_pil(img), {'deskew': True})
    assert r['ops'] == ['deskew'] and [s['op'] for s in r['steps']] == ['deskew']
    out = cv2.cvtColor(np.asarray(r['sheet']), cv2.COLOR_RGB2BGR)
    th1, _ = angle_of(out)
    assert th1 is not None and abs(th1) < 1.0, th1                                 # после шага прямые (< 1°)
    assert abs(r['deskew_deg'] - deg) < 1.0 and r['steps'][0]['residual_deg'] < 1.0   # угол — в паспорте листа


def test_page_rules_do_not_hide_the_plan_angle(monkeypatch):
    """kazan-13345066: план повёрнут на ~20°, а по листу идут длинные горизонтальные линейки/рамка (больше длины по одному углу, чем у стен) — угол плана всё равно найден"""
    _clear(monkeypatch)
    img, _ = rotated(20.0)
    h, w = img.shape[:2]
    for y in (int(h * 0.12), int(h * 0.16), int(h * 0.88)):
        cv2.line(img, (0, y), (w - 1, y), (60, 60, 60), 3)
    th, info = angle_of(img)
    assert th is not None and abs(th - 20.0) < 1.0, (th, info)
    r = ins.run(_pil(img), {'deskew': True})
    assert r['ops'] == ['deskew'] and abs(r['deskew_deg'] - 20.0) < 1.0


def test_only_one_family_is_not_a_plan(monkeypatch):
    """только горизонтальные линейки без стен поперёк (одно семейство) — «главного угла нет», лист не трогаем"""
    _clear(monkeypatch)
    img = np.full((900, 1200, 3), 255, np.uint8)
    for k, y in enumerate(range(100, 800, 60)):
        cv2.line(img, (30, y), (1170, y + 40), (40, 40, 40), 4)                      # наклон 2° — только одно семейство
    th, info = angle_of(img)
    assert th is None and 'главного угла нет' in info['reason'], (th, info)
    sheet = _pil(img)
    assert ins.run(sheet, {'deskew': True})['sheet'] is sheet


def test_straight_sheet_untouched(monkeypatch):
    _clear(monkeypatch)
    for deg in (0.0, 0.5, -0.8):
        img = TC.plan(7, fill=False) if deg == 0.0 else rotated(deg, 7)[0]
        sheet = _pil(img)
        r = ins.run(sheet, {'deskew': True})
        assert r['sheet'] is sheet and r['ops'] == [] and r['steps'] == [] and r['deskew_deg'] is None, deg


def test_45_degrees_and_blank_not_touched(monkeypatch):
    _clear(monkeypatch)
    img, _ = rotated(40.0)
    sheet = _pil(img)
    r = ins.run(sheet, {'deskew': True})
    assert r['sheet'] is sheet and r['ops'] == []
    out, info = cl.deskew_lines(img)
    assert out is None and ('> 30' in info['reason'] or 'главного угла нет' in info['reason']), info
    blank = np.full((600, 800, 3), 255, np.uint8)
    out, info = cl.deskew_lines(blank)
    assert out is None and 'мало линий' in info['reason']


def test_answer_maps_back_to_source_sheet(monkeypatch):
    """точка на довёрнутом листе → на исходном (source_point по шагу 'deskew'): угол стены на исходном листе и положение точки сходятся ≤ 2 px"""
    _clear(monkeypatch)
    img, _ = rotated(12.0)
    r = ins.run(_pil(img), {'deskew': True})
    H = np.array(r['steps'][0]['H'], np.float64)
    for (x, y) in ((300.0, 200.0), (120.0, 450.0), (700.0, 600.0)):               # точки исходного листа → вперёд H → назад source_point
        q = H @ np.array([x, y, 1.0])
        bx, by = ac.source_point(r['steps'], q[0] / q[2], q[1] / q[2])
        assert abs(bx - x) < 2 and abs(by - y) < 2, ((x, y), (bx, by))


def test_control_wrong_sign_rolls_back_and_off_stays_rotated(monkeypatch):
    """сломал — покраснело: знак поворота наоборот → остаток ≈ 2θ ≥ 1° → откат, ops == [] (тест выше «ops == [deskew]» на таком коде красный);
    шаг выкл → лист повёрнут как был"""
    _clear(monkeypatch)
    img, _ = rotated(10.0)
    real = cv2.getRotationMatrix2D
    monkeypatch.setattr(cl.cv2, 'getRotationMatrix2D', lambda c, a, s: real(c, -a, s))
    r = ins.run(_pil(img), {'deskew': True})
    assert r['ops'] == [] and r['steps'] == [] and r['deskew_deg'] is None
    monkeypatch.undo()
    off = ins.run(_pil(img), {})
    th, _ = angle_of(cv2.cvtColor(np.asarray(off['sheet']), cv2.COLOR_RGB2BGR))
    assert off['ops'] == [] and abs(th - 10.0) < 1.0                              # шаг выкл — лист повёрнут как был


def test_flag_off_by_default_and_env_switches_it_on(monkeypatch):
    _clear(monkeypatch)
    assert cl.flag_deskew() is False and ins.flags_from_env()['deskew'] is False
    monkeypatch.setenv('FP_CLEAN_DESKEW', '1')
    assert cl.flag_deskew() is True and ins.flags_from_env()['deskew'] is True and ins.flags_from_env()['rect'] is False
    monkeypatch.delenv('FP_CLEAN_DESKEW')
    monkeypatch.setenv('FP_INPUT_ALL', '1')
    assert ins.flags_from_env()['deskew'] is True


def test_prepare_writes_angle_to_source_passport(tmp_path, monkeypatch):
    import pipeline as pl
    _clear(monkeypatch)
    img, _ = rotated(10.0)
    src = tmp_path / 'in.png'
    cv2.imwrite(str(src), img)
    _, off, _ = pl.prepare(src, 'image/png', tmp_path / 'off')
    assert 'inputDeskewDeg' not in off and 'inputTransform' not in off and 'inputOps' not in off      # выкл — паспорт прежний
    monkeypatch.setenv('FP_CLEAN_DESKEW', '1')
    sheet_png, on, _ = pl.prepare(src, 'image/png', tmp_path / 'on')
    assert on['inputOps'] == ['deskew'] and abs(on['inputDeskewDeg'] - 10.0) < 1.0
    assert on['inputTransform'][0]['op'] == 'deskew' and on['imageW'] == cv2.imread(str(sheet_png)).shape[1]
