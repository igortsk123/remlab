"""Люстра гостиной из набора (T-20261112-66): размер по мешу, подвес укорачивается, следующая — только если не влезает корпус;
МЕСТО — решатель паспорта (`dependents.resolve`, место `ceiling.chandelier`), норма низа — `rule_value` паспорта.
Без сети и моделей: габариты мешей и товары подменены синтетикой.
    ~/venvs/scout/bin/python tools/scout/tests/test_chandelier.py"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
import chandelier as CH  # noqa: E402
from planner import dependents as DEP  # noqa: E402  (путь к решателю кладёт chandelier.py)
from planner import room_templates as RT  # noqa: E402
from planner.models import Item, Placement, Room  # noqa: E402

fails = 0


def ok(name, cond, extra=''):
    global fails
    print(('OK   ' if cond else 'FAIL ') + name + (f' — {extra}' if extra and not cond else ''))
    fails += 0 if cond else 1


# 1) размер: наибольшая сторона плана меша = диаметр, высота — пропорцией (подвес со шнуром выше корпуса из карточки)
d = CH.hang_dims((1.31, 1.99, 1.17), 64)
ok('hang_dims: ширина = диаметр', d['w'] == 64.0, d)
ok('hang_dims: высота по пропорциям меша', d == {'w': 64.0, 'd': 57.2, 'h': 97.2}, d)
ok('hang_dims: плоский меш — нет габарита', CH.hang_dims((1, 0, 1), 60) is None)
ok('diameter: dia, иначе max(w, d)', CH.diameter({'dia': 66}) == 66 and CH.diameter({'w': 40, 'd': 55}) == 55
   and CH.diameter({}) is None)

# 2) норма низа — из паспорта, своего числа нет; подвес укорочен до нормы; корпус — по каталогу
ok('bottom_min_cm: rule_value паспорта', CH.bottom_min_cm() == float(RT.rule_value(CH.NORM + '.bottom_min')) == 210.0)
ok('drop_cm: плафон висит на свою высоту', CH.drop_cm({'h': 26.3}, 270, 210) == 26.3)
ok('drop_cm: длинный подвес укорочен до нормы', CH.drop_cm({'h': 158.2}, 270, 210) == 60)
ok('fits: корпус 60 при потолке 270 влезает', CH.fits(60, 270, 210))
ok('fits: корпус 86 при потолке 270 не влезает', not CH.fits(86, 270, 210))
ok('body_h: каталожная, иначе меш', CH.body_h({'h': 32}, {'h': 97}) == 32 and CH.body_h({}, {'h': 97}) == 97)

# 3) переходник «вариант → носители»: роли зоны отдыха → места паспорта, чужие роли и предметы без размера — мимо
SOFA = {'role': 'диван', 'x': 200, 'y': 305, 'rot': 180, 'w': 200, 'd': 90, 'h': 80}
TABLE = {'role': 'столик', 'x': 150, 'y': 180, 'rot': 0, 'w': 80, 'd': 50, 'h': 45}
RUG = {'role': 'ковёр', 'x': 230, 'y': 210, 'rot': 0, 'w': 200, 'd': 140, 'h': 1}
TV = {'role': 'тумба ТВ', 'x': 200, 'y': 20, 'rot': 0, 'w': 160, 'd': 40, 'h': 50}
VARIANT = [SOFA, TABLE, RUG, TV, {'role': 'кресло', 'x': 60, 'y': 200, 'rot': 90}, dict(SOFA, role='диван 2', x=330)]
cars = CH.carriers_from_variant(VARIANT)
ok('carriers_from_variant: места паспорта', [c.slot_instance_id for c in cars]
   == ['seating.sofa#0', 'seating.coffee#0', 'seating.rug#0', 'seating.sofa2#0'], [c.slot_instance_id for c in cars])


def lamp(eid, h, dia=60, name=None):
    return {'mid': '1', 'eid': str(eid), 'h': h, 'dia': dia, 'name': name or f'L{eid}'}


EXT = {'1': (1.0, 1.0, 1.0), '2': (1.0, 2.5, 1.0), '3': (1.0, 0.5, 1.0)}
model = lambda it: (EXT.get(it['eid']), None) if it['eid'] in EXT else (None, 'нет меша')  # noqa: E731
sets = [
    {'style': 'сканди', 'items': {'люстра': lamp(1, 30), 'диван': {'mid': '9', 'eid': '9'}}},
    {'style': 'лофт', 'items': {'люстра': lamp(2, 90)}},          # корпус 90 — не влезает
    {'style': 'лофт', 'items': {'люстра': lamp(4, 20)}},          # меша нет
    {'style': 'лофт', 'items': {'люстра': lamp(3, 25)}},
    {'style': 'сканди', 'items': {'люстра': lamp(1, 30)}},       # повтор артикула
]
WD = (400, 350)

# 4) подбор и место
it, dims, pl, why = CH.pick(sets, 0, VARIANT, WD, None, model)
ok('pick: своя влезла — своя, потолок по умолчанию', it['eid'] == '1' and not why and dims['h'] == 60.0, (it, dims, why))
ok('pick: место решателя — центр ковра, низ = потолок − высота меша',
   (pl.x, pl.y, pl.elev_cm, pl.slot_instance_id) == (230, 210, 210, 'ceiling.chandelier#0'), pl)
ok('candidates: без повторов и чужих стилей', [c[2]['eid'] for c in CH.candidates(sets, 0)] == ['1'])
it, dims, pl, why = CH.pick(sets, 1, VARIANT, WD, 270, model)
ok('pick: корпус не влез, меша нет — следующая того же стиля', it and it['eid'] == '3' and len(why) == 2, (it, why))
ok('pick: причина отказа — корпус', 'корпус 90' in why[0], why)
ok('pick: плафон 30 см — висит на свою высоту', pl.elev_cm == 240, pl)
it, dims, pl, why = CH.pick(sets, 1, VARIANT, WD, 230, model)
ok('pick: низкий потолок — ничего (не «в цене без 3D»)', it is None and pl is None and len(why) == 3, why)
it, dims, pl, why = CH.pick(sets, 0, [TV], WD, 270, model)
ok('pick: отказ решателя по комнате (нет зоны отдыха) — ничего, без перебора', it is None and len(why) == 1
   and 'CARRIER_MISSING' in why[0], why)
it, dims, pl, why = CH.pick(sets, 0, [SOFA, TABLE], WD, 270, model)
ok('pick: нет ковра — центр рамки зоны (диван + столик)', (pl.x, pl.y) == (200, 252.5), pl)
it, dims, pl, why = CH.pick([{'style': 'x', 'items': {'диван': {'mid': '9', 'eid': '9'}}}], 0, VARIANT, WD, 270, model)
ok('pick: в наборе люстры нет — ничего, журнал пуст', it is None and why == [], why)

# 5) ЭКСПОРТ: место люстры в данных демо = место `dependents.resolve` на том же варианте (носители собраны здесь вручную,
#    не переходником — иначе тест сверял бы код сам с собой). Сервер мешей и каталог подменены
import flat215_demo as F  # noqa: E402

F._mesh_index = lambda: {'m1'}
F._msid = lambda sid: 'm1'
F.color_ok = lambda m, name: True
F.colour_flagged = lambda sid: False
F._mesh_extents = lambda m: (1.31, 1.99, 1.17)
F._sku = lambda items, role: {'name': items[role]['name'], 'price': 9000, 'msid': 'm1'}
F.demo_ceiling = lambda: 265.0
ent = F.chandelier_decor([{'style': 'сканди', 'items': {'люстра': lamp(1, 32, dia=64, name='Люстра')}}], 0, 'set1', VARIANT, WD)
hand = [Placement(role='диван', x=200, y=305, rot=180, item=Item(role='диван', w_cm=200, d_cm=90, h_cm=80),
                  slot_instance_id='seating.sofa#0'),
        Placement(role='столик', x=150, y=180, rot=0, item=Item(role='столик', w_cm=80, d_cm=50, h_cm=45),
                  slot_instance_id='seating.coffee#0'),
        Placement(role='ковёр', x=230, y=210, rot=0, item=Item(role='ковёр', w_cm=200, d_cm=140, h_cm=1),
                  slot_instance_id='seating.rug#0')]
ref = DEP.resolve(RT._variant_places(RT.load('living'), 'ceiling', 'chandelier_seating'), hand,
                  Room(width_cm=400, depth_cm=350, ceiling_cm=265.0),
                  items={'ceiling.chandelier': Item(role='люстра', w_cm=64, d_cm=64, h_cm=55)})
(rp,) = [p for p in ref.placements if p.slot_instance_id.startswith('ceiling.chandelier#')]
ok('экспорт: место = dependents.resolve того же варианта', ent and ent['place'] == {
    'x': rp.x, 'y': rp.y, 'bottom_cm': rp.elev_cm, 'slot_instance_id': rp.slot_instance_id}, (ent, rp))
ok('экспорт: подвес 97 см укорочен до нормы — низ 210', ent and ent['place']['bottom_cm'] == 210, ent)
ok('экспорт: в цене каталог, в сцене — меш', ent and ent['sku']['h'] == 32 and ent['sku']['hang']['h'] == 97.2, ent)
ok('экспорт: своего числа нормы в строке нет', ent and 'bottom_min_cm' not in ent, ent)

print('test_chandelier:', 'FAIL' if fails else 'OK')
sys.exit(1 if fails else 0)
