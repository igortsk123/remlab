"""Правила ламп спальни (T-20261117-13, владелец TG 1382, шаг 2 bedroom-life-01): нижняя граница полосы высоты — данными (`band_min`),
запас у соседнего стиля — когда своих ламп (с моделью, влезающих) нет; лампа соседа помечена `style_from`, своя — нет.
Без сети и моделей: товары синтетические, проверка модели подменена.
    ~/venvs/scout/bin/python -m pytest -q -p no:cacheprovider tools/scout/tests/test_lamp_rules.py"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
sys.path.insert(0, HERE)
import compose_common as CC  # noqa: E402
import dependent_decor as DD  # noqa: E402

RULES = os.path.join(HERE, '..', 'rules', 'bedroom-composition.json')
DRESSER = {'role': 'комод', 'x': 60.0, 'y': 120.0, 'rot': 90, 'w': 120.0, 'd': 45.0, 'h': 80.0, 'sku': {'name': 'Комод Берг'}}
SOFA = {'role': 'диван', 'x': 250.0, 'y': 300.0, 'rot': 180, 'w': 200.0, 'd': 90.0, 'h': 80.0, 'sku': {'name': 'Диван'}}
ROOM = (500, 400)
TOL = (0.8, 1.1)


def lamp(eid, h=40, name='Лампа настольная'):
    return {'mid': 9, 'eid': str(eid), 'name': f'{name} {eid}', 'w': 25, 'd': 25, 'h': h, 'price': 4000}


def sets_for(style: str, *lamps):
    return {'style': style, 'items': {('лампа' if k == 0 else f'лампа {k + 1}'): it for k, it in enumerate(lamps)}}


def any_model(it):
    return True, None


def nb_scandi(style):
    return {'джапанди': ['сканди', 'минимализм'], 'лофт': ['джапанди', 'современный']}.get(style, [])


def test_band_min_lowers_floor_only_and_is_optional():
    slot = {'ideal': {'h': 45}, 'band': ['h']}
    assert CC.band_of(slot, TOL) == {'h': [36.0, 49.5]}                              # без band_min — как было
    assert CC.band_of(dict(slot, band_min={'h': 33}), TOL) == {'h': [33.0, 49.5]}    # нижняя граница ниже, верх не тронут
    assert CC.band_of(dict(slot, band_min={'h': 40}), TOL) == {'h': [36.0, 49.5]}    # выше расчётной не поднимает
    assert CC.band_of(dict(slot, band_min={'w': 10}), TOL) == {'h': [36.0, 49.5]}    # чужая сторона — игнор


def test_rules_file_has_lamp_band_from_33_and_neighbour_spare_everywhere():
    doc = json.load(open(RULES, encoding='utf-8'))
    n = 0
    for name, purpose in doc['purposes'].items():
        dc = (purpose.get('decor') or {}).get('лампа')
        if not dc:
            continue
        n += 1
        assert dc['band_min'] == {'h': 33}, name
        assert dc['neighbour_spare'] is True, name
        assert CC.band_of(dict(dc, role='лампа'), TOL)['h'] == [33.0, 49.5], name
    assert n >= 1


def test_own_lamp_wins_no_style_from():
    sets = [sets_for('джапанди', lamp(1)), sets_for('сканди', lamp(2))]
    it, pls, why = DD.lamp_pick_all(sets, 0, [SOFA, DRESSER], ROOM, any_model, neighbours=nb_scandi)
    assert it['eid'] == '1' and 'style_from' not in it and pls


def test_no_own_lamp_takes_neighbour_marked_style_from():
    sets = [sets_for('джапанди'), sets_for('сканди', lamp(2))]
    it, pls, why = DD.lamp_pick_all(sets, 0, [SOFA, DRESSER], ROOM, any_model, neighbours=nb_scandi)
    assert it and it['eid'] == '2' and it['style_from'] == 'сканди' and pls
    # без запаса (neighbours не передан) — как раньше: лампы нет
    none, no_pls, _ = DD.lamp_pick_all(sets, 0, [SOFA, DRESSER], ROOM, any_model)
    assert none is None and no_pls is None


def test_own_lamp_without_model_falls_to_neighbour_in_order():
    sets = [sets_for('лофт', lamp(1)), sets_for('джапанди', lamp(2)), sets_for('современный', lamp(3))]

    def model(it):
        return (None, 'нет модели на сервере') if it['eid'] == '1' else (True, None)
    it, pls, why = DD.lamp_pick_all(sets, 0, [SOFA, DRESSER], ROOM, model, neighbours=nb_scandi)
    assert it['eid'] == '2' and it['style_from'] == 'джапанди'                       # порядок соседей — данными: джапанди раньше современного
    assert any('нет модели на сервере' in w for w in why)


def test_lamp_already_borrowed_in_neighbour_keeps_real_origin():
    """Лампа лофта из набора джапанди, которая сама взята у сканди, остаётся «из сканди» — цепочка не прячет настоящий стиль."""
    sets = [sets_for('лофт'), sets_for('джапанди', dict(lamp(2), style_from='сканди'))]
    it, pls, why = DD.lamp_pick_all(sets, 0, [SOFA, DRESSER], ROOM, any_model, neighbours=nb_scandi)
    assert it['eid'] == '2' and it['style_from'] == 'сканди'


def test_neighbour_without_model_too_means_no_lamp_and_honest_journal():
    sets = [sets_for('лофт', lamp(1)), sets_for('джапанди', lamp(2))]
    it, pls, why = DD.lamp_pick_all(sets, 0, [SOFA, DRESSER], ROOM, lambda i: (None, 'нет модели на сервере'), neighbours=nb_scandi)
    assert it is None and pls is None and len([w for w in why if 'нет модели' in w]) == 2


def test_neighbour_style_from_survives_in_sku():
    """`flat215_demo._sku` кладёт `style_from` в товар строки декора (причина видна в данных набора)."""
    import flat215_demo as FD
    sk = FD._sku({'лампа': dict(lamp(2), style_from='сканди')}, 'лампа')
    assert sk['style_from'] == 'сканди'
    assert 'style_from' not in FD._sku({'лампа': lamp(2)}, 'лампа')
