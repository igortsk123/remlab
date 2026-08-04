#!/usr/bin/env python3
"""Ф1: сборка сцены комплекта — карты для всех камер И план, из ОДНОГО источника.

Зачем отдельный вход: раньше карты строил разовый скрипт, а план рисовал `viz_plan.py` по своей
копии раскладки — владелец поймал расхождение «план не совпадает с картой глубины». Здесь и карты,
и план читают один `v3set{n}-layout.json`, поэтому разойтись физически не могут.

План рисуется с камерами: точка съёмки и сектор обзора каждой камеры — видно, что попадёт в кадр.

  ~/venvs/scout/bin/python scene_build.py 21              # A, B, T
  ~/venvs/scout/bin/python scene_build.py 21 --views A
"""
import json
import math
import os
import sys

sys.path.insert(0, '/home/pakar/igor/remlab/services/planner-solver')

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from planner.models import Item, Placement, Room  # noqa: E402
from planner.scene import cameras_for, compile_scene, save_maps  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
SCENE_DIR = os.environ.get('SCENE_DIR', '/tmp/room-scene')
FONT = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'


def load_scene(n: int) -> tuple[Room, list[Placement]]:
    """Комната и расстановка из канонического `v3set{n}-layout.json` (его же рисует viz_plan)."""
    L = json.load(open(os.path.join(HERE, f'v3set{n}-layout.json')))
    room_spec = L.pop('_room')
    sets = json.load(open(os.path.join(HERE, 'sets3.json')))
    heights = {role: it.get('h') for role, it in sets[n - 1]['items'].items()}
    room = Room(width_cm=room_spec['w'], depth_cm=room_spec['d'],
                openings=room_spec.get('openings', []))
    placements = []
    for role, p in L.items():
        it = Item(role=role, w_cm=p['w'], d_cm=p['d'], h_cm=heights.get(role) or 60,
                  corner=bool(p.get('corner')))
        placements.append(Placement(role=role, x=p['x'], y=p['z'], rot=p['rot'], item=it))
    placements += derived(room, placements, sets[n - 1]['items'])
    return room, placements


def derived(room, placements, items):
    """Предметы, которых нет в раскладке пола, но которые обязаны быть в кадре.

    Телевизор, ковёр и люстра раньше не передавались вовсе — генератор ставил их куда придётся
    (владелец: «телек не там стоит, в угол не влез»). Теперь они часть геометрии.
    """
    by = {p.role: p for p in placements}
    out = []
    tv_stand = by.get('тв-тумба')
    if tv_stand is not None and 'тв' not in by:
        w = min(float(tv_stand.item.w_cm) * 0.85, 120.0)
        out.append(Placement(role='тв', x=tv_stand.x, y=tv_stand.y, rot=tv_stand.rot,
                             elev_cm=105.0,
                             item=Item(role='тв', w_cm=w, d_cm=8.0, h_cm=w * 0.58)))
    sofa, table = by.get('диван'), by.get('столик')
    rug = items.get('ковёр')
    if rug and sofa is not None and table is not None and 'ковёр' not in by:
        # длинная сторона ковра — вдоль длинной стороны дивана (решение владельца)
        long, short = max(float(rug['w']), float(rug['d'])), min(float(rug['w']), float(rug['d']))
        long, short = max(long, float(sofa.item.w_cm) * 0.9), max(short, 120.0)
        horizontal = int(round(sofa.rot)) % 180 == 0
        w_cm, d_cm = (long, short) if horizontal else (short, long)
        out.append(Placement(role='ковёр', x=table.x, y=table.y, rot=0,
                             item=Item(role='ковёр', w_cm=w_cm, d_cm=d_cm, h_cm=1.0)))
    lamp = items.get('люстра')
    if lamp and 'люстра' not in by:
        cx = (sofa.x if sofa is not None else room.width_cm / 2)
        cy = ((sofa.y + table.y) / 2 if sofa is not None and table is not None
              else room.depth_cm / 2)
        h = float(lamp.get('h') or 45)
        out.append(Placement(role='люстра', x=cx, y=cy, rot=0, elev_cm=270.0 - h,
                             item=Item(role='люстра', w_cm=float(lamp['w']),
                                       d_cm=float(lamp['d']), h_cm=h)))
    return out


