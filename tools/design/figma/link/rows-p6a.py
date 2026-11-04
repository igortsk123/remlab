"""design-02 П6а: профиль строк снимка — где по высоте начинаются/кончаются полосы «не фон».
Запуск: python3 rows-p6a.py <png> [x0 x1] — печатает отрезки y, где в столбцах x0..x1 есть пиксели, отличные от фона (цвет пикселя (2,2)).
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from importlib import import_module
read_png = import_module('compare-shots').read_png

w, h, rows = read_png(sys.argv[1])
x0 = int(sys.argv[2]) if len(sys.argv) > 2 else 0
x1 = int(sys.argv[3]) if len(sys.argv) > 3 else w
bg = rows[2][8:12]
runs, start = [], None
for y in range(h):
    r = rows[y]
    hit = any(max(abs(r[4 * x + k] - bg[k]) for k in range(3)) > 6 for x in range(x0, x1))
    if hit and start is None:
        start = y
    if not hit and start is not None:
        runs.append((start, y)); start = None
if start is not None:
    runs.append((start, h))
print('bg', tuple(bg), ' '.join(f'{a}-{b}' for a, b in runs))
