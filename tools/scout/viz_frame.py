#!/usr/bin/env python3
"""Кадр по КАРКАСУ: чистая перспектива комнаты с коробками предметов + фото товаров референсами.

Зачем (владелец 2026-08-03): путь «схема сверху» дал естественную картинку, но модель рисовала
мебель «по мотивам» — комод шире своего, тумба другой конструкции. Путь «коллаж из вырезанных
фото» держал геометрию, но выглядел грубо и путал развороты. Здесь — середина: модель получает
ТОЧНУЮ геометрию в системе КАДРА (коробки нужных габаритов на своих местах, подписанные) и
фото товаров референсами; вклеивать кривые вырезки не нужно.

В промпт уходит СПИСОК ТОГО, ЧТО РЕАЛЬНО В КАДРЕ при этом положении камеры, и что осталось
за спиной — чтобы модель не дорисовывала лишнее и не теряла нужное.

  ~/venvs/scout/bin/python viz_frame.py 21 [--view A|B] [--frame-only]
"""
import base64
import io
import json
import math
import os
import re
import sys
import urllib.request
import uuid

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
exec(open(os.path.join(HERE, 'viz3.py')).read().split("HERE=")[0])   # clean_bg

OAI = None
for _envp in (os.path.join(HERE, '.env'), '/home/pakar/igor/v0-health-card/backend/.env'):
    if OAI or not os.path.exists(_envp):
        continue
    for line in open(_envp):
        m = re.match(r'OPENAI_API_KEY=(.+)', line.strip())
        if m:
            OAI = m.group(1).strip().strip('"')

n = int(sys.argv[1]) if len(sys.argv) > 1 else 1
VIEW = sys.argv[sys.argv.index('--view') + 1] if '--view' in sys.argv else 'A'
sets = json.load(open(os.path.join(HERE, 'sets3.json')))
s = sets[n - 1]
items = {r.replace(' 2', ''): it for r, it in s['items'].items()}
L = json.load(open(os.path.join(HERE, f'v3set{n}-layout.json')))
room = L.pop('_room', None) or {'w': 400, 'd': 460}
RW, RD, RH = room['w'] / 100, room['d'] / 100, 2.7

W, H = 1536, 1024
CAMY = 1.35                      # высота глаз
CAMX, CAMZ = RW / 2, -1.3        # камера у южной стены, чуть за ней
F, CX, CY = 1250.0, W / 2, 520.0


def flip(x, z):
    """Вид B — мир поворачивается на 180°, камера всегда «снизу»."""
    return (RW - x, RD - z) if VIEW == 'B' else (x, z)


def P(X, Y, Z):
    d = max(Z - CAMZ, 0.05)
    return (CX + F * (X - CAMX) / d, CY - F * (Y - CAMY) / d)


def font(sz):
    for p in ('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
              '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf'):
        if os.path.exists(p):
            return ImageFont.truetype(p, sz)
    return ImageFont.load_default()


img = Image.new('RGB', (W, H), (250, 249, 246))
dr = ImageDraw.Draw(img)
# коробка комнаты
dr.polygon([P(0, 0, 0.02), P(RW, 0, 0.02), P(RW, 0, RD), P(0, 0, RD)], fill=(232, 224, 212))
dr.polygon([P(0, 0, RD), P(RW, 0, RD), P(RW, RH, RD), P(0, RH, RD)], fill=(246, 243, 238))
dr.polygon([P(0, 0, 0.02), P(0, 0, RD), P(0, RH, RD), P(0, RH, 0.02)], fill=(240, 236, 230))
dr.polygon([P(RW, 0, 0.02), P(RW, 0, RD), P(RW, RH, RD), P(RW, RH, 0.02)], fill=(240, 236, 230))
dr.polygon([P(0, RH, 0.02), P(RW, RH, 0.02), P(RW, RH, RD), P(0, RH, RD)], fill=(252, 251, 249))

# окно (восточная стена 140–280 см от юга) и дверь (южная стена 20–110 см) — с учётом вида
wx, wz0 = flip(RW, 1.4)
_, wz1 = flip(RW, 2.8)
if wz0 > wz1:
    wz0, wz1 = wz1, wz0
