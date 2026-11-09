#!/usr/bin/env python3
"""ОДИН AI-КАДР ГОСТИНОЙ ДЛЯ ПРОБЫ АГЕНТА (MASTER-agent-trial T7, T-20261109-13): кадр рендера 3D + состав сцены → одно
фото «как в объявлении» с плашкой `AI-generated visualisation — not a photograph` НА САМОЙ картинке.

ЧТО ПЕРЕИСПОЛЬЗУЕМ, А НЕ КОПИРУЕМ. Боевой путь «Сделать реалистичнее» (`draft_render.render(quality='realistic')`):
лист эталонов `draft_render._identity`, список товаров `improve_mode.product_list` (промпт v4), третий лист мягкого и декора
`improve_mode.third_sheet`, ворота «без листа товаров не платим» `improve_mode.paid_gate`, промпт `improve_mode.prompt_for`, вызов
шлюза `draft_render.gpt_edit`, исход одной меткой `draft_render.photo_outcome`. Отличие одно: у пробы ОДИН вид, а боевой промпт
написан под лист из двух видов с маджента-полосой — `single_view_prompt` меняет только фразы про два вида и полосу и ОТКАЗЫВАЕТ
(до оплаты), если после замены в тексте осталось хоть что-то про второй вид (промпт поменяли — тест и прогон это увидят).

ВХОД — папка сцены:
  frame.jpg | frame.png   кадр рендера гостиной с мебелью (любая пропорция; режется по центру под размер запроса, 3:2)
  scene.json              {"room": {...}, "items": [{role, name, img, w, d, h, x, y, rot, ...}], "decor": [...], "style": "сканди",
                           "floor": {...}?, "walls": {...}?} — формат запроса страницы к сервису кадров (`draft_render.scene_from_request`);
                          `img` — https:// или file:// (относительный путь берётся от папки сцены)
ВЫХОД — папка `--out`:
  hero.jpg                фото с плашкой (только при успехе; без плашки картинку не сохраняем)
  hero.json               {ok, model, quality, size, prompt_version, prompt_sha, timing{prep, model, post, total}, cost_usd,
                           cost_source, error, error_code, dry_run, ...}
  sources/                что ушло (или ушло бы) в модель: 1-frame.png, 2-ident.jpg, 3-extra.jpg, prompt.txt

  python tools/scout/trial_hero.py --scene DIR --out DIR            # СУХОЙ прогон: всё собрать, в модель не слать (бесплатно)
  python tools/scout/trial_hero.py --scene DIR --out DIR --go       # один платный кадр
  … --render                         # кадра в папке нет — нарисовать сервером одной камерой (полные меши; тяжёлое → heavy-slot)
  python tools/scout/trial_hero.py --prepare-demo demo-data.json --variant set1 --sheet лист.jpg --view 0 --scene DIR \\
         [--img-base ~/scout-scenes/flat215-demo]                   # папка сцены из демо (flat215): состав варианта + вид листа
Ключи: --budget 60 (с на весь шаг; кончился — отказ, тур отдаётся без фото), --size 1536x1024, --quality medium, --model ….
Код выхода: 0 — готово (или сухой прогон собран), 3 — отказ (hero.json с ошибкой, фото нет), 2 — неверный вход.
"""
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..', '..', 'services', 'planner-solver'))
# промпт и модель — как у рисующего процесса DEV (`tools/scout/systemd/remlab-render.service`): v4 читается при импорте improve_mode
os.environ.setdefault('IMPROVE_PROMPT', 'v4')

from PIL import Image, ImageDraw  # noqa: E402

BADGE_TEXT = 'AI-generated visualisation — not a photograph'
MODEL = os.environ.get('TRIAL_HERO_MODEL') or os.environ.get('REALISTIC_MODEL') or 'openai/gpt-image-2.5-sunburst'
QUALITY = os.environ.get('TRIAL_HERO_QUALITY', 'medium')
SIZE = os.environ.get('TRIAL_HERO_SIZE', '1536x1024')
BUDGET_S = float(os.environ.get('TRIAL_HERO_BUDGET_S', '60'))
SINGLE_TAG = 'single1'          # версия замены «два вида → один»; часть prompt_version в ответе

