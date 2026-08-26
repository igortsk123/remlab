#!/usr/bin/env python3
"""ЧЕРНОВОЙ РЕНДЕР КОМНАТЫ ≤10 с (владелец 26.08).

Идея: всё, что модель не должна выдумывать, отдаём ей готовым.
  • ГЕОМЕТРИЯ — карта глубины нашей сцены (стены, проёмы, габариты предметов на своих местах).
  • ТОВАРЫ — коллаж: фотография КАЖДОГО товара вклеена в маску именно его предмета, поэтому
    модель видит не «диван вообще», а наш диван, и не гадает, что где стоит.
Дальше один вызов image-to-image по этому коллажу: модель доводит свет, тени и материалы.

Почему коллаж по маскам, а не проекция граней (`viz_paste.py`): тот путь считает ракурс каждого
предмета и при косой камере отказывается вклеивать (проверено 26.08 — из 12 предметов вклеился
один). Для ЧЕРНОВИКА точность граней не нужна, нужна узнаваемость и скорость.

  ~/venvs/scout/bin/python draft_render.py 10                 # черновик по банку сета
  ~/venvs/scout/bin/python draft_render.py --layout f.json    # по произвольной расстановке
  ~/venvs/scout/bin/python draft_render.py --warm             # прогрев модели (холодный старт 76 с)
"""
import io
import json
import os
import sys
import time
import urllib.request

import numpy as np
from PIL import Image, ImageFilter

sys.path.insert(0, '/home/pakar/igor/remlab/services/planner-solver')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from planner.scene import cameras_for, clay_render, compile_scene  # noqa: E402

from falmini import fal_key, fal_run, uri_from_image  # noqa: E402  (лёгкий клиент fal)

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.environ.get('SCENE_DIR', os.path.expanduser('~/scout-scenes'))
CACHE = os.path.join(OUT, 'draft-photos')
# ВЫБОР МОДЕЛИ (26.08, замерено на нашем ключе): sdxl по одной глубине — 5–8 с и фотореализм, но
# товары «вообще»; lightning img2img по коллажу — 5.5 с, но коллаж так и остаётся коллажем;
# nano-banana/edit — 12.5 с и единственная, кто превращает наши вклейки в мебель, сохраняя места.
# Для чернового берём её и прогреваем заранее.
MODEL = 'fal-ai/nano-banana/edit'
# МЯГКОЕ (плед, подушки, шторы) НЕ ВКЛЕИВАЕМ: у них нет своей формы, и плоское фото ткани в маске
# читается как флаг на стене — модель честно рисует флаг. Их дорисовывает промпт.
SKIP_PASTE = ('плед', 'подушка', 'штора', 'тюль', 'картина')
# СЛОВАРЬ РОЛЕЙ ДЛЯ ПРОМПТА: модель должна знать, ЧТО за серый блок стоит в кадре, иначе она
# честно оставляет его серым блоком (владелец 26.08: «бред делает»).
RU_EN = {'диван': 'sofa', 'диван 2': 'second sofa', 'кресло': 'armchair', 'столик': 'coffee table',
         'ковёр': 'rug', 'тв-тумба': 'TV console', 'тв': 'wall-mounted flat TV, screen off',
         'стенка': 'media wall unit', 'стеллаж': 'open bookshelf', 'комод': 'chest of drawers',
         'витрина': 'display cabinet', 'торшер': 'floor lamp', 'пуф': 'pouf', 'кашпо': 'potted plant',
         'стул': 'dining chair', 'стол обеденный': 'dining table', 'банкетка': 'bench',
         'люстра': 'ceiling light', 'приставной': 'side table', 'камин': 'fireplace'}


def build_prompt(diag: dict) -> str:
    """Что вклеено — «оставь как есть»; что не вклеено — «это такой-то предмет, нарисуй его»."""
    keep = [RU_EN.get(r.split(' ')[0], r) for r in diag.get('вклеено', [])]
    make = [RU_EN.get(r.split(' ')[0], r) for r in
            (diag.get('ракурс не тот', []) + diag.get('без фото', []))]
    p = ('Turn this collage into a photorealistic interior photograph. '
         'Keep the room geometry, the camera and the position of every object exactly as they are. '
         'Do not add or remove any furniture. ')
    if keep:
        p += ('The objects that already show a real product photo (' + ', '.join(dict.fromkeys(keep))
              + ') must keep their exact shape, colour and material. ')
    if make:
        p += ('The plain grey untextured blocks are furniture that must be rendered as realistic '
              'pieces of these kinds: ' + ', '.join(dict.fromkeys(make))
              + ' — same size and position, neutral modern style matching the room. ')
    p += ('The blue rectangle on the wall is a switched-off flat TV. '
          'Add natural daylight from the window, soft contact shadows, realistic wood floor and '
          'wall textures, and dress the sofa with a few matching cushions and a throw.')
    return p


