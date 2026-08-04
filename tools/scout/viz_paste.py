#!/usr/bin/env python3
"""Ф2 (дешёвый путь): фотография товара НАТЯГИВАЕТСЯ на его грань в кадре — без нейросети.

Почему так: пообъектная правка нейросетью стоит ~5–19 центов ЗА ПРЕДМЕТ, а комплект — это
12–17 предметов. Между тем мы знаем точную геометрию: где стоит предмет, какого он размера и
какой стороной повёрнут. Значит фотографию товара можно спроецировать на его переднюю грань
математикой — локально, бесплатно и со стопроцентной узнаваемостью (это буквально фото товара).

Нейросеть остаётся нужна только на финальное согласование света и краёв — один вызов на кадр
независимо от числа предметов.

  ~/venvs/scout/bin/python viz_paste.py 21              # вклеить все товары в панораму
  ~/venvs/scout/bin/python viz_paste.py 21 --only диван
"""
import io
import json
import math
import os
import sys

sys.path.insert(0, '/home/pakar/igor/remlab/services/planner-solver')

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from planner.scene import cameras_for, proxy_parts  # noqa: E402
from scene_build import SCENE_DIR, load_scene  # noqa: E402
from viz_objects import product  # noqa: E402
from viz_base import fal_key, fal_run, uri_from_image  # noqa: E402

import steps  # noqa: E402

# Плоские/мелкие роли не вклеиваем: у ковра и люстры фронтальной грани нет, декор не опознаётся
# Ковёр лежит на полу — у него отдельная ветка проекции. ТВ рисует базовый проход.
SKIP = {'тв'}
FLOOR = {'ковёр', 'ковер'}


_CUTS: list[tuple[str, str]] = []      # что вырезали в этом прогоне — для журнала
# birefnet/v2 — вдвое чище край, чем birefnet и bria (замер на диване: светлый ореол 7,3% против
# 14,9% и 14,8% краевых пикселей). Разово на товар, ~1 цент, кэш навсегда.
CUTOUT = 'fal-ai/birefnet/v2'


def cutout(path: str) -> Image.Image:
    """Фото товара без фона (RGBA). Кэшируется рядом: `-cut.png`.

    Без этого вклейка тащит в кадр подложку карточки — у дивана белый ореол, у столика синий
    прямоугольник (поймано 2026-08-04).
    """
    dst = os.path.splitext(path)[0] + '-cut.png'
    if os.path.exists(dst):
        return Image.open(dst).convert('RGBA')
    _CUTS.append((path, dst))
    src = Image.open(path).convert('RGB')
    res = fal_run(CUTOUT, {'image_url': uri_from_image(src)}, fal_key())
    url = (res.get('image') or {}).get('url') or (res.get('images') or [{}])[0].get('url')
    if not url:
        return src.convert('RGBA')
    import urllib.request as _u
    raw = Image.open(io.BytesIO(_u.urlopen(url, timeout=120).read())).convert('RGBA')
    clean = defringe(raw)
    clean.save(dst)
    return clean


def defringe(img: Image.Image) -> Image.Image:
    """Снимает светлую кайму: у полупрозрачных пикселей вычитаем подмешанный фон карточки.

    Иначе вместе с товаром в кадр уезжает белый ободок, и предмет выглядит наклеенным.
    """
    a = np.asarray(img).astype(np.float32)
    rgb, alpha = a[..., :3], a[..., 3:4] / 255.0
    corners = np.concatenate([a[:4, :4, :3].reshape(-1, 3), a[:4, -4:, :3].reshape(-1, 3),
                              a[-4:, :4, :3].reshape(-1, 3), a[-4:, -4:, :3].reshape(-1, 3)])
    bg = corners.mean(axis=0) if len(corners) else np.array([255.0, 255.0, 255.0])
    soft = (alpha > 0.05) & (alpha < 0.97)
    fixed = np.where(soft, np.clip((rgb - (1 - alpha) * bg) / np.maximum(alpha, 0.05), 0, 255), rgb)
    out = np.concatenate([fixed, alpha * 255], axis=2).astype(np.uint8)
    return Image.fromarray(out, 'RGBA')


