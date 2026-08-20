"""Сторож дублей чисел в правилах (19.08, разбор Codex): одно число — один источник истины.

Дубль всегда расходится: заход ковра жил как 15 в templates.geometry и 25 в occupancy.rug_rules,
порог радиатора — в distances_cm и в dynamic.radiator. Тест держит зеркала синхронными.
"""
import json
import os

ROOT = os.path.join(os.path.dirname(__file__), '..')


def _load(name):
    with open(os.path.join(ROOT, 'rules', name), encoding='utf-8') as f:
        return json.load(f)


def test_radiator_threshold_single_value():
    occ = _load('occupancy.json')
    a = occ['distances_cm']['sofa_to_radiator_wall']
    b = occ['dynamic']['radiator']['hard_min_clearance_cm']
    assert list(a) == list(b), f'порог радиатора разошёлся: {a} vs {b} (источник истины — dynamic.radiator)'


def test_rug_tuck_single_value():
    occ, tpl = _load('occupancy.json'), _load('templates.json')
    a = occ['dynamic']['rug_rules']['front_legs_on_rug_cm']
    b = tpl['geometry']['rug_tuck_cm']['v']
    assert float(a) == float(b), f'заход ковра разошёлся: occupancy {a} vs templates {b}'


def test_lamp_gap_from_rules():
    from planner.template import LAMP_GAP
    occ = _load('occupancy.json')
    lo = occ['dynamic']['extras']['floor_lamp']['from_armrest_cm'][0]
    assert LAMP_GAP == float(lo), f'зазор торшера в коде {LAMP_GAP} вне правила {lo}'
