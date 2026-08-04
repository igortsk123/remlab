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
    style = ''
    if s.get('style'):
        sp = json.load(open(os.path.join(HERE, 'styles.json')))['styles']
        style = sp.get(s['style'], {}).get('prompt', '') or s['style']
    return (f'A living room in a Russian city flat, {s.get("band", "18-20")} m², '
            f'4.00 × 4.60 m, ceiling 2.7 m, one window on the right-hand wall, one door. '
            f'Interior style: {style}')


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

    prompt = (
        f'{room_brief(n)}. '
        'The FIRST image is a collage: every piece of furniture is a real product photo placed at '
        'its exact position and true size. Turn it into one believable photograph of this room: '
        'add soft contact shadows under every item, unify lighting and white balance, soften the '
        'pasted outlines, make floor and wall junctions correct, keep vertical lines vertical. '
        'The SECOND image is the SAME frame with red numbered markers above each item and a thin '
        'leader line ending on the item — it is an annotation for you only. '
        'The THIRD image is the floor plan of this room with the camera position (red dot) and its '
        'field of view: use it to understand where each item stands, which items are close to the '
        'camera and which parts of them the frame cuts off. '
        'NEVER draw numbers, circles or lines in the output. '
        'Here is what every number is and how it must sit (JSON): ' + legend_json(legend) + '. '
        'The visibility field says whether an item is whole or cut by the frame edge: never '
        'complete a cut-off item — draw exactly the part that is in the frame. '
        'Follow the placement field exactly: a throw drapes over the sofa, cushions rest on the '
        'seat, a vase and a lamp stand on the chest of drawers, a rug lies flat on the floor. '
        'You MAY turn an item slightly around its own vertical axis so that it sits logically '
        'in the room (an ottoman faces the sofa, a coffee table is parallel to the sofa) — the '
        'product photos are frontal, so a small rotation makes the scene believable. '
        'STRICT: do not move an item to another place, do not resize or replace it; do not add '
        'furniture, decor, '
        'plants or artwork that is not in the list; keep the walls, floor, window and door as they '
        'are. Photorealistic interior photography, natural daylight, no people, no text.'
    )
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