def trim_alpha(img: Image.Image) -> Image.Image:
    """Обрезает пустые поля по альфе — предмет должен занимать всю грань."""
    a = np.asarray(img)
    if a.shape[2] < 4:
        return img
    ys, xs = np.where(a[..., 3] > 8)
    if not len(xs):
        return img
    return img.crop((int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1))


def trim_white(img: Image.Image, thr: int = 244) -> Image.Image:
    """Обрезает белые поля фотографии товара — иначе предмет вклеится с воздухом по краям."""
    a = np.asarray(img.convert('RGB'))
    nonwhite = (a < thr).any(axis=2)
    if not nonwhite.any():
        return img
    ys, xs = np.where(nonwhite)
    return img.crop((int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1))


def face_of(p, it) -> tuple[np.ndarray, np.ndarray, np.ndarray, float, float]:
    """Передняя грань предмета: точка-угол, вектор ширины, нормаль, ширина и высота (см)."""
    parts = proxy_parts(p, it)
    x0 = min(q[0] for q in parts)
    x1 = max(q[1] for q in parts)
    z0 = min(q[4] for q in parts)
    z1 = max(q[5] for q in parts)
    h = max(q[3] for q in parts)
    rot = int(round(p.rot)) % 360
    if rot in (0, 180):
        zf = z1 if rot == 0 else z0                       # лицевая плоскость по глубине
        n = np.array([0.0, 0.0, 1.0 if rot == 0 else -1.0])
        corner = np.array([x0, 0.0, zf])
        wvec = np.array([x1 - x0, 0.0, 0.0])
    else:
        xf = x1 if rot == 90 else x0
        n = np.array([1.0 if rot == 90 else -1.0, 0.0, 0.0])
        corner = np.array([xf, 0.0, z0])
        wvec = np.array([0.0, 0.0, z1 - z0])
    return corner, wvec, n, float(np.linalg.norm(wvec)), h


def billboard(p, it, cam):
    """Вырезка товара СТОИТ НА ПОЛУ лицом к камере — как фигура на подставке.

    Раньше фото натягивалось на переднюю плоскость коробки. У низкой мебели (столик, тумба) мы
    сверху видим не перёд, а столешницу, и фотография оказывалась вертикальной картинкой ВНУТРИ
    серого объёма — «отражение внутри модели» (владелец, 2026-08-04). Стоячая вырезка так не врёт:
    предмет всегда повёрнут к зрителю тем, что снято на фото.
    """
    eye, fwd, right, up = cam.basis()
    centre = np.array([p.x, 0.0, p.y])
    look = centre - eye
    look[1] = 0.0
    n = np.linalg.norm(look)
    look = look / (n if n > 1e-6 else 1.0)
    side = np.cross(np.array([0.0, 1.0, 0.0]), look)          # горизонтальная ось вырезки
    side /= max(float(np.linalg.norm(side)), 1e-6)
    w_cm = float(it.w_cm)
    h_cm = float(it.h_cm or 60.0) + float(getattr(p, "elev_cm", 0.0))
    base = float(getattr(p, "elev_cm", 0.0))
    corner = centre - side * (w_cm / 2) + np.array([0.0, base, 0.0])
    return corner, side * w_cm, np.array([0.0, h_cm - base, 0.0]), look


def floor_quad(p, it):
    """Горизонтальный четырёхугольник ковра: он лежит, а не стоит."""
    from planner.geometry import footprint
    poly = footprint(p, it)
    xs, ys = poly.exterior.coords.xy
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    corner = np.array([x0, 0.6, y0])
    return (corner, np.array([x1 - x0, 0.0, 0.0]), np.array([0.0, 0.0, y1 - y0]),
            np.array([0.0, 1.0, 0.0]))


