#!/usr/bin/env python3
"""ОТЧЁТ КАТАЛОГА ДЕТСКОЙ (план kids-room-01 шаг 1, T-20261107-43/1): возраст × стиль × роль × семейство — хватит ли товаров на
два набора детской двух заметно разных стилей (на стиль ≥ 2 семейства каждой основной роли: кровать, стол, стул; не хватает —
один стиль). Только чтение базы DEV, бесплатно.

Годный товар роли — в показе (`room_catalog.shown_where`: цена, живое фото, оффер в последнем свежем фиде), с честными
размерами (`footprint_ok`: у кровати — габарит ≠ спальное место, у стола и стула — Ш×Г×В полные и правдоподобные) и с
назначением возраста по правилам (`room_catalog.purposes_of`, вилки — `rules/bedroom-roles.json` purposes; растущая мебель —
диапазон высоты из заметки размеров).

Стиль — ТОЛЬКО бесплатная ступень «правила» (`style_rules.rule_score`: слова стиля в названии и ярлыке магазина «Стиль»,
дерево/металл/ткань, правила по материалу): оценки нейросети у детских ролей нет (`style_score.py --source room_catalog`
берёт только взрослые роли). Товар «в стиле», если балл ≥ `STYLE_MIN` и не ниже лучшего стиля товара больше чем на
`STYLE_NEAR`. Цвет — семейство палитры опроса по названию и цвету фида (`rules/quiz.json` palettes.dictionary_ru).

    ~/venvs/scout/bin/python kids_catalog_report.py [--age 7-12] [--json OUT]
    python3 kids_catalog_report.py --selftest        # чистые функции, без базы
"""
from __future__ import annotations

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MAIN = ('кровать', 'стол', 'стул')                  # основные роли набора детской (план, правки Codex)
KIDS_ROLE = {'кровать': 'кровать детская', 'стол': 'стол детский', 'стул': 'стул детский'}
ADULT_ROLE = {'стол': 'стол рабочий', 'стул': 'стул рабочий'}   # справка: взрослым ребёнку можно только teen (правила)
STYLE_MIN = 2.5          # одно слово стиля (или ярлык магазина) — 2.5 по шкале правил
STYLE_NEAR = 1.0
MIN_FAMILIES = 2
# «что если» (НЕ правило, гипотеза для ведущего): взрослый рабочий стул в детскую 7–12 — та же вилка высоты, что у детского
# стула возраста (`purposes` правил), и компактный (Ш ≤ WHAT_IF_CHAIR_W, см); детских стульев в каталоге — 2 семейства
WHAT_IF_CHAIR_W = 65
_NOTE_H = re.compile(r'растущая: высота (\d+)–(\d+)')


def h_min_of(note: str | None) -> float | None:
    """Низ диапазона растущей мебели — из заметки размеров (`room_catalog.dims_of`: «растущая: высота 52–76»)."""
    m = _NOTE_H.search(note or '')
    return float(m.group(1)) if m else None


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
    """None — товар годен в детскую возраста; иначе причина (честные размеры, назначение)."""
    import room_catalog as RC
    if not row['ok']:
        return 'размеры не честные'
    d = {'w': row['w'], 'd': row['d'], 'h': row['h'], 'sw': row['sw'], 'sl': row['sl'], 'ok': row['ok'],
         'h_min': h_min_of(row['note'])}
    if purpose not in RC.purposes_of(row['role'], d, R):
        return f'не {purpose} по размерам'
    return None


def what_if_rows(rows: list) -> list:
    """Взрослые рабочие стулья как детские (роль подменена — вилка возраста та же), только компактные: «что если»."""
    return [dict(r, role=KIDS_ROLE['стул']) for r in rows
            if r['role'] == ADULT_ROLE['стул'] and r['w'] is not None and r['w'] <= WHAT_IF_CHAIR_W]


def table(rows: list, purpose: str, R: dict, styles: dict, dictionary: dict, mrules: list) -> dict:
    """{основная роль: {стиль|'—': {'items': n, 'families': {семейство: n}, 'price': [min, max], 'colours': {…}}}} + отсев."""
    import room_catalog as RC
    import style_rules as SR
    out = {m: {} for m in MAIN}
    drop: dict = {}
    for r in rows:
        main = next((m for m, kr in KIDS_ROLE.items() if kr == r['role']), None)
        if main is None:
            continue
        why = eligible(r, purpose, R)
        if why:
            drop[(main, why)] = drop.get((main, why), 0) + 1
            continue
        p = dict(name=r['name'], mat=r['mat'], col=r['col'], uph=r['uph'], stp=r['stp'], desc='')
        sts = styles_of(SR.rule_score(p, styles, mrules)) or ['—']
        fam = f"{r['shop']}|{RC.family(r['name'])}"
        col = colour_of(r['name'] + ' ' + r['col'], dictionary) or '?'
        for st in sts:
            c = out[main].setdefault(st, {'items': 0, 'families': {}, 'price': [None, None], 'colours': {}})
            c['items'] += 1
            c['families'][fam] = c['families'].get(fam, 0) + 1
            c['colours'][col] = c['colours'].get(col, 0) + 1
            lo, hi = c['price']
            c['price'] = [r['price'] if lo is None else min(lo, r['price']), r['price'] if hi is None else max(hi, r['price'])]
    return {'by_role': out, 'dropped': {f'{m}: {w}': n for (m, w), n in sorted(drop.items())}}


