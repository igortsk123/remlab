#!/usr/bin/env python3
"""Цвет по стилю и роли в ГОСТИНОЙ (план style-color-01, шаг 2а, T-20261107-25/2): тот же оценщик `compose_common.color_eval`
у сборщика гостиной (`compose_common.color_split` → `compose2.pick2`), у дозаполнения опубликованных вариантов
(`demo_fill.fill_set` → `color_need`) и у лент замен (`demo_fill.lane_color` → страница `feedFor`). Без базы и сети.

ЗАЧЕМ. На витрине 07.11 минимализм стоял со стеллажом «Кейн Серо-зеленый» (по правилам цвет у крупной мебели минимализма
запрещён), джапанди — с парой оливковых стульев «Марти-2» (нежелательно). Банк гостиной держит ячейки между ночами
(`bank_keep`), поэтому одной правки сборщика витрине мало: замена идёт тем же путём, что «нет модели».
  • регрессии: «Кейн серо-зелёный» минимализма не берётся и в витрине заменяется; «Марти-2 олива» джапанди ниже графитового
    и пара стульев меняется ОДНОЙ заменой;
  • карта ролей гостиной (тв-тумба, столик, стол обеденный → корпусная, подушка → мягкое) не меняет 4 остальных варианта
    витрины (их состав 07.11 — ниже);
  • лента: forbidden снимает стиль с товара, discouraged — пометка `color_low`, товар варианта не трогаем.

  python3 tools/scout/tests/test_living_color.py
"""
from __future__ import annotations

import os
import sys

SCOUT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SCOUT)

import compose_common as CC  # noqa: E402
import demo_fill as DF  # noqa: E402

bad = 0


def ok(name, cond):
    global bad
    print(('OK   ' if cond else 'FAIL ') + name)
    bad += not cond


P = CC.color_policy()
KANE = 'Стеллаж divan.ru Кейн 6-75x75 Серо-зеленый'
WHITE = 'Стеллаж divan.ru Амберсон 80x118 Белый'
OLIVE = 'Стул divan.ru Марти-2 Велюр Оливковый/Натуральный'
GRAPHITE = 'Стул divan.ru Данмор Рогожка Графитовый/Натуральный'

# --- карта ролей гостиной
grp = lambda role: CC.color_group(role, P)  # noqa: E731
ok('карта ролей: тв-тумба, столик, стол обеденный — корпусная; подушка — мягкое',
   [grp('тв-тумба'), grp('столик'), grp('стол обеденный'), grp('подушка'), grp('подушка 2')]
   == ['large_casework'] * 3 + ['soft_textile'] * 2)

# --- сборщик гостиной: ярус до меша
it = lambda name, **k: {'name': name, 'cls': k.get('cls'), 'rgb': k.get('rgb'), 'price': 1000, 'mid': '1', 'eid': name}  # noqa: E731
g = CC.color_split([(9.0, it(KANE)), (5.0, it(WHITE))], 'стеллаж', 'минимализм', {}, P)
ok('минимализм: стеллаж «Кейн Серо-зеленый» (forbidden) в сборке гостиной не кандидат даже с лучшим баллом',
   [x[1]['name'] for grp_ in g for x in grp_] == [WHITE])
g = CC.color_split([(9.0, it(OLIVE)), (4.0, it(GRAPHITE))], 'стул', 'джапанди', {}, P)
ok('джапанди: «Марти-2 олива» (discouraged) ниже графитового при лучшем балле — разные ярусы, меш внутри яруса',
   [[x[1]['name'] for x in grp_] for grp_ in g] == [[GRAPHITE], [OLIVE]])
g = CC.color_split([(9.0, it(OLIVE)), (4.0, it(GRAPHITE))], 'подушка', 'джапанди', {}, P)
ok('не крупная роль (подушка) — одна группа, порядок балла прежний (подушки пары — шаг 2б)',
   [[x[1]['name'] for x in grp_] for grp_ in g] == [[OLIVE, GRAPHITE]])
ok('стиль без правил (сборка без стиля) — одна группа', len(CC.color_split([(1, it(KANE)), (2, it(WHITE))], 'стеллаж', None, {}, P)) == 1)