# ОДИН ВИД ВМЕСТО ЛИСТА: (было, стало). Блоки декора/мягкого/штор условные — замены, которых нет в тексте, пропускаются;
# что осталось про второй вид — ловит `_TWO_VIEW_LEFT` и отказывает до оплаты.
SINGLE_SUBS = [
    ('* IMAGE 1: one sheet containing TWO rendered views of the SAME furnished room, stacked vertically and separated by a magenta band.',
     '* IMAGE 1: one rendered view of the furnished room from a single camera.'),
    ('TASK: turn IMAGE 1 into two photorealistic views of a renovated room.',
     'TASK: turn IMAGE 1 into one photorealistic view of a renovated room.'),
    ('* the two-view layout or magenta separator;\n', ''),
    ('Keep the magenta band in exactly the same position, height and colour, with nothing drawn over it.\n\n', ''),
    (' Place each item ONCE and show it in both views if that surface is visible in both.', ' Place each item ONCE.'),
    ('show it in both views wherever that place is visible.', 'show it wherever that place is visible.'),
    ('hang them correctly and identically in both views', 'hang them correctly'),
    ('hung correctly and identical in both views.', 'hung correctly.'),
    ('The two views show the SAME room. Use exactly the same wall colour, floor material and direction, trim, door finish, window '
     'design and light temperature in both views.\n\n', ''),
    (' and must appear consistently in both views.', '.'),
    ('It is the same physical fixture in both views: the same design, materials, colour, scale, ceiling attachment point and '
     'switched-off state, shown only where naturally visible from each existing camera.',
     'It is switched off and shown only where naturally visible from the existing camera.'),
    ('Return ONE image with exactly the dimensions and proportions of IMAGE 1 and the same two-view layout.',
     'Return ONE image with exactly the dimensions and proportions of IMAGE 1.'),
]
_TWO_VIEW_LEFT = re.compile(r'magenta|both views|two views|two-view|each existing camera|view 1|view 2|stacked|separator|'
                            r'side by side', re.I)


class HeroError(RuntimeError):
    """Отказ шага с меткой (`code`) для json и очереди пробы: тур отдаётся без фото."""

    def __init__(self, code: str, msg: str):
        super().__init__(msg)
        self.code = code


def single_view_prompt(prompt: str) -> str:
    """Боевой промпт листа → промпт одного вида. Осталось упоминание второго вида/полосы — HeroError до оплаты."""
    for old, new in SINGLE_SUBS:
        prompt = prompt.replace(old, new)
    left = sorted({m.group(0).lower() for m in _TWO_VIEW_LEFT.finditer(prompt)})
    if left:
        raise HeroError('prompt_two_view', 'в промпте одного вида осталось про два вида: ' + ', '.join(left))
    return prompt


def fit_frame(img: Image.Image, size: str) -> Image.Image:
    """Кадр → ровно размер запроса: обрезка по центру до пропорции, затем масштаб (пропорция входа = пропорция ответа)."""
    tw, th = (int(x) for x in size.split('x'))
    img = img.convert('RGB')
    if abs(img.width / img.height - tw / th) > 0.002:
        if img.width / img.height > tw / th:
            cw = round(img.height * tw / th)
            x0 = (img.width - cw) // 2
            img = img.crop((x0, 0, x0 + cw, img.height))
        else:
            ch = round(img.width * th / tw)
            y0 = (img.height - ch) // 2
            img = img.crop((0, y0, img.width, y0 + ch))
    return img.resize((tw, th), Image.LANCZOS) if img.size != (tw, th) else img


