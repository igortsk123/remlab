#!/usr/bin/env python3
"""T-20261119-88/2: три карты в UV для дорисовки дыр (StableGen Masked Edit) по итогу цепочки «вариант 9».

  uv_maps.py --glb <итог цепочки .glb> --conf <s2-photo/<ключ>.uvmap-confidence.png> --out-dir <папка> [--photo-json <s2-photo/<ключ>.photo.json>] [--hole-t 0.5] [--yaw N] [--key имя]
  → <out-dir>/{base_color, confidence, hole_mask, hole_mask_all, island_mask, outer_mask}.png, uv_maps.json, README.txt; все карты — того же размера, что текстура итога, строка 0 — верх картинки (как в GLB).

  base_color     — текстура итога (фото на видимой стороне + база MV на остальном), RGB.
  confidence     — вес проекции фото на тексель (`photo_front.photo_weight`): 0 — фото не легло, тексель = база; 255 — целиком из фото. Вне островков развёртки — 0.
  hole_mask      — 255: тексель виден снаружи (`tex_coverage.analyze`, классы 1…4) и фото легло слабо (confidence < hole-t) — тут нужна дорисовка; 0 — фото достаточно, тексель спрятан внутри формы или вне островков.
  hole_mask_all  — то же, но со спрятанными внутри текселями (полная заливка).
  island_mask    — 255: тексель внутри островка развёртки; остальное — паддинг/пустота карты. outer_mask — 255: тексель виден снаружи.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.normpath(os.path.join(HERE, '..', '..')))

README = """Карты UV для дорисовки дыр — {key}
Размер всех карт: {size}×{size}, PNG, строка 0 — верх картинки (как текстура GLB). Форма и развёртка те же, что у итога цепочки «вариант 9» ({glb}).

base_color.png   RGB, текстура итога: фото, наложенное на видимую сторону, а на остальном — база (MV-Adapter на той же форме + заливка пустот).
confidence.png   серая 8 бит. 0 = фото на этот тексель НЕ легло (цвет — база), 255 = целиком из фото; середина — смесь по углу обзора и швам (значение/255 = доля фото). Вне островков развёртки — 0.
hole_mask.png    серая, ТОЛЬКО 0 и 255. 255 = ДЫРА: тексель, который виден снаружи (outer_mask) и где фото легло слабо (confidence < {hole_t}) — его надо дорисовать; 0 = не трогать (фото достаточно, либо тексель спрятан внутри формы / вне островков).
hole_mask_all.png то же, но с текселями, спрятанными внутри формы (у сеток TRELLIS их большинство; покупатель их не видит) — для полной заливки.
island_mask.png  серая, 0 и 255. 255 = тексель принадлежит островку развёртки (на поверхности); 0 = пустота/паддинг карты.
outer_mask.png   серая, 0 и 255. 255 = тексель виден снаружи хотя бы с одного из 26 направлений (классы tex_coverage 1…4); 0 = спрятан внутри или вне островков.

Числа
  островков (текселей поверхности): {island_px}; из них видно снаружи: {outer_px} ({outer_pct}%)
  под фото (confidence ≥ {hole_t}): {photo_share_pct}% всех островков, {photo_outer_pct}% видимых снаружи
  под фото хоть чуть (confidence > 0): {photo_any_pct}% островков
  дыры (hole_mask = 255): {hole_share_pct}% всех островков, {hole_outer_pct}% видимых снаружи (с внутренними, hole_mask_all: {hole_all_pct}%)
  совпадение кромок фото ↔ база до регистрации {agree_before}, после {agree_after} (фото {laid})
