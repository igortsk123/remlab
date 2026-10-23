"""Свой запасной набора — первым для ушедшей роли ядра, и он не делает хуже прежнего (T-20261023-10). Без сети, базы и солвера.

23.10 лофт выпал из демо: диван «Этен Мини» снят, в ленте замен «диван/лофт» пусто, а в наборе 10 лежал свой запасной «Викс»
(в продаже, модель готова). Теперь дозаполнение берёт сперва свои запасные (`demo_fill.own_spares`), потом пул. Свой запасной
проходит ворота, но может не дать расстановку («современный», набор 6: столик 120×58 вытеснил торшер) — тогда тот же набор с
прежним дозаполнением из пула пробуется раньше следующего набора. Проверяем настоящие `fill_banks` и `choose_banks` на заглушках:
  1) набор со своим запасным → два кандидата подряд: со своим запасным, затем тот же набор только из пула; без запасных — один;
  2) свой запасной не расставился → выбран тот же набор из пула, а не следующий набор стиля;
  3) расставился → выбран он, журнал помечает источник «запасной набора».
    python3 tools/scout/tests/test_demo_own_spare.py"""
import os
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
fails = 0


def check(name, cond, extra=''):
    global fails
    print(('OK   ' if cond else 'FAIL ') + name + (f' — {extra}' if extra and not cond else ''))
    fails += 0 if cond else 1


import demo_fill as DF  # noqa: E402
import flat215_demo as F  # noqa: E402

CAT = {('1', 'sofa-gone'): {'state': 'gone', 'w': 180, 'd': 90},
       ('1', 'spare'): {'state': 'available', 'name': 'Викс', 'w': 198, 'd': 90, 'h': 83, 'img': '//s', 'url': 'u', 'price': 1},
       ('2', 'pool-sofa'): {'state': 'available', 'name': 'Диван пула', 'w': 190, 'd': 95, 'h': 80, 'img': '//p', 'price': 1}}
for r in ('столик', 'тв-тумба', 'ковёр', 'торшер'):
    CAT[('1', r)] = {'state': 'available', 'w': 100, 'd': 160 if r == 'ковёр' else 50, 'img': '//x', 'price': 1}


def media(mid, eid):
    return CAT.get((str(mid), str(eid)), {'state': 'available', 'w': 50, 'd': 50, 'img': '//y'})


def kit(n, style, sofa, alts):
    items = {'диван': {'mid': 1, 'eid': sofa, 'name': 'Диван ' + sofa, 'w': 180}}
    items.update({r: {'mid': 1, 'eid': r, 'name': r, 'w': 100} for r in ('столик', 'тв-тумба', 'ковёр', 'торшер')})
    return {'band': '14-16', 'style': style, 'items': items, 'alternates': {'диван': alts}, 'gaps': [], 'n': n}


STUBS = {
    'catalog_media': types.SimpleNamespace(media=media),
    'img_alive': types.SimpleNamespace(alive_now=lambda url: True),
    'footprint': types.SimpleNamespace(footprint_known=lambda m: True),
    'item_function': types.SimpleNamespace(subtype=lambda b, c: None),
    'proportions': types.SimpleNamespace(check=lambda b, c, ctx, sub: (True, 0, [])),
    'sets_incremental': types.SimpleNamespace(_card=lambda c, old: {k: c.get(k) for k in ('mid', 'eid', 'name', 'w', 'd', 'h')}),
    'mesh_dark': types.SimpleNamespace(family_colour_mismatch=lambda sid, msid: None),
    'unfit': types.SimpleNamespace(unfit=lambda *a, **k: None),
    'catalog_rules': types.SimpleNamespace(availability=lambda m: 'available' if (m or {}).get('state') == 'available'
                                           else 'unavailable'),
}
keep_mods = {k: sys.modules.get(k) for k in STUBS}
keep_f = {k: getattr(F, k) for k in ('_mesh_index', 'color_ok', 'bench_pool', 'drop_lonely_nook', 'solve_layouts', 'layout_ok',
                                     'layout_path', '_write_demo_sets', '_msid')}
keep_pool = DF.load_pool
sys.modules.update(STUBS)
F._mesh_index = lambda: {'1_spare', '2_pool-sofa', '1_столик', '1_тв-тумба', '1_торшер'}
F._msid = lambda sid: sid
F.color_ok = lambda msid, name: True
F.bench_pool = lambda sets, rows=None: {}
F.drop_lonely_nook = lambda s, benches: None
DF.load_pool = lambda: [{'mid': '2', 'eid': 'pool-sofa', 'role': 'диван', 'style': 'лофт', 'name': 'Диван пула', 'w': 190, 'd': 95,
                         'h': 80, 'img': '//p', 'price': 1}]
td = tempfile.mkdtemp(prefix='demo-own-spare-')
try:
    sets = [kit(1, 'лофт', 'sofa-gone', [{'mid': 1, 'eid': 'spare'}]), kit(2, 'лофт', 'sofa-gone', [])]
    ranked = F.fill_banks(sets)
    lo = ranked.get('лофт') or []
    order = [(i, k[-1]) for k, i, s, j in lo]
    check('набор со своим запасным — два кандидата подряд (свой, затем только пул); без запасных — один',
          order[:2] == [(1, 0), (1, 1)] and order.count((2, 0)) == 1 and (2, 1) not in order, order)
    own = lo[0]
    check('кандидат со своим запасным: диван «Викс», журнал — «запасной набора»',
          own[2]['items']['диван']['eid'] == 'spare' and any(x.get('source') == 'запасной набора' for x in own[3]))
    check('тот же набор без своих запасных: диван из пула, без пометки',
          lo[1][2]['items']['диван']['eid'] == 'pool-sofa' and not any(x.get('source') for x in lo[1][3]))

    def choose(fit):
        """`fit(s)` — встала ли расстановка у варианта, который сейчас лежит в наборе."""
        cur = {}
        F._write_demo_sets = lambda ss: cur.update(sets=ss)
        F.solve_layouts = lambda flat, only=None: None
        F.layout_path = lambda n: os.path.join(td, f'layout{n}.json')
        F.layout_ok = lambda n, core=(): fit(cur['sets'][n - 1])
        banks, journal, incomplete = F.choose_banks({}, [dict(s) for s in sets], {'лофт': lo})
        return banks, journal, cur['sets']
    banks, journal, ss = choose(lambda s: s['items']['диван']['eid'] != 'spare')
    check('свой запасной не расставился → тот же набор из пула, а не следующий набор',
          banks == [1] and ss[0]['items']['диван']['eid'] == 'pool-sofa', (banks, ss[0]['items']['диван']['eid']))
    banks, journal, ss = choose(lambda s: True)
    check('расставился → выбран свой запасной, журнал помечает источник',
          banks == [1] and ss[0]['items']['диван']['eid'] == 'spare'
          and any(x.get('source') == 'запасной набора' for x in journal.get('set1', [])))
finally:
    for k, v in keep_mods.items():
        if v is None:
            sys.modules.pop(k, None)
        else:
            sys.modules[k] = v
    for k, v in keep_f.items():
        setattr(F, k, v)
    DF.load_pool = keep_pool

print('итог:', 'FAIL' if fails else 'OK')
sys.exit(1 if fails else 0)