dr.polygon([P(wx, 0.9, wz0), P(wx, 0.9, wz1), P(wx, 2.1, wz1), P(wx, 2.1, wz0)],
           fill=(214, 231, 244), outline=(255, 255, 255), width=5)
dx0, dz = flip(0.2, 0.0)
dx1, _ = flip(1.1, 0.0)
if dz < 0.05:                     # дверь на стене за камерой — в кадре не видна
    door_visible = False
else:
    door_visible = True
    dr.polygon([P(min(dx0, dx1), 0, dz), P(max(dx0, dx1), 0, dz),
                P(max(dx0, dx1), 2.05, dz), P(min(dx0, dx1), 2.05, dz)],
               outline=(196, 150, 96), width=5)

refs, in_frame, behind = [], [], []


def fetch(it, maxpx=700):
    u = (it.get('img') or '')
    u = 'https:' + u if u.startswith('//') else u
    for cand in (u, u.replace('/small.', '/big.'), u.replace('/big.', '/small.')):
        try:
            req = urllib.request.Request(cand, headers={'User-Agent': 'Mozilla/5.0'})
            ph = Image.open(io.BytesIO(urllib.request.urlopen(req, timeout=25).read())).convert('RGB')
            ph.thumbnail((maxpx, maxpx))
            return clean_bg(ph).convert('RGBA')
        except Exception:
            continue
    return None


PALETTE = {'диван': (150, 152, 196), 'тв-тумба': (168, 168, 168), 'кресло': (196, 162, 152),
           'столик': (168, 140, 106), 'пуф': (176, 176, 156), 'стеллаж': (186, 178, 164),
           'комод': (186, 178, 164), 'стенка': (176, 164, 148), 'витрина': (176, 186, 196),
           'камин': (196, 150, 128), 'кашпо': (150, 176, 150), 'торшер': (120, 120, 120),
           'стол обеденный': (176, 152, 120), 'стул': (186, 176, 160)}

for role, v in sorted(L.items(), key=lambda kv: -kv[1]['z']):
    it = items.get(role)
    if it is None:
        continue
    rot = int(v.get('rot', 0)) % 360
    w, d = (v.get('w') or 60) / 100, (v.get('d') or 60) / 100
    if rot in (90, 270):
        w, d = d, w
    h = (it.get('h') or 60) / 100
    x, z = flip(v['x'] / 100, v['z'] / 100)
    if z - CAMZ < 1.0:                       # за камерой / вплотную к объективу
        behind.append(role)
        continue
    in_frame.append((role, it, int(v.get('w') or 0), int(v.get('d') or 0), int(it.get('h') or 0)))
    col = PALETTE.get(role, (180, 180, 180))
    x0, x1, z0, z1 = x - w / 2, x + w / 2, z - d / 2, z + d / 2
    top = [P(x0, h, z0), P(x1, h, z0), P(x1, h, z1), P(x0, h, z1)]
    front = [P(x0, 0, z0), P(x1, 0, z0), P(x1, h, z0), P(x0, h, z0)]
    side = [P(x1, 0, z0), P(x1, 0, z1), P(x1, h, z1), P(x1, h, z0)]
    dr.polygon(side, fill=tuple(int(c * 0.86) for c in col), outline=(70, 70, 70))
    dr.polygon(top, fill=tuple(min(255, int(c * 1.1)) for c in col), outline=(70, 70, 70))
    dr.polygon(front, fill=col, outline=(50, 50, 50))
    cxp, cyp = P(x, h / 2, z0)
    dr.text((cxp, cyp), role, fill=(20, 20, 20), font=font(19), anchor='mm',
            stroke_width=3, stroke_fill=(255, 255, 255))
    ph = fetch(it)
    if ph is not None:
        buf = io.BytesIO()
        ph.save(buf, 'PNG')
        refs.append(buf.getvalue())

frame_path = os.path.join(HERE, f'v3set{n}-frame{"-B" if VIEW == "B" else ""}.png')
img.save(frame_path)
print('каркас:', frame_path)

