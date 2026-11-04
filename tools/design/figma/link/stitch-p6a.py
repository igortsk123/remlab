"""design-02 П6а: склейка «эталон | сборка | разница» и попиксельная разница двух снимков одного размера (без PIL).
Запуск: python3 stitch-p6a.py <эталон.png> <сборка.png> <выход.png>
Разница: красный — канал отличается > 48 (заметно глазом), розовый — 13..48 (сглаживание, оттенок), серый — эталон бледно.
Печатает: размер, отличающихся пикселей (любой порог / >12 / >48), рамку заметных отличий и полосы по высоте, где они есть.
"""
import os
import struct
import sys
import zlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from importlib import import_module
read_png = import_module('compare-shots').read_png


def write_png(path, w, h, rows):
    raw = b''.join(b'\x00' + r for r in rows)
    def chunk(t, b): return struct.pack('>I', len(b)) + t + b + struct.pack('>I', zlib.crc32(t + b) & 0xffffffff)
    open(path, 'wb').write(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 6, 0, 0, 0))
                           + chunk(b'IDAT', zlib.compress(raw, 9)) + chunk(b'IEND', b''))


wa, ha, ra = read_png(sys.argv[1])
wb, hb, rb = read_png(sys.argv[2])
assert (wa, ha) == (wb, hb), ((wa, ha), (wb, hb))
gapc = b'\x60\x60\x60\xff' * 8
out, n_any, n12, n48, bbox, bands = [], 0, 0, 0, None, set()
for y in range(ha):
    a, b = ra[y], rb[y]
    d = bytearray()
    for x in range(wa):
        m = max(abs(a[4 * x + k] - b[4 * x + k]) for k in range(3))
        if m: n_any += 1
        if m > 12: n12 += 1
        if m > 48:
            n48 += 1; bands.add(y // 10)
            bbox = (min(bbox[0], x), min(bbox[1], y), max(bbox[2], x + 1), max(bbox[3], y + 1)) if bbox else (x, y, x + 1, y + 1)
            d += b'\xe0\x20\x20\xff'
        elif m > 12:
            d += b'\xf0\xa8\xa8\xff'
        else:
            g = 200 + (sum(a[4 * x:4 * x + 3]) // 3) * 55 // 255
            d += bytes([g, g, g, 255])
    out.append(a + gapc + b + gapc + bytes(d))
write_png(sys.argv[3], wa * 3 + 16, ha, out)
runs, prev = [], None
for k in sorted(bands):
    if prev is not None and k == prev + 1: runs[-1][1] = k
    else: runs.append([k, k])
    prev = k
tot = wa * ha
print(f'{os.path.basename(sys.argv[3])}: {wa}x{ha} diff_any={n_any} ({100*n_any/tot:.1f}%) >12={n12} ({100*n12/tot:.1f}%) '
      f'>48={n48} ({100*n48/tot:.1f}%) bbox48={bbox} bands48(y)=' + ','.join(f'{a*10}-{b*10+10}' for a, b in runs))
