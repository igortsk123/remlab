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
# ЧЕРНОВИК — САМАЯ ПРОСТАЯ КАРТИНОЧНАЯ МОДЕЛЬ (владелец 27.08: «надо на минимальных и самую
# простую gpt-модель, которая прорисовывает может не полностью все детали»). Замер на одном и том
# же листе: gpt-image-1-mini 13.7 с, gpt-image-1 15.8 с, gpt-image-2 19.2 с. Товары у mini —
# приближение, но комната, расстановка, окно и ковёр на полу читаются верно.
# ЧЕРНОВИК — ТА ЖЕ gpt-image-2, НО НА МИНИМАЛКАХ (владелец 27.08: «gpt-image-2 ставь, но на
# минималках — там качество же можно менять»). quality=low + лист 1024: ~19–22 с против 38–45 у
# medium. У mini время то же, но она теряет товары и маджента-полосу, поэтому вернулись к -2.
MODEL = os.environ.get('DRAFT_MODEL', 'openai/gpt-image-2')       # черновик: тот же трек А
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
    # ЦВЕТА СЛУЖЕБНОГО РЕНДЕРА — ЭТО НЕ ПРЕДМЕТЫ (26.08): синий прямоугольник на стене я по ошибке
    # называл телевизором, а это ОКНО (палитра clay: window = 108,166,208), и модель рисовала синюю
    # панель вместо окна. Коричневый прямоугольник — дверь.
    p += ('In the layout image a blue rectangle on a wall is a WINDOW: render it as a real window '
          'with glass, frame and daylight outside, never as a panel or picture. A brown rectangle '
          'is a DOOR. Add natural daylight from the window, soft contact shadows, realistic wood '
          'floor and wall textures, and dress the sofa with a few matching cushions and a throw.')
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
        if m.sum() < 20:
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


def _opening(o: dict) -> dict:
    """Проём из запроса страницы → поля модели планировщика (лишнее отбрасываем)."""
    out = {k: v for k, v in o.items()
           if k in ('kind', 'wall', 'offset_cm', 'width_cm', 'swing_cm', 'sill_cm')}
    # `height_cm` модель планировщика не знает — размер окна уходит отдельно в промпт
    if o.get('hinge') in ('start', 'left'):
        out['hinge'] = 'left'
    elif o.get('hinge') in ('end', 'right'):
        out['hinge'] = 'right'
    if o.get('into') is False:
        out['swing_cm'] = 0        # открывается наружу — внутри комнаты место не занимает
    return out


