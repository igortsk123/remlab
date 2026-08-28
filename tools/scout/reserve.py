#!/usr/bin/env python3
"""Резерв замен: сколько у каждого занятого слота готовых подмен — и чего не хватает.

ЧТО СЧИТАЕМ РЕЗЕРВОМ. Не «весь остаток каталога» (так priority 3 в очереди мешей и работал —
это хвост, а не резерв), а `alternates` опубликованных комплектов: compose2 уже отобрал их
теми же воротами, что и основной товар слота — роль, подтип, конверт, цена, качество. То есть
совместимость доказана сборкой, а не переизобретена здесь.

ЗАЧЕМ. Владелец: «вот товары в сетах, а вот товары-заменители, по которым меши УЖЕ готовы».
Замена без готового меша — это дыра в визуализации, а не починка. Значит резерв надо мерить
не количеством запасных, а количеством ГОДНЫХ запасных, и дефицит превращать в спрос на
генерацию. Один товар обычно закрывает много слотов, поэтому спрос считается покрытием
дефицитов, а не «N штук на роль».

НОРМАТИВ (стартовый, калибруется по факту): 2 готовые подмены на слот, 3 для якорных ролей —
у них замена ломает раскладку сильнее всего, 1 для необязательных. Разные магазины
предпочтительны: падение одного фида не должно обнулять резерв слота целиком.

  ~/venvs/scout/bin/python reserve.py            # отчёт покрытия
  ~/venvs/scout/bin/python reserve.py --deficit  # чего не хватает, списком SKU
"""
import collections
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
SETS = os.path.join(HERE, 'sets3.json')

ANCHOR = {'диван', 'тв-тумба', 'стенка', 'стол обеденный'}
OPTIONAL = {'пуф', 'банкетка', 'торшер', 'растение', 'ваза', 'статуэтка', 'кашпо'}


def target_for(role: str) -> int:
    if role in ANCHOR:
        return 3
    if role in OPTIONAL:
        return 1
    return 2


def base_role(slot: str) -> str:
    parts = slot.split(' ')
    return slot if not parts[-1].isdigit() else ' '.join(parts[:-1])


def coverage() -> dict:
    """По каждому (комплект, слот): сколько запасных всего и сколько из них с готовым мешом."""
    try:
        from mesh_ready import mesh_ready
    except Exception:  # noqa: BLE001 — без предиката отчёт бессмыслен, честнее упасть
        raise
    sets = json.load(open(SETS))
    rows = []
    for s in sets:
        sid = s.get('set_id') or '—'
        for slot, alts in (s.get('alternates') or {}).items():
            role = base_role(slot)
            ready = [a for a in alts if mesh_ready(f"{a.get('mid')}:{a.get('eid')}")]
            shops = {a.get('mid') for a in ready}
            rows.append({'set_id': sid, 'slot': slot, 'role': role,
                         'spares': len(alts), 'ready': len(ready),
                         'shops': len(shops), 'target': target_for(role),
                         'missing': [f"{a.get('mid')}:{a.get('eid')}" for a in alts
                                     if not mesh_ready(f"{a.get('mid')}:{a.get('eid')}")]})
    return {'rows': rows, 'sets': len(sets)}


def report() -> None:
    cov = coverage()
    rows = cov['rows']
    if not rows:
        print('запасных в комплектах нет — резерв не с чего считать')
        return
    covered = sum(1 for r in rows if r['ready'] >= r['target'])
    one_shop = sum(1 for r in rows if r['ready'] >= r['target'] and r['shops'] < 2)
    print(f"слотов с запасом: {len(rows)} в {cov['sets']} комплектах")
    print(f"  покрыты нормативом : {covered} ({100 * covered / len(rows):.1f}%)")
    print(f"  из них с одним магазином: {one_shop} — падение фида обнулит резерв слота")
    by = collections.defaultdict(lambda: [0, 0, 0])
    for r in rows:
        b = by[r['role']]
        b[0] += 1
        b[1] += r['ready'] >= r['target']
        b[2] += r['ready']
    print(f"\n{'роль':18}{'слотов':>8}{'покрыто':>9}{'готовых подмен':>16}")
    for role, (n, ok, ready) in sorted(by.items(), key=lambda kv: -kv[1][0])[:16]:
        print(f'{role[:17]:18}{n:8}{ok:9}{ready:16}')


def deficit() -> list[str]:
    """SKU, которых не хватает до норматива — это и есть спрос на генерацию."""
    seen, out = set(), []
    for r in coverage()['rows']:
        if r['ready'] >= r['target']:
            continue
        for sku in r['missing'][:max(0, r['target'] - r['ready'])]:
            if sku not in seen:
                seen.add(sku)
                out.append(sku)
    return out


if __name__ == '__main__':
    if '--deficit' in sys.argv:
        d = deficit()
        print(f'не хватает готовых подмен: {len(d)} товаров')
        for sku in d[:40]:
            print(' ', sku)
    else:
        report()
