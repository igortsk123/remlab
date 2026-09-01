#!/usr/bin/env python3
"""Регламент приоритета как ИСПОЛНЯЕМАЯ проверка — без БД, сети и GPU.

Правило владельца 01.09: сначала демо flat215, потом позиции готовых сетов, потом вся
прочая мебель, потом свет и декор. Здесь оно закреплено так, чтобы молчаливое расхождение
кода и `rules/mesh-priority.json` было невозможно.

Запуск: ~/venvs/scout/bin/python tests_priority.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mesh_priority as MP  # noqa: E402


def fake(prod, demo, sets, alts=None):
    """Подменяем ТОЛЬКО источники данных: правило считается настоящим кодом."""
    MP.products = lambda: prod
    MP.demo_skus = lambda: demo
    MP.sets_data = lambda: (sets, alts or {})


def case_regulation_matches_code() -> None:
    """Каждый ярус регламента обязан быть реализован, и в том же порядке."""
    r = MP.rules()
    assert [t['id'] for t in r['tiers']] == list(MP.TIER_IDS), r['tiers']
    for t in r['tiers']:
        assert t.get('why'), f'ярус {t["id"]} без обоснования — регламент должен объяснять'
    print('  ✓ ярусы регламента и кода совпадают, у каждого есть обоснование')


def case_owner_order() -> None:
    """Порядок владельца соблюдается: демо → сеты → мебель → свет/декор."""
    prod = {
        'a:1': {'role': 'диван', 'status': 'none'},      # демо
        'b:2': {'role': 'стул', 'status': 'none'},       # в сете
        'c:3': {'role': 'комод', 'status': 'none'},      # мебель
        'd:4': {'role': 'люстра', 'status': 'none'},     # свет
        'e:5': {'role': 'ваза', 'status': 'none'},       # декор
    }
    fake(prod, {'a:1'}, {'s1': {'b:2'}})
    order = [x['tier'] for x in MP.rank()]
    assert order == ['demo_flat215', 'set_closure', 'furniture', 'light_decor',
                     'light_decor'], order
    print('  ✓ порядок владельца: демо → сеты → мебель → свет и декор')


def case_cheapest_set_first() -> None:
    """Внутри сетов вперёд идёт тот, чей сет ДЕШЕВЛЕ достроить.

    Это главный вывод замера 01.09: сет полезен только целиком, поэтому «частая роль
    вперёд» даёт меньше готовых сетов, чем «дешёвый сет вперёд»."""
    prod = {f'x:{i}': {'role': 'стул', 'status': 'none'} for i in range(1, 6)}
    # s_cheap не хватает одного меша, s_dear — четырёх
    fake(prod, set(), {'s_cheap': {'x:1'}, 's_dear': {'x:2', 'x:3', 'x:4', 'x:5'}})
    first = MP.rank()[0]
    assert first['sku'] == 'x:1', [r['sku'] for r in MP.rank()]
    assert 'не хватает 1' in first['reason'], first['reason']
    print('  ✓ первым идёт товар, закрывающий сет целиком')


def case_ready_does_not_block() -> None:
    """Готовый меш не считается недостающим: сет с одним готовым дешевле."""
    prod = {'x:1': {'role': 'стул', 'status': 'ready'},
            'x:2': {'role': 'стол', 'status': 'none'},
            'y:1': {'role': 'стул', 'status': 'none'},
            'y:2': {'role': 'стол', 'status': 'none'}}
    fake(prod, set(), {'s1': {'x:1', 'x:2'}, 's2': {'y:1', 'y:2'}})
    todo = [x for x in MP.rank() if x['status'] != 'ready']
    assert todo[0]['sku'] == 'x:2', [t['sku'] for t in todo]
    print('  ✓ уже готовые позиции удешевляют свой сет, а не блокируют его')


def case_alternates_before_plain_furniture() -> None:
    """Замены опубликованных сетов идут раньше прочей мебели: закрывают дефицит подмен."""
    prod = {'a:1': {'role': 'комод', 'status': 'none'},
            'b:2': {'role': 'комод', 'status': 'none'}}
    fake(prod, set(), {}, {'b:2': {'s1'}})
    order = [x['sku'] for x in MP.rank()]
    assert order[0] == 'b:2', order
    print('  ✓ замены вперёд обычной мебели')


def case_light_and_decor_last() -> None:
    """Свет и декор — хвост, даже если их в каталоге больше всех (люстр 2422)."""
    prod = {f'l:{i}': {'role': 'люстра', 'status': 'none'} for i in range(50)}
    prod['f:1'] = {'role': 'шкаф', 'status': 'none'}
    fake(prod, set(), {})
    assert MP.rank()[0]['sku'] == 'f:1'
    assert MP.rank()[-1]['tier'] == 'light_decor'
    print('  ✓ массовость роли не поднимает свет и декор из хвоста')


def case_stable_order() -> None:
    """Порядок детерминированный: два прогона на тех же данных дают одно и то же."""
    prod = {f'x:{i}': {'role': 'стул', 'status': 'none'} for i in range(30)}
    fake(prod, set(), {'s1': {'x:1', 'x:2'}})
    assert [r['sku'] for r in MP.rank()] == [r['sku'] for r in MP.rank()]
    print('  ✓ порядок детерминированный (стабильный tie-break по sku)')


def case_every_row_explained() -> None:
    """У каждой позиции есть ярус и причина: очередь должна быть объяснимой."""
    prod = {'a:1': {'role': 'диван', 'status': 'none'},
            'b:2': {'role': 'ваза', 'status': 'none'}}
    fake(prod, set(), {})
    for x in MP.rank():
        assert x['tier'] in MP.TIER_IDS and x['reason'], x
        assert x['policy_version'] >= 1
    print('  ✓ каждая позиция объяснена ярусом, причиной и версией регламента')


def main() -> None:
    for fn in (case_regulation_matches_code, case_owner_order, case_cheapest_set_first,
               case_ready_does_not_block, case_alternates_before_plain_furniture,
               case_light_and_decor_last, case_stable_order, case_every_row_explained):
        fn()
    print('регламент приоритета: ВСЁ ЗЕЛЁНОЕ')


if __name__ == '__main__':
    main()