def scene_from_request(payload: dict) -> tuple:
    """Комната и расстановка ИЗ ЗАПРОСА СТРАНИЦЫ (26.08): человек двигает мебель у себя, поэтому
    черновик обязан считаться по ТОЙ расстановке, что на экране, а не по банковскому артефакту."""
    from planner.models import Item, Opening, Placement, Radiator, Room
    r = payload['room']
    room = Room(width_cm=r['w'], depth_cm=r['d'],
                openings=[Opening(**_opening(o)) for o in (r.get('openings') or [])],
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
    for role in list(photos):                    # экземпляры пары («стул 2») наследуют фото роли
        pass
    for it in payload.get('items') or []:
        role = it['role']
        base = role.split(' ')[0]
        if photos.get(role) is None and photos.get(base) is not None:
            photos[role] = photos[base]
    # ТЕЛЕВИЗОР — ОБЪЁМ В СЦЕНЕ, А НЕ ПРОСЬБА В ТЕКСТЕ (27.08, владелец: «телевизор напротив
    # дивана, а в присланных вариантах он где угодно»). Пока ТВ существовал только фразой в
    # промпте, модель вешала его на любую понравившуюся стену. Теперь это пронумерованная панель
    # на стене над тумбой: у неё есть место, размер и разворот, как у любого другого предмета.
    stand = next((p for p in placements if _base_role(p.role) == 'тв-тумба'), None)
    if stand is not None and not any(_base_role(p.role) == 'тв' for p in placements):
        seat = next((p for p in placements if _base_role(p.role) == 'диван'), None) \
            or next((p for p in placements if _base_role(p.role) == 'кресло'), None)
        dist = (((seat.x - stand.x) ** 2 + (seat.y - stand.y) ** 2) ** 0.5
                if seat is not None else 300.0)   # math импортируется локально по файлу
        inch, w, h, elev, how = tv_spec(dist, float(stand.item.w_cm),
                                        float(stand.item.h_cm or 45))
        placements.append(Placement(role='тв', x=stand.x, y=stand.y, rot=stand.rot,
                                    elev_cm=elev,
                                    item=Item(role='тв', w_cm=w, d_cm=8.0, h_cm=h,
                                              name=f'телевизор {inch}″ ({how})')))
    return room, placements, photos



# --- телевизор: размер по расстоянию, подвес по высоте тумбы ------------------------------------
# Таблица владельца (01.09). Расстояние до экрана → рекомендуемая диагональ. Это ходовая норма
# для 4K: смотреть с 1.5 м на 85″ невозможно, а с 4 м на 43″ ничего не видно.
TV_BY_DIST_CM = ((150, 43), (200, 50), (250, 55), (300, 65), (350, 75), (10 ** 9, 85))
TV_SEAT_EYE_CM = 105.0     # центр экрана на уровне глаз сидящего — норма установки
TV_MAX_CENTER_CM = 125.0   # выше этого шею уже задирают: значит вешаем, а не ставим


def tv_spec(dist_cm: float, stand_w_cm: float, stand_h_cm: float):
    """→ (дюймы, ширина см, высота см, отметка низа см, как поставлен).

    Диагональ — по таблице расстояний, но НЕ шире тумбы (правило владельца 01.09: «не более
    длины тв тумбы»). Прежний код брал 90% ширины тумбы и растягивал экран на всю её длину
    независимо от того, с какого расстояния на него смотрят.

    Подвес: если, стоя на тумбе, центр экрана оказывается не выше TV_MAX_CENTER_CM — ТВ СТОИТ
    на тумбе. Иначе вешаем на стену и опускаем центр к уровню глаз сидящего, но не ниже
    верха тумбы — сквозь мебель экран не вешают.
    """
    inch = next(v for lim, v in TV_BY_DIST_CM if dist_cm < lim)
    diag = inch * 2.54
    w = diag * 16 / (16 ** 2 + 9 ** 2) ** 0.5          # 16:9
    h = diag * 9 / (16 ** 2 + 9 ** 2) ** 0.5
    # ПОТОЛОК — ТУМБА, И С ЗАПАСОМ. Владелец 01.09 просил и «не более длины тв-тумбы», и «чтоб
    # не растягивался на всю длину»: экран ровно в длину тумбы читается как растянутый, поэтому
    # оставляем поля. Доля настраивается (TV_MAX_STAND_FRAC), по умолчанию 0.9 — обычная норма
    # установки: тумба шире экрана, а не вровень.
    cap = stand_w_cm * float(os.environ.get('TV_MAX_STAND_FRAC', 0.9))
    if cap > 0 and w > cap:
        k = cap / w
        w, h = w * k, h * k
        inch = round((w ** 2 + h ** 2) ** 0.5 / 2.54)
    if stand_h_cm + h / 2 <= TV_MAX_CENTER_CM:
        return inch, round(w, 1), round(h, 1), round(stand_h_cm, 1), 'на тумбе'
    elev = max(stand_h_cm + 10.0, TV_SEAT_EYE_CM - h / 2)
    return inch, round(w, 1), round(h, 1), round(elev, 1), 'на стене'

def _cam_score(room, placements, cam) -> dict:
    """Насколько кадр ГОДЕН: сколько предметов видно, сколько обрезано рамкой, не заслоняет ли
    один предмет полкадра. Считаем по уменьшенной сцене — дёшево и детерминированно."""
    small = Camera(name=cam.name, eye=cam.eye, target=cam.target, fov_deg=cam.fov_deg,
                   width=336, height=224)
    sc = compile_scene(room, placements, small)
    inst, ids = sc['instances'], sc['ids']
    H, W = inst.shape
    seen, cut, hog = set(), set(), 0.0
    for i, role in ids.items():
        m = (inst == i)
        n = int(m.sum())
        if n < 60:                                  # предмет практически не виден
            continue
        seen.add(role)
        ys, xs = np.where(m)
        if xs.min() <= 0 or xs.max() >= W - 1 or ys.min() <= 0 or ys.max() >= H - 1:
            cut.add(role)
        hog = max(hog, n / (W * H))
    empty = float((sc['semantic'] == 0).mean())     # сколько кадра «мимо комнаты»
    fur = (inst > 0)
    area = float(fur.mean())                        # доля кадра, занятая мебелью
    cy = float(np.where(fur)[0].mean() / H) if fur.any() else 0.5
    # кадр должен выглядеть как фотография комнаты: мебель занимает около трети кадра и стоит
    # примерно по центру по высоте, а не жмётся к нижнему краю под пустым потолком
    return {'seen': seen, 'cut': cut, 'hog': hog, 'area': round(area, 3), 'cy': round(cy, 3),
            'empty': round(empty, 3),
            'score': (len(seen) - 0.6 * len(cut) - (2.0 if hog > 0.34 else 0.0)
                      - 4.0 * abs(area - 0.33) - 3.0 * abs(cy - 0.58)
                      - 6.0 * max(0.0, empty - 0.10))}


def demo_cams(room, placements=None) -> list:
    """ДВА РАКУРСА ВЫБИРАЮТСЯ ЗАМЕРОМ, А НЕ ДОКТРИНОЙ (27.08, разбор Codex + жалоба владельца
    «стул виден, а ИИ ставит туда стеллаж»): камера в углу в 25 см от стен давала кадр, где диван
    закрывает полкадра, половина предметов обрезана рамкой, и модель достраивала комнату по
    своему разумению. Теперь перебираем углы (в т.ч. вынесенные ЗА стену — стена ближе камеры
    не рисуется) и берём пару кадров, которая показывает больше предметов целиком.

    Без расстановки (старый вызов) остаётся прежнее поведение: два противоположных угла.
    """
    W, D = room.width_cm, room.depth_cm
    eye_h, tgt_h = 165.0, 105.0
    def cam(name, ex, ey, tx, ty, fov):
        return Camera(name=name, eye=(ex, eye_h, ey), target=(tx, tgt_h, ty), fov_deg=fov,
                      width=1344, height=896)
    if not placements:
        off = 25.0
        return [cam('C1', W - off, D - off, off, off, 72.0),
                cam('C2', off, off, W - off, D - off, 72.0)]
    cx, cy = W / 2, D / 2
    fx = sum(p.x for p in placements) / len(placements)
    fy = sum(p.y for p in placements) / len(placements)
    # УГОЛ ОБЗОРА: потолок 72° по горизонтали (владелец 01.09 — «максимально широкий, но без
    # искажений»). 72° при кадре 3:2 это ≈24 мм в плёночном эквиваленте — общепринятая граница
    # интерьерной съёмки: шире начинается растяжение по краям, круглое становится овальным, а
    # предмет у рамки выглядит крупнее и шире, чем он есть. Прежние 82° (≈20 мм) эту границу
    # переходили. Охват не теряем: камеру и так выносим за стену (cutaway ниже), что даёт тот же
    # обзор без искажения.
    # КАМЕРА ВСЕГДА ВНУТРИ ПЕРИМЕТРА, И ОТБОР ОБЯЗАН ЭТО ЗНАТЬ (01.09). Правило «сквозь стену
    # смотреть нельзя» (владелец 31.08) применялось ПОЗЖЕ отбора: кандидаты считались из точек
    # за стеной, побеждал лучший из них, а рендер потом заводил глаз внутрь — и кадр выходил не
    # тем, который выиграл. Заодно это делало бессмысленным «вынос за стену» как способ
    # расширить охват: единственный оставшийся рычаг — угол объектива.
    def _clamp(x, z):
        pad = 25.0
        return (min(max(x, pad), W - pad), min(max(z, pad), D - pad))

    cands = []
    CORNERS = ((W, D), (0, 0), (W, 0), (0, D))
    DIAG = {0: 1, 1: 0, 2: 3, 3: 2}                # диагональная пара углов
    corner_of = {}
    for k, (ex, ey) in enumerate(CORNERS):
        # ОТОДВИГАЕМСЯ ДАЛЬШЕ, А НЕ РАСШИРЯЕМ ОБЪЕКТИВ (владелец 01.09: «широкий угол
        # обзора, чтоб больше пространства посмотреть»). Больше комнаты в кадре дают два
        # рычага: угол объектива и удаление камеры. Первый за 72° начинает растягивать
        # края (круглый стол становится овальным), второй не искажает ничего — стена
        # перед камерой просто не рисуется. Поэтому охват добираем выносом до 2 м за
        # стену, а объектив держим на пределе без искажений.
        offs = (25.0,) if os.environ.get('INSIDE_CAMS') else (25.0, -60.0, -130.0, -200.0)
        for off in offs:                           # изнутри угла и «сквозь стену» (cutaway)
            sx = -1 if ex > 0 else 1
            sy = -1 if ey > 0 else 1
            px, py = _clamp(ex + sx * off, ey + sy * off)
            for tx, ty in ((cx, cy), (fx, fy)):
                # ДВА ОБЪЕКТИВА НА ВЫБОР (владелец 01.09: «широкий угол обзора, чтоб больше
                # пространства посмотреть»). 72° ≈ 24 мм — предел без заметного искажения краёв;
                # 82° ≈ 20 мм шире и в маленькой комнате показывает существенно больше, ценой
                # растяжения по краям. Раз из комнаты не отойти, выбор между охватом и
                # геометрией делает отбор по баллу, а не константа.
                for fov in (72.0, 82.0):
                    c = cam(f'K{len(cands)}', px, py, tx, ty, fov)
                    corner_of[c.name] = k
                    cands.append(c)
    scored = []
    for c in cands:
        try:
            scored.append((_cam_score(room, placements, c), c))
        except Exception:
            continue
    if not scored:
        off = 25.0
        return [cam('C1', W - off, D - off, off, off, 72.0),
                cam('C2', off, off, W - off, D - off, 72.0)]
    scored.sort(key=lambda z: -z[0]['score'])
    best_s, best = scored[0]
    # ВТОРОЙ КАДР — ИЗ ПРОТИВОПОЛОЖНОГО УГЛА (владелец 01.09: «должно быть 2 точки обзора
    # комнаты по диагонали»). Прежний отбор брал «тот, что добавляет предметов», и лучшими по
    # баллу нередко оказывались два СОСЕДНИХ угла: комната показывалась дважды почти с одной
    # стороны, а противоположная стена не попадала ни в один кадр. Диагональ гарантирует, что
    # две съёмки together покрывают все четыре стены. Внутри диагонального угла по-прежнему
    # выбираем лучший кадр по тому же баллу и приросту предметов.
    want_corner = DIAG.get(corner_of.get(best.name))
    diag = [(sc, c) for sc, c in scored[1:] if corner_of.get(c.name) == want_corner]
    pool = diag or scored[1:]                      # диагонали не нашлось — прежнее поведение
    second, best_gain = None, -1e9
    for sc, c in pool:
        g = (len(sc['seen'] - best_s['seen']) * 1.6 + sc['score'] * 0.4
             - (1.5 if _cam_close(c, best) else 0.0))
        if g > best_gain:
            second, best_gain = c, g
    if not diag:
        print('[cams] диагонального угла среди кандидатов нет — второй кадр выбран по баллу',
              flush=True)
    out = [best, second or scored[-1][1]]
    for i, c in enumerate(out):
        c.name = f'C{i + 1}'
    return out


def _cam_close(a, b) -> bool:
    """Два ракурса из почти одной точки — это один и тот же кадр."""
    return ((a.eye[0] - b.eye[0]) ** 2 + (a.eye[2] - b.eye[2]) ** 2) ** 0.5 < 120


def anchors(room, placements, cam, skus: dict, sc: dict | None = None) -> list:
    """ЯКОРЯ ТОВАРОВ НА КАДРЕ (владелец 26.08: «на фотографиях размещать якоря на мебель»).

    Координаты НЕ спрашиваем у модели: сцену считаем мы, и маска каждого предмета в этом ракурсе
    уже есть (`compile_scene`). Берём точку внутри маски — она и есть место значка, в долях кадра.
    Это дешевле, детерминированно и не врёт: модель могла бы назвать чужие координаты.
    """
    sc = sc or compile_scene(room, placements, cam)
    inst, ids = sc['instances'], sc['ids']
    H, W = inst.shape
    out = []
    for i, role in ids.items():
        m = (inst == i)
        if m.sum() < 20:            # ниже — шум растеризации, предмета в кадре реально нет
            continue
        ys, xs = np.where(m)
        cx, cy = float(xs.mean()), float(ys.mean())
        if not m[int(round(cy)), int(round(cx))]:
            # центр масс вне маски (Г-образный предмет): берём самую «глубокую» точку внутри —
            # центр наибольшей вписанной окружности, чтобы значок не сел на кромку
            try:
                from scipy.ndimage import distance_transform_edt   # noqa: PLC0415
                dt = distance_transform_edt(m)
                cy, cx = [float(v) for v in np.unravel_index(int(np.argmax(dt)), dt.shape)]
            except Exception:
                k = int(np.argmin((xs - cx) ** 2 + (ys - cy) ** 2))
                cx, cy = float(xs[k]), float(ys[k])
        sku = _base_sku(role, skus)
        dep = sc['depth'][m]
        dep = dep[np.isfinite(dep)]
        out.append({'role': role, 'x': round(cx / W, 4), 'y': round(cy / H, 4),
                    'top': round(float(ys.min()) / H, 4), 'cx': round(float(xs.mean()) / W, 4),
                    # для метаданных кадра: глубина от камеры, ширина пятна и обрез рамкой
                    'depth_cm': round(float(dep.mean()), 1) if dep.size else None,
                    'x0': round(float(xs.min()) / W, 4), 'x1': round(float(xs.max()) / W, 4),
                    'bot': round(float(ys.max()) / H, 4), 'area': int(m.sum()),
                    'tiny': bool(m.sum() < 400),         # метка — только выноской
                    'recognizable': bool(m.sum() >= 400),  # хватает пикселей для проверки SKU
                    'cut': bool(xs.min() <= 1 or xs.max() >= W - 2
                                or ys.min() <= 1 or ys.max() >= H - 2),
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
    fp = os.path.join(FRAMES_DIR, name)
    img.save(fp, quality=92)
    push = os.environ.get('FRAME_PUSH')
    if push:  # DEV-рендер для прода: кадр доставляется на сервер, ссылка остаётся прод-URL
        import subprocess as _sp
        _sp.run(['scp', '-q', '-o', 'BatchMode=yes', fp, push], timeout=60, check=False)
    return (PUBLIC_BASE + FRAMES_URL + '/' + name) if PUBLIC_BASE else fp


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


_FONT_CACHE: dict = {}


def _font(size: int):
    """Шрифт С КИРИЛЛИЦЕЙ (27.08, владелец: «подписи передаются некорректно»). В контейнере
    сервиса не было ни одного ttf, PIL брал встроенный битмап без кириллицы, и в модель уходили
    подписи из квадратиков — модель не понимала, что это за предмет. Ищем шире и проверяем, что
    глиф для «А» действительно есть."""
    if size in _FONT_CACHE:
        return _FONT_CACHE[size]
    import glob
    cands = ['/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
             '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf']
    cands += sorted(glob.glob('/usr/share/fonts/**/*.ttf', recursive=True))
    cands += sorted(glob.glob(os.path.join(HERE, 'fonts', '*.ttf')))
    for c in cands:
        try:
            f = ImageFont.truetype(c, size)
            if f.getbbox('А')[2] > 0:          # кириллица в шрифте есть
                _FONT_CACHE[size] = f
                return f
        except Exception:
            continue
    _FONT_CACHE[size] = ImageFont.load_default()
    return _FONT_CACHE[size]


def _label(text: str) -> str:
    """Если кириллического шрифта в системе нет — латиницей, но НИКОГДА квадратиками."""
    f = _font(20)
    try:
        if f.getbbox('А')[2] > 0:
            return text
    except Exception:
        pass
    table = {'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'e', 'ж': 'zh',
             'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm', 'н': 'n', 'о': 'o',
             'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u', 'ф': 'f', 'х': 'h', 'ц': 'c',
             'ч': 'ch', 'ш': 'sh', 'щ': 'sch', 'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu',
             'я': 'ya'}
    out = []
    for ch in text:
        low = ch.lower()
        rep = table.get(low)
        out.append(ch if rep is None else (rep.upper() if ch.isupper() else rep))
    return ''.join(out)


_COLOUR_WORDS = ('белый', 'бежевый', 'серый', 'графит', 'чёрный', 'черный', 'коричневый', 'дуб',
                 'орех', 'венге', 'терракот', 'шоколад', 'молочный', 'кремовый', 'крем', 'синий',
                 'зелёный', 'зеленый', 'оливков', 'голубой', 'песочный', 'сонома', 'вотан',
                 'капучино', 'антрацит', 'латте', 'бургунди', 'розов', 'жёлт', 'желт')
_FRONTED = ('диван', 'кресло', 'стул', 'тв-тумба', 'комод', 'стеллаж', 'витрина', 'банкетка',
            'камин', 'кровать', 'стол')


def _colour_from_name(name: str) -> str | None:
    """Цвет в русских карточках пишут ХВОСТОМ названия («…Рогожка Мальмо шоколад»)."""
    low = (name or '').lower()
    hit = [w for w in _COLOUR_WORDS if w in low]
    if not hit:
        return None
    words = [w for w in (name or '').split()[-3:]
             if '.' not in w and not any(c.isdigit() for c in w)]
    tail = ' '.join(words)
    return tail if any(w in tail.lower() for w in hit) else hit[0]


def _photo_hex(im) -> str | None:
    """Средний цвет товара по его фотографии — без фона. Материал и цвет словами есть не всегда,
    а модель без них красит ткань кожей (урок 05.08); измеренный тон дешевле любых догадок."""
    try:
        import numpy as _np
        a = _np.asarray(im.convert('RGB').resize((64, 64)))
        m = a.sum(axis=2) < 720                      # белый фон карточки отбрасываем
        if m.sum() < 40:
            return None
        r, g, b = (a[..., i][m].mean() for i in range(3))
        return f'#{int(r):02X}{int(g):02X}{int(b):02X}'
    except Exception:
        return None


def _cam_geom(room, cam) -> tuple:
    """Углы комнаты и проёмы В ЭТОМ КАДРЕ — числами (рецепт 05.08, `viz_final.corner_brief`).

    Словесного «не трогай стены» мало: угол уезжал на пятую часть ширины кадра, а модель
    дорисовывала окно там, где стена глухая. Состав проёмов считаем мы, а не модель.
    """
    import math
    eye, fwd, right, up = cam.basis()
    W, H = cam.width, cam.height
    focal = (W / 2) / math.tan(math.radians(cam.fov_deg) / 2)

    def px(pt):
        rel = np.array(pt, float) - eye
        z = float(rel @ fwd)
        if z <= 1e-3:
            return None, None
        return (W / 2 + focal * float(rel @ right) / z,
                H / 2 - focal * float(rel @ up) / z + getattr(cam, 'shift_y', 0.0) * H)

    cor = []
    for x, y in ((0, 0), (room.width_cm, 0), (room.width_cm, room.depth_cm), (0, room.depth_cm)):
        u, _ = px([x, 150.0, y])
        if u is not None and 0 < u < W:
            cor.append(round(u / W * 100))
    cor = sorted(cor)
    if not cor:
        corner = 'no vertical wall corner is visible in this frame'
    elif len(cor) == 1:
        corner = (f'the vertical corner where two walls meet is at {cor[0]}% of the frame width — '
                  'keep it exactly there')
    else:
        corner = (f'there are {len(cor)} vertical wall corners, at '
                  + ', '.join(f'{v}%' for v in cor)
                  + ' of the frame width — keep each of them exactly there')

    found = {'window': [], 'door': []}
    for op in (getattr(room, 'openings', []) or []):
        o0, o1 = op.offset_cm, op.offset_cm + op.width_cm
        ends = {'south': [(o0, 0), (o1, 0)], 'north': [(o0, room.depth_cm), (o1, room.depth_cm)],
                'west': [(0, o0), (0, o1)],
                'east': [(room.width_cm, o0), (room.width_cm, o1)]}[op.wall]
        pts = [px([x, 120, y]) for x, y in ends]
        inside = [q for q in pts if q[0] is not None and 0 <= q[0] < W]
        if not inside:
            continue
        side = 'left-hand' if float(np.mean([q[0] for q in inside])) < W / 2 else 'right-hand'
        found['window' if op.kind == 'window' else 'door'].append(
            (side, len(inside) == 2, int(op.width_cm), int(getattr(op, 'sill_cm', 0) or 90)))

    def phrase(kind, items):
        out = []
        for side, whole, w, sill in items:
            state = ('fully visible' if whole else 'only PARTLY in frame — draw only the part '
                     'that is inside the frame, do not complete it')
            extra = f', sill {sill} cm above the floor, {max(0, 210 - sill)} cm tall' \
                if kind == 'window' else ', 205 cm tall'
            out.append(f'one {kind} on the {side} wall, {w} cm wide{extra}, {state}')
        return '; '.join(out)

    win, door = found['window'], found['door']
    if not win and not door:
        ops = ('There is NO window and NO door in this frame — every wall in view is blank. '
               'Do not put an opening anywhere.')
    elif win and not door:
        ops = (f'The only opening in this frame is {phrase("window", win)}. '
               'There is NO door in this frame.')
    elif door and not win:
        ops = (f'The only opening in this frame is {phrase("door", door)}. '
               'There is NO window in this frame.')
    else:
        ops = (f'Openings in this frame: {phrase("window", win)}; and {phrase("door", door)}. '
               'There are no other openings.')
    return corner, ops


def _room_meta(room, placements) -> dict:
    """Что где стоит: у какой стены, вплотную или с зазором, на чём стоит, с кем рядом
    (владелец 27.08: «все метаданные по товарам тоже надо отправлять и что где стоит за чем»).
    Считаем по нашей геометрии — модель ничего не додумывает."""
    W, D = room.width_cm, room.depth_cm
    by = {}
    for p in placements:
        it = p.item
        w, d = float(it.w_cm), float(it.d_cm)
        if int(round(p.rot)) % 180 == 90:
            w, d = d, w
        x0, x1, y0, y1 = p.x - w / 2, p.x + w / 2, p.y - d / 2, p.y + d / 2
        gaps = {'west': x0, 'east': W - x1, 'north': D - y1, 'south': y0}
        wall, gap = min(gaps.items(), key=lambda kv: kv[1])
        by[p.role] = {'x': round(p.x), 'y': round(p.y), 'rot': int(round(p.rot)) % 360,
                      'box': (x0, x1, y0, y1), 'wall': wall, 'gap': max(0, round(gap)),
                      'elev': float(getattr(p, 'elev_cm', 0) or 0)}
    for role, m in by.items():
        x0, x1, y0, y1 = m['box']
        near = []
        for other, o in by.items():
            if other == role:
                continue
            ox0, ox1, oy0, oy1 = o['box']
            dx = max(ox0 - x1, x0 - ox1, 0)
            dy = max(oy0 - y1, y0 - oy1, 0)
            dist = (dx * dx + dy * dy) ** 0.5
            if dist < 90:
                near.append((round(dist), other))
        m['near'] = [f'{r} ({d} см)' for d, r in sorted(near)[:3]]
        if m['elev'] > 1:
            host = min(((abs(o['x'] - m['x']) + abs(o['y'] - m['y']), r)
                        for r, o in by.items() if r != role and o['elev'] <= 1), default=(0, ''))[1]
            m['on'] = host
    for m in by.values():                       # «коробки» нужны были только для соседства
        m.pop('box', None)
    return by


def _opening_caps(room) -> dict:
    """Подписи проёмов С РАЗМЕРАМИ (владелец 27.08: «у окна подписывай размер всегда», «размер
    двери тоже пиши»). Числа берём те же, что рисует clay: окно от подоконника до 210 см,
    дверь 0–205 см. Разные окна одной комнаты с разной шириной — подписываем без числа."""
    caps = {}
    for kind, key in (('window', 'ОКНО'), ('door', 'ДВЕРЬ')):
        ops = [o for o in (getattr(room, 'openings', []) or []) if getattr(o, 'kind', '') == kind]
        if not ops:
            continue
        wid = {int(getattr(o, 'width_cm', 0) or 0) for o in ops}
        if len(wid) != 1 or not min(wid):
            continue
        w = wid.pop()
        if kind == 'window':
            sill = int(getattr(ops[0], 'sill_cm', 0) or 90)
            caps[key] = f'ОКНО {w}×{max(0, 210 - sill)} см, подоконник {sill} см'
        else:
            caps[key] = f'ДВЕРЬ {w}×205 см'
    return caps


# ЦВЕТ ПРЕДМЕТА — ТОЛЬКО НА СЛУЖЕБНОМ ЛИСТЕ (27.08, идея владельца): полупрозрачная заливка
# каждого предмета своим цветом плюс КРУПНЫЙ номер прямо на нём. Чистый макет остаётся серым,
# иначе цвета протекут в материалы товаров (предупреждение Codex).
MARK_COLOURS = [((230, 25, 75), 'красный'), ((60, 180, 75), 'зелёный'), ((0, 130, 200), 'синий'),
                ((245, 130, 48), 'оранжевый'), ((145, 30, 180), 'фиолетовый'),
                ((0, 158, 158), 'бирюзовый'), ((240, 50, 230), 'розовый'),
                ((160, 160, 20), 'оливковый'), ((170, 110, 40), 'коричневый'),
                ((70, 100, 240), 'васильковый'), ((250, 100, 100), 'коралловый'),
                ((20, 120, 60), 'изумрудный')]


def mark_colour(n: int, role: str = '', photos: dict | None = None) -> tuple:
    """ЦВЕТ МЕТКИ — ЦВЕТ САМОГО ТОВАРА (27.08, владелец: «я предлагал красить цветом самого
    товара, а ты красишь произвольно»). Берём средний тон с фотографии товара: два экземпляра
    одного изделия («стул» и «стул 2») получают ОДИН цвет, а не разные, как было с палитрой.
    Фото нет — падаем на палитру, чтобы предмет всё равно отличался от соседа."""
    im = (photos or {}).get(role) if role else None
    hx = _photo_hex(im) if im is not None else None
    if hx:
        rgb = tuple(int(hx[i:i + 2], 16) for i in (1, 3, 5))
        return rgb, hx
    return MARK_COLOURS[(int(n) - 1) % len(MARK_COLOURS)]


def _footprints(img: Image.Image, room, placements, cam) -> Image.Image:
    """СЛЕД ПРЕДМЕТА НА ПОЛУ (27.08, владелец: «торшер она всё равно переставила»). Мелкий предмет
    занимает десяток пикселей, и модель ставит его «куда логично». Контур следа на полу говорит
    буквально: предмет стоит ВОТ ЗДЕСЬ. Приём наш же — `viz_paste`, работал в треке А."""
    import math
    out = img.copy()
    d = ImageDraw.Draw(out, 'RGBA')
    W, H = out.size
    try:
        from planner.geometry import footprint as _fp
    except Exception:
        return out
    eye, fwd, right, up = cam.basis()
    focal = (cam.width / 2) / math.tan(math.radians(cam.fov_deg) / 2)
    sx, sy = W / cam.width, H / cam.height
    for p in placements:
        if p.item is None or float(getattr(p, 'elev_cm', 0) or 0) > 1.0:
            continue                       # ТВ на стене следа на полу не имеет
        try:
            xs, ys = _fp(p, p.item).exterior.coords.xy
        except Exception:
            continue
        pts, ok = [], True
        for x, y in zip(xs, ys):
            rel = np.array([float(x), 0.0, float(y)]) - eye
            z = float(rel @ fwd)
            if z <= 1e-3:
                ok = False
                break
            pts.append(((cam.width / 2 + focal * float(rel @ right) / z) * sx,
                        (cam.height / 2 - focal * float(rel @ up) / z
                         + getattr(cam, 'shift_y', 0.0) * cam.height) * sy))
        if ok and len(pts) > 2:
            d.line(pts + [pts[0]], fill=(40, 40, 44, 210), width=max(2, W // 480))
    return out


def _marked(img: Image.Image, anchors: list, skus: dict, caps: dict | None = None,
            inst=None, ids: dict | None = None, photos: dict | None = None) -> Image.Image:
    """Служебный лист: заливка предмета своим цветом, КРУПНЫЙ номер на предмете и подпись над ним.

    Владелец 27.08: «крупную цифру жирную по возможности на сам объект и подпись над ней; сноски
    наверх ТОЛЬКО когда идёт перекрытие соседних надписей». Прежняя схема ставила плашку в
    свободное место над предметом и тянула выноску через полкадра — модель читала номер на чужом
    объекте (стеллаж уезжал к окну, стулья к тв-тумбе).
    """
    out = img.copy()
    W, H = out.size
    # 1) ЗАЛИВКА: каждый предмет своим цветом, слабой прозрачностью — форма и тени остаются видны
    if inst is not None and ids:
        import numpy as _np
        base = _np.asarray(out.convert('RGB')).astype(float)
        ih, iw = inst.shape
        big = _np.asarray(Image.fromarray(inst.astype(_np.int32), 'I').resize((W, H), Image.NEAREST))
        for a in anchors:
            i = next((k for k, v in ids.items() if v == a['role']), None)
            if i is None:
                continue
            m = big == i
            if not m.any():
                continue
            rgb, _ = mark_colour(a['n'], a['role'], photos)
            base[m] = base[m] * 0.42 + _np.array(rgb, float) * 0.58
        out = Image.fromarray(base.clip(0, 255).astype('uint8'))
    d = ImageDraw.Draw(out)
    r = max(15, W // 46)
    fc = _font(max(13, int(r * 0.8)))
    boxes: list = []

    def free(px, py, w, h):
        if px < 2 or py < 2 or px + w > W - 2 or py + h > H - 2:
            return False
        for bx0, by0, bx1, by1 in boxes:
            if not (px + w < bx0 - 4 or px > bx1 + 4 or py + h < by0 - 3 or py > by1 + 3):
                return False
        return True

    # ПРОЁМЫ ПОДПИСЫВАЕМ ПЕРВЫМИ и запоминаем их места
    import numpy as _np
    arr = _np.asarray(img.convert('RGB')).astype(int)
    for rgb, cap in (((108, 166, 208), 'ОКНО'), ((176, 136, 84), 'ДВЕРЬ')):
        cap = (caps or {}).get(cap, cap)
        m = ((abs(arr[..., 0] - rgb[0]) < 26) & (abs(arr[..., 1] - rgb[1]) < 26)
             & (abs(arr[..., 2] - rgb[2]) < 26))
        if m.sum() < 400:
            continue
        ys, xs = _np.where(m)
        t = _label(cap)
        bb = d.textbbox((0, 0), t, font=fc)
        w, h = bb[2] - bb[0] + 10, bb[3] - bb[1] + 8
        px = min(max(float(xs.mean()) - w / 2, 2), W - w - 2)
        py = min(max(float(ys.mean()) - h / 2, 2), H - h - 2)
        d.rectangle([px, py, px + w, py + h], fill=(255, 255, 255))
        d.text((px + 5, py + 4), t, fill=(30, 90, 160) if t.startswith(_label('ОКНО'))
               else (150, 90, 40), font=fc)
        boxes.append((px, py, px + w, py + h))

    # 2) НОМЕР И ПОДПИСЬ: сперва мелкие предметы — у них меньше выбора
    for a in sorted(anchors, key=lambda z: z.get('area') or 0):
        ax, ay = a['x'] * W, a['y'] * H
        top = (a.get('top', a['y'])) * H
        ox0, ox1 = (a.get('x0', a['x'])) * W, (a.get('x1', a['x'])) * W
        rgb, _cname = mark_colour(a['n'], a['role'], photos)
        if sum(rgb) > 430:                    # светлый товар: для текста берём тон потемнее
            rgb = tuple(int(v * 0.45) for v in rgb)
        sku = _base_sku(a['role'], skus)
        dim = ''
        if sku.get('w') and sku.get('d'):
            dim = f"{round(sku['w'])}×{round(sku['d'])}" + \
                  (f"×{round(sku['h'])}" if sku.get('h') else '') + ' см'
        l1, l2 = _label(a['role']), _label(dim)
        fnum = _font(max(34, W // 26))      # у всех предметов цифра ОДНОГО размера, средняя жирная
        nb = d.textbbox((0, 0), str(a['n']), font=fnum)
        nw, nh = nb[2] - nb[0], nb[3] - nb[1]
        nx, ny = ax - nw / 2, ay - nh / 2
        boxes.append((nx - 4, ny - 4, nx + nw + 4, ny + nh + 4))   # цифра занимает место сразу
        b1 = d.textbbox((0, 0), l1, font=fc)
        b2_ = d.textbbox((0, 0), l2, font=fc) if l2 else (0, 0, 0, 0)
        lh = (b1[3] - b1[1]) + 6
        cw = max(b1[2] - b1[0], b2_[2] - b2_[0]) + 12
        ch = lh * (2 if l2 else 1) + 8
        cx0, cy0 = ax - cw / 2, ny - ch - 6            # подпись НАД цифрой
        if not free(cx0, cy0, cw, ch):     # 3) ВЫНОСКА ТОЛЬКО ВВЕРХ и только при перекрытии
            spot = None
            px = min(max(ax - cw / 2, 4), W - cw - 4)      # x не меняем: линия строго вертикальная
            py = cy0 - 6
            while py > 4:
                if free(px, py, cw, ch):
                    spot = (px, py)
                    break
                py -= max(8, ch // 2)
            if spot is None:                 # столбец занят целиком — ближайшее свободное выше
                best = None
                for gy in range(4, int(max(6, cy0)), max(10, ch // 2)):
                    for gx in range(4, int(W - cw - 4), max(16, int(cw / 3))):
                        if not free(gx, gy, cw, ch):
                            continue
                        dist = (gx + cw / 2 - ax) ** 2 + (gy + ch / 2 - ay) ** 2
                        if best is None or dist < best[0]:
                            best = (dist, gx, gy)
                spot = (best[1], best[2]) if best else (px, max(4.0, cy0))
            cx0, cy0 = spot
            d.line([ax, cy0 + ch, ax, ny], fill=rgb, width=3)   # выноска — вертикаль вверх
        d.rectangle([cx0, cy0, cx0 + cw, cy0 + ch], fill=(255, 255, 255), outline=rgb, width=2)
        d.text((cx0 + 6, cy0 + 4), l1, fill=rgb, font=fc)
        if l2:
            d.text((cx0 + 6, cy0 + 4 + lh), l2, fill=rgb, font=fc)
        boxes.append((cx0, cy0, cx0 + cw, cy0 + ch))
        # цифра — жирная, с белой обводкой, чтобы читалась на любом фоне
        for ddx, ddy in ((-2, 0), (2, 0), (0, -2), (0, 2), (-2, -2), (2, 2), (-2, 2), (2, -2)):
            d.text((nx + ddx, ny + ddy - nb[1]), str(a['n']), fill=(255, 255, 255), font=fnum)
        d.text((nx, ny - nb[1]), str(a['n']), fill=rgb, font=fnum)

    return out


def _identity(anchors_all: list, photos: dict, skus: dict | None = None) -> Image.Image | None:
    """Лист эталонов: фото КАЖДОГО товара с подписью «#N роль» — по нему модель узнаёт материал."""
    # ОДИН ТОВАР — ОДНА КАРТОЧКА (27.08): «стул» и «стул 2» это комплект из двух штук, показывать
    # его дважды незачем — вместо этого перечисляем оба номера на одной карточке.
    seen, cells, by_sku = set(), [], {}
    for a in anchors_all:
        if a['role'] in seen:
            continue
        seen.add(a['role'])
        key = ((a.get('name') or _base_sku(a['role'], skus or {}).get('name') or '')
               + '|' + _base_role(a['role']))
        if not key.startswith('|') and key in by_sku:
            by_sku[key].append(a['n'])
            continue
        by_sku.setdefault(key, [a['n']])
        # ЛИСТ ЭТАЛОНОВ ПОКРЫВАЕТ ВСЕ ПОЗИЦИИ КАДРА (ADR-0063, опыт «б» 05.08): всё, чего модель
        # не увидела фотографией, она выдумывает по названию. Нет фото — кладём пустую карточку
        # с подписью, чтобы предмет всё равно был назван.
        cells.append([key, _base_role(a['role']), photos.get(a['role']),
                      a.get('name') or _base_sku(a['role'], skus or {}).get('name') or ''])
    if not cells:
        return None
    for c in cells:                       # подставляем список номеров этого товара
        c[0] = by_sku.get(c[0], [0])
    cells.sort(key=lambda c: c[0][0])
    cols = min(3, len(cells))
    rows = (len(cells) + cols - 1) // cols
    cw, ch = 520, 500
    sheet = Image.new('RGB', (cols * cw, rows * ch), (255, 255, 255))
    d = ImageDraw.Draw(sheet)
    f = _font(34)
    fs = _font(24)
    for i, (nums_, role, im, name) in enumerate(cells):
        num = ', '.join('#' + str(n) for n in nums_)
        rgb = mark_colour(nums_[0], role, photos)[0]   # тот же цвет, что у предмета на макете
        if sum(rgb) > 560:
            rgb = tuple(int(v * 0.55) for v in rgb)
        x, y = (i % cols) * cw, (i // cols) * ch
        d.rectangle([x + 6, y + 6, x + cw - 6, y + ch - 6], outline=rgb, width=4)
        if im is not None:
            im = _one_of_set(im.copy(), _set_qty(name))   # «2 шт.» на фото → в эталон одна штука
            im.thumbnail((cw - 40, ch - 120))
            sheet.paste(im, (x + (cw - im.width) // 2, y + 24))
        else:
            d.rectangle([x + 30, y + 30, x + cw - 30, y + ch - 130], outline=(200, 200, 200), width=3)
            d.text((x + cw // 2, y + (ch - 100) // 2), 'фото нет', fill=(150, 150, 150),
                   anchor='mm', font=_font(28))
        sku = _base_sku(role, skus or {})
        dim = (f"{round(sku['w'])}×{round(sku['d'])}" + (f"×{round(sku['h'])}" if sku.get('h') else '') + ' см'
               if sku.get('w') and sku.get('d') else '')
        cap = f'{num} {role}'
        note = 'НА ПОЛ (вид сверху)' if role == 'ковёр' else ''   # иначе модель вешает ковёр на стену
        if len(nums_) > 1:                     # комплект: одно фото, количество — словами
            note = f'в комнате {len(nums_)} шт.'
        def fit(txt, font, limit):
            t = _label(txt)
            while t and d.textlength(t, font=font) > limit:
                t = t[:-1]
            return t
        d.text((x + 20, y + ch - 118), fit(cap, f, cw - 40), fill=rgb, font=f)
        if note:
            d.text((x + 20, y + ch - 78), fit(note, fs, cw - 40), fill=rgb, font=fs)
        d.text((x + 20, y + ch - 44), fit(name[:60] + (' · ' + dim if dim else ''), fs, cw - 40),
               fill=(90, 90, 90), font=fs)
    return sheet


_SET_QTY = re.compile(r'(\d+)\s*шт', re.I)


def _set_qty(name: str) -> int:
    """«Стул АСТИ 2 шт.» → 2. Комплект продаётся коробкой, но в комнате это отдельные предметы."""
    m = _SET_QTY.search(name or '')
    n = int(m.group(1)) if m else 1
    return n if 1 < n <= 8 else 1


def _one_of_set(im: Image.Image, qty: int) -> Image.Image:
    """ОДНА ШТУКА ИЗ КОМПЛЕКТА (27.08, владелец: «на каждом фото по 2 стула — модель думает, что
    стульев 4»). Фото товара «2 шт.» показывает пару; для эталона режем его на предметы по
    белым промежуткам и оставляем ОДИН. Не получилось разделить — отдаём фото как есть."""
    if qty < 2:
        return im
    try:
        import numpy as _np
        a = _np.asarray(im.convert('L'))
        ink = (a < 240).sum(axis=0)
        thr = max(1, int(a.shape[0] * 0.01))
        cols = ink > thr
        segs, st = [], None
        for i, v in enumerate(cols):
            if v and st is None:
                st = i
            elif not v and st is not None:
                if i - st > a.shape[1] * 0.05:
                    segs.append((st, i))
                st = None
        if st is not None and len(cols) - st > a.shape[1] * 0.05:
            segs.append((st, len(cols)))
        if len(segs) < 2:
            return im
        x0, x1 = max(segs, key=lambda s: s[1] - s[0])      # берём самый крупный предмет
        pad = int((x1 - x0) * 0.06)
        rows = _np.where((a < 240).sum(axis=1) > max(1, int(a.shape[1] * 0.01)))[0]
        y0, y1 = (int(rows.min()), int(rows.max()) + 1) if len(rows) else (0, a.shape[0])
        return im.crop((max(0, x0 - pad), max(0, y0 - pad),
                        min(a.shape[1], x1 + pad), min(a.shape[0], y1 + pad)))
    except Exception:
        return im


def _base_role(role: str) -> str:
    """Роль без номера экземпляра: «стул 2» → «стул»; «стол обеденный» остаётся как есть."""
    return re.sub(r'\s+\d+$', '', role or '').strip()


def _base_sku(role: str, skus: dict) -> dict:
    """Товар экземпляра, добитый товаром базовой роли: «стул 2» — вторая штука из комплекта
    «стул», своей карточки у неё нет (name/img/url приходят пустыми) — берём их у базы."""
    inst = skus.get(role) or {}
    base = skus.get(_base_role(role)) or {}
    if not base or base is inst:
        return inst
    out = dict(base)
    out.update({k: v for k, v in inst.items() if v not in (None, '')})
    return out


def _legend(per_cam: list, skus: dict, meta: dict | None = None,
            photos: dict | None = None) -> list:
    """КАРТОЧКА ПРЕДМЕТА ДЛЯ МОДЕЛИ (27.08, владелец: «все метаданные по товарам тоже надо
    отправлять и что где стоит за чем»). Кроме номера и товара идут: измеренные габариты,
    цвет из названия и средний тон, снятый с фотографии товара, координаты и разворот в
    сантиметрах, у какой стены и с каким зазором стоит предмет, на чём он стоит и что рядом,
    и как он виден в каждом кадре — целиком или обрезанным рамкой кадра."""
    merged = {}
    meta = meta or {}
    for idx, anchors in enumerate(per_cam):
        for a in anchors:
            role = a['role']
            sku = _base_sku(role, skus)
            m = meta.get(role) or {}
            it = merged.setdefault(a['n'], {
                'id': a['n'], 'type': role,
                'product': a.get('name') or sku.get('name') or '—',
                'size_cm': None, 'in_view_1': 'absent', 'in_view_2': 'absent'})
            if sku.get('w'):
                it['size_cm'] = f"{round(sku['w'])}x{round(sku.get('d') or 0)}" + \
                                (f"x{round(sku['h'])}" if sku.get('h') else '')
            if 'position_cm' not in it and m:
                ap = {}
                col = _colour_from_name(it['product'])
                if col:
                    ap['colour_name'] = col
                ph = (photos or {}).get(role)
                hx = _photo_hex(ph) if ph is not None else None
                if hx:
                    ap['colour_hex'] = hx
                if ap:
                    it['appearance'] = ap
                it['position_cm'] = [m['x'], m['y']]
                it['rotation_deg'] = m['rot']
                it['stands'] = (f"вплотную к стене ({m['wall']}), зазор {m['gap']} см"
                                if m['gap'] <= 15 else
                                f"в {m['gap']} см от ближайшей стены ({m['wall']})")
                if m.get('on'):
                    it['support'] = f"стоит на предмете «{m['on']}»"
                if m.get('near'):
                    it['next_to'] = m['near']
            it['in_view_1' if idx == 0 else 'in_view_2'] = 'part' if a.get('cut') else 'whole'
            it[f'in_frame_{idx + 1}'] = {'x_pct': round(a['x'] * 100), 'y_pct': round(a['y'] * 100)}
    out, first = [], {}
    for k in sorted(merged):
        it = merged[k]
        key = it['product']
        if key != '—' and key in first:
            it['same_product_as'] = first[key]      # «стул 2» = вторая штука комплекта «стул»
            base = next(x for x in out if x['id'] == first[key])
            base['quantity_in_room'] = base.get('quantity_in_room', 1) + 1
        else:
            first[key] = it['id']
        out.append(it)
    return out


def _chat_edit(images: list, prompt: str, model: str) -> Image.Image:
    """Google-модели картинок живут на шлюзе не в /images/edits, а в /chat/completions: картинки
    уходят частями сообщения, ответ приходит с полем images. Нужно, чтобы сравнивать модели на
    ОДНОМ и том же макете (владелец 27.08: «может, другую модель пробовать»)."""
    import base64
    parts = [{'type': 'text', 'text': prompt}]
    for im in images:
        buf = io.BytesIO()
        im.convert('RGB').save(buf, 'JPEG', quality=92)
        parts.append({'type': 'image_url', 'image_url': {
            'url': 'data:image/jpeg;base64,' + base64.b64encode(buf.getvalue()).decode()}})
    body = {'model': model, 'messages': [{'role': 'user', 'content': parts}],
            'modalities': ['image', 'text']}
    req = urllib.request.Request(CHAT_URL, json.dumps(body).encode(),
                                 {'Authorization': 'Bearer ' + gw_key(),
                                  'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=900) as r:
        j = json.loads(r.read())
    msg = (j.get('choices') or [{}])[0].get('message') or {}
    for im in (msg.get('images') or []):
        u = (im.get('image_url') or {}).get('url', '') if isinstance(im, dict) else ''
        if u.startswith('data:'):
            return Image.open(io.BytesIO(base64.b64decode(u.split(',', 1)[1]))).convert('RGB')
    raise SystemExit(f'шлюз не вернул картинку: {json.dumps(j)[:300]}')


def gpt_edit(images: list, prompt: str, size: str = '1024x1536',
             quality: str = 'medium', model: str = 'openai/gpt-image-2',
             mask: Image.Image | None = None) -> Image.Image:
    """Один запрос в модель картинок через шлюз Vercel: несколько картинок + текст → один лист.

    `mask` — для ЛОКАЛЬНОГО РЕМОНТА (28.08): PNG с альфой, ПРОЗРАЧНОЕ = можно перерисовывать.
    По докам OpenAI маска — отдельное multipart-поле и применяется к ПЕРВОМУ изображению;
    это guidance, не пиксельная гарантия — жёсткую фиксацию вне маски делает код (`viz_repair`)."""
    if not model.startswith('openai/'):
        return _chat_edit(images, prompt, model)
    import uuid
    bnd = '----rl' + uuid.uuid4().hex[:16]
    body = b''

    def part(name: str, val: str) -> bytes:
        return (f'--{bnd}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{val}\r\n').encode()

    body += part('model', model) + part('prompt', prompt) + part('size', size) + part('quality', quality)
    for i, im in enumerate(images):
        buf = io.BytesIO()
        im.convert('RGB').save(buf, 'PNG')     # PNG: JPEG мылит тонкие линии и мелкие цифры
        body += (f'--{bnd}\r\nContent-Disposition: form-data; name="image[]"; '
                 f'filename="i{i}.png"\r\nContent-Type: image/png\r\n\r\n').encode()
        body += buf.getvalue() + b'\r\n'
    if mask is not None:
        mb = io.BytesIO()
        mask.save(mb, 'PNG')                     # обязателен PNG с альфа-каналом
        body += (f'--{bnd}\r\nContent-Disposition: form-data; name="mask"; '
                 f'filename="mask.png"\r\nContent-Type: image/png\r\n\r\n').encode()
        body += mb.getvalue() + b'\r\n'
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


STYLE_HINT = {
    'сканди': 'Scandinavian: light oak floor, white and warm-grey walls, soft daylight, matte '
              'natural textures, minimal decor, one or two live plants',
    'лофт': 'Loft: exposed brick or concrete accent wall, dark metal, aged wood, warm industrial '
            'lighting, no glossy surfaces',
    'минимализм': 'Minimalism: neutral monochrome palette, clean lines, no visible clutter, '
                  'hidden storage, calm even lighting',
    'неоклассика': 'Neoclassic: light wall panelling and mouldings, symmetric composition, warm '
                   'brass details, textile with subtle sheen',
    'джапанди': 'Japandi: pale wood and warm beige, low furniture, natural linen, paper-diffused '
                'light, very restrained decor',
    'современный': 'Contemporary: warm neutral palette, mixed wood and matte black details, '
                   'layered lighting, uncluttered surfaces',
}
# КОРОТКОЕ ОПИСАНИЕ РОЛИ ДЛЯ ЗРЯЧЕЙ МОДЕЛИ (26.08): без него она путала журнальный столик с
# обеденным и стеллаж с тумбой — проверено на кадре «от входа». С описанием попадает.
ROLE_HINT = {
    'диван': 'большой мягкий диван', 'диван 2': 'второй диван', 'кресло': 'кресло',
    'столик': 'низкий журнальный столик перед диваном', 'ковёр': 'ковёр на полу',
    'тв-тумба': 'низкая тумба под телевизором', 'тв': 'телевизор на стене',
    'стеллаж': 'высокий открытый стеллаж/шкаф с полками', 'комод': 'комод',
    'витрина': 'витрина со стеклом', 'торшер': 'напольный светильник на ножке',
    'пуф': 'пуф', 'кашпо': 'растение в горшке', 'стул': 'обеденный стул',
    'стол обеденный': 'обеденный стол', 'банкетка': 'банкетка', 'приставной': 'приставной столик',
}
VISION_MODEL = os.environ.get('VISION_MODEL', 'openai/gpt-4.1-mini')
CHAT_URL = 'https://ai-gateway.vercel.sh/v1/chat/completions'


def refine_anchors(img: Image.Image, an: list, all_skus: dict | None = None) -> list:
    """УТОЧНЯЕМ ЯКОРЯ ПО ГОТОВОМУ КАДРУ (владелец 26.08: «цифры все неверно обозначены»).

    Наши координаты точны для НАШЕЙ сцены, но модель перерисовывает комнату и мелкие предметы
    (торшер, тумба, стеллаж) сдвигает — значок повисал не на том предмете. Поэтому спрашиваем
    зрячую модель, где предмет на ИТОГОВОМ кадре, и берём её точку, только если она недалеко от
    нашей: так уходит грубая ошибка, но не появляется выдумка на пустом месте.
    """
    roles = [a['role'] for a in an if a.get('name')]
    if not roles:
        return an
    extra = [r for r in (all_skus or {}) if r not in roles and (all_skus[r] or {}).get('name')]
    ask = roles + extra          # спрашиваем и про то, чего наша сцена в кадре не видит:
                                 # модель дорисовывает ковёр и мелочь, а якоря им взяться неоткуда
    import base64
    buf = io.BytesIO()
    img.convert('RGB').save(buf, 'JPEG', quality=80)
    b64 = base64.b64encode(buf.getvalue()).decode()
    body = {'model': VISION_MODEL, 'max_tokens': 700, 'messages': [{'role': 'user', 'content': [
        {'type': 'text', 'text': 'Найди на этом фото интерьера предметы: ' + ', '.join(ask) +
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
    def ok(d):
        return (isinstance(d.get('x'), (int, float)) and isinstance(d.get('y'), (int, float))
                and 0 <= float(d['x']) <= 1 and 0 <= float(d['y']) <= 1)
    out = []
    for a in an:
        d = found.get(a['role'])
        b = dict(a)
        if d and ok(d):
            dx, dy = float(d['x']) - a['x'], float(d['y']) - a['y']
            if (dx * dx + dy * dy) ** 0.5 < 0.28:
                b['x'], b['y'] = round(float(d['x']), 4), round(float(d['y']), 4)
                b['refined'] = True
        out.append(b)
    # предмет, которого наша сцена в кадре не видела, а модель нарисовала (частый случай — ковёр)
    have = {a['role'] for a in an}
    n = max([a.get('n') or 0 for a in an] or [0])
    for role in extra:
        d = found.get(role)
        if not d or not ok(d):
            continue
        sku = (all_skus or {}).get(role) or {}
        n += 1
        out.append({'role': role, 'x': round(float(d['x']), 4), 'y': round(float(d['y']), 4),
                    'n': n, 'name': sku.get('name'), 'price': sku.get('price'),
                    'url': sku.get('url'), 'img': sku.get('img'), 'shop': sku.get('shop'),
                    'refined': True, 'added': True})
    return out


def _b64(img, q: int = 78) -> str:
    import base64
    buf = io.BytesIO()
    img.convert('RGB').save(buf, 'JPEG', quality=q)
    return 'data:image/jpeg;base64,' + base64.b64encode(buf.getvalue()).decode()


def _ask(content: list, max_tokens: int = 900) -> str:
    body = {'model': VISION_MODEL, 'max_tokens': max_tokens,
            'messages': [{'role': 'user', 'content': content}]}
    req = urllib.request.Request(CHAT_URL, data=json.dumps(body).encode(),
                                 headers={'Authorization': f'Bearer {gw_key()}',
                                          'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())['choices'][0]['message']['content'] or ''


def refine_pair(pieces: list, per_cam: list, skus: dict, marks: list,
                verify: bool = True, photos_by_role: dict | None = None) -> list:
    """ЯКОРЯ: РАМКА + ПРОВЕРКА ВЫРЕЗКОЙ (26.08, владелец: «надписи не соответствуют на обоих фото»).

    Одной точки мало: модель уверенно называет координату «где-то там», и значок садится на чужой
    предмет. Поэтому два шага. Первый — просим РАМКУ каждого предмета (рамку модель ставит точнее
    точки). Второй — вырезаем эти рамки и спрашиваем по каждой: что на ней? Совпало — значок
    остаётся, не совпало — значка не будет вовсе. Лучше меньше значков, чем неверные.
    """
    names, order = {}, []
    for an in per_cam:
        for a in an:
            if a.get('name') and a['role'] not in names:
                names[a['role']] = a['name']
                order.append(a['role'])
    if not names:
        return per_cam
    listing = '; '.join(f'{r} — {ROLE_HINT.get(r.split(" ")[0], r)}' for r in order)
    content = [{'type': 'text', 'text':
                f'Ниже {len(pieces)} фотографии одной комнаты с разных точек. Предметы: {listing}.\n'
                'Для КАЖДОЙ фотографии верни рамки найденных предметов. Ответ — СТРОГО JSON '
                '{"1":[{"role":"диван","box":[x0,y0,x1,y1]}],"2":[...]}, координаты — доли ширины '
                'и высоты этой фотографии, 0..1. Предмет не виден — пропусти его. Не путай '
                'журнальный столик с обеденным столом и стеллаж с тумбой.'}]
    content += [{'type': 'image_url', 'image_url': {'url': _b64(p)}} for p in pieces]
    def _hide(cams_anchors):
        # НЕ СМОГЛИ ПОДТВЕРДИТЬ — ЗНАЧКА НЕТ (разбор Codex 27.08: раньше при сбое проверки
        # показывались сырые координаты нашей сцены, и значок садился на чужой предмет).
        out = []
        for an in cams_anchors:
            out.append([dict(a, unverified=True) if a.get('name') else dict(a) for a in an])
        return out

    try:
        m = re.search(r'\{.*\}', _ask(content), re.S)
        data = json.loads(m.group(0)) if m else {}
        if not data:
            return _hide(per_cam)
    except Exception:
        return _hide(per_cam)

    # ——— шаг 2: вырезаем предложенные рамки и просим модель назвать, что на каждой
    crops, meta = [], []
    for i, piece in enumerate(pieces, 1):
        for d in (data.get(str(i)) or []):
            b = d.get('box') if isinstance(d, dict) else None
            if not (isinstance(b, list) and len(b) == 4):
                continue
            try:
                x0, y0, x1, y1 = [float(v) for v in b]
            except Exception:
                continue
            if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
                continue
            if (x1 - x0) * (y1 - y0) > 0.75:
                continue
            W, H = piece.size
            pad = 0.02
            box = (int(max(0, x0 - pad) * W), int(max(0, y0 - pad) * H),
                   int(min(1, x1 + pad) * W), int(min(1, y1 + pad) * H))
            crop = piece.crop(box)
            crop.thumbnail((320, 320))
            crops.append(crop)
            meta.append({'view': i, 'role': d.get('role'),
                         'x': round((x0 + x1) / 2, 4), 'y': round((y0 + y1) / 2, 4)})
    ok = set()
    if crops and not verify:
        ok = set(range(len(meta)))
    elif crops:
        # пары «вырезка из кадра + эталонное фото товара»: спрашиваем не класс, а тот ли это товар
        pairs, order_idx = [], []
        for k, c in enumerate(crops):
            ph = photos_by_role.get(meta[k]['role']) if photos_by_role else None
            pairs.append((c, ph))
            order_idx.append(k)
        vc = [{'type': 'text', 'text':
               f'Ниже {len(pairs)} пар изображений. В каждой паре: (1) вырезка из фотографии '
               'интерьера, (2) фотография товара из каталога (если есть). Ответь для каждой пары '
               'одним словом: "да" — на вырезке тот же предмет того же типа, цвета и формы, что на '
               'фотографии товара; "нет" — другой предмет, другой цвет или это вообще не мебель. '
               'Ответ — СТРОГО JSON-массив строк по числу пар, по порядку.'}]
        for c, ph in pairs:
            vc.append({'type': 'image_url', 'image_url': {'url': _b64(c, 70)}})
            if ph is not None:
                vc.append({'type': 'image_url', 'image_url': {'url': _b64(ph, 70)}})
        try:
            m2 = re.search(r'\[.*\]', _ask(vc, 400), re.S)
            said = json.loads(m2.group(0)) if m2 else []
            if not said:
                return _hide(per_cam)
            for k, val in enumerate(said[:len(meta)]):
                if str(val).strip().lower().startswith('да'):
                    ok.add(k)
        except Exception:
            return _hide(per_cam)               # проверка не удалась — значков не показываем
    else:
        return _hide(per_cam)

    out = []
    for i, an in enumerate(per_cam, 1):
        found = {meta[k]['role']: meta[k] for k in ok if meta[k]['view'] == i}
        res, seen, n = [], set(), 0
        for a in an:
            b = dict(a)
            d = found.get(a['role'])
            if d:
                b['x'], b['y'], b['refined'] = d['x'], d['y'], True
                res.append(b)
            elif a.get('name'):
                b['unverified'] = True          # не подтверждено — значка не будет
                res.append(b)
            else:
                res.append(b)
            seen.add(a['role'])
            n = max(n, b.get('n') or 0)
        for role, d in found.items():
            if role in seen:
                continue
            sku = _base_sku(role, skus or {})
            n += 1
            res.append({'role': role, 'x': d['x'], 'y': d['y'], 'n': n, 'name': names.get(role),
                        'price': sku.get('price'), 'url': sku.get('url'), 'img': sku.get('img'),
                        'shop': sku.get('shop'), 'refined': True, 'added': True})
        out.append(res)
    return out


_T0 = [0.0]


def _sheet_gpt(room, placements, photos, cams, prefix: str, side: int, skus: dict,
               model: str, quality: str = 'medium', refine: bool = True,
               style: str = '') -> list:
    _T0[0] = time.time()
    # `refine` оставлен для отладки: якоря уточняются всегда — владелец 26.08 «надо их точнее
    # расставлять» (цифра стула висела на журнальном столике, у ковра якоря не было вовсе)
    """Полный рецепт трека А: коллажи → номера → эталоны → один запрос → разрез по полосе."""
    import hashlib
    parts, marks, diags, per_cam = [], [], [], []
    numbering: dict = {}
    for cam in cams:
        coll, _d, diag = collage(room, placements, cam, photos, paste=False)
        h = max(2, int(round(side * coll.height / coll.width)))
        coll = coll.resize((side, h))
        coll = _footprints(coll, room, placements, cam)
        sc = compile_scene(room, placements, cam)
        an = anchors(room, placements, cam, skus, sc)
        for a in an:                                   # сквозная нумерация по всем видам
            a['n'] = numbering.setdefault(a['role'], len(numbering) + 1)
        parts.append(coll)
        marks.append(_marked(coll, an, skus, _opening_caps(room), sc['instances'], sc['ids'],
                             photos))
        diags.append(diag)
        per_cam.append(an)
    def stack(imgs):
        if len(imgs) == 1:
            return imgs[0]
        total = sum(p.height for p in imgs) + BAND_PX * (len(imgs) - 1)
        sh = Image.new('RGB', (side, total), BAND_RGB)
        y = 0
        for p in imgs:
            sh.paste(p, (0, y))
            y += p.height + BAND_PX
        return sh
    # ДВА ВИДА — ДВА ЗАПРОСА, КОГДА МОДЕЛЬ ТЕРЯЕТ ПОЛОСУ (27.08). У быстрой mini маджента-полоса
    # часто пропадает, разрез уходит наугад, и сверху второго кадра остаётся полоска первого
    # (владелец: «не вижу второго вида»). Для таких моделей считаем каждый ракурс отдельным
    # запросом параллельно — артефакта шва нет, а по времени даже быстрее.
    # ОДИН ВИД — ОДИН ЗАПРОС (27.08, разбор Codex): на общем листе модель решала две перспективы
    # разом, маджента-полоса для неё не граница, а рисунок, и каждый вид получал половину
    # запрошенного разрешения. Раздельные вызовы идут параллельно, по времени не дороже.
    split_calls = len(cams) > 1 and os.environ.get('SPLIT_VIEWS', '1') == '1'
    sheet, sheet_marks = stack(parts), stack(marks)
    sheet.save(prefix + '-sheet.jpg', quality=92)
    sheet_marks.save(prefix + '-marked.jpg', quality=92)
    ident = _identity([a for an in per_cam for a in an], photos, skus)
    if ident is not None:
        ident.save(prefix + '-identity.jpg', quality=92)
    legend = _legend(per_cam, skus, _room_meta(room, placements), photos)
    t_coll = round(time.time() - _T0[0], 1)      # сцена + коллажи + листы
    # ПОЛНЫЙ РЕЦЕПТ ЗАПРОСА (27.08, владелец прислал прежнюю версию промпта): роль «дизайнер и
    # фотограф», комната зафиксирована, состав проёмов и положение углов — числом на кадр,
    # приоритет источников геометрии, метаданные товара и список запрещённых исходов. Короткий
    # промпт модель читала как пожелание и переставляла мебель «покрасивее».
    def frame_brief(k: int, label: str) -> str:
        corner, ops = _cam_geom(room, cams[k])
        # ЧЕГО В КАДРЕ НЕТ — СПИСКОМ (27.08): «absent» в карточке предмета модель читала как
        # необязательное, и дорисовывала диван, стоящий за спиной камеры.
        here = {a['n'] for a in per_cam[k] if a.get('n')}
        gone = sorted({a['n'] for an in per_cam for a in an if a.get('n')} - here)
        miss = (' The following numbered items are NOT in this frame and must not appear in it: '
                + ', '.join('#' + str(n) for n in gone) + '.') if gone else ''
        return f'{label}: {ops} In this frame {corner}.{miss}\n'

    def legend_for(k: int | None) -> list:
        if k is None:
            return legend
        here = {a['n'] for a in per_cam[k] if a.get('n')}
        out = []
        for it in legend:
            if it['id'] not in here:
                continue
            it = dict(it)
            it['visibility'] = it.get(f'in_view_{k + 1}', 'whole')
            for f in ('in_view_1', 'in_view_2'):
                it.pop(f, None)
            out.append(it)
        return out

    def build_full_prompt(two_views: bool, only: int | None = None) -> str:
        deliver = ('two photographs on one sheet: TOP is view 1, BOTTOM is view 2, with the '
                   'magenta band between them kept exactly as in the input (same position, height '
                   'and colour, nothing drawn on it)' if two_views else
                   'ONE photograph of the same proportions as the input, with no second view, no '
                   'split screen and no magenta band')
        if two_views:
            frames = frame_brief(0, 'TOP frame') + frame_brief(1, 'BOTTOM frame')
        else:
            frames = frame_brief(only or 0, 'This frame')
        return (
            'TASK. You are a photographic materialization renderer, not a designer: you turn OUR '
            '3D layout into a photograph. The furniture is already bought and its arrangement is '
            'decided — you may not redesign it. Replace every grey volume by its real product, '
            'renovate the surfaces of the room around them, and deliver '
            f'{deliver}.\n\n'

            'THE ROOM ITSELF IS FIXED. Image 1 is OUR 3D layout and a locked composition and '
            'perspective guide: every piece of furniture is a plain grey volume standing in its '
            'exact place, at its exact size and rotation; dark outlines separate the volumes from '
            'one another and lighter volumes stand closer to the camera than darker ones. The wall '
            'planes and the vertical corners where walls meet stay at the same place and angle, '
            'the ceiling line and the floor line stay at the same height, the room keeps its '
            'proportions and the camera does not move. You repaint and light the room, you do not '
            'rebuild it.\n\n'

            'INPUT IMAGES. Image 1 — OUR CLEAN 3D LAYOUT: the geometry you must follow, grey '
            'volumes without any markup; this is the picture you repaint. Image 2 — the SAME frame '
            'with service markup: a red number on every item plus its type and size in cm, and the '
            'openings captioned ОКНО (window) and ДВЕРЬ (door) with their size; use it only to '
            'learn WHICH number sits on WHICH volume, and never draw any of that markup. Image 3 — '
            'the reference sheet: the real shop photo of every numbered item, labelled with its '
            'number. Some shop photos sit on a branded background or carry a logo or watermark — '
            'read the product itself and ignore the background, the logo and any lettering; never '
            'copy them into the room.\n\n'

            'READ THE ITEM LIST BEFORE YOU DRAW ANYTHING. "mark_tint" is the average colour of '
            'that product, and the volume on image 2 is tinted with exactly it; "product" is the '
            'exact retail name; '
            '"size_cm" is width x depth x height in centimetres, measured; "appearance" carries the '
            'colour from the retail name and "colour_hex", the average tone measured off the shop '
            'photo; "position_cm" and "rotation_deg" are the coordinates of the item on the floor '
            'plan (origin in a room corner, X across the room, Y into the room) and its rotation, '
            'while "in_frame_N" gives where the centre of that object sits IN FRAME N as percent '
            'of the frame width and height — check your drawing against those percentages; '
            '"stands", "support" and "next_to" say against which wall the item stands and with what '
            'gap, what it stands on, and what stands next to it; "in_view_1" and "in_view_2" say '
            'how the item appears in each frame: whole = draw it fully, part = it is cut by the '
            'edge of the frame, draw only the visible part and never complete it, absent = it is '
            'not in that frame. Scale every item to its own size_cm relative to the room and to the '
            'other items. Mismatched material, colour or scale is a defect.\n\n'

            'GEOMETRY PRIORITY (highest first): the grey volume in image 1 → the item list '
            '(size_cm, position_cm, rotation_deg, stands, next_to) → the shop photo. If they '
            'disagree, the higher source wins.\n\n'

            'FOOTPRINTS. On image 1 a thin dark outline is drawn on the floor around the base of '
            'every object that stands on the floor. The product must fill exactly that outline — '
            'same position, same footprint, same rotation. Never draw the outlines themselves.\n\n'

            'GREY VOLUMES. A grey block is a placeholder: its size, place and rotation are exact, '
            'its surface is not. Draw the real product from image 3 and the item list standing '
            'exactly on that volume — same footprint, same rotation, same distance to the walls '
            'and to its neighbours. The shop photo shows the product from a catalogue angle: do '
            'not copy that angle, turn the product to match the volume.\n\n'

            'IMMUTABLE. Products: no replacing, recolouring, restyling, resizing, moving, rotating '
            'or duplicating; the layout is a strict blueprint, not an inspiration, and an '
            'arrangement that looks unusual is intentional. Room shell: walls, floor, ceiling and '
            'camera stay as they are. Openings: exactly as listed here — never invent, move, add '
            'or remove a window or a door.\n' + frames + '\n'

            'ALLOWED EDITS. Renovate the room in the style below: wall finish and colour, '
            'flooring, ceiling, skirting, frames and dressing of the given openings. Natural '
            'daylight, soft contact shadows, correct wall-to-floor junctions, vertical lines '
            'vertical' + (', lighting and materials identical in both frames' if two_views else '')
            + '. Wall colour and finish, floor material and tone, ceiling and skirting are yours '
            'to choose in the style below; curtains or blinds on the given windows and framed wall '
            'art are welcome when they match that style and the colours of the walls and the floor. '
            'No tabletop, shelf, floor or freestanding decor of your own. Every planter and vase '
            'from the list must hold a live plant sized to it.\n\n'

            'ITEM RULES.\n'
            '- A RUG (ковёр) is photographed from above: render it LYING FLAT ON THE FLOOR with '
            'exactly that pattern and colours. Never hang a rug, carpet, textile or any reference '
            'image on a wall, and never invent a second rug.\n'
            '- Some numbers share ONE product (a set of two chairs, for example): such an item has '
            '"same_product_as": N in the list, the base item says "quantity_in_room": N, and the '
            'reference sheet holds ONE card captioned with all its numbers. Draw exactly ONE piece '
            'per number — that many pieces in total, never a pair per number.\n'
            '- An item marked "фото нет" on the reference sheet has no photo: render a plain, '
            'neutral piece of exactly that type and size.\n'
            '- In the layout a blue rectangle on a wall is a WINDOW (render real glass, a frame '
            'and daylight outside, never a blue panel or a picture); a brown rectangle is a DOOR.\n'
            + (tv_note or '') + all_note_for(None if two_views else (only or 0)) + '\n'
            + (f'STYLE — {style}: {STYLE_HINT.get(style, "")} It sets finishes, colour, light and '
               'mood only; it never adds or removes objects.\n\n' if style else '')

            + 'ITEMS (JSON; id = the number drawn on the object in image 2; every item on this '
            'list is in '
            'this frame and no other item exists):\n'
            + json.dumps(legend_for(None if two_views else (only or 0)), ensure_ascii=False)
            + '\n\n'

            'INVALID OUTPUT — redo if any of this happens: an item stands anywhere other than on '
            'its grey volume, or is bigger or smaller than it; an item is replaced, recoloured, '
            'restyled or rotated; an object that is not in the list appears; an item shows up in '
            'the wrong frame; a window or a door appears where the list says there is none; the '
            'room shell, the wall corners or the camera move; '
            + ('the magenta band is missing, moved or painted over; ' if two_views else '')
            + 'red numbers, captions or any markup are drawn in the photograph.')

    # ТЕЛЕВИЗОР РИСУЕТ МОДЕЛЬ — ПО ТУМБЕ (владелец 27.08: «где должен быть телевизор в зависимости
    # от тв-тумбы, пусть ИИ рисует»). Своего объекта «тв» в расстановке нет: вешаем экран над
    # тумбой, размер — по её ширине.
    tv_note = ''
    tv_num = next((a['n'] for an in per_cam for a in an
                   if a['role'].split(' ')[0] == 'тв-тумба' and a.get('n')), None)
    if tv_num:
        tv_w = int((skus.get('тв-тумба') or {}).get('w') or 0)
        size_hint = f'about {max(90, int(tv_w * 0.85))} cm wide' if tv_w else 'wall-sized to the console'
        tv_note = (f'- Object of type «тв» is the TELEVISION: a modern flat TV hanging on the '
                   f'wall right above console #{tv_num}, {size_hint}, screen off (dark matte). It '
                   'has no product photo on the reference sheet — draw a plain modern TV of that '
                   'size in exactly the place its volume occupies, and nowhere else.\n')
    # ВСЕ ПРОНУМЕРОВАННЫЕ ПРЕДМЕТЫ ОБЯЗАНЫ БЫТЬ В КАДРЕ (27.08): модель роняла диван на одном из
    # видов, и кадр приходил «пустым» по составу.
    def all_note_for(k: int | None) -> str:
        src = per_cam if k is None else [per_cam[k]]
        ns = sorted({a['n'] for an in src for a in an if a.get('n')})
        note = (f'- The photo must contain ALL numbered objects of this frame: '
                f'{", ".join("#" + str(n) for n in ns)}. Do not omit any of them, and draw nothing '
                'else.\n' if ns else '')
        if k is not None:
            # ПОРЯДОК СЛЕВА НАПРАВО И ПО ГЛУБИНЕ — то, что модель может сверить глазами: мировые
            # сантиметры она игнорирует, а «стоит третьим слева» проверяется прямо по картинке.
            lr = sorted(per_cam[k], key=lambda a: a['x'])
            nf = sorted([a for a in per_cam[k] if a.get('depth_cm')], key=lambda a: a['depth_cm'])
            note += ('- Left to right in this frame the objects stand in this order: '
                     + ', '.join(f"#{a['n']} ({a['role']}, centre at {round(a['x'] * 100)}% of the "
                                 f"frame width)" for a in lr) + '.\n')
            if nf:
                note += ('- From nearest to the camera to farthest: '
                         + ', '.join('#' + str(a['n']) for a in nf) + '.\n')
        return note
    two = len(cams) > 1
    prompt = build_full_prompt(two and not split_calls)
    imgs = [sheet, sheet_marks] + ([ident] if ident is not None else [])
    w, h = sheet.size
    size = '1024x1536' if h > w else '1536x1024'
    stamp = hashlib.md5((prefix + str(time.time())).encode()).hexdigest()[:10]
    src_imgs = {}
    for i, (cl, mk) in enumerate(zip(parts, marks), start=1):
        src_imgs[f'{i}-вид-{i}-макет-чистый'] = cl
        src_imgs[f'{i}-вид-{i}-макет-с-номерами'] = mk
    src_imgs['9-эталоны-товаров'] = ident
    src_url = _publish_sources(stamp, src_imgs, prompt, legend,
                               {'модель': model, 'размер': size, 'качество': quality,
                                'видов': len(cams), 'стиль': style or '—'})
    _t = time.time()
    if split_calls:
        from concurrent.futures import ThreadPoolExecutor
        def one(k):
            sub = [parts[k], marks[k]] + ([ident] if ident is not None else [])
            w2, h2 = parts[k].size
            return gpt_edit(sub, build_full_prompt(False, k),
                            size=('1024x1536' if h2 > w2 else '1536x1024'),
                            quality=quality, model=model.split('gateway:')[-1])
        with ThreadPoolExecutor(max_workers=len(parts)) as ex:
            outs = list(ex.map(one, range(len(parts))))
        out = outs[0]
    else:
        out = gpt_edit(imgs, prompt, size=size, quality=quality, model=model.split('gateway:')[-1])
    t_model = round(time.time() - _t, 1)
    out.save(prefix + '-final.jpg', quality=94)
    pieces = outs if split_calls else (_split_pair(out) if len(cams) > 1 else [out])
    # УТОЧНЕНИЕ ЯКОРЕЙ ПО ОБОИМ КАДРАМ ПАРАЛЛЕЛЬНО: два последовательных зрячих вызова добавляли
    # к черновику ~8 с, параллельно — вдвое меньше.
    prepared = []
    for cam, piece, diag, an in zip(cams, pieces, diags, per_cam):
        piece = _trim_band(piece)
        piece.save(f'{prefix}-{cam.name}.jpg', quality=92)
        prepared.append((cam, piece, diag, an))
    # ЗНАЧКОВ НА ФОТО БОЛЬШЕ НЕТ (владелец 27.08: «убери значки все с фото, просто ленту с
    # товарами внизу»), поэтому и зрячая проверка координат не нужна — это снимает с черновика
    # самый дорогой шаг после самой генерации (6–17 с). Список товаров кадра остаётся: он берётся
    # из состава сцены, а не из координат. Вернуть значки — `ANCHORS=1`.
    _t = time.time()
    if os.environ.get('ANCHORS', '0') == '1':
        refined = refine_pair([t[1] for t in prepared], [t[3] for t in prepared], skus,
                              [sheet_marks], verify=True, photos_by_role=photos)
    else:
        refined = [[dict(a, unverified=True) for a in t[3]] for t in prepared]
    t_vis = round(time.time() - _t, 1)
    shots = []
    timing = {'сцена и коллажи': t_coll, 'генерация кадра': t_model, 'проверка значков': t_vis,
              'публикация': round(time.time() - _T0[0] - t_coll - t_model - t_vis, 1)}
    for (cam, piece, diag, _an), an2 in zip(prepared, refined):
        shots.append({'camera': cam.name, 'url': _publish_frame(piece, f'{stamp}-{cam.name}.jpg'),
                      'diag': diag, 'sources': src_url, 'anchors': an2, 'timing': timing})
    print('  время: ' + ', '.join(f'{k} {v} с' for k, v in timing.items()))
    return shots


SCENE3D_CACHE = '/tmp/mesh3d-cache'


def _scene3d_orient() -> dict:
    """Карта sid → канонический yaw (фронт), собранная пилотом (orient.json галереи)."""
    import urllib.request
    global _S3_ORIENT
    try:
        return _S3_ORIENT
    except NameError:
        pass
    base = os.environ.get('MESH_HTTP', 'https://remont-lab.online/test/mesh-pilot10')
    try:
        _S3_ORIENT = json.loads(urllib.request.urlopen(base + '/orient.json', timeout=20).read())
    except Exception:  # noqa: BLE001
        _S3_ORIENT = {}
    return _S3_ORIENT


def _scene3d_glb(sid: str) -> str | None:
    """GLB меша по sid: скачивается с нашей галереи в кэш (контейнер draft без томов мешей)."""
    import urllib.request
    os.makedirs(SCENE3D_CACHE, exist_ok=True)
    dst = os.path.join(SCENE3D_CACHE, sid + '.glb')
    if os.path.exists(dst) and os.path.getsize(dst) > 1000:
        return dst
    base = os.environ.get('MESH_HTTP', 'https://remont-lab.online/test/mesh-pilot10')
    try:
        data = urllib.request.urlopen(f'{base}/{sid}/model.glb', timeout=60).read()
        open(dst, 'wb').write(data)
        return dst
    except Exception:  # noqa: BLE001
        return None


_S3_PARTS: dict = {}


def _scene3d_parts(glb: str):
    """Кэш РАЗОБРАННЫХ мешей в памяти сервиса: декод GLB на каждый клик съедал секунды."""
    import mesh_render as MR
    hit = _S3_PARTS.get(glb)
    if hit is not None:
        return hit
    parts = MR.load_parts(glb)
    # SCENE3D_QUALITY=full — БЕЗ декимации, с полными текстурами (владелец 31.08: кадр
    # должен быть качественным для человека и GPT — «дырки»/цвет не должны читаться как
    # свойства товара); по умолчанию — декимация под 2 слабых ядра прода
    if os.environ.get('SCENE3D_QUALITY') == 'full':
        _S3_PARTS[glb] = parts
        return parts
    try:
        import fast_simplification as _fs
        import numpy as _n
        slim = []
        for m in parts:
            f = _n.asarray(m.faces)
            if len(f) > 12000:
                target = 9000 / len(f)
                pts, fcs, coll = _fs.simplify(_n.asarray(m.vertices, _n.float32), f.astype(_n.int32),
                                              target_reduction=1 - target, return_collapses=True)
                import trimesh as _t
                m2 = _t.Trimesh(vertices=pts, faces=fcs, process=False)
                try:
                    # цвет вершин — от БЛИЖАЙШЕЙ исходной вершины (KD-tree): грубее
                    # текстуры, но без грязи кривых UV; в кадре сцены неотличимо
                    from scipy.spatial import cKDTree
                    import mesh_render as _MR2
                    tex, uvm = _MR2.texture_of(m)
                    V0 = _n.asarray(m.vertices, _n.float32)
                    if tex is not None and uvm is not None:
                        th_, tw_ = tex.shape[:2]
                        tx = _n.clip((uvm[:, 0] % 1.0) * (tw_ - 1), 0, tw_ - 1).astype(int)
                        ty = _n.clip((1.0 - (uvm[:, 1] % 1.0)) * (th_ - 1), 0, th_ - 1).astype(int)
                        vcol = tex[ty, tx]
                    else:
                        vcol = _n.tile(_MR2.flat_colors(m).mean(axis=0), (len(V0), 1))
                    idx = cKDTree(V0).query(pts, k=1)[1]
                    rgba = _n.c_[vcol[idx], _n.full(len(pts), 255)].astype(_n.uint8)
                    m2.visual = _t.visual.color.ColorVisuals(mesh=m2, vertex_colors=rgba)
                except Exception:  # noqa: BLE001 — цвет не перенёсся: серый, но кадр живёт
                    pass
                slim.append(m2)
            else:
                slim.append(m)
        parts = slim
    except Exception:  # noqa: BLE001 — нет декиматора: рендерим полный меш
        pass
    if len(_S3_PARTS) > 60:
        _S3_PARTS.clear()
    _S3_PARTS[glb] = parts
    return parts


def _paste_rug(canvas, zbuf, place, cam, W, H, ph) -> bool:
    """КОВЁР — ФОТО НА ПОЛУ (владелец 31.08: «ковры просто вклеиваем, они сняты сверху»):
    прямоугольник ковра проецируется в кадр, фото натягивается перспективно, глубина пола
    пишется в z-буфер — мебель поверх перекрывает ковёр честно."""
    import math
    import scene_mesh as SM
    if ph is None:
        return False
    # маска ковра — АДАПТИВНО по цвету углов фото (владелец 31.08: кремовый фон карточки
    # оставался «вторым ковриком» вокруг настоящего при белом пороге)
    src = np.asarray(ph.convert('RGB'), np.float32)
    sh, sw = src.shape[:2]
    corn = np.concatenate([src[:6, :6].reshape(-1, 3), src[:6, -6:].reshape(-1, 3),
                           src[-6:, :6].reshape(-1, 3), src[-6:, -6:].reshape(-1, 3)])
    bg = np.median(corn, axis=0)
    dist = np.linalg.norm(src - bg, axis=2)
    msk = (dist > 22).astype(np.uint8) * 255
    from scipy import ndimage as _ndi
    msk = (_ndi.binary_closing(msk > 0, iterations=3)).astype(np.uint8) * 255
    lab, n = _ndi.label(msk > 0)
    if n:
        sizes = np.bincount(lab.ravel())[1:]
        msk = ((lab == (int(np.argmax(sizes)) + 1)) * 255).astype(np.uint8)
        msk = (_ndi.binary_fill_holes(msk > 0)).astype(np.uint8) * 255
    cover = float((msk > 128).mean())
    if cover < 0.30:                           # маска подозрительно мала — берём всё фото
        msk = np.full(msk.shape, 255, np.uint8)
    # СИСТЕМНО ДЛЯ ВСЕХ КОВРОВ (владелец 31.08, «ковёр опять с косяком»): на габарит
    # натягиваем ПРЯМОУГОЛЬНИК САМОГО КОВРА (bbox маски), а не всё фото — белые поля
    # карточки смещали узор и давали белёсые рваные края; ориентации не совпали
    # (портрет/альбом) — поворот текстуры на 90°
    ys_, xs_ = np.where(msk > 128)
    bx0, bx1 = (int(xs_.min()), int(xs_.max())) if len(xs_) else (0, sw - 1)
    by0, by1 = (int(ys_.min()), int(ys_.max())) if len(ys_) else (0, sh - 1)
    bw_, bh_ = bx1 - bx0 + 1, by1 - by0 + 1
    it = place.item
    hw, hd = float(it.w_cm) / 2, float(it.d_cm) / 2
    a = math.radians(float(place.rot or 0))
    ca, sa = math.cos(a), math.sin(a)
    corners = []
    for dx, dz, u, v in ((-hw, -hd, 0, 0), (hw, -hd, 1, 0), (hw, hd, 1, 1), (-hw, hd, 0, 1)):
        wx = place.x + dx * ca + dz * sa
        wz = place.y - dx * sa + dz * ca
        corners.append((wx, 1.0, wz, u, v))
    pts = SM.project_pts(cam, [(c[0], c[1], c[2]) for c in corners], W, H)
    if pts is None:
        return False
    P = [(float(p[0]), float(p[1])) for p in pts]
    # ГОМОГРАФИЯ экран→(u,v): два аффинных треугольника ломали перспективу по диагонали —
    # шахматный узор шёл «бугром» (владелец 31.08); проективное натяжение излом убирает
    A, B = [], []
    for (x, y), (u, v) in zip(P, ((0, 0), (1, 0), (1, 1), (0, 1))):
        A.append([x, y, 1, 0, 0, 0, -u * x, -u * y]); B.append(u)
        A.append([0, 0, 0, x, y, 1, -v * x, -v * y]); B.append(v)
    try:
        hcf = np.linalg.solve(np.array(A, np.float64), np.array(B, np.float64))
    except np.linalg.LinAlgError:
        return False
    x0 = int(max(0, min(p[0] for p in P))); x1 = int(min(W - 1, max(p[0] for p in P)) + 1)
    y0 = int(max(0, min(p[1] for p in P))); y1 = int(min(H - 1, max(p[1] for p in P)) + 1)
    if x1 <= x0 or y1 <= y0:
        return False
    gy, gx = np.mgrid[y0:y1, x0:x1]
    den = hcf[6] * gx + hcf[7] * gy + 1.0
    den[np.abs(den) < 1e-9] = 1e-9
    uu = (hcf[0] * gx + hcf[1] * gy + hcf[2]) / den
    vv = (hcf[3] * gx + hcf[4] * gy + hcf[5]) / den
    inside = (uu >= -0.002) & (uu <= 1.002) & (vv >= -0.002) & (vv <= 1.002)
    if not inside.any():
        return False
    # честная глубина плоскости ковра в точке (u,v)
    eye, fwd, _, _ = cam.basis()
    C = np.array([[c[0], c[1], c[2]] for c in corners], np.float32)
    Pw = (C[0][None, None, :] + uu[..., None] * (C[1] - C[0])[None, None, :]
          + vv[..., None] * (C[3] - C[0])[None, None, :])
    zt = ((Pw - np.array(eye, np.float32)) @ np.array(fwd, np.float32)).astype(np.float32)
    sub = zbuf[y0:y1, x0:x1]
    # КОВЁР — НАЛОЖЕНИЕ НА СЛОЙ ПОЛА (владелец 31.08): закрашиваем ТОЛЬКО полосу пола.
    # Глубина clay-пола систематически смещена от честного луча (разные растеризаторы) —
    # сдвиг калибруем медианой по пикселям ковра, а не фиксированным допуском: прежний
    # допуск +25 см закрашивал низ мебели, и ковёр «шёл бугром» на кресле
    fin = inside & np.isfinite(sub) & (np.abs(zt - sub) < 45.0)
    shift = float(np.median((zt - sub)[fin])) if fin.sum() > 200 else 18.0
    ztc = zt - shift
    rot90 = (bw_ >= bh_) != (float(it.w_cm) >= float(it.d_cm))
    ua, va = (vv, 1.0 - uu) if rot90 else (uu, vv)
    tx = np.clip(bx0 + ua * (bw_ - 1), 0, sw - 1).astype(int)
    ty = np.clip(by0 + va * (bh_ - 1), 0, sh - 1).astype(int)
    upd = inside & (sub > ztc - 8.0) & (msk[ty, tx] > 128)
    if not upd.any():
        return False
    sub[upd] = ztc[upd] - 0.1                  # глубина пола: мебель и меши лягут поверх
    canvas[y0:y1, x0:x1][upd] = src[ty, tx][upd]
    return True


_S3_JOB = None


def _s3_cam_job(i):
    """Воркер fork-пула scene3d: рендер одной камеры из унаследованного _S3_JOB."""
    import io as _io
    room, placements, want, sid_by_role, photos = _S3_JOB
    img, diag = scene3d_frame(room, placements, want[i], sid_by_role, photos)
    buf = _io.BytesIO(); img.save(buf, format='JPEG', quality=92)
    return want[i].name, buf.getvalue(), diag


def _push_from_supports(mesh_places, others, room):
    """СТУЛ НЕ ВРЕЗАЕТСЯ В НОЖКИ СТОЛА (владелец 31.08 «ножки протыкают абстрактный стул»;
    разбор с Codex: НЕ общий 2D-pushout — под столешницу заезжать можно, в ОПОРЫ нельзя).
    Маска опор: вершины меша стола ниже 55 см → 2D-сетка 2 см с дилатацией; тело стула
    в занятых клетках → стул отъезжает от центра стола шагами 2 см (максимум 20 см).
    Двигается КОПИЯ позы для кадра — план пользователя не меняется; сдвиг пишется в diag."""
    import math
    import scene_mesh as SM
    from planner.models import Placement as _P
    notes = []
    tables = [(pl, glb) for pl, _sid, glb in mesh_places
              if pl.role.split(' ')[0] in ('стол', 'столик')]
    for tpl, glb in tables:
        try:
            parts = _scene3d_parts(glb)
            out, *_rest = SM.world_vertices(parts, tpl, 0.0)
            import numpy as _n
            allv = _n.vstack(out)
            low = allv[allv[:, 1] < 55.0]
            if not len(low):
                continue
            cell = 2.0
            occ = set()
            for x, z in zip(low[:, 0], low[:, 2]):
                cx, cz = int(x // cell), int(z // cell)
                for dx in (-1, 0, 1):
                    for dz in (-1, 0, 1):
                        occ.add((cx + dx, cz + dz))
        except Exception:  # noqa: BLE001 — нет маски, значит не разводим
            continue

        def _hits(pl) -> bool:
            it = pl.item
            hw, hd = float(it.w_cm) / 2, float(it.d_cm) / 2
            a = math.radians(float(pl.rot or 0)); ca, sa = math.cos(a), math.sin(a)
            for gx in range(-3, 4):
                for gz in range(-3, 4):
                    dx, dz = hw * gx / 3.0, hd * gz / 3.0
                    wx = pl.x + dx * ca + dz * sa
                    wz = pl.y - dx * sa + dz * ca
                    if (int(wx // 2.0), int(wz // 2.0)) in occ:
                        return True
            return False
        for i, entry in enumerate(others):
            pl = entry[0]
            if pl.role.split(' ')[0] not in ('стул', 'кресло', 'табурет') or pl is tpl:
                continue
            if not _hits(pl):
                continue
            vx, vz = pl.x - tpl.x, pl.y - tpl.y
            L = math.hypot(vx, vz) or 1.0
            vx, vz = vx / L, vz / L
            moved = 0.0
            cand = pl
            while moved < 20.0 and _hits(cand):
                moved += cell
                cand = _P(role=pl.role, x=pl.x + vx * moved, y=pl.y + vz * moved,
                          rot=pl.rot, item=pl.item,
                          elev_cm=getattr(pl, 'elev_cm', 0) or 0)
            if moved and not _hits(cand):
                others[i] = (cand,) + tuple(entry[1:])
                notes.append(f'{pl.role}: отодвинут на {moved:.0f} см от ножек ({tpl.role})')
            elif moved:
                notes.append(f'{pl.role}: коллизия с опорами ({tpl.role}) не разведена за 20 см')
    return notes


def scene3d_frame(room, placements, cam, sid_by_role: dict, photos_by_role: dict | None = None) -> tuple[Image.Image, dict]:
    """КАДР СЦЕНЫ ИЗ МЕШЕЙ (владелец 31.08: «по кнопке — фотография собранной 3D-сцены,
    в GPT пока не отправляем»): clay-комната + реальные меши в перспективе, общий z-буфер
    (правильные перекрытия). Нет меша — предмет остаётся clay-формой."""
    import mesh_render as MR
    import scene_mesh as SM
    # предмет либо МОДЕЛЬЮ, либо clay-формой — не оба (владелец 31.08: «если ставишь
    # реальную модель, абстрактную убирай»): сначала выясняем, у кого есть меш, и строим
    # clay-сцену БЕЗ них; глубины обеих половин делят один z-буфер — перекрытия честные
    orient = _scene3d_orient()
    mesh_places, clay_places = [], []
    try:
        import asset_strategy as AS
    except Exception:  # noqa: BLE001
        AS = None
    rug_places = []
    for place in placements:
        sid = sid_by_role.get(place.role)
        base = place.role.split(' ')[0]
        if base == 'ковёр':
            rug_places.append(place)           # фото на пол, не clay и не меш
            continue
        # канон стратегий: не-hunyuan НЕ ставятся мешом; нет файла канона (контейнер!) —
        # жёсткий фолбэк по ролям, чтобы ковёр НИКОГДА не оказался мешом
        if sid and ((AS is not None and AS.strategy(base) != 'hunyuan3d')
                    or base in ('картина', 'зеркало', 'плед', 'шторы')):
            sid = None
        glb = _scene3d_glb(sid) if sid else None
        (mesh_places if glb else clay_places).append((place, sid, glb))
    coll_notes = _push_from_supports(mesh_places, clay_places, room)
    coll_notes += _push_from_supports(mesh_places, mesh_places, room)
    sc = compile_scene(room, [p for p, _, _ in clay_places], cam)
    depth = sc['depth']
    H, W = depth.shape
    canvas = np.asarray(clay_render(sc)).astype(np.float32).copy()
    zbuf = depth.astype(np.float32).copy()
    zbuf[~np.isfinite(zbuf)] = 1e9
    used, missing = [], [p.role for p, _, _ in clay_places]
    for place in rug_places:
        ph = photos_by_role.get(place.role) if photos_by_role else None
        if _paste_rug(canvas, zbuf, place, cam, W, H, ph):
            used.append(place.role + ' (фото-ковёр)')
        else:
            missing.append(place.role)
    for place, sid, glb in mesh_places:
        try:
            parts = _scene3d_parts(glb)
            oinfo = orient.get(sid) or {}
            osrc = str(oinfo.get('orient') or '')
            # ПРАВИЛО ДЛЯ ВСЕХ МОДЕЛЕЙ (владелец 31.08): канонический разворот применяем
            # ТОЛЬКО при уверенном фронте; симметричным и спорным — 0 (стол «вставал криво»
            # от ненужного разворота симметрика)
            sure = any(k in osrc for k in ('seat_agree', 'vlm_agree', 'cabinet_', 'confident',
                                           'human'))
            yaw = float(oinfo.get('yaw') or 0) if sure else 0.0
            # КОНВЕНЦИЯ ПЛАННЕРА И ДЕМО (сверено по geometry.footprint и SVG демо 31.08):
            # (x,y) — ЦЕНТР предмета; знак rot — ПЛЮС (сверено с планом владельца 31.08:
            # кресло rot=315 сиденьем к тв-тумбе; scene_mesh сам согласован с −rot планнера).
            # Прежний «центр-фикс» +w/2,+d/2 был ошибкой и смещал меши от clay.
            from planner.models import Placement as _P
            pc = _P(role=place.role, x=place.x, y=place.y, rot=float(place.rot or 0),
                    item=place.item, elev_cm=getattr(place, 'elev_cm', 0) or 0)
            SM.raster_mesh(canvas, zbuf, parts, pc, cam, W, H, yaw)
            used.append(place.role)
        except Exception as e:  # noqa: BLE001 — один битый меш не валит кадр
            print(f'  scene3d: {place.role} пропущен ({str(e)[:60]})')
            missing.append(place.role)
    img = Image.fromarray(np.clip(canvas, 0, 255).astype(np.uint8), 'RGB')
    diag = {'мешей': used, 'clay': missing}
    if coll_notes:
        diag['развод коллизий'] = coll_notes
    return img, diag


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
    all_cams = demo_cams(room, placements) if os.environ.get('DEMO_CAMS', '1') != '0' \
        else cameras_for(room, placements)
    # ЧЕРНОВИК ДОЛЖЕН БЫТЬ БЫСТРЫМ (владелец 26.08: «уже 40 сек жду»): один ракурс вместо двух,
    # меньший лист и без уточнения якорей зрячей моделью — это ещё +8 с. Реалистичный режим
    # остаётся полным: два вида одним листом и уточнённые якоря.
    if quality == 'realistic':
        want = [c for c in all_cams if c.name in ('C1', 'C2')] or all_cams[:2]
        model, side, gq = REALISTIC_MODEL, 1536, os.environ.get('GPT_IMAGE_QUALITY', 'medium')
    else:
        # ДВА ВИДА И В ЧЕРНОВИКЕ (владелец 26.08: «мы же генерируем одну фотографию и режем на два
        # вида — где у тебя два вида?»). Скорость держим не числом ракурсов, а качеством и
        # размером листа: low + 1024 против medium + 1536 у реалистичного.
        want = [c for c in all_cams if c.name in ('C1', 'C2')] or all_cams[:2]
        model, side, gq = MODEL, 1024, DRAFT_QUALITY
    prefix = save_prefix or os.path.join(OUT, f'draft{n}')
    skus = {it['role']: it for it in (layout or {}).get('items', []) if it.get('role')}
    if quality == 'draft' and os.environ.get('SCENE3D', '1') == '1':
        # РЕЖИМ ПРОВЕРКИ (владелец 31.08): сырой кадр 3D-сцены без модели и без GPT
        sid_by_role = {it['role']: it.get('sid') for it in (layout or {}).get('items', [])
                       if it.get('role')}
        # КАМЕРА ВСЕГДА ВНУТРИ ПЕРИМЕТРА (владелец 31.08: «сквозь стену смотреть нельзя
        # ни в каких сценах»): глаз клэмпится внутрь комнаты с отступом от стен
        def _inside(cam):
            ex, ey, ez = (float(v) for v in cam.eye)
            pad = 25.0
            nx = min(max(ex, pad), room.width_cm - pad)
            nz = min(max(ez, pad), room.depth_cm - pad)
            if nx == ex and nz == ez:
                return cam
            return Camera(name=cam.name, eye=(nx, ey, nz), target=cam.target,
                          fov_deg=cam.fov_deg, width=cam.width, height=cam.height)
        want = [_inside(c) for c in want]
        # обе камеры ПАРАЛЛЕЛЬНО (владелец 31.08 «это же параллелить можно»): numpy
        # отпускает GIL, ядер на DEV хватает; кадр и scp-доставка каждой камеры — свой тред
        stamp = time.strftime('%H%M%S')

        def _one_cam(cam):
            img, diag = scene3d_frame(room, placements, cam, sid_by_role, photos)
            url = _publish_frame(img, f'scene3d-{stamp}-{cam.name}.jpg')
            return {'camera': cam.name, 'url': url, 'diag': diag, 'anchors': []}
        if os.environ.get('SCENE3D_PROCS') == '1' and len(want) > 1:
            # ДВА ПРОЦЕССА через fork (DEV, 12 ядер): треды упирались в GIL питон-цикла
            # растеризации. Pool пиклит callable по имени — воркер модульный, аргументы
            # наследуются форком через глобал _S3_JOB, назад едут JPEG-байты
            import multiprocessing as _mp
            global _S3_JOB
            _S3_JOB = (room, placements, want, sid_by_role, photos)
            with _mp.get_context('fork').Pool(2) as pool:
                got = pool.map(_s3_cam_job, range(len(want)))
            shots = []
            for name, data, diag in got:
                import io as _io
                url = _publish_frame(Image.open(_io.BytesIO(data)).convert('RGB'),
                                     f'scene3d-{stamp}-{name}.jpg')
                shots.append({'camera': name, 'url': url, 'diag': diag, 'anchors': []})
        else:
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=2) as ex:
                shots = list(ex.map(_one_cam, want))
        sec = round(time.time() - t0, 1)
        print(f'scene3d: кадров {len(shots)}, {sec} с (без модели)')
        first = shots[0] if shots else {'url': '', 'diag': {}}
        return {'shots': shots, 'sources': None, 'timing': None,
                'model': 'scene3d-raw', 'quality': quality, 'sec': sec,
                'file': '', 'url': first.get('url', ''), 'diag': first.get('diag', {})}
    if model.startswith('openai/'):
        # трек А работает и на одном ракурсе: тот же рецепт, просто лист без второй половины
        shots = _sheet_gpt(room, placements, photos, want, prefix, side, skus, model, gq,
                           style=str((layout or {}).get('style') or ''))
    elif len(want) > 1:
        shots = _sheet(room, placements, photos, want, prefix, model, side, skus)
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
            'timing': next((s.get('timing') for s in shots if s.get('timing')), None),
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


def tv_selftest() -> int:
    """Таблица случаев на правило телевизора: размер по расстоянию, потолок по тумбе, подвес."""
    cases = [
        # (расстояние, ширина тумбы, высота тумбы) → (дюймы, как поставлен)
        ((120, 200, 45), (43, 'на тумбе')),      # близко — маленький, тумба не мешает
        ((180, 200, 45), (50, 'на тумбе')),
        ((230, 200, 45), (55, 'на тумбе')),
        ((280, 200, 45), (65, 'на тумбе')),
        ((330, 200, 45), (75, 'на тумбе')),
        ((400, 230, 45), (85, 'на тумбе')),      # далеко — крупный (тумба 230 не режет)
        ((400, 200, 45), (81, 'на тумбе')),      # та же даль, тумба 200 → потолок 180 см
        ((400, 120, 45), (49, 'на тумбе')),      # узкая тумба режет 85″ до 49″
        ((280, 139, 90), (57, 'на стене')),      # высокая тумба → вешаем
    ]
    bad = 0
    for (dist, sw, sh), (want_inch, want_how) in cases:
        inch, w, h, elev, how = tv_spec(dist, sw, sh)
        if (inch, how) != (want_inch, want_how):
            bad += 1
            print(f'  FAIL {dist}см тумба {sw}x{sh}: получили {inch}″ {how}, '
                  f'ждали {want_inch}″ {want_how}')
        if w > sw:
            bad += 1
            print(f'  FAIL экран {w:.1f} шире тумбы {sw}')
        if abs(w / h - 16 / 9) > 0.02:
            bad += 1
            print(f'  FAIL пропорции не 16:9: {w:.1f}x{h:.1f}')
    print(f'tv_spec selftest: случаев {len(cases)}, ошибок {bad}')
    return 1 if bad else 0


if __name__ == '__main__':
    if '--tv-selftest' in sys.argv:
        sys.exit(tv_selftest())
    if '--warm' in sys.argv:
        print(f'прогрев: {warm()} с')
    elif '--layout' in sys.argv:
        pl = json.load(open(sys.argv[sys.argv.index('--layout') + 1], encoding='utf-8'))
        render(layout=pl, save_prefix=os.path.join(OUT, 'draft-live'))
    else:
        render(int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 10)
