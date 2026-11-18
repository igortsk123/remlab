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

# 1б) аудит выбросов (T-61/4): правила — в конфиге, с причиной; комплектующие не входят в границы, дорогое по цене не режется
import price_outliers as PO  # noqa: E402
import price_segments_build as PB  # noqa: E402
OC = CFG.get('outliers') or {}
check('конфиг аудита: термины названий, статистика и магазины с причиной',
      bool(OC.get('terms')) and OC.get('mad_k') == 5 and OC.get('variant_ratio') == 3 and all(isinstance(v, str) and len(v) > 20 for v in (OC.get('exclude_shops') or {}).values()))
rows = [('шкаф', '1', str(i), '', f'Шкаф Модель{i} 100x50', 100.0, 20000.0 + i * 1000) for i in range(40)]
junk = [('шкаф', '1', f'j{i}', '', f'INTEGRO Направляющая верхняя {i}', 100.0, 20.0 + i) for i in range(30)] + \
       [('шкаф', '7', f'k{i}', '', f'Крепёж {i}', 100.0, 40.0 + i) for i in range(5)]
cfg_t = dict(CFG, outliers=dict(OC, exclude_shops={'7': 'тест: магазин комплектующих'}))
kept_t, rep_t = PO.audit(rows + junk, cfg_t)
check('аудит: комплектующие (по названию и по магазину) исключены, мебель на месте', len(kept_t) == 40 and rep_t['n_in'] - rep_t['n_kept'] == 35, str(rep_t['n_kept']))
check('аудит: у каждого исключения есть причина', all(w.startswith(('component_name:', 'component_shop:')) for d in rep_t['excluded'].values() for w in d))
b_all = PB.build(PT.families_from(rows + junk), CFG)['roles']['шкаф']['boundaries_rub']
b_kept = PB.build(PT.families_from(kept_t), CFG)['roles']['шкаф']['boundaries_rub']
check('границы без комплектующих — терцили мебели (13 цен ниже B1, 27 ниже B2), с ними — сдвинуты', b_kept == [33000, 47000] and b_all != b_kept, f'{b_all} → {b_kept}')
check('сравнение было→стало показывает изменённую роль', any(l.startswith('шкаф') for l in PB.compare({'roles': {'шкаф': {'families': 75, 'boundaries_rub': b_all, 'method': 'local'}}},
                                                                                                    {'roles': {'шкаф': {'families': 40, 'boundaries_rub': b_kept, 'method': 'local'}}})))
dear = rows + [('шкаф', '1', 'd', '', 'Шкаф Дизайнерский 300', 100.0, 3_000_000.0)]
check('дорогое по цене не исключается (только флаг)', len(PO.audit(dear, cfg_t)[0]) == 41)

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

# 5) банк наборов (T-20261118-61/6): ОДИН resolver ступени; 4 дубля перцентилей и пересчёт внутри стиля — убраны; флаг по умолчанию выкл
import re  # noqa: E402
SCOUT = os.path.join(HERE, '..')
src = {n: open(os.path.join(SCOUT, n), encoding='utf-8').read() for n in ('candidates.py', 'compose.py', 'compose2.py', 'compose_common.py', 'compose_bedroom.py', 'compose_hall.py')}
check('банк: перцентили p05–45/35–80/70–97 — только в price_tiers (resolver), в потребителях их нет',
      not any(re.search(r'\.35\s*,\s*\.80|0\.35,\s*0\.80|pc\(\s*0?\.97', t) for t in src.values()) and 'LEGACY_Q' in open(PT.__file__, encoding='utf-8').read())
check('банк: все потребители зовут price_tiers.tier_band, `tier_range` из compose_common убран',
      all('tier_band(' in src[n] for n in ('candidates.py', 'compose.py', 'compose2.py', 'compose_bedroom.py', 'compose_hall.py')) and 'def tier_range' not in src['compose_common.py']
      and not any('tier_range' in t for t in src.values()))
check('банк: пересчёт квантилей внутри стиля — только в прежнем режиме (за bank_segments_on)',
      all(re.search(r'if out or not styled or PT\.bank_segments_on\(\)', src[n]) for n in ('compose_bedroom.py', 'compose_hall.py')))
check('банк: флаг bank_use_segments в конфиге, по умолчанию выкл (включает директор по отчёту тени)', CFG.get('bank_use_segments') is False and CFG.get('_bank_use_segments_why'))
_env = os.environ.pop('BANK_PRICE_SEGMENTS', None)
try:
    check('банк: без env флаг читается из конфига (выкл) — прежний режим', PT.bank_segments_on() is False)
    os.environ['BANK_PRICE_SEGMENTS'] = '1'
    check('банк: env BANK_PRICE_SEGMENTS=1 включает ступени из правила', PT.bank_segments_on() is True)
    FR = {'version': 't', 'roles': {'диван': {'boundaries_rub': [50000, 90000], 'families': 100, 'method': 'local'}}}
    bands = {t: PT.tier_band('диван', t, [1, 2, 3], rules=FR) for t in PT.BANK_TIERS}
    check('банк: ступени из правила не пересекаются и закрывают ось цен',
          bands['эконом'][1] < bands['комфорт'][0] and bands['комфорт'][1] < bands['премиум'][0] and bands['премиум'][1] >= 10 ** 9
          and all(sum(lo <= x <= hi for lo, hi in bands.values()) == 1 for x in (1, 49999, 50000, 89999, 90000, 10 ** 6)))
    os.environ['BANK_PRICE_SEGMENTS'] = '0'
    check('банк: env=0 — прежние квантили (перекрываются: комфорт 35–80 % и премиум 70–97 % по ценам роли)',
          PT.tier_band('диван', 'комфорт', list(range(100)), rules=FR) == (35, 80) and PT.tier_band('диван', 'премиум', list(range(100)), rules=FR) == (70, 97))
finally:
    os.environ.pop('BANK_PRICE_SEGMENTS', None)
    if _env is not None:
        os.environ['BANK_PRICE_SEGMENTS'] = _env

print(f'test_price_segments: ошибок {fails}')
sys.exit(1 if fails else 0)
