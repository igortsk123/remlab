"""Лампа на комоде (T-20261112-101): место — решатель паспорта (`dependents.resolve`, `light.lamp` на `light.dresser`), строка декора —
одна и та же у /demo (`flat215_demo.lamp_decor`) и тура (`trial_demo.lamp_rows` → `trial_bundle._decor_item`); ряд ваз её не берёт.
Без сети и моделей: товары синтетические, проверка модели подменена.
    ~/venvs/scout/bin/python -m pytest -q -p no:cacheprovider tools/scout/tests/test_dependent_decor.py"""
import copy
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
sys.path.insert(0, HERE)
import dependent_decor as DD  # noqa: E402
from planner import dependents as DEP  # noqa: E402  (путь к решателю кладёт dependent_decor.py)
from planner import room_templates as RT  # noqa: E402
from planner.models import Item, Room  # noqa: E402

DRESSER = {'role': 'комод', 'x': 60.0, 'y': 120.0, 'rot': 90, 'w': 120.0, 'd': 45.0, 'h': 80.0, 'sku': {'name': 'Комод Берг'}}
SOFA = {'role': 'диван', 'x': 250.0, 'y': 300.0, 'rot': 180, 'w': 200.0, 'd': 90.0, 'h': 80.0, 'sku': {'name': 'Диван'}}
ROOM = (500, 400)


def lamp(eid, w=25, d=25, h=50, name='Лампа настольная'):
    return {'mid': 9, 'eid': str(eid), 'name': f'{name} {eid}', 'w': w, 'd': d, 'h': h, 'price': 4000}


def sets_with(*lamps, style='сканди'):
    return [{'style': style, 'items': {('лампа' if k == 0 else f'лампа {k + 1}'): it for k, it in enumerate(lamps)}}]


def any_model(it):
    return True, None


def test_place_is_passport_resolver_with_parent_local_and_fit():
    it, pl, why = DD.lamp_pick(sets_with(lamp(1)), 0, [SOFA, DRESSER], ROOM, any_model)
    assert it and not why
    places = RT._variant_places(RT.load('living'), *DD.LAMP_PLACE)
    res = DEP.resolve(places, DD.variant_carriers([SOFA, DRESSER], DD.LAMP_CARRIERS),
                      Room(width_cm=500, depth_cm=400, ceiling_cm=270), items={DD.LAMP_DEP: Item(role='лампа', w_cm=25, d_cm=25, h_cm=50)})
    (ref,) = [p for p in res.placements if p.slot_instance_id == 'light.lamp#0']
    row = DD.lamp_row(pl, [SOFA, DRESSER], {'name': it['name']})
    assert row['role'] == 'лампа' and row['strategy'] == 'carrier_surface'
    p = row['place']
    assert (p['x'], p['y'], p['bottom_cm']) == (ref.x, ref.y, ref.elev_cm) == (60.0, 120.0, 80.0)
    assert p['slot_instance_id'] == 'light.lamp#0' and p['parent_slot_instance_id'] == 'light.dresser#0'
    assert p['anchor'] == {'kind': 'item_surface', 'surface': 'top'} and p['local'] == {'dx': 0.0, 'dy': 0.0}
    assert p['carrier'] == {'role': 'комод', 'ordinal': 0}
    rule = RT.rule_value(DD.FIT_REF)
    assert DD.FIT_REF == 'distances_cm.dependents.table_lamp_on_surface'
    # опора без модели — весь габарит лампы (осторожно); сцене — норма лампы и опора
    assert p['fit'] == {'edge_clear_cm': rule['edge_clear_cm'], 'shade_overhang_front_cm': rule['shade_overhang_front_cm'],
                        'base_w_cm': 25.0, 'base_d_cm': 25.0}


