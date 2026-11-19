#!/usr/bin/env python3
"""T-93 п.3: что за «клочки» у низа дивана во входе пробы (inputs30/…rgba.png): цвет, альфа, связность с телом. Только чтение."""
import numpy as np
from PIL import Image
from scipy import ndimage

p = '/home/pakar/remlab-logs/mesh-models-1118/trellis/inputs30/114667_11634594969038554503.rgba.png'
im = np.asarray(Image.open(p).convert('RGBA')).astype(np.float32)
rgb, a = im[..., :3], im[..., 3] / 255.0
H, W = a.shape
lab, n = ndimage.label(a > 0.04)
sizes = ndimage.sum(np.ones_like(a), lab, range(1, n + 1))
print('компонент α>0.04:', n, '| крупнейшая:', int(sizes.max()), 'px | остальные:', sorted(int(s) for s in sizes)[:-1][-8:])
body = lab == (1 + int(np.argmax(sizes)))
# светлые полупрозрачные/светлые пиксели у нижней кромки: яркость > тела (тело ≈ серое ~120)
mx = rgb.max(axis=2)
mn = rgb.min(axis=2)
bodymed = float(np.median(mx[body & (a > 0.9)]))
print('медианная яркость тела:', round(bodymed, 1))
for name, sel in (('светлее тела на 60+ и α>0.04', (mx > bodymed + 60) & (a > 0.04)), ('то же, α≥0.5', (mx > bodymed + 60) & (a >= 0.5))):
    ys, xs = np.where(sel)
    print(name, '→', int(sel.sum()), 'px', ('x %d..%d y %d..%d' % (xs.min(), xs.max(), ys.min(), ys.max())) if len(xs) else '')
    if len(xs):
        print('   средний цвет', np.round(rgb[sel].mean(axis=0), 0), '| средняя α', round(float(a[sel].mean()), 2), '| насыщенность (max-min) ср.', round(float((mx - mn)[sel].mean()), 1))
# есть ли α>0 ниже нижней кромки сплошного тела
solid = a >= 0.5
rows = np.where(solid.any(axis=1))[0]
print('нижняя строка сплошного (α≥0.5):', rows.max(), '| нижняя строка α>0.04:', int(np.where((a > 0.04).any(axis=1))[0].max()), '| высота кадра', H)
for y in range(int(rows.max()) - 4, int(np.where((a > 0.04).any(axis=1))[0].max()) + 1):
    r = a[y] > 0.04
    print('  y=%d: α>0.04 в %d столбцах, α≥0.5 в %d, средний цвет %s' % (y, int(r.sum()), int((a[y] >= 0.5).sum()), np.round(rgb[y][r].mean(axis=0), 0) if r.any() else '-'))
