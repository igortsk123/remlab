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

    objs = ids > 0
    marked = img.copy()
    d = ImageDraw.Draw(marked, 'RGBA')
    legend: list[dict] = []
    placed: list[tuple[float, float, int]] = []
    num = 0
    for sid, role in meta['ids'].items():
        if role in SKIP_MARK or role not in items:
            continue
        m = ids == int(sid)
        if m.sum() < 400:
            continue
        # Доля видимости: если предмет обрезан краем кадра или закрыт другим, модель должна об
        # этом ЗНАТЬ — иначе она пытается дорисовать целый предмет из фрагмента (владелец,
        # 2026-08-04). Совсем мелкие фрагменты в легенду не попадают вовсе.
        ys_a, xs_a = np.where(m)
        touches_edge = (xs_a.min() <= 1 or xs_a.max() >= W - 2
                        or ys_a.min() <= 1 or ys_a.max() >= H - 2)
        share = float(m.sum()) / max(1.0, (xs_a.max() - xs_a.min() + 1) * (ys_a.max() - ys_a.min() + 1))
        frag = m.sum() / (W * H)
        if frag < 0.004:
            continue
        seen_txt = ('виден целиком' if not touches_edge else
                    'виден частично: обрезан краем кадра, рисовать только видимую часть')
        num += 1
        ys, xs = np.where(m)
        cx = float(xs.mean())
        top = float(ys.min())
        # Номер ставим НАД предметом, а не по центру: на мелких (лампа, ваза) кружок закрывал
        # сам товар, и модель не видела, о чём речь (замечание владельца 2026-08-04).
        r = int(min(26, max(13, (xs.max() - xs.min()) / 6)))
        def ok_at(px, py):
            """Место годится, если номер не закрывает товар, не липнет к другому номеру и
            стоит от него ОТДЕЛЬНО ПО ГОРИЗОНТАЛИ — иначе два номера читаются как один
            (владелец: «4 и 10 сливаются»)."""
            if py - r < 2 or px - r < 2 or px + r > W - 2:
                return False
            box = objs[max(0, int(py - r)):int(py + r), max(0, int(px - r)):int(px + r)]
            if box.size and box.mean() > 0.02:
                return False
            for ux, uy, ur in placed:
                if abs(px - ux) < r + ur + 12 and abs(py - uy) < (r + ur) * 3.2:
                    return False                       # столбиком друг под другом — запрещено
                if (px - ux) ** 2 + (py - uy) ** 2 < (r + ur + 8) ** 2:
                    return False
            return True

        mx, my = cx, top - r - 10
        if not ok_at(mx, my):
            found = False
            for k in range(1, 9):                      # сначала вбок, потом чуть выше
                for dx in (-1, 1):
                    for dy in (0, -1.4, -2.8):
                        px = cx + dx * k * (r * 1.9)
                        py = top - r - 10 + dy * r
                        if ok_at(px, py):
                            mx, my, found = px, py, True
                            break
                    if found:
                        break
                if found:
                    break
        my = max(r + 4, my)
        mx = min(max(r + 4, mx), W - r - 4)
        placed.append((mx, my, r))
        # Выноска ведёт В САМ ПРЕДМЕТ, а не к его верхней кромке: иначе у соседних объектов
        # (подушки, ваза с комодом) непонятно, к кому относится номер (владелец, 2026-08-04).
        cy_m, cx_m = float(ys.mean()), float(xs.mean())
        near = np.argmin((ys - cy_m) ** 2 + (xs - cx_m) ** 2)   # точка внутри маски
        ax, ay = float(xs[near]), float(ys[near])
        d.line([mx, my + r, ax, ay], fill=(200, 30, 30, 210), width=2)
        d.ellipse([ax - 6, ay - 6, ax + 6, ay + 6], fill=(200, 30, 30, 235),
                  outline=(255, 255, 255, 220), width=2)
        d.ellipse([mx - r, my - r, mx + r, my + r], fill=(200, 30, 30, 235),
                  outline=(255, 255, 255, 255), width=3)
        fnt = ImageFont.truetype(FONT, int(r * 1.35))
        d.text((mx, my), str(num), fill=(255, 255, 255), font=fnt, anchor='mm')
        it = items[role]
        try:
            _, photo = product(n, role)
        except KeyError:
            photo = ''
        details = ', '.join(x for x in (
            it.get('cls'), it.get('fabric') and f'обивка: {it["fabric"]}',
            it.get('wood') and f'дерево: {it["wood"]}',
            it.get('metal') and f'металл: {it["metal"]}',
            it.get('style') and f'стиль: {it["style"]}') if x)
        legend.append({
            'n': num, 'роль': role, 'товар': (it.get('name') or '')[:80],
            'описание': details[:160],
            'габариты_см': [int(it.get('w') or 0), int(it.get('d') or 0), int(it.get('h') or 0)],
            'положение': rel.get(role, 'стоит на полу'),
            'видимость': seen_txt,
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
