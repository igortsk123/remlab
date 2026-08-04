#!/usr/bin/env python3
"""Генерация кадра ОТ ПЛАНА (вариант владельца 2026-08-03).

Идея: не строить поддельную перспективу с вклеенными фото, а отдать модели
план сверху, где фото товаров стоят ровно там, где их поставил солвер, плюс сами фото
референсами — и короткое задание «сделай из этого фотореалистичный интерьер».
Модель сама решает перспективу, развороты и свет; мы не объясняем ей градусы.

  ~/venvs/scout/bin/python viz_plan.py 21            # план-фото + генерация
  ~/venvs/scout/bin/python viz_plan.py 21 --plan-only  # только план-фото, без вызова модели
"""
import base64
import io
import json
import os
import re
import sys
import urllib.request
import uuid

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
exec(open(os.path.join(HERE, 'viz3.py')).read().split("HERE=")[0])   # clean_bg и утилиты

OAI = None
for line in open('/home/pakar/igor/v0-health-card/backend/.env'):
    m = re.match(r'OPENAI_API_KEY=(.+)', line.strip())
    if m:
        OAI = m.group(1).strip().strip('"')

n = int(sys.argv[1]) if len(sys.argv) > 1 else 1
sets = json.load(open(os.path.join(HERE, 'sets3.json')))
s = sets[n - 1]
items = {r.replace(' 2', ''): it for r, it in s['items'].items()}
L = json.load(open(os.path.join(HERE, f'v3set{n}-layout.json')))
room = L.pop('_room', None) or {'w': 400, 'd': 460}
RW, RD = room['w'], room['d']

W, H = 1400, int(1400 * RD / RW)
SC = W / RW
PAD = 40


def font(sz):
    for p in ('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
              '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf'):
        if os.path.exists(p):
            return ImageFont.truetype(p, sz)
    return ImageFont.load_default()


def fetch(it, maxpx=700):
    """Фото товара без фона (та же вырезка, что в основном конвейере)."""
    u = it.get('img') or ''
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


img = Image.new('RGB', (W + PAD * 2, H + PAD * 2), (252, 250, 247))
dr = ImageDraw.Draw(img)
dr.rectangle([PAD, PAD, PAD + W, PAD + H], fill=(255, 255, 255), outline=(60, 60, 60), width=3)


def T(x, z):
    return (PAD + x * SC, PAD + (RD - z) * SC)


# проёмы: дверь (юг) и окно (восток) — рисуем как в плане солвера
dr.rectangle([T(20, 92)[0], T(20, 92)[1], T(110, 0)[0], T(110, 0)[1]],
             outline=(200, 140, 70), width=3)
dr.text(T(30, 46), 'дверь', fill=(180, 110, 50), font=font(20))
dr.rectangle([T(RW - 12, 280)[0], T(RW - 12, 280)[1], T(RW, 140)[0], T(RW, 140)[1]],
             fill=(190, 220, 245))
dr.text(T(RW - 130, 210), 'окно', fill=(60, 110, 170), font=font(20))

refs = []
placed_names = []
for role, v in L.items():
    it = items.get(role)
    if not it:
        continue
    x, z, rot = v['x'], v['z'], int(v.get('rot', 0)) % 360
    w, d = v.get('w') or 60, v.get('d') or 60
    # прямоугольник — по СЛЕДУ предмета с учётом поворота (при 90/270 стороны меняются местами)
    fw, fd = (d, w) if rot in (90, 270) else (w, d)
    px0, py0 = T(x - fw / 2, z + fd / 2)
    px1, py1 = T(x + fw / 2, z - fd / 2)
    bw, bh = int(px1 - px0), int(py1 - py0)
    ph = fetch(it)
    if ph is not None:
        # фото в ячейке — только для опознания товара; его разворот на схеме ничего не значит
        # (владелец 2026-08-03: «на плане сверху даже если перевёрнута — пофиг»)
        ph.thumbnail((max(bw - 6, 24), max(bh - 6, 24)))
        img.paste(ph, (int(px0 + (bw - ph.width) / 2), int(py0 + (bh - ph.height) / 2)), ph)
        buf = io.BytesIO()
        ph.convert('RGBA').save(buf, 'PNG')
        refs.append(buf.getvalue())
    dr.rectangle([px0, py0, px1, py1], outline=(120, 120, 120), width=2)
    dr.text(((px0 + px1) / 2, py1 - 14), f"{role} {int(w)}x{int(d)} см", fill=(30, 30, 30),
            font=font(18), anchor='mm', stroke_width=3, stroke_fill=(255, 255, 255))
    placed_names.append(f"{role}: «{(it.get('name') or '')[:50]}»")

