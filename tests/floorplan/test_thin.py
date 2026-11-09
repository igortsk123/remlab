"""T-20261109-09: маска тонких стен и водяного знака, семейства углов с разносом, безопасное имя кадра."""
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools' / 'floorplan'))
import fpcore as fc  # noqa: E402
import stitch  # noqa: E402


def sheet_thin():
    """Белый лист: наружные стены 4 px, внутренняя стена 2 px (как E/F), текст — короткие штрихи 2 px."""
    g = np.full((200, 300), 255, np.uint8)
    g[20:24, 20:281] = 0; g[177:181, 20:281] = 0; g[20:181, 20:24] = 0; g[20:181, 277:281] = 0   # ровно 4 px
    g[22:178, 150:152] = 20                                # тонкая внутренняя стена 2 px
    for x in range(60, 110, 8):                            # «текст»: штрихи 2×7
        g[90:97, x:x + 2] = 0
    return cv2.cvtColor(g, cv2.COLOR_GRAY2BGR)


def test_line_kernel_direction():
    k = fc.line_kernel(11, 0)
    assert k[5].sum() == 11 and k.sum() == 11
    k = fc.line_kernel(11, 90)
    assert k[:, 5].sum() == 11
    k = fc.line_kernel(11, 45)
    assert k[0, 0] and k[10, 10] and not k[0, 10]          # y вниз: 45° — с левого верха в правый низ


def test_long_strokes_keeps_thin_line_drops_text():
    m = np.zeros((100, 100), np.uint8)
    m[50, 10:90] = 1                                       # линия 1 px длиной 80
    m[20:27, 20:22] = 1                                    # буква: 2×7
    out = fc.long_strokes(m, 21)
    assert out[50, 10:90].all()
    assert not out[20:27, 20:22].any()


def test_grow_within_limited():
    m = np.zeros((10, 40), np.uint8)
    m[5, :] = 1
    seed = np.zeros_like(m)
    seed[5, 0] = 1
    g = fc.grow_within(seed, m, 5)
    assert g[5, :6].all() and not g[5, 7:].any()


def test_hysteresis_keeps_wall_under_watermark():
    g = np.full((60, 120), 255, np.uint8)
    g[30:34, 5:115] = 30                                   # стена
    g[20:44, 50:70] = 200                                  # полупрозрачный знак: фон светлее
    g[30:34, 50:70] = 140                                  # стена под знаком — светлее порога 125
    g[5:10, 90:110] = 160                                  # отдельная серая клякса (не связана со стеной)
    h = fc.hysteresis(g, 125, 170)
    assert h[30:34, 50:70].all()                           # стена под знаком — целая
    assert not h[5:10, 90:110].any()                       # серое отдельно — не стена
    assert not h[20:30, 50:70].any()                       # сам знак — не стена


def test_wall_mask_auto_thin_modes_recover_2px_wall():
    img = sheet_thin()
    base, info = fc.wall_mask_auto(img, 'base')
    assert not base[100, 149:152].any()                    # открытие 3 стирает стену в 2 px (как E/F)
    assert info['open'] == 3
    for mode in ('lines', 'lsd'):
        m, _ = fc.wall_mask_auto(img, mode)
        assert m[40:160, 149:152].any(axis=1).mean() > 0.95, mode
        assert not m[90:97, 60:110].any(), mode           # текст не стал стеной
    w, info = fc.wall_mask_auto(img, 'width')
    assert info['thin_share'] > 0 and info['open'] == 2
    assert w[40:160, 149:152].any(axis=1).mean() > 0.95
    assert (w >= base).all()                               # открытие 2 без сдвига: всё, что было при 3, на месте


def test_wall_mask_auto_thick_sheet_unchanged():
    g = np.full((300, 300), 255, np.uint8)
    cv2.rectangle(g, (20, 20), (280, 280), 0, 24)           # толстые стены (B) — открытие 5, как было
    g[44:60, 44:46] = 150                                   # серый штрих мебели, примыкающий к стене
    m, info = fc.wall_mask_auto(cv2.cvtColor(g, cv2.COLOR_GRAY2BGR), 'lines', thr_hi=170)
    assert info['open'] == 5
    ref = fc.wall_mask_dark(g, 125, 5, 120)
    assert (m == ref).all()                                 # толстые: гистерезис и добавки не применяются