# --- витрина: замена по цвету в опубликованном варианте
pool = [{'mid': '9', 'eid': 'white', 'role': 'стеллаж', 'style': 'минимализм', 'name': WHITE, 'w': 80, 'd': 35, 'price': 11990},
        {'mid': '9', 'eid': 'green2', 'role': 'стеллаж', 'style': 'минимализм', 'name': 'Стеллаж Талдом 65x80 Серо-зеленый', 'w': 75,
         'd': 35, 'price': 10990},
        {'mid': '9', 'eid': 'graph', 'role': 'стул', 'style': 'джапанди', 'name': GRAPHITE, 'w': 50, 'd': 55, 'price': 7992},
        {'mid': '9', 'eid': 'olive2', 'role': 'стул', 'style': 'джапанди', 'name': 'Стул Фирес Рогожка Оливковый', 'w': 50, 'd': 55,
         'price': 8990}]
media = lambda mid, eid: {'state': 'available'}  # noqa: E731
has_mesh = lambda x: True  # noqa: E731
gate = lambda role, c, s, chosen: True  # noqa: E731
card = lambda c, old: {'mid': c['mid'], 'eid': c['eid'], 'name': c['name'], 'w': c['w'], 'price': c.get('price')}  # noqa: E731
s = {'style': 'минимализм', 'items': {'диван': {'mid': '1', 'eid': 'sofa', 'name': 'Диван Риббл-1 Букле Графитовый', 'w': 200},
                                      'стеллаж': {'mid': '1', 'eid': 'kane', 'name': KANE, 'w': 75, 'price': 10990}}}
j = [x for x in DF.fill_set(s, pool, gate, card, media, has_mesh) if x['reason'] != 'нет товара']   # ядро без дивана и пр. — не про цвет
ok('витрина минимализм: «Кейн Серо-зеленый» заменён нейтральным (серо-зелёный «Талдом» ближе по ширине — пропущен), журнал «цвет»',
   s['items']['стеллаж']['name'] == WHITE and [x['role'] for x in j] == ['стеллаж'] and j[0]['reason'].startswith('цвет не в стиле'))
ok('…годный диван не тронут', s['items']['диван']['name'] == 'Диван Риббл-1 Букле Графитовый')
s = {'style': 'джапанди', 'items': {'стул': {'mid': '1', 'eid': 'marti', 'name': OLIVE, 'w': 50, 'price': 8990},
                                    'стул 2': {'mid': '1', 'eid': 'marti', 'name': OLIVE, 'w': 50, 'price': 8990}}}
j = [x for x in DF.fill_set(s, pool, gate, card, media, has_mesh) if x['reason'] != 'нет товара']
ok('витрина джапанди: пара оливковых «Марти-2» → оба графитовые (одна замена на пару, оливковый «Фирес» пропущен)',
   [s['items'][r]['name'] for r in ('стул', 'стул 2')] == [GRAPHITE, GRAPHITE] and len(j) == 2)
s = {'style': 'минимализм', 'items': {'стеллаж': {'mid': '1', 'eid': 'kane', 'name': KANE, 'w': 75}}}
j = [x for x in DF.fill_set(s, [p for p in pool if p['eid'] == 'green2'], gate, card, media, has_mesh) if x['reason'] != 'нет товара']
ok('заменить нечем (в пуле только цветные) — вещь остаётся, журнал пуст: цвет дыры не делает',
   s['items']['стеллаж']['name'] == KANE and j == [])

# --- сухой прогон T-25/2: цвет и в ОБЫЧНОЙ замене, высота при замене по цвету, отсечка forbidden
media2 = lambda mid, eid: {'state': 'gone' if eid == 'gone' else 'available'}  # noqa: E731
s = {'style': 'джапанди', 'items': {'стул': {'mid': '1', 'eid': 'gone', 'name': 'Стул TC Diamante Коричневый/Белый', 'w': 50,
                                            'price': 8990}}}
j = [x for x in DF.fill_set(s, pool, gate, card, media2, has_mesh) if x['reason'] != 'нет товара']
ok('снятый с продажи стул джапанди заменяется графитовым, а не оливковым «Фирес» (тот ближе по цене): discouraged — после годных',
   s['items']['стул']['name'] == GRAPHITE and len(j) == 1 and not DF.is_colour_swap(j[0]))
