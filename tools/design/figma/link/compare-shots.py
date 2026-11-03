"""design-02: попарное сравнение снимков до/после (одинаковые имена файлов в двух папках).
Запуск: python3 compare-shots.py <папка-до> <папка-после> [--diff <папка-для-масок>]
Печатает: файл, размеры, число отличающихся пикселей, макс. разница канала, рамку отличий.
Без PIL (на algor его нет) — встроенный разбор PNG (8 бит, RGB/RGBA/серый, без чересстрочности); маски — только с PIL.
"""
import os
import struct
import sys
import zlib

try:
    from PIL import Image, ImageChops  # noqa: F401
    HAVE_PIL = True
except ImportError:
    HAVE_PIL = False


def read_png(path):
    """-> (w, h, rows) где rows — список bytes RGBA по строкам."""
    data = open(path, 'rb').read()
    assert data[:8] == b'\x89PNG\r\n\x1a\n', path
    pos, idat, w = 8, b'', None
    while pos < len(data):
        ln, = struct.unpack('>I', data[pos:pos + 4])
        typ = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + ln]
        pos += 12 + ln
        if typ == b'IHDR':
            w, h, depth, ctype, _, _, inter = struct.unpack('>IIBBBBB', body)
            assert depth == 8 and inter == 0 and ctype in (0, 2, 4, 6), (path, depth, ctype, inter)
        elif typ == b'IDAT':
            idat += body
        elif typ == b'IEND':
            break
    bpp = {0: 1, 2: 3, 4: 2, 6: 4}[ctype]
    raw = zlib.decompress(idat)
    stride = w * bpp
    rows, prev, i = [], bytearray(stride), 0
    for _ in range(h):
        f = raw[i]; line = bytearray(raw[i + 1:i + 1 + stride]); i += 1 + stride
        for x in range(stride):
            a = line[x - bpp] if x >= bpp else 0
            b = prev[x]
            c = prev[x - bpp] if x >= bpp else 0
            if f == 1: line[x] = (line[x] + a) & 255
            elif f == 2: line[x] = (line[x] + b) & 255
            elif f == 3: line[x] = (line[x] + ((a + b) >> 1)) & 255
            elif f == 4:
                p = a + b - c; pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[x] = (line[x] + (a if pa <= pb and pa <= pc else (b if pb <= pc else c))) & 255
        prev = line
        if bpp == 4: rows.append(bytes(line))
        elif bpp == 3: rows.append(b''.join(bytes(line[k:k + 3]) + b'\xff' for k in range(0, stride, 3)))
        elif bpp == 2: rows.append(b''.join(bytes([line[k]] * 3 + [line[k + 1]]) for k in range(0, stride, 2)))
        else: rows.append(b''.join(bytes([v, v, v, 255]) for v in line))
    return w, h, rows


def compare(pa, pb):
    wa, ha, ra = read_png(pa)
    wb, hb, rb = read_png(pb)
    if (wa, ha) != (wb, hb):
        return f'размер {(wa, ha)} -> {(wb, hb)}'
    px, mx, bbox = 0, 0, None
    for y in range(ha):
        a, b = ra[y], rb[y]
        if a == b:
            continue
        for x in range(wa):
            d = max(abs(a[4 * x + k] - b[4 * x + k]) for k in range(4))
            if d:
                px += 1; mx = max(mx, d)
                bbox = (min(bbox[0], x), min(bbox[1], y), max(bbox[2], x + 1), max(bbox[3], y + 1)) if bbox else (x, y, x + 1, y + 1)
    return f'{wa}x{ha} diff_px={px} max_ch={mx} bbox={bbox}'


def main():
    a_dir, b_dir = sys.argv[1], sys.argv[2]
    diff_dir = sys.argv[sys.argv.index('--diff') + 1] if '--diff' in sys.argv else None
    if diff_dir and HAVE_PIL:
        os.makedirs(diff_dir, exist_ok=True)
    for name in sorted(os.listdir(a_dir)):
        if not name.endswith('.png'):
            continue
        pb = os.path.join(b_dir, name)
        if not os.path.exists(pb):
            print(f'{name}: нет пары')
            continue
        print(f'{name}: {compare(os.path.join(a_dir, name), pb)}')
        if diff_dir and HAVE_PIL:
            a = Image.open(os.path.join(a_dir, name)).convert('RGBA')
            b = Image.open(pb).convert('RGBA')
            if a.size == b.size:
                d = ImageChops.difference(a, b)
                if d.getbbox():
                    d.convert('RGB').point(lambda v: 255 if v else 0).save(os.path.join(diff_dir, name))


if __name__ == '__main__':
    main()
