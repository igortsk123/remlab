#!/usr/bin/env python3
"""Финальный проход: аппликация + разметка + JSON-описание → фотореалистичный кадр.

В запрос уходит всё, что модель не может вывести из картинки:
  • что это за помещение (площадь, потолок, окно и дверь) и в каком стиле;
  • JSON по каждому номеру: товар, роль, габариты, материал и КАК он должен стоять/лежать;
  • два изображения — чистый кадр и он же с номерами (разметка служебная, рисовать её нельзя).

  ~/venvs/scout/bin/python viz_final.py 21 --cam C1
"""
import json
import os
import sys

from PIL import Image

import steps
from viz_marks import build
from viz_objects import edit_gpt_raw, product
from viz_base import fal_key, fal_run, uri_from_image
from viz_paste import cutout, trim_alpha

HERE = os.path.dirname(os.path.abspath(__file__))
SCENE_DIR = os.environ.get('SCENE_DIR', os.path.expanduser('~/scout-scenes'))


def room_brief(n: int) -> str:
    s = json.load(open(os.path.join(HERE, 'sets3.json')))[n - 1]
    # Про окна и двери в шапке не пишем: их состав для КАЖДОГО кадра считается отдельно
    # (openings_brief) — иначе шапка противоречит кадру, где проёмов нет.
    return (f'ROOM: a living room in a city flat, {s.get("band", "18-20")} m², '
            f'4.00 × 4.60 m, ceiling 2.7 m.')


def style_name(n: int) -> str:
    s = json.load(open(os.path.join(HERE, 'sets3.json')))[n - 1]
    sp = json.load(open(os.path.join(HERE, 'styles.json')))['styles']
    return sp.get(s.get('style', ''), {}).get('en', s.get('style', ''))


def style_brief(n: int) -> str:
    """Паспорт стиля: чем именно модель имеет право «делать ремонт»."""
    s = json.load(open(os.path.join(HERE, 'sets3.json')))[n - 1]
    sp = json.load(open(os.path.join(HERE, 'styles.json')))['styles']
    return sp.get(s.get('style', ''), {}).get('prompt', '')


def openings_brief(n: int, cam_name: str) -> str:
    """Проёмы считаем МЫ и передаём словами: где они в кадре и что их больше нет."""
    import math

    import numpy as np
    sys.path.insert(0, '/home/pakar/igor/remlab/services/planner-solver')
    from planner.scene import cameras_for
    from scene_build import load_scene
    room, placements = load_scene(n)
    cam = next(c for c in cameras_for(room, placements) if c.name == cam_name)
    eye, fwd, right, up = cam.basis()
    W, H = cam.width, cam.height
    focal = (W / 2) / math.tan(math.radians(cam.fov_deg) / 2)

    def where(pt):
        rel = np.array(pt, float) - eye
        z = float(rel @ fwd)
        if z <= 1e-3:
            return None
        u = W / 2 + focal * float(rel @ right) / z
        v = H / 2 - focal * float(rel @ up) / z + cam.shift_y * H
        return (u, v) if 0 <= u < W and 0 <= v < H else None

    seen = []
    for op in room.openings:
        o0, o1 = op.offset_cm, op.offset_cm + op.width_cm
        pts = {'south': [(o0, 0), (o1, 0)], 'north': [(o0, room.depth_cm), (o1, room.depth_cm)],
               'west': [(0, o0), (0, o1)], 'east': [(room.width_cm, o0), (room.width_cm, o1)]}[op.wall]
        got = [where([x, 120, y]) for x, y in pts]
        if not any(got):
            continue
        side = 'left' if (np.mean([g[0] for g in got if g]) < W / 2) else 'right'
        kind = 'window' if op.kind == 'window' else 'door'
        whole = 'fully in frame' if all(got) else 'only partly in frame'
        seen.append(f'one {kind} on the {side}-hand wall ({whole}, {int(op.width_cm)} cm wide)')
    if not seen:
        return ('There is NO window and NO door in this frame — all walls in view are blank. ')
    return 'Openings visible in this frame: ' + '; '.join(seen) + '. '


def legend_json(legend: list[dict]) -> str:
    """JSON для модели: номер → товар, роль, габариты, материал, как стоит."""
    out = []
    for e in legend:
        out.append({
            'id': e['n'],
            'product': e['товар'],
            'type': e['роль'],
            'size_cm': e['габариты_см'],
            'placement': e['положение'],
            'details': e.get('описание', ''),
            'visibility': e.get('видимость', 'виден целиком'),
        })
    return json.dumps(out, ensure_ascii=False)


