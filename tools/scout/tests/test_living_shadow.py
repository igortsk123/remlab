"""T-20261112-69: тень гостиной (`living_shadow.py`) — предметы варианта на места уровня, частичная проверка, вариант целиком
на комнате и раскладке как у /demo set1 (без node и файлов витрины)."""
import os
import sys

import pytest

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
    assert kind['ваза'] == 'оба'                                           # место вазы на столике у SD есть (T-71; в T-69 не было)
    assert kind['картина'] == kind['картина 2'] == 'оба'
    pil = [p for p in sv['deps'] if p.role == 'подушка']
    assert len(pil) == 2 and {p.parent_slot_instance_id for p in pil} == {'seating.sofa#0'}   # 2 товара — 2 места, не 3 по ширине
    assert sv['art']['shift_cm'] == 7.0                                    # живые числа (22 над спинкой) против середины 10–20
    assert sv['empty_slots'] == [] and [e for e in sv['empty_deps'] if e['code'] != S.NO_ITEM] == []
    assert {e['place'] for e in sv['empty_deps']} == {'ceiling.chandelier', 'soft.throw'}   # в декоре примера нет люстры и пледа


def test_tour_set_without_light_no_level_only_light():
    """Набор тура без торшера и комода (T-71/2): свет обязателен — уровня нет, признак «не хватает только света»; без столика
    — тоже отказ, но уже не «только свет»."""
    items = [x for x in ITEMS if x['role'] != 'торшер']
    sv = S.shadow_variant(GEO, {'id': 't', 'style': 'сканди', 'items': items, 'decor': []}, [])
    assert sv['status'].startswith('нет уровня') and sv['only_light'], sv['status']
    assert sv['missing'] and all(m in ('торшер×1', 'комод×1') for m in sv['missing'])
    no_table = [x for x in items if x['role'] != 'столик']                 # столик — всегда: нет его — честный отказ
    sv2 = S.shadow_variant(GEO, {'id': 't2', 'style': 'сканди', 'items': no_table, 'decor': []}, [])
    assert sv2['status'].startswith('нет уровня') and 'столик×1' in sv2['missing'] and not sv2['only_light']


def test_tour_without_decor_places_empty_no_item():
    """Тур с торшером, декора в данных нет: уровень есть, места подушек по норме (3), но ПУСТЫЕ — «нет в наборе» в `empty_deps`
    (NO_ITEM) и пустым кружком на схеме; экран ТВ (непродаваемое) — не в счёт."""
    sv = S.shadow_variant(GEO, {'id': 't', 'style': 'сканди', 'items': ITEMS, 'decor': []}, [])
    assert (sv['tpl'], sv['level'], sv['status']) == ('LR-C1', 'SD', 'OK'), sv['tried']
    pil = [p for p in sv['deps'] if p.role == 'подушка']
    assert len(pil) == 3 and all(S.is_no_item(p) for p in pil)        # товаров не знаем — по норме: диван 198 см — 3
    no = {e['place']: e for e in sv['empty_deps'] if e['code'] == S.NO_ITEM}
    assert no['soft.pillows']['n'] == 3 and 'нет в наборе' in no['soft.pillows']['message']
    assert not any(p.priced is False and p.slot_instance_id.split('#')[0] in no for p in sv['deps'])


def test_demo_set_with_decor_has_no_empty_places():
    """/demo-набор с декором: у мест мелочей есть товар — пустых «нет в наборе» нет (схема рисует их заполненными)."""
    full = DECOR + [{'role': r, 'sku': {'name': r, 'w': w, 'd': w, 'h': h, 'price': 500}} for r, w, h in (('плед', 130, 2), ('люстра', 60, 40))]
    sv = S.shadow_variant(GEO, {'id': 'set1', 'style': 'сканди', 'items': ITEMS, 'decor': full}, [])
    assert sv['status'] == 'OK' and [e for e in sv['empty_deps'] if e['code'] == S.NO_ITEM] == []


def test_rug_drawn_first_under_furniture():
    """Ковёр на схеме — первым (под мебелью): иначе закрывает журнальный столик и ваза «висит» на ковре."""
    sv = S.shadow_variant(GEO, {'id': 'set1', 'style': 'сканди', 'items': ITEMS, 'decor': DECOR}, [])
    order = [S.base_role(p.role) for p in S.floor_draw_order(sv['floor'])]
    assert order[0] == 'ковёр' and order.index('столик') > order.index('ковёр')


def test_only_light_summary_line():
    """Строка-итог отчёта: «не хватает ТОЛЬКО света: N туров» + стили с торшерами каталога и банка."""
    items = [x for x in ITEMS if x['role'] != 'торшер']
    sv = {**S.shadow_variant(GEO, {'id': 't', 'style': 'сканди', 'items': items, 'decor': []}, []), 'src': 'x'}
    L = S.light_summary([sv], {'sets': {'сканди': {'n': 21, 'торшер': 3, 'комод': 15}}, 'catalog': {'сканди': 11}})
    assert 'ТОЛЬКО света (торшер или комод + лампа): 1 туров' in L[0]
    assert any(ln.startswith('| сканди | 1 | 21 | 3 | 15 | 11 |') for ln in L)
    assert any('стилей без торшера в каталоге: нет' in ln for ln in L)
    assert S.light_label(['кресло×1', 'комод×1']) == ['кресло×1', 'свет (торшер или комод + лампа)']
    assert S.light_label(['столик×1']) == ['столик×1']


def test_area_counts_annex_but_not_corridor_stub():
    """Площадь для выбора уровня — весь контур: пристройка в счёт, хвост коридора (stub) и балкон (outdoor) — нет."""
    geo = {**GEO, 'w': 335, 'd': 380, 'title': 'Кухня-гостиная',
           'annexes': [{'x': 80, 'y': 380, 'w': 255, 'd': 265}, {'x': -40, 'y': 398, 'w': 120, 'd': 90, 'stub': True},
                       {'x': 0, 'y': -100, 'w': 200, 'd': 100, 'outdoor': True}]}
    _, notes, facts = S.to_room(geo)
    assert facts['area_m2'] == pytest.approx(3.35 * 3.80 + 2.55 * 2.65) and facts['kitchen'] and facts['annex']
    assert RT.select(S.DOC, facts)[0] == 'LR-O1'