def badge(img: Image.Image, text: str = BADGE_TEXT) -> Image.Image:
    """Плашка на картинке, внизу слева: тёмная подложка 62 %, белый текст. Высота букв ≈ 3,2 % ширины — на телефоне (кадр
    шириной 375 px) это ~12 px, читается; не влезла по ширине (узкий кадр) — шрифт уменьшается до 90 % ширины."""
    import draft_render as DR
    img = img.convert('RGB')
    W, H = img.size
    fs = max(14, round(W * 0.032))
    probe = ImageDraw.Draw(img)
    font = DR._font(fs)
    while fs > 12 and probe.textlength(text, font=font) > W * 0.90:
        fs -= 1
        font = DR._font(fs)
    tw = probe.textlength(text, font=font)
    pad, m = round(fs * 0.45), round(W * 0.018)
    box = (m, H - m - fs - 2 * pad, m + round(tw) + 2 * pad, H - m)
    over = Image.new('RGBA', img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(over)
    d.rounded_rectangle(box, radius=round(fs * 0.35), fill=(0, 0, 0, 158))
    d.text((box[0] + pad, box[1] + pad + fs // 2), text, font=font, fill=(255, 255, 255, 255), anchor='lm')
    return Image.alpha_composite(img.convert('RGBA'), over).convert('RGB')


def _abs_img(url, base: str):
    if not url or str(url).startswith(('http://', 'https://', 'file://', '//')):
        return url
    return 'file://' + os.path.abspath(os.path.join(base, str(url)))


def render_frame(payload: dict, size: str = SIZE) -> tuple[Image.Image, dict]:
    """КАДРА НЕТ — РИСУЕМ САМИ ОДНОЙ КАМЕРОЙ (запасной путь, если стадия мебели не сдала кадр). Тот же рендер полных мешей, что у
    боевого `improve_mode.build` (`draft_render.scene3d_frame`), но одна камера — первая из `cams` сцены (у демо — «афиша» C1; нет
    `cams` — автоподбор `demo_cams`) и сразу в размер запроса. Меш — по `msid`/`sid`, экземпляр комплекта — меш базовой роли."""
    os.environ.setdefault('SCENE3D_QUALITY', 'full')
    import draft_render as DR
    from planner.scene import Camera
    DR.S3_LITE[0] = False                                 # в платный запрос — только полная геометрия (как improve_mode.build)
    room, placements, photos = DR.scene_from_request(payload)
    c = DR.cams_from_request(room, placements, payload)[0]
    tw, th = (int(x) for x in size.split('x'))
    cam = Camera(name=c.name, eye=c.eye, target=c.target, fov_deg=c.fov_deg, width=tw, height=th,
                 **({'shift_y': c.shift_y} if hasattr(c, 'shift_y') else {}))
    sid = {it['role']: (it.get('msid') or it.get('sid')) for it in payload.get('items') or [] if it.get('role')}
    for role in list(sid):
        base = re.sub(r'\s+\d+$', '', role)
        if not sid[role] and base != role and sid.get(base):
            sid[role] = sid[base]
    for d in DR.decor_split(payload)[0]:
        sk = d.get('sku') or {}
        if d.get('role') and (sk.get('msid') or sk.get('sid')):
            sid[d['role']] = sk.get('msid') or sk.get('sid')
    img, diag = DR.scene3d_frame(room, placements, cam, sid, photos)
    return img, {'camera': c.name, 'clay': sorted(set(r for r in (diag.get('clay') or []) if r != 'тв'))}


def load_scene(scene_dir: str, render: bool = False) -> tuple[dict, Image.Image]:
    """Папка сцены → (запрос как у страницы, кадр). Пути картинок товаров — абсолютные. Кадра нет и `render` — рисуем сами."""
    sj = os.path.join(scene_dir, 'scene.json')
    fp = next((os.path.join(scene_dir, n) for n in ('frame.jpg', 'frame.png') if os.path.exists(os.path.join(scene_dir, n))), None)
    if not os.path.exists(sj) or (fp is None and not render):
        raise HeroError('bad_input', f'в {scene_dir} нужны scene.json и frame.jpg|png')
    payload = json.load(open(sj, encoding='utf-8'))
    if not isinstance(payload, dict) or not payload.get('room') or not payload.get('items'):
        raise HeroError('bad_input', 'scene.json без room/items')
    for it in payload['items']:
        it['img'] = _abs_img(it.get('img'), scene_dir)
    for d in payload.get('decor') or []:
        sk = d.get('sku') or {}
        if sk.get('img'):
            sk['img'] = _abs_img(sk['img'], scene_dir)
    if fp is None:
        img, info = render_frame(payload)
        payload['_rendered'] = info
        return payload, img
    return payload, Image.open(fp).convert('RGB')


def items_from_variant(v: dict, img_base: str) -> list:
    """Предметы варианта демо (`sku` вложен) → плоский формат запроса (как `improve_mode.variant_payload`): экземпляр комплекта
    («стул 2» без своего товара) наследует товар базовой роли."""
    items = []
    for it in v.get('items') or []:
        sku = it.get('sku') or {}
        items.append({'role': it['role'], 'x': it['x'], 'y': it['y'], 'rot': it.get('rot'), 'w': it.get('w'), 'd': it.get('d'),
                      'h': it.get('h'), 'elev': it.get('elev'), 'hung': sku.get('hung') if it.get('hung') is None else it.get('hung'),
                      'corner': it.get('corner'), 'section': it.get('section'), 'sid': sku.get('sid'), 'msid': sku.get('msid'),
                      'name': sku.get('name'), 'img': _abs_img(sku.get('img'), img_base)})
    by_role = {it['role']: it for it in items if it.get('name')}
    for it in items:
        if not it.get('name'):
            src = by_role.get(re.sub(r'\s+\d+$', '', it['role']))
            if src:
                for k in ('sid', 'msid', 'name', 'img'):
                    it[k] = src.get(k)
    return [{k: v for k, v in it.items() if v is not None} for it in items]


def prepare_demo(demo_json: str, variant: str, sheet: str, view: int, scene_dir: str, img_base: str | None = None) -> str:
    """Папка сцены из демо: состав варианта `variant` из `demo-data.json` + вид №`view` листа двух видов (кадры исходника
    «Сделать реалистичнее» `~/scout-scenes/src/improve-*/1-ОТПРАВЛЯЕМ-лист-двух-видов.jpg`). Живые файлы только читаются;
    `img_base` — папка, от которой считаются `img/…` товаров (живое демо), по умолчанию — папка `demo-data.json`."""
    d = json.load(open(demo_json, encoding='utf-8'))
    v = next((x for x in d.get('variants') or [] if x.get('id') == variant or x.get('title') == variant), None)
    if v is None:
        raise HeroError('bad_input', f'нет варианта {variant!r}')
    base = os.path.abspath(img_base) if img_base else os.path.dirname(os.path.abspath(demo_json))
    decor = []
    for x in v.get('decor') or []:
        x = json.loads(json.dumps(x))
        if (x.get('sku') or {}).get('img'):
            x['sku']['img'] = _abs_img(x['sku']['img'], base)
        decor.append(x)
    payload = {'room': d['room'], 'items': items_from_variant(v, base), 'decor': decor, 'style': v.get('style') or '',
               'variant': v.get('id'), 'source': f'demo:{d.get("apartment_id") or "?"}:{v.get("id")}',
               'cams': [{k: c[k] for k in ('name', 'x', 'y', 'rot', 'fov', 'pose') if k in c} for c in (v.get('cams') or [])]}
    os.makedirs(scene_dir, exist_ok=True)
    json.dump(payload, open(os.path.join(scene_dir, 'scene.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    if not sheet:
        return scene_dir                                  # без листа — только scene.json (кадр нарисует --render)
    im = Image.open(sheet).convert('RGB')
    import numpy as np
    a = np.asarray(im).astype(int)
    rows = ((a[..., 0] > 170) & (a[..., 2] > 170) & (a[..., 1] < 110)).mean(axis=1) > 0.5
    idx = np.where(rows)[0]
    if len(idx) >= 8:
        views = [im.crop((0, 0, im.width, int(idx[0]))), im.crop((0, int(idx[-1]) + 1, im.width, im.height))]
    else:
        views = [im]
    views[min(view, len(views) - 1)].save(os.path.join(scene_dir, 'frame.jpg'), quality=93)
    return scene_dir


def build(payload: dict, frame: Image.Image, size: str = SIZE) -> dict:
    """Всё, что уходит в модель: кадр под размер, лист эталонов, третий лист (декор вне сцены и мягкое), промпт одного вида."""
    import draft_render as DR
    import improve_mode as IM
    items = payload.get('items') or []
    photos = {it['role']: DR.photo(it.get('img')) for it in items if it.get('img') and it.get('role')}
    for it in items:                                     # «стул 2» — фото базовой роли
        base = re.sub(r'\s+\d+$', '', it.get('role') or '')
        if photos.get(it.get('role')) is None and photos.get(base) is not None:
            photos[it['role']] = photos[base]
    ident = None
    try:
        ident = DR._identity([{'role': it['role'], 'n': i + 1} for i, it in enumerate(items) if it.get('name')], photos,
                             {it['role']: it for it in items if it.get('role')})
    except Exception as e:  # noqa: BLE001 — отказ решают ворота ниже
        print(f'  лист эталонов не собрался: {str(e)[:80]}')
    decor, soft = DR.decor_split(payload)[1], IM.soft_items(payload)
    extra = None
    if decor or soft:
        try:
            extra = IM.third_sheet(decor, soft)
        except Exception as e:  # noqa: BLE001
            print(f'  третий лист не собрался: {str(e)[:80]}')
    if extra is None:
        decor, soft = [], []
    prods = None
    if IM.PROMPT_V4:
        try:
            prods = IM.product_list(items, photos)
        except Exception as e:  # noqa: BLE001
            print(f'  список товаров не собрался: {str(e)[:80]}')
    fl, wl = payload.get('floor') or {}, payload.get('walls') or {}
    base_prompt = IM.prompt_for(payload.get('style') or '', decor, fl.get('title') or fl.get('id') or None,
                                wl.get('title') or wl.get('id') or None, None, prods, IM.soft_list(soft, len(decor) + 1, items),
                                room=IM.room_kind(payload))
    prompt = single_view_prompt(base_prompt)
    named = [it for it in items if it.get('name')]
    return {'frame': fit_frame(frame, size), 'ident': ident, 'dsheet': extra, 'prompt': prompt, 'size': size,
            'prods_failed': IM.PROMPT_V4 and not prods, 'prompt_version': f'{IM.PROMPT_VERSION}-{SINGLE_TAG}',
            'prompt_sha': IM.prompt_sha(prompt), 'n_items': len(named),
            'n_photos': sum(1 for it in named if photos.get(it['role']) is not None), 'n_extra': len(decor) + len(soft)}


MIN_PHOTO_SHARE = 0.75


def photo_gate(built: dict) -> None:
    """БЕЗ ФОТО ТОВАРОВ НЕ ПЛАТИМ. `paid_gate` проверяет, что лист эталонов собран, но лист из карточек «фото нет» он пропускает
    (найдено сухим прогоном 09.11: путь к `img/` не тот — 0 фото из 9, лист собран). Модель тогда рисует товары по названию —
    «не тот» набор за деньги. Порог — 3/4 позиций с фото."""
    n, k = built.get('n_items') or 0, built.get('n_photos') or 0
    if n == 0 or k < MIN_PHOTO_SHARE * n:
        raise HeroError('no_product_photos', f'фото товаров {k} из {n} — платный вызов не делаю')


def _save_sources(out: str, built: dict) -> None:
    src = os.path.join(out, 'sources')
    os.makedirs(src, exist_ok=True)
    built['frame'].save(os.path.join(src, '1-frame.png'))
    if built.get('ident') is not None:
        built['ident'].save(os.path.join(src, '2-ident.jpg'), quality=88)
    if built.get('dsheet') is not None:
        built['dsheet'].save(os.path.join(src, '3-extra.jpg'), quality=88)
    open(os.path.join(src, 'prompt.txt'), 'w', encoding='utf-8').write(built['prompt'])


def _write_json(out: str, res: dict) -> None:
    p = os.path.join(out, 'hero.json')
    tmp = p + '.tmp'
    json.dump(res, open(tmp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    os.replace(tmp, p)


def run(scene_dir: str, out: str, go: bool = False, budget_s: float = BUDGET_S, size: str = SIZE, quality: str = QUALITY,
        model: str = MODEL, render: bool = False) -> dict:
    """Шаг пробы целиком. Никогда не бросает: итог — словарь (он же hero.json); `ok` False — тур отдаётся без фото."""
    t0 = time.time()
    os.makedirs(out, exist_ok=True)
    res = {'ok': False, 'dry_run': not go, 'model': model, 'quality': quality, 'size': size, 'badge': BADGE_TEXT,
           'budget_s': budget_s, 'timing': {}, 'cost_usd': None, 'cost_source': None, 'error': None, 'error_code': None,
           'scene': os.path.abspath(scene_dir), 'image': None}
    try:
        import draft_render as DR
        import improve_mode as IM
        payload, frame = load_scene(scene_dir, render=render)
        if payload.get('_rendered'):
            res['timing']['render'] = round(time.time() - t0, 2)
            res['rendered'] = payload.pop('_rendered')
        built = build(payload, frame, size)
        res.update(prompt_version=built['prompt_version'], prompt_sha=built['prompt_sha'], n_items=built['n_items'],
                   n_extra=built['n_extra'], style=payload.get('style') or '', source=payload.get('source'))
        _save_sources(out, built)
        try:
            IM.paid_gate(built)                               # без листа товаров не платим (room-photos-07 п.3)
        except DR.NoProductSheet as e:
            raise HeroError('no_product_sheet', str(e)) from None
        photo_gate(built)
        res['n_photos'] = built['n_photos']
        res['timing']['prep'] = round(time.time() - t0, 2)
        imgs = [built['frame'], built['ident']] + ([built['dsheet']] if built.get('dsheet') is not None and 'IMAGE 3' in built['prompt']
                                                   else [])
        if not go:
            # сухой прогон: плашка на ВХОДНОМ кадре — проверить читаемость бесплатно; в модель ничего не ушло
            badge(built['frame']).save(os.path.join(out, 'dry-badge.jpg'), quality=90)
            res.update(ok=True, images_sent=len(imgs), note='сухой прогон: в модель НЕ отправлено')
            return res
        left = budget_s - (time.time() - t0) - 3.0           # 3 с — на плашку и запись
        if left < 10:
            raise HeroError('budget', f'на модель осталось {left:.0f} с — не зову')
        bal0 = DR.gw_credits(max_age_s=0)
        DR._GW_TIMEOUT = max(5, int(left))                   # потолок ожидания шлюза = остаток бюджета шага
        t_m = time.time()
        try:
            img = DR.gpt_edit(imgs, built['prompt'], size=size, quality=quality, model=model)
        except BaseException as e:                           # SystemExit шлюза, таймаут, нет денег — одной меткой
            raise HeroError(DR.photo_outcome(e), str(e)[:300]) from None
        res['timing']['model'] = round(time.time() - t_m, 1)
        t_p = time.time()
        img = fit_frame(img, size) if abs(img.width / img.height - built['frame'].width / built['frame'].height) > 0.01 else img
        badge(img).save(os.path.join(out, 'hero.jpg'), quality=90)
        res['timing']['post'] = round(time.time() - t_p, 2)
        res.update(ok=True, image=os.path.join(out, 'hero.jpg'), out_px=list(img.size))
        time.sleep(2)                                         # баланс шлюза обновляется не мгновенно
        bal1 = DR.gw_credits(max_age_s=0)
        if bal0 is not None and bal1 is not None and bal0 >= bal1:
            res.update(cost_usd=round(bal0 - bal1, 4), cost_source='balance_delta (общий счёт шлюза: параллельные задания DEV '
                                                                    'попадают в разницу)')
        return res
    except HeroError as e:
        res.update(error=str(e), error_code=e.code)
        return res
    except Exception as e:  # noqa: BLE001 — шаг пробы не роняет конвейер: причина — в json
        res.update(error=f'{type(e).__name__}: {str(e)[:300]}', error_code='other')
        return res
    finally:
        res['timing']['total'] = round(time.time() - t0, 2)
        _write_json(out, res)


def _arg(name: str, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def main() -> int:
    if '--prepare-demo' in sys.argv:
        try:
            d = prepare_demo(_arg('--prepare-demo'), _arg('--variant', 'set1'), _arg('--sheet'), int(_arg('--view', '0')),
                             _arg('--scene'), _arg('--img-base'))
        except HeroError as e:
            print(f'ошибка: {e}')
            return 2
        print(f'папка сцены: {d}')
        return 0
    scene, out = _arg('--scene'), _arg('--out')
    if not scene or not out:
        print(__doc__)
        return 2
    r = run(scene, out, go='--go' in sys.argv, budget_s=float(_arg('--budget', BUDGET_S)), size=_arg('--size', SIZE),
            quality=_arg('--quality', QUALITY), model=_arg('--model', MODEL), render='--render' in sys.argv)
    print(json.dumps({k: r[k] for k in ('ok', 'dry_run', 'model', 'size', 'timing', 'cost_usd', 'error_code', 'error', 'image')
                      if k in r}, ensure_ascii=False))
    return 0 if r['ok'] else 3


if __name__ == '__main__':
    sys.exit(main())
