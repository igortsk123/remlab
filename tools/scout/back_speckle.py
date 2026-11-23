#!/usr/bin/env python3
"""Мерка крапинок на заду (T-20261123-43/3; правило R-BACKPANEL-06) — по листу «со всех сторон» (`tools/assets/sides_sheet.py`, раскладка — data/flat3d/sides-sheet.json).

ЗАЧЕМ. После выравнивания зада корпусной мебели на плоскости появляются мелкие выбросы по яркости («крапинки»); глазами это видно, числом — не было. Мерка даёт одно число на лист:
доля пикселей центра предмета на виде «зад», у которых сумма RGB отличается от медианы окна больше порога. Замер 23.11: комод 0,09 % до → 0,36 % после; шкаф 0,42 % → 16,5 %.

Что делает: берёт ячейку вида с `view_dtheta` (зад) из листа; предмет = рамка не-белых пикселей, сжатая на `core_shrink` с каждой стороны (край силуэта не считаем); считает долю выбросов.
Все числа — rules/edge-sharpen.json (back_panel.speckle) и data/flat3d/sides-sheet.json; в коде чисел нет, ID товаров нет. Нужны numpy, scipy, Pillow.

  python tools/scout/back_speckle.py ЛИСТ.png [ЛИСТ2.png ...]         → строка JSON на лист; код возврата 1, если хоть один лист выше порога `share_max`
  python tools/scout/back_speckle.py --before ДО.png ПОСЛЕ.png         → парное сравнение: после ≤ max(share_max, ratio_max × до) (товар с рисунком шумит и до выравнивания)
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
EDGE_RULES = os.path.join(HERE, 'rules', 'edge-sharpen.json')
SHEET_RULES = os.path.join(ROOT, 'data', 'flat3d', 'sides-sheet.json')


def load_rules(edge_path: str = EDGE_RULES, sheet_path: str = SHEET_RULES) -> tuple[dict, dict]:
    with open(edge_path, encoding='utf-8') as f:
        sp = json.load(f)['back_panel']['speckle']
    with open(sheet_path, encoding='utf-8') as f:
        sh = json.load(f)
    return sp, sh


def cell_of(img, sp: dict, sh: dict):
    """Ячейка вида «зад» из листа (numpy HxWx3, int): колонка 0 — фото, дальше виды по порядку правил листа."""
    idx = [i for i, v in enumerate(sh['views']) if v['dtheta'] == sp['view_dtheta']]
    if not idx:
        raise ValueError('в sides-sheet.json нет вида с dtheta=%s' % sp['view_dtheta'])
    s, hp = int(sh['size']), int(sh['header_px'])
    c0 = (idx[0] + 1) * s
    if img.shape[1] < c0 + s or img.shape[0] < hp + s:
        raise ValueError('лист %dx%d меньше раскладки (%d видов по %d)' % (img.shape[1], img.shape[0], len(sh['views']), s))
    return img[hp:hp + s, c0:c0 + s]


def measure_cell(cell, sp: dict) -> dict:
    """Мерка на одной ячейке. → {share, mean_dev, px, box}; share=None, если предмета в ячейке нет."""
    import numpy as np
    from scipy.ndimage import median_filter
    g = cell.astype(int).sum(axis=2)
    ys, xs = np.where(g < int(sp['white_sum']))
    if len(ys) == 0:
        return {'share': None, 'mean_dev': None, 'px': 0, 'box': None}
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    dy, dx = int((y1 - y0) * sp['core_shrink']), int((x1 - x0) * sp['core_shrink'])
    reg = g[y0 + dy:y1 - dy, x0 + dx:x1 - dx]
    if reg.size == 0:
        return {'share': None, 'mean_dev': None, 'px': 0, 'box': [int(y0), int(y1), int(x0), int(x1)]}
    dev = np.abs(reg - median_filter(reg, size=int(sp['median_px'])))
    thr = float(sp['dev_levels'])
    tone = float(np.median(reg))
    if sp.get('rel_k') is not None:                                  # контраст — к тону стороны: на тёмной стороне тёмная крапина мала по абсолютной сумме RGB, но заметна глазами
        thr = min(thr, max(float(sp['rel_min']), float(sp['rel_k']) * tone))
    return {'share': float((dev > thr).mean()), 'mean_dev': float(dev.mean()), 'px': int(reg.size), 'box': [int(y0), int(y1), int(x0), int(x1)], 'tone': tone, 'thr': thr}


def measure(sheet_png: str, sp: dict | None = None, sh: dict | None = None) -> dict:
    """Мерка листа. → {share, mean_dev, px, ok, limit, reason}; ok=False при доле выше `share_max` или если мерить нечего (нет предмета на виде «зад»)."""
    import numpy as np
    from PIL import Image
    if sp is None or sh is None:
        sp, sh = load_rules()
    img = np.asarray(Image.open(sheet_png).convert('RGB'))
    m = measure_cell(cell_of(img, sp, sh), sp)
    lim = float(sp['share_max'])
    if m['share'] is None:
        return dict(m, ok=False, limit=lim, reason='на виде «зад» предмета нет')
    ok = m['share'] <= lim
    return dict(m, ok=ok, limit=lim, reason='' if ok else 'крапинок %.2f %% > порога %.2f %%' % (m['share'] * 100, lim * 100))


def compare(before_png: str, after_png: str, sp: dict | None = None, sh: dict | None = None) -> dict:
    """Парное сравнение листов «до» / «после». ok, если «после» ≤ max(share_max, ratio_max × «до»). → мерка «после» + {before, limit, ok, reason}."""
    if sp is None or sh is None:
        sp, sh = load_rules()
    b, a = measure(before_png, sp, sh), measure(after_png, sp, sh)
    if b['share'] is None or a['share'] is None:
        return dict(a, ok=False, before=b['share'], reason='нет предмета на виде «зад» (до: %s, после: %s)' % (b['share'], a['share']))
    lim = max(float(sp['share_max']), float(sp['ratio_max']) * b['share'])
    ok = a['share'] <= lim
    return dict(a, ok=ok, before=b['share'], limit=lim, reason='' if ok else 'крапинок %.2f %% (до %.2f %%) > порога %.2f %%' % (a['share'] * 100, b['share'] * 100, lim * 100))


def main(argv: list) -> int:
    if not argv:
        print(__doc__.split('\n')[0])
        return 2
    sp, sh = load_rules()
    if argv[0] == '--before':
        if len(argv) != 3:
            print('нужно: --before ДО.png ПОСЛЕ.png')
            return 2
        try:
            r = compare(argv[1], argv[2], sp, sh)
        except (OSError, ValueError) as e:
            r = {'ok': False, 'reason': '%s: %s' % (type(e).__name__, e)}
        print(json.dumps(r, ensure_ascii=False))
        return 0 if r.get('ok') else 1
    bad = 0
    for p in argv:
        try:
            r = measure(p, sp, sh)
        except (OSError, ValueError) as e:
            r = {'ok': False, 'reason': '%s: %s' % (type(e).__name__, e)}
        r['sheet'] = p
        bad += 0 if r.get('ok') else 1
        print(json.dumps(r, ensure_ascii=False))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
