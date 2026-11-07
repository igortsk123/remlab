"""Спальни витрины демо (onb-07 Т2, T-20261105-32): банк спальни → варианты с комнатой, назначением и своей геометрией; флаг
включения; ленты замен по ролям спальни. Без сети и базы (товар и габарит — из записи заготовки, солвер спальни — настоящий).
    ~/venvs/scout/bin/python tools/scout/tests/test_demo_bedroom.py"""
import json
import os
import sys
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))  # tools/scout — помощник временного
import remlab_tmp  # noqa: E402
remlab_tmp.use('test_demo_bedroom')  # временное теста — на диске, не в /tmp; папка убирается при выходе (T-20261107-13)

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
fails = 0


def check(name, cond):
    global fails
    print(('OK   ' if cond else 'FAIL ') + name)
    fails += 0 if cond else 1


import demo_bedroom as DB  # noqa: E402
import flat215_demo as F  # noqa: E402

FIX = os.path.join(HERE, 'fixtures', 'sets-bedroom.fixture.json')
bank = DB.load_bank(FIX)
check('заготовка банка: 2 записи спальни 1 «пара» со стилем', [(r['room_id'], r['purpose'], r['style']) for r in bank]
      == [('bedroom-1', 'couple', 'сканди'), ('bedroom-1', 'couple', 'современный')])
check('банка нет — пусто (комната остаётся «скоро»)', DB.load_bank(os.path.join(HERE, 'нет.json')) == [])

reg = {'id': 'bedroom-1', 'kind': 'bedroom', 'titleRu': 'Спальня 1', 'areaM2': 17.5}
geo = DB.room_geo('bedroom-1', reg, {'height_cm': 270})
check('геометрия спальни 1 — основной вариант чертежа 618×293, тип зоны «bedroom», подпись реестра',
      (geo['w'], geo['d'], geo['kind'], geo['title'], geo['height_cm']) == (618, 293, 'bedroom', 'Спальня 1 17.5 м²', 270))
check('служебные пояснения проёмов в данные не идут', not any(k.startswith('_') for o in geo['openings'] + geo['radiators'] for k in o))
check('комнаты нет в файле геометрии — None', DB.room_geo('bedroom-9', {}) is None)


def sku(items, role):
    it = items.get(role) or items.get(DB.base_role(role))
    return it and {'name': it['name'], 'price': it['price'], 'img': it['img'], 'sid': f"{it['mid']}_{it['eid']}",
                   'msid': f"{it['mid']}_{it['eid']}", 'w': it['w'], 'd': it['d'], 'h': it['h']}


v, why = DB.build_variant(bank[0], geo, sku, F._dims_of, F.style_id)
roles = sorted(i['role'] for i in v['items'])
check('вариант: id «комната-стиль», комната и назначение из записи', (v['id'], v['room_id'], v['purpose'], v['style_id'])
      == ('bedroom-1-scandi', 'bedroom-1', 'couple', 'scandi') and why is None)
check('солвер спальни расставил кровать, обе тумбы, шкаф и комод',
      roles == ['комод', 'кровать', 'тумба прикроватная', 'тумба прикроватная 2', 'шкаф'])
inside = all(0 <= i['x'] - i['w'] / 2 + 1e-6 or i['rot'] % 180 for i in v['items'])
bed = next(i for i in v['items'] if i['role'] == 'кровать')
win = [o for o in geo['openings'] if o['kind'] == 'window']
# изголовье — у стены rot 0 → y = 0 (юг); окна спальни 1 — восток и север: изголовье не в окно
check('изголовье кровати не у окна (стена изголовья без окна)',
      bed['rot'] == 0 and abs(bed['y'] - bed['d'] / 2) < 2 and not any(o['wall'] == 'south' for o in win))
check('габариты — товара, не придуманы', (bed['w'], bed['d']) == (173.0, 203.0))
no_bed = dict(bank[0], items={k: x for k, x in bank[0]['items'].items() if k != 'кровать'})
v2, why2 = DB.build_variant(no_bed, geo, sku, F._dims_of, F.style_id)
check('без кровати вариант не публикуется, причина — с комнатой', v2 is None and why2['room_id'] == 'bedroom-1'
      and 'кровать' in why2['missing'])
