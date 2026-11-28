"""Защита доворота и четверть ПОСЛЕ доворота (T-171/k6-zashchita, Fable otvet-48; круг 6). Оба флага свои, по умолчанию ВЫКЛ, FP_INPUT_ALL=1 их не включает.

Без OCR и сети (идёт в CI): оценщик четверти — подмена; лист — синтетика test_cleanup.plan.
  • защита доворота (`deskew_guard`): мелкий лист (длинная сторона < DESKEW_SIDE_MIN) и поворот, после которого чернил < 0,75 от исходных, — откат с записью
    {'op':'deskew','skip':…,'guard':…} в steps; здоровый лист — тот же результат, что без защиты (побайтно); флаг выкл — как прежде;
  • сломал — покраснело: без защиты лист с тонкими тёмными линиями поворот ПРОХОДИТ и теряет чернила (тест это показывает числом);
  • четверть после доворота (`quarter_after`): «наклон 18° + вверх ногами» → сначала доворот, потом 180°; старым порядком (флаг выкл) — лист не повёрнут (−контроль красный
    для нового порядка); второй проход — только если доворот сработал и первый проход не повернул; шаги в steps — в порядке применения, обратное преобразование ≤ 3 px."""
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
import test_deskew as TD  # noqa: E402

FLAGS = ('FP_INPUT_ALL', 'FP_CLEAN_BG', 'FP_CLEAN_RECT', 'FP_CLEAN_GRID', 'FP_CLEAN_LINES', 'FP_CLEAN_LAYERS', 'FP_CLEAN_DESKEW', 'FP_CLEAN_DESKEW_GUARD',
         'FP_CLEAN_QUARTER', 'FP_CLEAN_QUARTER_AFTER', 'FP_CUT_APT')


def _clear(monkeypatch):
    for k in FLAGS:
        monkeypatch.delenv(k, raising=False)


def _pil(img):
    from PIL import Image
    return Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))


def _bgr(pil):
    return cv2.cvtColor(np.asarray(pil), cv2.COLOR_RGB2BGR)


def tilt(img, deg):
    """повернуть лист на deg (+ = по часовой), холст расширен, поле белое"""
    h, w = img.shape[:2]
    M = cv2.getRotationMatrix2D((w / 2, h / 2), -deg, 1.0)
    c, s = abs(M[0, 0]), abs(M[0, 1])
    nW, nH = int(np.ceil(h * s + w * c)), int(np.ceil(h * c + w * s))
    M[0, 2] += nW / 2 - w / 2
    M[1, 2] += nH / 2 - h / 2
    return cv2.warpAffine(img, M, (nW, nH), flags=cv2.INTER_CUBIC, borderValue=(255, 255, 255))


def marked_plan():
    """прямой план + красная метка у верхнего левого угла плана («верх» листа — сторона с меткой)"""
    img = TC.plan(3, fill=False)
    cv2.rectangle(img, (170, 140), (230, 200), (0, 0, 255), -1)
    return img


def red_centroid(img):
    m = (img[:, :, 2] > 200) & (img[:, :, 1] < 80) & (img[:, :, 0] < 80)
    ys, xs = np.nonzero(m)
    assert len(xs) > 50, 'метка не найдена'
    return float(xs.mean()), float(ys.mean())


def make_scorer(calls=None):
    """«OCR»-подмена: читает, только когда линии листа ровные (|угол| < 5°) — как настоящий на наклонном листе не читает; читаемый — тот, где метка в верхнем левом углу"""
    def scorer(k, img):
        if calls is not None:
            calls.append(k)
        th, _ = cl.main_angle(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY))
        if th is None or abs(th) > 5.0:
            return 20.0
        cx, cy = red_centroid(img)
        h, w = img.shape[:2]
        return 500.0 if (cx < w / 2 and cy < h / 2) else 20.0
    return scorer


