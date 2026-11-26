"""Вырезать нашу квартиру из листа (T-20261126-98/4, проба 2 → бой за флагом FP_CUT_APT, по умолчанию выкл).

Синтетика без внешних файлов (идёт в CI): лист с нашей квартирой и соседней, выделение — заливка / красный контур / жирный контур / поле вокруг плана.
  • вырезка: снаружи белый, подписи нашей квартиры на месте, чужие убраны, кадр меньше листа; обратное преобразование точно возвращает точку на исходный лист;
  • дефект 9583744: балкон с подписью «(1,37)» не теряется (шум подписи внутри заливки не отбрасывает заливку); автопроверка подписей до/после;
  • дефект krasnodar: цветная метка на стене не оставляет выемки — закрашена цветом стены; выемок после 0;
  • нет выделения / серые толстые стены без заливки / белый лист — лист как есть («пометка»); флаг выкл — тот же объект; сбой — лист как есть;
  • `prepare()` за флагом пишет `inputTransform` (шаги входа, меняющие геометрию).
"""
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools' / 'floorplan'))
import apartment_cut as ac  # noqa: E402

W, H = 1000, 760
OUR = (80, 140, 560, 640)       # x0, y0, x1, y1 — наша квартира
NEIGH = (560, 140, 900, 640)    # соседняя