def draw_plan(room: Room, placements: list[Placement], cams, path: str) -> str:
    """План сверху из ТЕХ ЖЕ placements + позиции камер и сектор обзора."""
    from planner.geometry import footprint

    sc = 900 / max(room.width_cm, room.depth_cm)
    pad = 60
    W = int(room.width_cm * sc) + pad * 2
    H = int(room.depth_cm * sc) + pad * 2
    img = Image.new('RGB', (W, H), '#F6F7F5')
    d = ImageDraw.Draw(img, 'RGBA')

    def T(x, z):                                   # z вверх, как в viz_plan
        return (pad + x * sc, pad + (room.depth_cm - z) * sc)

    d.rectangle([T(0, room.depth_cm), T(room.width_cm, 0)], outline='#1A1F1C', width=3)
    f_small = ImageFont.truetype(FONT, 15)
    f_cam = ImageFont.truetype(FONT, 17)

    for p in placements:
        poly = footprint(p, p.item)
        xs, ys = poly.exterior.coords.xy
        pts = [T(x, y) for x, y in zip(xs, ys)]
        d.polygon(pts, fill=(63, 107, 87, 55), outline='#3F6B57')
        cx, cz = T(p.x, p.y)
        label = f'{p.role} {int(p.item.w_cm)}×{int(p.item.d_cm)}'
        w = d.textlength(label, font=f_small)
        d.text((cx - w / 2, cz - 8), label, fill='#1A1F1C', font=f_small)

    for op in room.openings:                       # проёмы — на плане и в картах один источник
        o0, o1 = op.offset_cm, op.offset_cm + op.width_cm
        seg = {'south': ((o0, 0), (o1, 0)), 'north': ((o0, room.depth_cm), (o1, room.depth_cm)),
               'west': ((0, o0), (0, o1)), 'east': ((room.width_cm, o0), (room.width_cm, o1))}[op.wall]
        col = '#3B76A2' if op.kind == 'window' else '#B8862F'
        d.line([T(*seg[0]), T(*seg[1])], fill=col, width=9)
        mx, mz = T((seg[0][0] + seg[1][0]) / 2, (seg[0][1] + seg[1][1]) / 2)
        d.text((mx - 18, mz - 22), 'окно' if op.kind == 'window' else 'дверь', fill=col, font=f_cam)

    for cam in cams:
        if cam.ortho:
            continue
        ex, _, ez = cam.eye
        tx, _, tz = cam.target
        half = math.radians(cam.fov_deg) / 2
        ang = math.atan2(tz - ez, tx - ex)
        reach = max(room.width_cm, room.depth_cm) * 1.4
        cone = [T(ex, ez)] + [
            T(ex + math.cos(ang + a) * reach, ez + math.sin(ang + a) * reach)
            for a in (-half, -half / 2, 0, half / 2, half)
        ]
        d.polygon(cone, fill=(162, 73, 59, 38))
        px, pz = T(ex, ez)
        d.ellipse([px - 9, pz - 9, px + 9, pz + 9], fill='#A2493B')
        d.text((px + 13, pz - 10), f'камера {cam.name}', fill='#A2493B', font=f_cam)

    img.save(path)
    return path


def main() -> None:
    n = int(sys.argv[1])
    views = (sys.argv[sys.argv.index('--views') + 1].split(',')
             if '--views' in sys.argv else ['A', 'B', 'T'])
    os.makedirs(SCENE_DIR, exist_ok=True)
    room, placements = load_scene(n)
    cams = [c for c in cameras_for(room, placements) if c.name in views]

    plan = draw_plan(room, placements, cams, os.path.join(SCENE_DIR, f'scene{n}-plan.png'))
    print(plan)
    for cam in cams:
        out = compile_scene(room, placements, cam)
        prefix = os.path.join(SCENE_DIR, f'scene{n}-{cam.name}')
        save_maps(out, prefix)
        print(f'{cam.name}: видно {", ".join(out["visible"])}'
              + (f'  · вне кадра: {", ".join(out["behind"])}' if out['behind'] else ''))


if __name__ == '__main__':
    main()
