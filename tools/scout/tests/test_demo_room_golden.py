"""ЭТАЛОН ВИТРИНЫ СПАЛЬНИ (hall-demo-01 этап 3, T-20261106-98): выход функций витрины спальни на заготовке банка — побайтно как до
переноса ядра в `demo_room.py`. Сценарии — те же, что `test_demo_bedroom.py` (солвер спальни настоящий, без сети и базы): варианты
(солвер, готовая расстановка, банк onb-06, сторож модели с заменами и запасом, нерешённый разворот), ленты, полосы, одна расстановка.
Эталон снят на main 62a8e0dd (до переноса) — `fixtures/demo-room-golden.json`; `--write` перезаписывает его (только осознанно).
    ~/venvs/scout/bin/python tools/scout/tests/test_demo_room_golden.py [--write]"""
import copy
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
GOLD = os.path.join(HERE, 'fixtures', 'demo-room-golden.json')

import demo_bedroom as DB  # noqa: E402
import flat215_demo as F  # noqa: E402


def _j(x):
    """Сериализуемый вид: множества — отсортированным списком, кортежи — списком."""
    return json.loads(json.dumps(x, ensure_ascii=False, sort_keys=True, default=lambda o: sorted(o) if isinstance(o, set) else str(o)))


def scenarios() -> dict:
    bank = DB.load_bank(os.path.join(HERE, 'fixtures', 'sets-bedroom.fixture.json'))
    reg = {'id': 'bedroom-1', 'kind': 'bedroom', 'titleRu': 'Спальня 1', 'areaM2': 17.5}
    geo = DB.room_geo('bedroom-1', reg, {'height_cm': 270})
    out = {'geo': geo, 'geo2': DB.room_geo('bedroom-2', {'id': 'bedroom-2', 'titleRu': 'Спальня 2', 'areaM2': 11.2})}

    def sku(items, role):
        it = items.get(role) or items.get(DB.base_role(role))
        return it and {'name': it['name'], 'price': it['price'], 'img': it['img'], 'sid': f"{it['mid']}_{it['eid']}",
                       'msid': f"{it['mid']}_{it['eid']}", 'w': it['w'], 'd': it['d'], 'h': it['h']}

    def bv(rec, **kw):
        return list(DB.build_variant(copy.deepcopy(rec), geo, sku, F._dims_of, F.style_id, **kw))
    out['solver'] = [bv(r) for r in bank]
    out['no_bed'] = bv(dict(bank[0], items={k: x for k, x in bank[0]['items'].items() if k != 'кровать'}))
    out['off_style'] = bv(dict(bank[0], style='бохо'))
    out['layout'] = bv(bank[0], layout={'кровать': {'x': 300, 'z': 102, 'rot': 0}, 'тумба прикроватная': {'x': 200, 'z': 21, 'rot': 0}})
    L = {'_room': {'variant': 'registry-17.5', 'w': 597, 'd': 293, 'openings': geo['openings'], 'radiators': geo['radiators']},
         '_meta': {'solver': 'bedroom-v1'}, 'кровать': {'x': 298.5, 'z': 101.5, 'rot': 0},
         'тумба прикроватная': {'x': 190, 'z': 17.5, 'rot': 0}, 'тумба прикроватная 2': {'x': 407, 'z': 17.5, 'rot': 0},
         'ковёр': {'x': 298.5, 'z': 167.7, 'rot': 0}, 'лампа': {'x': 190, 'z': 17.5, 'elev': 52, 'on': 'тумба прикроватная'},
         'лампа 2': {'x': 407, 'z': 17.5, 'elev': 52, 'on': 'тумба прикроватная 2'}}
    its = {k: x for k, x in bank[0]['items'].items() if k != 'тумба прикроватная 2'}
    its['ковёр'] = dict(its['комод'], name='Ковер Мирна 200x300', w=300, d=200, h=1)
    its['лампа'] = dict(its['комод'], name='Светильник настольный', w=11, d=11, h=38, qty=2)
    rb = dict(bank[0], items=its, layout=L)
    out['onb06'] = bv(rb, decor_role=lambda r: False)
    out['onb06_decor'] = bv(rb, decor_role=lambda r: r.startswith('ковёр'), hung=lambda n: 'Мирна' in (n or ''))
    out['bank_room'] = DB.bank_room([rb], 'bedroom-1')
    tiers = [dict(bank[0], tier=t, set_id=t, purpose=p) for t in ('эконом', 'премиум', 'комфорт') for p in ('guest', 'couple')]
    out['pick'] = [(r['set_id'], r['purpose']) for r in DB.pick_records(tiers, ['bedroom-1'], ['сканди'])]
    out['pick2'] = [(r['room_id'], r['style']) for r in DB.pick_records(bank + [dict(bank[0], room_id='bedroom-2')],
                                                                        ['bedroom-2', 'bedroom-1'], ['современный', 'сканди', 'лофт'])]
    msid = lambda s: s  # noqa: E731
    cat = {'roles': {'кровать': [{'sid': '1:2', 'name': 'Кровать Х 160', 'img': 'x.jpg', 'price': 9, 'w': 170, 'd': 210, 'h': 90}],
                     'ковёр': [{'sid': '1:9', 'name': 'Ковёр Y 200x300', 'img': 'r.jpg', 'price': 5, 'w': 200, 'd': 300}],
                     'шторы': [{'sid': '1:8', 'name': 'Шторы', 'img': 's.jpg', 'price': 3, 'w': 200, 'd': 1}]}}
    out['feeds'] = DB.feeds(bank, cat, msid, lambda s: 'нет в индексе прода' if s['msid'] == '112923_11672424920201226922' else '')
    out['feeds_dead'] = DB.feeds(bank, cat, msid, lambda s: '', alive=lambda u: u != 'x.jpg')
    out['bands'] = {p: DB.bands([p]) for p in ('couple', 'guest', 'single', 'office')}
    out['room_bands'] = DB.room_bands([{'room_id': 'bedroom-1', 'purpose': 'couple'}, {'room_id': 'bedroom-2', 'purpose': 'guest'},
                                       {'room_id': 'bedroom-2', 'purpose': 'single'}], ['bedroom-1', 'bedroom-2'])
    out['merge'] = DB.merge_room_feeds({'ковёр': [{'sid': 'L1'}]}, 'bedroom', {'ковёр': [{'sid': 'B1'}], 'кровать': [{'sid': 'K1'}]})
    out['keys'] = [DB.room_key(r, x) for r, x in (('living', 'ковёр'), ('', 'ковёр'), ('bedroom', 'ковёр'), ('bedroom-2', 'кровать'))]
    out['consts'] = {'SOLVER_ROLES': DB.SOLVER_ROLES, 'PLACE_ROLES': DB.PLACE_ROLES, 'LIST_ROLES': DB.LIST_ROLES,
                     'MESH_FREE_ROLES': DB.MESH_FREE_ROLES, 'ONE_FREE_ROLES': DB.ONE_FREE_ROLES, 'TIER_ORDER': DB.TIER_ORDER,
                     'PURPOSE_ORDER': DB.PURPOSE_ORDER, 'BAND_CM': DB.BAND_CM, 'lead': DB.lead_roles(),
                     'GEO_FILE': os.path.relpath(DB.GEO_FILE, os.path.join(HERE, '..')),
                     'BANK_LIVE': os.path.relpath(DB.BANK_LIVE, os.path.join(HERE, '..')),
                     'neighbours': {s: DB.neighbour_styles(s) for s in ('сканди', 'лофт', 'бохо', 'джапанди')},
                     'variant_id': DB.variant_id('bedroom-2', 'loft'), 'one_rule': DB.one_rule()}

    # одна расстановка (T-32/4)
    R = {'w': 597, 'd': 293, 'openings': L['_room']['openings'], 'radiators': L['_room']['radiators']}

    def art(комод, bed_w=174):
        return {'_room': R, 'кровать': {'x': 298.5, 'z': 106.5, 'rot': 0, 'w': bed_w, 'd': 213, 'h': 100},
                'тумба прикроватная': {'x': 298.5 - bed_w / 2 - 24, 'z': 21, 'rot': 0, 'w': 43, 'd': 42, 'h': 55},
                'шкаф': {'x': 26, 'z': 165.5, 'rot': 90, 'w': 135, 'd': 52, 'h': 200}, 'комод': комод}
    A = {'а': art({'x': 97, 'z': 270, 'rot': 180, 'w': 90, 'd': 46, 'h': 80}),
         'б': art({'x': 485, 'z': 23, 'rot': 0, 'w': 90, 'd': 46, 'h': 80}),
         'в': art({'x': 95.5, 'z': 273, 'rot': 180, 'w': 83, 'd': 40, 'h': 80})}
    out['zones'] = {k: DB.zones(a) for k, a in A.items()}
    out['one'] = list(DB.one_layout(copy.deepcopy(A), ['а', 'б', 'в']))
    blk = dict(A['б'], **{'стол рабочий': {'x': 100, 'z': 263, 'rot': 180, 'w': 100, 'd': 60, 'h': 75}})
    out['one_blk'] = list(DB.one_layout({'а': A['а'], 'б': blk, 'в': A['в']}, ['а', 'б', 'в']))
    out['one_other'] = list(DB.one_layout({'а': A['а'], 'б': dict(A['б'], _room=dict(R, w=618))}, ['а', 'б']))
    out['hard'] = DB.hard_codes(dict(A['б'], комод={'x': 300, 'z': 106, 'rot': 0, 'w': 90, 'd': 46, 'h': 80}), 'couple')

    # сторож модели, запас, разворот
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
    out['gate'] = bv(grec, mesh_ok=gate)
    nob = dict(grec, alternates={})
    out['gate_nob'] = bv(nob, mesh_ok=gate)
    mine2 = dict(grec, room_id='bedroom-2', purpose='guest', alternates={'кровать': [alt('кровать', 'o1')],
                                                                     'тумба прикроватная': [alt('тумба прикроватная', 't2', w=40, d=40)]})
    near = dict(grec, style='джапанди', alternates={'кровать': [alt('кровать', 'n1'), alt('кровать', 'n2', w=120)]})
    far = dict(grec, style='лофт', alternates={'кровать': [alt('кровать', 'f1')]})
    pool = [far, near, nob, mine2]
    sp = DB.role_spares(pool, nob)
    out['spares'] = sp
    out['spares_lead'] = DB.role_spares(pool, nob, DB.lead_roles())
    out['gate_spares'] = bv(nob, mesh_ok=gate, spares=sp)
    bad['112923_o1'] = 'привязка none'
    out['gate_near'] = bv(nob, mesh_ok=gate, spares=DB.role_spares(pool, nob))
    bad['112923_n1'] = 'модель не выложена'
    out['gate_none'] = bv(nob, mesh_ok=gate, spares=DB.role_spares(pool, nob))
    out['gate_lead_pair'] = bv(nob, mesh_ok=gate, spares=sp, lead=('кровать',))
    for k in ('112923_o1', '112923_n1'):
        bad.pop(k)
    og = lambda s: '' if s['sid'] != '112923_' + it0['кровать']['eid'] else 'привязка blocked'   # noqa: E731
    og.note = lambda s: 'orientation_symmetric_by_role' if s['sid'] in ('112923_b1', '112923_' + it0['шкаф']['eid']) else ''
    out['orient'] = bv(grec, mesh_ok=og)
    out['items'] = DB.gate_items(copy.deepcopy(grec), copy.deepcopy(G), sku, F._dims_of, gate, sp)
    return _j(out)


