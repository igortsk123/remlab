#!/usr/bin/env python3
"""Проверка сета по дизайнерским соотношениям — жёсткий фильтр ДО стилевого рейтинга.

Идея владельца (2026-08-05): сперва отбираем товары, которые вообще сочетаются по размеру, и
только потом ранжируем оставшихся по стилю. Иначе в сет попадает пуф размером со столик, и никакой
стиль этого не спасёт.

Числа не выдуманы: это публичные дизайнерские правила (правило двух третей и производные), с
источниками — `proportions.json`.

  ~/venvs/scout/bin/python proportion_check.py 21
  ~/venvs/scout/bin/python proportion_check.py --all      # по всем сетам, сводка
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))



from proportions import P as RULES_P, metrics  # noqa: E402


_BANDS = {b['band']: b['m2'] for b in
          json.load(open(os.path.join(HERE, 'composition.json')))['bands']}


def wall_of(band: str) -> float:
    """Длина стены метража — по ТОМУ ЖЕ справочнику, что и сборщик.

    Раньше метраж парсился из строки, и «50+» не разбирался: подставлялась стена 4 м, из-за чего
    18 больших сетов числились нарушителями на ровном месте (2026-08-05).
    """
    pair = _BANDS.get(str(band))
    if pair:
        m2 = sum(pair) / 2
    else:
        try:
            lo, hi = (float(x) for x in str(band).split('-'))
            m2 = (lo + hi) / 2
        except Exception:  # noqa: BLE001 — незнакомый метраж: типовая стена 4 м
            return 400.0
    # формула ровно как в сборщике, иначе пограничные сеты «мигают» между проверками
    return float(int((m2 * 10000 / 1.15) ** 0.5 // 5 * 5))


def check(setn: int, sets: list) -> list[dict]:
    """Каждое правило по готовому сету: попадает ли в допустимые и предпочтительные рамки."""
    s = sets[setn - 1]
    items = s['items']
    corner = bool('углов' in str((items.get('диван') or {}).get('name', '')).lower())
    ctx = {'chosen': items, 'wall': wall_of(s.get('band', '')), 'corner_sofa': corner}
    out = []
    from item_function import subtype as _sub
    for r in RULES_P['rules']:
        role = r.get('role')
        it = items.get(role)
        if not it:
            continue
        # исключения по подтипу: пуф-стол живёт по правилам столика, а не пуфа
        if _sub(role, it) in (r.get('only_if_subtype_not') or []):
            continue
        ref_role, field = r['b'].split('.')
        a = metrics(role, it, corner).get(r['a'].split('.')[1])
        if ref_role == 'room':
            b = ctx['wall']
        else:
            other = items.get(ref_role)
            b = metrics(ref_role, other, corner).get(field) if other else None
        if not a or not b:
            continue
        ratio = a / b
        lo, hi = r['allowed']
        plo, phi = r['preferred']
        out.append({'set': setn, 'id': r['id'], 'what': r['what'], 'ratio': round(ratio, 2),
                    'allowed': (lo, hi), 'preferred': (plo, phi),
                    'ok': lo <= ratio <= hi, 'best': plo <= ratio <= phi, 'why': r['why'],
                    'a': f"{r['a']}={a:.0f}", 'b': f"{r['b']}={b:.0f}"})
    return out


def main() -> None:
    sets = json.load(open(os.path.join(HERE, 'sets3.json')))
    if '--all' in sys.argv:
        bad_by_rule: dict[str, int] = {}
        total = 0
        for i in range(1, len(sets) + 1):
            rows = check(i, sets)
            total += 1
            for r in rows:
                if not r['ok']:
                    bad_by_rule[r['id']] = bad_by_rule.get(r['id'], 0) + 1
        print(f'сетов проверено: {total}\n')
        for rid, cnt in sorted(bad_by_rule.items(), key=lambda kv: -kv[1]):
            rule = next(r for r in RULES_P['rules'] if r['id'] == rid)
            print(f'{cnt:4d} сетов нарушают · {rule["what"]}')
        if not bad_by_rule:
            print('нарушений допустимых рамок нет')
        return

    n = int(sys.argv[1])
    rows = check(n, sets)
    print(f'комплект {n}\n')
    print(f'{"правило":22s} {"что":42s} {"факт":>6s} {"допустимо":>12s}   вывод')
    for r in rows:
        norm = f'{r["allowed"][0]}–{r["allowed"][1]}'
        verdict = 'ок, в норме' if r['best'] else ('ок' if r['ok'] else 'НЕ ПРОХОДИТ')
        print(f'{r["id"]:22s} {r["what"][:42]:42s} {r["ratio"]:6.2f} {norm:>12s}   {verdict}')
    bad = [r for r in rows if not r['ok']]
    print(f'\nнарушено правил: {len(bad)} из {len(rows)}')
    for r in bad:
        print(f'  · {r["what"]}: {r["a"]}, {r["b"]} → {r["ratio"]}. {r["why"]}')


if __name__ == '__main__':
    main()
