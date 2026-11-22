#!/usr/bin/env python3
"""Мерка «тёмные рваные полосы у изломов» по готовым выходам этапов 06/07 (T-194/1, T-194/2): без нового счёта, только чтение. Для каждого товара — доля пикселей полосы изломов, где итог тёмнее панели
на dark_streak_dL (`dark_streak_share`), и та же доля без тёмного, которое есть на фото через камеру 04 (`dark_streak_new`: дизайнерские зазоры и ручки браком не считаются), плюс контраст щели.
Полоса изломов — одна на товар (по 06 первого корня), чтобы корни сравнивались на равных.
Запуск: python streak_compare.py --inputs inputs.json --roots A=<out_A> V=<out_V> [--stage 07] [--json out.json]
  inputs.json: {товар: {photo: RGBA-вырезка, pose_run: папка камеры этапа 4}}; <out_X>/<товар>/{06-visible/visible.glb, 07-fill/filled.glb}."""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, '..'), os.path.join(HERE, '..', '..')]
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402
import crease_mask as CM  # noqa: E402
import tex_visible as TV  # noqa: E402

SUB = {'06': ('06-visible', 'visible.glb'), '07': ('07-fill', 'filled.glb')}


def measure(inputs: dict, roots: dict, stage: str) -> list:
    rules = CM.load_rules()
    sub, fn = SUB[stage]
    first = next(iter(roots.values()))
    rows = []
    for sku, it in inputs.items():
        st = TV.load_stage(it['pose_run'])
        prgb, pmask = TV.photo_to_frame(np.asarray(Image.open(it['photo']).convert('RGBA')), st['P'], st['px'])
        cs = CM.crease_shadow(prgb, pmask, st, TV.load_shape(os.path.join(first, sku, '06-visible', 'visible.glb')), rules)
        valid = st['mask']
        row = {'sku': sku}
        for name, root in roots.items():
            p = os.path.join(root, sku, sub, fn)
            if not os.path.exists(p):
                row[name] = None
                continue
            gg = TV.load_shape(p)
            after = TV.frame_from_tex(st, gg, [x['tex'] for x in gg])
            d = CM.dark_streak_share(after, cs['band'], cs['groove'], valid, st['mask'], rules)
            dn = CM.dark_streak_new(after, prgb, pmask, cs['band'], cs['groove'], valid, st['mask'], rules)
            row[name] = {'share_pct': d['share_pct'], 'new_pct': dn['share_pct'], 'streak_px': dn['streak_px'], 'in_photo_px': dn['streak_in_photo_px'], 'contrast': CM.slit_contrast_ratio(prgb, after, cs, st['mask'], valid, rules).get('ratio')}
        rows.append(row)
    return rows


def summary(rows: list, base: str) -> dict:
    out = {}
    names = [k for k in rows[0] if k != 'sku'] if rows else []
    for n in names:
        if n == base:
            continue
        rt = [r[n]['new_pct'] / r[base]['new_pct'] for r in rows if r.get(n) and r.get(base) and r[n]['new_pct'] is not None and r[base]['new_pct']]
        out[n] = {'median_new_over_base': round(statistics.median(rt), 3) if rt else None, 'worse': sum(1 for x in rt if x > 1.05), 'n': len(rt)}
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--inputs', required=True)
    ap.add_argument('--roots', nargs='+', required=True, help='ИМЯ=папка; первое — база сравнения')
    ap.add_argument('--stage', default='07', choices=['06', '07'])
    ap.add_argument('--json', default='')
    a = ap.parse_args()
    roots = dict(x.split('=', 1) for x in a.roots)
    rows = measure(json.load(open(a.inputs, encoding='utf-8')), roots, a.stage)
    for r in rows:
        print(r['sku'], {k: (v and (v['share_pct'], v['new_pct'])) for k, v in r.items() if k != 'sku'})
    sm = summary(rows, next(iter(roots)))
    print('сводка (new_pct / база):', json.dumps(sm, ensure_ascii=False))
    if a.json:
        json.dump({'rows': rows, 'summary': sm}, open(a.json, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
