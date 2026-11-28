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
    r = ins.run(sheet, {'quarter': True}, scorer=None)                    # флаг без оценщика — лист не меняется, но пропуск ВИДЕН (T-171/quarter-otkaz)
    assert r['sheet'] is sheet and r['ops'] == [] and r['quarter_k'] is None
    assert r['steps'] == [{'op': 'quarter', 'skip': 'нет оценщика'}]
    r = ins.run(sheet, {}, scorer=scorer_for(1))                          # оценщик без флага — тоже
    assert r['sheet'] is sheet and r['ops'] == []


def test_step_failure_leaves_sheet_as_is(monkeypatch):
    _clear(monkeypatch)
    sheet = _pil(marked())

    def boom(k, img):
        raise RuntimeError('нет OCR')
    r = ins.run(sheet, {'quarter': True}, scorer=boom)
    assert r['sheet'] is sheet and r['ops'] == [] and r['quarter_k'] is None
    assert len(r['steps']) == 1 and r['steps'][0]['op'] == 'quarter' and 'skip' not in r['steps'][0]
    assert r['steps'][0]['fail'] == 'RuntimeError: нет OCR'                 # сбой не молчит: класс исключения + сообщение


def test_control_swapped_sides_turns_wrong_way(monkeypatch):
    """сломал — покраснело: перепутать стороны (k=1 ↔ k=3) → после шага красный квадрат не там, где у настоящего поворота (проверка выше «np.array_equal» красная)"""
    _clear(monkeypatch)
    img = marked()
    real = Q.rotate_k
    monkeypatch.setattr(Q, 'rotate_k', lambda b, k: real(b, {1: 3, 3: 1}.get(k, k)))
    r = ins.run(_pil(img), {'quarter': True}, scorer=scorer_for(1))
    out = cv2.cvtColor(np.asarray(r['sheet']), cv2.COLOR_RGB2BGR)
    assert not np.array_equal(out, real(img, 1))


def test_failure_reason_short_and_one_line(monkeypatch):
    _clear(monkeypatch)

    def boom(k, img):
        raise ValueError('строка 1\n' + 'х' * 500)
    f = ins.run(_pil(marked()), {'quarter': True}, scorer=boom)['steps'][0]['fail']
    assert f.startswith('ValueError: строка 1 хх') and '\n' not in f and len(f) <= len('ValueError: ') + 120


def test_flag_off_nothing_new_byte_for_byte(monkeypatch):
    """флаг выкл — живое побайтно как раньше: тот же объект листа, ни skip, ни fail, оценщик даже не зовётся"""
    _clear(monkeypatch)
    sheet = _pil(marked())
    calls = []

    def scorer(k, img):
        calls.append(k)
        raise RuntimeError('не должен звониться')
    for fl in ({}, {'quarter': False}):
        for sc in (None, scorer):
            r = ins.run(sheet, fl, scorer=sc)
            assert r['sheet'] is sheet and r['ops'] == [] and r['steps'] == [] and r['quarter_k'] is None
    assert calls == []


def test_not_applied_is_not_a_failure(monkeypatch):
    """оценщик отработал, но поворот не нужен (исходный читается не хуже) — это штатный исход, не пропуск и не сбой: записи нет"""
    _clear(monkeypatch)
    sheet = _pil(marked())
    r = ins.run(sheet, {'quarter': True}, scorer=lambda k, img: 100.0)
    assert r['sheet'] is sheet and r['steps'] == [] and r['ops'] == []


def test_skip_and_fail_records_do_not_break_source_point(monkeypatch):
    """запись skip/fail — не геометрия: обратное преобразование точки проходит мимо неё (раньше KeyError 'H')"""
    for rec in ({'op': 'quarter', 'skip': 'нет оценщика'}, {'op': 'quarter', 'fail': 'RuntimeError: x'}):
        assert ac.source_point([rec], 12.5, 7.0) == (12.5, 7.0)
        H = Q.matrix(1, 300, 200)
        q = H @ np.array([25.0, 25.0, 1.0])
        bx, by = ac.source_point([{'op': 'quarter', 'H': H.tolist()}, rec], q[0], q[1])     # настоящий шаг + запись после него
        assert abs(bx - 25) < 1 and abs(by - 25) < 1


def test_quarter_report_counts_skips_and_fails_with_reasons(monkeypatch):
    _clear(monkeypatch)
    sheet = _pil(marked())

    def boom(k, img):
        raise RuntimeError('нет OCR')
    runs = [ins.run(sheet, {'quarter': True}, scorer=None)['steps'],
            ins.run(sheet, {'quarter': True}, scorer=None)['steps'],
            ins.run(sheet, {'quarter': True}, scorer=boom)['steps'],
            ins.run(sheet, {'quarter': True}, scorer=scorer_for(1))['steps'],      # применён — не в счёте отказов
            ins.run(sheet, {}, scorer=None)['steps']]                              # флаг выкл — тоже
    rep = ins.quarter_report(runs)
    assert rep['пропущено'] == 2 and rep['нет оценщика'] == 2 and rep['сбоев'] == 1
    assert rep['причины сбоев'] == {'RuntimeError: нет OCR': 1}
    assert ins.quarter_report([]) == {'пропущено': 0, 'нет оценщика': 0, 'сбоев': 0, 'причины сбоев': {}}
