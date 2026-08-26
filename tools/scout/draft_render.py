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
import re
import sys
import time
import urllib.request

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

sys.path.insert(0, '/home/pakar/igor/remlab/services/planner-solver')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from planner.scene import Camera, cameras_for, clay_render, compile_scene  # noqa: E402

from falmini import fal_key, fal_run, uri_from_image  # noqa: E402  (лёгкий клиент fal)

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.environ.get('SCENE_DIR', os.path.expanduser('~/scout-scenes'))
CACHE = os.path.join(OUT, 'draft-photos')
# ВЫБОР МОДЕЛИ (26.08, замерено на нашем ключе): sdxl по одной глубине — 5–8 с и фотореализм, но
# товары «вообще»; lightning img2img по коллажу — 5.5 с, но коллаж так и остаётся коллажем;
# nano-banana/edit — 12.5 с и единственная, кто превращает наши вклейки в мебель, сохраняя места.
# Для чернового берём её и прогреваем заранее.
MODEL = os.environ.get('DRAFT_MODEL', 'openai/gpt-image-2')      # черновик: тот же трек А
DRAFT_QUALITY = os.environ.get('DRAFT_QUALITY', 'low')            # low ≈ 20 с, medium ≈ 34 с
FAST_FALLBACK = 'fal-ai/nano-banana/edit'                         # если шлюз недоступен
# РЕАЛИСТИЧНЫЙ РЕЖИМ (26.08, владелец: «та модель, что уже в проекте»). Трек А плейбука точности —
# `gpt-image-2 medium` у OpenAI (13–14/14 точных предметов), но на ключе сейчас insufficient_quota,
# поэтому по умолчанию берём наш же проверенный дубль на fal (в A/B 10/10, $0.067/кадр).
# Переключение — переменной REALISTIC_MODEL, без правки кода.
REALISTIC_MODEL = os.environ.get('REALISTIC_MODEL', 'openai/gpt-image-2')  # через шлюз Vercel
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
    p += ('The dark rectangle on the wall is a switched-off flat TV. '
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


def collage(room, placements, cam, photos: dict,
            paste: bool = True) -> tuple[Image.Image, Image.Image, dict]:
    """→ (кадр, карта глубины для контроля, диагностика).

    `paste=True` — черновик: фотографии товаров вклеиваются в маски предметов (быстро и сразу
    видно состав). `paste=False` — трек А: отдаём модели ЧИСТЫЙ объёмный рендер комнаты, а товары
    показываем отдельным листом эталонов. Так решено ещё 05.08 (ADR-0062/0063): плоская вклейка
    врёт про РАЗВОРОТ — стул, снятый в фас, при виде сбоку выглядит повёрнутым не туда, и модель
    считает это намеренным; а всё, чего нет в листе эталонов, она выдумывает по названию.
    """
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
        if role.split(' ')[0] == 'тв':
            # ЭКРАН — ТЁМНЫЙ, А НЕ СИНИЙ (26.08): на clay-рендере ТВ синий, и модель честно
            # возвращала ярко-синюю панель на стене. Тёмная заливка читается как выключенный экран.
            dark = Image.new('RGB', (W, H), (24, 24, 26))
            canvas = Image.composite(dark, canvas,
                                     Image.fromarray((m * 255).astype(np.uint8)))
            put.append(role)
            continue
        ph = None if (not paste or role.split(' ')[0] in SKIP_PASTE) else photos.get(role)
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
    if paste:
        diag = {'вклеено': put, 'без фото': miss, 'ракурс не тот': skewed, 'вне кадра': sc['behind']}
    else:                       # трек А: в кадр ничего не клеим, товары — отдельным листом
        diag = {'в кадре': sorted(set(miss + put + skewed)), 'вне кадра': sc['behind']}
    return canvas, dmap, diag


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


def demo_cams(room) -> list:
    """ДВЕ КАМЕРЫ ИЗ УГЛОВ КОМНАТЫ (26.08, владелец: «мебель хреново расставляется»). Разбор
    исходников показал, что расстановка верная, а виновата съёмка: штатные камеры конвейера
    стоят вплотную к дивану и ТВ (они задуманы для витрины одного предмета), поэтому диван
    вылезал за край кадра, а половину картинки занимала пустая стена. Для планировщика нужен
    обзор ВСЕЙ комнаты: встаём в два противоположных угла на высоте глаз и смотрим в центр.
    """
    W, D = room.width_cm, room.depth_cm
    eye_h, tgt_h, off = 165.0, 105.0, 25.0
    cx, cy = W / 2, D / 2
    # ОСИ СЦЕНЫ: точка задаётся как (x, ВЫСОТА, глубина) — вверх смотрит Y, а не Z. Перепутал
    # порядок — и камера уезжает в стену: первый заход показал 1 предмет из 9 (26.08).
    return [
        Camera(name='C1', eye=(W - off, eye_h, D - off), target=(off, tgt_h, off), fov_deg=80.0,
               width=1344, height=896),
        Camera(name='C2', eye=(off, eye_h, D - off), target=(W - off, tgt_h, off), fov_deg=80.0,
               width=1344, height=896),
    ]


def anchors(room, placements, cam, skus: dict) -> list:
    """ЯКОРЯ ТОВАРОВ НА КАДРЕ (владелец 26.08: «на фотографиях размещать якоря на мебель»).

    Координаты НЕ спрашиваем у модели: сцену считаем мы, и маска каждого предмета в этом ракурсе
    уже есть (`compile_scene`). Берём точку внутри маски — она и есть место значка, в долях кадра.
    Это дешевле, детерминированно и не врёт: модель могла бы назвать чужие координаты.
    """
    sc = compile_scene(room, placements, cam)
    inst, ids = sc['instances'], sc['ids']
    H, W = inst.shape
    out = []
    for i, role in ids.items():
        m = (inst == i)
        if m.sum() < 400:
            continue
        ys, xs = np.where(m)
        cx, cy = float(xs.mean()), float(ys.mean())
        if not m[int(round(cy)), int(round(cx))]:          # центр масс вне маски (Г-образный предмет)
            k = int(np.argmin((xs - cx) ** 2 + (ys - cy) ** 2))
            cx, cy = float(xs[k]), float(ys[k])
        sku = skus.get(role) or {}
        out.append({'role': role, 'x': round(cx / W, 4), 'y': round(cy / H, 4),
                    'name': sku.get('name'), 'price': sku.get('price'),
                    'url': sku.get('url'), 'img': sku.get('img'), 'shop': sku.get('shop')})
    return out


def _one_camera(room, placements, photos, cam, prefix: str, model: str, side: int,
                skus: dict | None = None) -> dict:
    """Один ракурс: коллаж → один вызов модели → ссылка на кадр и якоря товаров."""
    coll, _dmap, diag = collage(room, placements, cam, photos)
    coll.save(f'{prefix}-{cam.name}-collage.jpg', quality=92)
    w = side
    h = max(2, int(round(side * coll.height / coll.width)))
    res = fal_run(model, {'prompt': build_prompt(diag), 'num_images': 1,
                          'image_urls': [uri_from_image(coll.resize((w, h)))]},
                  fal_key(), timeout=240)
    url = ((res.get('images') or [{}])[0] or {}).get('url', '')
    if url:
        try:
            with urllib.request.urlopen(url, timeout=60) as f:
                open(f'{prefix}-{cam.name}.jpg', 'wb').write(f.read())
        except Exception:
            pass
    return {'camera': cam.name, 'url': url, 'diag': diag,
            'anchors': anchors(room, placements, cam, skus or {})}


BAND_RGB, BAND_PX = (255, 0, 255), 94      # маркерная полоса между видами: маджента в интерьере
FRAMES_DIR = os.environ.get('FRAMES_DIR', os.path.join(OUT, 'frames'))   # не встречается, шов виден
FRAMES_URL = os.environ.get('FRAMES_URL', '/test/share/frames')
SRC_DIR = os.environ.get('SRC_DIR', os.path.join(OUT, 'src'))     # «исходники»: что ушло в модель
SRC_URL = os.environ.get('SRC_URL', '/test/share/src')
PUBLIC_BASE = os.environ.get('PUBLIC_BASE', '')


def _split_pair(sheet: Image.Image) -> list:
    """Режем ответ модели по маркерной полосе; полосы нет — делим пополам (как `viz_final`)."""
    a = np.asarray(sheet.convert('RGB')).astype(int)
    mask = (a[..., 0] > 170) & (a[..., 2] > 170) & (a[..., 1] < 110)
    rows = np.where(mask.mean(axis=1) > 0.5)[0]
    if len(rows) < 8:
        half = sheet.height // 2
        return [sheet.crop((0, 0, sheet.width, half)),
                sheet.crop((0, half, sheet.width, sheet.height))]
    y0, y1 = int(rows.min()), int(rows.max())
    return [sheet.crop((0, 0, sheet.width, y0)),
            sheet.crop((0, y1 + 1, sheet.width, sheet.height))]


def _trim_band(img: Image.Image) -> Image.Image:
    """Срезать остатки маркерной полосы по краям куска: пара строк маджента портит кадр."""
    a = np.asarray(img.convert('RGB')).astype(int)
    bad = ((a[..., 0] > 140) & (a[..., 2] > 140) & (a[..., 1] < 150)).mean(axis=1) > 0.12
    ys = np.where(~bad)[0]
    if not len(ys):
        return img
    return img.crop((0, int(ys.min()), img.width, int(ys.max()) + 1))


def _publish_frame(img: Image.Image, name: str) -> str:
    """Кадр из разрезанного листа кладём в раздаваемую папку и отдаём ссылку на него."""
    os.makedirs(FRAMES_DIR, exist_ok=True)
    img.save(os.path.join(FRAMES_DIR, name), quality=92)
    return (PUBLIC_BASE + FRAMES_URL + '/' + name) if PUBLIC_BASE else os.path.join(FRAMES_DIR, name)


def _sheet(room, placements, photos, cams, prefix: str, model: str, side: int, skus: dict) -> list:
    """ДВА ВИДА ОДНИМ ЛИСТОМ (владелец 26.08: «генерили как единую фотографию и резали по полосе»).

    Так свет, материалы и стиль у обоих ракурсов совпадают ПО ПОСТРОЕНИЮ, а не по удаче двух
    независимых вызовов, и это один запрос вместо двух.
    """
    import hashlib
    parts, diags = [], []
    for cam in cams:
        coll, _d, diag = collage(room, placements, cam, photos)
        h = max(2, int(round(side * coll.height / coll.width)))
        parts.append(coll.resize((side, h)))
        diags.append(diag)
    total_h = sum(p.height for p in parts) + BAND_PX * (len(parts) - 1)
    sheet = Image.new('RGB', (side, total_h), BAND_RGB)
    y = 0
    for p in parts:
        sheet.paste(p, (0, y))
        y += p.height + BAND_PX
    sheet.save(prefix + '-sheet.jpg', quality=92)
    merged = {k: sum([d.get(k, []) for d in diags], []) for k in
              ('вклеено', 'без фото', 'ракурс не тот', 'вне кадра')}
    prompt = (build_prompt(merged) +
              ' The image is a single sheet with two views of the SAME room stacked vertically and '
              'separated by a magenta band. Render both views, keep the magenta band exactly where '
              'it is, and make lighting and materials identical in both.')
    res = fal_run(model, {'prompt': prompt, 'num_images': 1,
                          'image_urls': [uri_from_image(sheet)]}, fal_key(), timeout=300)
    url = ((res.get('images') or [{}])[0] or {}).get('url', '')
    if not url:
        return []
    with urllib.request.urlopen(url, timeout=120) as f:
        raw = f.read()
    out_sheet = Image.open(io.BytesIO(raw)).convert('RGB')
    pieces = _split_pair(out_sheet)
    stamp = hashlib.md5((prefix + str(time.time())).encode()).hexdigest()[:10]
    shots = []
    for cam, piece, diag in zip(cams, pieces, diags):
        piece = _trim_band(piece)
        piece.save(f'{prefix}-{cam.name}.jpg', quality=92)
        shots.append({'camera': cam.name, 'url': _publish_frame(piece, f'{stamp}-{cam.name}.jpg'),
                      'diag': diag, 'anchors': anchors(room, placements, cam, skus)})
    return shots


# ——— ТРЕК А: ГЛАВНЫЙ КАДР ЧЕРЕЗ GPT-IMAGE (владелец 26.08: «мы отправляли модель с подписанными
# элементами и референсы всех фотографий одним листом, промпт делал одну картинку в двух видах»).
# Восстановлен рецепт `viz_final.py`: модель получает ЧЕТЫРЕ вещи —
#   1) лист из двух ракурсов (коллаж), разделённых маджента-полосой;
#   2) тот же лист с НОМЕРАМИ предметов;
#   3) лист эталонов: фотография каждого товара с подписью «#N роль»;
#   4) список предметов JSON: номер, товар, роль, габариты, где стоит, в каком виде виден.
# Модель дорисовывает свет и материалы, но не выдумывает состав: всё названо и показано.
GATEWAY = 'https://ai-gateway.vercel.sh/v1/images/edits'


def gw_key() -> str:
    k = os.environ.get('VERCEL_AI_GATEWAY_KEY')
    if k:
        return k.strip()
    for p in (os.path.join(HERE, '.env'), os.path.join(HERE, '..', '..', '.env')):
        try:
            for line in open(p, encoding='utf-8'):
                if line.startswith('VERCEL_AI_GATEWAY_KEY='):
                    return line.split('=', 1)[1].strip().strip('"\'')
        except OSError:
            continue
    raise SystemExit('нет VERCEL_AI_GATEWAY_KEY — см. .memory_bank/_secrets/ACCESS.md')


def _font(size: int):
    for p in ('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
              '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'):
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def _marked(img: Image.Image, anchors: list, skus: dict) -> Image.Image:
    """Кадр с НОМЕРОМ, НАЗВАНИЕМ И РАЗМЕРОМ каждого предмета (владелец 26.08: «подписывали размеры
    каждого элемента и что это — стол, стул, а потом с номерами»). Номер связывает предмет в кадре
    с его эталонной фотографией на отдельном листе, подпись говорит модели, что это и какого оно
    размера, — тогда она не превращает тумбу в комод и не меняет пропорции."""
    out = img.copy()
    d = ImageDraw.Draw(out)
    r = max(16, img.width // 42)
    f = _font(int(r * 1.25))
    fc = _font(max(13, int(r * 0.78)))
    for a in anchors:
        cx, cy = a['x'] * out.width, a['y'] * out.height
        sku = skus.get(a['role']) or {}
        dim = ''
        if sku.get('w') and sku.get('d'):
            dim = f" {round(sku['w'])}×{round(sku['d'])}" + (f"×{round(sku['h'])}" if sku.get('h') else '')
        cap = f"{a['n']}. {a['role']}{dim} см" if dim else f"{a['n']}. {a['role']}"
        bb = d.textbbox((0, 0), cap, font=fc)
        w, h = bb[2] - bb[0] + 10, bb[3] - bb[1] + 8
        bx, by = min(max(cx - w / 2, 2), out.width - w - 2), min(cy + r + 4, out.height - h - 2)
        d.rectangle([bx, by, bx + w, by + h], fill=(255, 255, 255))
        d.text((bx + 5, by + 4), cap, fill=(200, 30, 30), font=fc)
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 255, 255), outline=(200, 30, 30),
                  width=max(2, r // 7))
        d.text((cx, cy), str(a['n']), fill=(200, 30, 30), anchor='mm', font=f)
    return out


def _identity(anchors_all: list, photos: dict, skus: dict | None = None) -> Image.Image | None:
    """Лист эталонов: фото КАЖДОГО товара с подписью «#N роль» — по нему модель узнаёт материал."""
    seen, cells = set(), []
    for a in anchors_all:
        if a['role'] in seen:
            continue
        seen.add(a['role'])
        # ЛИСТ ЭТАЛОНОВ ПОКРЫВАЕТ ВСЕ ПОЗИЦИИ КАДРА (ADR-0063, опыт «б» 05.08): всё, чего модель
        # не увидела фотографией, она выдумывает по названию. Нет фото — кладём пустую карточку
        # с подписью, чтобы предмет всё равно был назван.
        cells.append((a['n'], a['role'], photos.get(a['role']), a.get('name') or ''))
    if not cells:
        return None
    cells.sort(key=lambda c: c[0])
    cols = min(3, len(cells))
    rows = (len(cells) + cols - 1) // cols
    cw, ch = 520, 500
    sheet = Image.new('RGB', (cols * cw, rows * ch), (255, 255, 255))
    d = ImageDraw.Draw(sheet)
    f = _font(34)
    fs = _font(24)
    for i, (num, role, im, name) in enumerate(cells):
        x, y = (i % cols) * cw, (i // cols) * ch
        if im is not None:
            im = im.copy()
            im.thumbnail((cw - 40, ch - 120))
            sheet.paste(im, (x + (cw - im.width) // 2, y + 24))
        else:
            d.rectangle([x + 30, y + 30, x + cw - 30, y + ch - 130], outline=(200, 200, 200), width=3)
            d.text((x + cw // 2, y + (ch - 100) // 2), 'фото нет', fill=(150, 150, 150),
                   anchor='mm', font=_font(28))
        sku = (skus or {}).get(role) or {}
        dim = (f"{round(sku['w'])}×{round(sku['d'])}" + (f"×{round(sku['h'])}" if sku.get('h') else '') + ' см'
               if sku.get('w') and sku.get('d') else '')
        d.text((x + 20, y + ch - 86), f'#{num} {role}', fill=(200, 30, 30), font=f)
        d.text((x + 20, y + ch - 46), (name[:38] + (' · ' + dim if dim else '')), fill=(90, 90, 90), font=fs)
    return sheet


def _legend(per_cam: list, skus: dict) -> list:
    """Список предметов для модели: номер, товар, роль, габариты и в каком виде он виден."""
    merged = {}
    for idx, anchors in enumerate(per_cam):
        for a in anchors:
            it = merged.setdefault(a['n'], {
                'id': a['n'], 'type': a['role'],
                'product': a.get('name') or '—',
                'size_cm': None, 'in_view_1': 'absent', 'in_view_2': 'absent'})
            sku = skus.get(a['role']) or {}
            if sku.get('w'):
                it['size_cm'] = f"{round(sku['w'])}x{round(sku.get('d') or 0)}" + \
                                (f"x{round(sku['h'])}" if sku.get('h') else '')
            it['in_view_1' if idx == 0 else 'in_view_2'] = 'visible'
    return [merged[k] for k in sorted(merged)]


def gpt_edit(images: list, prompt: str, size: str = '1024x1536',
             quality: str = 'medium', model: str = 'openai/gpt-image-2') -> Image.Image:
    """Один запрос в gpt-image через шлюз Vercel: несколько картинок + текст → один лист."""
    import uuid
    bnd = '----rl' + uuid.uuid4().hex[:16]
    body = b''

    def part(name: str, val: str) -> bytes:
        return (f'--{bnd}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{val}\r\n').encode()

    body += part('model', model) + part('prompt', prompt) + part('size', size) + part('quality', quality)
    for i, im in enumerate(images):
        buf = io.BytesIO()
        im.convert('RGB').save(buf, 'JPEG', quality=92)
        body += (f'--{bnd}\r\nContent-Disposition: form-data; name="image[]"; '
                 f'filename="i{i}.jpg"\r\nContent-Type: image/jpeg\r\n\r\n').encode()
        body += buf.getvalue() + b'\r\n'
    body += f'--{bnd}--\r\n'.encode()
    req = urllib.request.Request(GATEWAY, data=body, headers={
        'Authorization': f'Bearer {gw_key()}',
        'Content-Type': f'multipart/form-data; boundary={bnd}'})
    with urllib.request.urlopen(req, timeout=900) as r:
        j = json.loads(r.read())
    b64 = (j.get('data') or [{}])[0].get('b64_json')
    if not b64:
        raise SystemExit(f'шлюз не вернул картинку: {json.dumps(j)[:300]}')
    import base64
    return Image.open(io.BytesIO(base64.b64decode(b64))).convert('RGB')


def _publish_sources(stamp: str, imgs: dict, prompt: str, legend: list, meta: dict) -> str:
    """СЛУЖЕБНАЯ СТРАНИЦА «ИСХОДНИКИ» (владелец 26.08: «покажи полностью, что отправляешь в GPT и
    в каком виде и какой промпт — результат пока плохой»). Кладём РОВНО то, что ушло в модель:
    каждую картинку запроса, текст промпта и список предметов. Проверяемость важнее аккуратности:
    если кадр плохой, по этой странице видно, виноват вход или модель."""
    d = os.path.join(SRC_DIR, stamp)
    os.makedirs(d, exist_ok=True)
    tiles = []
    for name, im in imgs.items():
        if im is None:
            continue
        im.save(os.path.join(d, f'{name}.jpg'), quality=88)
        tiles.append(f'<figure><a href="{name}.jpg" target="_blank"><img src="{name}.jpg" '
                     f'alt="{name}"></a><figcaption>{name} · {im.width}×{im.height}</figcaption></figure>')
    open(os.path.join(d, 'prompt.txt'), 'w', encoding='utf-8').write(prompt)
    open(os.path.join(d, 'legend.json'), 'w', encoding='utf-8').write(
        json.dumps(legend, ensure_ascii=False, indent=1))
    import html as _h
    page = (
        '<!doctype html><html lang="ru"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="robots" content="noindex"><title>Исходники запроса</title><style>'
        'body{margin:0;background:#fff;color:#1A1F1C;font:15px/1.5 system-ui,-apple-system,Segoe UI,Roboto}'
        '.w{max-width:1200px;margin:0 auto;padding:16px}'
        'h1{font-size:22px;margin:4px 0 2px}.m{color:#5C655E;font-size:14px;margin-bottom:14px}'
        '.g{display:grid;gap:14px;grid-template-columns:repeat(auto-fill,minmax(300px,1fr))}'
        'figure{margin:0}img{width:100%;border:1px solid #E4E6E2;border-radius:8px;display:block}'
        'figcaption{font-size:13px;color:#5C655E;margin-top:5px}'
        'pre{white-space:pre-wrap;background:#FAF8F3;border:1px solid #E4E6E2;border-radius:8px;'
        'padding:12px;font-size:13px;overflow:auto;max-height:60vh}'
        'h2{font-size:17px;margin:22px 0 8px}</style></head><body><div class="w">'
        f'<h1>Что уходит в модель</h1><div class="m">{_h.escape(json.dumps(meta, ensure_ascii=False))}</div>'
        f'<div class="g">{"".join(tiles)}</div>'
        f'<h2>Промпт</h2><pre>{_h.escape(prompt)}</pre>'
        f'<h2>Список предметов (уходит в промпт)</h2>'
        f'<pre>{_h.escape(json.dumps(legend, ensure_ascii=False, indent=1))}</pre>'
        '</div></body></html>')
    open(os.path.join(d, 'index.html'), 'w', encoding='utf-8').write(page)
    return (PUBLIC_BASE + SRC_URL + '/' + stamp + '/') if PUBLIC_BASE else d


VISION_MODEL = os.environ.get('VISION_MODEL', 'openai/gpt-4.1-mini')
CHAT_URL = 'https://ai-gateway.vercel.sh/v1/chat/completions'


def refine_anchors(img: Image.Image, an: list) -> list:
    """УТОЧНЯЕМ ЯКОРЯ ПО ГОТОВОМУ КАДРУ (владелец 26.08: «цифры все неверно обозначены»).

    Наши координаты точны для НАШЕЙ сцены, но модель перерисовывает комнату и мелкие предметы
    (торшер, тумба, стеллаж) сдвигает — значок повисал не на том предмете. Поэтому спрашиваем
    зрячую модель, где предмет на ИТОГОВОМ кадре, и берём её точку, только если она недалеко от
    нашей: так уходит грубая ошибка, но не появляется выдумка на пустом месте.
    """
    roles = [a['role'] for a in an if a.get('name')]
    if not roles:
        return an
    import base64
    buf = io.BytesIO()
    img.convert('RGB').save(buf, 'JPEG', quality=80)
    b64 = base64.b64encode(buf.getvalue()).decode()
    body = {'model': VISION_MODEL, 'max_tokens': 700, 'messages': [{'role': 'user', 'content': [
        {'type': 'text', 'text': 'Найди на этом фото интерьера предметы: ' + ', '.join(roles) +
         '. Ответь ТОЛЬКО JSON-массивом [{"role":"диван","x":0.31,"y":0.65}] — x и y это доли '
         'ширины и высоты кадра, точка в центре видимой части предмета. Предмет не виден — не '
         'включай его в ответ.'},
        {'type': 'image_url', 'image_url': {'url': 'data:image/jpeg;base64,' + b64}}]}]}
    try:
        req = urllib.request.Request(CHAT_URL, data=json.dumps(body).encode(),
                                     headers={'Authorization': f'Bearer {gw_key()}',
                                              'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=90) as r:
            txt = json.loads(r.read())['choices'][0]['message']['content'] or ''
        m = re.search(r'\[.*\]', txt, re.S)
        found = {d.get('role'): d for d in json.loads(m.group(0))} if m else {}
    except Exception:
        return an
    out = []
    for a in an:
        d = found.get(a['role'])
        b = dict(a)
        if d and isinstance(d.get('x'), (int, float)) and isinstance(d.get('y'), (int, float)):
            dx, dy = float(d['x']) - a['x'], float(d['y']) - a['y']
            if 0 <= float(d['x']) <= 1 and 0 <= float(d['y']) <= 1 and (dx * dx + dy * dy) ** 0.5 < 0.28:
                b['x'], b['y'] = round(float(d['x']), 4), round(float(d['y']), 4)
                b['refined'] = True
        out.append(b)
    return out


def _sheet_gpt(room, placements, photos, cams, prefix: str, side: int, skus: dict,
               model: str, quality: str = 'medium') -> list:
    """Полный рецепт трека А: коллажи → номера → эталоны → один запрос → разрез по полосе."""
    import hashlib
    parts, marks, diags, per_cam = [], [], [], []
    numbering: dict = {}
    for cam in cams:
        coll, _d, diag = collage(room, placements, cam, photos, paste=False)
        h = max(2, int(round(side * coll.height / coll.width)))
        coll = coll.resize((side, h))
        an = anchors(room, placements, cam, skus)
        for a in an:                                   # сквозная нумерация по всем видам
            a['n'] = numbering.setdefault(a['role'], len(numbering) + 1)
        parts.append(coll)
        marks.append(_marked(coll, an, skus))
        diags.append(diag)
        per_cam.append(an)
    def stack(imgs):
        total = sum(p.height for p in imgs) + BAND_PX * (len(imgs) - 1)
        sh = Image.new('RGB', (side, total), BAND_RGB)
        y = 0
        for p in imgs:
            sh.paste(p, (0, y))
            y += p.height + BAND_PX
        return sh
    sheet, sheet_marks = stack(parts), stack(marks)
    sheet.save(prefix + '-sheet.jpg', quality=92)
    sheet_marks.save(prefix + '-marked.jpg', quality=92)
    ident = _identity([a for an in per_cam for a in an], photos, skus)
    if ident is not None:
        ident.save(prefix + '-identity.jpg', quality=92)
    legend = _legend(per_cam, skus)
    prompt = (
        'You are given: (1) a sheet with TWO views of the SAME room stacked vertically and split by '
        'a magenta band — this is OUR 3D layout: every piece of furniture is a plain grey volume in '
        'its exact place, size and orientation; (2) the same sheet with red numbers and captions '
        '(number, type of furniture and its size in cm); (3) a reference sheet with the real product '
        'photo of every numbered item.\n'
        'Return ONE image of the same proportions: both views rendered as photorealistic interior '
        'photographs, with the magenta band kept exactly where it is.\n'
        'Rules:\n'
        '- Replace each numbered grey volume with the product that carries the SAME number on the '
        'reference sheet: same model, colour, material and proportions.\n'
        '- Keep the position, footprint and ORIENTATION of every volume exactly as in the layout. '
        'The reference photo shows the product from a catalogue angle — do not copy that angle, turn '
        'the product to match the volume in the room.\n'
        '- Do not add, remove or move furniture. Do not draw the red numbers or captions.\n'
        '- Items marked "фото нет" have no reference: render a plain, neutral piece of that exact '
        'type and size.\n'
        '- Natural daylight from the window, soft contact shadows, realistic wood floor and wall '
        'textures; lighting and materials identical in both views.\n'
        'Objects:\n'
        + json.dumps(legend, ensure_ascii=False))
    imgs = [sheet, sheet_marks] + ([ident] if ident is not None else [])
    w, h = sheet.size
    size = '1024x1536' if h > w else '1536x1024'
    stamp = hashlib.md5((prefix + str(time.time())).encode()).hexdigest()[:10]
    src_url = _publish_sources(stamp, {'1-комната-два-вида': sheet, '2-с-номерами': sheet_marks,
                                       '3-эталоны-товаров': ident}, prompt, legend,
                               {'модель': model, 'размер': size, 'качество': quality,
                                'видов': len(cams)})
    out = gpt_edit(imgs, prompt, size=size, quality=quality, model=model.split('gateway:')[-1])
    out.save(prefix + '-final.jpg', quality=94)
    pieces = _split_pair(out)
    shots = []
    for cam, piece, diag, an in zip(cams, pieces, diags, per_cam):
        piece = _trim_band(piece)
        piece.save(f'{prefix}-{cam.name}.jpg', quality=92)
        shots.append({'camera': cam.name, 'url': _publish_frame(piece, f'{stamp}-{cam.name}.jpg'),
                      'diag': diag, 'anchors': refine_anchors(piece, an), 'sources': src_url})
    return shots


def render(n: int | None = None, layout: dict | None = None, cam_name: str = 'C1',
           save_prefix: str | None = None, quality: str = 'draft') -> dict:
    """Кадр(ы) комнаты. `draft` — один ракурс и быстрая модель, `realistic` — два ракурса
    (от окна и от входа), модель точности и больший размер коллажа.

    Модель реалистичного режима задаётся `REALISTIC_MODEL`. По плейбуку точности трек А — это
    `gpt-image-2 medium` у OpenAI, но на ключе 26.08 `insufficient_quota`, поэтому по умолчанию
    работает проверенный нами дубль на fal (`nano-banana-2/edit`, в A/B 10/10 точных предметов).
    """
    t0 = time.time()
    if layout is not None:
        room, placements, photos = scene_from_request(layout)
    else:
        from scene_build import load_scene      # только для режима «по номеру сета»
        room, placements = load_scene(n)
        sets = json.load(open(os.path.join(HERE, 'sets3.json'), encoding='utf-8'))
        items = sets[n - 1]['items']
        photos = {r: photo((items.get(r) or {}).get('img')) for r in items}
    all_cams = demo_cams(room) if os.environ.get('DEMO_CAMS', '1') != '0' \
        else cameras_for(room, placements)
    if quality == 'realistic':
        want = [c for c in all_cams if c.name in ('C1', 'C2')] or all_cams[:2]
        model, side, gq = REALISTIC_MODEL, 1536, os.environ.get('GPT_IMAGE_QUALITY', 'medium')
    else:
        want = [c for c in all_cams if c.name in ('C1', 'C2')] or all_cams[:2]
        model, side, gq = MODEL, 1024, DRAFT_QUALITY
    prefix = save_prefix or os.path.join(OUT, f'draft{n}')
    skus = {it['role']: it for it in (layout or {}).get('items', []) if it.get('role')}
    if len(want) > 1:
        # gpt-image идёт по полному рецепту трека А (номера + эталоны + список), fal — коротким
        shots = (_sheet_gpt(room, placements, photos, want, prefix, side, skus, model, gq)
                 if model.startswith('openai/')
                 else _sheet(room, placements, photos, want, prefix, model, side, skus))
    else:
        shots = [_one_camera(room, placements, photos, want[0], prefix, model, side, skus)]
    sec = round(time.time() - t0, 1)
    print(f'{quality}: кадров {len([s for s in shots if s["url"]])} из {len(want)}, {sec} с, модель {model}')
    for s in shots:
        print('  ' + s['camera'] + ' ' + json.dumps(s['diag'], ensure_ascii=False))
    first = shots[0] if shots else {'url': '', 'diag': {}}
    return {'shots': [{'camera': s['camera'], 'url': s['url'], 'anchors': s.get('anchors') or [],
                       'sources': s.get('sources')} for s in shots if s['url']],
            'sources': next((s.get('sources') for s in shots if s.get('sources')), None),
            'model': model, 'quality': quality, 'sec': sec,
            'file': f'{prefix}-{first.get("camera", "C1")}.jpg',
            'url': first.get('url', ''), 'diag': first.get('diag', {})}


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
