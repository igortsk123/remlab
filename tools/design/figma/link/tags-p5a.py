# design-02 П5 (T-20261107-62) п.7: ТОЛЬКО ЧТЕНИЕ — найти белые плашки-ценники на снимке эталона (1x, 375 px шириной).
# python3 tags-p5a.py <png> [y0 y1] → рамки связных белых областей (почти белые пиксели) размером ~35–120 × 16–34.
import sys
sys.path.insert(0, '/home/pakar/igor/remlab/tools/design/figma/link')
from importlib import import_module
rp = import_module('compare-shots').read_png
W, H, rows = rp(sys.argv[1])
y0 = int(sys.argv[2]) if len(sys.argv) > 2 else 90
y1 = int(sys.argv[3]) if len(sys.argv) > 3 else 600
def white(x, y):
    r = rows[y]; i = x * 4
    return r[i] > 246 and r[i + 1] > 246 and r[i + 2] > 246
seen = set()
for y in range(y0, y1):
    for x in range(W):
        if (x, y) in seen or not white(x, y):
            continue
        st = [(x, y)]; seen.add((x, y)); xs = []; ys = []
        while st:
            a, b = st.pop(); xs.append(a); ys.append(b)
            for c, d in ((a + 1, b), (a - 1, b), (a, b + 1), (a, b - 1)):
                if 0 <= c < W and y0 <= d < y1 and (c, d) not in seen and white(c, d):
                    seen.add((c, d)); st.append((c, d))
        w = max(xs) - min(xs) + 1; h = max(ys) - min(ys) + 1
        if 35 <= w <= 120 and 16 <= h <= 34 and len(xs) > w * h * 0.6:
            print('tag x=%d y=%d w=%d h=%d fill=%.2f' % (min(xs), min(ys), w, h, len(xs) / (w * h)))
