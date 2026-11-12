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


def test_schemes_levels_small_room_has_c_and_keeps_core():
    room = {'area': 14.3}
    lv = ls.levels_for(room, 'C1')
    assert [k for k, _v, _d in lv] == ['A', 'B', 'C', 'D']
    by = {k: v for k, v, _d in lv}
    assert by['A']['arm'] == 1 and by['A']['dining'] == 2
    assert by['B']['dining'] == 0 and by['B']['arm'] == 1          # B меняет только столовую
    assert by['C']['arm'] == 0 and not by['C']['vase'] and not by['C']['plant']
    assert by['D']['light'] == 'floor'


def test_schemes_levels_big_room_no_silent_drop():
    """≥ 16 м²: уровня C (без кресла) нет — тихий дроп запрещён (Codex §2 «Деградация»)."""
    lv = ls.levels_for({'area': 33.0}, 'L1')
    assert [k for k, _v, _d in lv] == ['A', 'B', 'D']
    assert all(v['arm'] == 2 for _k, v, _d in lv)
    assert lv[0][1]['dining'] == 4 and lv[1][1]['dining'] == 2
