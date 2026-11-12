"""Схемы гостиной (T-20261112-46): функции выбора шаблона, уровня и мелочей — без рисования, сети и БД."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
ls = pytest.importorskip('living_schemes')


@pytest.mark.parametrize('w, n', [(160, 2), (189, 2), (190, 3), (227, 3), (253, 3), (254, 4), (300, 4)])
def test_schemes_pillow_count_by_sofa_width(w, n):
    assert ls.pillow_count(w) == n


@pytest.mark.parametrize('area, aspect, kitchen, annex, first', [
    (14.3, 1.35, False, False, 'C1'),    # демо 439×325
    (15.0, 1.67, False, False, 'C2'),    # 300×500 — вытянутая
    (20.8, 1.30, True, False, 'O1'),     # кухня-гостиная — сперва диван-разделитель
    (30.25, 1.5, False, True, 'L1'),     # Г-образная — П в основном прямоугольнике
    (33.0, 1.32, False, False, 'L1'),
    (41.6, 1.54, False, False, 'L2'),
    (22.0, 1.2, False, False, 'M1'),
    (20.0, 1.6, False, False, 'C2'),
])
def test_schemes_choose_templates(area, aspect, kitchen, annex, first):
    order, why = ls.choose_templates(area, aspect, kitchen, annex)
    assert order[0] == first
    assert why


def test_schemes_kitchen_falls_back_to_walls():
    assert ls.choose_templates(20.8, 1.3, kitchen=True)[0] == ['O1', 'O2']


def test_schemes_levels_small_room_keeps_dining_drops_armchair():
    """< 16 м² (канон core/lr-checklist.md): кресла нет ни на каком уровне, стол на 2 держится до последнего:
    без вазы/кашпо → компактный стол → торшер вместо комода → и только потом без столовой."""
    lv = ls.levels_for({'area': 14.3}, 'C1')
    assert [k for k, _v, _d in lv] == ['A', 'B', 'C', 'D', 'E']
    by = {k: v for k, v, _d in lv}
    assert all(v['arm'] == 0 for v in by.values())
    assert by['A']['dining'] == 2 and set(by['A']['optional']) == {'vase', 'plant'}
    assert by['B']['dining'] == 2 and not by['B']['vase'] and not by['B']['plant']
    assert by['C']['compact'] and by['C']['dining'] == 2 and by['C']['light'] == 'dresser'
    assert by['D']['compact'] and by['D']['light'] == 'floor'
    assert by['E']['dining'] == 0


def test_schemes_levels_big_room_no_silent_drop():
    """≥ 16 м²: кресла на всех уровнях, стол по площади (33 м² → 4), дальше на 2 места меньше."""
    lv = ls.levels_for({'area': 33.0}, 'L1')
    assert [k for k, _v, _d in lv] == ['A', 'B', 'D']
    assert all(v['arm'] == 2 for _k, v, _d in lv)
    assert lv[0][1]['dining'] == 4 and lv[1][1]['dining'] == 2


@pytest.mark.parametrize('m2, n', [(14.3, 2), (20.8, 2), (21.9, 2), (22.0, 4), (33.0, 4), (39.9, 4), (40.0, 6), (41.6, 6)])
def test_schemes_dining_seats_by_room_area(m2, n):
    """Мест за столом — как в подборе комплекта (`slot_rules.seats_for_room`, zones.json `seats_by_room_m2`)."""
    assert ls.dining_seats(m2) == n


def test_schemes_smallest_prefers_style_and_min_side():
    sets = [{'set_id': 'a', 'style': 'лофт', 'band': '14-16', 'items': {'стол обеденный': {'name': 'x', 'w': 60, 'd': 60}}},
            {'set_id': 'b', 'style': 'лофт', 'band': '14-16', 'items': {'стол обеденный': {'name': 'y', 'w': 90, 'd': 90}}},
            {'set_id': 'c', 'style': 'сканди', 'band': '14-16', 'items': {'стол обеденный': {'name': 'z', 'w': 80, 'd': 80}}}]
    assert ls.smallest(sets, 'стол обеденный', 'лофт', 70)['name'] == 'y'      # 60×60 меньше нижней границы
    assert ls.smallest(sets, 'стол обеденный', 'сканди', 70)['name'] == 'z'