def test_hung_dresser_lifts_lamp_like_scene():
    import draft_render as DR
    hung = dict(DRESSER, h=50.0, sku={'name': 'Комод подвесной Лайн'})
    _it, pl, _ = DD.lamp_pick(sets_with(lamp(1)), 0, [hung], ROOM, any_model)
    assert DD.lamp_row(pl, [hung], {})['place']['bottom_cm'] == 50.0 + float(DR.HUNG['dresser_bottom_cm'])


def test_big_lamp_falls_to_next_of_style_none_fits_no_row():
    big = lamp(1, w=60, d=60)
    it, _pl, why = DD.lamp_pick(sets_with(big, lamp(2)), 0, [DRESSER], ROOM, any_model)
    assert it['eid'] == '2' and 'FIT_FAIL' in why[0]
    it, pl, why = DD.lamp_pick(sets_with(big), 0, [DRESSER], ROOM, any_model)
    assert it is None and pl is None and 'FIT_FAIL' in why[0]
    # без модели — следующая; комода нет — отказ по комнате, дальше не ищем
    it, _pl, why = DD.lamp_pick(sets_with(lamp(1), lamp(2)), 0, [DRESSER], ROOM,
                                lambda x: (None, 'нет модели') if x['eid'] == '1' else (True, None))
    assert it['eid'] == '2' and 'нет модели' in why[0]
    it, _pl, why = DD.lamp_pick(sets_with(lamp(1)), 0, [SOFA], ROOM, any_model)
    assert it is None and 'CARRIER_MISSING' in why[0]


def test_lamp_without_height_takes_it_from_mesh_like_chandelier():
    import chandelier as CH
    tall = dict(lamp(1), h=None)
    it, pl, why = DD.lamp_pick(sets_with(tall), 0, [DRESSER], ROOM, lambda x: ((10.0, 30.0, 10.0), None))
    assert it['h'] == 75.0 == CH.hang_dims((10.0, 30.0, 10.0), 25)['h'] and not why and pl
    assert tall['h'] is None                     # банк не трогаем — копия
    # ни в карточке, ни у модели — следующая
    it, _pl, why = DD.lamp_pick(sets_with(tall, lamp(2)), 0, [DRESSER], ROOM, any_model)
    assert it['eid'] == '2' and 'высоты нет' in why[0]


def test_demo_and_tour_give_same_lamp_row(monkeypatch):
    import flat215_demo as FD
    import trial_demo as TD
    st = {'style': 'сканди', 'items': {'лампа': lamp(1), 'комод': {'mid': 9, 'eid': 'c', 'name': 'Комод Берг'}}}
    monkeypatch.setattr(FD, 'decor_model', any_model)
    monkeypatch.setattr(FD, '_sku', lambda items, role: {'name': items[role]['name'], 'price': items[role]['price']})
    demo = FD.lamp_decor([st], 0, 'set1', [SOFA, DRESSER], ROOM)
    rows = [dict(DRESSER, _it={'name': 'Комод Берг'}), dict(SOFA, _it={'name': 'Диван'})]
    for r in rows:
        r.pop('sku')
    (tour,) = TD.lamp_rows(st, rows, ROOM, None)
    assert demo['place'] == tour['place'] and demo['strategy'] == tour['strategy'] == 'carrier_surface'
    assert tour['sid'] == '9_1' and (tour['w'], tour['d'], tour['h']) == (25, 25, 50)
    # лампы в наборе нет или комода в варианте нет — строки нет (как было)
    assert FD.lamp_decor([{'style': 'сканди', 'items': {}}], 0, 'set1', [DRESSER], ROOM) is None
    assert FD.lamp_decor([st], 0, 'set1', [SOFA], ROOM) is None
    assert TD.lamp_rows(st, [dict(SOFA, _it={})], ROOM, None) == []


