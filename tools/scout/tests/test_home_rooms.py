"""Главная «стиль → комнаты» (demo-16): генератор витрины берёт комнаты квартиры из реестра застройщиков, у варианта —
латинский id стиля для `?style=` и комната, которую он обставляет. Без сети и базы.
    ~/venvs/scout/bin/python tools/scout/tests/test_home_rooms.py"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
fails = 0


def check(name, cond):
    global fails
    print(('OK   ' if cond else 'FAIL ') + name)
    fails += 0 if cond else 1


import flat215_demo as F  # noqa: E402

check('стили витрины — латинские id', [F.style_id(s) for s in ['сканди', 'Современный', 'минимализм', 'лофт', 'джапанди', 'неоклассика']]
      == ['scandi', 'modern', 'minimal', 'loft', 'japandi', 'neoclassic'])
check('неизвестный стиль — пусто, не выдуманный транслит', F.style_id('бохо') == '' and F.style_id(None) == '')
rooms = F.demo_apartment().get('rooms') or []
check('комнаты квартиры демо — из реестра, в порядке плана',
      [r['id'] for r in rooms] == ['living', 'kitchen', 'bedroom-1', 'bedroom-2', 'bathroom-1', 'bathroom-2', 'hall'])
check('готова только гостиная', [r['id'] for r in rooms if r['contentState'] == 'ready'] == ['living'])
check('варианты обставляют гостиную реестра', F.living_room_id() == 'living')
# ФЛАГИ НОВЫХ КОМНАТ И ОПРОСА (ADR-0330 п.5, onb-12): выключено — полей в demo-data.json нет (данные гостиной прежние)
check('флаги: в реестре всё выключено — полей нет', F.room_flags(F.demo_apartment()) == {})
on = dict(F.demo_apartment(), quiz={'enabled': True},
          rooms=[dict(r, enabled=r['id'] in ('bedroom-1', 'kitchen')) for r in rooms])
check('флаги: включённые комнаты — в порядке плана, опрос — true',
      F.room_flags(on) == {'rooms_enabled': ['kitchen', 'bedroom-1'], 'quiz_enabled': True})
check('флаги: строка «true» не включает', F.room_flags(dict(on, quiz={'enabled': 'true'},
                                                             rooms=[dict(r, enabled='true') for r in rooms])) == {})

# ОДНА ИСТИНА ПЛОЩАДЕЙ (T-20261022-04): реестр — комнаты + лоджия = площадь квартиры; схема плана — только геометрия с id реестра
import json  # noqa: E402
apt = F.demo_apartment()
flat = json.load(open(os.path.join(HERE, '..', 'flat215.json'), encoding='utf-8'))
check('площади реестра: комнаты + лоджия = площадь квартиры (77,2)',
      abs(sum(r['areaM2'] for r in rooms) + (apt.get('loggiaM2') or 0) - apt['areaM2']) <= 0.2 and apt['areaM2'] == 77.2)
# СПАЛЬНЯ 2 = 13,2 ВЕЗДЕ (владелец 05.11, T-20261105-27): подпись из реестра и геометрия плана — одно число
_br2 = next(r for r in flat['plan_example']['rooms'] if r['id'] == 'bedroom-2')
check('спальня 2: реестр 13,2 = геометрия плана (4,50 × 2,93)',
      next(r['areaM2'] for r in rooms if r['id'] == 'bedroom-2') == 13.2 and round(_br2['w'] * _br2['d'], 1) == 13.2)
check('схема плана: комнаты с id реестра и без своих площадей/имён',
      {r['id'] for r in flat['plan_example']['rooms']} <= {r['id'] for r in rooms}
      and not any('m2' in r or 'name' in r for r in flat['plan_example']['rooms']))
check('flat215.json: только геометрия гостиной, второго списка комнат с площадями нет', [r['id'] for r in flat['rooms']] == ['living'])


def guard(a, plan):
    try:
        F.apartment_area_check(a, plan)
        return 'ok'
    except SystemExit as e:
        return str(e)


check('сторож площадей: реальные данные проходят', guard(apt, flat['plan_example']) == 'ok')
bad = dict(apt, rooms=[r for r in rooms if r['id'] != 'bathroom-2'])
check('сторож площадей: пропала комната — сборка падает с суммой', guard(bad, {}).startswith('FAIL:площади: комнаты'))
check('сторож площадей: комната схемы не из реестра — сборка падает',
      'bath_44' in guard(apt, {'rooms': [{'id': 'bath_44'}]}))

# ОСНОВА НЕСКОЛЬКИХ КОМНАТ (onb-07, ADR-0330 п.3): `rooms_geo` — гостиная тем же объектом, что `room`; другие комнаты рядом
liv = {'w': 439, 'd': 325, 'title': 'Гостиная', 'openings': [], 'radiators': []}
bed = {'w': 618, 'd': 293, 'title': 'Спальня 1', 'openings': [], 'radiators': []}
g = F.rooms_geo(liv)
check('rooms_geo: только гостиная, тот же объект, что room', list(g) == ['living'] and g['living'] is liv)
g2 = F.rooms_geo(liv, {'bedroom-1': bed, 'living': bed, 'bad': {'w': 0}})
check('rooms_geo: спальня рядом, гостиную не подменить, пустую геометрию не берём',
      list(g2) == ['living', 'bedroom-1'] and g2['living'] is liv and g2['bedroom-1'] is bed)
d = {'room': liv, 'rooms_geo': g2, 'variants': [{'id': 'set1', 'room_id': 'living'}, {'id': 'b1', 'room_id': 'bedroom-1'}]}
check('unique_rooms: гостиная один раз (room и rooms_geo — один объект), спальня отдельно',
      [r['title'] for r in F.unique_rooms(d)] == ['Гостиная', 'Спальня 1'])
check('unique_rooms: старые данные без rooms_geo — одна гостиная', len(F.unique_rooms({'room': liv})) == 1)
check('rooms_check: всё на месте — молчит', F.rooms_check(d) == [])
warn = F.rooms_check(dict(d, variants=d['variants'] + [{'id': 'k1', 'room_id': 'kitchen'}]))
check('rooms_check: комнаты варианта нет — WARN', len(warn) == 1 and 'kitchen' in warn[0])
try:
    F.rooms_check(dict(d, variants=[{'id': 'set1', 'room_id': 'living'}, {'id': 'set1', 'room_id': 'bedroom-1'}]))
    dup = 'ok'
except SystemExit as e:
    dup = str(e)
check('rooms_check: один номер варианта в двух комнатах — сборка падает', dup.startswith('FAIL:rooms:'))
# СПАЛЬНИ ВИТРИНЫ (onb-07 Т2, T-20261105-32): флаг выключен — вариантов, лент и геометрий спален нет, списки не тронуты
vs0, fd0, inc0 = [{'id': 'set1', 'style': 'сканди'}], {'диван': []}, []
check('спальни: флаг выключен — данные гостиной не тронуты',
      F.bedroom_variants(F.demo_apartment(), {}, vs0, fd0, inc0, liv, {}) == ({}, {})
      and vs0 == [{'id': 'set1', 'style': 'сканди'}] and fd0 == {'диван': []} and inc0 == [])
check('спальни: включена только кухня — спальни не строятся', F.bedroom_variants(F.demo_apartment(), {'rooms_enabled': ['kitchen']},
                                                                                vs0, fd0, inc0, liv, {}) == ({}, {}))

print('итог:', 'FAIL' if fails else 'OK')
sys.exit(1 if fails else 0)