def paste_role(pano: np.ndarray, zbuf: np.ndarray, cam, p, it, photo: Image.Image) -> int:
    """Ставит вырезку товара в кадр. Рисуем по прямоугольнику вырезки, а не по силуэту коробки:
    иначе часть товара срезается по её краю (у столика отрезало половину столешницы — владелец,
    2026-08-04). Что чем перекрыто, решает z-буфер сцены."""
    H, W = pano.shape[:2]
    eye, fwd, right, up = cam.basis()
    fv = (H / 2) / math.tan(math.radians(cam.vfov_deg) / 2)
    if p.role in FLOOR:                    # ковёр лежит НА ПОЛУ: проекция на горизонталь
        corner, wvec, hvec, n = floor_quad(p, it)
    else:
        corner, wvec, hvec, n = billboard(p, it, cam)
    w_cm = float(np.linalg.norm(wvec))
    h_cm = float(np.linalg.norm(hvec))
    quad = np.array([corner, corner + wvec, corner + wvec + hvec, corner + hvec])
    rel = quad - eye
    if cam.cyl:
        angq = np.arctan2(rel @ right, rel @ fwd)
        horiz = np.hypot(rel @ right, rel @ fwd)
        uq = W / 2 + angq / math.radians(cam.fov_deg) * W
        vq = H / 2 - fv * (rel @ up) / np.maximum(horiz, 1e-3)
    else:
        focal = (W / 2) / math.tan(math.radians(cam.fov_deg) / 2)
        zq = np.maximum(rel @ fwd, 1e-3)
        uq = W / 2 + focal * (rel @ right) / zq
        vq = H / 2 - focal * (rel @ up) / zq + cam.shift_y * H
    x0, x1 = int(max(0, np.floor(uq.min()))), int(min(W - 1, np.ceil(uq.max())))
    y0, y1 = int(max(0, np.floor(vq.min()))), int(min(H - 1, np.ceil(vq.max())))
    if x1 <= x0 or y1 <= y0:
        return 0
    gy, gx = np.mgrid[y0:y1 + 1, x0:x1 + 1]
    ys, xs = gy.ravel(), gx.ravel()
    if cam.cyl:                                            # панорама
        ang = (xs - W / 2) / W * math.radians(cam.fov_deg)
        dirs = (fwd[None, :] * np.cos(ang)[:, None]
                + right[None, :] * np.sin(ang)[:, None]
                + up[None, :] * ((H / 2 - ys) / fv)[:, None])
    else:                                                  # обычный кадр со сдвигом объектива
        focal2 = (W / 2) / math.tan(math.radians(cam.fov_deg) / 2)
        dirs = (fwd[None, :] * focal2
                + right[None, :] * (xs - W / 2)[:, None]
                + up[None, :] * (H / 2 + cam.shift_y * H - ys)[:, None])
    denom = dirs @ n
    with np.errstate(divide='ignore', invalid='ignore'):
        t = ((corner - eye) @ n) / denom
    hit = eye[None, :] + dirs * t[:, None]
    s = ((hit - corner[None, :]) @ wvec) / (w_cm ** 2)
    v = ((hit - corner[None, :]) @ hvec) / (h_cm ** 2)
    ok = np.isfinite(t) & (t > 0) & (s >= -0.02) & (s <= 1.02) & (v >= -0.02) & (v <= 1.02)
    if ok.sum() < 200:
        return 0

    cut = trim_alpha(photo)
    if p.role in FLOOR:
        # У ковра снимок обычно вертикальный, а след — вдоль дивана. Разворачиваем фото под след
        # и заполняем его целиком: иначе ковёр ложится поперёк (владелец, 2026-08-04).
        long_x = float(np.linalg.norm(wvec)) >= float(np.linalg.norm(hvec))
        if (cut.width >= cut.height) != long_x:
            cut = cut.transpose(Image.ROTATE_90)
    src = np.asarray(cut).astype(np.float32)
    sh, sw = src.shape[:2]
    # ПРОПОРЦИИ ФОТО НЕ ЛОМАЕМ: вписываем снимок в габарит предмета и ставим по низу и центру,
    # иначе диван сплющивается по высоте, а стеллаж растягивается (владелец, 2026-08-04)
    box_ar = (w_cm / h_cm) if h_cm > 1e-6 else 1.0
    ph_ar = sw / max(sh, 1)
    if p.role in FLOOR:                    # ковёр растягиваем на весь след — он и есть его размер
        fit_w = fit_h = 1.0
    else:
        fit_w = min(1.0, ph_ar / box_ar)
        fit_h = min(1.0, box_ar / ph_ar)
    su = (s[ok] - (1 - fit_w) / 2) / fit_w          # центрируем по ширине
    sv = v[ok] / fit_h                              # прижимаем к полу
    inside = (su >= 0) & (su <= 1) & (sv >= 0) & (sv <= 1)
    if inside.sum() < 100:
        return 0
    px = np.clip((su[inside] * (sw - 1)).astype(int), 0, sw - 1)
    py = np.clip(((1 - sv[inside]) * (sh - 1)).astype(int), 0, sh - 1)
    smp = src[py, px]
    rgb = smp[:, :3]
    alpha = (smp[:, 3:4] / 255.0) if src.shape[2] > 3 else np.ones((len(px), 1), np.float32)
    yy, xx = ys[ok][inside], xs[ok][inside]
    zpix = (t[ok][inside] if cam.cyl else t[ok][inside] * (dirs[ok][inside] @ fwd))
    visible = (zpix < zbuf[yy, xx] + 1.0) & (alpha[:, 0] > 0.02)   # 1 см допуска на стену за спиной
    if visible.sum() < 50:
        return 0
    yy, xx, rgb, alpha, zpix = (yy[visible], xx[visible], rgb[visible],
                                alpha[visible], zpix[visible])
    base_px = pano[yy, xx].astype(np.float32)
    pano[yy, xx] = np.clip(rgb * alpha + base_px * (1 - alpha), 0, 255).astype(np.uint8)
    hard = alpha[:, 0] > 0.5
    zbuf[yy[hard], xx[hard]] = zpix[hard]                          # ближние перекроют дальние
    return int(hard.sum())