v3, why3 = DB.build_variant(dict(bank[0], style='бохо'), geo, sku, F._dims_of, F.style_id)
check('стиль вне витрины — не публикуется', v3 is None and why3['missing'] == ['стиль вне витрины'])
lay = {'кровать': {'x': 300, 'z': 102, 'rot': 0}, 'тумба прикроватная': {'x': 200, 'z': 21, 'rot': 0}}
v4, _ = DB.build_variant(bank[0], geo, sku, F._dims_of, F.style_id, layout=lay)
check('готовая расстановка записи берётся как есть, без солвера', sorted(i['role'] for i in v4['items']) == ['кровать', 'тумба прикроватная'])

# ГОТОВАЯ РАССТАНОВКА БАНКА (формат onb-06, T-31): места в комнате записи, вторые экземпляры — «… 2», лампа на тумбе — строкой списка
L = {'_room': {'variant': 'registry-17.5', 'w': 597, 'd': 293, 'openings': geo['openings'], 'radiators': geo['radiators']},
     '_meta': {'solver': 'bedroom-v1'}, 'кровать': {'x': 298.5, 'z': 101.5, 'rot': 0},
     'тумба прикроватная': {'x': 190, 'z': 17.5, 'rot': 0}, 'тумба прикроватная 2': {'x': 407, 'z': 17.5, 'rot': 0},
     'ковёр': {'x': 298.5, 'z': 167.7, 'rot': 0}, 'лампа': {'x': 190, 'z': 17.5, 'elev': 52, 'on': 'тумба прикроватная'},
     'лампа 2': {'x': 407, 'z': 17.5, 'elev': 52, 'on': 'тумба прикроватная 2'}}
its = {k: x for k, x in bank[0]['items'].items() if k != 'тумба прикроватная 2'}
its['ковёр'] = dict(its['комод'], name='Ковер Мирна 200x300', w=300, d=200, h=1)
its['лампа'] = dict(its['комод'], name='Светильник настольный', w=11, d=11, h=38, qty=2)
rb = dict(bank[0], items=its, layout=L)
v5, _ = DB.build_variant(rb, geo, sku, F._dims_of, F.style_id, decor_role=lambda r: False)
check('банк onb-06: вторая тумба — по месту «… 2», ковёр — в сцене, шкаф и комод без места — не выдуманы',
      sorted(i['role'] for i in v5['items']) == ['ковёр', 'кровать', 'тумба прикроватная', 'тумба прикроватная 2'])
check('банк onb-06: лампы на тумбах — две строки списка, не в 3D', [d['role'] for d in v5['decor']] == ['лампа', 'лампа 2'])
check('лампы — «только в списке» (`list_only`): окно и ворота копий их в 3D не ставят (T-77/2)',
      all(d.get('list_only') is True for d in v5['decor']))
check('банк onb-06: геометрия — комната расстановки записи (597×293), не чертёж', DB.bank_room([rb], 'bedroom-1')['w'] == 597
      and DB.room_geo('bedroom-1', reg, layout_room=DB.bank_room([rb], 'bedroom-1'))['w'] == 597)
tiers = [dict(bank[0], tier=t, set_id=t) for t in ('эконом', 'премиум', 'комфорт')]
check('ячейка витрины: средняя ступень цены «комфорт»', [r['set_id'] for r in DB.pick_records(tiers, ['bedroom-1'], ['сканди'])]
      == ['комфорт'])

recs = DB.pick_records(bank + [dict(bank[0], room_id='bedroom-2')], ['bedroom-1'], ['современный', 'сканди', 'лофт'])
check('отбор записей: только включённые комнаты, стили и порядок — витрины гостиной',
      [(r['room_id'], r['style']) for r in recs] == [('bedroom-1', 'современный'), ('bedroom-1', 'сканди')])

msid = lambda s: s  # noqa: E731
fd = DB.feeds(bank, {'roles': {'кровать': [{'sid': '1:2', 'name': 'Кровать Х 160', 'img': 'x.jpg', 'price': 9, 'w': 170, 'd': 210,
                                            'h': 90}],
                                'ковёр': [{'sid': '1:9', 'name': 'Ковёр Y 200x300', 'img': 'r.jpg', 'price': 5, 'w': 200,
                                           'd': 300}]}},
               msid, lambda s: 'нет в индексе прода' if s['msid'] == '112923_11672424920201226922' else '')
check('ленты спальни: товары наборов со стилем, каталог — без стиля, дешевле сначала',
      [(p['name'][:7], p['styles']) for p in fd['кровать']] == [('Кровать', []), ('Кровать', ['сканди']), ('Кровать', ['современный'])])
check('ленты спальни: товар без модели на сервере в ленту не идёт', all(p['sid'] != '112923_11672424920201226922'
                                                                       for p in fd.get('комод', [])))
