"""Спальни витрины демо (onb-07 Т2, T-20261105-32): банк спальни → варианты с комнатой, назначением и своей геометрией; флаг
включения; ленты замен по ролям спальни. Без сети и базы (товар и габарит — из записи заготовки, солвер спальни — настоящий).
    ~/venvs/scout/bin/python tools/scout/tests/test_demo_bedroom.py"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
fails = 0


def check(name, cond):
    global fails
    print(('OK   ' if cond else 'FAIL ') + name)
    fails += 0 if cond else 1


import demo_bedroom as DB  # noqa: E402
import flat215_demo as F  # noqa: E402

FIX = os.path.join(HERE, 'fixtures', 'sets-bedroom.fixture.json')
bank = DB.load_bank(FIX)
check('заготовка банка: 2 записи спальни 1 «пара» со стилем', [(r['room_id'], r['purpose'], r['style']) for r in bank]
      == [('bedroom-1', 'couple', 'сканди'), ('bedroom-1', 'couple', 'современный')])
check('банка нет — пусто (комната остаётся «скоро»)', DB.load_bank(os.path.join(HERE, 'нет.json')) == [])

reg = {'id': 'bedroom-1', 'kind': 'bedroom', 'titleRu': 'Спальня 1', 'areaM2': 17.5}
geo = DB.room_geo('bedroom-1', reg, {'height_cm': 270})
check('геометрия спальни 1 — основной вариант чертежа 618×293, тип зоны «bedroom», подпись реестра',
      (geo['w'], geo['d'], geo['kind'], geo['title'], geo['height_cm']) == (618, 293, 'bedroom', 'Спальня 1 17.5 м²', 270))
check('служебные пояснения проёмов в данные не идут', not any(k.startswith('_') for o in geo['openings'] + geo['radiators'] for k in o))
check('комнаты нет в файле геометрии — None', DB.room_geo('bedroom-9', {}) is None)


def sku(items, role):
    it = items.get(role) or items.get(DB.base_role(role))
    return it and {'name': it['name'], 'price': it['price'], 'img': it['img'], 'sid': f"{it['mid']}_{it['eid']}",
                   'msid': f"{it['mid']}_{it['eid']}", 'w': it['w'], 'd': it['d'], 'h': it['h']}


v, why = DB.build_variant(bank[0], geo, sku, F._dims_of, F.style_id)
roles = sorted(i['role'] for i in v['items'])
check('вариант: id «комната-стиль», комната и назначение из записи', (v['id'], v['room_id'], v['purpose'], v['style_id'])
      == ('bedroom-1-scandi', 'bedroom-1', 'couple', 'scandi') and why is None)
check('солвер спальни расставил кровать, обе тумбы, шкаф и комод',
      roles == ['комод', 'кровать', 'тумба прикроватная', 'тумба прикроватная 2', 'шкаф'])
inside = all(0 <= i['x'] - i['w'] / 2 + 1e-6 or i['rot'] % 180 for i in v['items'])
bed = next(i for i in v['items'] if i['role'] == 'кровать')
win = [o for o in geo['openings'] if o['kind'] == 'window']
# изголовье — у стены rot 0 → y = 0 (юг); окна спальни 1 — восток и север: изголовье не в окно
check('изголовье кровати не у окна (стена изголовья без окна)',
      bed['rot'] == 0 and abs(bed['y'] - bed['d'] / 2) < 2 and not any(o['wall'] == 'south' for o in win))
check('габариты — товара, не придуманы', (bed['w'], bed['d']) == (173.0, 203.0))
no_bed = dict(bank[0], items={k: x for k, x in bank[0]['items'].items() if k != 'кровать'})
v2, why2 = DB.build_variant(no_bed, geo, sku, F._dims_of, F.style_id)
check('без кровати вариант не публикуется, причина — с комнатой', v2 is None and why2['room_id'] == 'bedroom-1'
      and 'кровать' in why2['missing'])
v3, why3 = DB.build_variant(dict(bank[0], style='бохо'), geo, sku, F._dims_of, F.style_id)
check('стиль вне витрины — не публикуется', v3 is None and why3['missing'] == ['стиль вне витрины'])
lay = {'кровать': {'x': 300, 'z': 102, 'rot': 0}, 'тумба прикроватная': {'x': 200, 'z': 21, 'rot': 0}}
v4, _ = DB.build_variant(bank[0], geo, sku, F._dims_of, F.style_id, layout=lay)
check('готовая расстановка записи берётся как есть, без солвера', sorted(i['role'] for i in v4['items']) == ['кровать', 'тумба прикроватная'])

# ГОТОВАЯ РАССТАНОВКА БАНКА (формат onb-06, T-31): места в комнате записи, вторые экземпляры — «… 2», лампа на тумбе — строкой списка
L = {'_room': {'variant': 'registry-17.5', 'w': 597, 'd': 293, 'openings': geo['openings'], 'radiators': geo['radiators']},
     '_meta': {'solver': 'bedroom-v1'}, 'кровать': {'x': 298.5, 'z': 101.5, 'rot': 0},
     'тумба прикроватная': {'x': 190, 'z': 17.5, 'rot': 0}, 'тумба прикроватная 2': {'x': 407, 'z': 17.5, 'rot': 0},
     'ковёр': {'x': 298.5, 'z': 167.7, 'rot': 0}, 'лампа': {'x': 190, 'z': 17.5, 'elev': 52, 'on': 'тумба прикроватная'},
     'лампа 2': {'x': 407, 'z': 17.5, 'elev': 52, 'on': 'тумба прикроватная 2'}}
its = {k: x for k, x in bank[0]['items'].items() if k != 'тумба прикроватная 2'}
its['ковёр'] = dict(its['комод'], name='Ковер Мирна 200x300', w=300, d=200, h=1)
its['лампа'] = dict(its['комод'], name='Светильник настольный', w=11, d=11, h=38, qty=2)
rb = dict(bank[0], items=its, layout=L)
v5, _ = DB.build_variant(rb, geo, sku, F._dims_of, F.style_id, decor_role=lambda r: False)
check('банк onb-06: вторая тумба — по месту «… 2», ковёр — в сцене, шкаф и комод без места — не выдуманы',
      sorted(i['role'] for i in v5['items']) == ['ковёр', 'кровать', 'тумба прикроватная', 'тумба прикроватная 2'])
check('банк onb-06: лампы на тумбах — две строки списка, не в 3D', [d['role'] for d in v5['decor']] == ['лампа', 'лампа 2'])
check('банк onb-06: геометрия — комната расстановки записи (597×293), не чертёж', DB.bank_room([rb], 'bedroom-1')['w'] == 597
      and DB.room_geo('bedroom-1', reg, layout_room=DB.bank_room([rb], 'bedroom-1'))['w'] == 597)
tiers = [dict(bank[0], tier=t, set_id=t) for t in ('эконом', 'премиум', 'комфорт')]
check('ячейка витрины: средняя ступень цены «комфорт»', [r['set_id'] for r in DB.pick_records(tiers, ['bedroom-1'], ['сканди'])]
      == ['комфорт'])

recs = DB.pick_records(bank + [dict(bank[0], room_id='bedroom-2')], ['bedroom-1'], ['современный', 'сканди', 'лофт'])
check('отбор записей: только включённые комнаты, стили и порядок — витрины гостиной',
      [(r['room_id'], r['style']) for r in recs] == [('bedroom-1', 'современный'), ('bedroom-1', 'сканди')])

msid = lambda s: s  # noqa: E731
fd = DB.feeds(bank, {'roles': {'кровать': [{'sid': '1:2', 'name': 'Кровать Х 160', 'img': 'x.jpg', 'price': 9, 'w': 170, 'd': 210,
                                            'h': 90}]}}, msid, lambda m: m != '112923_11672424920201226922')
check('ленты спальни: товары наборов со стилем, каталог — без стиля, дешевле сначала',
      [(p['name'][:7], p['styles']) for p in fd['кровать']] == [('Кровать', []), ('Кровать', ['сканди']), ('Кровать', ['современный'])])
check('ленты спальни: товар без модели на сервере в ленту не идёт', all(p['sid'] != '112923_11672424920201226922'
                                                                       for p in fd.get('комод', [])))
check('ленты спальни: тумба двух слотов — одна строка', len(fd['тумба прикроватная']) == 2)
check('полоса размера кровати «вдвоём» 160–205 и тумб', DB.bands(['couple']) == {'тумба прикроватная': {'lo': 30, 'hi': 65},
                                                                              'кровать': {'lo': 160, 'hi': 205}})

# ФЛАГ: проверочное включение — только у сборки рядом; главная демо — реестром
apt = F.demo_apartment()
check('флаг: без переменной — как реестр (всё выключено)', F.rooms_on(apt, {}) == {})
check('флаг: сборка рядом включает спальню 1', F.rooms_on(apt, {F.ROOMS_ENV: 'bedroom-1'}, '/tmp/x-demo')
      == {'rooms_enabled': ['bedroom-1']})


def refuse(env, out):
    try:
        F.rooms_on(apt, env, out)
        return ''
    except SystemExit as e:
        return str(e)


check('флаг: переменная у папки витрины — отказ', 'реестром' in refuse({F.ROOMS_ENV: 'bedroom-1'}, F._BP.DEMO_OUT_DEFAULT))
check('флаг: опечатка в id комнаты — отказ', 'нет в реестре' in refuse({F.ROOMS_ENV: 'bedrom-1'}, '/tmp/x-demo'))
print('итог:', 'FAIL' if fails else 'OK')
sys.exit(1 if fails else 0)