HARMONIZE = 'fal-ai/nano-banana/edit'      # один вызов на кадр, ~4 цента, независимо от числа
                                           # предметов — иначе цена растёт линейно и не влезает


def harmonize(pano: Image.Image) -> Image.Image:
    """Согласование вклеенных фотографий со сценой: тени, контакт с полом, края.

    Товары уже стоят на своих местах и это ИХ фотографии — модели остаётся только «подружить»
    их со светом сцены. Composition при этом менять нельзя, о чём и говорит промпт.
    """
    prompt = ('Blend the furniture into this interior photo: add soft contact shadows under every '
              'piece, match the room lighting and white balance, soften the cut-out edges. '
              'Do NOT move, resize, replace or restyle any object: every piece of furniture must '
              'keep exactly its current position, size, shape, colour and fabric. Keep walls, '
              'floor, window and door exactly as they are. Photorealistic interior photo.')
    res = fal_run(HARMONIZE, {'prompt': prompt, 'image_urls': [uri_from_image(pano)],
                              'num_images': 1, 'output_format': 'png'}, fal_key())
    url = (res.get('images') or [{}])[0].get('url')
    if not url:
        return pano
    import io as _io
    import urllib.request as _u
    out = Image.open(_io.BytesIO(_u.urlopen(url, timeout=240).read())).convert('RGB')
    return out.resize(pano.size)


