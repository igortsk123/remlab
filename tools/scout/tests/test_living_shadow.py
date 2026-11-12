"""T-20261112-69: тень гостиной (`living_shadow.py`) — предметы варианта на места уровня, частичная проверка, вариант целиком
на комнате и раскладке как у /demo set1 (без node и файлов витрины)."""
import os
import sys

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import living_shadow as S  # noqa: E402
from planner import room_templates as RT  # noqa: E402

GEO = {'w': 439, 'd': 325, 'title': 'Гостиная 14.4 м²',
       'openings': [{'kind': 'window', 'wall': 'west', 'offset_cm': 70, 'width_cm': 150, 'sill_cm': 85, 'height_cm': 150},
                    {'kind': 'door', 'wall': 'east', 'offset_cm': 205, 'width_cm': 90, 'swing_cm': 90}]}


def it(role, x, y, rot, w, d, h, price=1000):
    return {'role': role, 'x': x, 'y': y, 'rot': rot, 'w': w, 'd': d, 'h': h, 'sku': {'name': role, 'sid': role, 'price': price}}


ITEMS = [it('диван', 155.3, 280, 180, 198, 90, 83), it('столик', 155.3, 162.5, 180, 110, 60, 36), it('пуф', 57.8, 162.5, 90, 35, 35, 42),
         it('торшер', 33.3, 300, 180, 30, 30, 160), it('ковёр', 155.3, 180, 180, 230, 160, 1), it('тв-тумба', 155.3, 25, 0, 139, 45, 50),
         it('стол обеденный', 394, 50, 270, 90, 90, 75), it('стул', 324.5, 50, 90, 45, 50, 85), it('стул 2', 394, 119.5, 180, 45, 50, 85)]
DECOR = [{'role': r, 'sku': {'name': r, 'w': w, 'd': w, 'h': h, 'price': 500}}
         for r, w, h in (('подушка', 45, 11), ('подушка 2', 45, 11), ('ваза', 16, 20), ('шторы', 280, 300), ('картина', 60, 90),
                         ('картина 2', 60, 90))]


def _level(tid, lid):
    places, err = RT.compile_level(S.DOC, RT.template_by_id('living', tid), lid)
    assert not err, err
    return places


def test_match_slots_extras_missing():
    places = _level('LR-C1', 'SD')
    cars, missing, extra, sid_of, miss = S.match(places, ITEMS)
    assert not missing and not miss
    assert {c.slot_instance_id for c in cars} >= {'seating.sofa#0', 'dining.chairs#0', 'dining.chairs#1', 'light.floor_lamp#0'}
    assert [e.slot_instance_id for e in extra] == ['extra.пуф#0']          # пуф вне уровня — остаётся на полу, как в живой сцене
    assert len(sid_of) == len(ITEMS)
    floor, miss2 = S.carriers_from_variant({'items': ITEMS}, places)       # переходник для живого экспорта — то же самое
    assert not miss2 and {p.slot_instance_id for p in floor} == set(sid_of.values())
    no_lamp = [x for x in ITEMS if x['role'] != 'торшер']
    _, missing, _, _, miss = S.match(places, no_lamp)
    assert missing == ['торшер×1'] and miss == {'light.floor_lamp'}


def test_partial_drops_group_and_its_dependents():
    places = _level('LR-C1', 'SA')                                        # комод + лампа на нём; картина — над диваном или комодом
    part, dropped = S.partial_places(places, {'light.dresser', 'seating.coffee'})
    ids = {p['id'] for p in part}
    assert dropped == ['light.dresser', 'seating.coffee']
    assert not ids & {'light.dresser', 'light.lamp', 'seating.coffee', 'vase.vase'}      # лампа на комоде, ваза на столике
    assert {'seating.sofa', 'soft.pillows', 'soft.throw'} <= ids                       # диван есть — подушки проверяются
    art = next(p for p in part if p['id'] == 'art.art')
    assert art['carrier']['one_of'] == ['seating.sofa']


def test_variant_like_demo_set1():
    rows = [{'src': 'item', 'role': x['role'], 'name': x['role'], 'price': 1000, 'qty': 1, 'slots': 1, 'shown': 1, 'qty_shown': 1}
            for x in ITEMS]
    rows += [{'src': 'decor', 'role': d['role'], 'name': d['role'], 'price': 500, 'qty': 1, 'slots': 1,
              'shown': 0 if d['role'].startswith(('подушка', 'шторы')) else 1, 'qty_shown': 0} for d in DECOR]
    sv = S.shadow_variant(GEO, {'id': 'set1', 'style': 'сканди', 'items': ITEMS, 'decor': DECOR}, rows)
    assert (sv['tpl'], sv['level'], sv['status']) == ('LR-C1', 'SD', 'OK'), sv['tried']
    assert sv['drift_cm'] == 0 and not sv['hard']                          # носители не сдвинуты, зависимые в комнате
    kind = {r['role']: r['kind'] for r in sv['rows']}
    assert kind['подушка'] == kind['подушка 2'] == 'тень добавила'
    assert kind['шторы'] == 'место есть, товар отдельно'
    assert kind['ваза'] == 'тень потеряла'                                 # у уровня SD нет места вазы (находка T-69)
    assert kind['картина'] == kind['картина 2'] == 'оба'
    assert {p.parent_slot_instance_id for p in sv['deps'] if p.role == 'подушка'} == {'seating.sofa#0'}
    assert sv['art']['shift_cm'] == 7.0                                    # живые числа (22 над спинкой) против середины 10–20
