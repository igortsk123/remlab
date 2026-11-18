"""Ценовые ступени роли в витрине /demo (T-20261118-61/3, план price-segments-01): правило границ, штамп `price_segment` в лентах,
выборка фото-каталога комнаты, диапазоны для страницы. Без сети и базы (цены семейств подменены).
    ~/venvs/scout/bin/python tools/scout/tests/test_price_segments.py"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
sys.path.insert(0, os.path.join(HERE, '..', '..', '..', 'services', 'planner-solver'))
fails = 0


def check(name, cond, info=''):
    global fails
    print(('OK   ' if cond else 'FAIL ') + name + (f' — {info}' if info and not cond else ''))
    fails += 0 if cond else 1


import build_stamp as BS  # noqa: E402
import flat215_demo as F  # noqa: E402
import price_tiers as PT  # noqa: E402

# 1) файл правила: у каждой роли границы по возрастанию, метод из словаря, «свои терцили» — только при достаточной выборке
R = json.load(open(PT.RULES_PATH, encoding='utf-8'))
CFG = json.load(open(os.path.join(HERE, '..', 'rules', 'price-segments-config.json'), encoding='utf-8'))
roles = R['roles']
check('правило: версия, поле цены и непустые роли', bool(R.get('version')) and 'price_shown_rub' in R.get('price_field', '') and len(roles) >= 30)
check('границы каждой роли: 0 < B1 < B2', all(not e['boundaries_rub'] or 0 < e['boundaries_rub'][0] < e['boundaries_rub'][1] for e in roles.values()))
check('метод из словаря local/shrink/prior/previous/manual/none',
      {e['method'] for e in roles.values()} <= {'local', 'shrink', 'prior', 'previous', 'manual', 'none'})
check('«local» — только при N ≥ 30 и ≥ 10 разных цен (правило Codex)',
      all(e['families'] >= CFG['min_local_families'] and e['distinct_prices'] >= CFG['min_local_distinct_prices']
          for e in roles.values() if e['method'] == 'local'))
check('«none» — только без границ, остальные с границами', all((e['method'] == 'none') == (not e['boundaries_rub']) for e in roles.values()))
check('правило читает сборка витрины (входы build_stamp) — смена границ пересоберёт /demo',
      any('price-segments.json' in str(x) for x in BS.DEMO_INPUTS))
check('те же границы — ровно одна ступень на цену, хвосты в крайних ступенях',
      all(PT.tier_of(r, 1, R) == 'lo' and PT.tier_of(r, 10 ** 9, R) == 'hi' for r, e in roles.items() if e['boundaries_rub']))

# 2) выборка фото-каталога: по ступеням, без перекрытий, годные с моделью первыми; границы и цены семейств — подменены
FAKE = {'roles': {'кровать': {'boundaries_rub': [30000, 60000], 'families': 90, 'method': 'local'},
                  'без-границ': {'boundaries_rub': None, 'families': 3, 'method': 'none'}}, 'version': 'test'}
_old_c, _old_fp = dict(PT._CACHE), PT.family_prices_cached
PT._CACHE[PT.RULES_PATH] = FAKE
PT.family_prices_cached = lambda *a, **k: {}
try:
    reps = [{'sid': f'9:{i}', 'name': f'Кровать М{i} 160', 'shop': 's', 'url': 'u', 'img': 'i', 'price': 10000 + i * 600, 'w': 160,
             'meshy': 1 if i % 3 == 0 else 0} for i in range(100)]
    got = F._catalog_pick('кровать', reps, 10)
    by = {}
    for x in got:
        by.setdefault(x['price_segment'], []).append(x)
    check('каталог: по 10 на КАЖДУЮ ступень, три ступени', {k: len(v) for k, v in by.items()} == {'lo': 10, 'mid': 10, 'hi': 10}, str({k: len(v) for k, v in by.items()}))
    check('каталог: каждая цена — в своей ступени по границам [30000, 60000]',
          all(PT.tier_of('кровать', x['price'], FAKE) == x['price_segment'] for x in got))
    check('каталог: служебное поле meshy в данные не идёт', all('meshy' not in x for x in got))
    check('каталог: ступень без модели добирается квотой, годные — первыми',
          sum(1 for x in by['hi'] if int(x['sid'].split(':')[1]) % 3 == 0) >= min(10, sum(1 for r in reps if r['price'] >= 60000 and r['meshy'])))
    check('каталог: порядок по цене', [x['price'] for x in got] == sorted(x['price'] for x in got))
    nb = F._catalog_pick('без-границ', reps[:25], 10)
    check('каталог: роль без границ — одна группа до квоты, без price_segment', len(nb) == 10 and all('price_segment' not in x for x in nb))

    # 3) штамп лент: ступень по цене СЕМЕЙСТВА (не цвета), комнаты — по роли после двоеточия, роль без границ — без метки
    PT.family_prices_cached = lambda *a, **k: {'кровать': {'m:M_1': 90000}}
    feeds = {'кровать': [{'sid': 'x_1', 'msid': 'M_1', 'name': 'Кровать Альфа', 'w': 160, 'price': 10000}],
             'bedroom:кровать': [{'sid': 'x_2', 'msid': 'M_2', 'name': 'Кровать Бета', 'w': 160, 'price': 45000}],
             'без-границ': [{'sid': 'x_3', 'msid': 'M_3', 'name': 'Что-то', 'w': 50, 'price': 5000}]}
    rep = F.stamp_price_segments(feeds)
    check('штамп: цена семейства 90 000 → premium, хоть цвет стоит 10 000', feeds['кровать'][0].get('price_segment') == 'hi')
    check('штамп: ключ комнаты «bedroom:кровать» → роль «кровать», цена карточки 45 000 → mid', feeds['bedroom:кровать'][0].get('price_segment') == 'mid')
    check('штамп: роль без границ — поля нет, в отчёте «—»', 'price_segment' not in feeds['без-границ'][0] and rep['без-границ'] == {'—': 1})
    # 4) диапазоны для страницы
    rg = F._price_segment_ranges()
    check('диапазоны страницы: версия, подписи RU/EN и границы роли', rg.get('version') == 'test' and rg['roles']['кровать']['boundaries_rub'] == [30000, 60000]
          and set(rg['labels']['ru']) == {'lo', 'mid', 'hi'} and set(rg['labels']['en']) == {'lo', 'mid', 'hi'})
    PT._CACHE[PT.RULES_PATH] = {}
    check('нет правила — штампа и диапазонов нет (витрина как раньше)', F._price_segment_ranges() == {} and F.stamp_price_segments({'кровать': [{'sid': 'a_b'}]}) == {})
finally:
    PT._CACHE.clear()
    PT._CACHE.update(_old_c)
    PT.family_prices_cached = _old_fp

print(f'test_price_segments: ошибок {fails}')
sys.exit(1 if fails else 0)
