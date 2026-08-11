#!/usr/bin/env python3
"""Майнинг ОФОРМЛЕНИЯ зон из ProcTHOR-10k (Apache 2.0) — заявка владельца 11.08:
как в реальных сценах организуют хранение (комод/стеллаж), медиа-тумбу и чем их
УКРАШАЮТ (напольная зелень/торшеры + декор НА поверхностях), по диапазонам площади.
В прод переносятся только агрегаты; данные датасета остаются референсом.

  ~/venvs/scout/bin/python mine_decor.py    # → decor-mining.json + таблица в чат
"""
import gzip
import json
import math
import os
from collections import Counter, defaultdict

from shapely.geometry import Point, Polygon

SRC = os.path.expanduser('~/datasets/procthor-10k/train.jsonl.gz')

# напольные «якоря» оформления и сами украшения (имена ассетов ProcTHOR)
ANCHORS = {'TV_Stand': 'тв-тумба', 'Dresser': 'комод', 'Shelving': 'стеллаж',
           'Sofa': 'диван', 'Fireplace': 'камин'}
FLOOR_DECOR = {'Houseplant': 'кашпо', 'Floor_Lamp': 'торшер', 'Box': 'коробка'}


def kind(asset: str, table: dict) -> str | None:
    for k, v in table.items():
        if asset.startswith(k) or k.lower() in asset.lower():
            return v
    return None


def band_of(m2: float) -> str:
    for hi, name in ((15, '≤15'), (22, '15-22'), (32, '22-32'), (45, '32-45')):
        if m2 <= hi:
            return name
    return '45+'


def main() -> None:
    n_lr = 0
    decor_per_band = defaultdict(list)          # band → сколько напольного декора
    near_anchor = Counter()                     # (декор, ближайший якорь) в ≤120 см
    dist_bucket = Counter()                     # расстояние декор→якорь
    on_top = defaultdict(Counter)               # якорь → что стоит СВЕРХУ
    on_top_count = defaultdict(list)            # якорь → сколько предметов сверху
    anchors_per_band = defaultdict(Counter)     # band → какие якоря присутствуют
    fireplaces = 0
    with gzip.open(SRC, 'rt') as f:
        for line in f:
            h = json.loads(line)
            lrs = [r for r in h.get('rooms', []) if r.get('roomType') == 'LivingRoom']
            if not lrs:
                continue
            for lr in lrs:
                poly = Polygon([(p['x'], p['z']) for p in lr['floorPolygon']])
                m2 = poly.area
                band = band_of(m2)
                n_lr += 1
                anchors, decors = [], []
                for o in h.get('objects', []):
                    pos = o.get('position') or {}
                    if not poly.contains(Point(pos.get('x', 1e9), pos.get('z', 1e9))):
                        continue
                    aid = o.get('assetId', '')
                    a = kind(aid, ANCHORS)
                    if a:
                        if a == 'камин':
                            fireplaces += 1
                        anchors.append((a, pos['x'], pos['z']))
                        anchors_per_band[band][a] += 1
                        kids = [k.get('assetId', '') for k in (o.get('children') or [])]
                        # декор на поверхности: всё кроме мелочи-мусора
                        deco_kids = [k for k in kids if not any(
                            s in k for s in ('Remote', 'Pencil', 'Pen_', 'CreditCard',
                                             'Keychain', 'Cellphone', 'Watch'))]
                        on_top_count[a].append(len(deco_kids))
                        for k in deco_kids:
                            on_top[a][k.rsplit('_', 1)[0]] += 1
                    d = kind(aid, FLOOR_DECOR)
                    if d:
                        decors.append((d, pos['x'], pos['z']))
                decor_per_band[band].append(len(decors))
                for d, dx, dz in decors:
                    if not anchors:
                        continue
                    best = min(anchors, key=lambda a: math.hypot(a[1] - dx, a[2] - dz))
                    dist = math.hypot(best[1] - dx, best[2] - dz) * 100
                    if dist <= 120:
                        near_anchor[(d, best[0])] += 1
                    dist_bucket[(d, '≤60' if dist <= 60 else '60-120' if dist <= 120
                                 else '120-250' if dist <= 250 else '>250')] += 1
    out = {
        'living_rooms': n_lr, 'fireplaces_found': fireplaces,
        'decor_per_band': {b: round(sum(v) / max(len(v), 1), 2)
                           for b, v in decor_per_band.items()},
        'anchors_per_band': {b: c.most_common() for b, c in anchors_per_band.items()},
        'near_anchor': [[f'{d} у {a}', n] for (d, a), n in near_anchor.most_common(12)],
        'dist_bucket': [[f'{d} {b}', n] for (d, b), n in dist_bucket.most_common(12)],
        'on_top': {a: c.most_common(8) for a, c in on_top.items()},
        'on_top_avg': {a: round(sum(v) / max(len(v), 1), 2)
                       for a, v in on_top_count.items()},
    }
    json.dump(out, open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     'decor-mining.json'), 'w'),
              ensure_ascii=False, indent=1)
    print(f'гостиных: {n_lr}; каминов в датасете: {fireplaces}')
    print('\nСреднее число НАПОЛЬНОГО декора на гостиную по площади:')
    for b in ('≤15', '15-22', '22-32', '32-45', '45+'):
        print(f'  {b} м²: {out["decor_per_band"].get(b, 0)}')
    print('\nЧто рядом с чем (декор в ≤120 см от якоря):')
    for k, n in out['near_anchor']:
        print(f'  {n:5d}  {k}')
    print('\nДистанция декора до ближайшего якоря:')
    for k, n in out['dist_bucket'][:8]:
        print(f'  {n:5d}  {k} см')
    print('\nЧто ставят СВЕРХУ (среднее число предметов):')
    for a, avg in out['on_top_avg'].items():
        top = ', '.join(f'{k}×{v}' for k, v in out['on_top'].get(a, [])[:4])
        print(f'  {a}: {avg} шт — {top}')


if __name__ == '__main__':
    main()