def redraw_angled(n: int, prefix: str) -> None:
    """Предметы, повёрнутые к нам боком, фронтальным фото не вклеить — их перерисовывает
    дешёвая модель по их же фотографиям, в правильном ракурсе и на своём месте."""
    path = f'{prefix}-angled.json'
    angled = json.load(open(path)) if os.path.exists(path) else []
    if not angled:
        return
    view = Image.open(f'{prefix}-pasted.jpg').convert('RGB')
    refs, names = [], []
    for role in angled:
        try:
            it, photo = product(n, role)
        except KeyError:
            continue
        if os.path.exists(photo):
            refs.append(trim_alpha(cutout(photo)).convert('RGB'))
            names.append(f'{role} — {(it.get("name") or "")[:50]}')
    if not refs:
        return
    pr = ('Interior photo. The pieces listed below are missing or shown flat because their product '
          'photos are frontal while the camera sees them from the side. Draw them at their marked '
          'places in the correct perspective, using the reference photos for shape, colour and '
          'material: ' + '; '.join(names) + '. STRICT: keep every other object exactly as it is, '
          'do not move anything, add nothing else, keep walls, floor, window and door unchanged.')
    res = fal_run('fal-ai/nano-banana/edit', {
        'prompt': pr,
        'image_urls': [uri_from_image(view)] + [uri_from_image(r) for r in refs[:8]],
        'num_images': 1, 'output_format': 'png'}, fal_key())
    url = (res.get('images') or [{}])[0].get('url')
    if not url:
        return
    import io as _io
    import urllib.request as _u
    out = Image.open(_io.BytesIO(_u.urlopen(url, timeout=240).read())).convert('RGB')
    out.resize(view.size).save(f'{prefix}-pasted.jpg', quality=93)
    steps.log(prefix, 'Дорисовываем предметы, повёрнутые к камере боком',
              model='fal-ai/nano-banana/edit', prompt=pr,
              params={'предметы': angled, 'фото-референсов': len(refs)},
              inputs=[f'{prefix}-pasted.jpg'], outputs=[f'{prefix}-pasted.jpg'],
              note='Фронтальное фото на боковой ракурс не натянуть — эти предметы рисует модель '
                   'по их же фотографиям.')


def main() -> None:
    n = int(sys.argv[1])
    cam = sys.argv[sys.argv.index('--cam') + 1] if '--cam' in sys.argv else 'C1'
    prefix = os.path.join(SCENE_DIR, f'scene{n}-{cam}')
    if '--no-angled' not in sys.argv:
        redraw_angled(n, prefix)
    src, marked, legend = build(n, cam)
    clean = Image.open(src).convert('RGB').resize((1536, 1024))
    mark = Image.open(marked).convert('RGB').resize((1536, 1024))
    plan_p = os.path.join(SCENE_DIR, f'scene{n}-plan.png')
    plan = Image.open(plan_p).convert('RGB') if os.path.exists(plan_p) else None

    openings = openings_brief(n, cam)
    prompt = (
        f'{room_brief(n)}\n\n'
        'INPUT IMAGES\n'
        '1) The collage: every piece of furniture is a real product photo placed at its exact '
        'position and true size, on a neutral render of the room.\n'
        '2) The same frame with red numbered markers above each item and a leader line ending on '
        'the item — an annotation for you only.\n'
        '3) The floor plan of the room with the camera position and its field of view — use it to '
        'understand what stands where and which parts the frame cuts off.\n\n'
        'WHAT YOU MUST NOT CHANGE\n'
        '- Products. Never replace, restyle, recolour or resize any item from the list. What is '
        'shown IS the product the customer buys.\n'
        '- Positions. Do not move an item to another place and do not swap items.\n'
        f'- Openings. {openings} Do NOT invent, move, add or remove any window or door: their '
        'places are given by the plan, not by you.\n'
        '- The room shell: wall planes, floor plane, ceiling height and the camera stay as they are.\n\n'
        'WHAT YOU MAY AND SHOULD DO\n'
        '- Turn an item slightly around its own vertical axis so it sits naturally (an ottoman '
        'faces the sofa, a coffee table is parallel to the sofa). Product photos are frontal, a '
        'small rotation makes the scene believable.\n'
        '- Renovate the room in the chosen style: wall finish and colour, flooring, ceiling, '
        'skirting, and the FRAMES and dressing of the given window and door (frame colour, '
        'curtains) — all in that style, without changing where they are.\n'
        '- Add greenery and wall art that suit the style: potted plants and framed prints only.\n'
        '- Every planter or pot in the list MUST have a living plant in it.\n'
        '- Light the scene naturally, add soft contact shadows under every item, soften the pasted '
        'outlines, make floor and wall junctions correct, keep vertical lines vertical.\n'
        '- Add nothing else: no extra furniture, no rugs, no lamps, no TV, no textiles beyond the '
        'list.\n\n'
        f'STYLE OF THIS SET — {style_name(n)}\n{style_brief(n)}\n\n'
        'ITEMS IN THE FRAME (JSON: id = number on image 2)\n' + legend_json(legend) + '\n\n'
        'The visibility field says whether an item is whole or cut by the frame edge: never '
        'complete a cut-off item — draw exactly the part that is in the frame. Follow the '
        'placement field exactly.\n\n'
        'OUTPUT: one photorealistic interior photograph, natural daylight, no people, no text, '
        'no numbers, no circles, no leader lines.'
    )
    if '--print-prompt' in sys.argv:        # показать запрос без генерации
        print(prompt)
        return
    imgs = [clean, mark] + ([plan] if plan is not None else [])
    out = edit_gpt_raw(imgs, prompt, size='1536x1024')
    dst = f'{prefix}-final.jpg'
    out.save(dst, quality=94)
    steps.log(prefix, 'Делаем фотореалистичный кадр по разметке и описанию',
              model='openai/gpt-image-2 (images/edits)', prompt=prompt,
              params={'номеров в разметке': len(legend), 'кадр': '1536×1024'},
              inputs=[src, marked] + ([plan_p] if plan is not None else []), outputs=[dst],
              note='Модель получает аппликацию, разметку с номерами и JSON: что каждый номер '
                   'значит и как предмет должен стоять. Двигать и добавлять запрещено.')
    print(dst)


if __name__ == '__main__':
    main()
