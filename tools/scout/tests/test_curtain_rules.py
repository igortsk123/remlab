"""Правила штор спальни (T-20261120-163, владелец TG 50/52): у лофта по воротам слота штор нет (все годные по стилю — рулонные, а они под `deny`) —
значит `decor.шторы.neighbour_spare` включён у ВСЕХ назначений (общее правило, не заплатка под один стиль), ворота слота не ослаблены.
    ~/venvs/scout/bin/python -m pytest -q -p no:cacheprovider tools/scout/tests/test_curtain_rules.py"""
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
RULES = os.path.join(HERE, '..', 'rules', 'bedroom-composition.json')


def _rules_curtains():
    doc = json.load(open(RULES, encoding='utf-8'))
    got = {n: (p.get('decor') or {}).get('шторы') for n, p in doc['purposes'].items()}
    return {n: dc for n, dc in got.items() if dc}


def test_every_purpose_with_curtains_has_neighbour_spare():
    got = _rules_curtains()
    assert len(got) >= 4                                   # couple, single, guest, single_narrow
    for name, dc in got.items():
        assert dc.get('neighbour_spare') is True, name


def test_curtain_gates_not_relaxed_by_the_spare():
    for name, dc in _rules_curtains().items():
        assert dc['qty_from'] == 'windows' and dc['min_w'] == 'window', name              # полотно не уже окна — как было
        deny = re.compile(dc['deny'], re.I)
        for bad in ('Рулонная штора серая', 'Римская штора', 'Штора кафе', 'Штора для кухни'):
            assert deny.search(bad), (name, bad)                                          # рулонные/римские/кухонные — по-прежнему нет
        assert not deny.search('Комплект штор Togas Плассе графит'), name


def test_loft_allows_roller_blinds_but_not_roman_cafe_kitchen():
    """Владелец TG 69: рулонные в лофте по стилю можно — исключение данными на стиль, у остальных стилей общий deny."""
    for name, dc in _rules_curtains().items():
        assert set(dc['deny_by_style']) == {'лофт'}, name
        loft = re.compile(dc['deny_by_style']['лофт'], re.I)
        assert not loft.search('Рулонная штора FixLine графит'), name
        for bad in ('Римская штора', 'Штора кафе', 'Штора для кухни'):
            assert loft.search(bad), (name, bad)


# ---- сборщик спальни: шторы по окну, тон лофта (T-20261120-163)
import copy  # noqa: E402
import sys  # noqa: E402
from types import SimpleNamespace as NS  # noqa: E402

sys.path.insert(0, os.path.join(HERE, '..'))
sys.path.insert(0, HERE)
import compose_bedroom as CB  # noqa: E402

ALL = {x: 1.0 for x in ('сканди', 'современный', 'минимализм', 'лофт', 'джапанди', 'неоклассика')}
DARK, LIGHT = {'cls': 'neutral_grey', 'cls2': 'neutral_grey', 'rgb': [60, 60, 60]}, {'cls': 'neutral_light', 'cls2': 'neutral_light', 'rgb': [235, 235, 230]}


def _c(eid, name, style, w, tone=LIGHT):
    return dict({'mid': 7, 'eid': str(eid), 'sid': f'7:{eid}', 'role': 'шторы', 'name': name, 'w': float(w), 'd': None, 'h': 270.0, 'price': 5000,
                 'mesh': None, 'styles': dict(ALL, **{style: 9.0}), 'fam': str(eid)}, **tone)


def _win(*widths):
    return type('R', (), {'openings': [NS(kind='window', width_cm=float(w), wall='north', offset_cm=10.0) for w in widths]})()


def _curtains(decor, style, *widths):
    R = copy.deepcopy(CB.rules())
    R['purposes']['couple']['decor'] = {'шторы': R['purposes']['couple']['decor']['шторы']}
    comp = CB.Composer([], decor, set(), set(), R, CB.tolerance(), 6.6)
    picks, alts, gaps, lay, slots, _rx = comp.decor_pick('couple', style, 'комфорт', {}, type('L', (), {'placements': []})(), _win(*widths), {})
    return picks, gaps, lay


def test_loft_narrow_window_gets_roller_wide_window_gets_neighbour_panel():
    d = [_c(1, 'Рулонная штора Лофт графит', 'лофт', 100, DARK), _c(2, 'Комплект штор Джапанди', 'джапанди', 260)]
    picks, gaps, lay = _curtains(d, 'лофт', 90, 240)
    assert picks['шторы 2']['eid'] == '1' and picks['шторы 2']['qty'] == 1                      # рулонная — узкому окну
    assert picks['шторы']['eid'] == '2' and picks['шторы']['qty'] == 1 and picks['шторы']['style_from'] == 'джапанди'   # широкому — шторы соседа
    assert [w['width_cm'] for w in lay['шторы 2']['windows']] == [90.0] and [w['width_cm'] for w in lay['шторы']['windows']] == [240.0]


def test_loft_all_windows_narrow_roller_covers_all():
    picks, gaps, lay = _curtains([_c(1, 'Рулонная штора Лофт', 'лофт', 100)], 'лофт', 90, 80)
    assert picks['шторы']['eid'] == '1' and picks['шторы']['qty'] == 2 and 'шторы 2' not in picks
    assert len(lay['шторы']['windows']) == 2


def test_loft_roller_too_narrow_for_every_window_old_path():
    """Окно 240, рулонная 100 — не годна: как раньше, только шторы соседа (рулонка 80 см на окно 2,4 м — нет)."""
    picks, gaps, lay = _curtains([_c(1, 'Рулонная штора Лофт', 'лофт', 100), _c(2, 'Комплект штор Джапанди', 'джапанди', 260)], 'лофт', 240)
    assert picks['шторы']['eid'] == '2' and 'шторы 2' not in picks


def test_other_style_rollers_still_denied():
    picks, gaps, lay = _curtains([_c(1, 'Рулонная штора Сканди', 'сканди', 100)], 'сканди', 90)
    assert 'шторы' not in picks and 'шторы 2' not in picks


def test_roman_and_kitchen_denied_even_in_loft():
    d = [_c(1, 'Римская штора Лофт', 'лофт', 100), _c(2, 'Штора для кухни Лофт', 'лофт', 100)]
    picks, gaps, lay = _curtains(d, 'лофт', 90)
    assert 'шторы' not in picks and 'шторы 2' not in picks


def test_loft_prefers_dark_neighbour_curtains_over_light():
    d = [_c(1, 'Комплект штор Бежевый', 'джапанди', 260, LIGHT), _c(2, 'Комплект штор Графит', 'современный', 260, DARK)]
    picks, gaps, lay = _curtains(d, 'лофт', 240)
    assert picks['шторы']['eid'] == '2' and picks['шторы']['style_from'] == 'современный'     # соседи — в одном пуле: тёмная у второго соседа не теряется


def test_loft_takes_light_when_no_dark():
    picks, gaps, lay = _curtains([_c(1, 'Комплект штор Бежевый', 'джапанди', 260, LIGHT)], 'лофт', 240)
    assert picks['шторы']['eid'] == '1'
