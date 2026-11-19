#!/usr/bin/env python3
"""T-93 п.2: сравнение сырых масок моделей на HD-фото. Для каждого товара и модели: розовый композит (низ ×4) + метрики.
  compare_masks.py <sku> <папка_маски> [<папка_маски> …]   (папки из masks/, имя = модель_режим_srcРазмер)
Метрики (без эталонной маски — только прокси, это честно сказано в отчёте): площадь α>0,5; полупрозрачная доля 0,04<α<0,96;
α>0,04 вне главной компоненты; светлые бесцветные пиксели в нижних 12 % (тень/блик); сколько тёмных тонких деталей ниже тела (ножки) сохранено — глазами."""
import os
import sys

import numpy as np
from PIL import Image
from scipy import ndimage

ROOT = '/home/pakar/remlab-logs/t93-1119'


def src(sku):
    k = sku.replace(':', '_')
    for e in ('jpg', 'png', 'webp'):
        p = f'{ROOT}/photos/{k}/B_original_picture.{e}'
        if os.path.exists(p):
            return Image.open(p).convert('RGB')
    raise SystemExit('нет фото')


def main():
    sku, dirs = sys.argv[1], sys.argv[2:]
    k = sku.replace(':', '_')
    im = src(sku)
    rgb = np.asarray(im).astype(np.float32)
    W, H = im.size
    rows, tiles = [], []
    for d in dirs:
        m = Image.open(f'{ROOT}/masks/{d}/{k}.mask.png').convert('L')
        if m.size != im.size:
            m = m.resize(im.size, Image.BICUBIC)
        a = np.asarray(m).astype(np.float32) / 255.0
        lab, n = ndimage.label(a > 0.04, structure=np.ones((3, 3)))
        sizes = ndimage.sum(np.ones_like(a), lab, range(1, n + 1)) if n else [0]
        body = lab == (1 + int(np.argmax(sizes))) if n else a > 2
        out_body = float(((a > 0.04) & ~body).sum())
        ys = np.where(body.any(axis=1))[0]
        y1 = int(ys.max()) if len(ys) else H - 1
        y0 = int(ys.min()) if len(ys) else 0
        band = np.zeros_like(body)
        band[int(y1 - 0.12 * (y1 - y0)):y1 + 1] = True
        mx, mn = rgb.max(axis=2), rgb.min(axis=2)
        pale = band & (a > 0.5) & ((mx - mn) < 22) & (mx > 150)
        rows.append((d, int((a > 0.5).sum()), round(float(((a > 0.04) & (a < 0.96)).sum() / max((a > 0.04).sum(), 1)) * 100, 2), int(out_body), int(pale.sum()), n))
        pink = np.zeros_like(rgb) + np.array([255, 0, 170], np.float32)
        comp = (rgb * a[..., None] + pink * (1 - a[..., None])).clip(0, 255).astype(np.uint8)
        crop = comp[max(0, y1 - int(0.22 * (y1 - y0))):min(H, y1 + 30)]
        Image.fromarray(crop).save(f'{ROOT}/cut/{k}_{d}_bottom.png')
        Image.fromarray(comp).save(f'{ROOT}/cut/{k}_{d}_pink.png')
        tiles.append(d)
    print(f'{"маска":40s} {"α>0.5 px":>10s} {"полупр.%":>9s} {"вне тела px":>12s} {"бледных у низа":>15s} {"компонент":>9s}')
    for r in rows:
        print(f'{r[0]:40s} {r[1]:10d} {r[2]:9.2f} {r[3]:12d} {r[4]:15d} {r[5]:9d}')


main()
