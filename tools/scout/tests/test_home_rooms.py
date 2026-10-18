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
      [r['id'] for r in rooms] == ['living', 'kitchen', 'bedroom-1', 'bedroom-2', 'bathroom-1', 'hall'])
check('готова только гостиная', [r['id'] for r in rooms if r['contentState'] == 'ready'] == ['living'])
check('варианты обставляют гостиную реестра', F.living_room_id() == 'living')

print('итог:', 'FAIL' if fails else 'OK')
sys.exit(1 if fails else 0)
