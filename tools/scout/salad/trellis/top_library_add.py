#!/usr/bin/env python3
"""Светлые породы в библиотеку верха (T-20261125-69/6; владелец TG 2725 — «да» на светлые сканы): пробел L 74–82 (у ambientCG Color-карт дерева почти нет светлее L 72). Добавляет бины из `data/flat3d/top-library/light-add.json`
в `library.json` и пишет узор `pat512/<бин>.jpg`. Источник — ТОЛЬКО ambientCG (CC0): бин = скан как есть (`derive: null`) либо ПРОИЗВОДНОЕ от скана CC0 — осветлённая/обесцвеченная копия (`derive`: целевое Lab-среднее и масштаб a/b; узор L — отклонение от
среднего — не меняется, меняется только тон, по которому бин выбирается). Происхождение пишется в бин (`derived_from`, `derive`, `license`).
  python3 top_library_add.py <папка сканов (<id>/diff.jpg, Color-карта 1K ambientCG)>   # идемпотентно: повторный запуск перезаписывает те же бины
Полезно: у derive бинов `sha256_zip` — хэш zip исходного скана."""
from __future__ import annotations

import json
import os
import sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..', '..'))
sys.path.insert(0, HERE)
import tex_coverage as TC  # noqa: E402
LIBDIR = os.path.join(ROOT, 'data', 'flat3d', 'top-library')
SIDE, QUALITY = 512, 95
_M = np.array([[0.4124564, 0.3575761, 0.1804375], [0.2126729, 0.7151522, 0.0721750], [0.0193339, 0.1191920, 0.9503041]])
_WP = np.array([0.95047, 1.0, 1.08883])


def lab2rgb(lab):
    """Lab (N,3), D65 → sRGB uint8 (N,3); обратное к tex_coverage.rgb2lab."""
    fy = (lab[:, 0] + 16) / 116
    fx, fz = fy + lab[:, 1] / 500, fy - lab[:, 2] / 200
    f = np.stack([fx, fy, fz], 1)
    xyz = np.where(f ** 3 > 216 / 24389, f ** 3, (116 * f - 16) * 27 / 24389) * _WP
    c = np.clip(xyz @ np.linalg.inv(_M).T, 0.0, 1.0)
    c = np.where(c > 0.0031308, 1.055 * np.power(c, 1 / 2.4) - 0.055, 12.92 * c)
    return np.clip(np.rint(c * 255), 0, 255).astype(np.uint8)


def derive(im, spec: dict):
    """Тон-копия скана: L-среднее → target_L (отклонения L те же), a/b-среднее → target_a/target_b, отклонения a/b × chroma_var. → RGB uint8 (h,w,3)."""
    h, w = im.shape[:2]
    lab = TC.rgb2lab(im.reshape(-1, 3)).reshape(-1, 3)
    m = lab.mean(0)
    out = np.empty_like(lab)
    out[:, 0] = lab[:, 0] - m[0] + spec['target_L']
    out[:, 1] = (lab[:, 1] - m[1]) * spec['chroma_var'] + spec['target_a']
    out[:, 2] = (lab[:, 2] - m[2]) * spec['chroma_var'] + spec['target_b']
    return lab2rgb(out).reshape(h, w, 3)


def orient(im):
    L = np.asarray(Image.fromarray(im).convert('L').resize((512, 512), Image.BILINEAR), np.float64)
    gy, gx = np.gradient(L)
    ex, ey = float((gx ** 2).sum()), float((gy ** 2).sum())
    return ('u' if ey > ex else 'v'), abs(ey - ex) / (ey + ex)


def swirl_share(im, axis, min_coh, B=16):
    L = np.asarray(Image.fromarray(im).convert('L').resize((512, 512), Image.BILINEAR), np.float64)
    if axis == 'v':
        L = L.T
    gy, gx = np.gradient(L)
    dev = []
    for by in range(0, 512, B):
        for bx in range(0, 512, B):
            a, b, c = (gx[by:by + B, bx:bx + B] ** 2).sum(), (gy[by:by + B, bx:bx + B] ** 2).sum(), (gx * gy)[by:by + B, bx:bx + B].sum()
            if a + b < 1e-6 or np.sqrt((a - b) ** 2 + 4 * c * c) / (a + b) < min_coh:
                continue
            dev.append(abs(np.pi / 2 - abs(0.5 * np.arctan2(2 * c, a - b))))
    return (float(np.mean(np.array(dev) > np.deg2rad(25))) if dev else 0.0), len(dev)


def build(raw: str) -> list:
    spec = json.load(open(os.path.join(LIBDIR, 'light-add.json'), encoding='utf-8'))
    lib_path = os.path.join(LIBDIR, 'library.json')
    lib = json.load(open(lib_path, encoding='utf-8'))
    rules = json.load(open(os.path.join(ROOT, 'tools', 'scout', 'rules', 'top-prior.json'), encoding='utf-8'))['pattern']['classify']
    made = []
    for k, s in spec['items'].items():
        im = np.asarray(Image.open(os.path.join(raw, s['source'], 'diff.jpg')).convert('RGB').resize((SIDE, SIDE)), np.uint8)
        if s.get('derive'):
            im = derive(im, s['derive'])
        Image.fromarray(im).save(os.path.join(LIBDIR, 'pat512', k + '.jpg'), 'JPEG', quality=QUALITY)
        im2 = np.asarray(Image.open(os.path.join(LIBDIR, 'pat512', k + '.jpg')).convert('RGB'), np.uint8)          # метрики — по тому, что реально читает этап 07 (JPEG)
        lab = TC.rgb2lab(im2.reshape(-1, 3))
        ax, st = orient(im2)
        sw, n = swirl_share(im2, ax, rules['min_coh'])
        cls = 'flat' if st < rules['flat_strength'] else ('swirl' if sw >= rules['swirl_share16'] else 'straight')
        item = {'lab': [round(float(x), 2) for x in lab.mean(0)], 'lab_std': [round(float(x), 2) for x in lab.std(0)], 'grain_axis': ax, 'grain_strength': round(st, 3), 'tile_cm': s.get('tile_cm', [0, 0]),
                'sha256_zip': s['sha256_zip'], 'path': 'raw/' + s['source'], 'family': 'wood', 'pattern_metrics': {'swirl_share16': round(sw, 3), 'n_blocks': n}, 'pattern_class': cls, 'pattern_class_metric': cls,
                'pattern_class_source': 'метрика', 'license': 'CC0 (ambientCG)', 'source_asset': s['source'], 'added': 'T-20261125-69/6'}
        if s.get('derive'):
            item['derived_from'] = s['source']
            item['derive'] = s['derive']
            item['derive_doc'] = s.get('doc')
        lib['items'][k] = item
        made.append((k, item['lab'], cls))
    json.dump(lib, open(lib_path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    return made


if __name__ == '__main__':
    for row in build(os.path.expanduser(sys.argv[1])):
        print(row)
