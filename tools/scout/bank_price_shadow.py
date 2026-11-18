"""ТЕНЬ банка наборов на общих ценовых ступенях (T-20261118-61/6, план `plans/price-segments-01.md` шаг 3): сравнение двух сборок
(прежние перцентили → ступени из `rules/price-segments.json`) БЕЗ записи в банк. Сборки делаются отдельно — `compose2.py` /
`compose_bedroom.py` / `compose_hall.py` с `BANK_PRICE_SEGMENTS=0|1` и выходом ВНЕ банка (`SETS_OUTPUT` / `ROOM_SETS_OUTPUT`); этот
модуль только читает два файла и считает: сколько ячеек и наборов меняется, по ролям и стилям, сколько позиций вне своей ступени
(было → стало), примеры. Модуль чистый (без БД и сети).

  python3 bank_price_shadow.py --old OLD.json --new NEW.json [--kind living|bedroom|hall] [--live LIVE.json] [--json out.json]
  python3 bank_price_shadow.py --selftest
"""
import json
import os
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bank_tiers as BT  # noqa: E402
import price_tiers as PT  # noqa: E402

TIER_KEY = BT.BANK_TIERS    # эконом/комфорт/премиум → lo/mid/hi


def cell_key(s: dict, kind: str) -> tuple:
    """Ячейка набора: гостиная — (полоса, стиль, ступень); комнаты — поле `cell` (комната|назначение|полоса|стиль|ступень)."""
    if kind == 'living':
        return (s.get('band'), s.get('style'), s.get('tier'))
    return tuple((s.get('cell') or '|'.join(str(s.get(k)) for k in ('room_id', 'purpose', 'band', 'style', 'tier'))).split('|'))


def load_bank(path: str) -> list:
    d = json.load(open(path, encoding='utf-8'))
    return d if isinstance(d, list) else (d.get('sets') or [])


def sid_of(it: dict) -> str:
    return str(it.get('sid') or f"{it.get('mid')}:{it.get('eid')}")


def base(role: str) -> str:
    return BT.base_role(role)


def position_tier(role: str, price, rules=None):
    """Ступень позиции набора по её цене и границам роли (None — у роли нет границ)."""
    return PT.tier_of(base(role), price, rules)


def outside(bank: list, rules=None) -> tuple:
    """(позиций с границами роли, из них вне ступени своей ячейки, примеры). Роль без границ не считается — судить не по чему."""
    n = bad = 0
    ex = []
    for s in bank:
        want = TIER_KEY.get(s.get('tier'))
        for role, it in (s.get('items') or {}).items():
            got = position_tier(role, it.get('price'), rules)
            if got is None or want is None:
                continue
            n += 1
            if got != want:
                bad += 1
                if len(ex) < 400:
                    ex.append((role, s.get('tier'), got, it.get('price'), it.get('name')))
    return n, bad, ex


def outside_by_role(bank: list, rules=None) -> dict:
    """{роль: [позиций с границами, из них вне ступени ячейки]} — где ступень на деле не держится (мягкие роли и добор без ступени)."""
    out: dict = {}
    for s in bank:
        want = TIER_KEY.get(s.get('tier'))
        for role, it in (s.get('items') or {}).items():
            got = position_tier(role, it.get('price'), rules)
            if got is None or want is None:
                continue
            c = out.setdefault(base(role), [0, 0])
            c[0] += 1
            c[1] += got != want
    return out


def class_stats(bank: list, rules=None, cfg=None) -> dict:
    """По классу роли (strict/budgeted/exempt): позиций с границами, вне своей ступени, нарушений правила класса (strict — не своя
    ступень, budgeted — дальше соседней, exempt — не проверяется). Класс None (роль без класса) — под ключом «без класса»."""
    out: dict = {}
    for s in bank:
        want = TIER_KEY.get(s.get('tier'))
        for role, it in (s.get('items') or {}).items():
            if not it or it.get('alt'):
                continue
            got = position_tier(role, it.get('price'), rules)
            if got is None or want is None:
                continue
            c = out.setdefault(BT.role_class(role, cfg) or 'без класса', {'позиций': 0, 'вне своей ступени': 0, 'нарушений': 0})
            c['позиций'] += 1
            c['вне своей ступени'] += got != want
            c['нарушений'] += BT.tier_violation(role, s.get('tier'), it.get('price'), rules, cfg) is not None
    return out