def test_wall_mask_auto_medium_sheet_no_thin_layer():
    g = np.full((300, 300), 255, np.uint8)
    cv2.rectangle(g, (20, 20), (280, 280), 0, 8)            # стены 8 px (C, G) — тонкий слой не нужен
    g[150, 30:270] = 40                                     # линия 1 px (размерная) — стеной не становится
    g[60:62, 30:270] = 150                                  # серый штрих, примыкающий к стене — без гистерезиса
    for mode in ('lines', 'lsd', 'width'):
        m, info = fc.wall_mask_auto(cv2.cvtColor(g, cv2.COLOR_GRAY2BGR), mode, thr_hi=170)
        assert info['open'] == 3 and not info['thin'], mode
        assert (m == fc.wall_mask_dark(g, 125, 3, 60)).all(), mode


def test_build_mask_thin_layer_only_on_thin_sheet(monkeypatch):
    import bench
    monkeypatch.delenv('FP_MASK', raising=False)
    thin = sheet_thin()
    cfg = {'mask': ('dark', 125, 3), 'min_area': 60}
    m = bench.build_mask(thin, cfg)
    assert cfg['mask_info']['thin'] and cfg['thin_hi'] > 125
    assert m[40:160, 149:152].any(axis=1).mean() > 0.95      # тонкая стена 2 px на месте
    g = np.full((300, 300), 255, np.uint8)
    cv2.rectangle(g, (20, 20), (280, 280), 0, 8)
    mid = cv2.cvtColor(g, cv2.COLOR_GRAY2BGR)
    cfg = {'mask': ('dark', 110, 3), 'min_area': 60}         # как C: порог и открытие плана, добавки нет
    assert (bench.build_mask(mid, cfg) == fc.wall_mask_dark(mid, 110, 3, 60)).all() and 'thin_hi' not in cfg
    g = np.full((300, 300), 255, np.uint8)
    cv2.rectangle(g, (20, 20), (280, 280), 0, 24)
    thick = cv2.cvtColor(g, cv2.COLOR_GRAY2BGR)
    cfg = {'mask': ('dark', 135, 5), 'min_area': 120}        # как B: толстые — маска плана
    assert (bench.build_mask(thick, cfg) == fc.wall_mask_dark(thick, 135, 5, 120)).all() and 'thin_hi' not in cfg
    monkeypatch.setenv('FP_MASK', 'old')
    cfg = {'mask': ('dark', 125, 3), 'min_area': 60}
    assert (bench.build_mask(thin, cfg) == fc.wall_mask_dark(thin, 125, 3, 60)).all()


def test_separate_families_keeps_longer_of_close_pair():
    hist = np.zeros(180)
    hist[0] += 100; hist[90] += 100; hist[6] += 400; hist[96] += 300
    out = fc.separate_families([0.5, 90.2, 5.7, 95.7], hist, 8.0)
    assert len(out) == 2
    assert any(fc.angdiff(f, 5.7) < 0.1 for f in out) and any(fc.angdiff(f, 95.7) < 0.1 for f in out)
    out = fc.separate_families([0.0, 90.0, 45.0], np.ones(180), 8.0)
    assert len(out) == 3                                   # эркер 45° — не «близкое» семейство


def test_panel_families_min_separation():
    m = np.zeros((400, 400), np.uint8)
    box = cv2.boxPoints(((200, 200), (300, 200), 5.5)).astype(np.int32)   # крыло под 5,5°
    cv2.polylines(m, [box], True, 1, 6)
    cv2.line(m, (20, 20), (120, 20), 1, 6)                 # короткий осевой кусок
    fams = fc.panel_families(m, 60)
    assert all(fc.angdiff(a, b) >= 8 for i, a in enumerate(fams) for b in fams[i + 1:])
    assert any(fc.angdiff(f, 5.5) < 1.5 for f in fams)


def test_room_body_inside_bay_not_empty():
    import bench
    lab = np.zeros((20, 20), np.int32)
    lab[2:8, 2:8] = 1
    lab[10:14, 10:14] = 2
    bay = np.zeros((20, 20), bool)
    bay[2:8, 6:8] = True                                   # эркер у комнаты 1
    bay[9:15, 9:15] = True                                 # комната 2 целиком в эркере
    res = {'lab': lab, 'bay_in': bay}
    assert bench.room_body(res, 1).sum() == 24             # без эркера
    assert bench.room_body(res, 2).sum() == 16             # целиком в эркере — как есть, не пусто
    assert bench.room_body({'lab': lab}, 1).sum() == 36


def test_stitch_safe_name():
    assert stitch.safe_name('Garage / Workshop') == 'Garage - Workshop'
    assert '/' not in stitch.safe_name('a/b\\c:d')
    assert stitch.safe_name('///') == 'panel'
    assert stitch.safe_name('Ground Floor') == 'Ground Floor'