check('ленты спальни: тумба двух слотов — одна строка', len(fd['тумба прикроватная']) == 2)
check('ленты спальни: ковёр — плоскость по канону стратегий, модели и высоты не требует (T-77 Д1)',
      '1_9' in [p['sid'] for p in fd.get('ковёр', [])])
seen = []
DB.feeds(bank, {}, msid, lambda s: seen.append(s) or 'нет')
check('ленты спальни: сторож получает товар (sid и msid), как у варианта; отказ — товара в ленте нет',
      seen and all(set(x) == {'sid', 'msid'} for x in seen)
      and not DB.feeds(bank, {}, msid, lambda s: 'нет').get('кровать'))
check('полоса размера кровати «вдвоём» 160–205 и тумб', DB.bands(['couple']) == {'тумба прикроватная': {'lo': 30, 'hi': 65},
                                                                              'кровать': {'lo': 160, 'hi': 205}})

# ЛЕНТЫ И ПОЛОСЫ ПО КЛЮЧУ КОМНАТЫ (T-20261106-77, Codex): общая роль «ковёр» гостиной и спальни — разные ленты; гостиная побайтно та же
_liv = {'ковёр': [{'sid': 'L1'}], 'диван': [{'sid': 'S1'}]}
_liv_before = json.dumps(_liv, ensure_ascii=False, sort_keys=True)
_m = DB.merge_room_feeds(json.loads(_liv_before), 'bedroom', {'ковёр': [{'sid': 'B1'}], 'кровать': [{'sid': 'K1'}]})
check('ковёр гостиной и спальни — разные ленты', _m['ковёр'] == [{'sid': 'L1'}] and _m['bedroom:ковёр'] == [{'sid': 'B1'}])
check('ленты гостиной побайтно прежние (голые роли)',
      json.dumps({k: v for k, v in _m.items() if ':' not in k}, ensure_ascii=False, sort_keys=True) == _liv_before)
check('роль только спальни — под ключом спальни', 'кровать' not in _m and _m['bedroom:кровать'] == [{'sid': 'K1'}])
_rb = DB.room_bands([{'room_id': 'bedroom-1', 'purpose': 'couple'}, {'room_id': 'bedroom-2', 'purpose': 'guest'}], ['bedroom-1', 'bedroom-2'])
check('полоса — своя у каждой спальни', _rb['bedroom-1:кровать'] == DB.bands(['couple'])['кровать']
      and _rb['bedroom-2:кровать'] == DB.bands(['guest']).get('кровать') and not any(':' not in k for k in _rb))

# ФЛАГ: проверочное включение — только у сборки рядом; главная демо — реестром
# комнаты и опрос — разные флаги одного словаря (`room_flags`): комнаты сверяются по `rooms_enabled`, опрос — отдельно по реестру
# (T-77 и T-83 влиты параллельно: целым словарём сравнивать нельзя — опрос demo/flat215 включён, T-20261106-83/2)
check('флаг: без переменной — как реестр (обе спальни включены, T-77)',
      F.rooms_on(F.demo_apartment(), {}).get('rooms_enabled') == ['bedroom-1', 'bedroom-2'])
check('флаг опроса: у demo/flat215 по реестру включён (T-83)', F.rooms_on(F.demo_apartment(), {}).get('quiz_enabled') is True)
apt = dict(F.demo_apartment(), rooms=[{k: v for k, v in r.items() if k != 'enabled'} for r in F.demo_apartment()['rooms']])
check('флаг: без переменной — как реестр (комнаты выключены)', F.rooms_on(apt, {}).get('rooms_enabled') is None)
apt_noquiz = {k: v for k, v in apt.items() if k != 'quiz'}
check('флаг опроса: квартира без ключа quiz — нет поля, всё выключено — пусто',
      'quiz_enabled' not in F.rooms_on(apt_noquiz, {}) and F.rooms_on(apt_noquiz, {}) == {})
check('флаг: сборка рядом включает спальню 1', F.rooms_on(apt, {F.ROOMS_ENV: 'bedroom-1'}, '/tmp/x-demo').get('rooms_enabled')
      == ['bedroom-1'])


def refuse(env, out):
    try:
        F.rooms_on(apt, env, out)
        return ''
    except SystemExit as e:
        return str(e)


check('флаг: переменная у папки витрины — отказ', 'реестром' in refuse({F.ROOMS_ENV: 'bedroom-1'}, F._BP.DEMO_OUT_DEFAULT))
check('флаг: опечатка в id комнаты — отказ', 'нет в реестре' in refuse({F.ROOMS_ENV: 'bedrom-1'}, '/tmp/x-demo'))

