#!/usr/bin/env python3
"""T-20261119-88 (доработка директора, TG 1882): заливка дыр как у PhotoMesh `inpaint.py` — `cv2.inpaint` TELEA, радиус 3, по маске плохих текселей прямо в КАРТЕ (UV), БЕЗ учёта швов и границ островов.

ЗАЧЕМ. Сравнить с `tex_fill.py` (донор по расстоянию между точками поверхности меша внутри материальной области): TELEA тянет цвет по картинке развёртки, поэтому на краях островов он берёт
цвет чужой стороны (шов виден на 45° и сбоку). Маска — те же плохие тексели, что залил `tex_fill` (красный и жёлтый на его `-fillmap.png`), чтобы сравнение было на одних и тех же текселях.
Форма и развёртка не меняются (guard 1e-6). Без зависимостей кроме numpy/opencv.

  inpaint_telea.py --glb <GLB с картой> --fillmap <…-fillmap.png tex_fill> --out-dir <папка> --stem <имя> [--radius 3]
  → <out-dir>/<stem>-telea.glb, <stem>.telea.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.normpath(os.path.join(HERE, '..', '..')))
import a1_tone as A  # noqa: E402
import ab_tint as T  # noqa: E402


def mask_from_fillmap(path: str) -> np.ndarray:
    """Красный (залито) и жёлтый (смешано) пиксели карты заливки `tex_fill` → маска плохих текселей (приглушённая краска не достигает 255)."""
    from PIL import Image
    im = np.asarray(Image.open(path).convert('RGB')).astype(int)
    red = (im[..., 0] == 255) & (im[..., 1] == 0) & (im[..., 2] == 0)
    yellow = (im[..., 0] == 255) & (im[..., 1] == 220) & (im[..., 2] == 0)
    return red | yellow


def telea(tex: np.ndarray, mask: np.ndarray, radius: int = 3) -> np.ndarray:
    import cv2
    return cv2.inpaint(np.ascontiguousarray(tex), mask.astype(np.uint8) * 255, radius, cv2.INPAINT_TELEA)


def run(glb: str, fillmap: str, out_dir: str, stem: str, radius: int = 3) -> dict:
    t0 = time.time()
    os.makedirs(out_dir, exist_ok=True)
    j0, b0 = A.read_glb(glb)
    tex = T.read_texture(j0, b0)
    mask = mask_from_fillmap(fillmap)
    if mask.shape != tex.shape[:2]:
        raise ValueError(f'маска {mask.shape} не совпадает с картой {tex.shape[:2]}')
    new = telea(tex, mask, radius)
    jn, bn = A.swap_texture(j0, b0, A.png_bytes(new))
    out = os.path.join(out_dir, f'{stem}-telea.glb')
    A.write_glb(out, jn, bn)
    g = A.geometry_guard(*A.read_glb(glb), *A.read_glb(out))
    keep = ~mask
    res = {'glb_in': glb, 'out': out, 'radius': radius, 'masked_texels': int(mask.sum()), 'masked_share': round(float(mask.mean()), 4),
           'unmasked_changed_texels': int((new[keep] != tex[keep]).any(-1).sum()), 'guard': g, 'time_s': round(time.time() - t0, 1)}
    json.dump(res, open(os.path.join(out_dir, f'{stem}.telea.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--glb', required=True)
    ap.add_argument('--fillmap', required=True)
    ap.add_argument('--out-dir', required=True)
    ap.add_argument('--stem', required=True)
    ap.add_argument('--radius', type=int, default=3)
    a = ap.parse_args()
    r = run(a.glb, a.fillmap, a.out_dir, a.stem, a.radius)
    print(json.dumps(r, ensure_ascii=False, indent=1))
    return 0 if r['guard']['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
