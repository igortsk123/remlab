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
from viz_objects import edit_gpt_raw

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
        })
    return json.dumps(out, ensure_ascii=False)


def main() -> None:
    n = int(sys.argv[1])
    cam = sys.argv[sys.argv.index('--cam') + 1] if '--cam' in sys.argv else 'C1'
    prefix = os.path.join(SCENE_DIR, f'scene{n}-{cam}')
    src, marked, legend = build(n, cam)
    clean = Image.open(src).convert('RGB').resize((1536, 1024))
    mark = Image.open(marked).convert('RGB').resize((1536, 1024))

    prompt = (
        f'{room_brief(n)}. '
        'The FIRST image is a collage: every piece of furniture is a real product photo placed at '
        'its exact position and true size. Turn it into one believable photograph of this room: '
        'add soft contact shadows under every item, unify lighting and white balance, soften the '
        'pasted outlines, make floor and wall junctions correct, keep vertical lines vertical. '
        'The SECOND image is the SAME frame with red numbered markers above each item and a thin '
        'leader line ending on the item — it is an annotation for you only. '
        'NEVER draw numbers, circles or lines in the output. '
        'Here is what every number is and how it must sit (JSON): ' + legend_json(legend) + '. '
        'Follow the placement field exactly: a throw drapes over the sofa, cushions rest on the '
        'seat, a vase and a lamp stand on the chest of drawers, a rug lies flat on the floor. '
        'STRICT: do not move, resize, rotate or replace any item; do not add furniture, decor, '
        'plants or artwork that is not in the list; keep the walls, floor, window and door as they '
        'are. Photorealistic interior photography, natural daylight, no people, no text.'
    )
    out = edit_gpt_raw([clean, mark], prompt, size='1536x1024')
    dst = f'{prefix}-final.jpg'
    out.save(dst, quality=94)
    steps.log(prefix, 'Делаем фотореалистичный кадр по разметке и описанию',
              model='openai/gpt-image-2 (images/edits)', prompt=prompt,
              params={'номеров в разметке': len(legend), 'кадр': '1536×1024'},
              inputs=[src, marked], outputs=[dst],
              note='Модель получает аппликацию, разметку с номерами и JSON: что каждый номер '
                   'значит и как предмет должен стоять. Двигать и добавлять запрещено.')
    print(dst)


if __name__ == '__main__':
    main()