def identical(old: list, new: list, kind: str) -> dict:
    """Золотая проверка выкл-режима: состав наборов совпадает? Ячейка равна, если у каждой роли тот же SKU/sid, количество и цена."""
    O = {cell_key(s, kind): s for s in old}
    N = {cell_key(s, kind): s for s in new}
    sig = lambda s: sorted((r, sid_of(it), int(it.get('qty') or 1), it.get('price')) for r, it in (s.get('items') or {}).items() if it)  # noqa: E731
    diff = [k for k in sorted(set(O) & set(N), key=str) if sig(O[k]) != sig(N[k])]
    return {'cells_old': len(O), 'cells_new': len(N), 'gone': sorted(set(O) - set(N), key=str), 'came': sorted(set(N) - set(O), key=str),
            'different': diff, 'ok': not diff and set(O) == set(N)}


def compare(old: list, new: list, kind: str, rules=None) -> dict:
    """Было → стало по ячейкам: изменённые, пропавшие/появившиеся, по ролям, стилям, ступеням; позиции вне ступени; примеры."""
    O = {cell_key(s, kind): s for s in old}
    N = {cell_key(s, kind): s for s in new}
    both = sorted(set(O) & set(N), key=str)
    changed = []                                    # (ячейка, {роль: (было, стало)})
    by_role = Counter()
    by_style = Counter()
    by_tier = Counter()
    by_role_kind = defaultdict(Counter)             # роль → {'сменилась','появилась','пропала'}
    ex = defaultdict(list)
    lost = defaultdict(list)                        # роль → ячейки, где позиции не стало (роль пропала из набора)
    for k in both:
        a, b = O[k].get('items') or {}, N[k].get('items') or {}
        diff = {}
        for role in sorted(set(a) | set(b)):
            sa, sb = sid_of(a[role]) if role in a else None, sid_of(b[role]) if role in b else None
            if sa != sb:
                diff[role] = (a.get(role), b.get(role))
                by_role[base(role)] += 1
                by_role_kind[base(role)]['сменилась' if sa and sb else 'появилась' if sb else 'пропала'] += 1
                if sa and not sb:
                    lost[base(role)].append('/'.join(map(str, k)))
                if len(ex[base(role)]) < 2:
                    ex[base(role)].append((k, a.get(role), b.get(role)))
        if diff:
            changed.append((k, diff))
            by_style[k[-2]] += 1
            by_tier[k[-1]] += 1
    gone, came = sorted(set(O) - set(N), key=str), sorted(set(N) - set(O), key=str)
    rel = lambda L: sum(1 for s in L if s.get('tier_relaxed'))  # noqa: E731
    on, ob, _ = outside(old, rules)
    nn, nb, _ = outside(new, rules)
    fb = sorted({base(r) for s in new for r in (s.get('items') or {}) if BT.band_source(base(r), rules) == 'legacy'})
    return {'cells_old': len(O), 'cells_new': len(N), 'both': len(both), 'changed_cells': len(changed), 'gone': [list(k) for k in gone],
            'came': [list(k) for k in came], 'by_role': dict(by_role.most_common()), 'by_role_kind': {r: dict(c) for r, c in by_role_kind.items()},
            'by_style': dict(by_style.most_common()), 'by_tier': dict(by_tier.most_common()),
            'positions_old': [on, ob], 'positions_new': [nn, nb], 'relaxed_old': rel(old), 'relaxed_new': rel(new),
            'total_old': sum(s.get('total') or 0 for s in old), 'total_new': sum(s.get('total') or 0 for s in new),
            'fallback_roles': fb, 'lost': dict(lost), 'classes_old': class_stats(old, rules), 'classes_new': class_stats(new, rules),
            'unavailable_by_style': dict(Counter(k[-2] for k in gone)), 'unavailable_by_tier': dict(Counter(k[-1] for k in gone)),
            'outside_by_role': {r: [outside_by_role(old, rules).get(r, [0, 0]), outside_by_role(new, rules).get(r, [0, 0])]
                                for r in sorted(set(outside_by_role(old, rules)) | set(outside_by_role(new, rules)))},
            'examples': {r: [{'cell': list(k), 'was': (a or {}).get('name') and [a.get('name'), a.get('price')], 'now': (b or {}).get('name') and [b.get('name'), b.get('price')]}
                             for k, a, b in v] for r, v in ex.items()}}


