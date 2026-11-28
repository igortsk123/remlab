"""Порог доворота 5° (T-171/k6-porog5, Fable otvet-49; круг 6). Флаг свой FP_CLEAN_DESKEW_MIN5, по умолчанию ВЫКЛ, FP_INPUT_ALL=1 его не включает.

Без OCR и сети (идёт в CI); лист — синтетика test_deskew.rotated.
  • флаг ВКЛ: главный угол 4° — шаг лист не трогает (ops пусто, лист тот же, причина в info); 6° — доворачивает до прямого;
  • −контроль (старый порог 1,5°): тот же лист на 4° с прежним порогом ДОВОРАЧИВАЕТСЯ — тест красный, если новый порог откатить на 1,5;
  • флаг ВЫКЛ = побайтно прежнее: 4° доворачивается как до правки, результат равен вызову со старым порогом явно (min_deg=DESKEW_MIN);
  • порог лежит в deskew_min.json с непустым _why; четверть при <5° как есть: доворота нет — второго прохода четверти нет."""
import json
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools' / 'floorplan'))
sys.path.insert(0, str(ROOT / 'tests' / 'floorplan'))
import cleanup as cl  # noqa: E402
import input_step as ins  # noqa: E402
import test_deskew as TD  # noqa: E402
import test_deskew_guard as TG  # noqa: E402

FLAGS = ('FP_INPUT_ALL', 'FP_CLEAN_BG', 'FP_CLEAN_RECT', 'FP_CLEAN_GRID', 'FP_CLEAN_LINES', 'FP_CLEAN_LAYERS', 'FP_CLEAN_DESKEW', 'FP_CLEAN_DESKEW_GUARD',
         'FP_CLEAN_DESKEW_MIN5', 'FP_CLEAN_QUARTER', 'FP_CLEAN_QUARTER_AFTER', 'FP_CUT_APT')


def _clear(monkeypatch):
    for k in FLAGS:
        monkeypatch.delenv(k, raising=False)


def test_threshold_lives_in_json_with_why():
    d = json.loads((ROOT / 'tools' / 'floorplan' / 'deskew_min.json').read_text(encoding='utf-8'))
    assert d['min_deg'] == 5.0 and len(d['_why']) > 200 and cl.DESKEW_MIN_HIGH == 5.0
    assert cl.DESKEW_MIN == 1.5                                                            # прежний порог не тронут


def test_flag_is_own_and_off(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv('FP_INPUT_ALL', '1')
    assert ins.flags_from_env()['deskew'] and not ins.flags_from_env()['deskew_min5']     # FP_INPUT_ALL=1 свой флаг НЕ включает
    _clear(monkeypatch)
    assert not ins.flags_from_env()['deskew_min5'] and not cl.flag_deskew_min5()
    monkeypatch.setenv('FP_CLEAN_DESKEW_MIN5', '1')
    assert ins.flags_from_env()['deskew_min5'] and cl.flag_deskew_min5()


def test_4_degrees_not_touched_with_flag(monkeypatch):
    _clear(monkeypatch)
    img, _ = TD.rotated(4.0)
    th, _ = TD.angle_of(img)
    assert 3.0 < abs(th) < 5.0, th                                                         # лист действительно на ~4°
    sheet = TG._pil(img)
    r = ins.run(sheet, {'deskew': True, 'deskew_min5': True})
    assert r['ops'] == [] and r['steps'] == [] and r['sheet'] is sheet                    # шаг лист не трогает: тот же объект
    _, info = cl.deskew_lines(img, min_deg=cl.DESKEW_MIN_HIGH)
    assert 'лист ровный' in info['reason'] and '5.0' in info['reason']


def test_6_degrees_turned_with_flag(monkeypatch):
    _clear(monkeypatch)
    img, _ = TD.rotated(6.0)
    r = ins.run(TG._pil(img), {'deskew': True, 'deskew_min5': True})
    assert r['ops'] == ['deskew'] and [s['op'] for s in r['steps']] == ['deskew']
    th, _ = TD.angle_of(TG._bgr(r['sheet']))
    assert th is None or abs(th) < 1.0, th                                                 # после доворота лист прямой


def test_control_old_threshold_turns_4_degrees(monkeypatch):
    _clear(monkeypatch)
    img, _ = TD.rotated(4.0)
    out, info = cl.deskew_lines(img, min_deg=cl.DESKEW_MIN)                                # −контроль: порог 1,5° (старый) — 4° доворачивается
    assert out is not None and info['ok'], info
    out5, _ = cl.deskew_lines(img, min_deg=cl.DESKEW_MIN_HIGH)
    assert out5 is None                                                                    # порог 5° — нет: разница и есть новое правило


@pytest.mark.parametrize('deg', [2.0, 4.0, 10.0])
def test_flag_off_is_byte_identical_to_before(monkeypatch, deg):
    _clear(monkeypatch)
    img, _ = TD.rotated(deg)
    a = ins.run(TG._pil(img), {'deskew': True})
    b = ins.run(TG._pil(img), {'deskew': True, 'deskew_min5': False})
    assert a['ops'] == b['ops'] == ['deskew']                                              # флаг выкл: 2° и 4° доворачиваются, как до правки
    assert np.array_equal(np.asarray(a['sheet']), np.asarray(b['sheet'])) and a['steps'] == b['steps']
    old, _ = cl.deskew_lines(img)                                                          # вызов без параметра = старый порог явно
    old2, _ = cl.deskew_lines(img, min_deg=cl.DESKEW_MIN)
    assert np.array_equal(old, old2) and np.array_equal(old, TG._bgr(a['sheet']))


def test_flag_on_above_threshold_same_as_flag_off(monkeypatch):
    _clear(monkeypatch)
    img, _ = TD.rotated(10.0)
    a = ins.run(TG._pil(img), {'deskew': True})
    b = ins.run(TG._pil(img), {'deskew': True, 'deskew_min5': True})
    assert np.array_equal(np.asarray(a['sheet']), np.asarray(b['sheet'])) and a['steps'] == b['steps']     # от 5° флаг ничего не меняет


def test_quarter_as_is_below_threshold(monkeypatch):
    _clear(monkeypatch)
    straight = TG.marked_plan()
    img = TG.tilt(cv2.rotate(straight, cv2.ROTATE_180), 4.0)                               # 4° и вверх ногами: доворота нет → четверть как есть, второго прохода нет
    calls = []
    flags = {'deskew': True, 'deskew_min5': True, 'quarter': True, 'quarter_after': True}
    r = ins.run(TG._pil(img), flags, scorer=TG.make_scorer(calls))
    assert 'deskew' not in r['ops'] and calls == [0, 1, 2, 3]
