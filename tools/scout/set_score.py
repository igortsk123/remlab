#!/usr/bin/env python3
"""Оценка комплекта ЦЕЛИКОМ: смотрим на набор, а не на каждый предмет по отдельности.

Сборщик выбирает лучшего в каждой роли, и из шести по отдельности удачных вещей выходит комплект,
в котором три узора, весь глянец и ни одного тёплого пятна. Дизайнер так не работает: он смотрит,
как вещи живут вместе.

Правила ниже — не вкусовщина, а то, что повторяется во всех руководствах по составлению интерьера
и что мы теперь можем проверить, потому что после обогащения у каждого товара есть материал,
отделка, узор, визуальная масса и теплота (К2).

  ~/venvs/scout/bin/python set_score.py 21        # разбор одного комплекта
  ~/venvs/scout/bin/python set_score.py --all     # сводка по всем
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import enrich_bridge as EB  # noqa: E402

SETS = os.path.join(HERE, 'sets3.json')
# крупные роли задают характер комнаты, мелочь его только поддерживает
BIG = {'диван', 'кресло', 'комод', 'стеллаж', 'стенка', 'витрина', 'тв-тумба', 'шкаф', 'ковёр'}
SMALL = {'ваза', 'статуэтка', 'подушка', 'подушка 2', 'подушка 3', 'плед', 'кашпо', 'часы'}
MASS = {'лёгкая': 1, 'средняя': 2, 'тяжёлая': 3}


def _facts(it: dict) -> dict:
    e = EB.get(it.get('mid'), it.get('eid')) or {}
    ph = e.get('photo') or {}
    return {'materials': e.get('materials') or [], 'mass': e.get('mass'),
            'warmth': e.get('warmth'), 'colour': e.get('colour'),
            'finish': ph.get('finish'), 'pattern': ph.get('pattern')}


def score(setn: int, sets: list) -> dict:
    s = sets[setn - 1]
    items = {r: dict(it, **_facts(it)) for r, it in s['items'].items()}
    notes, pts = [], []

    # 1. Материалы: у набора должна быть общая нить, но не один материал на всё
    mats = [m for it in items.values() for m in (it['materials'] or [])]
    uniq = set(mats)
    shared = sum(1 for m in uniq if mats.count(m) >= 2)
    if not mats:
        notes.append('материалы неизвестны — оценить нечем')
    elif shared == 0:
        pts.append(3.0)
        notes.append('ни один материал не повторяется — набор рассыпается')
    elif len(uniq) <= 2:
        pts.append(6.0)
        notes.append(f'всего {len(uniq)} материала на весь комплект — однообразно')
    else:
        pts.append(9.0)

    # 2. Визуальная масса: крупное должно быть тяжелее мелкого, и всё разом лёгким не бывает
    big = [MASS.get(it['mass'], 0) for r, it in items.items() if r in BIG and it['mass']]
    small = [MASS.get(it['mass'], 0) for r, it in items.items() if r in SMALL and it['mass']]
    if big:
        if small and sum(small) / len(small) > sum(big) / len(big):
            pts.append(4.0)
            notes.append('мелочь тяжелее крупной мебели — комната читается перегруженной понизу')
        elif sum(big) / len(big) < 1.5:
            pts.append(6.0)
            notes.append('вся крупная мебель «лёгкая» — комнате не за что зацепиться')
        else:
            pts.append(9.0)

    # 3. Теплота: одна доминанта плюс акцент, а не поровну тёплого и холодного
    warm = sum(1 for it in items.values() if it['warmth'] == 'тёплая')
    cold = sum(1 for it in items.values() if it['warmth'] == 'холодная')
    if warm and cold:
        ratio = min(warm, cold) / max(warm, cold)
        if ratio > 0.6:
            pts.append(4.0)
            notes.append(f'тёплого и холодного поровну ({warm} и {cold}) — гамма не читается')
        else:
            pts.append(9.0)
    elif warm or cold:
        pts.append(8.0)

    # 4. Отделка: сплошной глянец выглядит дёшево, сплошной мат — плоско
    fins = [it['finish'] for it in items.values() if it['finish'] and it['finish'] != 'неясно']
    if len(fins) >= 3:
        gl = fins.count('глянцевый') / len(fins)
        if gl > 0.6:
            pts.append(4.0)
            notes.append('больше половины предметов глянцевые')
        elif gl == 0:
            pts.append(7.0)
            notes.append('ни одной блестящей поверхности — не хватает контраста фактур')
        else:
            pts.append(9.0)

    # 5. Узор: одно-два узорных пятна, остальное однотонное
    pats = [it['pattern'] for it in items.values()
            if it['pattern'] and it['pattern'] not in ('однотонный', 'неясно', 'текстура_дерева')]
    if len(pats) > 2:
        pts.append(3.0)
        notes.append(f'узорных предметов {len(pats)} — они спорят друг с другом')
    else:
        pts.append(9.0)

    # 6. Цвет: доминанта и акценты, а не пёстрое собрание
    cols = [it['colour'] for it in items.values() if it['colour'] and it['colour'] != 'не_определён']
    if cols:
        base = sum(1 for c in set(cols) if cols.count(c) >= 2)
        if len(set(cols)) > 5 and base < 2:
            pts.append(4.0)
            notes.append(f'{len(set(cols))} разных цветов и ни одного повторяющегося')
        else:
            pts.append(9.0)

    total = round(sum(pts) / max(len(pts), 1), 1) if pts else 0.0
    return {'set': setn, 'score': total, 'notes': notes,
            'style': s.get('style'), 'band': s.get('band'), 'tier': s.get('tier'),
            'items': len(items)}


def main() -> None:
    sets = json.load(open(SETS))
    if '--all' in sys.argv:
        rows = [score(i, sets) for i in range(1, len(sets) + 1)]
        rows.sort(key=lambda r: r['score'])
        avg = sum(r['score'] for r in rows) / len(rows)
        print(f'комплектов: {len(rows)}; средняя оценка набора: {avg:.1f} из 10\n')
        buckets: dict[str, int] = {}
        for r in rows:
            for n in r['notes']:
                key = n.split('—')[0].strip()[:52]
                buckets[key] = buckets.get(key, 0) + 1
        print('что чаще всего не так:')
        for k, v in sorted(buckets.items(), key=lambda kv: -kv[1]):
            print(f'  {v:>4}  {k}')
        print('\nхудшие комплекты:')
        for r in rows[:6]:
            print(f'  {r["set"]:>3} ({r["style"]}, {r["band"]} м², {r["tier"]}): {r["score"]}')
            for n in r['notes']:
                print(f'        · {n}')
        return
    n = int(sys.argv[1])
    r = score(n, sets)
    print(f'комплект {n} ({r["style"]}, {r["band"]} м², {r["tier"]}), позиций {r["items"]}')
    print(f'оценка набора: {r["score"]} из 10')
    for note in r['notes']:
        print(f'  · {note}')
    if not r['notes']:
        print('  замечаний нет')


if __name__ == '__main__':
    main()