def lines(r: dict, title: str, limit_roles: int = 40) -> list:
    out = [f'{title}: ячеек было {r["cells_old"]}, стало {r["cells_new"]}; общих {r["both"]}, из них набор изменился в {r["changed_cells"]}'
           f' ({100 * r["changed_cells"] // max(1, r["both"])} %); пропало ячеек {len(r["gone"])}, появилось {len(r["came"])}']
    if r['gone']:
        out.append('  пропали ячейки: ' + '; '.join('/'.join(map(str, c)) for c in r['gone'][:12]))
    if r['came']:
        out.append('  появились ячейки: ' + '; '.join('/'.join(map(str, c)) for c in r['came'][:12]))
    a, b = r['positions_old'], r['positions_new']
    out.append(f'  позиций с границами роли: было {a[0]}, вне ступени своей ячейки {a[1]} ({100 * a[1] // max(1, a[0])} %) → стало {b[0]}, вне ступени {b[1]} '
               f'({100 * b[1] // max(1, b[0])} %); «ослаблена ступень» (прежний пересчёт в стиле): было {r["relaxed_old"]}, стало {r["relaxed_new"]}')
    out.append(f'  сумма наборов: было {r["total_old"]:,} ₽, стало {r["total_new"]:,} ₽'.replace(',', ' '))
    out.append('  по ступеням (изменённых ячеек): ' + ', '.join(f'{k} {v}' for k, v in r['by_tier'].items()))
    out.append('  по стилям (изменённых ячеек): ' + ', '.join(f'{k} {v}' for k, v in r['by_style'].items()))
    out.append('  по ролям (позиций изменилось: сменилась/появилась/пропала):')
    for role, n in list(r['by_role'].items())[:limit_roles]:
        c = r['by_role_kind'][role]
        out.append(f'    {role}: {n} ({c.get("сменилась", 0)}/{c.get("появилась", 0)}/{c.get("пропала", 0)})')
        for e in r['examples'].get(role, [])[:1]:
            out.append(f'      пример {"/".join(map(str, e["cell"]))}: было {e["was"]} → стало {e["now"]}')
    out.append('  вне ступени ячейки по ролям (было → стало, из позиций):')
    for role, (a2, b2) in sorted(r['outside_by_role'].items(), key=lambda x: -x[1][1][1])[:14]:
        out.append(f'    {role}: {a2[1]}/{a2[0]} → {b2[1]}/{b2[0]}')
    for role, cells in r['lost'].items():
        if len(cells) <= 12 and role in ('диван', 'кровать', 'кресло', 'шкаф', 'комод', 'стеллаж'):
            out.append(f'  роль пропала из набора · {role}: ' + '; '.join(cells))
    out.append('  по классам ролей (позиций с границами · вне своей ступени · нарушений правила класса), было → стало:')
    for c in ('strict', 'budgeted', 'exempt', 'без класса'):
        a1, b1 = r['classes_old'].get(c), r['classes_new'].get(c)
        if a1 or b1:
            f = lambda x: f"{x['позиций']} · {x['вне своей ступени']} · {x['нарушений']}" if x else '—'  # noqa: E731
            out.append(f'    {c}: {f(a1)} → {f(b1)}')
    if r['gone']:
        out.append('  недоступных ячеек по стилям: ' + ', '.join(f'{k} {v}' for k, v in sorted(r['unavailable_by_style'].items()))
                   + '; по ступеням: ' + ', '.join(f'{k} {v}' for k, v in sorted(r['unavailable_by_tier'].items())))
    if r['fallback_roles']:
        out.append('  роли без границ (запасной путь прежними квантилями): ' + ', '.join(r['fallback_roles']))
    return out