# БАНК ПО УМОЛЧАНИЮ (T-20261105-32/2): сборке рядом не нужен BEDROOM_SETS — берёт кандидат `.next`; живой есть — живой; витрина — только живой
_live = DB.BANK_LIVE
try:
    DB.BANK_LIVE = os.path.join(HERE, 'нет-такого-sets-bedroom.json')
    nxt = F._BP.room_bank_output({}, 'bedroom')
    check('банк: сборка рядом без переменной — кандидат sets-bedroom.next.json',
          F.bedroom_bank_path({}, '/tmp/x-demo') == nxt and nxt.endswith('sets-bedroom.next.json'))
    check('банк: ROOM_SETS_OUTPUT сборщика на выбор не влияет', F.bedroom_bank_path({'ROOM_SETS_OUTPUT': '/tmp/b.json'}, '/tmp/x-demo') == nxt)
    check('банк: витрина без живого — живой путь (спальня «скоро»), не кандидат',
          F.bedroom_bank_path({}, F._BP.DEMO_OUT_DEFAULT) == DB.BANK_LIVE)
    check('банк: BEDROOM_SETS — главнее', F.bedroom_bank_path({F.BEDROOM_SETS_ENV: '/tmp/s.json'}, '/tmp/x-demo') == '/tmp/s.json')
    DB.BANK_LIVE = os.path.abspath(__file__)  # «живой есть»
    check('банк: живой есть — живой и у сборки рядом', F.bedroom_bank_path({}, '/tmp/x-demo') == DB.BANK_LIVE)
finally:
    DB.BANK_LIVE = _live

# ОДНА РАССТАНОВКА СПАЛЬНИ НА ВСЕ СТИЛИ (T-20261105-32/4): комната 597×293 спальни 1, у третьего стиля комод у кровати (NE),
# у двух — у южной стены (SW). Опорный — по согласию зон, не по имени; роль в чужой зоне — на место опорной, если встаёт
R = {'w': 597, 'd': 293, 'openings': L['_room']['openings'], 'radiators': L['_room']['radiators']}


def art(комод, bed_w=174):
    return {'_room': R, 'кровать': {'x': 298.5, 'z': 106.5, 'rot': 0, 'w': bed_w, 'd': 213, 'h': 100},
            'тумба прикроватная': {'x': 298.5 - bed_w / 2 - 24, 'z': 21, 'rot': 0, 'w': 43, 'd': 42, 'h': 55},
            'шкаф': {'x': 26, 'z': 165.5, 'rot': 90, 'w': 135, 'd': 52, 'h': 200}, 'комод': комод}


A = {'а': art({'x': 97, 'z': 270, 'rot': 180, 'w': 90, 'd': 46, 'h': 80}),
     'б': art({'x': 485, 'z': 23, 'rot': 0, 'w': 90, 'd': 46, 'h': 80}),
     'в': art({'x': 95.5, 'z': 273, 'rot': 180, 'w': 83, 'd': 40, 'h': 80})}
check('зона — стена у центра и четверть, как подпись гостиной', (DB.zones(A['а'])['комод'], DB.zones(A['б'])['комод'])
      == ('S:SW', 'N:NE'))
check('опорный — с кем согласно больше ролей, а не первый по порядку', DB.reference(A, ['б', 'а', 'в']) == 'а')
check('при равенстве — первый по порядку витрины', DB.reference({k: A[k] for k in ('а', 'в')}, ['в', 'а']) == 'в')
out, rep = DB.one_layout(A, ['а', 'б', 'в'])
k = out['б']['комод']
check('комод «б» — на месте опорного: та же стена вплотную, поворот, центр вдоль стены; свой габарит',
      (k['x'], k['z'], k['rot'], k['w']) == (97, 270.0, 180, 90) and [(m['style'], m['role']) for m in rep['moved']] == [('б', 'комод')])
check('у «в» комод в той же зоне — не тронут (размер свой, банк подогнал к соседям)', out['в']['комод'] == A['в']['комод'])
check('банк не переписан — входные расстановки прежние', A['б']['комод']['x'] == 485 and out['а'] is A['а'])
check('после переноса нет жёстких нарушений', DB.hard_codes(out['б'], 'couple') == set())
# место опорного занято своим предметом стиля («б» ставит туда рабочий стол, которого у опорного нет) — комод остаётся, причина в отчёте
blk = dict(A['б'], **{'стол рабочий': {'x': 100, 'z': 263, 'rot': 180, 'w': 100, 'd': 60, 'h': 75}})
out2, rep2 = DB.one_layout({'а': A['а'], 'б': blk, 'в': A['в']}, ['а', 'б', 'в'])
kept = {(x['style'], x['role']) for x in rep2['kept']}
check('не встаёт (наезд) — своя позиция банка и строка с причиной', out2['б']['комод'] == blk['комод']
      and ('б', 'комод') in kept and any('COLLISION' in w or 'OVERLAP' in w for x in rep2['kept'] if x['role'] == 'комод'
                                         for w in x['why']))