def test_tour_bundle_carries_lamp_with_goods_and_public_whitelist():
    import trial_bundle as TB
    import test_trial_bundle as TT
    flat = TT.flat_with_bedrooms()
    scene = TT.scene_for(flat)
    st = {'style': 'сканди', 'items': {'лампа': dict(lamp(1), mid=1, eid='2l')}}
    rows = [{'role': 'комод', 'x': 100.0, 'y': 30.0, 'rot': 0, 'w': 120.0, 'd': 45.0, 'h': 80.0, '_it': {'name': 'Комод'}}]
    scene['variants'][0]['decor'] = TD_rows = __import__('trial_demo').lamp_rows(st, rows, (500, 400), None)
    cat = dict(TT.CATALOG, **{'1_2l': {'name': 'Лампа Бра Хюгге', 'name_en': 'Hygge table lamp', 'colour_en': 'white', 'price': 3990,
                                       'img': 'img/0123456789abcdef.jpg', 'url': 'https://xf.gdeslon.ru/cm/l/?goto=y', 'shop': 'Hoff'}})
    d = TB.build(TT.JOB, flat, scene, ctx={**TT.GCTX, 'goods': lambda sid, role: dict(cat[sid]) if sid in cat else None},
                 parts=[TT.goods_bedroom_part()])
    v = next(v for v in d['variants'] if v['room_id'] == 'living' and v['style'] == 'сканди')
    (x,) = v['decor']
    assert x['role'] == 'лампа' and x['strategy'] == 'carrier_surface'
    assert x['place'] == {k: TD_rows[0]['place'][k] for k in TB.DECOR_PLACE_KEYS if k in TD_rows[0]['place']}
    assert x['place']['parent_slot_instance_id'] == 'light.dresser#0' and x['place']['carrier'] == {'role': 'комод', 'ordinal': 0}
    assert x['sku']['price'] == 3990 and x['sku']['name'] == 'Лампа Бра Хюгге' and x['sku']['w'] == 25
    assert set(x['sku']) <= TB.PUBLIC_SKU_KEYS and '"sid"' not in json.dumps(x) and '"_sid"' not in json.dumps(x)
    # упавший вариант декора не несёт
    assert all(not v['decor'] for v in d['variants'] if v.get('furniture_state') == 'failed')


def test_server_frame_keeps_vases_lamp_goes_to_rest():
    import draft_render as DR
    payload = {'items': [{'role': 'столик', 'x': 150, 'y': 180, 'rot': 0, 'w': 80, 'd': 50, 'h': 45},
                         dict(DRESSER)],
               'decor': [{'role': 'ваза', 'sku': {'w': 15, 'd': 15, 'h': 30}},
                         {'role': 'лампа', 'strategy': 'carrier_surface', 'place': {'x': 60, 'y': 120}, 'sku': {'w': 60, 'd': 60, 'h': 50}}]}
    placed, rest = DR.decor_layout(copy.deepcopy(payload))
    assert [p['decor']['role'] for p in placed] == ['ваза']
    assert [r['role'] for r in rest] == ['лампа']


def test_bedroom_lamp_is_dependent_decor():
    """T-20261113-22 (владелец TG 1623 «всё видно»): лампа спальни — не «только в списке», а зависимый декор на тумбе."""
    import demo_bedroom as DB
    assert DB.LIST_ROLES == () and DB.DEP_ROLES == ('лампа',) and DB.SPEC.dep_roles == ('лампа',)


# ───── T-20261113-12: лампа по размеру комода — основание по модели, лучшая по пропорции ─────
DRESSER_42 = dict(DRESSER, w=80.0, d=42.0, h=80.0)


def test_mesh_base_is_bottom_slice():
    import numpy as np
    # лампа: основание 10×10 внизу (y 0..2), абажур 40×40 наверху (y 30..60)
    g = np.linspace(-5, 5, 10)
    base = [(x, y, z) for x in g for z in g for y in (0.0, 1.0)]
    shade = [(x * 4, y, z * 4) for x in g for z in g for y in (30.0, 60.0)]
    bw, bd = DD.mesh_base_units(base + shade)
    assert (round(bw, 3), round(bd, 3)) == (10.0, 10.0)
    assert DD.mesh_base_units(base[:10]) is None                # мало вершин — основанию не верим
    # масштаб — как у габарита по мешу: max(Ш, Г) карточки = бо́льшая сторона плана меша
    assert DD.base_cm({'w': 38, 'd': 38}, (40.0, 60.0, 40.0), (10.0, 10.0)) == (9.5, 9.5)
    assert DD.base_cm({'w': 38, 'd': 38}, True, (10.0, 10.0)) == (None, None)


