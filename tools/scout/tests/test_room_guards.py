#!/usr/bin/env python3
"""Сторожа кандидата банка комнаты (room-bank-01 этап Г, T-20261106-93; Codex «Обязательные тесты» этапа Г).

ЗАЧЕМ. Ночью банк спальни (затем прихожей) должен обновляться без человека: ячейка кандидата подменяет живую только чистой и
целиком, за ночь — не больше четверти. Здесь — каждый сторож на хорошем и плохом входе, без базы и сети:
  • strict по текущему каталогу: наличие, ссылка, фото (и мёртвое), роль, цена, размеры по воротам сборщика, штук, итог;
  • готовность моделей по стратегии профиля: 3D-роли ждут годную привязку, ковёр/шторы/плед/лампа/зеркало — нет; orient ↔ strict;
  • экзамен фактической ячейки: размеры каталога → planner.validate HARD = 0, всё солверное в расстановке, не меньше живой;
  • порядок ступеней цены; демо-сторож old/hybrid (пропал вариант, новый incomplete, ядро, dims_unknown, модель);
  • план: без изменений / отказ / ждёт / подмена / отложено, приоритет (сломанная живая → витрина), предел 25 %, ячейка целиком;
  • ночь: строка DIGEST одна на комнату, прихожая — «показа нет», `room_bootstrap check --night` зовёт сторожей и не падает.
Срез настоящих данных — `fixtures/room_guards.json` (2 ячейки спальни одной группы, 1 прихожей и товары их составов; собран
из кандидатов сухого прогона T-93 и каталога того же часа).
"""
from __future__ import annotations

import contextlib
import copy
import dataclasses
import io
import json
import os
import sys
import tempfile
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))  # tools/scout — помощник временного
import remlab_tmp  # noqa: E402
remlab_tmp.use('test_room_guards')  # временное теста — на диске, не в /tmp; папка убирается при выходе (T-20261107-13)

SCOUT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SCOUT)

import catalog_items as CI  # noqa: E402
import compose_bedroom as CB  # noqa: E402
import compose_hall as CH  # noqa: E402
import room_bootstrap as RBO  # noqa: E402
import room_guards as G  # noqa: E402
import room_ready as RR  # noqa: E402

FIX = json.load(open(os.path.join(SCOUT, 'tests', 'fixtures', 'room_guards.json'), encoding='utf-8'))
RB_, RH_ = CB.rules(), CH.rules()
bad = 0


def ok(name, cond, extra=''):
    global bad
    print(('  ✓ ' if cond else '  ✗ ') + name + (f' — {extra}' if extra and not cond else ''))
    bad += 0 if cond else 1


def has(reasons, text) -> bool:
    return any(text in r for r in reasons)


def cat_of(room: str) -> dict:
    return {d['offer_id']: CI.CatalogItem(**{**d, 'roles': tuple(d['roles'])}) for d in FIX[room]['catalog']}


def rec(room: str, i: int = 0) -> dict:
    return copy.deepcopy(FIX[room]['records'][i])


def tweak(cat: dict, sku: str, **kw) -> dict:
    out = dict(cat)
    c = out[sku]
    if 'dims' in kw:
        kw['dims'] = {**c.dims, **kw['dims']}
    if 'photo' in kw:
        kw['photo'] = {**c.photo, **kw['photo']}
    out[sku] = dataclasses.replace(c, **kw)
    return out


def facts(skus, mode='orient', **over) -> RR.Facts:
    """Привязка: все товары `ready`, выложены, модель сцены = своя и в индексе прода; `over` — {sku: строка привязки | None}."""
    rows = {k: RR._row('ready', k.replace(':', '_', 1), True) for k in skus}
    for k, v in over.items():
        if v is None:
            rows.pop(k, None)
        else:
            rows[k] = v
    return RR.Facts(rows, '', {k.replace(':', '_', 1) for k in skus}, {}, mode)


def all_skus(*recs) -> set:
    return {G.sku_of(it) for s in recs for it in s['items'].values()}


