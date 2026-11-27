"""Четверть оборота листа по OCR (T-171/vhod, Fable otvet-36, круг 6): модуль `quarter_turn` + шаг `quarter` в input_step (FP_CLEAN_QUARTER, по умолчанию ВЫКЛ).

Без OCR и сети (идёт в CI): оценщик — подмена (`scorer(k, img)`). Лист-метка: картинка со стрелкой «вверх» — по ней видно, в какую сторону повернули.
  • выбор поворота: уверенный текст виден при k → выбран k; исходный читается не хуже / текста мало / ничья → 0 (лист не трогаем);
  • поворот k и матрица `H` согласованы: точка исходного листа → H → точка повёрнутого лист-метки; обратно — `source_point` ≤ 1 px;
  • шаг: флаг выкл (по умолчанию) — тот же объект, ops == []; FP_INPUT_ALL=1 шаг quarter НЕ включает; флаг без оценщика — ничего не делает;
  • сломал — покраснело: перепутать стороны (k=1 ↔ k=3) → тест «стрелка вверх после шага» красный (−контроль в тесте)."""
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools' / 'floorplan'))
import apartment_cut as ac  # noqa: E402
import input_step as ins  # noqa: E402
import quarter_turn as Q  # noqa: E402

FLAGS = ('FP_INPUT_ALL', 'FP_CLEAN_BG', 'FP_CLEAN_RECT', 'FP_CLEAN_GRID', 'FP_CLEAN_LINES', 'FP_CLEAN_LAYERS', 'FP_CLEAN_DESKEW', 'FP_CLEAN_QUARTER', 'FP_CUT_APT')


def _clear(monkeypatch):
    for k in FLAGS:
        monkeypatch.delenv(k, raising=False)


def _pil(img):
    from PIL import Image
    return Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))


def marked():
    """лист 300×200 (ш×в): красный квадрат у верхнего левого угла и чёрный — у нижнего правого; «верх» — сторона с красным"""
    img = np.full((200, 300, 3), 255, np.uint8)
    cv2.rectangle(img, (10, 10), (40, 40), (0, 0, 255), -1)
    cv2.rectangle(img, (260, 160), (290, 190), (0, 0, 0), -1)
    return img


def scorer_for(truth_k):
    """оценщик-подмена: текст «читается» (большая оценка) ровно на повороте truth_k"""
    return lambda k, img: 500.0 if k == truth_k else 20.0


def test_choose_picks_the_readable_turn():
    for k in (1, 2, 3):
        got, info = Q.choose({0: 20.0, 1: 20.0, 2: 20.0, 3: 20.0, k: 400.0})
        assert got == k and info['k'] == k
    got, info = Q.choose({0: 400.0, 1: 380.0, 2: 20.0, 3: 20.0})
    assert got == 0 and 'не хуже' in info['reason']                      # исходный читается не хуже — не трогаем
    got, info = Q.choose({0: 5.0, 1: 30.0, 2: 10.0, 3: 5.0})
    assert got == 0 and 'текста мало' in info['reason']                  # текста нет — решать нечем
    got, info = Q.choose({0: 100.0, 1: 150.0, 2: 90.0, 3: 120.0})
    assert got == 0                                                       # ничья/неясность — не трогаем


def test_chars_score_counts_only_confident_text():
    items = [('Кухня', 0.95, None), ('12', 0.99, None), ('Ванная', 0.30, None), ('Комната 14,2', 0.9, None)]
    assert Q.chars_score(items) == pytest.approx(5 * 0.95 + 12 * 0.9)     # короткие и неуверенные строки не в счёт


@pytest.mark.parametrize('k', [1, 2, 3])
def test_rotate_and_matrix_agree(k):
    img = marked()
    out = Q.rotate_k(img, k)
    H = Q.matrix(k, img.shape[1], img.shape[0])
    for (x, y) in ((25, 25), (275, 175)):                                 # центры красного и чёрного квадратов
        q = H @ np.array([x, y, 1.0])
        qx, qy = int(round(q[0])), int(round(q[1]))
        assert tuple(out[qy, qx]) == tuple(img[y, x]), (k, (x, y), (qx, qy))
        bx, by = ac.source_point([{'op': 'quarter', 'H': H.tolist()}], q[0], q[1])
        assert abs(bx - x) < 1 and abs(by - y) < 1


@pytest.mark.parametrize('k', [1, 2, 3])
def test_step_turns_sheet_and_writes_step(monkeypatch, k):
    _clear(monkeypatch)
    img = marked()
    r = ins.run(_pil(img), {'quarter': True}, scorer=scorer_for(k))
    assert r['ops'] == ['quarter'] and r['quarter_k'] == k and [s['op'] for s in r['steps']] == ['quarter']
    out = cv2.cvtColor(np.asarray(r['sheet']), cv2.COLOR_RGB2BGR)
    assert out.shape == Q.rotate_k(img, k).shape and np.array_equal(out, Q.rotate_k(img, k))


def test_step_off_by_default_and_not_in_all(monkeypatch):
    _clear(monkeypatch)
    assert ins.flags_from_env()['quarter'] is False
    monkeypatch.setenv('FP_INPUT_ALL', '1')
    assert ins.flags_from_env()['quarter'] is False and ins.flags_from_env()['deskew'] is True      # «все шаги» OCR не запускают
    monkeypatch.delenv('FP_INPUT_ALL')
    monkeypatch.setenv('FP_CLEAN_QUARTER', '1')
    assert ins.flags_from_env()['quarter'] is True
    sheet = _pil(marked())
    r = ins.run(sheet, {'quarter': True}, scorer=None)                    # флаг без оценщика — ничего не делает
    assert r['sheet'] is sheet and r['ops'] == [] and r['steps'] == [] and r['quarter_k'] is None
    r = ins.run(sheet, {}, scorer=scorer_for(1))                          # оценщик без флага — тоже
    assert r['sheet'] is sheet and r['ops'] == []


def test_step_failure_leaves_sheet_as_is(monkeypatch):
    _clear(monkeypatch)
    sheet = _pil(marked())

    def boom(k, img):
        raise RuntimeError('нет OCR')
    r = ins.run(sheet, {'quarter': True}, scorer=boom)
    assert r['sheet'] is sheet and r['ops'] == []


def test_control_swapped_sides_turns_wrong_way(monkeypatch):
    """сломал — покраснело: перепутать стороны (k=1 ↔ k=3) → после шага красный квадрат не там, где у настоящего поворота (проверка выше «np.array_equal» красная)"""
    _clear(monkeypatch)
    img = marked()
    real = Q.rotate_k
    monkeypatch.setattr(Q, 'rotate_k', lambda b, k: real(b, {1: 3, 3: 1}.get(k, k)))
    r = ins.run(_pil(img), {'quarter': True}, scorer=scorer_for(1))
    out = cv2.cvtColor(np.asarray(r['sheet']), cv2.COLOR_RGB2BGR)
    assert not np.array_equal(out, real(img, 1))
