# design-02 П5 (T-20261107-62) п.8: ТОЛЬКО ЧТЕНИЕ — оценить цвет и прозрачность вуали по двум снимкам одного кадра:
# без вуали (base) и с вуалью (veiled): O = a·C + (1 − a)·B по каждому каналу, МНК по точкам сетки в области x0..x1, y0..y1.
# python3 veil-p5a.py base.png veiled.png x0 y0 x1 y1 [шаг]
import sys
sys.path.insert(0, '/home/pakar/igor/remlab/tools/design/figma/link')
from importlib import import_module
rp = import_module('compare-shots').read_png
# необязательно 8-й аргумент «a,r,g,b»: base снят с известной вуалью (a, цвет) — сперва снять её: B = (O − a·C) / (1 − a)
_, _, A = rp(sys.argv[1]); _, _, B = rp(sys.argv[2])
x0, y0, x1, y1 = map(int, sys.argv[3:7]); st = int(sys.argv[7]) if len(sys.argv) > 7 else 6
und = [float(v) for v in sys.argv[8].split(',')] if len(sys.argv) > 8 else None
for ch, nm in enumerate('RGB'):
    xs = []; ys = []
    for y in range(y0, y1, st):
        for x in range(x0, x1, st):
            b = A[y][x * 4 + ch]
            if und: b = (b - und[0] * und[1 + ch]) / (1 - und[0])
            xs.append(b); ys.append(B[y][x * 4 + ch])
    n = len(xs); mx = sum(xs) / n; my = sum(ys) / n
    sxx = sum((a - mx) ** 2 for a in xs); sxy = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
    k = sxy / sxx; c0 = my - k * mx  # O = k·B + c0, k = 1 − a, c0 = a·C
    a = 1 - k; C = c0 / a if a else float('nan')
    res = sum((b - (k * a_ + c0)) ** 2 for a_, b in zip(xs, ys)) / n
    print('%s: alpha=%.3f color=%.1f  (k=%.3f c0=%.1f, rms=%.1f, n=%d)' % (nm, a, C, k, c0, res ** 0.5, n))