check('другая комната — стиль не трогаем', DB.one_layout({'а': A['а'], 'б': dict(A['б'], _room=dict(R, w=618))},
                                                          ['а', 'б'])[1]['kept'][0]['why'] == 'другая комната')
check('правило включено в данных (`rules/demo-layout.json` → bedroom)', DB.one_rule().get('enabled') is True)

# СТОРОЖ МОДЕЛИ ПРЕДМЕТА (T-20261105-51/2): без готовой выложенной модели — следующий кандидат роли; нет — роль пустая с причиной
it0 = bank[0]['items']
alt = lambda base, eid, **kw: dict(it0[base], eid=eid, name=f'{base} {eid}', **kw)   # noqa: E731
G = dict(art(dict(A['а']['комод'])), **{'тумба прикроватная 2': {'x': 298.5 + 87 + 24, 'z': 21, 'rot': 0, 'w': 43, 'd': 42, 'h': 55},
                                         'ковёр': {'x': 298.5, 'z': 160, 'rot': 0, 'w': 200, 'd': 140, 'h': 1}})
grec = dict(bank[0], items=dict(it0, ковёр=dict(it0['комод'], eid='rug', name='Ковёр', w=200, d=140, h=1)), layout=G,
            alternates={'кровать': [alt('кровать', 'b1'), alt('кровать', 'b2')],
                        'тумба прикроватная': [alt('тумба прикроватная', 't1'), alt('тумба прикроватная', 't2', w=40, d=40)],
                        'комод': [alt('комод', 'k1', w=300)]})
bad = {'112923_' + it0['кровать']['eid']: 'привязка blocked', '112923_b1': 'модель не выложена',
       '112923_' + it0['тумба прикроватная']['eid']: 'нет в индексе прода', '112923_t1': 'привязка none',
       '112923_' + it0['комод']['eid']: 'привязка blocked', '112923_k1': '', '112923_rug': 'привязка none'}
gate = lambda s: bad.get(s['sid'], '')   # noqa: E731
v6, why6 = DB.build_variant(grec, geo, sku, F._dims_of, F.style_id, mesh_ok=gate)
by6 = {i['role']: i['sku']['sid'] for i in v6['items']}
check('сторож: кровать без модели → второй кандидат (первый не выложен)', by6['кровать'] == '112923_b2' and why6 is None)
check('сторож: тумба — второй кандидат в ОБОИХ местах (и строка банка «… 2»)',
      by6['тумба прикроватная'] == by6['тумба прикроватная 2'] == '112923_t2')
t2 = next(i for i in v6['items'] if i['role'] == 'тумба прикроватная')
check('сторож: замена на месте прежней — та же стена вплотную, свой габарит', (t2['w'], t2['y']) == (40.0, 20.0))
check('сторож: комод — единственный кандидат не встаёт (300 см) → роль пустая, причина в отчёте',
      'комод' not in by6 and [e['role'] for e in v6['missing_item']] == ['комод']
      and 'не встаёт' in v6['missing_item'][0]['why'] and 'привязка blocked' in v6['missing_item'][0]['why'])
check('сторож: ковёр — своей отрисовкой, сторож не трогает; шкаф годен — тот же', by6['ковёр'] == '112923_rug'
      and by6['шкаф'] == '112923_' + it0['шкаф']['eid'])
check('сторож: замены — в отчёт сборки «было → стало»', [(e['role'], e['now'][0], e['why']) for e in v6['mesh_swaps']]
      == [('кровать', '112923_b2', 'привязка blocked'), ('тумба прикроватная', '112923_t2', 'нет в индексе прода')])
nob = dict(grec, alternates={})
v7, why7 = DB.build_variant(nob, geo, sku, F._dims_of, F.style_id, mesh_ok=gate)
check('сторож: у кровати нет годного кандидата → вариант не публикуется, причина «модель»', v7 is None
      and 'кровать' in why7['missing'] and why7['mesh'][0]['why'].startswith('модель не готова (привязка blocked); кандидатов 0'))