OAK = 'Стеллаж divan.ru Талдом 65x80 Дуб Барбера'
pool_h = [dict(pool[0], h=118), {'mid': '9', 'eid': 'oak', 'role': 'стеллаж', 'style': 'минимализм', 'name': OAK, 'w': 65, 'd': 35,
                                 'h': 80, 'price': 9990}]
s = {'style': 'минимализм', 'items': {'стеллаж': {'mid': '1', 'eid': 'kane', 'name': KANE, 'w': 75, 'h': 75, 'price': 10990}}}
j = DF.fill_set(s, pool_h, gate, card, media, has_mesh)
ok('замена по цвету — сперва ближе по высоте: стеллаж 75 см (под окном) → «Талдом» 80 см, не «Амберсон» 118 см (ближе по ширине)',
   s['items']['стеллаж']['name'] == OAK and any(DF.is_colour_swap(x) for x in j))
s = {'style': 'минимализм', 'items': {'стеллаж': {'mid': '1', 'eid': 'kane', 'name': KANE, 'w': 75, 'h': 75}}}
j = [x for x in DF.fill_set(s, pool_h, gate, card, media, has_mesh, colour_swap=False) if x['reason'] != 'нет товара']
ok('colour_swap=False (запасной вариант choose_banks) — замен по цвету нет, вещь та же', s['items']['стеллаж']['name'] == KANE and j == [])
BURG = 'ТВ-тумба divan.ru Блест 151x61 Бургундский'
cs = [it(KANE), it(WHITE)]
ok('color_order: forbidden не ядра — отсечка', [c['name'] for c in DF.color_order('стеллаж', cs, 'минимализм')] == [WHITE])
cs = [it(BURG), it('ТВ-тумба divan.ru Кимбол 140x45 Белый')]
ok('color_order: forbidden у ядра (тв-тумба) — не отсечка, а в конец (дыра в ядре снимает вариант)',
   [c['name'] for c in DF.color_order('тв-тумба', cs, 'минимализм', core=True)] == ['ТВ-тумба divan.ru Кимбол 140x45 Белый', BURG])
cs = [it('Стул Фирес Рогожка Оливковый'), it('Стул Ламекс-1 Рогожка Серый/Черный'), it(GRAPHITE)]
ok('color_order: годные (preferred и allowed) — прежний порядок, discouraged после',
   [c['name'] for c in DF.color_order('стул', cs, 'джапанди')] == ['Стул Ламекс-1 Рогожка Серый/Черный', GRAPHITE,
                                                                   'Стул Фирес Рогожка Оливковый'])
ok('color_order: не крупная роль — как было', DF.color_order('подушка', cs, 'джапанди') == cs)

# --- 4 остальных варианта витрины 07.11 (сборка rehearsal-0711, /test/style-fallback-23/): ни одной замены по цвету
SHOWN = {
    'сканди': ['диван|Диван прямой divan.ru Викс Рогожка Серый', 'столик|Журнальный стол divan.ru Хостер-1 Темно-бежевая керамика/Орех',
               'пуф|Пуф divan.ru Кофи Велюр Светло-серый', 'ковёр|Ковер divan.ru Фонте 160x230',
               'тв-тумба|ТВ-тумба divan.ru Теджонс 139x62 Ромб Латте', 'стол обеденный|Кухонный стол divan.ru Таргет 90 Черный/Натуральный',
               'стул|Стул divan.ru Корнер Велюр Бежевый/Натуральный', 'стул 2|Стул divan.ru Корнер Велюр Бежевый/Натуральный'],
    'современный': ['диван|Диван прямой divan.ru Сорен Велюр Коричневый', 'столик|Журнальный стол divan.ru Саймон Ясень Черный',
                    'ковёр|Ковер divan.ru Руффи Вью 160x230', 'тв-тумба|ТВ-тумба divan.ru Кимбол 140x45 Белый',
                    'стол обеденный|Кухонный стол divan.ru Хилл 85 Древесный черный', 'стул|Стул divan.ru Ламекс-1 Рогожка Серый/Черный',
                    'стул 2|Стул divan.ru Ламекс-1 Рогожка Серый/Черный'],
    'лофт': ['диван|Диван Босс двухместный велюр Роял синий', 'столик|Журнальный стол divan.ru Харис Черный',
             'ковёр|Ковер divan.ru Мирна 160x230', 'тв-тумба|ТВ-тумба divan.ru Харис 140x41 Черный',
             'стол обеденный|Кухонный стол divan.ru Мелтон 75x95 Ореx/Черный', 'стул|Стул divan.ru Торви Рогожка Серый/Черный',
             'стул 2|Стул divan.ru Торви Рогожка Серый/Черный'],
    'неоклассика': ['диван|Диван модульный divan.ru Брера 2 Букле Бежевый',
                    'столик|Журнальный стол divan.ru Вегар-1 Древесный натуральный/Черный', 'ковёр|Ковер divan.ru Котри Серый 160x230',
                    'тв-тумба|ТВ-тумба divan.ru Харис 140x41 Черный', 'стол обеденный|Кухонный стол divan.ru Тюлип 90 Черный',
                    'стул|Стул Glasar Сакура 48х46х96 см', 'стул 2|Стул Glasar Сакура 48х46х96 см',
                    'стеллаж|Стеллаж divan.ru Дигарс 83x220 Графитовый'],
}
need = [f'{st}/{x}' for st, xs in SHOWN.items() for x in xs if DF.color_need(x.split('|')[0], {'name': x.split('|')[1]}, st)]
ok('4 остальных варианта (сканди, современный, лофт, неоклассика): по цвету ничего не меняется', not need)
if need:
    print('   ', need)

