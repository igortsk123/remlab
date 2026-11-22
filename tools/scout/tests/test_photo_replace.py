"""Предмет варианта без скачанной картинки заменяется ближайшим из ленты с картинкой (T-20261119-115/3). Без сети, базы и моделей.
    ~/venvs/scout/bin/python tools/scout/tests/test_photo_replace.py"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
import photo_replace as PR  # noqa: E402

fails = 0


def check(name, cond, info=''):
    global fails
    print(('OK   ' if cond else 'FAIL ') + name + (f' — {info}' if info and not cond else ''))
    fails += 0 if cond else 1


KEY = lambda room, role: role if room == 'living' else f'{room}:{role}'   # noqa: E731
GAP = 12


def feed_row(sid, w, d, price=1000, img='img/x.jpg', styles=('лофт',), **kw):
    return dict({'sid': sid, 'msid': sid, 'name': 'р-' + sid, 'w': w, 'd': d, 'h': 1, 'price': price, 'img': img, 'styles': list(styles),
                 'url': 'u', 'shop': 's'}, **kw)


def item(role, w, d, sid='old', img=None, **kw):
    return dict({'role': role, 'w': w, 'd': d, 'sku': {'name': 'старый', 'sid': sid, 'msid': sid, 'img': img, 'w': w, 'd': d, 'price': 1, 'dia': None}}, **kw)


def run(items, feeds, style='лофт', room='living'):
    v = {'id': 'v1', 'style': style, 'room_id': room, 'items': items}
    return v, PR.replace_no_photo([v], feeds, KEY, GAP)


# 1) ковёр без картинки → ближайший по габаритам (длинная с длинной), с картинкой, того же стиля; место и размеры предмета те же
v, r = run([item('ковёр', 230, 160)], {'ковёр': [feed_row('a', 200, 140), feed_row('b', 235, 160, price=500), feed_row('c', 230, 160, price=900)]})
sk = v['items'][0]['sku']
check('ковёр: взят ближайший по размеру (c — точный)', sk['sid'] == 'c' and sk['img'] == 'img/x.jpg', sk)
check('ковёр: размеры и место предмета не тронуты', (v['items'][0]['w'], v['items'][0]['d']) == (230, 160))
check('счётчик: без фото 1, заменено 1', (r['without'], r['replaced']) == (1, 1) and len(r['replaced_rows']) == 1, r)
check('набор ключей sku сохранён (dia остался)', 'dia' in sk and sk['msid'] == 'c', sk)

# 2) равный зазор → дешевле
v, r = run([item('ковёр', 230, 160)], {'ковёр': [feed_row('p', 236, 160, price=900), feed_row('q', 224, 160, price=400)]})
check('равный зазор — дешевле', v['items'][0]['sku']['sid'] == 'q')

# 3) габариты вне допуска → не заменяем, предмет остаётся с плашкой, строка в отчёте
v, r = run([item('ковёр', 230, 160)], {'ковёр': [feed_row('far', 300, 200)]})
check('вне допуска: остался без картинки', not v['items'][0]['sku']['img'] and r['replaced'] == 0 and len(r['left_rows']) == 1, r)

# 4) чужой стиль, без картинки в ленте, без модели, тот же товар — не берём
v, r = run([item('ковёр', 230, 160, sid='old')], {'ковёр': [feed_row('s', 230, 160, styles=('сканди',)), feed_row('n', 230, 160, img=None),
                                                            feed_row('m', 230, 160, msid=None), feed_row('old', 230, 160)]})
check('чужой стиль/без картинки/без модели/тот же — не годятся', r['replaced'] == 0, r)

# 5) ковёр не короче дивана расстановки
v, r = run([item('диван', 200, 90, sid='dv', img='img/d.jpg'), item('ковёр', 195, 120)], {'ковёр': [feed_row('short', 190, 120), feed_row('long', 205, 120)]})
check('ковёр: длинная сторона не короче дивана', v['items'][1]['sku']['sid'] == 'long', v['items'][1]['sku'])

# 6) диван: угловой только на угловое, прямой — на прямое
v, r = run([item('диван', 200, 90, corner=True, corner_left=True)], {'диван': [feed_row('st', 200, 90), feed_row('cr', 205, 92, corner=True, corner_left=False), feed_row('cl', 206, 92, corner=True, corner_left=True)]})
check('диван: форма места (угловой слева)', v['items'][0]['sku']['sid'] == 'cl', v['items'][0]['sku'])

# 7) лента комнаты — под своим ключом «<тип>:<роль>», номер комнаты отбрасывается
check('тип комнаты: bedroom-2 → bedroom, пусто → living', PR.room_type('bedroom-2') == 'bedroom' and PR.room_type(None) == 'living' and PR.room_type('living') == 'living')
v, r = run([item('ковёр', 300, 200)], {'ковёр': [feed_row('liv', 300, 200)], 'bedroom:ковёр': [feed_row('bed', 300, 200)]}, room='bedroom-2')
check('ковёр спальни берёт ленту спальни', v['items'][0]['sku']['sid'] == 'bed', v['items'][0]['sku'])

# 8) уже с картинкой — не трогаем; другой предмет варианта с этим же товаром — не берём (дубль)
v, r = run([item('ковёр', 230, 160, sid='keep', img='img/k.jpg')], {'ковёр': [feed_row('z', 230, 160)]})
check('с картинкой — не трогаем', v['items'][0]['sku']['sid'] == 'keep' and r['without'] == 0)
v, r = run([item('ковёр', 230, 160), item('ковёр 2', 230, 160, sid='dup', img='img/d.jpg')], {'ковёр': [feed_row('dup', 230, 160, price=1), feed_row('ok', 232, 160)]})
check('товар, уже стоящий в варианте, не берём', v['items'][0]['sku']['sid'] == 'ok', v['items'][0]['sku'])

# 9) правило данных на месте
import json  # noqa: E402
rule = json.load(open(os.path.join(HERE, '..', 'rules', 'demo-swap.json'), encoding='utf-8')).get('no_photo_replace') or {}
check('rules/demo-swap.json: no_photo_replace.max_size_gap_cm', isinstance(rule.get('max_size_gap_cm'), (int, float)) and rule['max_size_gap_cm'] > 0, rule)

print(f'\n{"все проверки прошли" if not fails else "ПАДЕНИЙ: " + str(fails)}')
sys.exit(1 if fails else 0)
