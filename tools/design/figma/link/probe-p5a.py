# design-02 П5 (T-20261107-62): ТОЛЬКО ЧТЕНИЕ — средний цвет квадрата 5×5 в точках x,y на нескольких снимках.
# python3 probe-p5a.py "x,y x,y …" a.png b.png …
import sys
sys.path.insert(0, '/home/pakar/igor/remlab/tools/design/figma/link')
from importlib import import_module
rp = import_module('compare-shots').read_png
pts = [tuple(map(int, p.split(','))) for p in sys.argv[1].split()]
for f in sys.argv[2:]:
    _, _, R = rp(f); s = []
    for x, y in pts:
        c = [0, 0, 0]
        for dy in range(-2, 3):
            for dx in range(-2, 3):
                for k in range(3): c[k] += R[y + dy][(x + dx) * 4 + k]
        s.append('%d,%d=%s' % (x, y, '/'.join(str(round(v / 25)) for v in c)))
    print(f.split('/')[-1], ' '.join(s))