v8, _ = DB.build_variant(grec, geo, sku, F._dims_of, F.style_id)
check('без сторожа — как было (товары записи, без замен)', {i['role']: i['sku']['sid'] for i in v8['items']}['кровать']
      == '112923_' + it0['кровать']['eid'] and 'mesh_swaps' not in v8 and v8['missing_item'] == [])

# ВЕДУЩИЙ ПРЕДМЕТ (T-20261106-77): роли — данными профиля; без модели — свой стиль (другие записи), потом соседний; нет — не публикуем
check('ведущие роли — из профиля спальни (`lead: true`), не списком в коде',
      DB.lead_roles() == ('кровать', 'тумба прикроватная') and not hasattr(DB, 'CORE'))
check('соседние стили — пары «легко спутать» паспорта осей (сканди → джапанди, минимализм)',
      DB.neighbour_styles('сканди') == ['джапанди', 'минимализм'] and DB.neighbour_styles('бохо') == [])
mine2 = dict(grec, room_id='bedroom-2', purpose='guest', alternates={'кровать': [alt('кровать', 'o1')],
                                                                 'тумба прикроватная': [alt('тумба прикроватная', 't2', w=40, d=40)]})
near = dict(grec, style='джапанди', alternates={'кровать': [alt('кровать', 'n1'), alt('кровать', 'n2', w=120)]})
far = dict(grec, style='лофт', alternates={'кровать': [alt('кровать', 'f1')]})
pool_bank = [far, near, nob, mine2]
sp = DB.role_spares(pool_bank, nob)
check('запас: все роли солвера (одно правило, T-20261106-77/4); свой стиль раньше соседнего; несоседний стиль (лофт) не берём; без повторов sid',
      set(sp) == set(DB.SOLVER_ROLES) and [st for st, _ in sp['кровать']][:2] == ['сканди', 'сканди']
      and 'лофт' not in {st for st, _ in sp['кровать']} and len({DB._key(it) for _, it in sp['кровать']}) == len(sp['кровать']))
vA, whyA = DB.build_variant(nob, geo, sku, F._dims_of, F.style_id, mesh_ok=gate, spares=sp)
byA = {i['role']: i['sku']['sid'] for i in vA['items']} if vA else {}
check('ведущий: своя запись без годной кровати → кровать своего стиля из другой записи банка, без пометки стиля',
      whyA is None and byA.get('кровать') == '112923_o1'
      and next(e for e in vA['mesh_swaps'] if e['role'] == 'кровать').get('style') is None)
bad['112923_o1'] = 'привязка none'
vB, whyB = DB.build_variant(nob, geo, sku, F._dims_of, F.style_id, mesh_ok=gate, spares=DB.role_spares(pool_bank, nob))
eB = next((e for e in (vB or {}).get('mesh_swaps') or [] if e['role'] == 'кровать'), {})
check('ведущий: в своём стиле годной нет → соседний стиль (джапанди), пометка стиля в замене для журнала',
      whyB is None and eB.get('now', [None])[0] == '112923_n1' and eB.get('style') == 'джапанди')
bad['112923_n1'] = 'модель не выложена'
vC, whyC = DB.build_variant(nob, geo, sku, F._dims_of, F.style_id, mesh_ok=gate, spares=DB.role_spares(pool_bank, nob))
check('ведущий: у соседа только кровать вне полосы назначения (120 см у «пары») → вариант не публикуется, причина «модель»',
      vC is None and 'кровать' in whyC['missing'] and 'вне полосы размера' in whyC['mesh'][0]['why'])
for k in ('112923_o1', '112923_n1'):
    bad.pop(k)

# ЗАПАС — ВСЕМ РОЛЯМ СОЛВЕРА (T-20261106-77/4): комод минимализма без годной модели (цвет семьи не тот — привязка blocked), своих
# запасных нет → годный комод другой записи своего стиля (на проде — Лигес серо-зелёный); раньше запас был только у ведущих
mn = dict(nob, style='минимализм')
mn_other = dict(grec, style='минимализм', room_id='bedroom-2', purpose='guest',
                alternates={'кровать': [alt('кровать', 'o1')], 'тумба прикроватная': [alt('тумба прикроватная', 't2', w=40, d=40)],
                            'комод': [alt('комод', 'lig')]})
