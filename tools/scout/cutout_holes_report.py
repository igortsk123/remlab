#!/usr/bin/env python3
"""Дыры внутри тела вырезок «было→стало» (T-20261119-104/3): доля замкнутых дыр по ролям и кадры «было|стало» на тёмном.

  python tools/scout/cutout_holes_report.py --run 1119-a --before cut-before-holes [--pick sku,sku,...] [--random N] [--controls N]

Считает по папке прогона `~/remlab-logs/t104-1119/<run>`: `cut/` (после) против `--before` (копия до правки). Пишет `holes-inside.json` (после),
`holes-by-role.json` и кадры в НОВУЮ папку `holes-<ЧЧММ>/`. Выбор кадров: --pick (названные), --random (случайные сплошные роли из ≥10 % до правки),
--controls (стулья/стеллажи с дырами — контроль: должны остаться прежними)."""
import argparse
import collections
import json
import os
import random
import time

import numpy as np
from PIL import Image
from scipy import ndimage as ndi

ROOT = os.path.expanduser('~/remlab-logs/t104-1119')
SOLID = {'комод', 'тумба прикроватная', 'тв-тумба', 'шкаф', 'пуф', 'банкетка', 'диван', 'ваза', 'кашпо', 'статуэтка'}   # как components.SOLID_BODY_ROLES (проверяется ниже)


def share(path: str) -> float:
    a = np.asarray(Image.open(path).convert('RGBA'))[..., 3] > 127
    f = ndi.binary_fill_holes(a)
    return float((f & ~a).sum()) / max(1.0, float(f.sum()))


def dark(path: str, h: int = 460) -> Image.Image:
    c = Image.open(path).convert('RGBA')
    b = Image.new('RGBA', c.size, (27, 27, 31, 255))
    b.alpha_composite(c)
    b = b.convert('RGB')
    return b.resize((max(1, int(b.width * h / b.height)), h))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--run', required=True)
    ap.add_argument('--before', default='cut-before-holes')
    ap.add_argument('--pick', default='')
    ap.add_argument('--random', type=int, default=3)
    ap.add_argument('--controls', type=int, default=2)
    ap.add_argument('--seed', type=int, default=104)
    a = ap.parse_args()
    d = os.path.join(ROOT, a.run)
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'salad'))
    import components as C
    assert SOLID == set(C.SOLID_BODY_ROLES), 'список ролей отчёта разошёлся с components.SOLID_BODY_ROLES'
    rows = {r['sku']: r for r in json.load(open(os.path.join(d, 'products.json'), encoding='utf-8'))}
    last = {}
    for line in open(os.path.join(d, 'chain.jsonl'), encoding='utf-8'):
        try:
            r = json.loads(line)
        except ValueError:
            continue
        last[r['sku']] = r
    res = []
    for sku, c in last.items():
        sha = c['sha']
        res.append({'sku': sku, 'role': rows[sku]['role'], 'sha': sha,
                    'before': round(share(os.path.join(d, a.before, sha + '.png')), 4), 'after': round(share(os.path.join(d, 'cut', sha + '.png')), 4)})
    json.dump([r for r in sorted(res, key=lambda r: -r['after']) if r['after'] >= 0.02], open(os.path.join(d, 'holes-inside.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    by = collections.defaultdict(lambda: {'total': 0, 'b2': 0, 'a2': 0, 'b10': 0, 'a10': 0})
    for r in res:
        g = by[r['role']]
        g['total'] += 1
        g['b2'] += r['before'] >= 0.02
        g['a2'] += r['after'] >= 0.02
        g['b10'] += r['before'] >= 0.10
        g['a10'] += r['after'] >= 0.10
    json.dump(by, open(os.path.join(d, 'holes-by-role.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f'{"роль":22} всего  ≥2% было→стало  ≥10% было→стало')
    for role, g in sorted(by.items(), key=lambda t: -t[1]['b2']):
        if g['b2'] or g['a2']:
            print(f'{role:22} {g["total"]:5}  {g["b2"]:4} → {g["a2"]:<4}      {g["b10"]:4} → {g["a10"]:<4}   {"(сплошная)" if role in SOLID else ""}')
    tot = {k: sum(g[k] for g in by.values()) for k in ('b2', 'a2', 'b10', 'a10')}
    print('ВСЕГО', tot)
    out = os.path.join(d, 'holes-' + time.strftime('%H%M'))
    os.makedirs(out, exist_ok=True)
    rnd = random.Random(a.seed)
    named = [s for s in a.pick.split(',') if s]
    solid10 = [r for r in res if r['role'] in SOLID and r['before'] >= 0.10 and r['sku'] not in named]
    chosen = [('названный', s) for s in named] + [('случайный', r['sku']) for r in rnd.sample(solid10, min(a.random, len(solid10)))]
    ctrl = [r for r in res if r['role'] in ('стул', 'стеллаж') and r['before'] >= 0.10]
    chosen += [('контроль', r['sku']) for r in rnd.sample(ctrl, min(a.controls, len(ctrl)))]
    by_sku = {r['sku']: r for r in res}
    for kind, sku in chosen:
        r = by_sku[sku]
        im = [dark(os.path.join(d, a.before, r['sha'] + '.png')), dark(os.path.join(d, 'cut', r['sha'] + '.png'))]
        o = Image.new('RGB', (im[0].width + im[1].width + 10, im[0].height), (255, 0, 255))
        o.paste(im[0], (0, 0))
        o.paste(im[1], (im[0].width + 10, 0))
        name = f'{kind}-{r["role"].replace(" ", "-")}-{r["before"]:.2f}-{r["after"]:.2f}-{sku.replace(":", "_")}.png'
        o.save(os.path.join(out, name))
        print(f'  кадр {kind}: {r["role"]} {sku} {r["before"]} → {r["after"]} → {name}')
    print('папка', out)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