def test_strict():
    print('strict по текущему каталогу')
    b, cat = rec('bedroom'), cat_of('bedroom')
    bed, tb = G.sku_of(b['items']['кровать']), G.sku_of(b['items']['тумба прикроватная'])
    ok('годная ячейка спальни — чиста', G.strict_cell('bedroom', b, cat, RB_) == [], G.strict_cell('bedroom', b, cat, RB_))
    c2 = dict(cat)
    c2.pop(bed)
    ok('товар ушёл из показа — отказ', has(G.strict_cell('bedroom', b, c2, RB_), 'нет в показе каталога'))
    ok('нет в наличии — отказ', has(G.strict_cell('bedroom', b, tweak(cat, bed, in_stock=False), RB_), 'нет в наличии'))
    ok('ссылка сменилась — отказ', has(G.strict_cell('bedroom', b, tweak(cat, bed, url='https://x/new'), RB_), 'ссылка не текущая'))
    ok('фото сменилось — отказ', has(G.strict_cell('bedroom', b, tweak(cat, bed, photo={'best': 'https://x/p.jpg'}), RB_),
                                     'фото не текущее'))
    ok('фото мёртвое — отказ', has(G.strict_cell('bedroom', b, cat, RB_, dead={b['items']['кровать']['img']}), 'фото мёртвое'))
    ok('роль товара в каталоге другая — отказ', has(G.strict_cell('bedroom', b, tweak(cat, bed, roles=('шкаф',)), RB_),
                                                    'роль в каталоге'))
    ok('цена сменилась — отказ', has(G.strict_cell('bedroom', b, tweak(cat, bed, price=1.0), RB_), 'цена'))
    ok('габарит кровати не сверен (footprint_ok) — отказ',
       has(G.strict_cell('bedroom', b, tweak(cat, bed, dims={'footprint_ok': False}), RB_), 'габарит не сверен'))
    ok('размер пропал в каталоге — отказ', has(G.strict_cell('bedroom', b, tweak(cat, bed, dims={'w': None}), RB_), 'нет Ш×Г×В'))
    ok('размер вне полосы слота — отказ', has(G.strict_cell('bedroom', b, tweak(cat, tb, dims={'w': 400.0}), RB_), 'вне'))
    b2 = rec('bedroom')
    b2['items']['тумба прикроватная']['qty'] = 1
    ok('пара: тумба одна при слоте на две — отказ', has(G.strict_cell('bedroom', b2, cat, RB_), 'штук'))
    b3 = rec('bedroom')
    b3['total'] = b3['total'] + 5000
    ok('итог не равен сумме позиций — отказ', has(G.strict_cell('bedroom', b3, cat, RB_), 'итог'))
    h, hc = rec('hall'), cat_of('hall')
    wr = G.sku_of(h['items']['шкаф-купе'])
    ok('годная ячейка прихожей — чиста', G.strict_cell('hall', h, hc, RH_) == [], G.strict_cell('hall', h, hc, RH_))
    ok('прихожая: размеры неправдоподобны (dims_sane) — отказ',
       has(G.strict_cell('hall', h, tweak(hc, wr, dims={'footprint_ok': False}), RH_), 'размеры неправдоподобны'))
    ok('прихожая: шкаф-купе вне полосы типоразмера — отказ',
       has(G.strict_cell('hall', h, tweak(hc, wr, dims={'d': 90.0}), RH_), 'вне полосы'))


