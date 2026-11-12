"""T-20261111-12: площадь, напечатанная на листе у комнаты, — истина для показа; контур не подгоняется, а сверяется.

`pipeline.area_shown` (показ подписи, `areaContourM2` — сверка), `pipeline.scale_by_labels` (масштаб по медиане подписанных
комнат), `room_edits._scaled` (правка агента — показанная площадь и площадь контура тянутся тем же sx·sy, сверка с подписью
остаётся; T-20261112-28), `trial_bundle._approx` (расхождение — «форма приблизительная»).
Лёгкие: без сети, без стенда."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools' / 'floorplan'))
sys.path.append(str(ROOT / 'tools' / 'scout'))          # в конец: у scout свой pipeline.py
import pipeline as pl  # noqa: E402
import room_edits as RE  # noqa: E402

# подписи листа «Этажи» (labels4, gold.json прогона a1-211259) и площади контуров того же прогона
ETAGI = {'Kitchen-living room': (20.8, 20.26), 'Bedroom 1': (14.9, 14.9), 'Bedroom 2': (12.8, 12.87), 'Bathroom 1': (5.1, 4.84),
         'Hall': (4.3, 4.28), 'Corridor': (3.8, 4.2), 'Bathroom 2': (4.0, 4.1), 'Dressing room': (2.3, 2.23)}


@pytest.mark.parametrize('name', list(ETAGI))
def test_etagi_label_shown_contour_kept(name):
    want, got = ETAGI[name]
    G_by = {n: {'area_m2': a} for n, (a, _) in ETAGI.items()}
    area, fl = pl.area_shown([name], G_by, got)
    assert area == want and fl == ['area_label_ok', 'area_from_label']


def test_label_off_shown_with_flag_not_fitted():
    G_by = {'A': {'area_m2': 10.0}}
    area, fl = pl.area_shown(['A'], G_by, 7.0)                       # −30 %: подпись показана, контур под вопросом
    assert area == 10.0 and fl == ['area_label_off', 'area_from_label']


@pytest.mark.parametrize('g, got', [
    ({'area_m2': 150.0}, 14.0),                    # футы, прочитанные как м², — дальше вдвое: не про эту комнату
    ({'area_m2': 5.0}, 1.9),
    ({'area_m2': 5.0, 'unsure': True}, 4.8),       # неуверенно прочитанная подпись — не истина
])
def test_label_not_trusted_contour_shown(g, got):
    area, fl = pl.area_shown(['A'], {'A': g}, got)
    assert area == got and 'area_from_label' not in fl and fl[0].startswith('area_label_')


def test_merged_sum_and_missing_label():
    G_by = {'A': {'area_m2': 5.1}, 'B': {'area_m2': 4.0}, 'C': {}}
    assert pl.area_shown(['A', 'B'], G_by, 8.6) == (9.1, ['area_label_ok', 'area_from_label'])
    assert pl.area_shown(['A', 'C'], G_by, 8.6) == (8.6, [])           # у одной из слитых подписи нет — по контуру
    assert pl.area_shown([], G_by, 3.0) == (3.0, [])


def _panel(pairs):
    return [{'rooms': [{'areaM2': a, 'areaContourM2': c, 'flags': ['area_label_ok', 'area_from_label']} for a, c in pairs]
             + [{'areaM2': 9.0, 'flags': []}]}]


def test_scale_by_labels():
    assert pl.scale_by_labels(_panel([(a, c) for a, c in ETAGI.values()])) == ['scale_labels_ok']
    # масштаб на 10 % крупнее: все контуры в 1,21 раза больше подписей (один контур «свой» медиану не сдвигает)
    k = [(a, a * 1.21) for a, _ in ETAGI.values()][:-1] + [(2.3, 1.0)]
    assert pl.scale_by_labels(_panel(k)) == ['scale_labels_off']
    assert pl.scale_by_labels(_panel([(5.0, 4.9), (4.0, 4.0)])) == []    # меньше 3 подписанных — молчим


def test_panel_result_shows_label_and_keeps_contour():
    sq = lambda s: [[0, 0], [s, 0], [s, s], [0, s]]                                       # noqa: E731
    model = {'rooms': [{'id': 1, 'names': ['Corridor'], 'area_m2': 4.2}, {'id': 2, 'names': ['Hall'], 'area_m2': 4.28}],
             'floors': [{'room': 1, 'outer': sq(2.05)}, {'room': 2, 'outer': sq(2.07)}], 'bands': [], 'openings': []}
    G_by = {'Corridor': {'name': 'Corridor', 'name0': 'Corridor', 'area_m2': 3.8}, 'Hall': {'name': 'Hall', 'name0': 'Hall'}}
    rooms = {r['name']: r for r in pl.panel_result(0, {}, model, G_by, True)['rooms']}
    assert rooms['Corridor']['areaM2'] == 3.8 and rooms['Corridor']['areaContourM2'] == 4.2
    assert 'area_from_label' in rooms['Corridor']['flags']
    assert rooms['Hall']['areaM2'] == 4.28 and 'areaContourM2' not in rooms['Hall']    # подписи площади нет — как до T-12


@pytest.mark.parametrize('check', ['area_label_ok', 'area_label_off'])
def test_agent_edit_scales_shown_and_contour_area_together(check):
    """T-20261112-28: правка размера тянет ПОКАЗАННУЮ площадь (подпись листа) тем же sx·sy, что окошко правки (`tcfArea`), площадь
    контура — тем же масштабом, контур — от центра охвата; флаги сверки с подписью (`area_from_label`, ok/off) остаются, добавляется
    `user_dims`; исходные контур и охват — в `plan`. Прежний контракт T-20261111-12 (площадь от контура, подпись снимается) отменён:
    у «Спальни 1» 14,9 (контур 11,29) окошко обещало 16,2, а выходило 12,3."""
    contour = [[0, 0], [200, 0], [200, 200], [0, 200]]
    room = {'id': 'r', 'kind': 'hall', 'name': 'Corridor', 'areaM2': 3.8, 'areaContourM2': 4.0,
            'flags': [check, 'area_from_label'], 'bbox': {'x': 0, 'y': 0, 'w': 200, 'd': 200}, 'contour': [list(p) for p in contour]}
    RE._scaled(room, 300, 250)                                    # sx = 1,5, sy = 1,25
    assert room['areaM2'] == pytest.approx(3.8 * 1.5 * 1.25, abs=0.01)     # показанная (подпись) × sx·sy — как окошко правки,
    assert room['areaContourM2'] == pytest.approx(4.0 * 1.5 * 1.25, abs=0.01)   # не контур × sx·sy (это 7,5)
    assert abs(room['areaM2'] - 7.5) > 0.3
    assert room['contour'] == [[-50.0, -25.0], [250.0, -25.0], [250.0, 225.0], [-50.0, 225.0]]   # от центра охвата (100, 100)
    assert room['bbox'] == {'x': -50.0, 'y': -25.0, 'w': 300.0, 'd': 250.0}
    assert room['flags'][:2] == [check, 'area_from_label'] and 'user_dims' in room['flags']
    assert room['plan']['contour'] == contour and room['plan']['bbox'] == {'x': 0, 'y': 0, 'w': 200, 'd': 200}
    assert room['edited'] == {'w': 300, 'd': 250}


def test_agent_edit_without_label_scales_contour_area_only():
    """Подписи площади нет (`areaContourM2` не было) — показанная площадь (= контур) × sx·sy, новых полей и флагов сверки нет."""
    room = {'id': 'r', 'kind': 'hall', 'name': 'Hall', 'areaM2': 4.0, 'flags': [], 'bbox': {'x': 0, 'y': 0, 'w': 200, 'd': 200},
            'contour': [[0, 0], [200, 0], [200, 200], [0, 200]]}
    RE._scaled(room, 300, 200)
    assert room['areaM2'] == 6.0 and 'areaContourM2' not in room
    assert room['flags'] == ['user_dims']


def test_bundle_marks_label_off_room_approx():
    import trial_bundle as TB
    room = {'contour': [[0, 0], [300, 0], [300, 300], [0, 300]], 'flags': ['area_label_off', 'area_from_label']}
    assert TB._approx(room, {'w': 300, 'd': 300})
    assert not TB._approx(dict(room, flags=['area_label_ok', 'area_from_label']), {'w': 300, 'd': 300})