dr.text((PAD + W / 2, PAD - 22), f"{RW} см", fill=(70, 70, 70), font=font(22), anchor='mm')
dr.text((PAD - 22, PAD + H / 2), f"{RD} см", fill=(70, 70, 70), font=font(22), anchor='mm')
dr.text((PAD, PAD + H + 8), f"План сверху · комната {RW}x{RD} см ({RW * RD / 10000:.0f} м²) · "
        f"низ плана — сторона, с которой смотрит камера", fill=(90, 90, 90), font=font(20))
plan_path = os.path.join(HERE, f'v3set{n}-planphoto.png')
img.save(plan_path)
print('план-фото:', plan_path)

STYLE = s.get('style')
sblock = ''
if STYLE:
    sp = json.load(open(os.path.join(HERE, 'styles.json')))['styles']
    if STYLE in sp:
        sblock = ' ' + sp[STYLE]['prompt']

# --- камера и «что за спиной» считаются ОТ ПЛАНА -------------------------------------------
# Ошибка предыдущей версии: камера всегда стояла у нижнего края, а там же стояла ТВ-тумба —
# телевизор оказывался ЗА камерой, и модель «чинила» это, перетаскивая его в кадр.
VIEW = 'B' if '--view' in sys.argv and sys.argv[sys.argv.index('--view') + 1] == 'B' else 'A'
_sofa = L.get('диван'); _tv = L.get('тв-тумба')
if VIEW == 'A':                     # смотрим на зону отдыха: камера у стены ТВ, ТВ за спиной
    behind = [r for r, v in L.items() if v['z'] < RD * 0.28]
    cam_txt = ("The camera stands at the BOTTOM edge of the plan, at the wall where the TV unit is. "
               "Everything drawn in the bottom fifth of the plan is BEHIND the camera and must NOT "
               "appear in the photo")
else:                               # смотрим на ТВ-зону: камера у стены дивана, диван за спиной
    behind = [r for r, v in L.items() if v['z'] > RD * 0.72]
    cam_txt = ("The camera stands at the TOP edge of the plan, behind the sofa. Everything drawn in "
               "the top fifth of the plan is BEHIND the camera and must NOT appear in the photo")
if behind:
    cam_txt += " — namely: " + ", ".join(behind)
cam_txt += ". Everything else from the plan MUST be visible in the frame."

# ТВ в каталоге нет — в сете есть только тумба; телевизор дорисовывается по правилу
# (он часть ТВ-зоны, а не «лишняя мебель»). В старом конвейере это была отдельная фраза промпта,
# при переносе она потерялась и тумба осталась пустой (вердикт владельца 2026-08-03).
_extras = []
if 'тв-тумба' in L or 'стенка' in L:
    _extras.append("A flat television stands on the TV unit, screen off — it is part of the TV zone, "
                   "not extra furniture")
if 'люстра' in items:
    _extras.append("the ceiling light from the item list hangs over the seating area")
_extras_txt = (" " + "; ".join(_extras) + ".") if _extras else ""

PROMPT = (
    f"The attached image is a SCHEMATIC top-down floor plan of a real living room "
    f"{RW/100:.1f} x {RD/100:.1f} m ({RW*RD/10000:.0f} sq m), ceiling 2.7 m. Each rectangle is a "
    "footprint drawn to scale with its size in cm; the product photo inside a rectangle only says "
    "WHICH item stands there — the photo's own orientation on the plan means nothing, and the plan "
    "is a scheme, not a technical drawing. "
    "Render ONE photorealistic interior photo of this room at eye level. " + cam_txt + " "
    "The plan is already a designer-approved layout: do NOT move pieces to other walls, do not "
    "swap them around. Keep the room proportions, the door and window where the plan shows them, "
    "and every item in ITS place and of its size. Only the fine orientation is yours: each piece "
    "stands parallel to the walls and is turned the way it is used — seating towards the seating "
    "group, storage flat against its wall. Keep every product's exact design, colour and "
    "proportions from its photo; do not add or remove furniture." + _extras_txt + sblock +
    " Small city flat, honest scale — do not make the room look larger. Natural daylight from the "
    "window, soft shadows, cosy styling, storage tops styled with a few small objects. "
    "No people, no text, no watermarks. Items in the plan: " + "; ".join(placed_names) + "."
)

if '--plan-only' in sys.argv:
    print(PROMPT[:400])
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
    part("image[]", base_png, "plan.png", "image/png")
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
    img.save(os.path.join(dump, 'planphoto-base.png'))
    open(os.path.join(dump, 'planphoto-prompt.txt'), 'w').write(PROMPT)

buf = io.BytesIO()
img.save(buf, 'PNG')
out = img_edit(buf.getvalue(), PROMPT, refs)
res = os.path.join(HERE, f'v3set{n}-planshot{"-B" if VIEW == "B" else ""}.jpg')
open(res, 'wb').write(out)
print('готово:', res)
