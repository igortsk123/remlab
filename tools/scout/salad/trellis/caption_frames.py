#!/usr/bin/env python3
"""T-20261119-92/1: подписанные копии кадров стенда — тонкая полоса сверху с меткой варианта (путь, товар, доля куба) и именем кадра. Оригиналы не трогаются.
Запуск: caption_frames.py <папка кадров> <метка> → <папка>/cap/NN_<вид>_<tex|clay>.png (тот же размер плюс полоса 40 px)."""
import os
import sys

from PIL import Image, ImageDraw, ImageFont

src, label = sys.argv[1], sys.argv[2]
dst = os.path.join(src, 'cap')
os.makedirs(dst, exist_ok=True)
try:
    font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 24)
except OSError:
    font = ImageFont.load_default()
n = 0
for f in sorted(os.listdir(src)):
    if not f.endswith('.png'):
        continue
    im = Image.open(os.path.join(src, f)).convert('RGB')
    bar = Image.new('RGB', (im.width, 40), (20, 20, 20))
    ImageDraw.Draw(bar).text((12, 6), f'{label}  ·  {os.path.splitext(f)[0]}', fill=(255, 255, 255), font=font)
    out = Image.new('RGB', (im.width, im.height + 40))
    out.paste(bar, (0, 0))
    out.paste(im, (0, 40))
    out.save(os.path.join(dst, f))
    n += 1
print(f'подписано {n} кадров → {dst}')