def main() -> int:
    got = scenarios()
    if '--write' in sys.argv:
        json.dump({'_': 'эталон tests/test_demo_room_golden.py: витрина спальни до переноса ядра в demo_room.py (T-20261106-98)',
                   'rev': os.environ.get('GOLDEN_REV', 'worktree'), 'out': got},
                  open(GOLD, 'w', encoding='utf-8'), ensure_ascii=False, indent=1, sort_keys=True)
        print(f'записан {GOLD}: сценариев {len(got)}')
        return 0
    ref = json.load(open(GOLD, encoding='utf-8'))['out']
    bad = [k for k in sorted(set(ref) | set(got)) if ref.get(k) != got.get(k)]
    for k in sorted(set(ref) | set(got)):
        print(('OK   ' if k not in bad else 'FAIL ') + k)
    for k in bad[:3]:
        a = json.dumps(ref.get(k), ensure_ascii=False, sort_keys=True)
        b = json.dumps(got.get(k), ensure_ascii=False, sort_keys=True)
        i = next((n for n, (x, y) in enumerate(zip(a, b)) if x != y), min(len(a), len(b)))
        print(f'  {k}: было …{a[max(0, i - 80):i + 120]}\n  {" " * len(k)}  стало …{b[max(0, i - 80):i + 120]}')
    print(f'витрина спальни golden: сценариев {len(got)}, расхождений {len(bad)}')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