def test_ready():
    print('готовность моделей по стратегии профиля')
    ok('спальня: 3D-модель нужна кровати, тумбе, шкафу, комоду, столику; ковёр/шторы/плед/лампа — нет',
       G.mesh_roles('bedroom') == {'кровать', 'тумба прикроватная', 'шкаф', 'комод', 'туалетный столик'}, G.mesh_roles('bedroom'))
    ok('прихожая: зеркало (плоскость) модели не требует',
       G.mesh_roles('hall') == {'шкаф-купе', 'шкаф', 'прихожая', 'обувница', 'банкетка', 'консоль', 'вешалка'}, G.mesh_roles('hall'))
    b = rec('bedroom')
    roles = G.mesh_roles('bedroom')
    skus = all_skus(b)
    bed = G.sku_of(b['items']['кровать'])
    rug = G.sku_of(b['items']['ковёр'])
    ok('все модели годны — готова', G.ready_cell('bedroom', b, facts(skus), roles) == [])
    ok('у ковра модели нет — всё равно готова', G.ready_cell('bedroom', b, facts(skus, **{rug: None}), roles) == [])
    w = G.ready_cell('bedroom', b, facts(skus, **{bed: None}), roles)
    ok('у кровати привязки нет — ждёт, с причиной', [x['role'] for x in w] == ['кровать'] and 'привязка' in w[0]['why'], w)
    w = G.ready_cell('bedroom', b, facts(skus, **{bed: RR._row('ready', bed.replace(':', '_', 1), False)}), roles)
    ok('модель не выложена — ждёт', has([x['why'] for x in w], 'модель не выложена'), w)
    orient = RR._row('blocked', bed.replace(':', '_', 1), reasons=['orientation_review_pending'])
    ok('orient: blocked только по развороту — готова', G.ready_cell('bedroom', b, facts(skus, **{bed: orient}), roles) == [])
    ok('strict (ready + published_3d): тот же разворот — ждёт',
       len(G.ready_cell('bedroom', b, facts(skus, 'strict', **{bed: orient}), roles)) == 1)
    F = facts(skus)
    F.idx.discard(bed.replace(':', '_', 1))
    ok('модели нет в индексе прода — ждёт', has([x['why'] for x in G.ready_cell('bedroom', b, F, roles)], 'нет в индексе прода'))


def test_exam():
    print('экзамен фактической ячейки')
    b, cat = rec('bedroom'), cat_of('bedroom')
    ok('годная ячейка спальни — сдала', G.exam_cell('bedroom', b, cat) == [], G.exam_cell('bedroom', b, cat))
    b2 = rec('bedroom')
    b2['layout']['шкаф'].update(x=b2['layout']['кровать']['x'], z=b2['layout']['кровать']['z'], rot=0)
    ok('шкаф поставлен на кровать — жёсткое нарушение', has(G.exam_cell('bedroom', b2, cat), 'жёсткие нарушения'))
    bed = G.sku_of(b['items']['кровать'])
    ok('кровать в каталоге стала 4 м — жёсткое нарушение (размеры каталога, не записи)',
       has(G.exam_cell('bedroom', b, tweak(cat, bed, dims={'w': 400.0})), 'жёсткие нарушения'))
    b3 = rec('bedroom')
    b3['layout'].pop('комод')
    ok('комод в составе, но не в расстановке — отказ', has(G.exam_cell('bedroom', b3, cat), 'не в расстановке: комод'))
    b4 = rec('bedroom')
    b4['layout'].pop('_room')
    ok('нет комнаты расстановки — отказ', has(G.exam_cell('bedroom', b4, cat), 'нет комнаты'))
    b5 = rec('bedroom')
    b5['items'].pop('комод')
    b5['layout'].pop('комод')
    ok('расставлено меньше, чем в живой ячейке — отказ', has(G.exam_cell('bedroom', b5, cat, old=b), 'расставлено меньше'))
    ok('годная ячейка прихожей — сдала', G.exam_cell('hall', rec('hall'), cat_of('hall')) == [],
       G.exam_cell('hall', rec('hall'), cat_of('hall')))


def test_tiers():
    print('порядок ступеней цены в группе (room_id, purpose, band, style)')
    lo, hi = rec('bedroom', 0), rec('bedroom', 1)
    ok('эконом дешевле комфорта — нарушений нет', G.tier_problems([lo, hi], RB_) == [], G.tier_problems([lo, hi], RB_))
    lo['total'] = hi['total'] + 1
    p = G.tier_problems([lo, hi], RB_)
    ok('эконом дороже комфорта — нарушение с обоими set_id', len(p) == 1 and lo['set_id'] in p[0] and hi['set_id'] in p[0], p)
    hi2 = dict(hi, style='лофт')
    ok('разные стили — не сравниваются', G.tier_problems([lo, hi2], RB_) == [])


def _v(roles, **kw):
    return dict({'items': [{'role': r, 'sku': {'sid': f'1_{r}', 'msid': f'1_{r}'}} for r in roles], 'dims_unknown': []}, **kw)


