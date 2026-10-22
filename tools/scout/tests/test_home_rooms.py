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

# ОДНА ИСТИНА ПЛОЩАДЕЙ (T-20261022-04): реестр — комнаты + лоджия = площадь квартиры; схема плана — только геометрия с id реестра
import json  # noqa: E402
apt = F.demo_apartment()
flat = json.load(open(os.path.join(HERE, '..', 'flat215.json'), encoding='utf-8'))
check('площади реестра: комнаты + лоджия = площадь квартиры (73,7)',
      abs(sum(r['areaM2'] for r in rooms) + (apt.get('loggiaM2') or 0) - apt['areaM2']) <= 0.2 and apt['areaM2'] == 73.7)
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

print('итог:', 'FAIL' if fails else 'OK')
sys.exit(1 if fails else 0)