def propose(by_role: dict, styles: list) -> dict:
    """Пары стилей, где у КАЖДОЙ основной роли ≥ MIN_FAMILIES семейств; иначе — одиночные стили; иначе — узкое место.
    Порядок — по наименьшему числу семейств в роли (сначала самые обеспеченные)."""
    fams = {st: min(len((by_role[m].get(st) or {}).get('families', {})) for m in MAIN) for st in styles}
    full = [st for st in styles if fams[st] >= MIN_FAMILIES]
    pairs = sorted(((a, b) for i, a in enumerate(full) for b in full[i + 1:]), key=lambda ab: (-min(fams[ab[0]], fams[ab[1]]), ab))
    short = {st: [m for m in MAIN if len((by_role[m].get(st) or {}).get('families', {})) < MIN_FAMILIES] for st in styles}
    return {'min_families': fams, 'pairs': [list(p) for p in pairs], 'singles': full, 'short': short}


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
    purpose = f'child:{age}'
    rows, fresh = load(list(KIDS_ROLE.values()) + list(ADULT_ROLE.values()))
    mr = R.get('style_material_rules', [])
    kids = [r for r in rows if r['role'] in KIDS_ROLE.values()]
    T = table(kids, purpose, R, styles, dictionary, mr)
    W = table(kids + what_if_rows(rows), purpose, R, styles, dictionary, mr)
    adult = {m: sum(1 for r in rows if r['role'] == ADULT_ROLE[m] and r['ok']) for m in ADULT_ROLE}
    return dict(purpose=purpose, fresh_feed=fresh, rows=len(kids), adult_honest=adult,
                proposal=propose(T['by_role'], list(styles)),
                what_if={'chairs': W['by_role']['стул'], 'proposal': propose(W['by_role'], list(styles))}, **T)


def _rows_of(m: str, by: dict) -> list:
    L = []
    for st, c in sorted(by.items(), key=lambda kv: -len(kv[1]['families'])):
        fams = ', '.join(f"{f.split('|', 1)[1]} ({n})" for f, n in sorted(c['families'].items(), key=lambda kv: -kv[1]))
        cols = ' '.join(f'{k} {v}' for k, v in sorted(c['colours'].items(), key=lambda kv: -kv[1]))
        L.append(f"{m} | {st} | {c['items']} | {len(c['families'])} | {c['price'][0]:,.0f}–{c['price'][1]:,.0f} | {cols} | {fams}")
    return L


def _proposal(P: dict) -> list:
    return ['меньше всего семейств по ролям (кровать/стол/стул) на стиль: '
            + ', '.join(f'{st} {n}' for st, n in P['min_families'].items()),
            'пары стилей (≥ 2 семейства каждой роли): ' + ('; '.join(' + '.join(p) for p in P['pairs']) or 'нет'),
            'одиночные стили: ' + (', '.join(P['singles']) or 'нет'),
            'не хватает: ' + '; '.join(f"{st} — {', '.join(r)}" for st, r in P['short'].items() if r)]


def text(rep: dict) -> str:
    L = [f"Детская {rep['purpose']}: товаров в показе {rep['rows']} (свежий фид {rep['fresh_feed']}); стиль — правила, без нейросети",
         '', 'роль | стиль | товаров | семейств | цена, ₽ | цвет | семейства']
    for m in MAIN:
        L += _rows_of(m, rep['by_role'][m])
    L += ['', 'отсеяно: ' + '; '.join(f'{k} {v}' for k, v in rep['dropped'].items()),
          'справка — взрослых с честными размерами (ребёнку по правилам только teen): '
          + ', '.join(f'{ADULT_ROLE[m]} {n}' for m, n in rep['adult_honest'].items()), '']
    L += _proposal(rep['proposal'])
    L += ['', f"ЧТО ЕСЛИ (гипотеза, не правило): + взрослый «{ADULT_ROLE['стул']}» в вилке детского стула возраста и Ш ≤ "
          f"{WHAT_IF_CHAIR_W} см"] + _rows_of('стул', rep['what_if']['chairs']) + _proposal(rep['what_if']['proposal'])
    return '\n'.join(L)


def _selftest() -> int:
    bad = 0

    def ok(name, cond):
        nonlocal bad
        print(('OK   ' if cond else 'FAIL ') + name)
        bad += not cond
    ok('низ растущей — из заметки', h_min_of('размеры …; растущая: высота 52–76') == 52.0 and h_min_of('') is None)
    ok('стиль: порог и «рядом с лучшим»', styles_of({'сканди': 4.5, 'современный': 2.5, 'лофт': 0.0}) == ['сканди']
       and styles_of({'сканди': 3.0, 'современный': 2.5}) == ['сканди', 'современный'] and styles_of({'сканди': 1.0}) == [])
    D = {'белый': 'light', 'дуб': 'warm', 'розов': 'accent'}
    ok('цвет — первое слово в тексте', colour_of('Кровать Белый/Дуб', D) == 'light' and colour_of('Розовый', D) == 'accent'
       and colour_of('Серый', D) is None)
    by = {'кровать': {'сканди': {'families': {'a': 1, 'b': 1}}, 'лофт': {'families': {'c': 1}}},
          'стол': {'сканди': {'families': {'a': 1, 'b': 1}}, 'лофт': {'families': {'c': 1, 'd': 1}}},
          'стул': {'сканди': {'families': {'a': 1, 'b': 1}}}}
    P = propose(by, ['сканди', 'лофт'])
    ok('предложение: пара только где у всех ролей ≥ 2; лофт — нехватка кровати и стула',
       P['pairs'] == [] and P['singles'] == ['сканди'] and P['short']['лофт'] == ['кровать', 'стул'])
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