def test_demo_problems():
    print('демо-сторож old ↔ hybrid (спальня)')
    roles = {'кровать', 'шкаф', 'комод', 'тумба прикроватная'}
    F = facts({f'1:{r}' for r in roles})
    full = _v(['кровать', 'тумба прикроватная', 'шкаф'])
    A, B = {'cell': 'A'}, {'cell': 'B'}
    old = {('r1', 'сканди'): {'rec': A, 'variant': full, 'incomplete': None},
           ('r1', 'лофт'): {'rec': B, 'variant': None, 'incomplete': {'missing': ['тумба прикроватная']}}}
    same = {k: dict(v) for k, v in old.items()}
    ok('ничего не изменилось (старый incomplete остался) — чисто', G.demo_problems(old, same, {'A', 'B'}, F, roles) == {})
    lost = {**same, ('r1', 'сканди'): {'rec': A, 'variant': None, 'incomplete': {'missing': ['кровать']}}}
    ok('вариант пропал — отказ ячейки', has(G.demo_problems(old, lost, {'A'}, F, roles).get('A', []), 'пропал'))
    ok('та же поломка у неподменённой ячейки — не её вина', G.demo_problems(old, lost, {'B'}, F, roles) == {})
    old2 = {('r1', 'сканди'): old[('r1', 'сканди')]}
    new2 = {**old2, ('r2', 'сканди'): {'rec': B, 'variant': None, 'incomplete': {'missing': ['шкаф']}}}
    ok('новый incomplete — отказ', has(G.demo_problems(old2, new2, {'B'}, F, roles).get('B', []), 'новый incomplete'))
    core = {**same, ('r1', 'сканди'): {'rec': A, 'variant': _v(['кровать', 'тумба прикроватная']), 'incomplete': None}}
    ok('ядро: шкаф пропал из 3D — отказ', has(G.demo_problems(old, core, {'A'}, F, roles).get('A', []), 'пропало шкаф'))
    du = {**same, ('r1', 'сканди'): {'rec': A, 'variant': dict(full, dims_unknown=[{'role': 'комод'}]), 'incomplete': None}}
    ok('dims_unknown у размещаемого — отказ', has(G.demo_problems(old, du, {'A'}, F, roles).get('A', []), 'размер неизвестен'))
    Fx = facts({'1:кровать', '1:тумба прикроватная'})
    ok('модель шкафа не годна — отказ', has(G.demo_problems(old, same, {'A'}, Fx, roles).get('A', []), 'шкаф: модель не годна'))
    gone = {('r1', 'лофт'): same[('r1', 'лофт')]}
    ok('стиль комнаты исчез из выбора — отказ «*»', has(G.demo_problems(old, gone, {'A'}, F, roles).get('*', []), 'пропал из выбора'))


def _cells(n, prefix='c'):
    return [{'cell': f'{prefix}{i}', 'set_id': f'id-{prefix}{i}', 'items': {'кровать': {'sid': f'1:{i}', 'qty': 1, 'price': 1}},
             'total': 1} for i in range(n)]


def _changed(s, tag='new'):
    return dict(s, items={'кровать': {'sid': f"9:{s['cell']}{tag}", 'qty': 1, 'price': 1}})


