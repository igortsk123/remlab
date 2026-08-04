#!/usr/bin/env python3
"""Проверка кадра ПЛАНОМ: проецирует метровую сетку пола и следы предметов на готовый кадр.

Зачем: «на глаз» расхождение плана и генерации не ловится — так у нас месяц жил зеркальный кадр.
Сетка на полу даёт измеримый ответ на вопрос «объекты на правильном расстоянии?»: если мебель
стоит на своём следе и подпись «3 м» приходится туда, где по плану 3 метра — масштаб верный.

  ~/venvs/scout/bin/python scene_check.py 21 A            # → scene21-A-check.jpg
"""
import json
import os
import sys

sys.path.insert(0, '/home/pakar/igor/remlab/services/planner-solver')

import numpy as np  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from planner.geometry import footprint  # noqa: E402
from planner.scene import cameras_for  # noqa: E402
from scene_build import SCENE_DIR, load_scene  # noqa: E402

FONT = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'


def projector(cam, size):
    """Мировая точка (x, высота, y) → пиксель кадра; None, если за камерой."""
    eye, fwd, right, up = cam.basis()
    W, H = size
    focal = (W / 2) / np.tan(np.radians(cam.fov_deg) / 2)

    def to_px(x, h, y):
        rel = np.array([x, h, y], float) - eye
        if cam.cyl:                       # панорама: колонка = угол, строка = наклон
            horiz = float(np.hypot(rel @ right, rel @ fwd))
            if horiz <= 1e-3:
                return None
            ang = float(np.arctan2(rel @ right, rel @ fwd))
            if abs(ang) > np.radians(cam.fov_deg) / 2:
                return None
            fv = (H / 2) / np.tan(np.radians(cam.vfov_deg) / 2)
            return (W / 2 + ang / np.radians(cam.fov_deg) * W,
                    H / 2 - fv * float(rel @ up) / horiz)
        z = float(rel @ fwd)
        if z <= 1e-3:
            return None
        # сдвиг объектива обязан учитываться и в проверке — иначе следы плана уезжают вниз
        # на 0.1 высоты кадра и кажется, что мебель висит (поймано 2026-08-04)
        return (W / 2 + focal * float(rel @ right) / z,
                H / 2 - focal * float(rel @ up) / z + cam.shift_y * H)

    return to_px


def main() -> None:
    n = int(sys.argv[1])
    view = sys.argv[2] if len(sys.argv) > 2 else 'A'
    model = sys.argv[sys.argv.index('--model') + 1] if '--model' in sys.argv else 'sdxl'
    room, placements = load_scene(n)
    cam = next(c for c in cameras_for(room, placements) if c.name == view)
    prefix = os.path.join(SCENE_DIR, f'scene{n}-{view}')
    src = (f'{prefix}-final.jpg' if '--final' in sys.argv else
           f'{prefix}-pasted.jpg' if '--pasted' in sys.argv else f'{prefix}-base-{model}.jpg')
    img = Image.open(src).convert('RGB')
    to_px = projector(cam, img.size)
    d = ImageDraw.Draw(img, 'RGBA')
    f_lbl = ImageFont.truetype(FONT, 26)
    f_m = ImageFont.truetype(FONT, 22)

    def seg(a, b, fill, width=2):
        # в панораме прямая — дуга, поэтому рисуем ломаной по 12 точкам
        pts = [to_px(*(a[k] + (b[k] - a[k]) * i / 12 for k in range(3))) for i in range(13)]
        pts = [q for q in pts if q]
        if len(pts) > 1:
            d.line(pts, fill=fill, width=width)

    step = 100.0                                   # метровая сетка пола
    xs = np.arange(0, room.width_cm + 1, step)
    ys = np.arange(0, room.depth_cm + 1, step)
    for x in xs:
        seg((x, 0, 0), (x, 0, room.depth_cm), (255, 255, 255, 90))
    for y in ys:
        seg((0, 0, y), (room.width_cm, 0, y), (255, 255, 255, 90))

    # ось от камеры вперёд с подписями расстояния — «сколько метров до этой точки»
    ex, _, ez = cam.eye
    tx, _, tz = cam.target
    vx, vz = tx - ex, tz - ez
    ln = (vx ** 2 + vz ** 2) ** 0.5 or 1.0
    for m in range(1, 9):
        px_ = to_px(ex + vx / ln * m * 100, 0, ez + vz / ln * m * 100)
        if not px_ or not (0 < px_[0] < img.width and 0 < px_[1] < img.height):
            continue
        d.ellipse([px_[0] - 5, px_[1] - 5, px_[0] + 5, px_[1] + 5], fill=(255, 214, 10))
        d.text((px_[0] + 9, px_[1] - 12), f'{m} м', fill=(255, 214, 10), font=f_m,
               stroke_width=3, stroke_fill=(0, 0, 0))

    for p in placements:                            # следы предметов по плану
        poly = footprint(p, p.item)
        cx_, cy_ = poly.exterior.coords.xy
        pts = [to_px(x, 0, y) for x, y in zip(cx_, cy_)]
        if any(q is None for q in pts):
            continue
        for q0, q1 in zip(list(zip(cx_, cy_)), list(zip(cx_, cy_))[1:]):
            seg((q0[0], 0, q0[1]), (q1[0], 0, q1[1]), (80, 230, 160, 230), 4)
        top = to_px(p.x, float(p.item.h_cm or 60), p.y)
        if top and 0 < top[0] < img.width:
            d.text((top[0] - 30, top[1] - 14), p.role, fill=(255, 90, 70), font=f_lbl,
                   stroke_width=3, stroke_fill=(255, 255, 255))

    dst = f'{prefix}-check{"-final" if "--final" in sys.argv else ""}.jpg'
    img.save(dst, quality=90)
    meta = json.load(open(f'{prefix}-frame.json'))
    print(dst, '· видно:', ', '.join(meta['visible']))


if __name__ == '__main__':
    main()
