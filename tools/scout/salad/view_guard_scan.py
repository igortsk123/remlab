#!/usr/bin/env python3
"""Офлайн-прогон сторожа пустых видов (`view_guard.py`) по сохранённым комплектам `dbg-*` — без GPU.

  ~/venvs/scout/bin/python view_guard_scan.py <корень поиска> [--out таблица.tsv]

Идёт по папкам, где лежат `dbg-mv-albedo-N.png` и `dbg-cond-normal-N.png`, и печатает по каждому виду долю «как фон»
внутри силуэта и вердикт. Колонка `top_grey` — доля серых (124–134 по каждому каналу) пикселей в верхней части
дорисованной UV-карты `dbg-uv-albedo-inpainted.png` (грубый признак «серый верх уже в готовом меше»), чтобы сверить
вердикты сторожа с известным браком.
"""
import json
import os
import sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import view_guard as VG  # noqa: E402


def complects(root: str):
    for dp, _, fs in os.walk(root):
        if 'dbg-mv-albedo-0.png' in fs and 'dbg-cond-normal-0.png' in fs:
            yield dp


def load(dp: str, kind: str, i: int):
    p = os.path.join(dp, f'dbg-{kind}-{i}.png')
    return Image.open(p) if os.path.exists(p) else None


def grey_share(dp: str) -> float | None:
    p = os.path.join(dp, 'dbg-uv-albedo-inpainted.png')
    if not os.path.exists(p):
        return None
    a = np.asarray(Image.open(p).convert('RGB')).astype(int)
    g = np.all((a >= 124) & (a <= 134), axis=-1)
    return round(float(g.mean()), 4)


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    root = argv[0]
    out = argv[argv.index('--out') + 1] if '--out' in argv else None
    rows, n = [], 0
    for dp in sorted(complects(root)):
        n += 1
        views, conds = [], []
        i = 0
        while True:
            v, c = load(dp, 'mv-albedo', i), load(dp, 'cond-normal', i)
            if v is None or c is None:
                break
            views.append(v)
            conds.append(c)
            i += 1
        res = VG.judge_views(views, conds)
        gs = grey_share(dp)
        for r in res:
            rows.append((os.path.relpath(dp, root), r['view'], r['judged'], r['frac'], r['bg'], r['inside_px'],
                         r['empty'], r.get('reason', ''), gs))
    head = 'complect\tview\tjudged\tfrac\tbg\tinside_px\tempty\treason\tuv_grey_share'
    lines = [head] + ['\t'.join('' if x is None else (json.dumps(x) if isinstance(x, list) else str(x)) for x in r)
                      for r in rows]
    if out:
        open(out, 'w', encoding='utf-8').write('\n'.join(lines) + '\n')
    empties = [r for r in rows if r[6]]
    print(f'комплектов {n}, видов {len(rows)}, пустых {len(empties)}')
    for r in empties:
        print('  пустой:', r[0], 'вид', r[1], 'доля', r[3], 'bg', r[4], 'серого в UV', r[8])
    print('по номерам видов (пустых/судимых):',
          {v: f"{sum(1 for r in rows if r[1] == v and r[6])}/{sum(1 for r in rows if r[1] == v and r[2])}"
           for v in sorted({r[1] for r in rows})})
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