def _rooms(img, box, col=(40, 40, 40), t=9):
    x0, y0, x1, y1 = box
    cv2.rectangle(img, (x0, y0), (x1, y1), col, t)
    cv2.line(img, ((x0 + x1) // 2, y0), ((x0 + x1) // 2, y1), col, t)
    cv2.line(img, (x0, (y0 + y1) // 2), ((x0 + x1) // 2, (y0 + y1) // 2), col, t)


def _text(img, s, org, scale=0.8):
    cv2.putText(img, s, org, cv2.FONT_HERSHEY_SIMPLEX, scale, (30, 30, 30), 2, cv2.LINE_AA)


def sheet_fill(balcony=True):
    """наша квартира залита серым (177) + подписи; соседняя — без заливки; у нашей справа-внизу балкон тоже серый, подпись «(1,37)»"""
    img = np.full((H, W, 3), 255, np.uint8)
    img[OUR[1]:OUR[3], OUR[0]:OUR[2]] = 177
    if balcony:
        img[OUR[3]:OUR[3] + 70, 380:540] = 177
    _rooms(img, OUR)
    _rooms(img, NEIGH)
    for i, o in enumerate([(130, 220), (330, 220), (130, 480), (330, 480)]):
        _text(img, f'{12.3 + i:.1f}', o)
    _text(img, '88.8', (700, 300))
    _text(img, '77.7', (700, 500))
    if balcony:
        cv2.rectangle(img, (380, OUR[3]), (540, OUR[3] + 70), (40, 40, 40), 3)
        _text(img, '(1,37)', (400, OUR[3] + 45), 0.9)
        img[OUR[3] + 12:OUR[3] + 26, 390:430] = (110, 110, 110)    # штрих разметки: разброс тона внутри заливки
    return img


def sheet_red():
    img = np.full((H, W, 3), 255, np.uint8)
    _rooms(img, OUR, t=4)
    _rooms(img, NEIGH, t=4)
    cv2.rectangle(img, (OUR[0] - 14, OUR[1] - 14), (OUR[2] + 14, OUR[3] + 14), (30, 30, 200), 3)
    for o in [(130, 220), (330, 220), (130, 480), (330, 480)]:
        _text(img, '12.3', o)
    _text(img, '88.8', (700, 300))
    return img


def sheet_bold():
    img = np.full((H, W, 3), 245, np.uint8)
    _rooms(img, OUR, t=2)
    _rooms(img, NEIGH, t=2)
    for k in range(16):                                           # много тонких линий (размерные, мебель): жирный контур — малая доля чернил
        y = 60 + k * 40
        cv2.line(img, (30 + 15 * (k % 3), y), (970 - 15 * (k % 5), y), (60, 60, 60), 2)
    for k in range(10):
        x = 40 + k * 95
        cv2.line(img, (x, 20), (x, 740), (60, 60, 60), 2)
    cv2.rectangle(img, (OUR[0] - 10, OUR[1] - 10), (OUR[2] + 10, OUR[3] + 10), (20, 20, 20), 9)
    for o in [(130, 220), (330, 220), (130, 480), (330, 480)]:
        _text(img, '12.3', o)
    _text(img, '88.8', (700, 300))
    return img


def sheet_field(dot=True):
    """поле вокруг плана залито голубым; на правой внешней стене — синий кружок (метка), цвет которого совпадает с полем по тону"""
    img = np.full((H, W, 3), (235, 190, 120), np.uint8)       # голубое (BGR)
    plan = (110, 90, 890, 670)
    cv2.rectangle(img, (plan[0], plan[1]), (plan[2], plan[3]), (255, 255, 255), -1)
    _rooms(img, plan, t=8)
    for o in [(200, 220), (550, 220), (200, 480), (550, 480)]:
        _text(img, '12.3', o)
    if dot:
        cv2.circle(img, (plan[2], 380), 12, (215, 110, 0), -1)
    return img


def sheet_wall_ring():
    """толстые серые стены без заливки: кольцо стен — не заливка квартиры"""
    img = np.full((H, W, 3), 255, np.uint8)
    _rooms(img, OUR, col=(137, 137, 137), t=26)
    _text(img, '12.3', (200, 300))
    return img


def sheet_plain():
    img = np.full((H, W, 3), 255, np.uint8)
    _rooms(img, OUR)
    _rooms(img, NEIGH)
    _text(img, '12.3', (200, 300))
    return img


def _share_white(img, box):
    x0, y0, x1, y1 = box
    if img[max(y0, 0):y1, max(x0, 0):x1].size == 0:      # места нет в кадре — убрано совсем
        return 1.0
    return float((img[max(y0, 0):y1, max(x0, 0):x1].min(axis=2) >= 250).mean())


# ───────────────── вырезка по выделению ─────────────────

@pytest.mark.parametrize('kind,maker,method', [
    ('fill', sheet_fill, 'заливка'),
    ('red', sheet_red, 'цветной контур'),
    ('bold', sheet_bold, 'жирный контур'),
])
def test_cut_by_highlight(kind, maker, method):
    img = maker()
    out, info = ac.cut_bgr(img)
    assert info['status'] == 'cut' and info['method'] == method, info
    tr = info['transform']
    x0, y0, x1, y1 = tr['box']
    assert out.shape[1] == x1 - x0 and out.shape[0] == y1 - y0
    assert out.shape[1] < img.shape[1] * 0.8                          # кадр заметно меньше листа: соседняя квартира убрана
    # чужое убрано: на месте подписей соседней — белое
    nx0, ny0 = 690 - x0, 270 - y0
    assert _share_white(out, (nx0, ny0, nx0 + 120, ny0 + 40)) >= 0.99
    # своё осталось: подпись нашей квартиры (130,220)-(200,240) на месте и тёмная
    ox, oy = 130 - x0, 205 - y0
    assert out[oy:oy + 40, ox:ox + 80].min() < 100
    assert info['labels_out'] >= info['labels_sel'] - max(1, round(0.03 * info['labels_sel']))
    assert info['notches_after'] == 0


def test_inverse_transform_returns_source_point():
    img = sheet_red()
    out, info = ac.cut_bgr(img)
    assert info['status'] == 'cut'
    steps = [{'op': 'crop', **info['transform']}]
    # самая левая красная точка контура в кадре → на исходном листе та же красная точка (контур слева на x = OUR[0] - 14)
    ys, xs = np.where((out[:, :, 0] < 60) & (out[:, :, 2] > 150))
    j = int(np.argmin(xs))
    sx, sy = ac.source_point(steps, xs[j], ys[j])
    assert abs(sx - (OUR[0] - 14)) <= 4, (sx, sy)
    assert img[int(round(sy)), int(round(sx))][0] < 60 and img[int(round(sy)), int(round(sx))][2] > 150
    # поворот/гомография разворачиваются обратной матрицей
    Hm = [[1.0, 0.1, 5.0], [0.0, 1.0, 3.0], [0.0, 0.0, 1.0]]
    px = np.array(Hm) @ np.array([100.0, 50.0, 1.0])
    rx, ry = ac.source_point([{'op': 'rectify', 'H': Hm}], px[0], px[1])
    assert (round(rx, 6), round(ry, 6)) == (100.0, 50.0)


# ───────────────── дефект 9583744: балкон с подписью не теряется ─────────────────

def test_balcony_with_label_stays():
    img = sheet_fill(balcony=True)
    out, info = ac.cut_bgr(img)
    assert info['status'] == 'cut', info
    x0, y0, _, _ = info['transform']['box']
    bx, by = 400 - x0, OUR[3] + 30 - y0
    assert out[by:by + 30, bx:bx + 110].min() < 100            # подпись «(1,37)» в кадре
    assert info['labels_sel'] >= 5                              # подписи квартиры и балкона посчитаны до
    assert info['labels_out'] >= info['labels_sel'] - max(1, round(0.03 * info['labels_sel']))


# ───────────────── дефект krasnodar: метка на стене не оставляет выемки ─────────────────

def test_color_mark_on_wall_is_painted_wall_colour_not_notch():
    img = sheet_field(dot=True)
    out, info = ac.cut_bgr(img)
    assert info['status'] == 'cut' and info['method'] == 'заливка снаружи', info
    assert info["notches_after"] == 0 and info["notches_after"] <= info["notches_before"] and info["marks_painted"] >= 1
    x0, y0, _, _ = info['transform']['box']
    dx, dy = 890 - x0, 380 - y0
    patch = out[dy - 6:dy + 7, dx - 6:dx + 7]    # центр метки
    assert patch.mean() < 120, patch.mean()                      # на месте метки — стена, не белая выемка
    # то же без метки: выемок нет и до
    out0, info0 = ac.cut_bgr(sheet_field(dot=False))
    assert info0['status'] == 'cut' and info0['notches_before'] == 0 == info0['notches_after']


# ───────────────── ложные срабатывания ─────────────────

def test_wall_ring_is_not_fill():
    out, info = ac.cut_bgr(sheet_wall_ring())
    assert info['status'] == 'mark' and out is not None


@pytest.mark.parametrize('maker', [sheet_plain, lambda: np.full((H, W, 3), 255, np.uint8)])
def test_no_highlight_is_mark_and_sheet_untouched(maker):
    img = maker()
    out, info = ac.cut_bgr(img)
    assert info['status'] == 'mark' and out is img


# ───────────────── флаг, сбой, prepare() ─────────────────

def test_flag_off_by_default(monkeypatch):
    from PIL import Image
    monkeypatch.delenv('FP_CUT_APT', raising=False)
    sheet = Image.fromarray(cv2.cvtColor(sheet_red(), cv2.COLOR_BGR2RGB))
    out, info = ac.cut_sheet(sheet)
    assert out is sheet and info['status'] == 'off'


def test_cut_sheet_failure_returns_sheet(monkeypatch):
    from PIL import Image
    monkeypatch.setenv('FP_CUT_APT', '1')
    monkeypatch.setattr(ac, 'cut_bgr', lambda b: (_ for _ in ()).throw(RuntimeError('boom')))
    sheet = Image.fromarray(np.full((200, 300, 3), 200, np.uint8))
    out, info = ac.cut_sheet(sheet)
    assert out is sheet and info['status'] == 'error'


def test_prepare_flag_gated_and_writes_input_transform(tmp_path, monkeypatch):
    import pipeline as pl
    from PIL import Image
    src = tmp_path / 'in.png'
    cv2.imwrite(str(src), sheet_red())
    monkeypatch.delenv('FP_CUT_APT', raising=False)
    monkeypatch.delenv('FP_CLEAN_BG', raising=False)
    monkeypatch.delenv('FP_CLEAN_RECT', raising=False)
    off, source_off, _ = pl.prepare(src, 'image/png', tmp_path / 'off')
    assert np.array_equal(np.asarray(Image.open(off).convert('RGB')), np.asarray(Image.open(src).convert('RGB')))
    assert 'inputTransform' not in source_off
    monkeypatch.setenv('FP_CUT_APT', '1')
    on, source_on, _ = pl.prepare(src, 'image/png', tmp_path / 'on')
    a = np.asarray(Image.open(on).convert('RGB'))
    assert a.shape[1] < W * 0.8
    steps = source_on['inputTransform']
    assert steps[-1]['op'] == 'crop' and steps[-1]['scale'] == 1.0 and steps[-1]['src'] == [W, H]
    assert source_on['imageW'] == a.shape[1] and source_on['imageH'] == a.shape[0]