# --- лента замен
lane = [{'sid': 'kane', 'name': KANE, 'style': 'минимализм', 'styles': ['минимализм', 'сканди']},
        {'sid': 'white', 'name': WHITE, 'style': 'минимализм', 'styles': ['минимализм']},
        {'sid': 'only', 'name': 'Стеллаж Кейн 4-75x75 Оливковый', 'style': 'минимализм', 'styles': ['минимализм']},
        {'sid': 'own', 'name': 'Стеллаж Талдом 65x80 Серо-зеленый', 'style': 'минимализм', 'styles': ['минимализм']}]
out, cut, low = DF.lane_color('стеллаж', lane, {('минимализм', 'own')})
ok('лента: forbidden снимает стиль (Кейн остаётся в сканди), товар без стилей уходит, товар варианта не трогаем',
   [(p['sid'], p.get('styles')) for p in out] == [('kane', ['сканди']), ('white', ['минимализм']),
                                                    ('own', ['минимализм'])] and cut == 2 and low == 0)
lane = [{'sid': 'olive', 'name': OLIVE, 'style': 'джапанди', 'styles': ['джапанди', 'сканди']},
        {'sid': 'graph', 'name': GRAPHITE, 'style': 'джапанди'}]
out, cut, low = DF.lane_color('стул', lane)
ok('лента: discouraged — пометка `color_low` своего стиля, без отсева; годный товар — тот же объект',
   out[0].get('color_low') == ['джапанди'] and out[0]['styles'] == ['джапанди', 'сканди'] and out[1] is lane[1] and (cut, low) == (0, 1))
# --- шаг 2б (T-20261107-25/3): подушки и шторы — тем же ярусом soft_textile
ALES = 'Комплект штор Togas Алессио бирюзовые 260x275 см 2 предмета'
BLUE_P = 'Подушка Линкс Велюр Синий'
lane = [{'sid': 'ales', 'name': ALES, 'style': 'сканди', 'styles': ['сканди', 'современный']},
        {'sid': 'mint', 'name': 'Комплект штор Togas Роверо мятный 280x275 см', 'style': 'минимализм', 'styles': ['минимализм']},
        {'sid': 'beige', 'name': 'Комплект штор Togas Алессио бежевые 260x300 см', 'style': 'сканди', 'styles': ['сканди', 'джапанди']}]
out, cut, low = DF.lane_color('шторы', lane)
ok('лента штор: бирюзовые (яркое) снимаются со сканди, у современного остаются; мятные минимализма — в конец; бежевые — тот же объект',
   [(p['sid'], p.get('styles'), p.get('color_low')) for p in out]
   == [('ales', ['современный'], None), ('mint', ['минимализм'], ['минимализм']), ('beige', ['сканди', 'джапанди'], None)]
   and out[2] is lane[2] and (cut, low) == (1, 1))
