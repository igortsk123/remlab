"""Скрытый банком сет не идёт в демо (conv-14, T-20261022-25/1). Без сети и базы.

Писатель банка (`bank_refresh.py`) кладёт в сет `bank_status`: `hidden` — ушёл товар ключевой роли (вариант без него не пройдёт
рубеж ядра), `degraded` — ушло остальное (демо снимет позицию и дозаполнит). Стенд проверяет:
  1) `hidden()` — только state=hidden; degraded и старый банк без поля — не скрыт;
  2) счёт банкеток ленты (`bench_pool`) не берёт товары скрытого сета, degraded — берёт;
  3) выбор вариантов (`fill_banks`) и лента замен из товаров сетов (`build`) пропускают скрытые — тем же `hidden()`.
    ~/venvs/scout/bin/python tools/scout/tests/test_demo_hidden.py"""
import ast
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

check('hidden: state=hidden — скрыт', F.hidden({'bank_status': {'state': 'hidden', 'gone': ['диван']}}))
check('degraded — не скрыт (дозаполнение, как прежде)', not F.hidden({'bank_status': {'state': 'degraded'}}))
check('старый банк без поля — не скрыт', not F.hidden({}) and not F.hidden({'bank_status': None}))


def kit(style, eid, status=None):
    s = {'style': style, 'items': {'банкетка': {'mid': 1, 'eid': eid, 'name': 'Банкетка'}}}
    if status:
        s['bank_status'] = {'state': status}
    return s


keep = (F.set_feed_row, sys.modules.get('catalog_media'))
sys.modules['catalog_media'] = types.SimpleNamespace(media=lambda mid, eid: {'state': 'ok'})
F.set_feed_row = lambda base, it, style: {'sid': f"{it['mid']}_{it['eid']}"}
try:
    got = F.bench_pool([kit('сканди', 'a'), kit('сканди', 'h', 'hidden'), kit('сканди', 'd', 'degraded')])
    check('банкетки ленты: товар скрытого сета не считается, degraded — считается', got.get('сканди') == {'1_a', '1_d'})
finally:
    F.set_feed_row = keep[0]
    if keep[1] is None:
        sys.modules.pop('catalog_media', None)
    else:
        sys.modules['catalog_media'] = keep[1]

SRC = open(os.path.join(HERE, '..', 'flat215_demo.py'), encoding='utf-8').read()
FUNCS = {n.name: ast.get_source_segment(SRC, n) for n in ast.parse(SRC).body if isinstance(n, ast.FunctionDef)}
check('выбор вариантов (fill_banks) пропускает скрытые', 'if hidden(st):' in FUNCS['fill_banks'])
check('лента замен из товаров сетов (build) пропускает скрытые', 'if hidden(s):' in FUNCS['build'])
check('правило одно: hidden() — единственная проверка bank_status', SRC.count("get('bank_status')") == 1)

print('итог:', 'FAIL' if fails else 'OK')
sys.exit(1 if fails else 0)