def photo(url: str) -> Image.Image | None:
    """Фото товара с диска (кэш) или из сети — один раз на товар."""
    if not url:
        return None
    os.makedirs(CACHE, exist_ok=True)
    import hashlib
    p = os.path.join(CACHE, hashlib.md5(url.encode()).hexdigest()[:16] + '.png')
    if os.path.exists(p):
        return Image.open(p).convert('RGB')
    full = ('https:' + url) if url.startswith('//') else url
    try:
        req = urllib.request.Request(full, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=15) as f:
            img = Image.open(io.BytesIO(f.read())).convert('RGB')
    except Exception:
        return None
    img.thumbnail((640, 640))
    img.save(p, 'PNG')
    return img


def _cutout(img: Image.Image, thr: int = 238) -> tuple[Image.Image, Image.Image]:
    """Фото товара → (обрезанное фото, маска товара). Фон карточки — белый, и раньше он попадал
    в маску предмета сплошной плитой: модель честно рисовала белую плиту вместо стеллажа
    (владелец 26.08: «текущий рендер бред делает»). Фон отсекаем заливкой от краёв — так белый
    ВНУТРИ товара (белый шкаф) остаётся товаром."""
    a = np.asarray(img.convert('RGB')).astype(np.int16)
    h, w = a.shape[:2]
    light = a.min(axis=2) >= thr                      # почти белое
    seen = np.zeros((h, w), bool)
    stack = [(0, x) for x in range(w) if light[0, x]] + [(h - 1, x) for x in range(w) if light[h - 1, x]]
    stack += [(y, 0) for y in range(h) if light[y, 0]] + [(y, w - 1) for y in range(h) if light[y, w - 1]]
    for p0 in stack:
        seen[p0] = True
    while stack:
        y, x = stack.pop()
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            ny, nx = y + dy, x + dx
            if 0 <= ny < h and 0 <= nx < w and light[ny, nx] and not seen[ny, nx]:
                seen[ny, nx] = True
                stack.append((ny, nx))
    obj = ~seen
    if obj.sum() < 50:
        return img, Image.new('L', img.size, 255)
    ys, xs = np.where(obj)
    box = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)
    return img.crop(box), Image.fromarray((obj * 255).astype(np.uint8)).crop(box)


def collage(room, placements, cam, photos: dict) -> tuple[Image.Image, Image.Image, dict]:
    """→ (коллаж, карта глубины для контроля, диагностика)."""
    sc = compile_scene(room, placements, cam)
    depth, inst, ids = sc['depth'], sc['instances'], sc['ids']
    H, W = inst.shape
    # ФОН — НАШ CLAY-РЕНДЕР, А НЕ СЕРАЯ ГЛУБИНА (26.08): на «глубине» модель не видит ни стен,
    # ни пола, ни окна и возвращает предметы, висящие в пустоте (проверено). Clay даёт комнату.
    d = depth.copy()
    d[~np.isfinite(d)] = np.nanmax(d[np.isfinite(d)]) if np.isfinite(d).any() else 1.0
    dn = (d - d.min()) / max(d.max() - d.min(), 1e-6)
    canvas = Image.fromarray(clay_render(sc)).convert('RGB')
    put, miss, skewed = [], [], []
    order = sorted(ids.items(), key=lambda kv: -float(np.median(depth[inst == kv[0]]))
                   if (inst == kv[0]).any() else 0)          # дальние вклеиваем первыми
    for i, role in order:
        m = (inst == i)
        if m.sum() < 400:
            continue
        ph = None if role.split(' ')[0] in SKIP_PASTE else photos.get(role)
        if ph is None:
            miss.append(role)
            continue
        ys, xs = np.where(m)
        x0, x1, y0, y1 = int(xs.min()), int(xs.max()) + 1, int(ys.min()), int(ys.max()) + 1
        bw, bh = max(x1 - x0, 2), max(y1 - y0, 2)
        src, smask = _cutout(ph)
        # СИЛЬНОЕ НЕСОВПАДЕНИЕ ПРОПОРЦИЙ = предмет виден с другой стороны, чем снят на фото
        # (стеллаж с торца, тумба сбоку). Растянутое фото в такой силуэт превращается в мазок,
        # поэтому лучше оставить clay: модель нарисует мебель по форме, чем мы — кашу.
        if src.width and src.height and bw and bh:
            if max((src.width / src.height) / (bw / bh), (bw / bh) / (src.width / src.height)) > 2.6:
                skewed.append(role)
                continue
        src = src.resize((bw, bh), Image.LANCZOS)
        smask = smask.resize((bw, bh), Image.LANCZOS)
        tile = Image.new('RGB', (W, H), (255, 255, 255))
        tile.paste(src, (x0, y0))
        # альфа = маска предмета в кадре И маска самого товара на фото (без белого фона карточки)
        full = Image.new('L', (W, H), 0)
        full.paste(smask, (x0, y0))
        alpha = Image.fromarray(((m * (np.asarray(full) > 128)) * 255).astype(np.uint8)) \
            .filter(ImageFilter.GaussianBlur(0.6))
        canvas = Image.composite(tile, canvas, alpha)
        put.append(role)
    dmap = Image.fromarray(((1.0 - dn) * 255).astype(np.uint8)).convert('RGB')
    return canvas, dmap, {'вклеено': put, 'без фото': miss, 'ракурс не тот': skewed,
                          'вне кадра': sc['behind']}