STYLE = s.get('style')
sblock = ''
if STYLE:
    sp = json.load(open(os.path.join(HERE, 'styles.json')))['styles']
    if STYLE in sp:
        sblock = ' ' + sp[STYLE]['prompt']

listed = "; ".join(f"{r} «{(it.get('name') or '')[:48]}» {w}x{d} cm"
                   + (f", {h} cm tall" if h else "") for r, it, w, d, h in in_frame)
extras = []
if any(r == 'тв-тумба' for r, *_ in in_frame):
    extras.append("a flat TV with the screen off stands on the TV unit (part of the TV zone, not extra furniture)")
if 'люстра' in items:
    extras.append("the ceiling light hangs over the seating area")

PROMPT = (
    f"The attached image is a 3D BLOCK-OUT of a real living room {RW:.1f} x {RD:.1f} m "
    f"({RW*RD:.0f} sq m), ceiling 2.7 m, seen from the exact camera of the final photo. "
    "Every grey box is a real piece of furniture: its position, footprint size and height are "
    "correct and must be kept. Replace each box with the real product from the reference photos, "
    "keeping the product's exact design, colour, materials and proportions, and keeping the box's "
    "place, size and facing. Render ONE photorealistic interior photo. "
    f"EXACTLY these pieces are in the frame and nothing else: {listed}. "
    + (f"Out of frame, behind the camera: {', '.join(behind)} — do not draw them. " if behind else "")
    + ("The door is visible in this view. " if door_visible else "The entrance door is behind the camera. ")
    + (("Also: " + "; ".join(extras) + ". ") if extras else "")
    + "Do not add any other furniture, lamps, rugs or plants beyond the list."
    + sblock +
    " Small city flat, honest scale — keep the room exactly as wide and as deep as the block-out, "
    "do not enlarge it. Natural daylight from the window, soft shadows, cosy styling, storage tops "
    "styled with two or three small objects. No people, no text, no watermarks."
)

if '--frame-only' in sys.argv:
    print(PROMPT[:600])
    sys.exit(0)


def img_edit(base_png, prompt, refs=()):
    B = uuid.uuid4().hex
    body = io.BytesIO()

    def part(name, val, fname=None, ctype=None):
        body.write(f"--{B}\r\n".encode())
        if fname:
            body.write(f'Content-Disposition: form-data; name="{name}"; filename="{fname}"\r\n'
                       f'Content-Type: {ctype}\r\n\r\n'.encode())
            body.write(val)
            body.write(b"\r\n")
        else:
            body.write(f'Content-Disposition: form-data; name="{name}"\r\n\r\n{val}\r\n'.encode())

    part("model", "gpt-image-2")
    part("prompt", prompt)
    part("size", "1536x1024")
    part("quality", "medium")
    part("n", "1")
    part("image[]", base_png, "frame.png", "image/png")
    for i, rb in enumerate(refs[:12]):
        part("image[]", rb, f"ref{i}.png", "image/png")
    body.write(f"--{B}--\r\n".encode())
    req = urllib.request.Request("https://api.openai.com/v1/images/edits", data=body.getvalue(),
                                 headers={"Authorization": f"Bearer {OAI}",
                                          "Content-Type": f"multipart/form-data; boundary={B}"})
    with urllib.request.urlopen(req, timeout=600) as r:
        return base64.b64decode(json.loads(r.read())['data'][0]['b64_json'])


dump = os.environ.get('DUMP_PAYLOAD')
if dump:
    os.makedirs(dump, exist_ok=True)
    img.save(os.path.join(dump, f'frame{VIEW}-base.png'))
    open(os.path.join(dump, f'frame{VIEW}-prompt.txt'), 'w').write(PROMPT)

buf = io.BytesIO()
img.save(buf, 'PNG')
out = img_edit(buf.getvalue(), PROMPT, refs)
res = os.path.join(HERE, f'v3set{n}-frameshot{"-B" if VIEW == "B" else ""}.jpg')
open(res, 'wb').write(out)
print('готово:', res)
