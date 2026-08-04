#!/usr/bin/env python3
"""Разметка кадра номерами (Set-of-Mark) + легенда для модели.

Приём опубликован Microsoft (arXiv 2310.11441): если нанести на картинку номера и контуры
областей, модель начинает понимать, ЧТО и ГДЕ на ней, а не догадываться. Нам это дешевле, чем
авторам статьи: маски у нас точные, из собственной геометрии, сегментация не нужна.

Легенда несёт то, что модель по картинке не выведет: название товара, реальные габариты и
ОТНОШЕНИЕ («плед лежит на диване»). Без этого она честно оставит плед висящим в воздухе.

  ~/venvs/scout/bin/python viz_marks.py 21 --cam C1
"""
import json
import os
import sys

sys.path.insert(0, '/home/pakar/igor/remlab/services/planner-solver')

import numpy as np  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

import scene_build  # noqa: E402
from scene_build import SCENE_DIR, load_scene  # noqa: E402
from viz_objects import product  # noqa: E402

FONT = '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'
SKIP_MARK = {'тв'}


def build(n: int, cam_name: str = 'C1') -> tuple[str, str, list[dict]]:
    prefix = os.path.join(SCENE_DIR, f'scene{n}-{cam_name}')
    src = f'{prefix}-pasted.jpg'
    img = Image.open(src).convert('RGB')
    W, H = img.size
    ids_img = Image.open(f'{prefix}-instances.png').convert('RGB').resize((W, H), Image.NEAREST)
    ids = np.asarray(ids_img)[..., 0] // 8
    meta = json.load(open(f'{prefix}-frame.json'))
    load_scene(n)                                   # заполняет scene_build.RELATIONS
    rel = dict(scene_build.RELATIONS)
    items = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                        'sets3.json')))[n - 1]['items']

    marked = img.copy()
    d = ImageDraw.Draw(marked, 'RGBA')
    f = ImageFont.truetype(FONT, 34)
    legend: list[dict] = []
    num = 0
    for sid, role in meta['ids'].items():
        if role in SKIP_MARK or role not in items:
            continue
        m = ids == int(sid)
        if m.sum() < 400:
            continue
        num += 1
        ys, xs = np.where(m)
        cx, cy = float(xs.mean()), float(ys.mean())
        d.ellipse([cx - 24, cy - 24, cx + 24, cy + 24], fill=(200, 30, 30, 235),
                  outline=(255, 255, 255, 255), width=3)
        d.text((cx, cy), str(num), fill=(255, 255, 255), font=f, anchor='mm')
        it = items[role]
        try:
            _, photo = product(n, role)
        except KeyError:
            photo = ''
        legend.append({
            'n': num, 'роль': role, 'товар': (it.get('name') or '')[:80],
            'габариты_см': [int(it.get('w') or 0), int(it.get('d') or 0), int(it.get('h') or 0)],
            'положение': rel.get(role, 'стоит на полу'),
            'фото': os.path.basename(photo),
        })
    dst = f'{prefix}-marked.jpg'
    marked.save(dst, quality=93)
    json.dump(legend, open(f'{prefix}-legend.json', 'w'), ensure_ascii=False, indent=1)
    return src, dst, legend


def legend_text(legend: list[dict]) -> str:
    """Легенда одной строкой на запрос — то, что уходит модели вместе с размеченной картинкой."""
    return '; '.join(
        f'{e["n"]} — {e["роль"]} ({e["товар"]}), {e["габариты_см"][0]}×{e["габариты_см"][1]}×'
        f'{e["габариты_см"][2]} см, {e["положение"]}' for e in legend)


def main() -> None:
    n = int(sys.argv[1])
    cam = sys.argv[sys.argv.index('--cam') + 1] if '--cam' in sys.argv else 'C1'
    src, dst, legend = build(n, cam)
    print(dst)
    for e in legend:
        print(f'  {e["n"]:>2} {e["роль"]:<12} {e["положение"]}')


if __name__ == '__main__':
    main()
