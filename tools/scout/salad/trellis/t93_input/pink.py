#!/usr/bin/env python3
"""T-93: вырезка на розовом фоне (ff00aa), целиком и низ крупно (×4, nearest — видны пиксели), плюс статистика альфы вне главного тела.
  pink.py <rgba.png> <префикс-выхода>   → <префикс>_pink.png, <префикс>_bottom.png, печать статистики"""
import sys

import numpy as np
from PIL import Image

src, pre = sys.argv[1], sys.argv[2]
im = Image.open(src).convert('RGBA')
a = np.asarray(im)[..., 3]
bg = Image.new('RGBA', im.size, (255, 0, 170, 255))
bg.alpha_composite(im)
bg.convert('RGB').save(pre + '_pink.png')
H, W = a.shape
ys, xs = np.where(a > 8)
y0, y1, x0, x1 = ys.min(), ys.max(), xs.min(), xs.max()
# нижняя треть габарита предмета (с запасом вниз), увеличить ×4 без сглаживания
top = int(y0 + 0.62 * (y1 - y0))
crop = bg.convert('RGB').crop((max(0, x0 - 6), top, min(W, x1 + 7), min(H, y1 + 7)))
crop.resize((crop.width * 4, crop.height * 4), Image.NEAREST).save(pre + '_bottom.png')
# полупрозрачность: доля пикселей с 8<α<247 среди α>8
semi = ((a > 8) & (a < 247)).sum()
print('размер', im.size, '| габарит предмета x %d..%d y %d..%d' % (x0, x1, y0, y1), '| пикселей α>8:', int((a > 8).sum()), '| полупрозр. 8<α<247: %.1f %%' % (100 * semi / max(1, (a > 8).sum())))