def ref_sheet(n: int, roles: list[str]) -> tuple[Image.Image, list[str]]:
    """Лист референсов: фото товаров с подписями ролей — чтобы модель видела, ЧТО стоит в кадре."""
    from PIL import ImageDraw, ImageFont
    cells, names = [], []
    for role in roles:
        try:
            it, path = product(n, role)
        except KeyError:
            continue
        if not os.path.exists(path):
            continue
        cells.append((role, cutout(path)))
        names.append(f'{role}: {(it.get("name") or "")[:70]}')
    if not cells:
        return None, []
    cols = min(4, len(cells))
    rows = (len(cells) + cols - 1) // cols
    cw, ch = 420, 400
    sheet = Image.new('RGB', (cols * cw, rows * ch), (255, 255, 255))
    d = ImageDraw.Draw(sheet)
    f = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 26)
    for i, (role, img) in enumerate(cells):
        im = trim_alpha(img).convert('RGBA')
        im.thumbnail((cw - 30, ch - 70))
        x, y = (i % cols) * cw, (i // cols) * ch
        bg = Image.new('RGBA', im.size, (255, 255, 255, 255))
        bg.alpha_composite(im)
        sheet.paste(bg.convert('RGB'), (x + (cw - im.width) // 2, y + 20))
        d.text((x + 14, y + ch - 42), role, fill=(20, 20, 20), font=f)
    return sheet, names


def harmonize_gpt(frame: Image.Image, sheet: Image.Image, names: list[str]) -> Image.Image:
    """Согласование через OpenAI: кадр + ЛИСТ РЕФЕРЕНСОВ с подписями, до 16 картинок за запрос.

    Идея владельца: пусть модель сама видит и мебель, и сцену. Геометрию ей при этом не доверяем —
    предметы уже вклеены на свои места, менять их запрещено промптом.
    """
    from viz_objects import edit_gpt_raw
    prompt = ('This is a photo-collage of a real living room: every piece of furniture is a real '
              'product photo pasted at its exact position and size. Turn it into one believable '
              'photograph: add soft contact shadows under each piece, unify lighting and white '
              'balance, soften the pasted edges, fix the floor and wall junctions. '
              'STRICT: do not move, resize, rotate, remove, add or restyle any furniture; keep '
              'every product exactly as shown, including fabric, colour and proportions. '
              'The second image is a reference sheet of the same products with labels: '
              + '; '.join(names) + '.')
    return edit_gpt_raw([frame, sheet], prompt, size='1536x1024')


def main() -> None:
    n = int(sys.argv[1])
    only = sys.argv[sys.argv.index('--only') + 1] if '--only' in sys.argv else None
    cam_name = sys.argv[sys.argv.index('--cam') + 1] if '--cam' in sys.argv else 'P'
    prefix = os.path.join(SCENE_DIR, f'scene{n}-{cam_name}')
    # По умолчанию вклеиваем в НАШ clay-рендер: он геометрически точен. Сгенерированная оболочка
    # ставит пол и стены «примерно», из-за чего вклеенная мебель повисает в воздухе (2026-08-04).
    base = f'{prefix}-empty-clay.png'    # пустая комната: серых коробок в кадре быть не должно
    if '--base' in sys.argv:
        base = f'{prefix}-{sys.argv[sys.argv.index("--base") + 1]}.jpg'
    pano = np.asarray(Image.open(base).convert('RGB')).copy()
    H, W = pano.shape[:2]
    id_map = json.load(open(f'{prefix}-frame.json'))['ids']
    room, placements = load_scene(n)
    cam = next(c for c in cameras_for(room, placements) if c.name == cam_name)
    by = {p.role: p for p in placements}
    # z-буфер стартует с ПУСТОЙ комнаты: дальше каждый вклеенный товар пишет в него свою глубину,
    # поэтому ближние честно перекрывают дальние, а стены отсекают то, что за ними
    from planner.scene import compile_scene
    zbuf = compile_scene(room, [], cam)['depth'].copy()
    ex, _, ez = cam.eye
    order = sorted(id_map.items(), key=lambda kv: -((by[kv[1]].x - ex) ** 2 + (by[kv[1]].y - ez) ** 2)
                   if kv[1] in by else 0)

    total = 0
    angled: list[str] = []
    done_roles: list[str] = []
    for sid, role in order:
        if role in SKIP or (only and role != only) or role not in by:
            continue
        try:
            it, photo_path = product(n, role)
        except KeyError:
            continue
        if not os.path.exists(photo_path):
            print(f'  {role}: нет фото товара')
            continue
        px = paste_role(pano, zbuf, cam, by[role], by[role].item, cutout(photo_path))
        if px < 0:
            angled.append(role)
            print(f'  {role}: сильный ракурс — на нейросетевой проход')
            continue
        total += px
        if px:
            done_roles.append(role)
        print(f'  {role}: {px} px' if px else f'  {role}: не попал в кадр')
    img = Image.fromarray(pano)
    dst = f'{prefix}-pasted.jpg'
    img.save(dst, quality=93)
    refs = []
    for role in done_roles:
        try:
            refs.append(product(n, role)[1])
        except KeyError:
            pass
    steps.log(prefix, 'Ставим фотографии товаров на их места',
              params={'товаров вклеено': len(done_roles), 'предметы': done_roles,
                      'на нейросетевой проход (сильный ракурс)': angled,
                      'генераций': 0},
              inputs=[f'{prefix}-empty-clay.png'] + refs[:8], outputs=[dst],
              note='Вырезка товара ставится на пол лицом к камере, размер и место — из плана. '
                   'Это математика, не генерация: узнаваемость стопроцентная.')
    print(f'{dst}  (закрашено {total} px, генераций 0)'
          + (f'; на нейросетевой проход: {", ".join(angled)}' if angled else ''))
    json.dump(angled, open(f'{prefix}-angled.json', 'w'), ensure_ascii=False)
    if '--realism' in sys.argv:
        # доводка поверх ТОЧНОЙ геометрии: низкая сила — структура не уезжает
        from viz_base import fal_key, fal_run, uri_from_image
        img = Image.fromarray(pano)
        res = fal_run('fal-ai/fast-sdxl/image-to-image', {
            'prompt': ('Photorealistic interior photo of a living room, natural daylight, soft '
                       'shadows, matte walls, wooden floor. Keep every object exactly where it is.'),
            'negative_prompt': 'extra furniture, moved furniture, distorted perspective, text',
            'image_url': uri_from_image(img),
            'strength': float(os.environ.get('REALISM_STRENGTH', 0.35)),
            'num_inference_steps': 30, 'guidance_scale': 6.0,
            'image_size': {'width': img.width, 'height': img.height},
            'preserve_aspect_ratio': True, 'enable_safety_checker': False,
            'seed': int(os.environ.get('VIZ_SEED', 4242)),
        }, fal_key())
        url = (res.get('images') or [{}])[0].get('url')
        if url:
            import urllib.request as _u
            out = Image.open(io.BytesIO(_u.urlopen(url, timeout=240).read())).convert('RGB')
            out.resize(img.size).save(f'{prefix}-final.jpg', quality=93)
            steps.log(prefix, 'Доводим до фотореализма', model='fal-ai/fast-sdxl/image-to-image',
                      prompt='Photorealistic interior photo…',
                      params={'сила': os.environ.get('REALISM_STRENGTH', 0.35)},
                      inputs=[f'{prefix}-pasted.jpg'], outputs=[f'{prefix}-final.jpg'],
                      note='Открытый вопрос: без управления глубиной на большой силе модель '
                           'начинает пересочинять комнату.')
            print(f'{prefix}-final.jpg  (реализм поверх точной геометрии)')
        return
    if '--finish' in sys.argv:
        # Доводка ТОЛЬКО по кайме вокруг предметов: модель получает маску-полоску, поэтому
        # физически не может ни перекрасить товар, ни дорисовать шкаф на пустой стене.
        from scipy import ndimage
        from viz_objects import edit_gpt_raw
        obj = ids > 0
        band = ndimage.binary_dilation(obj, iterations=26) & ~ndimage.binary_erosion(obj, iterations=5)
        img = Image.fromarray(pano)
        pr = ('Photo of a living room where furniture was composited in. Blend it into the scene: '
              'add soft contact shadows on the floor under each piece, soften the pasted outlines, '
              'match the room lighting. Do not change the furniture itself and do not add anything.')
        edited = edit_gpt_raw([img.resize((1536, 1024))], pr, size='1536x1024',
                              mask=Image.fromarray((band * 255).astype(np.uint8)).resize((1536, 1024)))
        edited.resize(img.size).save(f'{prefix}-final.jpg', quality=93)
        print(f'{prefix}-final.jpg  (доводка по кайме, 1 вызов)')
        return
    if '--gpt-frames' in sys.argv:
        roles = [r for _, r in id_map.items() if r not in SKIP and r in by]
        sheet, names = ref_sheet(n, roles)
        from pano_views import crop_view
        meta = json.load(open(f'{prefix}-frame.json'))
        for yaw, name in ((-45.0, 'left'), (0.0, 'center'), (45.0, 'right')):
            view = crop_view(pano, meta['camera']['fov'], yaw, 65.0, (1536, 1024))
            out = harmonize_gpt(view, sheet, names)
            out.save(f'{prefix}-{name}-gpt.jpg', quality=93)
            print(f'{prefix}-{name}-gpt.jpg  (кадр + лист референсов, 1 вызов)')
        sheet.save(f'{prefix}-refsheet.jpg', quality=90)
        return
    if '--harmonize' in sys.argv:
        out = harmonize(img)
        dst2 = f'{prefix}-final.jpg'
        out.save(dst2, quality=93)
        print(f'{dst2}  (согласование: 1 вызов {HARMONIZE})')


if __name__ == '__main__':
    main()
