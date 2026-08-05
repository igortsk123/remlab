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


def corner_brief(n: int, cam_name: str) -> str:
    """Где в кадре вертикальный угол комнаты — числом.

    Словесного «не трогай стены» мало: во втором кадре угол уезжал на пятую часть ширины.
    Число проверяемо и его видно на картинке (владелец, 2026-08-05).
    """
    import math

    import numpy as np
    sys.path.insert(0, '/home/pakar/igor/remlab/services/planner-solver')
    from planner.scene import cameras_for
    from scene_build import load_scene
    room, placements = load_scene(n)
    cam = next(c for c in cameras_for(room, placements) if c.name == cam_name)
    eye, fwd, right, up = cam.basis()
    W = cam.width
    focal = (W / 2) / math.tan(math.radians(cam.fov_deg) / 2)
    out = []
    for x, y in ((0, 0), (room.width_cm, 0), (room.width_cm, room.depth_cm), (0, room.depth_cm)):
        rel = np.array([x, 150.0, y], float) - eye
        z = float(rel @ fwd)
        if z <= 1e-3:
            continue
        u = W / 2 + focal * float(rel @ right) / z
        if 0 < u < W:
            out.append(round(u / W * 100))
    if not out:
        return 'no wall corner is visible in this frame'
    return ('the vertical corner where two walls meet is at '
            + ' and '.join(f'{v}% of the frame width' for v in out)
            + ' — keep it exactly there')


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
    return body


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


def shops_note(n: int) -> str:
    """Заметка про ракурс карточек — только для поставщиков, у кого он ЗАМЕРЕН.

    Замер: `measure_angle.py` (nonton.ru — медиана 20°, «три четверти»). Для остальных магазинов
    ничего не пишем: выдумывать ракурс нельзя (владелец, 2026-08-04).
    """
    path = os.path.join(HERE, 'photo_angles.json')
    if not os.path.exists(path):
        return ''
    table = json.load(open(path))
    items = json.load(open(os.path.join(HERE, 'sets3.json')))[n - 1]['items']
    shops = sorted({it.get('shop') for it in items.values() if it.get('shop') in table})
    if not shops:
        return ''
    return ('- Product photos from ' + ', '.join(shops) + ' are 3/4 shots, not frontal: in the '
            'collage such items look turned towards the viewer — correct that rotation.\n')


