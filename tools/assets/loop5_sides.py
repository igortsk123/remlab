"""Лист «со всех сторон» на товар: фото + 6 видов (перед, 3/4, бок, зад, другой бок, верх). Использование: loop5_sides.py <material.glb> <фото.png> <лист.png>.
Копия листа директора (`~/remlab-logs/sides.py`, T-20) для круга «на 5» (loop5.py); заменяется командой из rules/loop5.json → sheets.cmd, когда будет tools/assets/sides_sheet.py (T-26)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'scout'))
import mesh_render as MR  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

glb, photo, out = sys.argv[1], sys.argv[2], sys.argv[3]
parts = MR.load_parts(glb)
views = [(0, 12, 'front'), (40, 20, '3/4'), (90, 12, 'side'), (180, 12, 'back'), (270, 12, 'other side'), (0, 80, 'top')]
S = 420
sheet = Image.new('RGB', (S * 7, S + 24), 'white')
d = ImageDraw.Draw(sheet)
try:
    ph = Image.open(photo).convert('RGB')
    ph.thumbnail((S, S))
    sheet.paste(ph, (0, 24))
except Exception:  # noqa: BLE001 — нет фото: лист всё равно нужен
    d.text((5, 30), 'no photo', fill='black')
d.text((5, 4), 'PHOTO', fill='black')
for k, (yaw, pitch, name) in enumerate(views, 1):
    im = MR.render(parts, yaw, pitch, size=(S, S))
    if not isinstance(im, Image.Image):
        im = Image.fromarray(im)
    im = im.convert('RGBA')
    bg = Image.new('RGBA', im.size, (255, 255, 255, 255))
    bg.alpha_composite(im)
    im = bg.convert('RGB')
    im.thumbnail((S, S))
    sheet.paste(im, (k * S, 24))
    d.text((k * S + 5, 4), name, fill='black')
os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
sheet.save(out + '.tmp.png')                                                  # сначала во временный: обрыв (диск полон) не оставит пустой png «готово»
os.replace(out + '.tmp.png', out)
print(out)
