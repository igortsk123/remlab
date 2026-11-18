"""МЯГКИЙ КАРАНТИН В ВАРИАНТЕ СПАЛЬНИ (T-20261118-04/12/2, директор): сторож модели (`demo_room.gate_items`) не пустеет из-за серой дыры покраски —
замена только товаром с годным мешем (не мягким, цвет близок к фото), заменить нечем — предмет ОСТАЁТСЯ, строка в `mesh_ok.kept`. Банк и солвер настоящие
(как в `test_demo_room_golden.py`), без сети и базы:  ~/venvs/scout/bin/python tools/scout/tests/test_gate_soft.py"""
import copy
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
import demo_bedroom as DB  # noqa: E402
import flat215_demo as F  # noqa: E402

fails = []


def check(name, cond):
    print(('OK   ' if cond else 'FAIL ') + name)
    if not cond:
        fails.append(name)


bank = DB.load_bank(os.path.join(HERE, 'fixtures', 'sets-bedroom.fixture.json'))
it0 = bank[0]['items']
R = {'w': 597, 'd': 293, 'openings': DB.room_geo('bedroom-1', {'id': 'bedroom-1', 'kind': 'bedroom', 'titleRu': 'Спальня 1', 'areaM2': 17.5}, {'height_cm': 270})['openings'],
     'radiators': DB.room_geo('bedroom-1', {'id': 'bedroom-1', 'kind': 'bedroom', 'titleRu': 'Спальня 1', 'areaM2': 17.5}, {'height_cm': 270})['radiators']}
art = {'_room': R, 'кровать': {'x': 298.5, 'z': 106.5, 'rot': 0, 'w': 174, 'd': 213, 'h': 100},
       'тумба прикроватная': {'x': 298.5 - 87 - 24, 'z': 21, 'rot': 0, 'w': 43, 'd': 42, 'h': 55},
       'шкаф': {'x': 26, 'z': 165.5, 'rot': 90, 'w': 135, 'd': 52, 'h': 200}, 'комод': {'x': 97, 'z': 270, 'rot': 180, 'w': 90, 'd': 46, 'h': 80}}


def sku(items, role):
    it = items.get(role) or items.get(DB.base_role(role))
    return it and {'name': it['name'], 'price': it['price'], 'img': it['img'], 'sid': f"{it['mid']}_{it['eid']}",
                   'msid': f"{it['mid']}_{it['eid']}", 'w': it['w'], 'd': it['d'], 'h': it['h']}


alt = lambda base, eid, **kw: dict(it0[base], eid=eid, name=f'{base} {eid}', **kw)   # noqa: E731
SOFT_SID = '112923_' + it0['тумба прикроватная']['eid']


def run(alts, soft_sids=(SOFT_SID,), repl_ok=lambda s: True, hard=None):
    rec = dict(bank[0], alternates={'тумба прикроватная': alts})
    hard = hard or {}
    gate = lambda s: hard.get(s['sid'], '')   # noqa: E731
    gate.soft = lambda s: bool(s) and s['sid'] in soft_sids
    gate.repl_ok = repl_ok
    gate.kept = []
    items, a, swaps, empty, orient = DB.gate_items(rec, copy.deepcopy(art), sku, F._dims_of, gate)
    return items, swaps, empty, gate.kept


items, swaps, empty, kept = run([alt('тумба прикроватная', 't1')])
sw = [x for x in swaps if x['role'] == 'тумба прикроватная']
check('мягкая тумба + годная замена: заменена, причина названа, не пусто и не «осталась»',
      sw and sw[0]['now'][0] == '112923_t1' and sw[0]['why'].startswith('серая дыра') and items['тумба прикроватная']['eid'] == 't1' and not kept and not empty)
items, swaps, empty, kept = run([])
check('единственный кандидат слота во флаге (замен нет): предмет остался, вариант не пустеет, строка kept',
      items['тумба прикроватная']['eid'] == it0['тумба прикроватная']['eid'] and not [e for e in empty if e['role'] == 'тумба прикроватная']
      and [k['role'] for k in kept] == ['тумба прикроватная'] and not swaps)
items, swaps, empty, kept = run([alt('тумба прикроватная', 't1')], repl_ok=lambda s: False)
check('замена есть, но цвет меша не как на фото (repl_ok нет) — не ставим, предмет остаётся', items['тумба прикроватная']['eid'] == it0['тумба прикроватная']['eid'] and kept and not swaps)
items, swaps, empty, kept = run([alt('тумба прикроватная', 't1')], soft_sids=(SOFT_SID, '112923_t1'))
check('замена сама в мягком карантине — не ставим (меняем серую на серую), предмет остаётся', items['тумба прикроватная']['eid'] == it0['тумба прикроватная']['eid'] and kept and not swaps)
bad = {SOFT_SID: 'привязка blocked'}
items, swaps, empty, kept = run([alt('тумба прикроватная', 't1')], soft_sids=('112923_t1',), hard=bad)
check('жёстко негодная модель: замена мягкой лучше пустой роли — берём, но с пометкой в kept (via)', items['тумба прикроватная']['eid'] == 't1' and not empty
      and [k.get('via') for k in kept] == ['замена жёстко негодной'])
items, swaps, empty, kept = run([], soft_sids=(), hard=bad)
check('жёстко негодная и заменить нечем — роль пустая, как раньше (мягкая политика её не трогает)', 'тумба прикроватная' not in items and [e['role'] for e in empty] == ['тумба прикроватная'])
import room_bindings as RB  # noqa: E402
check('политика: grey_top — мягкая причина; SQL мягкого и жёсткого карантина не пересекаются и покрывают прежнее cut/reject',
      RB.soft_policy().get('soft_reasons') == ['grey_top'] and "reasons,'') in ('grey_top')" in RB.soft_sql() and RB.soft_sql() in RB.hard_sql()
      and "coalesce(decision,'cut') in ('cut','reject')" in RB.hard_sql() and 'not (decision is null' in RB.hard_sql())
check('QUARANTINE_SQL (блок привязки) — только жёсткие: мягкую строку исключает', ('not ' + RB.soft_sql()) in RB.QUARANTINE_SQL)
tbl = {'1:a': (29.5, 0.2), '1:b': (4.0, 2.0), '1:c': (14.9, 9.9), '1:d': (15.1, 1.0)}
check('colour_close: ΔL 29,5 (графитовый столик светлее фото) — не верим; близкий — верим; на пороге — верим; нет замера — верим',
      not RB.colour_close('1_a', tbl, {'replace_dL': 15, 'replace_dab': 10}) and RB.colour_close('1_b', tbl, {'replace_dL': 15, 'replace_dab': 10})
      and RB.colour_close('1:c', tbl, {'replace_dL': 15, 'replace_dab': 10}) and not RB.colour_close('1:d', tbl, {'replace_dL': 15, 'replace_dab': 10})
      and RB.colour_close('9:z', tbl, {}))
idx = RB.ProdIndex({'a', 'b'})
check('ProdIndex: soft по умолчанию пуст, quarantined пуст', not idx.soft and not idx.quarantined)
print('итог:', 'чисто' if not fails else f'{len(fails)} падений')
sys.exit(1 if fails else 0)