Порог дыры {hole_t} — параметр `--hole-t`; для более мягкой дорисовки (трогать только пустое) — меньше (например 0.05), для строгой — больше.
"""


def main() -> int:
    from PIL import Image
    import a1_tone as A
    import ab_tint as T
    import tex_coverage as TC
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--glb', required=True)
    ap.add_argument('--conf', required=True)
    ap.add_argument('--out-dir', required=True)
    ap.add_argument('--photo-json', default=None)
    ap.add_argument('--hole-t', type=float, default=0.5)
    ap.add_argument('--yaw', type=float, default=0.0, help='поворот формы вокруг вертикали (как у цепочки: stages/manifest.json: yaw_deg) — для «наружу видимых» текселей')
    ap.add_argument('--key', default='')
    a = ap.parse_args()
    os.makedirs(a.out_dir, exist_ok=True)
    j, b = A.read_glb(a.glb)
    tex = T.read_texture(j, b)
    size = tex.shape[0]
    conf8 = np.asarray(Image.open(a.conf).convert('L'))
    if conf8.shape != (size, size):
        raise ValueError(f'карта уверенности {conf8.shape}, текстура итога {size}²: размеры должны совпадать')
    geo = TC.load_geoms(a.glb)
    if len(geo) != 1:
        raise ValueError('ожидалась одна геометрия')
    xy = np.stack([geo[0]['UV'][:, 0] * size, (1.0 - geo[0]['UV'][:, 1]) * size], 1)
    ids, _ = TC.raster(xy, geo[0]['F'], size)
    island = (ids >= 0).reshape(size, size)
    conf = (conf8.astype(np.float32) / 255.0) * island
    t = a.hole_t
    hole_all = island & (conf < t)
    # «наружу видимые» тексели — классы `tex_coverage.analyze` 1…4 (норма / не видно с видов наружу / вскользь / не закрашено); 5 — спрятано внутри формы (у сеток TRELLIS его до 80 %: покупатель не увидит, дорисовывать нечего)
    cls = TC.analyze(geo, a.yaw, size, 768)['maps'][0]['cls']
    outer = (cls >= 1) & (cls <= 4) & island
    hole = hole_all & outer
    n = max(int(island.sum()), 1)
    n_out = max(int(outer.sum()), 1)
    agree = {}
    laid = ''
    if a.photo_json and os.path.exists(a.photo_json):
        rr = json.load(open(a.photo_json, encoding='utf-8')).get('registration_refine', {})
        agree = {'before': (rr.get('before') or {}).get('agree'), 'after': (rr.get('after') or {}).get('agree')}
        laid = 'легло' if rr.get('photo_laid') else 'НЕ легло (совпадение кромок ниже порога — результат = база MV)'
    Image.fromarray(tex).save(os.path.join(a.out_dir, 'base_color.png'))
    Image.fromarray(conf8 * island.astype(np.uint8)).save(os.path.join(a.out_dir, 'confidence.png'))
    Image.fromarray(hole.astype(np.uint8) * 255).save(os.path.join(a.out_dir, 'hole_mask.png'))
    Image.fromarray(hole_all.astype(np.uint8) * 255).save(os.path.join(a.out_dir, 'hole_mask_all.png'))
    Image.fromarray(island.astype(np.uint8) * 255).save(os.path.join(a.out_dir, 'island_mask.png'))
    Image.fromarray(outer.astype(np.uint8) * 255).save(os.path.join(a.out_dir, 'outer_mask.png'))
    res = {'glb': a.glb, 'size': size, 'yaw': a.yaw, 'island_px': int(island.sum()), 'outer_px': int(outer.sum()), 'hole_t': t,
           'photo_share': round(float(((conf >= t) & island).sum() / n), 4), 'photo_any_share': round(float(((conf > 0) & island).sum() / n), 4),
           'photo_share_outer': round(float(((conf >= t) & outer).sum() / n_out), 4),
           'hole_share': round(float(hole.sum() / n), 4), 'hole_share_outer': round(float(hole.sum() / n_out), 4), 'hole_all_share': round(float(hole_all.sum() / n), 4),
           'edge_agree': agree, 'photo_laid': laid}
    json.dump(res, open(os.path.join(a.out_dir, 'uv_maps.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    open(os.path.join(a.out_dir, 'README.txt'), 'w', encoding='utf-8').write(README.format(
        key=a.key, size=size, glb=os.path.basename(a.glb), hole_t=t, island_px=res['island_px'], outer_px=res['outer_px'], outer_pct=round(100 * res['outer_px'] / n, 1),
        photo_share_pct=round(100 * res['photo_share'], 2), photo_outer_pct=round(100 * res['photo_share_outer'], 2), hole_outer_pct=round(100 * res['hole_share_outer'], 2),
        hole_all_pct=round(100 * res['hole_all_share'], 2),
        photo_any_pct=round(100 * res['photo_any_share'], 2), hole_share_pct=round(100 * res['hole_share'], 2), agree_before=agree.get('before'),
        agree_after=agree.get('after'), laid=laid or '—'))
    print(json.dumps(res, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
