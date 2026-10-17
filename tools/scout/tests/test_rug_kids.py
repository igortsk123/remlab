"""Детские ковры (demo-05, 17.10): слова из названий детских ковров — только для ковров и текстиля; ответ нейросети —
строго по форме; загрузчик снимает роль ковра по кэшу решения. Без сети и базы.
    ~/venvs/scout/bin/python tools/scout/tests/test_rug_kids.py"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
fails = 0


def check(name, cond):
    global fails
    print(('OK   ' if cond else 'FAIL ') + name)
    fails += 0 if cond else 1


import category_map as C  # noqa: E402

check('ковёр «Милна Фанни» — детский по названию', C.is_kids('Ковер divan.ru Милна Фанни Серый 160x230', 'ковёр'))
check('диван серии «Тут Рядом Космос» — не детский', not C.is_kids('Диван прямой divan.ru Тут Рядом Космос Рогожка Серый', 'диван'))
check('часы «Карта мира» — не детские', not C.is_kids('Часы настенные JJT Карта мира 29х29 см', 'часы'))
check('ковровая дорожка — не детская', not C.is_kids('Ковровая дорожка Бербер 80x300', 'ковёр'))
check('прежний отсев по названию работает для всех ролей', C.is_kids('Стул детский Котёнок', 'стул'))

os.environ['RUG_KIDS_CACHE'] = os.path.join(tempfile.mkdtemp(), 'rug-kids.json')
import rug_kids as R  # noqa: E402

check('ответ по форме разбирается', R.parse('{"kids": true, "why": "надпись let\'s play"}') == {'kids': True, 'motifs': ["надпись let's play"]})
for bad in ('```json {"kids": false, "why": "x"}```', '{"kids": "false", "why": "x"}', '{"kids": false}', '{"kids": false, "why": "x", "c": 1}'):
    try:
        R.parse(bad)
        check(f'не по форме — исключение: {bad[:30]}', False)
    except Exception:  # noqa: BLE001
        check(f'не по форме — исключение: {bad[:30]}', True)

import load3  # noqa: E402

url = 'https://example.com/rug-play.jpg'
json.dump({load3.image_hash(url): {'kids': True, 'why': 'надпись'}}, open(os.environ['RUG_KIDS_CACHE'], 'w'))
load3._RUG_KIDS = None
o = {'mid': 1, 'cid': 7, 'name': 'Ковер Обычный 160x230', 'pic': url, 'pic_hd': None, 'params': {}, 'price': 100}
out = load3.assign(dict(o), {(1, '7'): 'ковёр'}, set())
check('загрузчик: детский по картинке ковёр — без роли, но строка принята', out['role'] is None and out['accepted'] and out.get('kids_visual'))
out2 = load3.assign(dict(o, pic='https://example.com/plain.jpg'), {(1, '7'): 'ковёр'}, set())
check('загрузчик: обычный ковёр — с ролью', out2['role'] == 'ковёр')
print(f'{"всё зелёное" if not fails else f"красных: {fails}"}')
sys.exit(1 if fails else 0)