vK, whyK = DB.build_variant(mn, geo, sku, F._dims_of, F.style_id, mesh_ok=gate, spares=DB.role_spares([mn_other, mn], mn))
byK = {i['role']: i['sku']['sid'] for i in vK['items']} if vK else {}
check('запас всем ролям: комод минимализма встаёт из банка (другая запись своего стиля), пустых ролей нет',
      whyK is None and byK.get('комод') == '112923_lig' and vK['missing_item'] == []
      and next(e for e in vK['mesh_swaps'] if e['role'] == 'комод')['why'] == 'привязка blocked')
vK0, _ = DB.build_variant(mn, geo, sku, F._dims_of, F.style_id, mesh_ok=gate,
                          spares=DB.role_spares([mn_other, mn], mn, DB.lead_roles()))
check('прежнее правило (запас только ведущим) оставляло комод пустым — тот же случай',
      vK0 and 'комод' not in {i['role'] for i in vK0['items']} and [e['role'] for e in vK0['missing_item']] == ['комод'])

# сторож сборки: та же проверка, что выдача каталога (`catalog_items.bound_asset`), + сцена грузит модель привязки и она на проде
row = lambda st, pub, mesh, why=('rep:orientation_review_pending',): {   # noqa: E731
    'status': st, 'asset_id': 'sha256:' + 'a' * 64, 'mesh_id': mesh, 'representative_offer_id': None, 'via_family': False,
    'generation_key': 'g', 'revision_key': 'r', 'source_sha': 's', 'local_path': '/x.glb', 'orientation': None, 'passport': None,
    'local_3d': True, 'published_3d': pub, 'solver': True, 'appearance': True, 'reasons': list(why) if st != 'ready' else [],
    'warnings': [], 'snapshot_id': 'z' * 16}
