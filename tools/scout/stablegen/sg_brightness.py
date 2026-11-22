"""Выравнивание ЯРКОСТИ сгенерированных видов по фото товара (T-20261119-90/7, ⑪ (б), поручение директора 20.11).
Один множитель на весь набор видов: m = яркость предмета на фото / яркость предмета на виде 0 (камера-зерно, единственный вид, где фото было на входе).
Оттенок не трогается (множитель один и тот же на R, G, B); общий вид сохраняет различия между сторонами (у них одинаковый множитель, не «по среднему»).
Правит ТОЛЬКО копию папки `sg-output/Scene/<ts>` (generated/generated_image*-0-0001.png). Предел множителя — `--limit` (по умолчанию 0.6…1.4).
  sg_brightness.py <Scene/<ts>> <фото rgba.png> [--limit 0.6 1.4] [--first 0]   — --first: имя вида-зерна по номеру кадра (generated_image<N>, у ⑪ это 0)
Запуск: ~/venvs/scout/bin/python -I sg_brightness.py … (numpy + pillow)."""
import argparse
import glob
import os
import re

import numpy as np
from PIL import Image


def lum(px):
    return float((0.2126 * px[:, 0] + 0.7152 * px[:, 1] + 0.0722 * px[:, 2]).mean())


def obj_mask(a):
    corner = np.median(np.concatenate([a[:20, :20].reshape(-1, 3), a[-20:, -20:].reshape(-1, 3)]), axis=0)
    return np.abs(a - corner).sum(axis=2) > 25


def multiplier(view0, photo_rgba, lo=0.6, hi=1.4):
    a = np.asarray(view0.convert('RGB')).astype(float)
    p = np.asarray(photo_rgba.convert('RGBA')).astype(float)
    m_view, m_photo = lum(a[obj_mask(a)]), lum(p[:, :, :3][p[:, :, 3] > 200])
    return float(np.clip(m_photo / m_view, lo, hi)), m_view, m_photo


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('scene')
    ap.add_argument('photo')
    ap.add_argument('--limit', nargs=2, type=float, default=[0.6, 1.4])
    ap.add_argument('--first', type=int, default=0)
    a = ap.parse_args()
    files = sorted(glob.glob(os.path.join(a.scene, 'generated', 'generated_image*-0-0001.png')))
    first = os.path.join(a.scene, 'generated', f'generated_image{a.first}-0-0001.png')
    m, lv, lp = multiplier(Image.open(first), Image.open(a.photo), *a.limit)
    print(f'яркость предмета: вид {a.first} = {lv:.1f}, фото = {lp:.1f} → множитель {m:.3f} (предел {a.limit[0]}…{a.limit[1]})')
    for f in files:
        im = np.asarray(Image.open(f).convert('RGB')).astype(float)
        Image.fromarray(np.clip(im * m, 0, 255).astype(np.uint8)).save(f)
        print('  ', re.search(r'generated_image(\d+)', f).group(1), 'умножен')


if __name__ == '__main__':
    main()
