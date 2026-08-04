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

import steps  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
SCENE_DIR = os.environ.get('SCENE_DIR', os.path.expanduser('~/scout-scenes'))
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
    extra, rel = derived(room, placements, sets[n - 1]['items'])
    RELATIONS.clear()
    RELATIONS.update(rel)
    placements += extra
    return room, placements


RELATIONS: dict[str, str] = {}      # роль → на чём стоит/лежит (для подсказки модели)


def derived(room, placements, items):
    """Предметы, которых нет в раскладке пола, но которые обязаны быть в кадре.

    Телевизор, ковёр и люстра раньше не передавались вовсе — генератор ставил их куда придётся
    (владелец: «телек не там стоит, в угол не влез»). Теперь они часть геометрии.
    """
    by = {p.role: p for p in placements}
    out = []
    rel: dict[str, str] = {}
    tv_stand = by.get('тв-тумба')
    if tv_stand is not None and 'тв' not in by:
        w = min(float(tv_stand.item.w_cm) * 0.85, 120.0)
        rel['тв'] = 'висит на стене над тв-тумбой'
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
        rel['ковёр'] = ('лежит плашмя на полу под журнальным столиком, длинной стороной ВДОЛЬ '
                        'дивана (параллельно его спинке)')
        out.append(Placement(role='ковёр', x=table.x, y=table.y, rot=0,
                             item=Item(role='ковёр', w_cm=w_cm, d_cm=d_cm, h_cm=1.0)))
    # Декор на поверхностях: мы знаем высоту столешницы каждого предмета, поэтому ставим точно.
    # Так делают в дизайн-подаче: без мелочей кадр выглядит нежилым (владелец, 2026-08-04).
    # (хозяин, сдвиг вдоль его ширины, доля высоты — куда садится, сдвиг вперёд от спинки, см)
    # (хозяин, сдвиг вдоль ширины, доля высоты, сдвиг вперёд см, потолок ширины см)
    # Мягкий декор ограничиваем по размеру: плед 140 см в фас превращался в белую плиту на весь
    # диван, подушки — в щиты (владелец, 2026-08-04).
    hosts = {'ваза': ('комод', 0.0, 1.0, 0.0, 40.0), 'лампа': ('комод', -0.34, 1.0, 0.0, 40.0),
             'подушка': ('диван', -0.30, 0.50, 12.0, 50.0),
             'подушка 2': ('диван', 0.18, 0.50, 12.0, 50.0),
             'плед': ('диван', 0.46, 0.42, 6.0, 65.0)}
    for role, (host_role, along, hfrac, fwd_cm, wmax) in hosts.items():
        host = by.get(host_role)
        it_spec = items.get(role)
        if host is None or it_spec is None or role in by:
            continue
        hw = float(host.item.w_cm)
        rot = int(round(host.rot)) % 360
        dx, dy = (hw * along, 0.0) if rot in (0, 180) else (0.0, hw * along)
        face = {0: (0.0, 1.0), 90: (1.0, 0.0), 180: (0.0, -1.0), 270: (-1.0, 0.0)}[rot]
        dx += face[0] * fwd_cm                      # подушки — на сиденье, а не на спинку
        dy += face[1] * fwd_cm
        top = float(host.item.h_cm or 60) * hfrac
        rel[role] = ('лежит на сиденье дивана' if host_role == 'диван'
                     else f'стоит на поверхности: {host_role}')
        w_cm = min(float(it_spec.get('w') or 30), wmax)
        h_cm = float(it_spec.get('h') or 30)
        if role == 'плед':
            h_cm = max(h_cm, 55.0)                  # плед свисает с подлокотника
        out.append(Placement(role=role, x=host.x + dx, y=host.y + dy, rot=host.rot,
                             elev_cm=top,
                             item=Item(role=role, w_cm=w_cm,
                                       d_cm=min(float(it_spec.get('d') or 25), wmax),
                                       h_cm=h_cm)))

    if 'пуф' in by:
        rel['пуф'] = 'стоит на полу перед диваном и развёрнут сиденьем к нему'
    if 'столик' in by:
        rel['столик'] = 'стоит на ковре перед диваном, параллельно его спинке'
    if 'кресло' in by:
        rel['кресло'] = 'стоит на полу и развёрнуто к дивану'

    lamp = items.get('люстра')
    if lamp and 'люстра' not in by:
        # Люстра — всегда по ЦЕНТРУ комнаты, а не над зоной отдыха: это классика подвесного
        # освещения, к тому же так она не «привязывается» к дивану (владелец, 2026-08-04).
        h = float(lamp.get('h') or 45)
        rel['люстра'] = 'висит на потолке ровно по центру комнаты'
        out.append(Placement(role='люстра', x=room.width_cm / 2, y=room.depth_cm / 2,
                             rot=0, elev_cm=270.0 - h,
                             item=Item(role='люстра', w_cm=float(lamp['w']),
                                       d_cm=float(lamp['d']), h_cm=h)))

    return out, rel