def test_big_shade_small_base_fits_42cm_dresser_without_base_not():
    """Владелец TG 1406: «лампу по размеру комода». Абажур 38 с основанием по модели 12 встаёт на комод 80×42 (раньше — нет: 20 %
    площади к габариту всей лампы); без основания по модели — опора = весь габарит, не встаёт."""
    big = lamp(1, w=38, d=38, h=60)
    ext = (38.0, 60.0, 38.0)
    it, pl, why = DD.lamp_pick(sets_with(big), 0, [DRESSER_42], ROOM, lambda x: (ext, None), lambda x: (12.0, 12.0))
    assert it and pl and pl.item.base_w_cm == 12.0
    assert DD.lamp_row(pl, [DRESSER_42], {})['place']['fit']['base_w_cm'] == 12.0
    it, pl, why = DD.lamp_pick(sets_with(big), 0, [DRESSER_42], ROOM, lambda x: (ext, None), lambda x: None)
    assert it is None and 'FIT_FAIL' in why[0]


def test_proportional_lamp_beats_first_in_bank():
    """Перебираются ВСЕ лампы стиля; лучшая по пропорции к комоду, а не первая годная. Своя лампа набора побеждает при равенстве."""
    tiny = lamp(1, w=15, d=15, h=30)           # 15/80 < 0,25 ширины, 30/80 < 0,55 высоты
    good = lamp(2, w=34, d=34, h=56)           # 34/80 = 0,43, 56/80 = 0,70 — в пропорции
    ext = lambda it: ((float(it['w']), float(it['h']), float(it['d'])), None)  # noqa: E731
    it, _pl, _why = DD.lamp_pick(sets_with(tiny, good), 0, [DRESSER_42], ROOM, ext, lambda x: (10.0, 10.0))
    assert it['eid'] == '2'
    twin = lamp(3, w=34, d=34, h=56)
    other = [{'style': 'сканди', 'items': {'лампа': twin}}]
    it, _pl, _why = DD.lamp_pick(sets_with(good) + other, 0, [DRESSER_42], ROOM, ext, lambda x: (10.0, 10.0))
    assert it['eid'] == '2'                    # равенство — своя набора
    it, _pl, _why = DD.lamp_pick(other + sets_with(good), 0, [DRESSER_42], ROOM, ext, lambda x: (10.0, 10.0))
    assert it['eid'] == '3'


def test_bed_foot_top_is_mattress_not_side_backs_or_dense_base():
    """Верх у изножья (T-20261113-22): матрас — плоскость из немногих вершин над густым основанием; боковые спинки кровати-софы идут
    вдоль всей длины. Замер берёт центр ширины и верх полосы — матрас, а не спинки (1,0) и не основание (0,3)."""
    import numpy as np
    rng = np.random.default_rng(1)
    n = 4000
    base = np.c_[rng.uniform(-1, 1, n), rng.uniform(0, 0.3, n), rng.uniform(-1, 1, n)]           # густое основание до 0,3
    top = np.c_[rng.uniform(-0.8, 0.8, 120), np.full(120, 0.5), rng.uniform(-1, 1, 120)]       # редкий верх матраса 0,5
    sides = np.c_[np.repeat([-0.98, 0.98], 600), rng.uniform(0, 1, 1200), rng.uniform(-1, 1, 1200)]   # спинки по бокам до 1,0
    v = np.vstack([base, top, sides])
    assert abs(DD.mesh_front_top(v) - 0.5) < 0.02
