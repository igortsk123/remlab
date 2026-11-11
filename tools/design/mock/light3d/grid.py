"""T-20261111-22/2: склейка подписанных кадров сеткой. python .t22-grid.py <выход.jpg> <ширина ячейки> <колонок> <файл=подпись>..."""
import sys

from PIL import Image, ImageDraw, ImageFont

out, cw, cols = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
try:
    FONT = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", max(14, cw // 26))
except OSError:
    FONT = ImageFont.load_default()
cells = []
for a in sys.argv[4:]:
    f, _, t = a.partition("=")
    im = Image.open(f).convert("RGB")
    im = im.resize((cw, int(im.height * cw / im.width)))
    d = ImageDraw.Draw(im)
    w = d.textlength(t, font=FONT)
    d.rectangle([0, 0, w + 16, FONT.size + 12], fill=(255, 255, 255))
    d.text((8, 5), t, fill=(0, 0, 0), font=FONT)
    cells.append(im)
rows = [cells[i:i + cols] for i in range(0, len(cells), cols)]
H = sum(max(c.height for c in r) for r in rows) + 6 * (len(rows) - 1)
canvas = Image.new("RGB", (cols * cw + 6 * (cols - 1), H), (255, 255, 255))
y = 0
for r in rows:
    for i, c in enumerate(r):
        canvas.paste(c, (i * (cw + 6), y))
    y += max(c.height for c in r) + 6
canvas.save(out, quality=88)
print(out, canvas.size)
