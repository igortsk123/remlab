"""T-98/21: два слоя чернил листа (tools/floorplan/ink_layers.py) на синтетических листах. Номеров листов нет — только свойства слоёв."""
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'tools', 'floorplan'))
import ink_layers as il  # noqa: E402


def _sheet(paper=250):
    return np.full((600, 800), paper, np.uint8)


def _bgr(g, noise=0.0, seed=0, shade=None):
    f = g.astype(np.float32)
    if shade is not None:
        f = f * shade
    if noise:
        f += np.random.default_rng(seed).normal(0, noise, f.shape).astype(np.float32)
    return cv2.cvtColor(np.clip(f, 0, 255).astype(np.uint8), cv2.COLOR_GRAY2BGR)


def _text(g, x, y, val):
    cv2.putText(g, '1.25', (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.9, val, 2, cv2.LINE_AA)


def test_thick_walls_strict_thin_furniture_and_text_only_sensitive():
    g = _sheet()
    cv2.rectangle(g, (100, 100), (700, 500), 40, 12)       # толстые стены
    for x0 in (200, 330, 460):
        cv2.rectangle(g, (x0, 200), (x0 + 100, 260), 90, 1)    # тонкая мебель
    _text(g, 400, 300, 60)                                  # подпись
    sens, strict, pp = il.layers_of_bgr(_bgr(g, noise=1.5))
    assert pp['годен'] and sens.shape == g.shape and (strict <= sens).all()
    wall = np.zeros(g.shape, bool)
    wall[97:103, 120:680] = True
    assert strict[wall].mean() > 0.9                        # стена в строгом
    assert sens[wall].mean() > 0.9
    assert not strict[195:265, 195:305].any()               # мебель — не в строгом
    assert sens[195:265, 195:305].any()                     # но в чутком
    assert not strict[270:320, 395:520].any()               # подпись — не в строгом


def test_gray_fill_is_not_a_wall_black_walls_are():
    g = _sheet()
    cv2.rectangle(g, (30, 30), (80, 560), 190, -1)          # серая заливка (река/фон), уже окна фона
    cv2.rectangle(g, (300, 100), (700, 500), 30, 14)        # чёрные стены
    sens, strict, pp = il.layers_of_bgr(_bgr(g, noise=1.0, seed=3))
    assert pp['годен']
    assert not strict[100:500, 30:80].any()                # но не в строгом (не стена)
    wall = np.zeros(g.shape, bool)
    wall[97:103, 320:680] = True
    assert strict[wall].mean() > 0.9


def test_pale_thin_walls_sensitive_sees_them_strict_long_axis_lines_only():
    g = _sheet(245)
    cv2.rectangle(g, (100, 100), (700, 500), 205, 2)       # бледные тонкие стены (глубина ~16 %)
    _text(g, 400, 300, 200)
    sens, strict, pp = il.layers_of_bgr(_bgr(g, noise=1.0, seed=1))
    assert pp['годен']
    line = np.zeros(g.shape, bool)
    line[100:101, 120:680] = True
    assert sens[line].mean() > 0.8                          # бледная линия найдена
    assert strict[line].mean() > 0.8                        # длинная прямая — и в строгом
    assert not strict[270:320, 395:520].any()               # подпись — нет
    assert sens.mean() < 0.05                               # бумажное зерно не принято за линии


def test_shaded_sheet_lines_still_found():
    g = _sheet()
    cv2.rectangle(g, (100, 100), (700, 500), 20, 10)
    shade = np.linspace(1.0, 0.6, g.shape[1], dtype=np.float32)[None, :]     # лист темнеет к краю (освещение)
    sens, strict, pp = il.layers_of_bgr(_bgr(g, noise=1.0, seed=2, shade=shade))
    assert pp['годен']
    right = np.zeros(g.shape, bool)
    right[120:480, 697:703] = True
    assert strict[right].mean() > 0.8                       # стена в тёмной части листа найдена
    assert sens.mean() < 0.2                                # тёмный край не принят за чернила


def test_blank_and_black_sheets_not_usable_layers_empty():
    for g in (_sheet(), _sheet(10)):
        sens, strict, pp = il.layers_of_bgr(_bgr(g, noise=1.0))
        assert pp['годен'] is False and 'причина' in pp
        assert not sens.any() and not strict.any()


def test_config_has_why_and_no_pixel_thresholds():
    cfg = il.load_cfg()
    assert all(k in cfg for k in ('_why', 'paper_noise_k', 'strict_min_len_strokes', 'usable_ink_frac'))
    assert all(f'_why_{k}' in cfg for k in ('bg', 'sens', 'local', 'area', 'strict', 'thick', 'strict_shape', 'usable'))