_idx = F._MESH_IDX
try:
    F._MESH_IDX = {'1_a', '1_b', '1_c', '1_g', '1_h'}
    rows = {'1:a': row('ready', True, '1:a'), '1:b': row('blocked', True, '1:b'), '1:c': row('ready', False, '1:c'),
            '1:d': row('ready', True, '1:d'), '1:e': row('ready', True, '1:e'),
            '1:g': row('blocked', False, '1:g', ('orientation_symmetric_by_role',)),
            '1:h': row('blocked', True, '1:h', ('orientation_symmetric_by_role', 'family_colour_mismatch:зелёный→светлый')),
            '1:i': row('blocked', False, '1:i', ('orientation_vlm_pending',))}
    cases = (('a', '1_a'), ('b', '1_b'), ('c', '1_c'), ('d', '1_d'), ('e', '1_a'), ('f', '1_f'), ('g', '1_g'), ('h', '1_h'), ('i', '1_i'))
    g = F.bedroom_mesh_gate(rows, mode='strict')
    res = {k: g({'sid': f'1_{k}', 'msid': m}) for k, m in cases}
    check('сторож strict: годен только ready + выложен + в индексе прода + сцена грузит модель привязки',
          res['a'] == '' and res['b'].startswith('привязка blocked: rep:orientation') and res['c'] == 'модель не выложена'
          and res['d'] == 'нет в индексе прода' and res['e'].startswith('сцена грузит 1_a') and res['f'].startswith('привязка none')
          and res['g'].startswith('привязка blocked'))
    g = F.bedroom_mesh_gate(rows)
    res = {k: g({'sid': f'1_{k}', 'msid': m}) for k, m in cases}
    check('сторож по умолчанию — orient (правило В, T-51/3)', g.mode == 'orient')
    check('сторож orient: blocked ТОЛЬКО по развороту годен и без «выложена привязкой» (файл в индексе прода)',
          res['b'] == '' and res['g'] == '' and g.note({'sid': '1_g'}) == 'orientation_symmetric_by_role'
          and g.note({'sid': '1_a'}) == '')
    check('сторож orient: разворот + цвет — нет; разворот, но файла на проде нет — нет; ready не выложен — нет',
          res['h'].startswith('привязка blocked') and res['i'] == 'нет в индексе прода' and res['c'] == 'модель не выложена'
          and res['e'].startswith('сцена грузит'))
    check('разворот: и у представителя (`rep:orientation_*`), пустой список — не разворот',
          F.orient_only(['rep:orientation_review_pending', 'orientation_vlm_pending']) and not F.orient_only([])
          and not F.orient_only(['orientation_x', 'family_colour_mismatch:a→b']))
    # нерешённый разворот — в вариант (сборка снимает поле в журнал WARN:bedroom_orient_unresolved), заменённый — по новому товару
    og = lambda s: '' if s['sid'] != '112923_' + it0['кровать']['eid'] else 'привязка blocked'   # noqa: E731
    og.note = lambda s: 'orientation_symmetric_by_role' if s['sid'] in ('112923_b1', '112923_' + it0['шкаф']['eid']) else ''
    v9, _ = DB.build_variant(grec, geo, sku, F._dims_of, F.style_id, mesh_ok=og)
    check('нерешённый разворот: роль, msid, причина — у оставленного и у замены',
          sorted((e['role'], e['msid']) for e in v9['orient_unresolved'])
          == [('кровать', '112923_b1'), ('шкаф', '112923_' + it0['шкаф']['eid'])])
    try:
        F.bedroom_mesh_gate(rows, mode='мягко')
        bad_mode = False
    except SystemExit:
        bad_mode = True
    check('сторож: неизвестный режим — отказ, а не молча строгий', bad_mode)
    # МОДЕЛЬ СЦЕНЫ СПАЛЬНИ = МОДЕЛЬ ПРИВЯЗКИ (T-20261106-77/4, вариант А): 4 товара, у которых привязка проверила свою выложенную
    # модель, а `mesh_rep` давал представителя семьи — сторож отбрасывал их («сцена грузит X, привязка проверила Y»)
    four = {'112923:11782445784173503451': '112923_1040856729758645941',    # Теджонс Латте (шкаф)
            '112923:17736893906656810861': '112923_5969868554069204915',    # Ханна 105x80 Латте
            '112923:10046668357069746202': '112923_5177956365797043847',    # Монсон Латте
            '112923:212644341625369693': '112923_13224664101879413845'}     # Модерн Терракотовый
    _rep = F._MESH_REP
    try:
        F._MESH_REP = {k.replace(':', '_', 1): r for k, r in four.items()} | {'112923_7': '112923_8'}
        F._MESH_IDX = {k.replace(':', '_', 1) for k in four} | set(four.values()) | {'112923_8'}
        g4 = F.bedroom_mesh_gate({k: row('ready', True, k) for k in four})
        ms = {k: g4.msid(k.replace(':', '_', 1)) for k in four}
        check('модель сцены спальни = модель привязки: 4 товара (Теджонс/Ханна/Монсон Латте, Модерн) — своя модель, годны',
              all(ms[k] == k.replace(':', '_', 1) for k in four)
              and all(g4({'sid': k.replace(':', '_', 1), 'msid': ms[k]}) == '' for k in four))
        check('прежнее правило (представитель семьи) — те же 4 отброшены «сцена грузит …»',
              all(g4({'sid': k.replace(':', '_', 1), 'msid': F._MESH_REP.get(k.replace(':', '_', 1))}).startswith('сцена грузит')
                  for k in four))
        check('записи привязки нет — представитель семьи (запасной путь)', g4.msid('112923_7') == '112923_8')
        # T-77/5 шаг 3: гостиная — то же правило (`_msid` = `scene_msid` по привязке сборки), без записи — представитель
        _rows = F._BIND_ROWS
        F._BIND_ROWS = {'112923:11782445784173503451': row('ready', True, '112923:11782445784173503451')}
        check('гостиная: `_msid` — модель привязки; записи нет — представитель семьи',
              F._msid('112923_11782445784173503451') == '112923_11782445784173503451'
              and F._msid('112923_7') == '112923_8' and F._msid(None) is None)
        # blocked-привязка указывает на свой артикул, а файла модели нет (49 строк гостиной, сухой прогон T-77/5 шаг 3) —
        # сцена берёт представителя, а не пустое место
        F._BIND_ROWS = {'112923:7': dict(row('blocked', False, '112923:7', ('passport_mismatch',)), local_3d=False)}
        check('гостиная: blocked-привязка без файла модели (local_3d=false) — представитель семьи, не свой артикул',
              F._msid('112923_7') == '112923_8')
        F._BIND_ROWS = {'112923:7': dict(row('blocked', False, '112923:7', ('orientation_review_pending',)), local_3d=True)}
        check('гостиная: blocked-привязка С файлом — модель привязки (её судьбу решает сторож комнаты/индекс прода)',
              F._msid('112923_7') == '112923_7')
        F._BIND_ROWS = _rows
    finally:
        F._MESH_REP = _rep
    os.environ[F.BEDROOM_MESH_GATE_ENV] = '0'
    check('сторож сборки: BEDROOM_MESH_GATE=0 — выключен (откат)', F.bedroom_mesh_gate({}) is None)
finally:
    F._MESH_IDX = _idx
    os.environ.pop(F.BEDROOM_MESH_GATE_ENV, None)
print('итог:', 'FAIL' if fails else 'OK')
sys.exit(1 if fails else 0)
