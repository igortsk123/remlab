#!/usr/bin/env python3
"""ОТЧЁТ КАТАЛОГА ДЕТСКОЙ (план kids-room-01 шаг 1, T-20261107-43/1): возраст × стиль × роль × семейство — хватит ли товаров на
два набора детской двух заметно разных стилей. Только чтение базы DEV, бесплатно.

Правило наборов — ОДНО место: `rules/bedroom-composition.json` purposes[child:<возраст>].kids_sets (ведущий 07.11 для 7–12:
пара «сканди-светлое» + «современный»; семейств на стиль — кровать 2, стол 2, стул 1; стул — детский или взрослый рабочий,
годный возрасту по размеру; стул без слов стиля годен обоим; кровать сканди — только светлая). Нет правила у возраста —
по умолчанию: ≥ 2 семейства каждой роли, стул только детский, без цвета.

Годный товар роли — в показе (`room_catalog.shown_where`: цена, живое фото, оффер в последнем свежем фиде), с честными
размерами (`footprint_ok`) и с назначением возраста по правилам (`room_catalog.row_purposes`, вилки — `rules/bedroom-roles.json`
purposes; растущая мебель — диапазон высоты из заметки размеров). Это тот же отбор, что у каталога по назначению
(`catalog_items.items('bedroom', purpose=…)`).

Стиль — ТОЛЬКО бесплатная ступень «правила» (`style_rules.rule_score`: слова стиля в названии и ярлыке магазина «Стиль»,
дерево/металл/ткань, правила по материалу): оценки нейросети у детских ролей нет, платную не делаем (ведущий 07.11). Товар
«в стиле», если балл ≥ `STYLE_MIN` и не ниже лучшего стиля товара больше чем на `STYLE_NEAR`. Цвет — семейство палитры опроса
по названию и цвету фида (`rules/quiz.json` palettes.dictionary_ru).

    ~/venvs/scout/bin/python kids_catalog_report.py [--age 7-12] [--json OUT]
    python3 kids_catalog_report.py --selftest        # чистые функции, без базы
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MAIN = ('кровать', 'стол', 'стул')                  # основные роли набора детской (план, правки Codex)
KIDS_ROLE = {'кровать': 'кровать детская', 'стол': 'стол детский', 'стул': 'стул детский'}
STYLE_MIN = 2.5          # одно слово стиля (или ярлык магазина) — 2.5 по шкале правил
STYLE_NEAR = 1.0
NEUTRAL = '—'            # нет слов ни одного стиля


def kids_rule(comp: dict, purpose: str, all_styles: list) -> dict:
    """Правило наборов возраста из правил сборки; нет — умолчания (2 семейства на роль, стул только детский)."""
    ks = ((comp.get('purposes') or {}).get(purpose) or {}).get('kids_sets') or {}
    fm = ks.get('families_min') or {}
    return {'styles': ks.get('styles') or list(all_styles),
            'min': {m: int(fm.get(KIDS_ROLE[m] if m != 'стул' else 'стул', fm.get(KIDS_ROLE[m], 2))) for m in MAIN},
            'roles': {'кровать': [KIDS_ROLE['кровать']], 'стол': [KIDS_ROLE['стол']],
                      'стул': ks.get('chair_roles') or [KIDS_ROLE['стул']]},
            'neutral_chair': bool(ks.get('chair_neutral_ok')),
            'colour_only': ks.get('colour_only') or {}, 'from_rules': bool(ks)}


def styles_of(scores: dict) -> list:
    """Стили товара по баллам правил: ≥ STYLE_MIN и рядом с лучшим (STYLE_NEAR); порядок — порядок стилей."""
    if not scores:
        return []
    top = max(scores.values())
    return [st for st, v in scores.items() if v >= STYLE_MIN and v >= top - STYLE_NEAR]


def colour_of(text: str, dictionary: dict) -> str | None:
    """Семейство палитры (light/warm/cool/accent) по первому совпавшему корню словаря опроса; нет — None."""
    t = (text or '').lower()
    hits = [(t.find(root), fam) for root, fam in dictionary.items() if root in t]
    return min(hits)[1] if hits else None


def eligible(row: dict, purpose: str, R: dict) -> str | None:
    """None — товар годен в детскую возраста; иначе причина (честные размеры, назначение). Отбор — как у каталога по
    назначению (`room_catalog.row_purposes`)."""
    import room_catalog as RC
    if not row['ok']:
        return 'размеры не честные'
    if purpose not in RC.row_purposes(row['role'], row['name'], row['w'], row['d'], row['h'], row['sw'], row['sl'],
                                      row['ok'], row['note'], R):
        return f'не {purpose} по размерам'
    return None


def main_of(role: str, rule: dict) -> str | None:
    return next((m for m in MAIN if role in rule['roles'][m]), None)


def table(rows: list, purpose: str, R: dict, styles: dict, dictionary: dict, mrules: list, rule: dict) -> dict:
    """{основная роль: {стиль|'—': {'items': n, 'families': {семейство: n}, 'price': [min, max], 'colours': {…}}}} + отсев.
    Цвет по правилу (`colour_only`: стиль → роль → семейство палитры) — товар другого цвета в этот стиль не идёт."""
    import room_catalog as RC
    import style_rules as SR
    out = {m: {} for m in MAIN}
    drop: dict = {}
    for r in rows:
        main = main_of(r['role'], rule)
        if main is None:
            continue
        why = eligible(r, purpose, R)
        if why:
            drop[(main, why)] = drop.get((main, why), 0) + 1
            continue
        p = dict(name=r['name'], mat=r['mat'], col=r['col'], uph=r['uph'], stp=r['stp'], desc='')
        col = colour_of(r['name'] + ' ' + r['col'], dictionary) or '?'
        found = styles_of(SR.rule_score(p, styles, mrules))
        sts = [] if found else [NEUTRAL]          # ушёл из стиля по цвету — не «без стиля», просто не в наборе
        for st in found:
            want = (rule['colour_only'].get(st) or {}).get(r['role'])
            if want and col != want:
                k = (main, f'{st}: цвет не {want}')
                drop[k] = drop.get(k, 0) + 1
                continue
            sts.append(st)
        fam = f"{r['shop']}|{RC.family(r['name'])}"
        for st in sts:
            c = out[main].setdefault(st, {'items': 0, 'families': {}, 'price': [None, None], 'colours': {}})
            c['items'] += 1
            c['families'][fam] = c['families'].get(fam, 0) + 1
            c['colours'][col] = c['colours'].get(col, 0) + 1
            lo, hi = c['price']
            c['price'] = [r['price'] if lo is None else min(lo, r['price']), r['price'] if hi is None else max(hi, r['price'])]
    return {'by_role': out, 'dropped': {f'{m}: {w}': n for (m, w), n in sorted(drop.items())}}


def families(by_role: dict, m: str, st: str, rule: dict) -> set:
    """Семейства роли в стиле; у стула по правилу — и нейтральные (без слов стиля)."""
    got = set((by_role[m].get(st) or {}).get('families', {}))
    if m == 'стул' and rule['neutral_chair']:
        got |= set((by_role[m].get(NEUTRAL) or {}).get('families', {}))
    return got


def propose(by_role: dict, styles: list, rule: dict) -> dict:
    """Стили, где у КАЖДОЙ основной роли семейств ≥ минимума правила; пары таких стилей; узкие места; проверка пары правила.
    Пары — по запасу (наименьшее отношение семейств к минимуму, сначала самые обеспеченные)."""
    n = {st: {m: len(families(by_role, m, st, rule)) for m in MAIN} for st in styles}
    slack = {st: min(n[st][m] / rule['min'][m] for m in MAIN) for st in styles}
    full = [st for st in styles if slack[st] >= 1]
    pairs = sorted(((a, b) for i, a in enumerate(full) for b in full[i + 1:]), key=lambda ab: (-min(slack[ab[0]], slack[ab[1]]), ab))
    short = {st: [m for m in MAIN if n[st][m] < rule['min'][m]] for st in styles}
    chosen = {st: {'families': n.get(st) or {m: 0 for m in MAIN}, 'ok': st in full} for st in rule['styles']}
    return {'families': n, 'pairs': [list(p) for p in pairs], 'singles': full, 'short': short, 'chosen': chosen}


SQL_COLS = ("role, shop, name, price_rub, w_cm, d_cm, h_cm, sleep_w_cm, sleep_l_cm, coalesce(footprint_ok,false), "
            "coalesce(dims_note,''), last_seen, "
            "concat_ws(' / ', nullif(coalesce(params->>'Материал',params->>'Материал корпуса',params->>'Материал каркаса',''),''), "
            "nullif(coalesce(params->>'Материал фасада',''),'')), coalesce(params->>'Цвет',params->>'Цвет основной',''), "
            "coalesce(params->>'Материал обивки',params->>'Обивка',''), coalesce(params->>'Стиль','')")


def load(roles: list) -> tuple:
    """(строки годных к показу товаров ролей, дата свежего фида)."""
    import catalog_items as CI
    import room_catalog as RC
    R = RC.rules()
    got = CI.fetch(f"select {SQL_COLS} from room_catalog where {RC.shown_where(R)} and role in ("
                   + ','.join(CI._lit(r) for r in roles) + ') order by shop_mid, external_id')
    rows = [dict(role=g[0], shop=g[1] or '', name=g[2] or '', price=float(g[3]), w=CI._f(g[4]), d=CI._f(g[5]), h=CI._f(g[6]),
                 sw=CI._f(g[7]), sl=CI._f(g[8]), ok=g[9] == 't', note=g[10], seen=g[11], mat=g[12] or '', col=g[13] or '',
                 uph=g[14] or '', stp=g[15] or '') for g in got]
    fresh = CI.fetch(f"select max(last_seen) from room_catalog where room='{RC.ROOM}'")[0][0]
    return rows, fresh


def report(age: str) -> dict:
    import room_catalog as RC
    R = RC.rules()
    styles = json.load(open(os.path.join(HERE, 'styles.json'), encoding='utf-8'))['styles']
    dictionary = json.load(open(os.path.join(HERE, 'rules', 'quiz.json'), encoding='utf-8'))['palettes']['dictionary_ru']
    comp = json.load(open(os.path.join(HERE, 'rules', 'bedroom-composition.json'), encoding='utf-8'))
    purpose = f'child:{age}'
    rule = kids_rule(comp, purpose, list(styles))
    rows, fresh = load(sorted({r for rs in rule['roles'].values() for r in rs}))
    T = table(rows, purpose, R, styles, dictionary, R.get('style_material_rules', []), rule)
    by_src = {r: sum(1 for x in rows if x['role'] == r and eligible(x, purpose, R) is None)
              for r in sorted({x['role'] for x in rows})}
    return dict(purpose=purpose, fresh_feed=fresh, rows=len(rows), eligible_by_role=by_src, rule=rule,
                proposal=propose(T['by_role'], list(styles), rule), **T)


def _rows_of(m: str, by: dict) -> list:
    L = []
    for st, c in sorted(by.items(), key=lambda kv: -len(kv[1]['families'])):
        fams = ', '.join(f"{f.split('|', 1)[1]} ({n})" for f, n in sorted(c['families'].items(), key=lambda kv: -kv[1]))
        cols = ' '.join(f'{k} {v}' for k, v in sorted(c['colours'].items(), key=lambda kv: -kv[1]))
        L.append(f"{m} | {st} | {c['items']} | {len(c['families'])} | {c['price'][0]:,.0f}–{c['price'][1]:,.0f} | {cols} | {fams}")
    return L


def text(rep: dict) -> str:
    ru, P = rep['rule'], rep['proposal']
    L = [f"Детская {rep['purpose']}: товаров в показе {rep['rows']} (свежий фид {rep['fresh_feed']}); стиль — правила, без нейросети",
         'годны возрасту по размеру: ' + ', '.join(f'{r} {n}' for r, n in rep['eligible_by_role'].items()),
         f"правило ({'bedroom-composition.json kids_sets' if ru['from_rules'] else 'умолчание'}): стили "
         f"{' + '.join(ru['styles'])}; семейств на стиль — " + ', '.join(f'{m} {n}' for m, n in ru['min'].items())
         + f"; стул — {', '.join(ru['roles']['стул'])}" + ('; нейтральный стул годен всем' if ru['neutral_chair'] else '')
         + ''.join(f"; {st}: {r} только {c}" for st, rc in ru['colour_only'].items() for r, c in rc.items()),
         '', 'роль | стиль | товаров | семейств | цена, ₽ | цвет | семейства']
    for m in MAIN:
        L += _rows_of(m, rep['by_role'][m])
    L += ['', 'отсеяно: ' + '; '.join(f'{k} {v}' for k, v in rep['dropped'].items()), '',
          'ИТОГ ПО ПРАВИЛУ: ' + '; '.join(f"{st} — " + ', '.join(f'{m} {n}' for m, n in c['families'].items())
                                           + (' ✓' if c['ok'] else ' ✗ мало') for st, c in P['chosen'].items()),
          'все стили, годные по правилу: ' + (', '.join(P['singles']) or 'нет'),
          'пары: ' + ('; '.join(' + '.join(p) for p in P['pairs']) or 'нет'),
          'не хватает: ' + ('; '.join(f"{st} — {', '.join(r)}" for st, r in P['short'].items() if r) or 'ничего')]
    return '\n'.join(L)


def _selftest() -> int:
    bad = 0

    def ok(name, cond):
        nonlocal bad
        print(('OK   ' if cond else 'FAIL ') + name)
        bad += not cond
    ok('стиль: порог и «рядом с лучшим»', styles_of({'сканди': 4.5, 'современный': 2.5, 'лофт': 0.0}) == ['сканди']
       and styles_of({'сканди': 3.0, 'современный': 2.5}) == ['сканди', 'современный'] and styles_of({'сканди': 1.0}) == [])
    D = {'белый': 'light', 'дуб': 'warm', 'розов': 'accent'}
    ok('цвет — первое слово в тексте', colour_of('Кровать Белый/Дуб', D) == 'light' and colour_of('Розовый', D) == 'accent'
       and colour_of('Серый', D) is None)
    comp = json.load(open(os.path.join(HERE, 'rules', 'bedroom-composition.json'), encoding='utf-8'))
    r712 = kids_rule(comp, 'child:7-12', ['сканди', 'современный', 'лофт'])
    ok('правило 7–12 — из правил сборки: сканди + современный, кровать 2 / стол 2 / стул 1, стул и взрослый рабочий',
       r712['from_rules'] and r712['styles'] == ['сканди', 'современный'] and r712['min'] == {'кровать': 2, 'стол': 2, 'стул': 1}
       and 'стул рабочий' in r712['roles']['стул'] and r712['colour_only'] == {'сканди': {'кровать детская': 'light'}})
    d = kids_rule(comp, 'child:3-7', ['сканди', 'лофт'])
    ok('нет правила возраста — умолчания', not d['from_rules'] and d['min'] == {'кровать': 2, 'стол': 2, 'стул': 2}
       and d['roles']['стул'] == ['стул детский'] and not d['neutral_chair'])
    by = {'кровать': {'сканди': {'families': {'a': 1, 'b': 1}}, 'лофт': {'families': {'c': 1}}},
          'стол': {'сканди': {'families': {'a': 1, 'b': 1}}, 'лофт': {'families': {'c': 1, 'd': 1}}},
          'стул': {'сканди': {'families': {'a': 1, 'b': 1}}}}
    P = propose(by, ['сканди', 'лофт'], d)
    ok('по умолчанию: лофт — нехватка кровати и стула', P['pairs'] == [] and P['singles'] == ['сканди']
       and P['short']['лофт'] == ['кровать', 'стул'])
    by['стул'] = {NEUTRAL: {'families': {'n': 1}}}
    by['кровать']['лофт']['families']['e'] = 1
    rule = dict(d, styles=['сканди', 'лофт'], min={'кровать': 2, 'стол': 2, 'стул': 1}, neutral_chair=True)
    P = propose(by, ['сканди', 'лофт'], rule)
    ok('стул 1 семейство и нейтральный — годен обоим стилям', P['pairs'] == [['сканди', 'лофт']]
       and all(c['ok'] for c in P['chosen'].values()) and P['families']['лофт']['стул'] == 1)
    print('OK: 0 провалов' if not bad else f'ПРОВАЛОВ: {bad}')
    return 1 if bad else 0


def main(argv: list) -> int:
    if '--selftest' in argv:
        return _selftest()
    age = argv[argv.index('--age') + 1] if '--age' in argv else '7-12'
    rep = report(age)
    print(text(rep))
    if '--json' in argv:
        with open(argv[argv.index('--json') + 1], 'w', encoding='utf-8') as f:
            json.dump(rep, f, ensure_ascii=False, indent=1)
    return 0


if __name__ == '__main__':
    sys.path.insert(0, HERE)
    sys.exit(main(sys.argv[1:]))
