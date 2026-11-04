"""design-02 П6в: сдвиг по вертикали полос эталона относительно сборки (без PIL).
Запуск: python3 shift-p6c.py <эталон.png> <сборка.png> y0-y1 [y0-y1 ...]
Для каждой полосы эталона [y0,y1) ищет dy в −40..40, при котором строки сборки y+dy ближе всего (сумма |разниц| по яркости);
печатает dy (сборку надо сдвинуть на −dy, чтобы совпала) и остаток."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from importlib import import_module
rp = import_module('compare-shots').read_png
w, h, a = rp(sys.argv[1]); _, _, b = rp(sys.argv[2])
lum = lambda r: [sum(r[4*x:4*x+3]) for x in range(0, w, 2)]
A = [lum(r) for r in a]; B = [lum(r) for r in b]
for band in sys.argv[3:]:
    y0, y1 = map(int, band.split('-')); best = None
    for dy in range(-40, 41):
        if y0 + dy < 0 or y1 + dy > h: continue
        s = sum(abs(p - q) for y in range(y0, y1) for p, q in zip(A[y], B[y + dy]))
        if best is None or s < best[1]: best = (dy, s)
    print(f'{band}: dy={best[0]} err/px={best[1] / ((y1 - y0) * len(A[0])):.1f}', end='  ')
print()