def scene_from_request(payload: dict) -> tuple:
    """Комната и расстановка ИЗ ЗАПРОСА СТРАНИЦЫ (26.08): человек двигает мебель у себя, поэтому
    черновик обязан считаться по ТОЙ расстановке, что на экране, а не по банковскому артефакту."""
    from planner.models import Item, Opening, Placement, Radiator, Room
    r = payload['room']
    room = Room(width_cm=r['w'], depth_cm=r['d'],
                openings=[Opening(**{k: v for k, v in o.items() if not k.startswith('_')})
                          for o in (r.get('openings') or [])],
                radiators=[Radiator(**{k: v for k, v in x.items() if not k.startswith('_')})
                           for x in (r.get('radiators') or [])])
    placements, photos = [], {}
    for it in payload.get('items') or []:
        role = it['role']
        item = Item(role=role, w_cm=max(float(it['w']), 1), d_cm=max(float(it['d']), 1),
                    h_cm=float(it.get('h') or 0) or None, name=it.get('name'),
                    corner=bool(it.get('corner')),
                    corner_section_cm=float(it.get('section') or 95))
        placements.append(Placement(role=role, x=float(it['x']), y=float(it['y']),
                                    rot=float(it.get('rot') or 0), item=item,
                                    elev_cm=float(it.get('elev') or 0)))
        if it.get('img'):
            photos[role] = photo(it['img'])
    return room, placements, photos


def render(n: int | None = None, layout: dict | None = None, cam_name: str = 'C1',
           save_prefix: str | None = None) -> dict:
    t0 = time.time()
    if layout is not None:
        room, placements, photos = scene_from_request(layout)
    else:
        from scene_build import load_scene      # только для режима «по номеру сета»
        room, placements = load_scene(n)
        sets = json.load(open(os.path.join(HERE, 'sets3.json'), encoding='utf-8'))
        items = sets[n - 1]['items']
        photos = {r: photo((items.get(r) or {}).get('img')) for r in items}
    cams = [c for c in cameras_for(room, placements) if c.name == cam_name] or \
           cameras_for(room, placements)[:1]
    cam = cams[0]
    coll, dmap, diag = collage(room, placements, cam, photos)
    t_coll = time.time() - t0
    prefix = save_prefix or os.path.join(OUT, f'draft{n}-{cam.name}')
    coll.save(prefix + '-collage.jpg', quality=90)
    t1 = time.time()
    res = fal_run(MODEL, {'prompt': build_prompt(diag), 'num_images': 1,
                          'image_urls': [uri_from_image(coll.resize((1024, 683)))]},
                  fal_key(), timeout=120)
    url = ((res.get('images') or [{}])[0] or {}).get('url', '')
    t_ai = time.time() - t1
    if url:
        with urllib.request.urlopen(url, timeout=60) as f:
            open(prefix + '.jpg', 'wb').write(f.read())
    print(f'коллаж {t_coll:.1f} с, модель {t_ai:.1f} с, итого {time.time() - t0:.1f} с')
    print('  ' + json.dumps(diag, ensure_ascii=False))
    print('  ' + prefix + '.jpg')
    return {'file': prefix + '.jpg', 'url': url, 'sec': round(time.time() - t0, 1), 'diag': diag}


def warm() -> float:
    """Прогрев: холодный старт модели — 76 с, прогретая — 5.5 с. Зовём, когда человек начал двигать."""
    t = time.time()
    px = Image.new('RGB', (256, 256), (220, 220, 220))
    try:
        fal_run(MODEL, {'prompt': 'keep as is', 'num_images': 1,
                        'image_urls': [uri_from_image(px)]}, fal_key(), timeout=120)
    except SystemExit:
        pass
    return round(time.time() - t, 1)


if __name__ == '__main__':
    if '--warm' in sys.argv:
        print(f'прогрев: {warm()} с')
    elif '--layout' in sys.argv:
        pl = json.load(open(sys.argv[sys.argv.index('--layout') + 1], encoding='utf-8'))
        render(layout=pl, save_prefix=os.path.join(OUT, 'draft-live'))
    else:
        render(int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 10)