def pair_prompt(n: int, cams: tuple[str, str], legends: list[list[dict]],
                has_identity: bool = False) -> str:
    """Единый запрос на два вида: коротко, с акцентами и одним списком предметов."""
    a, b = cams
    merged: dict[int, dict] = {}
    for idx, legend in enumerate(legends):
        for e in legend:
            item = merged.setdefault(e['n'], {
                'id': e['n'], 'product': e['товар'], 'type': e['роль'],
                'size_cm': e['габариты_см'], 'appearance': e.get('внешний_вид', {}),
                'placement': e['положение'], 'orientation': e.get('ориентация', ''),
                'in_top': 'absent', 'in_bottom': 'absent',
            })
            code = ('whole' if e['видимость'].startswith('виден целиком') else 'part')
            item['in_top' if idx == 0 else 'in_bottom'] = code
    from viz_paste import FLOOR, KEY_FLOOR, SOFT
    sys.path.insert(0, '/home/pakar/igor/remlab/services/planner-solver')
    from scene_build import load_scene as _ls
    _room, _pl = _ls(n)
    _by = {q.role: q for q in _pl}
    fp_ids = [k for k in sorted(merged)
              if merged[k]['type'] in KEY_FLOOR and merged[k]['type'] not in FLOOR
              and merged[k]['type'] not in SOFT
              and float(getattr(_by.get(merged[k]['type']), 'elev_cm', 0) or 0) <= 1.0]
    on_top = {k: merged[k]['placement'] for k in sorted(merged)
              if float(getattr(_by.get(merged[k]['type']), 'elev_cm', 0) or 0) > 1.0}
    meshed_ids = []
    for c in cams:
        pp = os.path.join(SCENE_DIR, f'scene{n}-{c}-paint.json')
        if os.path.exists(pp):
            for role in json.load(open(pp)).get('meshed', []):
                ids = [k for k in merged if merged[k]['type'] == role]
                meshed_ids += ids
    meshed_ids = sorted(set(meshed_ids))
    not_shown = set()
    for c in cams:
        pp = os.path.join(SCENE_DIR, f'scene{n}-{c}-paint.json')
        if os.path.exists(pp):
            not_shown |= set(json.load(open(pp)).get('volumes') or [])
    # Свойства предмета живут В САМОМ ПРЕДМЕТЕ, а не в абзацах со списками номеров: иначе при
    # другом наборе мебели промпт приходится переписывать руками (разбор промпта, 2026-08-05).
    for k, m in merged.items():
        role = m['type']
        m['appearance_source'] = ('reconstructed_3d' if k in meshed_ids else
                                  'not_shown' if role in not_shown else 'product_photo')
        m['has_footprint'] = k in fp_ids
        m['support'] = ('parent' if k in on_top else
                        'ceiling' if role in ('люстра',) else 'floor')
    items = json.dumps([merged[k] for k in sorted(merged)], ensure_ascii=False)
    fp_list = ', '.join(f'#{k}' for k in fp_ids) or 'none'
    top_list = ', '.join(f'#{k}' for k in on_top) or 'none'
    return (
        'TASK. You are an interior designer and photographer. The furniture is already bought by '
        'the customer and cannot be changed. Design the room AROUND these exact products — '
        'finishes, light, colour — and deliver two photographs on one sheet: TOP is view '
        f'{a}, BOTTOM is view {b}, with the magenta band between them kept exactly as in the input '
        '(same position, height and colour, nothing drawn on it).\n'
        'THE ROOM ITSELF IS FIXED. Treat image 1 as a locked composition and perspective guide: the wall '
        'planes and the vertical corner where two walls meet stay at the same place and angle, the '
        'ceiling line and the floor line stay at the same height, the room keeps its proportions '
        'and the camera does not move. You repaint and light the room, you do not rebuild it.\n\n'
        'INPUT IMAGES. 1 — the collages: real product photos placed at their spots on a neutral '
        'render; on the floor thin dark rectangles mark the true base of the main furniture. '
        '2 — the same sheet with red numbers (annotation only, the same number is the same item in '
        'both frames). 3 — the floor plan with both camera positions and their fields of view.'
        + (' 4 — reference photos of the items whose look cannot be read from the collage (they are '
           'cut by the frame, or shown only as a grey volume), each labelled with its number: take '
           'their appearance from image 4, but their size, place and rotation only from the floor '
           'rectangle in image 1. Image 4 holds the original shop photos: some sit on a branded '
           'background and carry a shop logo or watermark — read the product itself and ignore '
           'that background, the logo and any lettering; never copy them into the room.'
           if has_identity else '') + '\n\n'
        'READ THE ITEM LIST BEFORE YOU DRAW ANYTHING. "product" is the exact retail name; '
        '"appearance" carries the measured material, official colour and colour_hex; "size_cm" is '
        '[width, depth, height] in centimetres, measured. An upholstered fabric stays fabric and '
        'never becomes leather, oak stays oak. Scale every item to its own size_cm relative to the '
        'room and to the other items — a 44 cm pouf must read as knee-high next to an 88 cm sofa. '
        'Mismatched material, colour or scale is a defect.'
        + '\n\n'
        'GEOMETRY PRIORITY (highest first): floor rectangle in image 1 → floor plan in image 3 → '
        'size_cm in the item list → the pasted photo. If they disagree, the higher source wins.\n'
        'APPEARANCE — one source per attribute, never a blend: shape and construction from the '
        'pasted product photo (or from image 4 when "appearance_source" is not "product_photo"); '
        'material from "appearance.material"; official colour from "appearance.colour_name"; '
        'tone calibration from "appearance.colour_hex"; texture and small details from the photo. '
        'An item whose "appearance_source" is "reconstructed_3d" is shown in image 1 as a computed '
        'render: its position, size and rotation are exact, its surface is not — never copy that '
        'surface. An item whose "appearance_source" is "not_shown" is missing from image 1 '
        'altogether: draw it from image 4 and its own data, on its floor rectangle.\n\n'
        'GREY VOLUMES. An item shown as a plain grey block in image 1 is a placeholder: its size, '
        'place and rotation are right, its look is not — draw the real product using image 4 and '
        'the item list.\n\n'
        f'FOOTPRINTS. Items {fp_list} have a floor rectangle: each item must fill its own rectangle '
        'exactly — same width, same length, same rotation, same position. Items ' + top_list +
        ' stand on other furniture and inherit its position. Never draw the rectangles.\n\n'
        'IMMUTABLE. Products: no replacing, recolouring, restyling, resizing, moving or '
        'duplicating. Room shell: walls, floor, ceiling and cameras stay as they are. Openings: '
        'exactly as listed below — never invent, move, add or remove a window or a door.\n'
        f'  TOP frame: {openings_brief(n, a)} In this frame {corner_brief(n, a)}.\n'
        f'  BOTTOM frame: {openings_brief(n, b)} In this frame {corner_brief(n, b)}.\n\n'
        'ALLOWED EDITS. Rotate an item around its vertical axis to match its rectangle and its '
        '"orientation" field. Renovate in the style below: wall finish and colour, flooring, '
        'ceiling, skirting, frames and dressing of the given openings. Natural light, soft contact '
        'shadows, correct wall-to-floor junctions, vertical lines vertical. Framed wall art may be '
        'added; no tabletop, shelf, floor or freestanding decor of your own. Every planter and vase '
        'from the list must hold a live plant sized to it. Where the list has a TV stand, a TV is '
        'always present — on the stand or wall-mounted right above it.\n'
        + shops_note(n) + '\n'
        f'STYLE — {style_name(n)} (finishes, colour, light and mood only; it never adds objects): '
        f'{style_brief(n)}\n\n'
        'ITEMS (JSON, one list for both frames; id = number on image 2; "in_top"/"in_bottom": '
        'whole = draw fully, part = draw only the visible part and never complete it, absent = not '
        'in that frame):\n' + items + '\n\n'
        'INVALID OUTPUT — redo if any of this happens: an item is bigger than its floor rectangle '
        'or shifted off it; an item is replaced, recoloured or resized; an object that is not in '
        'the list appears; an item shows up in the wrong frame; a window or door appears where the '
        'list says there is none; the magenta band is missing, moved or painted over; numbers, '
        'rectangles or any markup are drawn in the photograph.'
    )


