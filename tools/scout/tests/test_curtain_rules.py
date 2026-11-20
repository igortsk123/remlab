"""Правила штор спальни (T-20261120-163, владелец TG 50/52): у лофта по воротам слота штор нет (все годные по стилю — рулонные, а они под `deny`) —
значит `decor.шторы.neighbour_spare` включён у ВСЕХ назначений (общее правило, не заплатка под один стиль), ворота слота не ослаблены.
    ~/venvs/scout/bin/python -m pytest -q -p no:cacheprovider tools/scout/tests/test_curtain_rules.py"""
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
RULES = os.path.join(HERE, '..', 'rules', 'bedroom-composition.json')


def _curtains():
    doc = json.load(open(RULES, encoding='utf-8'))
    got = {n: (p.get('decor') or {}).get('шторы') for n, p in doc['purposes'].items()}
    return {n: dc for n, dc in got.items() if dc}


def test_every_purpose_with_curtains_has_neighbour_spare():
    got = _curtains()
    assert len(got) >= 4                                   # couple, single, guest, single_narrow
    for name, dc in got.items():
        assert dc.get('neighbour_spare') is True, name


def test_curtain_gates_not_relaxed_by_the_spare():
    for name, dc in _curtains().items():
        assert dc['qty_from'] == 'windows' and dc['min_w'] == 'window', name              # полотно не уже окна — как было
        deny = re.compile(dc['deny'], re.I)
        for bad in ('Рулонная штора серая', 'Римская штора', 'Штора кафе', 'Штора для кухни'):
            assert deny.search(bad), (name, bad)                                          # рулонные/римские/кухонные — по-прежнему нет
        assert not deny.search('Комплект штор Togas Плассе графит'), name


def test_loft_allows_roller_blinds_but_not_roman_cafe_kitchen():
    """Владелец TG 69: рулонные в лофте по стилю можно — исключение данными на стиль, у остальных стилей общий deny."""
    for name, dc in _curtains().items():
        assert set(dc['deny_by_style']) == {'лофт'}, name
        loft = re.compile(dc['deny_by_style']['лофт'], re.I)
        assert not loft.search('Рулонная штора FixLine графит'), name
        for bad in ('Римская штора', 'Штора кафе', 'Штора для кухни'):
            assert loft.search(bad), (name, bad)
