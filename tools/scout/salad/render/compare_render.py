#!/usr/bin/env python3
"""Сверка кадров форм с Salad (GPU) и наших локальных (CPU): T-184/1, очередь 3. Критерий директора (22.11): СОВПАЛО = те же файлы и размеры, силуэт тот же (IoU маски ≥ 0,99 по КАЖДОМУ кадру),
нет пустых/чёрных, средняя разница пикселей мала; шум Cycles не важен. Пороги — СТАРТОВЫЕ, в `tools/scout/rules/salad-render.json` (секция compare), в код не зашиты.

  python compare_render.py --ours <папка с <sku>/NN_….png> --ref <папка кадров р.6> --skus a,b,c [--out compare.json]
Маска силуэта: пиксель отличается от фона (медиана четырёх угловых пикселей) больше чем на `bg_tol` по любому каналу. Код возврата 0 — все совпали.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
RULES = os.path.normpath(os.path.join(HERE, '..', '..', 'rules', 'salad-render.json'))


def load_rules() -> dict:
    return json.load(open(RULES, encoding='utf-8'))['compare']


def read(path: str) -> np.ndarray:
    return np.asarray(Image.open(path).convert('RGB'), dtype=np.int16)


def mask_of(img: np.ndarray, tol: float) -> np.ndarray:
    corners = np.stack([img[0, 0], img[0, -1], img[-1, 0], img[-1, -1]])
    bg = np.median(corners, axis=0)
    return (np.abs(img - bg).max(axis=2) > tol)


def frame_metrics(ours: np.ndarray, ref: np.ndarray, rules: dict) -> dict:
    mo, mr = mask_of(ours, rules['bg_tol']), mask_of(ref, rules['bg_tol'])
    union = int(np.logical_or(mo, mr).sum())
    iou = 1.0 if union == 0 else float(np.logical_and(mo, mr).sum()) / union
    return {'iou': round(iou, 5), 'mad': round(float(np.abs(ours - ref).mean()), 3), 'mask_frac': round(float(mo.mean()), 4), 'luma': round(float(ours.mean()), 2)}


def frame_problems(m: dict, rules: dict) -> list[str]:
    bad = []
    if m['iou'] < rules['iou_min']:
        bad.append(f"силуэт: IoU {m['iou']} < {rules['iou_min']}")
    if m['mad'] > rules['mean_abs_diff_max']:
        bad.append(f"разница пикселей {m['mad']} > {rules['mean_abs_diff_max']}")
    if m['mask_frac'] < rules['min_mask_frac']:
        bad.append(f"кадр пустой: форма занимает {m['mask_frac']}")
    if m['luma'] < rules['min_mean_luma']:
        bad.append(f"кадр чёрный: средняя яркость {m['luma']}")
    return bad


def compare(ours_dir: str, ref_dir: str, skus: list[str], rules: dict | None = None) -> dict:
    rules = rules or load_rules()
    res: dict = {}
    for sku in skus:
        od, rd = os.path.join(ours_dir, sku), os.path.join(ref_dir, sku)
        on = sorted(f for f in os.listdir(od) if f.endswith('.png')) if os.path.isdir(od) else []
        rn = sorted(f for f in os.listdir(rd) if f.endswith('.png')) if os.path.isdir(rd) else []
        rec: dict = {'frames': {}, 'problems': []}
        if on != rn:
            rec['problems'].append(f'набор кадров другой: нет у нас {sorted(set(rn) - set(on))[:4]}, лишние {sorted(set(on) - set(rn))[:4]}')
        for n in sorted(set(on) & set(rn)):
            a, b = read(os.path.join(od, n)), read(os.path.join(rd, n))
            if a.shape != b.shape:
                rec['problems'].append(f'{n}: размер {a.shape[:2]} ≠ {b.shape[:2]}')
                continue
            m = frame_metrics(a, b, rules)
            rec['frames'][n] = m
            rec['problems'] += [f'{n}: {p}' for p in frame_problems(m, rules)]
        fs = rec['frames'].values()
        rec['n'] = len(rec['frames'])
        rec['iou_min'] = min((m['iou'] for m in fs), default=None)
        rec['mad_mean'] = round(sum(m['mad'] for m in fs) / len(rec['frames']), 3) if rec['frames'] else None
        rec['ok'] = not rec['problems'] and bool(rec['frames'])
        res[sku] = rec
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--ours', required=True)
    ap.add_argument('--ref', required=True)
    ap.add_argument('--skus', required=True)
    ap.add_argument('--out', default='')
    a = ap.parse_args()
    rules = load_rules()
    res = compare(a.ours, a.ref, [s for s in a.skus.split(',') if s], rules)
    for sku, r in res.items():
        print(sku, 'СОВПАЛО' if r['ok'] else 'НЕ СОВПАЛО', {k: r[k] for k in ('n', 'iou_min', 'mad_mean')}, r['problems'][:3] or '')
    ok = sum(1 for r in res.values() if r['ok'])
    print(f'итого: совпало {ok} из {len(res)}; пороги СТАРТОВЫЕ: {rules}')
    if a.out:
        json.dump({'rules': rules, 'result': res}, open(a.out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    return 0 if ok == len(res) else 1


if __name__ == '__main__':
    sys.exit(main())
