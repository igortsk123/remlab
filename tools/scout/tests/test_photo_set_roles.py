"""ЗАДАНИЕ ФОТО ПО СОСТАВУ НАБОРА (П1.50, T-20261113-06): группы `rules/photo-set-roles.json` × состояние (в кадре / третьим листом /
дорисовать / не уместно), расклад декора по листам, сквозные номера, ключ кадров. Без состава — промпт побайтно прежний.

    python tools/scout/tests/test_photo_set_roles.py        # без сети и модели
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
import improve_mode as IM  # noqa: E402

fails = []


def check(name, cond, info=''):
    print(('OK   ' if cond else 'FAIL ') + name + (f' — {info}' if info and not cond else ''))
    if not cond:
        fails.append(name)


S = json.load(open(os.path.join(HERE, '..', 'rules', 'photo-set-roles.json'), encoding='utf-8'))
WIN = {'openings': [{'kind': 'window', 'wall': 'west'}, {'kind': 'door', 'wall': 'east'}]}


def sku(name, **kw):
    return {'name': name, 'img': None, **kw}


def it(role, name):
    return {'role': role, 'name': name, 'img': None}


LIVING_ITEMS = [it('диван', 'Диван А'), it('кресло', 'Кресло Б'), {**it('столик', 'Столик В'), 'w': 100, 'd': 60, 'h': 45, 'x': 200, 'y': 200, 'rot': 0}, it('тв-тумба', 'Тумба Г')]
# гостиная как set1 витрины: подушки, ваза, шторы, люстра, картины — всё нарисовано страницей
LIVING_DECOR = [{'role': 'подушка', 'sku': sku('Подушка 1'), 'shown': True}, {'role': 'подушка 2', 'sku': sku('Подушка 1'), 'shown': True},
                {'role': 'ваза', 'sku': sku('Ваза', w=10, d=10, h=20), 'shown': True},
                {'role': 'шторы', 'strategy': 'textile_abstract', 'sku': sku('Шторы лён'), 'shown': True},
                {'role': 'люстра', 'strategy': 'ceiling_over', 'sku': sku('Люстра'), 'shown': True},
                {'role': 'картина', 'strategy': 'procedural_plane', 'sku': sku('Постер'), 'shown': True}]


def run(payload, style='сканди', placed=None):
    plan = IM.decor_plan(payload, placed)
    C = IM.compose(payload, payload['items'], plan)
    soft = IM.soft_list(C['soft'], C['n3'] + len(C['decor']), payload['items'])
    p = IM.prompt_for(style, C['decor'], None, None, None, None, soft, room=IM.room_kind(payload), groups=C['groups'], kept=C['kept'],
                      n3=C['n3'])
    return C, p


st = lambda C: {g: v['state'] for g, v in (C['groups'] or {}).items()}
guide_lines = lambda p, pre: [l for l in p.splitlines() if l.strip().startswith(pre)]

# 1. ВСЁ КУПЛЕНО И НАРИСОВАНО (гостиная set1) — «оставь как есть», вторых нет, гайд и разрешения «под стиль» сняты
pl = {'room': WIN, 'items': LIVING_ITEMS, 'decor': LIVING_DECOR}
C, p = run(pl)
check('set1: шторы, подушки, люстра, картины — в кадре; пледа нет, диван есть — дорисовать',
      st(C) == {'curtains': 'shown', 'cushions': 'shown', 'throw': 'add', 'ceiling': 'shown', 'art': 'shown'}, st(C))
check('set1: декор в кадре — карточками на листе эталонов после мебели (#5…#10), третьего листа нет',
      [x['role'] for x in C['extra']] == [d['role'] for d in LIVING_DECOR] and [k['id'] for k in C['kept']] == [5, 6, 7, 8, 9, 10]
      and not C['decor'] and not C['soft'] and 'IMAGE 3' not in p, C['kept'])
check('set1: блок KEEP AS RENDERED с номерами и названиями', S['kept_head'] in p and '"id": 8, "item": "curtains"' in p
      and '"item": "ceiling lamp", "name": "Люстра"' in p)
check('set1: шторы — «оставь купленные #8», ни «под стиль», ни строки гайда WINDOW DRESSING, ни разрешения',
      'KEEP THE BOUGHT CURTAINS (#8, IMAGE 2)' in p and 'DRESS THE WINDOW' not in p and not guide_lines(p, 'WINDOW DRESSING:')
      and 'curtains or blinds,' not in p.split('Explicitly ALLOWED', 1)[-1] and 'CURTAINS — WIDTH AND PLACE' in p)
check('set1: люстра — только купленная #9: блок CEILING FIXTURE заменён, строки CEILING LIGHT и разрешения светильника стиля нет',
      'CEILING FIXTURE — ONLY THE BOUGHT CEILING LAMP' in p and '(#9)' in p and 'CEILING FIXTURE — THE ONLY NEW LIGHTING' not in p
      and not guide_lines(p, 'CEILING LIGHT:') and 'style-matched ceiling fixture' not in p
      and IM._PREFIX_CEIL not in p and S['prefix_ceiling_owned'] in p)
forb = p.split('FORBIDDEN', 1)[1]
check('set1: запреты вторых — подушки #5, #6, люстра #9, картины #10, шторы #8',
      '* any cushions other than the bought cushions #5, #6;' in forb and 'other than the bought ceiling lamp #9;' in forb
      and 'other than the bought pictures #10;' in forb and 'other than the bought curtains #8;' in forb)
check('set1: плед дорисовать — на кресло (как SOFT_PLACE), блок STYLE TEXTILES, в TASK',
      S['add_head'] in p and '* one throw draped over the armchair;' in p and 'The only new objects are the style throw of STYLE TEXTILES.' in p)
check('set1: подушки и плед отдельными предметами разрешены (исключение к SHAPE_RULE, запрет стилей заменён)',
      S['exception'] in p and 'cushions, throws or armrests that the catalogue product does not have' not in forb
      and 'built-in cushions or armrests' in forb)
check('set1: «необязательный декор» без штор, подушек, пледов, ламп', S['optional_tail'].strip() in p)

# 2. СПАЛЬНЯ ЛОФТ (bedroom-1-loft): плед и картины есть, штор, подушек и люстры нет — дорисовать
bed = {'room': {**WIN, 'kind': 'bedroom'}, 'items': [it('кровать', 'Кровать'), it('тумба', 'Тумба')],
       'decor': [{'role': 'плед', 'strategy': 'textile_abstract', 'sku': sku('Плед'), 'shown': True},
                 {'role': 'картина', 'strategy': 'procedural_plane', 'sku': sku('Постер'), 'shown': True}]}
C, p = run(bed, 'лофт')
check('спальня: шторы, подушки, люстра — дорисовать; плед и картина — в кадре',
      st(C) == {'curtains': 'add', 'cushions': 'add', 'throw': 'shown', 'ceiling': 'add', 'art': 'shown'}, st(C))
check('спальня: шторы под стиль — прежняя строка, гайд WINDOW DRESSING и разрешение на месте',
      'DRESS THE WINDOW WITH CURTAINS' in p and guide_lines(p, 'WINDOW DRESSING:') and 'curtains or blinds' in p.split('Explicitly ALLOWED', 1)[-1])
check('спальня: люстра стиля — прежний CEILING FIXTURE и строка CEILING LIGHT',
      IM.CEILING_FIXTURE in p and guide_lines(p, 'CEILING LIGHT:') and IM._PREFIX_CEIL in p)
check('спальня: подушки — на кровать, в TASK шторы, светильник и подушки',
      '* two or three decorative cushions on the bed, leaning against the headboard;' in p
      and 'single ceiling fixture that replaces the white ceiling placeholder' in p.split('STATIC HARD RULES')[0]
      and 'curtains at the window' in p and 'the style cushions of STYLE TEXTILES' in p)
check('спальня: запрет второго пледа, «не добавлять» спальни на месте', 'other than the bought one #3;' in p and 'ROOM: this is a bedroom.' in p)

# 3. ПРИХОЖАЯ — ни штор, ни подушек, ни пледа (не уместно); люстра — везде
hall = {'room': {**WIN, 'kind': 'hall'}, 'items': [it('шкаф', 'Шкаф-купе')], 'decor': [], 'decor_known': True}
C, p = run(hall, 'минимализм')
check('прихожая: шторы, подушки, плед — не уместны; люстра — дорисовать',
      st(C) == {'curtains': 'none', 'cushions': 'none', 'throw': 'none', 'ceiling': 'add', 'art': 'none'}, st(C))
check('прихожая: ни штор (ни правила CURTAINS, ни строки гайда), ни STYLE TEXTILES; запрет штор',
      'DRESS THE WINDOW' not in p and 'CURTAINS — WIDTH AND PLACE' not in p and not guide_lines(p, 'WINDOW DRESSING:')
      and S['add_head'] not in p and '* curtains, sheers or blinds;' in p.split('FORBIDDEN', 1)[1] and S['exception'] not in p)
# комната без окна — шторы не уместны; проёмов в запросе нет — неизвестно, шторы как раньше
C, _ = run({'room': {'openings': [{'kind': 'door'}]}, 'items': LIVING_ITEMS, 'decor': [{'role': 'ваза', 'sku': sku('Ваза'), 'shown': True}]})
C2, _ = run({'items': LIVING_ITEMS, 'decor': [{'role': 'ваза', 'sku': sku('Ваза'), 'shown': True}]})
check('без окна — шторы не уместны; проёмов нет в запросе — «под стиль», как раньше',
      st(C)['curtains'] == 'none' and st(C2)['curtains'] == 'add', (st(C), st(C2)))
# кухня без дивана/кровати/кресла: подушек и пледа нет
C, _ = run({'room': {**WIN, 'kind': 'kitchen'}, 'items': [it('стол обеденный', 'Стол')], 'decor': [], 'decor_known': True})
check('кухня: шторы, подушки, плед — не уместны', st(C)['curtains'] == st(C)['cushions'] == st(C)['throw'] == 'none', st(C))

# 4. СТАРАЯ СТРАНИЦА (декор без флага `shown`) — состав неизвестен, задание побайтно прежнее
old = {'room': WIN, 'items': LIVING_ITEMS, 'decor': [{k: v for k, v in d.items() if k != 'shown'} for d in LIVING_DECOR]}
check('без флага `shown`: состав неизвестен', IM.decor_plan(old) is None)
C, p = run(old)
import draft_render as DR  # noqa: E402
_dec, _soft = DR.decor_split(old)[1], IM.soft_items(old)
check('без флага `shown`: задание побайтно как до П1.50 (без групп, номера с 1)', C['groups'] is None and C['n3'] == 1 and p == IM.prompt_for(
    'сканди', _dec, None, None, None, None, IM.soft_list(_soft, len(_dec) + 1, LIVING_ITEMS), room=None))

# 5. КАДР СЕРВЕРА: нарисована только ваза (`decor_split[0]`) — шторы и подушки третьим листом «повесь купленные», номера сквозные
srv = {'room': WIN, 'items': LIVING_ITEMS, 'decor': [{k: v for k, v in d.items() if k != 'shown'} for d in LIVING_DECOR]}
placed = DR.decor_split(srv)[0]
C, p = run(srv, placed=placed)
check('сервер: ваза на столике — в кадре (#5), остальное — третьим листом с #6', [k['item'] for k in C['kept']] == ['vase']
      and C['n3'] == 6 and st(C)['curtains'] == 'sheet' and st(C)['ceiling'] == 'sheet', (C['kept'], C['n3'], st(C)))
ids3 = sorted(int(x) for x in re.findall(r'"id": (\d+)', p.split('SOFT TEXTILES FROM IMAGE 3', 1)[1].split('SERVICE PLACEHOLDERS')[0])) if 'SOFT TEXTILES FROM' in p else []
check('сервер: номера третьего листа не пересекаются с листом эталонов', ids3 and min(ids3) >= C['n3'], ids3)
check('сервер: шторы — «повесь с IMAGE 3», без «под стиль» и гайда; люстра — купленная',
      'HANG THE CURTAINS FROM IMAGE 3' in p and 'DRESS THE WINDOW' not in p and not guide_lines(p, 'WINDOW DRESSING:')
      and 'CEILING FIXTURE — ONLY THE BOUGHT CEILING LAMP' in p and 'CEILING LAMP #' in p)

# 6. НИ ОДНОЙ НЕЗАПОЛНЕННОЙ МЕТКИ, ТЕКСТЫ — АНГЛИЙСКИЕ
allp = [run(x)[1] for x in (pl, bed, hall)] + [p]
check('ни одной незаполненной метки {ids}/{place}', not any('{ids}' in x or '{place}' in x for x in allp))
texts = json.dumps({k: v for k, v in S.items() if k not in ('_about', 'what', 'groups')}, ensure_ascii=False) + json.dumps(
    [{k: v for k, v in g.items() if k not in ('roles', 'needs_any', 'places')} for g in S['groups'].values()], ensure_ascii=False)
check('тексты кусков — без кириллицы (промпт английский)', not re.search('[а-яё]', texts.replace('Ё', '').lower()))
check('у каждой группы роли; deny с {ids}', all(g['roles'] and '{ids}' in g['deny'] for g in S['groups'].values()))

# 7. КЛЮЧ КАДРОВ: что нарисовано — часть ключа; без флага — прежняя форма
fk = {'views': [{'camera': 'C1', 'id': 'a'}, {'camera': 'C2', 'id': 'b'}], 'style': 'сканди', 'items': LIVING_ITEMS}
k_on = IM.frames_key({**fk, 'decor': LIVING_DECOR}, 'm', 'q')
k_off = IM.frames_key({**fk, 'decor': [{**d, 'shown': False} for d in LIVING_DECOR]}, 'm', 'q')
check('ключ кадров: нарисовано / не нарисовано — разные ключи', k_on != k_off)
sys.exit(1 if fails else 0)
