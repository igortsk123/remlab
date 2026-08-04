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


OBJECT_WORDS = ('plant', 'pot', 'cushion', 'pillow', 'throw', 'blanket', 'rug', 'vase',
                'poster', 'print', 'gallery', 'candle', 'furniture', 'sofa', 'lamp')


def style_brief(n: int) -> str:
    """Паспорт стиля — про ОТДЕЛКУ. Куски про объекты вырезаем: наполнением управляем мы,
    иначе стиль тянет модель добавить «пару растений в горшках» (владелец, 2026-08-04)."""
    s = json.load(open(os.path.join(HERE, 'sets3.json')))[n - 1]
    sp = json.load(open(os.path.join(HERE, 'styles.json')))['styles']
    text = sp.get(s.get('style', ''), {}).get('prompt', '')
    keep = [c.strip() for c in text.replace(';', ',').split(',')
            if c.strip() and not any(w in c.lower() for w in OBJECT_WORDS)]
    return ', '.join(keep)


def openings_brief(n: int, cam_name: str) -> str:
    """Фраза про проёмы собирается ДИНАМИЧЕСКИ по геометрии кадра.

    Варианты: ни одного проёма · только окно · только дверь · оба · каждый из них целиком или
    частью. Модель проёмы не придумывает — их состав считаем мы (правило владельца 2026-08-04).
    """
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

    def px(pt):
        rel = np.array(pt, float) - eye
        z = float(rel @ fwd)
        if z <= 1e-3:
            return None, None
        return (W / 2 + focal * float(rel @ right) / z,
                H / 2 - focal * float(rel @ up) / z + cam.shift_y * H)

    found = {'window': [], 'door': []}
    for op in room.openings:
        o0, o1 = op.offset_cm, op.offset_cm + op.width_cm
        ends = {'south': [(o0, 0), (o1, 0)], 'north': [(o0, room.depth_cm), (o1, room.depth_cm)],
                'west': [(0, o0), (0, o1)],
                'east': [(room.width_cm, o0), (room.width_cm, o1)]}[op.wall]
        pts = [px([x, 120, y]) for x, y in ends]
        inside = [q for q in pts if q[0] is not None and 0 <= q[0] < W]
        if not inside:
            continue
        whole = len(inside) == 2
        side = 'left-hand' if float(np.mean([q[0] for q in inside])) < W / 2 else 'right-hand'
        kind = 'window' if op.kind == 'window' else 'door'
        found[kind].append((side, whole, int(op.width_cm)))

    def phrase(kind: str, items: list) -> str:
        out = []
        for side, whole, w in items:
            state = ('fully visible' if whole else
                     'only PARTLY in frame — draw only the part that is inside the frame, '
                     'do not complete it')
            out.append(f'one {kind} on the {side} wall, {w} cm wide, {state}')
        return '; '.join(out)

    win, door = found['window'], found['door']
    if not win and not door:
        body = ('There is NO window and NO door in this frame — every wall in view is blank. '
                'Do not put an opening anywhere.')
    elif win and not door:
        body = (f'The only opening in this frame is {phrase("window", win)}. '
                'There is NO door in this frame.')
    elif door and not win:
        body = (f'The only opening in this frame is {phrase("door", door)}. '
                'There is NO window in this frame.')
    else:
        body = (f'Openings in this frame: {phrase("window", win)}; and {phrase("door", door)}. '
                'There are no other openings.')
    return (body + ' Do NOT invent, move, add or remove any window or door: their places come '
            'from the plan, not from you.')


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
            'orientation': e.get('ориентация', ''),
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
    # Пишем в ОТДЕЛЬНЫЙ файл: коллаж `-pasted.jpg` — исходник, его перезаписывать нельзя,
    # иначе в контроль и на лист уезжает уже сгенерированная картинка (владелец, 2026-08-04).
    out.resize(view.size).save(f'{prefix}-ready.jpg', quality=93)
    steps.log(prefix, 'Дорисовываем предметы, повёрнутые к камере боком',
              model='fal-ai/nano-banana/edit', prompt=pr,
              params={'предметы': angled, 'фото-референсов': len(refs)},
              inputs=[f'{prefix}-pasted.jpg'], outputs=[f'{prefix}-ready.jpg'],
              note='Фронтальное фото на боковой ракурс не натянуть — эти предметы рисует модель '
                   'по их же фотографиям.')