def test_plan():
    print('план: решения, приоритет, предел 25 %, ячейка целиком')
    live = _cells(8)
    cand = [(_changed(s) if i < 5 else copy.deepcopy(s)) for i, s in enumerate(live)]
    broken_live = {'c4'}
    strict = lambda s: (['ушёл'] if (s['cell'] == 'c1' and s['items']['кровать']['sid'].startswith('9:'))   # noqa: E731
                        or (s['cell'] in broken_live and s['items']['кровать']['sid'].startswith('1:')) else [])
    ready = lambda s: [{'role': 'кровать', 'sku': 'x', 'why': 'нет модели'}] if s['cell'] == 'c2' else []   # noqa: E731
    exam = lambda s, old: []   # noqa: E731
    clean = lambda b: []       # noqa: E731
    r = G.plan(live, cand, strict_fn=strict, ready_fn=ready, exam_fn=exam, bank_fn=clean, demo_cells={'c3'})
    d = {x['cell']: x['decision'] for x in r['rows']}
    ok('предел = floor(25 % × 8) = 2', r['cap'] == 2)
    ok('не изменившиеся — «без изменений»', all(d[f'c{i}'] == 'same' for i in range(5, 8)))
    ok('strict — отказ, ждущая модель — «ждёт»', d['c1'] == 'rejected' and d['c2'] == 'waiting')
    ok('приоритет: сломанная живая (c4) → ячейка витрины (c3); c0 — отложена', r['take'] == ['c4', 'c3'] and d['c0'] == 'deferred',
       (r['take'], d))
    hyb = r['hybrid']
    C, L = {s['cell']: s for s in cand}, {s['cell']: s for s in live}
    ok('смешанный банк: подменённые — запись кандидата целиком, прочие — живая целиком, порядок матрицы',
       [s['cell'] for s in hyb] == [s['cell'] for s in cand] and hyb[3] is C['c3'] and hyb[4] is C['c4'] and hyb[0] is L['c0'])
    sixty = _cells(60)
    r = G.plan(sixty, [(_changed(s) if i < 16 else s) for i, s in enumerate(sixty)], strict_fn=lambda s: [],
               ready_fn=lambda s: [], exam_fn=exam, bank_fn=clean)
    ok('граница: 16 годных из 60 → 15 подмен + 1 отложена', len(r['take']) == 15 and G.summary(r).get('deferred') == 1, G.summary(r))
    bank = lambda b: ['id-c3: связка кровать+шкаф повторяет id-c5'] if any(s['cell'] == 'c3' and s['items']['кровать']['sid'].startswith('9:')
                                                                     for s in b) else []   # noqa: E731
    r = G.plan(live, cand, strict_fn=strict, ready_fn=ready, exam_fn=exam, bank_fn=bank, demo_cells={'c3'})
    d = {x['cell']: x for x in r['rows']}
    ok('новое нарушение банка с этой ячейкой — отказ «bank», место берёт следующая', d['c3']['decision'] == 'rejected'
       and d['c3']['kind'] == 'bank' and r['take'] == ['c4', 'c0'], (r['take'], d['c3']))
    old_bad = lambda b: ['id-c6: старое нарушение']   # noqa: E731
    r = G.plan(live, cand, strict_fn=strict, ready_fn=ready, exam_fn=exam, bank_fn=old_bad)
    ok('нарушение, бывшее и в живом банке, подмену не держит', len(r['take']) == 2)
    demo = lambda lv, hyb, take: {'c4': ['вариант пропал']} if 'c4' in take else {}   # noqa: E731
    r = G.plan(live, cand, strict_fn=strict, ready_fn=ready, exam_fn=exam, bank_fn=clean, demo_fn=demo, demo_cells={'c3'})
    d = {x['cell']: x for x in r['rows']}
    ok('демо-сторож снял ячейку — «demo», в смешанном банке её нет', d['c4']['kind'] == 'demo' and 'c4' not in r['take']
       and r['hybrid'][4] is live[4], (r['take'], d['c4']))
    vanish = lambda lv, hyb, take: {'*': ['вариант r1 «лофт» пропал из выбора']} if take else {}   # noqa: E731
    r = G.plan(live, cand, strict_fn=strict, ready_fn=ready, exam_fn=exam, bank_fn=clean, demo_fn=vanish)
    ok('стиль пропал из выбора витрины — сняты ВСЕ подмены ночи', r['take'] == [] and G.summary(r).get('rejected:demo') == 2,
       G.summary(r))


def run_night_lines(*a, **k):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rep, lines = G.night(*a, **k)
    return rep, lines, buf.getvalue()


