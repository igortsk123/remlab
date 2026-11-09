#!/usr/bin/env python3
"""Вырезка с увеличением и сеткой координат — смотреть картинку глазами.
  python tools/floorplan/crop.py <картинка> <выход.png> x0 y0 x1 y1 [масштаб=2] [шаг сетки=50]"""
import sys

from PIL import Image, ImageDraw

src, dst = sys.argv[1], sys.argv[2]
x0, y0, x1, y1 = map(int, sys.argv[3:7])
k = float(sys.argv[7]) if len(sys.argv) > 7 else 2.0
step = int(sys.argv[8]) if len(sys.argv) > 8 else 50
im = Image.open(src).convert('RGB').crop((x0, y0, x1, y1))
im = im.resize((int(im.width * k), int(im.height * k)), Image.LANCZOS)
d = ImageDraw.Draw(im)
for gx in range((x0 // step + 1) * step, x1, step):
    X = (gx - x0) * k
    d.line([(X, 0), (X, im.height)], fill=(255, 0, 0), width=1)
    d.text((X + 2, 2), str(gx), fill=(255, 0, 0))
for gy in range((y0 // step + 1) * step, y1, step):
    Y = (gy - y0) * k
    d.line([(0, Y), (im.width, Y)], fill=(0, 160, 0), width=1)
    d.text((2, Y + 2), str(gy), fill=(0, 160, 0))
im.save(dst)