BAND_RGB = (255, 0, 255)          # маркерная полоса между кадрами: чистый маджента, такого
BAND_PX = 94                      # цвета в интерьере не бывает, поэтому шов легко найти


def stack_pair(paths: list[str], size=(2048, 2864), margin=20) -> 'Image.Image':
    """Два кадра на одном листе, между ними ЯРКАЯ ПОЛОСА-разделитель.

    Полосу модель обязана вернуть в ответе — по ней мы режем результат на два снимка
    (правило владельца 2026-08-04). Пропорции кадров 3:2 сохраняются.
    """
    W, H = size
    fh = (H - 2 * margin - BAND_PX) // 2
    canvas = Image.new('RGB', size, (250, 250, 248))
    for i, p in enumerate(paths[:2]):
        im = Image.open(p).convert('RGB').resize((W, int(W * Image.open(p).height /
                                                        Image.open(p).width)))
        if im.height > fh:
            top = (im.height - fh) // 2
            im = im.crop((0, top, W, top + fh))
        y = margin if i == 0 else margin + fh + BAND_PX
        canvas.paste(im, (0, y + (fh - im.height) // 2))
    band = Image.new('RGB', (W, BAND_PX), BAND_RGB)
    canvas.paste(band, (0, margin + fh))
    return canvas


def split_pair(sheet: 'Image.Image') -> list:
    """Режем ответ модели по маркерной полосе. Если её нет — делим пополам."""
    import numpy as np
    a = np.asarray(sheet.convert('RGB')).astype(int)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    mask = (r > 170) & (b > 170) & (g < 110)          # строки маджента-полосы
    rows = np.where(mask.mean(axis=1) > 0.5)[0]
    if len(rows) < 8:
        half = sheet.height // 2
        return [sheet.crop((0, 0, sheet.width, half)),
                sheet.crop((0, half, sheet.width, sheet.height))]
    y0, y1 = int(rows.min()), int(rows.max())
    return [sheet.crop((0, 0, sheet.width, y0)),
            sheet.crop((0, y1 + 1, sheet.width, sheet.height))]


def pair_prompt(n: int, cams: tuple[str, str], legends: list[list[dict]]) -> str:
    """Единый запрос на два вида: ОДИН список предметов со сквозными номерами.

    Номера одинаковы в обоих кадрах, поэтому список не дублируется — короче и однозначнее
    (владелец, 2026-08-04). У каждой позиции сказано, как она видна в каждом кадре.
    """
    a, b = cams
    merged: dict[int, dict] = {}
    for idx, legend in enumerate(legends):
        for e in legend:
            item = merged.setdefault(e['n'], {
                'id': e['n'], 'product': e['товар'], 'type': e['роль'],
                'size_cm': e['габариты_см'], 'details': e.get('описание', ''),
                'placement': e['положение'], 'orientation': e.get('ориентация', ''),
                'in_top': 'not in this frame', 'in_bottom': 'not in this frame',
            })
            item['in_top' if idx == 0 else 'in_bottom'] = e['видимость']
    items = json.dumps([merged[k] for k in sorted(merged)], ensure_ascii=False)
    return (
        f'{room_brief(n)}\n\n'
        'IMAGES: 1 — a sheet with TWO collages of the SAME room, one above the other: TOP is view '
        f'{a}, BOTTOM is view {b}, separated by a bright magenta band. Each collage puts real '
        'product photos at their places on a neutral render; it shows POSITION and APPROXIMATE '
        'scale, true dimensions are in the list. 2 — the same sheet with red numbered markers '
        '(annotation only; the same number always means the same item in both frames). 3 — the '
        'floor plan with both camera positions and their fields of view.\n\n'
        'Render BOTH views as one sheet in the SAME layout: two photographs of the same room, '
        'identical finishes, identical light, identical products — only the camera differs. Keep '
        'the magenta band exactly where it is, same colour and height, nothing drawn on it.\n\n'
        'DO NOT CHANGE: the products (never replace, recolour or resize); their places; the room '
        'shell (walls, floor, ceiling, cameras).\n'
        f'TOP VIEW openings. {openings_brief(n, a)}\n'
        f'BOTTOM VIEW openings. {openings_brief(n, b)}\n\n'
        'DO: turn each item slightly around its vertical axis to match its "orientation" and '
        '"placement" fields — product photos are shot from their own viewpoint, so this rotation '
        'makes the scene believable. Renovate the room in the style below: walls, floor, ceiling, '
        'skirting, frames and dressing of the given openings. Soft contact shadows, natural light, '
        'correct wall-floor junctions, verticals vertical. You may add wall art and small decor '
        'typical of the style. Fill every planter and vase from the list with a live plant sized '
        'to it. Where the list has a TV stand, a TV is ALWAYS present: put it either standing on '
        'the stand or wall-mounted right above it — choose by the size and design of that stand.\n\n'
        'NEVER ADD: furniture, rugs, lamps, TV, textiles, pots, planters or floor plants that are '
        'not in the list. Do not duplicate items to make the room look fuller.\n\n'
        f'STYLE (finishes, colour, light and mood only — it never adds objects) — {style_name(n)}: '
        f'{style_brief(n)}\n\n'
        'ITEMS (JSON, one list for both frames; "id" = the number on image 2). "in_top" and '
        '"in_bottom" say how the item is seen in each frame: whole, only a part (never complete '
        'it), or not in that frame at all.\n' + items + '\n\n'
        'OUTPUT: one sheet with the two photorealistic photographs in the same places as the input '
        'collages and the magenta band between them; no people, no text, no markers.'
    )


def run_pair(n: int, cams: tuple[str, str]) -> None:
    """Оба вида одним запросом: единый стиль по построению."""
    prefixes = [os.path.join(SCENE_DIR, f'scene{n}-{c}') for c in cams]
    from viz_marks import numbering
    nums = numbering(n, cams)
    srcs, marks, legends = [], [], []
    for c, pref in zip(cams, prefixes):
        src, marked, legend = build(n, c, nums)
        srcs.append(src)
        marks.append(marked)
        legends.append(legend)
    sheet = stack_pair(srcs)
    sheet_marks = stack_pair(marks)
    out_dir = os.path.join(SCENE_DIR, f'scene{n}-pair')
    sheet.save(f'{out_dir}-collage.jpg', quality=93)
    sheet_marks.save(f'{out_dir}-marked.jpg', quality=93)
    prompt = pair_prompt(n, cams, legends)
    if '--print-prompt' in sys.argv:
        print(prompt)
        return
    plan_p = os.path.join(SCENE_DIR, f'scene{n}-plan.png')
    imgs = [sheet, sheet_marks] + ([Image.open(plan_p).convert('RGB')] if os.path.exists(plan_p) else [])
    out = edit_gpt_raw(imgs, prompt, size='2048x2864')
    out.save(f'{out_dir}-final.jpg', quality=94)
    # Режем ответ по маркерной полосе, а не по фиксированным отступам: модель может немного
    # сместить кадры, а полосу видно всегда (владелец, 2026-08-04).
    for c, part in zip(cams, split_pair(out)):
        dst = os.path.join(SCENE_DIR, f'scene{n}-{c}-final.jpg')
        part.save(dst, quality=94)
        print(dst, part.size)

    steps.log(prefixes[0], 'Оба вида одним запросом',
              model='openai/gpt-image-2 (images/edits)', prompt=prompt,
              params={'виды': list(cams), 'лист': '2048×2864', 'кадр': '2048×1365',
                      'разделитель': 'маджента, 94 px'},
              inputs=[f'{out_dir}-collage.jpg', f'{out_dir}-marked.jpg'],
              outputs=[f'{out_dir}-final.jpg'],
              note='Один холст на два вида: стиль и свет совпадают по построению.')
    print(f'{out_dir}-final.jpg')


def main() -> None:
    n = int(sys.argv[1])
    if '--pair' in sys.argv:
        pair = sys.argv[sys.argv.index('--pair') + 1].split(',')
        run_pair(n, (pair[0], pair[1]))
        return
    cam = sys.argv[sys.argv.index('--cam') + 1] if '--cam' in sys.argv else 'C1'
    prefix = os.path.join(SCENE_DIR, f'scene{n}-{cam}')
    # ВАЖНО: печать промпта не должна запускать генерацию — иначе `--print-prompt` тихо
    # тратит деньги и подменяет коллаж результатом (поймано 2026-08-04).
    if '--no-angled' not in sys.argv and '--print-prompt' not in sys.argv:
        redraw_angled(n, prefix)
    src, marked, legend = build(n, cam)
    ready = f'{prefix}-ready.jpg'
    clean = Image.open(ready if os.path.exists(ready) else src).convert('RGB').resize((2048, 1360))
    mark = Image.open(marked).convert('RGB').resize((2048, 1360))
    plan_p = os.path.join(SCENE_DIR, f'scene{n}-plan.png')
    plan = Image.open(plan_p).convert('RGB') if os.path.exists(plan_p) else None

    openings = openings_brief(n, cam)
    prompt = (
        f'{room_brief(n)}\n\n'
        'IMAGES: 1 — collage, each piece of furniture is a real product photo put at its place on '
        'a neutral render of the room; the collage shows POSITION and APPROXIMATE scale, the true '
        'dimensions are in the list below. 2 — the same frame with red numbered markers (annotation '
        'only). 3 — the floor plan with the camera position and its field of view.\n\n'
        'DO NOT CHANGE: the products themselves (never replace, recolour or resize — this is what '
        'the customer buys); their places; the room shell (walls, floor, ceiling, camera). '
        f'{openings}\n\n'
        'DO: turn each item slightly around its vertical axis to match its "orientation" and '
        '"placement" fields — product photos are shot from their own viewpoint, so this rotation '
        'is what makes the scene believable. Renovate the room in the style below: walls, floor, '
        'ceiling, skirting, and the frames and dressing of the given openings. Add soft contact '
        'shadows, natural light, correct wall-floor junctions, keep verticals vertical. You may add '
        'wall art and small decor typical of the style. Fill every planter and vase from the list '
        'with a live plant sized to it. Where the list has a TV stand, a TV is ALWAYS present: put it either standing on the stand or wall-mounted right above it — choose by the size and design of that stand.\n\n'
        'NEVER ADD: furniture, rugs, lamps, TV, textiles, pots, planters or floor plants that are '
        'not in the list. Do not duplicate items to make the room look fuller — a small room stays '
        'sparse if the list is short.\n\n'
        f'STYLE (finishes, colour, light and mood only — it never adds objects) — {style_name(n)}: '
        f'{style_brief(n)}\n\n'
        'ITEMS (JSON, id = number on image 2). "visibility" says whether the item is whole or cut '
        'by the frame edge — never complete a cut-off item.\n' + legend_json(legend) + '\n\n'
        'OUTPUT: one photorealistic interior photograph, no people, no text, no markers.'
    )

    if '--print-prompt' in sys.argv:        # показать запрос без генерации
        print(prompt)
        return
    imgs = [clean, mark] + ([plan] if plan is not None else [])
    out = edit_gpt_raw(imgs, prompt, size='2048x1360')
    dst = f'{prefix}-final.jpg'
    out.save(dst, quality=94)
    steps.log(prefix, 'Делаем фотореалистичный кадр по разметке и описанию',
              model='openai/gpt-image-2 (images/edits)', prompt=prompt,
              params={'номеров в разметке': len(legend), 'кадр': '2048×1360'},
              inputs=[src, marked] + ([plan_p] if plan is not None else []), outputs=[dst],
              note='Модель получает аппликацию, разметку с номерами и JSON: что каждый номер '
                   'значит и как предмет должен стоять. Двигать и добавлять запрещено.')
    print(dst)


if __name__ == '__main__':
    main()
