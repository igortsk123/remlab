#!/usr/bin/env python3
"""Отладка: кандидаты разрывов (малые/большие) с «стеклом», дугой двери и наружностью — для одной области листа.
  python tools/floorplan/debug_gaps.py <A|B|C> <ppm> x0 y0 x1 y1"""
import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bench  # noqa: E402
import fpcore as fc  # noqa: E402

plan, ppm = sys.argv[1], float(sys.argv[2])
x0, y0, x1, y1 = map(int, sys.argv[3:7])
gold = json.loads((bench.HERE / 'gold' / f'{plan}.json').read_text())
img = cv2.imread(str(Path('/home/pakar/remlab-logs/floorplan-bench/inputs') / gold['image']))
gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
wall = bench.build_mask(img, bench.CFG[plan])
t = fc.stroke_thickness(wall)
fams = fc.angle_families(wall)
regions = fc.xy_cut(wall, max(40, int(3 * t)))
ang = bench.rot_angles(fams)
Ls, Lb, fl = int(1.7 * ppm), int(3.6 * ppm), max(3, int(round(1.5 * t)))
wall = (wall | fc.extend_corners(wall, int(0.6 * ppm), fl, fc.bevel_end_zone(wall, t, Ls))).astype(np.uint8)   # как bench._analyze
thin = fc.thin_lines(gray, wall, bench.CFG[plan]['thin'])
dark = (((gray < bench.CFG[plan]['glaze']) | (thin > 0)) & (wall == 0)).astype(np.uint8)
cs = bench.per_region(lambda w: fc.bridge_all(w, Ls, fl, ang), wall, regions)
cb = bench.per_region(lambda w: fc.bridge_all(w, Lb, fl, ang, both_flanks=True), wall, regions) & (cs == 0)
_, _, out1 = fc.free_components(wall | cs | cb)
print('t', t, 'fl', fl, 'Ls', Ls, 'Lb', Lb, 'fams', fams)
for nm, m in (('S', cs), ('B', cb)):
    lab, gs = fc.gap_components(m, dark, out1)
    for g in gs:
        if not (x0 <= g.cx <= x1 and y0 <= g.cy <= y1):
            continue
        ys, xs = np.nonzero(lab == g.id)
        c, u, n, L, d = fc.gap_axes(ys, xs)
        ev = fc.door_evidence(thin, c, u, n, L, d)
        print(nm, (round(g.cx), round(g.cy)), 'L', round(g.length), 'd', round(g.depth), 'glaze', round(g.glaze, 2),
              'ext', g.exterior, 'door', round(ev, 2))
