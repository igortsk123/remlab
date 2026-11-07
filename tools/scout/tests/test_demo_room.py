"""Общее ядро витрины комнаты `demo_room.py` на прихожей (hall-demo-01 этап 3, T-20261106-98/1 б): контур Г-образной комнаты,
подъём зеркала над полом (`elev`), ведущие ANY/ALL и парные роли — из профиля, сторож модели и лента — по стратегии ассета (зеркало —
плоскость без модели), ленты по ключу комнаты. Спальня побайтно — `test_demo_room_golden.py`. Без сети и базы: солвер и проверки
прихожей — настоящие (`planner.hall`), товары — заготовка теста. Адаптер прихожей (`demo_hall`) — этап 4; здесь описание комнаты — в тесте.
    ~/venvs/scout/bin/python tools/scout/tests/test_demo_room.py"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
fails = 0


def check(name, cond):
    global fails
    print(('OK   ' if cond else 'FAIL ') + name)
    fails += 0 if cond else 1


import demo_room as R  # noqa: E402

GEO = os.path.join(HERE, '..', 'flat215-hall.json')
ROLES = ('шкаф-купе', 'шкаф', 'прихожая', 'обувница', 'банкетка', 'консоль', 'вешалка', 'зеркало')


def solve_hall(geo, dims, purpose):
    """Солвер прихожей → расстановка с габаритом и подъёмом (как `compose_hall` пишет `layout`)."""
    sys.path.insert(0, R.PLANNER)
    from planner.hall import solve_hall as solve
    from planner.models import Item, Opening, Radiator, Room
    room = Room(width_cm=geo['w'], depth_cm=geo['d'], contour=geo.get('contour'), room_type='hall',
                openings=[Opening(**o) for o in geo.get('openings') or []], radiators=[Radiator(**r) for r in geo.get('radiators') or []])
    lay = solve(room, [Item(role=r, w_cm=w, d_cm=d, h_cm=h) for r, w, d, h in dims])
    out = {p.role: {'x': p.x, 'z': p.y, 'rot': p.rot, 'w': p.item.w_cm, 'd': p.item.d_cm, 'h': p.item.h_cm, 'elev': p.elev_cm}
           for p in lay.placements}
    out['_fill_pct'] = lay.floor_used_pct
    if not lay.ok:
        out['_reason'] = list(lay.meta.get('reason') or [])
    return out


HALL = R.Showcase(room_type='hall', solver_roles=ROLES, place_roles=ROLES, solve=solve_hall, tier_order=('комфорт',),
                  purpose_order=('hall',), solver_purposes=())


def it(mid, w, d, h, name):
    return {'mid': mid, 'eid': 'e', 'name': name, 'price': 1000 + mid, 'img': f'https://x/{mid}.jpg', 'w': w, 'd': d, 'h': h}


WARD, SHOE, CONS = it(1, 180, 60, 240, 'шкаф-купе'), it(2, 60, 35, 100, 'обувница'), it(3, 90, 35, 80, 'консоль')
MIRROR, HANGER = it(4, 60, 3, 120, 'зеркало'), it(5, 45, 40, 175, 'вешалка напольная')


def rec(items, style='лофт'):
    return {'room_id': 'hall', 'room_type': 'hall', 'purpose': 'hall', 'style': style, 'tier': 'комфорт', 'items': items}


def sku(items, role):
    x = items.get(role) or items.get(R.base_role(role))
    return x and {'name': x['name'], 'price': x['price'], 'img': x['img'], 'sid': f"{x['mid']}_{x['eid']}",
                  'msid': f"{x['mid']}_{x['eid']}", 'w': x['w'], 'd': x['d'], 'h': x['h']}


def dims_of(v, s, role):
    return {'w': s['w'], 'd': s['d'], 'h': s['h'], 'dims_src': 'тест'}


style_id = {'лофт': 'loft', 'сканди': 'scandi'}.get
rooms = [r for r in json.load(open(GEO, encoding='utf-8'))['rooms'] if r['id'] == 'hall']
L_ROOM = next(r for r in rooms if r.get('contour'))

# --- профиль: ведущие ANY/ALL и пары — данные
check('профиль прихожей: ведущие — хранение (шкаф-купе, распашной шкаф, прихожая, вешалка), правило ANY, пар нет',
      R.profile_rules('hall') == (('шкаф-купе', 'шкаф', 'прихожая', 'вешалка'), True, ()))
check('профиль спальни: ведущие кровать и тумба, правило ALL, пары — тумба и лампа',
      R.profile_rules('bedroom') == (('кровать', 'тумба прикроватная'), False, ('тумба прикроватная', 'лампа')))
check('модель по стратегии ассета: зеркало и ковёр — нет, шкаф-купе — да',
      (R.needs_mesh('зеркало'), R.needs_mesh('ковёр'), R.needs_mesh('шкаф-купе')) == (False, False, True))

# --- контур
geo = R.room_geo(HALL, 'hall', GEO, {'titleRu': 'Прихожая', 'areaM2': 9.3})
geo_l = R.room_geo(HALL, 'hall', GEO, layout_room=L_ROOM)
check('прямоугольная прихожая (чертёж №180, первый вариант) — без поля contour, тип зоны «hall»',
      'contour' not in geo and (geo['w'], geo['d'], geo['kind'], geo['title']) == (153, 620, 'hall', 'Прихожая 9.3 м²'))
check('Г-образная прихожая — контур в геометрии витрины (вершины чертежа)', geo_l.get('contour') == L_ROOM['contour'])
ghost = {'_room': geo_l, 'консоль': {'x': 300, 'z': 100, 'rot': 0, 'w': 90, 'd': 35, 'h': 80}}
flat = dict(ghost, _room={k: v for k, v in geo_l.items() if k != 'contour'})
check('контур доходит до проверок: предмет в вырезе «Г» — жёсткое нарушение, без контура (прямоугольник) — нет',
      R.hard_codes(HALL, ghost, 'hall') - R.hard_codes(HALL, flat, 'hall') != set())

# --- полный набор солвером: обе формы комнаты, HARD = 0, зеркало на стене
full = {'шкаф-купе': WARD, 'обувница': SHOE, 'консоль': CONS, 'зеркало': MIRROR}
for g, name in ((geo, 'чертёж №180'), (geo_l, 'Г-образная')):
    v, why = R.build_variant(HALL, rec(full), g, sku, dims_of, style_id)
    art = solve_hall(g, [(r, x['w'], x['d'], x['h']) for r, x in full.items()], None)
    mir = next((i for i in (v or {}).get('items') or [] if i['role'] == 'зеркало'), None)
    check(f'{name}: вариант опубликован, id «hall-loft», жёстких нарушений 0',
          why is None and v['id'] == 'hall-loft' and R.hard_codes(HALL, {**art, '_room': g}, 'hall') == set())
    check(f'{name}: зеркало висит — подъём над полом в варианте (elev > 0), у напольных поля нет',
          mir is not None and mir.get('elev', 0) > 0 and all('elev' not in i for i in v['items'] if i['role'] != 'зеркало'))

# --- ANY: любое хранение
v, why = R.build_variant(HALL, rec({'вешалка': HANGER, 'зеркало': MIRROR}), geo, sku, dims_of, style_id)
check('ANY: только напольная вешалка (хранение) — вариант публикуется', why is None and v is not None)
v, why = R.build_variant(HALL, rec({'обувница': SHOE, 'зеркало': MIRROR}), geo, sku, dims_of, style_id)
check('ANY: хранения нет вовсе — не публикуется, в причине все четыре ведущих',
      v is None and why['missing'][:4] == ['шкаф-купе', 'шкаф', 'прихожая', 'вешалка'])
v, why = R.build_variant(HALL, rec({'вешалка': HANGER, 'зеркало': MIRROR}), geo, sku, dims_of, style_id, lead_any=False)
check('ALL (переданное правило) на том же наборе — не публикуется: нет шкафа-купе, распашного и модуля',
      v is None and why['missing'][:3] == ['шкаф-купе', 'шкаф', 'прихожая'])

# --- сторож модели: зеркало без модели остаётся (плоскость), шкаф без модели — пустой с причиной
no_model = {'1_e', '4_e'}
v, why = R.build_variant(HALL, rec({'шкаф-купе': WARD, 'вешалка': HANGER, 'зеркало': MIRROR}), geo, sku, dims_of, style_id,
                         mesh_ok=lambda s: 'модели нет' if s['sid'] in no_model else '')
got = {i['role'] for i in (v or {}).get('items') or []}
check('сторож: зеркало без модели в варианте (стратегия — плоскость), шкаф-купе без модели — пустая роль, вариант жив (ANY)',
      why is None and 'зеркало' in got and 'шкаф-купе' not in got and [e['role'] for e in v['missing_item']] == ['шкаф-купе'])

# --- пары: пронумерованное место берёт товар роли только у парной роли
lay = {'_room': geo, 'шкаф-купе': {'x': 123, 'z': 300, 'rot': 270}, 'обувница': {'x': 18, 'z': 400, 'rot': 90},
       'обувница 2': {'x': 18, 'z': 480, 'rot': 90}}
r2 = rec({'шкаф-купе': WARD, 'обувница': SHOE})
v, _ = R.build_variant(HALL, r2, geo, sku, dims_of, style_id, layout=lay)
check('пары по профилю (у прихожей нет): «обувница 2» расстановки в вариант не идёт, но не молча — в поле unpaired',
      sorted(i['role'] for i in v['items']) == ['обувница', 'шкаф-купе'] and v.get('unpaired') == ['обувница 2'])
v, _ = R.build_variant(HALL, r2, geo, sku, dims_of, style_id, layout=lay, pairs=('обувница',))
check('парная роль: «обувница 2» — тот же товар на втором месте, поля unpaired нет',
      sorted(i['role'] for i in v['items']) == ['обувница', 'обувница 2', 'шкаф-купе']
      and len({i['sku']['sid'] for i in v['items'] if i['role'].startswith('обувница')}) == 1 and 'unpaired' not in v)
check('сторож пары: номер без товара базовой роли и служебные ключи — не в списке',
      R.unpaired_places({'_room': {}, 'банкетка 2': {}, 'обувница 2': {}, 'обувница': {}}, {'обувница': {}}, ()) == ['обувница 2'])

# --- ленты: зеркало без модели — в ленте, ключ комнаты
f = R.feeds(HALL, [rec(full)], None, msid=lambda s: s, mesh_ok=lambda s: 'модели нет')
check('лента: без моделей остаётся только зеркало (плоскость по фото), строка с фото и размером',
      list(f) == ['зеркало'] and f['зеркало'][0]['sid'] == '4_e' and f['зеркало'][0]['styles'] == ['лофт'])
merged = R.merge_room_feeds({'зеркало': ['гостиная']}, 'hall', f)
check('лента прихожей — под ключом «hall:зеркало», голая роль гостиной не тронута',
      merged['зеркало'] == ['гостиная'] and merged['hall:зеркало'] == f['зеркало'])
check('полосы по комнате: у прихожей без полос — пусто', R.room_bands(HALL, [rec(full)], ['hall']) == {})

print('итог:', 'OK' if not fails else f'{fails} FAIL')
sys.exit(1 if fails else 0)