def thin_heavy_plan():
    """план с толстыми стенами + много тонких тёмных линий (штриховка): после поворота интерполяция размывает тонкие — чернил становится заметно меньше"""
    img = TC.plan(3, fill=False)
    for y in range(160, 760, 10):
        cv2.line(img, (200, y), (1000, y), (100, 100, 100), 1)
    for x in range(200, 1000, 10):
        cv2.line(img, (x, 160), (x, 740), (100, 100, 100), 1)
    return img


def ink(img, t=128):
    return int((cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) < t).sum())


# ---------------- защита доворота ----------------
def test_guard_flags_are_own_and_off(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv('FP_INPUT_ALL', '1')
    f = ins.flags_from_env()
    assert f['deskew'] and not f['deskew_guard'] and not f['quarter_after'] and not f['quarter']     # FP_INPUT_ALL=1 свои флаги НЕ включает
    _clear(monkeypatch)
    f = ins.flags_from_env()
    assert not f['deskew_guard'] and not f['quarter_after']
    monkeypatch.setenv('FP_CLEAN_DESKEW_GUARD', '1')
    monkeypatch.setenv('FP_CLEAN_QUARTER_AFTER', '1')
    f = ins.flags_from_env()
    assert f['deskew_guard'] and f['quarter_after']


def test_healthy_sheet_same_with_guard_on(monkeypatch):
    _clear(monkeypatch)
    img, _ = TD.rotated(10.0)
    a = ins.run(_pil(img), {'deskew': True})
    b = ins.run(_pil(img), {'deskew': True, 'deskew_guard': True})
    assert a['ops'] == b['ops'] == ['deskew']
    assert np.array_equal(np.asarray(a['sheet']), np.asarray(b['sheet']))                  # здоровый лист: побайтно тот же результат
    assert [s['op'] for s in b['steps']] == ['deskew'] and 'skip' not in b['steps'][0]


def test_small_sheet_is_not_turned_with_guard(monkeypatch):
    _clear(monkeypatch)
    img, _ = TD.rotated(10.0)
    monkeypatch.setattr(cl, 'DESKEW_SIDE_MIN', max(img.shape[:2]) + 1)                     # «мелкий» — по порогу (на живых листах порог 450 px; kazan-14337759 — 396)
    off = ins.run(_pil(img), {'deskew': True})
    assert off['ops'] == ['deskew']                                                       # −контроль: без защиты мелкий лист довернулся бы
    on = ins.run(_pil(img), {'deskew': True, 'deskew_guard': True})
    assert on['ops'] == [] and on['deskew_deg'] is None
    assert on['steps'] == [{'op': 'deskew', 'skip': on['steps'][0]['skip'], 'guard': 'size'}] and 'мелкий' in on['steps'][0]['skip']
    assert np.array_equal(np.asarray(on['sheet']), np.asarray(_pil(img)))                  # лист как был
    assert ac.source_point(on['steps'], 10, 20) == (10.0, 20.0)                            # запись без геометрии точку не двигает


def test_thin_lines_lose_ink_on_turn_and_guard_rolls_back(monkeypatch):
    _clear(monkeypatch)
    base = thin_heavy_plan()
    img = tilt(base, 8.0)
    off = ins.run(_pil(img), {'deskew': True})
    assert off['ops'] == ['deskew']                                                       # −контроль: без защиты поворот проходит…
    ratio = ink(_bgr(off['sheet'])) / max(ink(img), 1)
    assert ratio < cl.DESKEW_INK_KEEP, ratio                                               # …и лист теряет чернила (тонкие линии размыты) — «сломанный лист без отката»
    on = ins.run(_pil(img), {'deskew': True, 'deskew_guard': True})
    assert on['ops'] == [] and on['steps'][0]['guard'] == 'ink' and 'чернил' in on['steps'][0]['skip']
    assert np.array_equal(np.asarray(on['sheet']), np.asarray(_pil(img)))


def test_guard_off_is_byte_identical_to_before(monkeypatch):
    _clear(monkeypatch)
    img = tilt(thin_heavy_plan(), 8.0)
    a = ins.run(_pil(img), {'deskew': True})
    b = ins.run(_pil(img), {'deskew': True, 'deskew_guard': False})
    assert np.array_equal(np.asarray(a['sheet']), np.asarray(b['sheet'])) and a['steps'] == b['steps']


# ---------------- четверть после доворота ----------------
def upside_down_tilted(deg=18.0):
    base = marked_plan()
    return tilt(cv2.rotate(base, cv2.ROTATE_180), deg)


def test_old_order_does_not_turn_tilted_upside_down(monkeypatch):
    _clear(monkeypatch)
    img = upside_down_tilted()
    r = ins.run(_pil(img), {'deskew': True, 'quarter': True}, scorer=make_scorer())
    assert r['ops'] == ['deskew'] and r['quarter_k'] is None                               # старый порядок: четверть мерила наклонный лист → «читаемого» нет → не повернула
    cx, cy = red_centroid(_bgr(r['sheet']))
    h, w = _bgr(r['sheet']).shape[:2]
    assert cx > w / 2 and cy > h / 2                                                       # метка внизу справа: лист всё ещё вверх ногами


def test_quarter_after_turns_180_after_deskew(monkeypatch):
    _clear(monkeypatch)
    img = upside_down_tilted()
    r = ins.run(_pil(img), {'deskew': True, 'quarter': True, 'quarter_after': True}, scorer=make_scorer())
    assert r['ops'] == ['deskew', 'quarter'] and r['quarter_k'] == 2
    assert [s['op'] for s in r['steps']] == ['deskew', 'quarter']                          # порядок применения
    out = _bgr(r['sheet'])
    cx, cy = red_centroid(out)
    h, w = out.shape[:2]
    assert cx < w / 2 and cy < h / 2                                                       # метка вверху слева: лист читается прямо
    th, _ = cl.main_angle(cv2.cvtColor(out, cv2.COLOR_BGR2GRAY))
    assert th is not None and abs(th) < 1.0
    sx, sy = ac.source_point(r['steps'], cx, cy)                                           # обратно на исходный (наклонный, вверх ногами) лист: туда, где метка там
    ix, iy = red_centroid(img)
    assert abs(sx - ix) < 3 and abs(sy - iy) < 3, ((sx, sy), (ix, iy))


def test_second_pass_only_if_deskew_worked_and_first_did_not_turn(monkeypatch):
    _clear(monkeypatch)
    flags = {'deskew': True, 'quarter': True, 'quarter_after': True}
    straight = marked_plan()                                                               # прямой и ровный: доворота нет → второго прохода нет
    calls = []
    r = ins.run(_pil(straight), flags, scorer=make_scorer(calls))
    assert r['ops'] == [] and r['quarter_k'] is None and calls == [0, 1, 2, 3]
    calls = []
    r = ins.run(_pil(cv2.rotate(straight, cv2.ROTATE_180)), flags, scorer=make_scorer(calls))   # прямой, вверх ногами: первый проход повернул → второго нет
    assert r['ops'] == ['quarter'] and r['quarter_k'] == 2 and calls == [0, 1, 2, 3]
    calls = []
    r = ins.run(_pil(tilt(straight, 10.0)), flags, scorer=make_scorer(calls))               # наклонный, но «вверх головой»: доворот, второй проход читает исходный k=0 → не поворачивает
    assert r['ops'] == ['deskew'] and r['quarter_k'] is None and calls == [0, 1, 2, 3, 0, 1, 2, 3]
    calls = []
    r = ins.run(_pil(upside_down_tilted()), {'deskew': True, 'quarter_after': True}, scorer=make_scorer(calls))   # флага quarter нет → четверти нет вовсе
    assert r['ops'] == ['deskew'] and calls == []


def test_quarter_after_off_changes_nothing(monkeypatch):
    _clear(monkeypatch)
    img = upside_down_tilted()
    a = ins.run(_pil(img), {'deskew': True, 'quarter': True}, scorer=make_scorer())
    b = ins.run(_pil(img), {'deskew': True, 'quarter': True, 'quarter_after': False}, scorer=make_scorer())
    assert np.array_equal(np.asarray(a['sheet']), np.asarray(b['sheet'])) and a['steps'] == b['steps']
