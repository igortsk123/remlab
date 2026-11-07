"""design-02 П6д: сетка снимков (обзор для владельца / контактный лист), без PIL.
Запуск: python3 grid-p6e.py <выход.png> <столбцов> <делитель масштаба> <снимок1.png> [снимок2.png ...]
Каждый снимок уменьшается в <делитель> раз (усреднение блока), раскладывается по строкам слева направо, зазор 12 px серый.
"""
import os
import struct
import sys
import zlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from importlib import import_module
read_png = import_module('compare-shots').read_png

out, cols, k = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
imgs = []
for p in sys.argv[4:]:
    w, h, rows = read_png(p)
    W, H = w // k, h // k
    small = []
    for Y in range(H):
        line = bytearray()
        rs = rows[Y * k:(Y + 1) * k]
        for X in range(W):
            acc = [0, 0, 0]
            for r in rs:
                for x in range(X * k, (X + 1) * k):
                    acc[0] += r[4 * x]; acc[1] += r[4 * x + 1]; acc[2] += r[4 * x + 2]
            n = k * len(rs)
            line += bytes([acc[0] // n, acc[1] // n, acc[2] // n, 255])
        small.append(bytes(line))
    imgs.append((W, H, small))
GAP = 12
cw = max(w for w, _, _ in imgs); ch = max(h for _, h, _ in imgs)
nrows = (len(imgs) + cols - 1) // cols
TW = cols * cw + (cols - 1) * GAP; TH = nrows * ch + (nrows - 1) * GAP
grey = b'\x60\x60\x60\xff'
canvas = [bytearray(grey * TW) for _ in range(TH)]
for i, (w, h, small) in enumerate(imgs):
    ox = (i % cols) * (cw + GAP); oy = (i // cols) * (ch + GAP)
    for y in range(h):
        canvas[oy + y][4 * ox:4 * (ox + w)] = small[y]
raw = b''.join(b'\x00' + bytes(r) for r in canvas)
def chunk(t, b): return struct.pack('>I', len(b)) + t + b + struct.pack('>I', zlib.crc32(t + b) & 0xffffffff)
open(out, 'wb').write(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', TW, TH, 8, 6, 0, 0, 0))
                      + chunk(b'IDAT', zlib.compress(raw, 6)) + chunk(b'IEND', b''))
print(out, TW, 'x', TH)
