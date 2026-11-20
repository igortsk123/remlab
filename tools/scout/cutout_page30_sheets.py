#!/usr/bin/env python3
"""Листы для глаз по странице cutout_page30: по N пар «фото | вырезка» с номерами (для самопроверки до показа). Без сети.
  python tools/scout/cutout_page30_sheets.py --site DIR/site [--per 4]"""
import argparse
import os

from PIL import Image, ImageDraw


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--site', required=True)
    ap.add_argument('--per', type=int, default=4)
    ap.add_argument('--h', type=int, default=330)
    a = ap.parse_args()
    img = os.path.join(a.site, 'img')
    ns = sorted({int(f[:2]) for f in os.listdir(img) if f.endswith('-photo.webp')})
    out = os.path.join(a.site, '..', 'sheets')
    os.makedirs(out, exist_ok=True)
    for k in range(0, len(ns), a.per):
        chunk = ns[k:k + a.per]
        rows = []
        for n in chunk:
            ims = [Image.open(os.path.join(img, f'{n:02d}-{t}.webp')).convert('RGB') for t in ('photo', 'cut')]
            ims = [im.resize((max(1, int(im.width * a.h / im.height)), a.h)) for im in ims]
            rows.append((n, ims))
        w = max(sum(i.width for i in r[1]) + 10 for r in rows) + 50
        sheet = Image.new('RGB', (w, (a.h + 6) * len(rows)), (255, 255, 255))
        d = ImageDraw.Draw(sheet)
        for j, (n, ims) in enumerate(rows):
            y = j * (a.h + 6)
            d.text((4, y + 4), f'{n:02d}', fill=(0, 0, 0))
            x = 50
            for im in ims:
                sheet.paste(im, (x, y))
                x += im.width + 10
        p = os.path.join(out, f'sheet-{chunk[0]:02d}-{chunk[-1]:02d}.png')
        sheet.save(p)
        print(p)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