def test_night():
    print('ночь: вердикт и строка DIGEST')
    h = rec('hall')
    F = facts(all_skus(h))
    rep, L, _ = run_night_lines('hall', [h], None, cat=cat_of('hall'), F=F, R=RH_, tol=CH.tolerance(),
                                gen0_verdict=lambda r, c: [])
    dg = [x for x in L if x.startswith('DIGEST:')]
    ok('прихожая без живого — «поколение 0», одна строка DIGEST последней', len(dg) == 1 and L[-1] == dg[0]
       and 'поколение 0 — годен' in dg[0], L)
    ok('прихожая: демо-сторож пропущен с явной строкой', any('у прихожей показа нет' in x for x in L) and 'демо — нет показа' in dg[0])
    ok('строка DIGEST влезает в сводку (≤ 300 знаков)', len(dg[0]) - len('DIGEST:') <= 300, len(dg[0]))
    rep, L, _ = run_night_lines('bedroom', [rec('bedroom')], [rec('bedroom')], cat=cat_of('bedroom'), F=F, R=RB_,
                                tol=CB.tolerance(), identity_fn=lambda r, c: ['пропали ячейки: 58 из 60'])
    ok('идентичность не та — кандидат не годен целиком, живой не тронут', 'не годен целиком' in L[-1] and rep['take'] == [], L)
    b0, b1 = rec('bedroom', 0), rec('bedroom', 1)
    nb0 = copy.deepcopy(b0)
    nb0['alternates'] = {r: xs[:1] for r, xs in nb0['alternates'].items()}     # запас замен изменился — ячейка «другая»
    F = facts(all_skus(b0, b1))
    rep, L, _ = run_night_lines('bedroom', [nb0, b1], [b0, b1], cat=cat_of('bedroom'), F=F, R=RB_, tol=CB.tolerance(),
                                identity_fn=lambda r, c: [], share=0.5)
    sm = G.summary(rep)
    ok('спальня на настоящих ячейках: строгая проверка запаса замен (spare=hard) не пускает обеднённую ячейку',
       sm.get('rejected:bank') == 1 and sm.get('same') == 1, (sm, L[-3:]))
    nb0 = copy.deepcopy(b0)
    nb0['alternates'] = {r: list(reversed(xs)) for r, xs in nb0['alternates'].items()}
    rep, L, _ = run_night_lines('bedroom', [nb0, b1], [b0, b1], cat=cat_of('bedroom'), F=F, R=RB_, tol=CB.tolerance(),
                                identity_fn=lambda r, c: [], share=0.5)
    ok('спальня: годная ячейка с витриной old/hybrid — подменена (предел 1 при 50 %)', rep['take'] == [b0['cell']], (G.summary(rep), L))
    ok('спальня: строка DIGEST одна, «подменить 1 из 2»', sum(x.startswith('DIGEST:') for x in L) == 1 and 'подменить 1 из 2' in L[-1],
       L[-1])


def test_bootstrap_night():
    print('room_bootstrap check --night зовёт сторожей и не падает')
    called = []
    real = G.run_night
    with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR') or None) as d:
        p = os.path.join(d, 'sets-hall.next.json')
        json.dump([rec('hall')], open(p, 'w', encoding='utf-8'))
        try:
            G.run_night = lambda room, cand, json_out=None, live_path=None, assume_ready=False: called.append((room, cand, live_path))
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                rc = RBO.main(['--room', 'hall', 'check', '--candidate', p, '--night', '--live', '/nope.json'])
            ok('суд + сторожа: код 0, сторожа получили комнату, кандидата и --live', rc == 0 and called == [('hall', p, '/nope.json')],
               (rc, called))

            def boom(*a, **k):
                raise RuntimeError('база легла')
            G.run_night = boom
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                rc = RBO.main(['--room', 'hall', 'check', '--candidate', p, '--night'])
            out = buf.getvalue()
            ok('сторожа упали — WARN и строка DIGEST, код 0 (шаг ночи не роняем)',
               rc == 0 and 'WARN:room_check:hall: сторожа этапа Г упали' in out and 'DIGEST:банк прихожая (сторожа, сухо): упали' in out,
               out[-400:])
        finally:
            G.run_night = real


def main() -> int:
    for t in (test_strict, test_ready, test_exam, test_tiers, test_demo_problems, test_plan, test_night, test_bootstrap_night):
        t()
    print(f"{'OK' if not bad else 'FAIL'} — сторожи кандидата банка комнаты, провалов {bad}")
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
