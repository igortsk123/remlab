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
RULES = json.load(open(os.path.join(HERE, 'proportions.json')))


def dims(it: dict) -> dict:
    """Габариты товара в сантиметрах плюс производные (площадь следа, высота сиденья)."""
    w = float(it.get('w') or 0)
    d = float(it.get('d') or 0)
    h = float(it.get('h') or 0)
    return {'w': w, 'd': d, 'h': h, 'area': w * d / 10000,
            'seat_h': h * float(RULES['defaults']['seat_h_ratio'])}


def value(path: str, items: dict, room_wall: float):
    role, field = path.split('.')
    if role == 'room':
        return room_wall
    it = items.get(role)
    if not it:
        return None
    return dims(it).get(field)


def check(setn: int, sets: list) -> list[dict]:
    s = sets[setn - 1]
    items = s['items']
    band = str(s.get('band', ''))
    try:
        lo, hi = (float(x) for x in band.split('-'))
        wall = (lo + hi) / 2 ** 0.5 * 100 / 10          # грубая оценка стены по метражу
    except Exception:  # noqa: BLE001 — нет метража: берём типовую стену 4 м
        wall = 400.0
    out = []
    for r in RULES['rules']:
        a = value(r['a'], items, wall)
        b = value(r['b'], items, wall)
        if not a or not b:
            continue
        ratio = a / b
        lo_r, hi_r = r.get('min'), r.get('max')
        ok = (lo_r is None or ratio >= lo_r) and (hi_r is None or ratio <= hi_r)
        out.append({'set': setn, 'id': r['id'], 'what': r['what'], 'ratio': round(ratio, 2),
                    'min': lo_r, 'max': hi_r, 'ok': ok, 'why': r['why'],
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
            rule = next(r for r in RULES['rules'] if r['id'] == rid)
            print(f'{cnt:4d} сетов нарушают · {rule["what"]}')
        return

    n = int(sys.argv[1])
    rows = check(n, sets)
    print(f'комплект {n}\n')
    print(f'{"правило":22s} {"что":46s} {"факт":>6s} {"норма":>12s}   вывод')
    for r in rows:
        norm = (f'{r["min"] or ""}–{r["max"] or ""}').strip('–')
        print(f'{r["id"]:22s} {r["what"][:46]:46s} {r["ratio"]:6.2f} {norm:>12s}   '
              f'{"ок" if r["ok"] else "НЕ ПРОХОДИТ"}')
    bad = [r for r in rows if not r['ok']]
    print(f'\nнарушено правил: {len(bad)} из {len(rows)}')
    for r in bad:
        print(f'  · {r["what"]}: {r["a"]}, {r["b"]} → {r["ratio"]}. {r["why"]}')


if __name__ == '__main__':
    main()
