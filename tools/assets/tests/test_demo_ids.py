#!/usr/bin/env python3
"""Охват лёгких копий моделей витрины (T-20261106-77 Д3, `tools/assets/runtime_mesh.py:demo_ids`): модели вариантов ВСЕХ
комнат витрины, кандидаты лент — по типу комнаты (`rules/demo-swap.json:rt_feed_top`), роли без модели по канону стратегий
ассета (ковёр — плоскость, шторы — спрайт) не требуют копий. Запуск: python tools/assets/tests/test_demo_ids.py"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
import runtime_mesh as RM  # noqa: E402

FAILS = []


def ok(name, cond, extra=''):
    print(('OK   ' if cond else 'FAIL ') + name + (f' — {extra}' if extra and not cond else ''))
    if not cond:
        FAILS.append(name)


def item(role, m):
    return {'role': role, 'sku': {'msid': m}}


def feed(prefix, n):
    return [{'msid': f'{prefix}{i}'} for i in range(n)]


D = {
    'rules': {'soft_roles': ['подушка', 'шторы']},
    'variants': [
        {'id': 'living-a', 'items': [item('диван', 'L1'), item('ковёр', 'RUG1'), item('комод', 'K1')],
         'decor': [{'role': 'ваза', 'sku': {'msid': 'V1'}}, {'role': 'подушка', 'sku': {'msid': 'P1'}}]},
        {'id': 'bedroom-1-scandi', 'room_id': 'bedroom-1',
         'items': [item('кровать', 'B1'), item('тумба прикроватная', 'T1'), item('тумба прикроватная 2', 'T1'),
                   item('ковёр', 'RUG2'), item('комод', 'K2')]},
    ],
    'feeds': {'диван': feed('d', 20), 'кровать': feed('b', 20), 'тумба прикроватная': feed('t', 9), 'комод': feed('k', 15),
              'ковёр': feed('r', 8), 'шторы': feed('s', 4), 'стул': feed('c', 12), 'роль-x': feed('x', 9)},
}
RULE = {'_default': 0, 'living': 6}
STRAT = {'ковёр': 'procedural_plane', 'шторы': 'cutout', 'подушка': 'cutout', '_default': 'hunyuan3d'}

with tempfile.TemporaryDirectory() as tmp:
    p = os.path.join(tmp, 'demo-data.json')
    json.dump(D, open(p, 'w', encoding='utf-8'), ensure_ascii=False)
    tops = RM.feed_tops(D, RULE)
    ok('гостиная — 6 первых', tops['диван'] == 6, tops)
    ok('спальня — вся лента', tops['кровать'] == 0 and tops['тумба прикроватная'] == 0, tops)
    ok('общая роль (комод в гостиной и спальне) — больший охват, вся лента', tops['комод'] == 0, tops)
    ok('роль без варианта, но из профиля гостиной (стул) — 6, как гостиная', tops['стул'] == 6, tops)
    ok('ничья роль — правило _default (вся лента)', tops['роль-x'] == 0, tops)
    ok('роли комнаты — из профиля её типа', 'кресло' in RM.profile_roles('living') and 'кровать' in RM.profile_roles('bedroom')
       and RM.profile_roles('нет-такого') == [])
    only_living = {**D, 'variants': D['variants'][:1]}
    ok('витрина без спальни — комод по правилу гостиной (6)', RM.feed_tops(only_living, RULE)['комод'] == 6)
    ok('тип комнаты: bedroom-1 → bedroom, без id → living', RM.room_type('bedroom-1') == 'bedroom' and RM.room_type(None) == 'living')
    var, fd = RM.demo_ids(p, rule=RULE, strategies=STRAT)
    ok('модели вариантов обеих комнат и декор, без ковра и мягкого', var == ['L1', 'K1', 'B1', 'T1', 'K2', 'V1'], var)
    ok('лента гостиной — первые 6', [x for x in fd if x.startswith('d')] == [f'd{i}' for i in range(6)], fd)
    ok('лента спальни — вся (20 кроватей, 9 тумб)', sum(x.startswith('b') for x in fd) == 20 and sum(x.startswith('t') for x in fd) == 9)
    ok('комод — вся лента (15)', sum(x.startswith('k') for x in fd) == 15)
    ok('ковёр и шторы — без копий (стратегия ассета)', not any(x[0] in 'rs' for x in fd), fd)
    ok('стул — первые 6 (роль гостиной)', sum(x.startswith('c') for x in fd) == 6)
    var6, fd6 = RM.demo_ids(p, 6, rule=RULE, strategies=STRAT)
    ok('явное --feed-top 6 — по 6 у каждой ленты, как раньше', sum(x.startswith('b') for x in fd6) == 6 and var6 == var)
    ok('правило в rules/demo-swap.json читается', isinstance(json.load(open(os.path.join(RM.RULES, 'demo-swap.json'),
                                                                        encoding='utf-8'))['rt_feed_top']['_default'], int))
    ok('ковёр в каноне стратегий — не модель', not RM.mesh_role('ковёр') and RM.mesh_role('кровать'))
    # T-77/2: ленты спальни под ключом комнаты («bedroom:роль»), лампа на тумбе — «только в списке» (в 3D нет, модели нет)
    D2 = {**D, 'variants': [D['variants'][0], {**D['variants'][1], 'decor': [
        {'role': 'лампа', 'list_only': True, 'sku': {'msid': 'LAMP'}}, {'role': 'ваза', 'sku': {'msid': 'V2'}}]}],
        'feeds': {'диван': feed('d', 20), 'bedroom:кровать': feed('b', 20), 'bedroom:ковёр': feed('r', 8), 'ковёр': feed('q', 8)}}
    p2 = os.path.join(tmp, 'demo-data-2.json')
    json.dump(D2, open(p2, 'w', encoding='utf-8'), ensure_ascii=False)
    var2, fd2 = RM.demo_ids(p2, rule=RULE, strategies=STRAT)
    ok('декор «только в списке» (лампа) — без копии; ваза спальни — с копией', 'LAMP' not in var2 and 'V2' in var2, var2)
    ok('ковёр спальни под ключом «bedroom:ковёр» — плоскость, без копий', not any(x[0] in 'rq' for x in fd2), fd2)
    ok('кровать под ключом спальни — вся лента (правило типа комнаты)', sum(x.startswith('b') for x in fd2) == 20
       and RM.feed_tops(D2, RULE)['bedroom:кровать'] == 0 and RM.feed_tops(D2, RULE)['диван'] == 6, RM.feed_tops(D2, RULE))

print(f'\nитог: {"FAIL " + str(len(FAILS)) if FAILS else "всё OK"}')
sys.exit(1 if FAILS else 0)