def draw_plan(room: Room, placements: list[Placement], cams, path: str) -> str:
    """План сверху из ТЕХ ЖЕ placements + позиции камер и сектор обзора."""
    from planner.geometry import footprint

    sc = 900 / max(room.width_cm, room.depth_cm)
    pad = 92
    W = int(room.width_cm * sc) + pad * 2
    H = int(room.depth_cm * sc) + pad * 2 + 20
    img = Image.new('RGB', (W, H), '#F6F7F5')
    d = ImageDraw.Draw(img, 'RGBA')

    def T(x, z):                                   # z вверх, как в viz_plan
        return (pad + x * sc, pad + (room.depth_cm - z) * sc)

    d.rectangle([T(0, room.depth_cm), T(room.width_cm, 0)], outline='#1A1F1C', width=3)
    f_small = ImageFont.truetype(FONT, 15)
    f_cam = ImageFont.truetype(FONT, 17)
    f_dim = ImageFont.truetype(FONT, 19)

    # размерные линии и площадь — план должен читаться как чертёж, а не как схема
    top = pad - 26
    d.line([(pad, top), (pad + room.width_cm * sc, top)], fill='#5C655E', width=2)
    for x in (pad, pad + room.width_cm * sc):
        d.line([(x, top - 7), (x, top + 7)], fill='#5C655E', width=2)
    wtxt = f'{room.width_cm / 100:.2f} м'
    d.text((pad + room.width_cm * sc / 2 - d.textlength(wtxt, font=f_dim) / 2, top - 26),
           wtxt, fill='#3A423C', font=f_dim)
    left = pad - 26
    d.line([(left, pad), (left, pad + room.depth_cm * sc)], fill='#5C655E', width=2)
    for y in (pad, pad + room.depth_cm * sc):
        d.line([(left - 7, y), (left + 7, y)], fill='#5C655E', width=2)
    d.text((left - 22, pad + room.depth_cm * sc / 2), f'{room.depth_cm / 100:.2f} м',
           fill='#3A423C', font=f_dim, anchor='mm')
    area = f'{room.width_cm * room.depth_cm / 10000:.1f} м²'
    d.text((pad + 10, pad + room.depth_cm * sc + 12), f'Площадь {area}',
           fill='#3A423C', font=f_dim)

    used: list[tuple[float, float, float]] = []          # занятые прямоугольники подписей
    for p in sorted(placements, key=lambda q: -(q.item.w_cm * q.item.d_cm)):
        poly = footprint(p, p.item)
        xs, ys = poly.exterior.coords.xy
        pts = [T(x, y) for x, y in zip(xs, ys)]
        flat = float(p.item.h_cm or 60) <= 5                 # ковёр рисуем контуром, без заливки
        d.polygon(pts, fill=(63, 107, 87, 0 if flat else 48), outline='#3F6B57')
        cx, cz = T(p.x, p.y)
        label = f'{p.role} {int(p.item.w_cm)}×{int(p.item.d_cm)}'
        w = d.textlength(label, font=f_small)
        y = cz - 8
        for _ in range(12):                                  # сдвигаем, пока подпись не свободна
            if all(abs(y - uy) > 17 or abs(cx - ux) > (w + uw) / 2 for ux, uy, uw in used):
                break
            y += 17
        used.append((cx, y, w))
        d.rectangle([cx - w / 2 - 3, y - 2, cx + w / 2 + 3, y + 17], fill=(246, 247, 245, 225))
        d.text((cx - w / 2, y), label, fill='#1A1F1C', font=f_small)

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
        # направление съёмки — двумя тонкими лучами до стен, без заливки: заливка забивала лист
        for a in (-half, half):
            reach = max(room.width_cm, room.depth_cm)
            x2 = min(max(ex + math.cos(ang + a) * reach, 0), room.width_cm)
            z2 = min(max(ez + math.sin(ang + a) * reach, 0), room.depth_cm)
            d.line([T(ex, ez), T(x2, z2)], fill=(162, 73, 59, 120), width=2)
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
        # карта ПУСТОЙ комнаты: базовый кадр рисуется по ней, иначе генератор заполняет пустые
        # стены своей мебелью (шкаф, обеденный стол, торшер — поймано 2026-08-04)
        save_maps(compile_scene(room, [], cam), f'{prefix}-empty')
        steps.reset(prefix)
        steps.log(prefix, 'Считаем сцену из плана расстановки',
                  params={'камера': cam.name, 'точка (см)': [round(v) for v in cam.eye],
                          'объектив': f'{cam.fov_deg:.0f}°', 'кадр': [cam.width, cam.height],
                          'в кадре': list(out['visible']), 'вне кадра': out['behind']},
                  inputs=[os.path.join(SCENE_DIR, f'scene{n}-plan.png')],
                  outputs=[f'{prefix}-clay.png', f'{prefix}-instances.png',
                           f'{prefix}-empty-clay.png'],
                  note='Карта глубины, маски объектов и пустая комната — всё из нашей геометрии, '
                       'без нейросети.')
        print(f'{cam.name}: видно {", ".join(out["visible"])}'
              + (f'  · вне кадра: {", ".join(out["behind"])}' if out['behind'] else ''))


if __name__ == '__main__':
    main()
