"""Одношаговый вход (T-20261126-98/4): input_step.run — выпрямление, фон, сетка, усиление линий, вырезка одним вызовом; каждый шаг за флагом, FP_INPUT_ALL=1 — все сразу.

  • всё выкл — тот же объект листа, ops == [], steps == [];
  • FP_INPUT_ALL=1 на листе «серая заливка нашей квартиры + клетка по всему листу»: клетка снята, квартира вырезана, ops ⊇ [grid, cut], steps кончаются шагом crop;
  • FP_INPUT_ALL откатывает окружение (после вызова флаги как были); prepare() кладёт source.inputOps и inputTransform только когда что-то применилось.
"""
import os
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools' / 'floorplan'))
sys.path.insert(0, str(ROOT / 'tests' / 'floorplan'))
import input_step as ins  # noqa: E402
import test_apartment_cut as T  # noqa: E402

FLAGS = ('FP_INPUT_ALL', 'FP_CLEAN_BG', 'FP_CLEAN_RECT', 'FP_CLEAN_GRID', 'FP_CLEAN_LINES', 'FP_CUT_APT')


def _clear(monkeypatch):
    for k in FLAGS:
        monkeypatch.delenv(k, raising=False)


def _sheet(grid=True):
    img = T.sheet_fill()
    if grid:
        for i, x in enumerate(range(5, T.W, 20)):
            seg = img[:, x:x + 1]
            seg[(seg == 255).all(axis=2)] = 190 if i % 5 == 0 else 228
        for i, y in enumerate(range(5, T.H, 20)):
            seg = img[y:y + 1, :]
            seg[(seg == 255).all(axis=2)] = 190 if i % 5 == 0 else 228
    return img


def _pil(img):
    from PIL import Image
    return Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))


def test_all_off_same_object(monkeypatch):
    _clear(monkeypatch)
    sheet = _pil(_sheet())
    r = ins.run(sheet)
    assert r['sheet'] is sheet and r['ops'] == [] and r['steps'] == [] and r['cut']['status'] == 'off'


def test_input_all_one_call(monkeypatch):
    _clear(monkeypatch)
    sheet = _pil(_sheet())
    monkeypatch.setenv('FP_INPUT_ALL', '1')
    r = ins.run(sheet)
    assert 'grid' in r['ops'] and 'cut' in r['ops'], r['ops']
    assert r['steps'][-1]['op'] == 'crop' and r['cut']['status'] == 'cut'
    assert r['sheet'].width < sheet.width * 0.8                                   # вырезано
    for k in ('FP_CLEAN_BG', 'FP_CLEAN_RECT', 'FP_CLEAN_GRID', 'FP_CLEAN_LINES', 'FP_CUT_APT'):
        assert k not in os.environ                                                # окружение возвращено


def test_prepare_writes_input_ops(tmp_path, monkeypatch):
    import pipeline as pl
    _clear(monkeypatch)
    src = tmp_path / 'in.png'
    cv2.imwrite(str(src), _sheet())
    _, off, _ = pl.prepare(src, 'image/png', tmp_path / 'off')
    assert 'inputOps' not in off and 'inputTransform' not in off
    monkeypatch.setenv('FP_INPUT_ALL', '1')
    _, on, _ = pl.prepare(src, 'image/png', tmp_path / 'on')
    assert 'cut' in on['inputOps'] and on['inputTransform'][-1]['op'] == 'crop'


def test_explicit_flags_no_env_and_no_crosstalk(monkeypatch):
    """два run подряд с разными flags не влияют друг на друга, os.environ не меняется и не читается (службе с потоками — без гонки)"""
    _clear(monkeypatch)
    before = dict(os.environ)
    sheet = _pil(_sheet())
    r_cut = ins.run(sheet, {"cut": True})
    r_grid = ins.run(sheet, {"grid": True})
    r_off = ins.run(sheet, {})
    r_cut2 = ins.run(sheet, {"cut": True})
    assert r_cut["ops"] == ["cut"] and r_cut2["ops"] == ["cut"] and r_cut["sheet"].size == r_cut2["sheet"].size
    assert r_grid["ops"] == ["grid"] and r_grid["sheet"].size == sheet.size
    assert r_off["ops"] == [] and r_off["sheet"] is sheet
    assert dict(os.environ) == before
    monkeypatch.setenv("FP_INPUT_ALL", "1")
    assert ins.run(sheet, {})["ops"] == []                        # явный набор сильнее окружения
    assert ins.flags_from_env() == {**{k: True for k in ins.ENV}, "quarter": False, "quarter_after": False, "deskew_guard": False, "deskew_min5": False}      # свои флаги (quarter — OCR; quarter_after, deskew_guard — T-171/k6-zashchita) «все шаги» не включают
