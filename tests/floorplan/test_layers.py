"""Слои (класс Г, T-20261126-98/4): cleanup.separate_layers — зелёная мебель и синие размерные линии отдельно от стен; флаг FP_CLEAN_LAYERS, по умолчанию выкл.

  • зелёные контуры мебели и синяя размерная линия с цифрой стираются; серые стены, красные подписи площадей, цифры — нетронуты (пиксель в пиксель);
  • маски слоёв отдаются отдельно (для нейросети);
  • фото (тёмная бумага, насыщенный фон), красное/сиреневое как данные, лист без цвета — не трогаем (None);
  • выключено — clean_sheet_steps возвращает тот же объект; явный flags={'layers': True} включает без окружения.
"""
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools' / 'floorplan'))
import cleanup as cl  # noqa: E402

W, H = 900, 640
GREEN, BLUE, RED, WALL = (60, 170, 60), (200, 90, 20), (30, 30, 200), (70, 70, 70)


def cad_sheet(furniture=True, dims=True, red_text=True):
    img = np.full((H, W, 3), 255, np.uint8)
    cv2.rectangle(img, (60, 60), (840, 580), WALL, 9)                       # внешние стены
    cv2.line(img, (450, 60), (450, 580), WALL, 7)                           # перегородка
    if furniture:
        for (x, y) in [(120, 130), (520, 300), (200, 420)]:
            cv2.rectangle(img, (x, y), (x + 110, y + 70), GREEN, 2)         # диван/стол: контур
            cv2.rectangle(img, (x + 12, y + 12), (x + 98, y + 58), GREEN, 2)
    if dims:
        cv2.line(img, (120, 110), (400, 110), BLUE, 2)                      # размерная линия
        cv2.putText(img, '280', (232, 104), cv2.FONT_HERSHEY_SIMPLEX, 0.45, BLUE, 1, cv2.LINE_AA)       # цифра размера того же цвета (как в образце kazan-14520382)
    if red_text:
        cv2.putText(img, 'S=12.4', (600, 160), cv2.FONT_HERSHEY_SIMPLEX, 0.6, RED, 2, cv2.LINE_AA)
    return img


def share(img, color, tol=40):
    return int((np.abs(img.astype(int) - np.array(color)).sum(axis=2) < tol).sum())


def test_furniture_and_dims_removed_walls_and_data_kept():
    img = cad_sheet()
    out, info, masks = cl.separate_layers(img)
    assert out is not None, info
    assert info['dim_lines'] >= 1 and info['furniture_px'] > 300
    assert share(out, GREEN) < 0.05 * share(img, GREEN)                      # мебель стёрта
    assert share(out, BLUE) < 0.1 * share(img, BLUE)                         # размерная линия стёрта
    wall = np.all(np.abs(img.astype(int) - np.array(WALL)) < 6, axis=2)
    assert (out[wall] == img[wall]).all()                                    # стены — пиксель в пиксель
    red = np.all(np.abs(img.astype(int) - np.array(RED)) < 60, axis=2)
    assert red.sum() > 100 and (out[red] == img[red]).all()                  # красная подпись площади цела
    assert set(masks) == {'furniture', 'dims'} and masks['furniture'].any() and masks['dims'].any()


def test_nothing_to_do_returns_none():
    out, info, masks = cl.separate_layers(cad_sheet(furniture=False, dims=False))
    assert out is None and masks == {}


def test_photo_and_colour_data_are_not_touched():
    photo = cad_sheet().astype(np.int16)
    photo[..., 0] += 25                                                      # жёлтый/синий оттенок бумаги: фото
    photo[..., 2] -= 20
    assert cl.separate_layers(np.clip(photo, 0, 255).astype(np.uint8))[0] is None
    dark = (cad_sheet() * 0.6).astype(np.uint8)                              # тёмный фон
    assert cl.separate_layers(dark)[0] is None
    red_only = cad_sheet(furniture=False, dims=False)
    for (x, y) in [(120, 130), (520, 300)]:
        cv2.rectangle(red_only, (x, y), (x + 110, y + 70), RED, 2)           # красные рамки = метки/данные, не мебель
    out, _, _ = cl.separate_layers(red_only)
    assert out is None


def test_flag_off_same_object_and_explicit_flag_on(monkeypatch):
    monkeypatch.delenv('FP_CLEAN_LAYERS', raising=False)
    sheet = Image.fromarray(cv2.cvtColor(cad_sheet(), cv2.COLOR_BGR2RGB))
    assert cl.flag_layers() is False
    s0, ops0, st0 = cl.clean_sheet_steps(sheet)
    assert s0 is sheet and ops0 == [] and st0 == []
    s1, ops1, st1 = cl.clean_sheet_steps(sheet, {'layers': True})
    assert ops1 == ['layers'] and st1 == [] and s1.size == sheet.size and s1 is not sheet
    assert 'FP_CLEAN_LAYERS' not in __import__('os').environ


def test_closing_coloured_line_at_wall_is_kept_but_room_furniture_goes():
    """цветная линия, замыкающая помещение (оба конца у стены — балкон/лоджия), остаётся: это граница, не мебель; стол в комнате уходит"""
    img = cad_sheet(dims=False, red_text=False)
    pts = np.array([(500, 67), (500, 200), (760, 200), (760, 67)], np.int32)
    cv2.polylines(img, [pts], False, GREEN, 2)                                # балкон-ниша у верхней стены: концы на стене
    cv2.line(img, (630, 200), (630, 205), GREEN, 2)
    out, info, masks = cl.separate_layers(img)
    assert out is not None and info.get("kept_closing", 0) >= 1, info
    box = (slice(60, 215), slice(490, 775))
    assert share(out[box], GREEN) >= 0.95 * share(img[box], GREEN)            # линия балкона цела
    room = (slice(290, 380), slice(510, 640))                                 # стол из cad_sheet() в комнате
    assert share(out[room], GREEN) < 0.05 * max(share(img[room], GREEN), 1)
