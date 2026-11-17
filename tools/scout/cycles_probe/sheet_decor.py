"""Лист T-20261117-02/2: строки C1/C2, столбцы — кадр 3D | Cycles пустой (было) | [Cycles с декором, быстрый CPU] | Cycles с декором + реализм (5.3) | нынешнее фото;
под каждым кадром — время и ₽. Время берётся из строки RENDER_SEC лога кадра.
  python3 sheet_decor.py <сцена> <папка best53> <выход.png> [<папка матрицы с plain-кадром, только гостиная>]"""
import os
import re
import sys

from PIL import Image, ImageDraw, ImageFont

scene, best, out = sys.argv[1], sys.argv[2], sys.argv[3]
mx = sys.argv[4] if len(sys.argv) > 4 else None
L = os.path.expanduser('~/remlab-logs')
t61 = f'{L}/t61-1116/2236/scenes/{scene}'
t62 = f'{L}/t62-1117/0036/{scene}'
old = f'{L}/t63-1117/0112/cycles'


def sec(log):
    try:
        m = re.search(r'RENDER_SEC ([0-9.]+) samples (\d+)', open(log).read())
        return f'{float(m.group(1)):.0f} с · {m.group(2)} спл.' if m else ''
    except OSError:
        return ''


cols = [
    ('кадр 3D (T-61)', lambda c: f'{t61}/{c}.png', lambda c: 'сервер · 0 ₽'),
    ('Cycles пустой (было)', lambda c: f'{old}/{scene}-{c}.png', lambda c: f'CPU 2048 px · {sec(f"{old}/{scene}-{c}.log")} · 0 ₽'),
]
if mx:
    tagp = 'plain-1024-s64'
    cols.append(('Cycles с декором (быстрый CPU)', lambda c: f'{mx}/{scene}-{c}-{tagp}.png', lambda c: f'CPU 1024 px · {sec(f"{mx}/{scene}-{c}-{tagp}.log")} · 0 ₽'))
b = 'best53-1536-s64'
cols.append(('Cycles с декором + реализм (Blender 5.3)', lambda c: f'{best}/{scene}-{c}-{b}.png', lambda c: f'CPU 1536 px · {sec(f"{best}/{scene}-{c}-{b}.log")} · 0 ₽'))
cols.append(('нынешнее фото (T-62)', lambda c: f'{t62}/base/{c}.png', lambda c: 'платный проход нейросети'))
w = 520
h = round(w * 1489 / 2048)
head, cap = 34, 24
f = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 17)
f2 = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 14)
sheet = Image.new('RGB', (len(cols) * (w + 6) + 6, head + 2 * (h + cap + 6) + 6), (245, 245, 245))
dr = ImageDraw.Draw(sheet)
for i, (name, path_of, cap_of) in enumerate(cols):
    x = 6 + i * (w + 6)
    dr.text((x, 6), name, fill=(0, 0, 0), font=f)
    for j, c in enumerate(('C1', 'C2')):
        y = head + j * (h + cap + 6)
        p = path_of(c)
        if os.path.exists(p):
            sheet.paste(Image.open(p).convert('RGB').resize((w, h), Image.LANCZOS), (x, y))
        dr.text((x, y + h + 3), c + ' · ' + cap_of(c), fill=(40, 40, 40), font=f2)
sheet.save(out)
print(out, sheet.size)
