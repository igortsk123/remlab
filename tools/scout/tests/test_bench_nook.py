"""«Уголок» с банкеткой — только если её есть чем заменить (владелец 20.10, demo-19 Г2). Без сети и базы.

В ленте замен сканди банкетка была одна — сама эта, кнопка «заменить» открывала выбор из неё же. Правило: банкеток в ленте
стиля меньше `nook_min_benches` (`rules/demo-swap.json`) — банкетку из набора снимаем ДО расстановки, солвер ставит обычную
столовую со стульями. Стенд проверяет:
  1) порог — из правил, не литерал; 2) одна банкетка в стиле — снята, стулья и стол на месте, строка журнала с причиной;
  3) две — «уголок» остаётся; 4) счёт по ленте: товары наборов и пула, снятый из продажи не считается, товар набора,
     который пул отобрал для другого стиля, считается и там, негодный пулу — нет; 5) набор без банкетки не трогаем.
    ~/venvs/scout/bin/python tools/scout/tests/test_bench_nook.py"""
import json
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
fails = 0


def check(name, cond):
    global fails
    print(('OK   ' if cond else 'FAIL ') + name)
    fails += 0 if cond else 1


import flat215_demo as F  # noqa: E402

rules = json.load(open(os.path.join(HERE, '..', 'rules', 'demo-swap.json'), encoding='utf-8'))
check('порог «уголка» — из rules/demo-swap.json', F.NOOK_MIN == rules['nook_min_benches'] == 2)


def bench(eid, name='Банкетка'):
    return {'mid': 1, 'eid': eid, 'name': name, 'w': 135, 'd': 45, 'h': 45, 'img': 'i', 'dining_bundle': 'edge_nook'}


def kit(style, b=None):
    items = {'стол обеденный': {'mid': 1, 'eid': 't', 'name': 'Стол'}, 'стул': {'mid': 1, 'eid': 'c', 'name': 'Стул', 'qty': 2}}
    if b:
        items['банкетка'] = b
    return {'style': style, 'items': items}


s = kit('сканди', bench('b1', 'Хоши-2'))
row = F.drop_lonely_nook(s, {'сканди': {'1_b1'}})
check('одна банкетка в ленте стиля — снята', 'банкетка' not in s['items'])
check('стол и стулья на месте', set(s['items']) == {'стол обеденный', 'стул'})
check('журнал: что снято, без замены, с причиной',
      row and row['role'] == 'банкетка' and row['from'] == 'Хоши-2' and row['from_sku'] == '1:b1' and row['to'] is None
      and '1 < 2' in row['reason'])
s = kit('лофт', bench('b2'))
check('две банкетки в ленте — уголок остаётся', F.drop_lonely_nook(s, {'лофт': {'1_b2', '1_b3'}}) is None and 'банкетка' in s['items'])
s = kit('джапанди', bench('b4'))
check('стиля нет в счёте (ни одной) — снята', F.drop_lonely_nook(s, {}) is not None and 'банкетка' not in s['items'])
s = kit('сканди')
check('набор без банкетки не трогаем', F.drop_lonely_nook(s, {}) is None and len(s['items']) == 2)

# счёт по ленте: проверки ленты и каталог подменены — правило отбора, а не данные
keep = (F.set_feed_row, F.pool_feed_check, sys.modules.get('catalog_media'))
gone = {'g1'}
sys.modules['catalog_media'] = types.SimpleNamespace(media=lambda mid, eid: {'state': 'gone' if eid in gone else 'ok'})
F.set_feed_row = lambda base, it, style: None if it.get('name') == 'нет модели' else {'sid': f"{it['mid']}_{it['eid']}"}
F.pool_feed_check = lambda p: '' if p.get('name') != 'барная' else 'unfit'
try:
    sets = [kit('сканди', bench('b1')), kit('сканди', bench('b1')), kit('лофт', bench('g1')),
            kit('лофт', bench('m1', 'нет модели')), kit('джапанди', bench('j1'))]
    pool = [{'role': 'банкетка', 'sid': '1_b1', 'style': 'джапанди', 'name': 'x'},       # товар набора сканди — и джапанди
            {'role': 'банкетка', 'sid': '1_p1', 'style': 'лофт', 'name': 'x'},
            {'role': 'банкетка', 'sid': '1_p2', 'style': 'лофт', 'name': 'барная'},      # пулу не годится
            {'role': 'пуф', 'sid': '1_p3', 'style': 'лофт', 'name': 'x'}]
    got = F.bench_pool(sets, pool)
    check('одна и та же банкетка в двух наборах — одна', got.get('сканди') == {'1_b1'})
    check('снятая из продажи и без модели не считаются, годная из пула — да', got.get('лофт') == {'1_p1'})
    check('товар набора, отобранный пулом для другого стиля, — и там', got.get('джапанди') == {'1_j1', '1_b1'})
    check('без пула — только наборы', F.bench_pool(sets).get('джапанди') == {'1_j1'})
finally:
    F.set_feed_row, F.pool_feed_check = keep[0], keep[1]
    if keep[2] is None:
        sys.modules.pop('catalog_media', None)
    else:
        sys.modules['catalog_media'] = keep[2]

print('итог:', 'FAIL' if fails else 'OK')
sys.exit(1 if fails else 0)