out, cut, low = DF.lane_color('шторы', lane[:1], {('сканди', 'ales')})
ok('лента штор: шторы, стоящие в варианте стиля, не трогаем', out[0] is lane[0] and (cut, low) == (0, 0))
out, cut, low = DF.lane_color('подушка', [{'sid': 'x', 'name': 'Подушка Саона Велюр Оранжевый/Синий', 'style': 'минимализм'}])
ok('лента подушек: яркое не в стиле уходит (минимализм, оранжевая)', not out and (cut, low) == (1, 0))
out, cut, low = DF.lane_color('ваза', [{'sid': 'v', 'name': 'Ваза оранжевая', 'style': 'минимализм'}])
ok('лента декора — как была', out[0].get('color_low') is None and (cut, low) == (0, 0))
ok('мягкое варианта: синяя подушка минимализма — замена по цвету, у современного — годна',
   (DF.soft_color_need('подушка 2', {'name': BLUE_P}, 'минимализм') or '').startswith(DF.COLOUR_REASON)
   and DF.soft_color_need('подушка', {'name': BLUE_P}, 'современный') is None)
ok('мягкое варианта: бирюзовые шторы — замена у сканди и джапанди, у современного нет; ваза и стул — не мягкое',
   bool(DF.soft_color_need('шторы', {'name': ALES}, 'сканди')) and bool(DF.soft_color_need('шторы', {'name': ALES}, 'джапанди'))
   and DF.soft_color_need('шторы', {'name': ALES}, 'современный') is None
   and DF.soft_color_need('ваза', {'name': 'Ваза оранжевая'}, 'минимализм') is None
   and DF.soft_color_need('стул', {'name': OLIVE}, 'джапанди') is None)
ok('пара подушек — из политики: минимализм и джапанди без пары, сканди green/yellow, лофт одна, стиль без правил — прежняя',
   CC.pillow_pair('минимализм') == () and CC.pillow_pair('джапанди') == () and CC.pillow_pair('сканди') == ('green', 'yellow')
   and CC.pillow_pair('лофт') == ('terra',) and CC.pillow_pair(None, ('terra', 'green')) == ('terra', 'green'))
sc = [(9.0, {'name': BLUE_P}), (5.0, {'name': 'Подушка Линкс Ваби Бежевый'}), (4.0, {'name': 'Подушка Скай Линии'})]
soft_g = tuple(P['major_groups']) + ('soft_textile',)
ok('подбор подушки минимализма (soft_textile): синяя — после нейтральных; без групп мягкого — порядок прежний',
   [[x[1]['name'] for x in g] for g in CC.color_split(sc, 'подушка', 'минимализм', groups=soft_g)]
   == [['Подушка Линкс Ваби Бежевый', 'Подушка Скай Линии'], [BLUE_P]]
   and CC.color_split(sc, 'подушка', 'минимализм') == [sc])
import demo_swap_pool as SP  # noqa: E402
ok('шторы из каталога: до пола и ткани ≥ 250 (комплект 2 шт — вдвое), рулонные/римские — нет, без размера — нет',
   SP.curtain_fits({'name': 'Комплект штор Алессио', 'w': 260, 'h': 275})
   and SP.curtain_fits({'name': 'Штора Бланш 2 шт', 'w': 150, 'h': 270})
   and not SP.curtain_fits({'name': 'Штора Бланш', 'w': 150, 'h': 270})
   and not SP.curtain_fits({'name': 'Рулонная штора FixLine белая 260х270 см', 'w': 260, 'h': 270})
   and not SP.curtain_fits({'name': 'Римская штора', 'w': 300, 'h': 300})
   and not SP.curtain_fits({'name': 'Тюль Кассандра', 'w': 300, 'h': 0}))
ok('шторы из каталога: одна строка на модель и цвет — размер из названия не различает',
   SP.model_key('Комплект штор Togas Пайнон экрю 260x275 см') == SP.model_key('Комплект штор Togas Пайнон экрю 260x300 см')
   != SP.model_key('Комплект штор Togas Пайнон бежевый 260x275 см')
   and SP.model_key('Тюль Daily Кассандра серый 300х280 см') == SP.model_key('Тюль Daily Кассандра серый 300х275 см'))

print('итог:', 'провалов ' + str(bad) if bad else 'всё ок')
sys.exit(1 if bad else 0)