def _selftest() -> int:
    bad = 0
    R = {'version': 't', 'roles': {'диван': {'boundaries_rub': [50000, 90000], 'families': 100, 'method': 'local'}}}
    mk = lambda tier, price, sid: {'band': '10', 'style': 'сканди', 'tier': tier, 'total': price, 'items': {'диван': {'sid': sid, 'price': price, 'name': sid}, 'ваза': {'sid': 'v', 'price': 1}}}  # noqa: E731
    old = [mk('эконом', 60000, 'a'), mk('комфорт', 70000, 'b'), mk('премиум', 80000, 'c')]
    new = [mk('эконом', 40000, 'x'), mk('комфорт', 70000, 'b'), mk('премиум', 95000, 'z')]
    r = compare(old, new, 'living', R)
    if r['changed_cells'] != 2 or r['by_role'] != {'диван': 2} or r['by_tier'].get('эконом') != 1:
        bad += 1
        print('  FAIL: изменённые ячейки и роли', r['changed_cells'], r['by_role'])
    if r['positions_old'] != [3, 2] or r['positions_new'] != [3, 0]:
        bad += 1
        print('  FAIL: позиции вне ступени: было (эконом 60000, премиум 80000) вне, стало ни одной', r['positions_old'], r['positions_new'])
    if r['fallback_roles'] != ['ваза'] or not lines(r, 'тест'):
        bad += 1
        print('  FAIL: роль без границ — в запасных; текст отчёта', r['fallback_roles'])
    if compare(old, old[:2], 'living', R)['gone'] != [['10', 'сканди', 'премиум']]:
        bad += 1
        print('  FAIL: пропавшая ячейка')
    if not identical(old, [dict(s) for s in old], 'living')['ok'] or identical(old, new, 'living')['ok'] or identical(old, old[:2], 'living')['ok']:
        bad += 1
        print('  FAIL: золотая проверка: те же наборы — ок, другой SKU или пропавшая ячейка — нет')
    C = {'bank_role_policy': {'strict': ['диван'], 'budgeted': [], 'exempt': ['ваза']}}
    cs = class_stats(new, R, C)
    if cs.get('strict') != {'позиций': 3, 'вне своей ступени': 0, 'нарушений': 0} or class_stats(old, R, C)['strict']['нарушений'] != 2:
        bad += 1
        print('  FAIL: статистика по классам', cs)
    print(f'bank_price_shadow selftest: случаев 6, ошибок {bad}')
    return 1 if bad else 0


def main(argv: list) -> int:
    if '--selftest' in argv:
        return _selftest()
    arg = lambda k, d=None: argv[argv.index(k) + 1] if k in argv else d  # noqa: E731
    old, new, kind = arg('--old'), arg('--new'), arg('--kind', 'living')
    if not old or not new:
        print(__doc__)
        return 2
    O, N = load_bank(old), load_bank(new)
    if '--identical' in argv:     # золотая проверка выкл-режима: состав наборов совпадает (rc 0) или нет (rc 1, расхождения по ячейкам)
        g = identical(O, N, kind)
        print(f"{kind}: ячеек {g['cells_old']} ↔ {g['cells_new']}; {'СОСТАВ ИДЕНТИЧЕН' if g['ok'] else 'РАСХОДИТСЯ'}"
              + ('' if g['ok'] else f": пропало {len(g['gone'])}, появилось {len(g['came'])}, иной состав {len(g['different'])} {['/'.join(map(str, k)) for k in g['different'][:5]]}"))
        return 0 if g['ok'] else 1
    r = compare(O, N, kind)
    print('\n'.join(lines(r, kind)))
    if arg('--live'):
        L = load_bank(arg('--live'))
        n, b, ex = outside(L)
        print(f'живой банк {arg("--live")}: позиций с границами {n}, вне ступени своей ячейки {b} ({100 * b // max(1, n)} %)')
        r['live_outside'] = [n, b]
    if arg('--json'):
        json.dump(r, open(arg('--json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