def hires(img: 'Image.Image', cache: str = '', min_side: int = 900) -> 'Image.Image':
    """Эталон в нормальном разрешении: фиды дают максимум 450 px (проверено — у CDN Гдеслона
    других вариантов нет), а по мыльной картинке модель не видит ни фактуру ткани, ни текстуру
    дерева. Апскейлим ×2 нейросетью и кэшируем рядом с фото: разово на товар."""
    if min(img.size) >= min_side:
        return img
    if cache and os.path.exists(cache):
        return Image.open(cache)
    from viz_base import fal_key, upscale
    try:
        big = upscale(img, fal_key())
        if cache:
            big.save(cache, quality=95)
        return big
    except Exception as e:  # noqa: BLE001 — не вышло: отдаём как есть
        print(f'  апскейл эталона не вышел ({str(e)[:50]})')
        return img


def identity_sheet(n: int, legends: list[list[dict]], nums: dict) -> 'Image.Image | None':
    """Лист эталонов: ОРИГИНАЛЬНЫЕ фото товаров из фида, в максимальном разрешении.

    Модель не может понять по обрезку, что это за предмет; эталон даёт внешний вид, но НЕ место
    (рекомендация из разбора, 2026-08-05).
    """
    from PIL import ImageDraw, ImageFont
    from viz_objects import product
    from viz_paste import cutout, trim_alpha
    partial = {}
    for legend in legends:
        for e in legend:
            if not e['видимость'].startswith('виден целиком'):
                partial.setdefault(e['n'], e['роль'])
    # и те, кого мы принципиально не вклеиваем фотографией (низкая мебель, мягкий декор):
    # их внешний вид модель узнаёт только из эталона
    for c in ('C1', 'C2'):
        ap = os.path.join(SCENE_DIR, f'scene{n}-{c}-angled.json')
        if os.path.exists(ap):
            for role in json.load(open(ap)):
                num = nums.get(role)
                if num:
                    partial.setdefault(num, role)
        # Предмет, показанный 3D-рендером, ОБЯЗАН попасть в эталоны: текстура модели
        # восстановлена по одному фото и всегда беднее оригинала — пуф вышел кожаным вместо
        # тканевого (владелец, 2026-08-05). Геометрия с коллажа, материал — отсюда.
        pp = os.path.join(SCENE_DIR, f'scene{n}-{c}-paint.json')
        if os.path.exists(pp):
            for role in json.load(open(pp)).get('meshed', []):
                num = nums.get(role)
                if num:
                    partial.setdefault(num, role)
    cells = []
    for num, role in sorted(partial.items()):
        try:
            _, photo = product(n, role)
        except KeyError:
            continue
        # Эталон — ОРИГИНАЛЬНОЕ фото магазина из поля `original_picture` фида (1080 px против
        # 450 у витринного), а не наша вырезка: вырезка теряет края, тени и часть фактуры
        # (владелец, 2026-08-05). Нет оригинала — берём витринное и апскейлим ×2.
        from viz_objects import orig_photo, product as _prod
        big = orig_photo(_prod(n, role)[0])
        if big and os.path.exists(big):
            cells.append((num, role, Image.open(big).convert('RGB')))
        elif os.path.exists(photo):
            cells.append((num, role,
                          hires(Image.open(photo).convert('RGB'),
                                os.path.splitext(photo)[0] + '-up.jpg')))
    if not cells:
        return None
    cols = min(3, len(cells))
    rows = (len(cells) + cols - 1) // cols
    cw, ch = 640, 620
    sheet = Image.new('RGB', (cols * cw, rows * ch), (255, 255, 255))
    d = ImageDraw.Draw(sheet)
    f = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 40)
    for i, (num, role, im) in enumerate(cells):
        im = im.copy()
        im.thumbnail((cw - 40, ch - 110))
        x, y = (i % cols) * cw, (i // cols) * ch
        sheet.paste(im, (x + (cw - im.width) // 2, y + 30))
        d.text((x + 24, y + ch - 70), f'#{num} {role}', fill=(200, 30, 30), font=f)
    return sheet


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
    prompt = pair_prompt(n, cams, legends, has_identity=identity_sheet(n, legends, nums) is not None)
    if '--print-prompt' in sys.argv:
        print(prompt)
        return
    plan_p = os.path.join(SCENE_DIR, f'scene{n}-plan.png')
    ident = identity_sheet(n, legends, nums)
    imgs = [sheet, sheet_marks] + ([Image.open(plan_p).convert('RGB')] if os.path.exists(plan_p) else [])
    if ident is not None:
        ident.save(f'{out_dir}-identity.jpg', quality=92)
        imgs.append(ident)
    out = edit_gpt_raw(imgs, prompt, size='2048x2864')
    out.save(f'{out_dir}-final.jpg', quality=94)
    from viz_objects import LAST_USAGE
    usage = dict(LAST_USAGE)
    # цены OpenAI за миллион токенов (gpt-image): текст на входе, картинки на входе, картинки на выходе
    rate = {'text_in': 5.0, 'image_in': 10.0, 'image_out': 40.0}
    det = usage.get('input_tokens_details', {}) or {}
    cost = (det.get('text_tokens', 0) * rate['text_in']
            + det.get('image_tokens', 0) * rate['image_in']
            + usage.get('output_tokens', 0) * rate['image_out']) / 1e6
    json.dump({'usage': usage, 'cost_usd': round(cost, 4), 'prompt_chars': len(prompt)},
              open(f'{out_dir}-cost.json', 'w'), ensure_ascii=False, indent=1)
    open(f'{out_dir}-prompt.txt', 'w').write(prompt)
    print(f'расход: {usage} → ≈ ${cost:.3f}')
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
        'ALLOWED GENERATED ELEMENTS (nothing else may be invented): a live plant inside a listed '
        'planter or vase; a TV on or above a listed TV stand; curtains or blinds on a listed '
        'window; a radiator under a listed window; restrained framed wall art; light, shadows and '
        'reflections. These must not cover or outshine the purchased products.\n\n'
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
