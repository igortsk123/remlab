#!/usr/bin/env python3
"""Диагностика входов стенда: частые цвета, гистограмма тёмного, толщина тёмных штрихов (distance transform).
  python tools/floorplan/probe_colors.py <картинка> <папка-вывода>"""
import sys
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

img = cv2.imread(sys.argv[1], cv2.IMREAD_COLOR)
out = Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)
q = (img // 16).reshape(-1, 3)
cnt = Counter(map(tuple, q))
print('частые цвета (BGR//16 → доля):')
for c, n in cnt.most_common(14):
    print(' ', tuple(int(x) * 16 + 8 for x in c), round(n / len(q), 4))
hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
for thr in (60, 90, 120):
    m = (gray < thr).astype(np.uint8)
    dt = cv2.distanceTransform(m, cv2.DIST_L2, 3)
    vals = dt[dt > 0]
    hist = np.histogram(vals * 2, bins=[0, 2, 3, 4, 5, 6, 8, 10, 12, 16, 20, 30, 60])
    print(f'gray<{thr}: доля {m.mean():.3f}; 2·dt (толщина штриха) гист:', list(zip(hist[1][:-1].tolist(), hist[0].tolist())))
    cv2.imwrite(str(out / f'dark{thr}.png'), 255 - m * 255)
blue = ((hsv[..., 0] > 100) & (hsv[..., 0] < 130) & (hsv[..., 1] > 120) & (hsv[..., 2] > 60)).astype(np.uint8)
print('синий доля', round(blue.mean(), 4))
cv2.imwrite(str(out / 'blue.png'), 255 - blue * 255)
