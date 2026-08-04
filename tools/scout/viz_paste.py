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

# Плоские/мелкие роли не вклеиваем: у ковра и люстры фронтальной грани нет, декор не опознаётся
SKIP = {'ковёр', 'ковер', 'люстра', 'тв', 'кашпо', 'ваза', 'лампа', 'подушка', 'подушка 2', 'плед'}


CUTOUT = 'fal-ai/birefnet'          # вырезание фона: разово на товар, ~1 цент, кэш навсегда


def cutout(path: str) -> Image.Image:
    """Фото товара без фона (RGBA). Кэшируется рядом: `-cut.png`.

    Без этого вклейка тащит в кадр подложку карточки — у дивана белый ореол, у столика синий
    прямоугольник (поймано 2026-08-04).
    """
    dst = os.path.splitext(path)[0] + '-cut.png'
    if os.path.exists(dst):
        return Image.open(dst).convert('RGBA')
    src = Image.open(path).convert('RGB')
    res = fal_run(CUTOUT, {'image_url': uri_from_image(src)}, fal_key())
    url = (res.get('image') or {}).get('url') or (res.get('images') or [{}])[0].get('url')
    if not url:
        return src.convert('RGBA')
    import urllib.request as _u
    open(dst, 'wb').write(_u.urlopen(url, timeout=120).read())
    return Image.open(dst).convert('RGBA')


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


def paste_role(pano: np.ndarray, ids: np.ndarray, sid: int, cam, p, it,
               photo: Image.Image) -> int:
    """Проецирует фото товара на его грань. Возвращает число закрашенных пикселей."""
    H, W = pano.shape[:2]
    eye, fwd, right, up = cam.basis()
    fv = (H / 2) / math.tan(math.radians(cam.vfov_deg) / 2)
    mask = ids == sid
    if mask.sum() < 200:
        return 0
    ys, xs = np.where(mask)

    if cam.cyl:                                            # панорама
        ang = (xs - W / 2) / W * math.radians(cam.fov_deg)
        dirs = (fwd[None, :] * np.cos(ang)[:, None]
                + right[None, :] * np.sin(ang)[:, None]
                + up[None, :] * ((H / 2 - ys) / fv)[:, None])
    else:                                                  # обычный кадр со сдвигом объектива
        focal = (W / 2) / math.tan(math.radians(cam.fov_deg) / 2)
        dirs = (fwd[None, :] * focal
                + right[None, :] * (xs - W / 2)[:, None]
                + up[None, :] * (H / 2 + cam.shift_y * H - ys)[:, None])

    corner, wvec, n, w_cm, h_cm = face_of(p, it)
    # Вклеивать фронтальное фото имеет смысл, только пока грань РАЗВЁРНУТА к нам. У комода и
    # ТВ-тумбы на боковой стене угол 3° — мы видим их с торца, фото туда натягивать бессмысленно;
    # такие предметы уходят на дешёвый нейросетевой проход (замечание владельца 2026-08-04).
    centre = corner + wvec / 2 + np.array([0.0, h_cm / 2, 0.0])
    look = centre - eye
    look = look / max(float(np.linalg.norm(look)), 1e-6)
    face_deg = 90.0 - math.degrees(math.acos(min(1.0, abs(float(look @ n)))))
    if face_deg < float(os.environ.get('PASTE_MIN_ANGLE', 40)):
        return -1
    denom = dirs @ n
    with np.errstate(divide='ignore', invalid='ignore'):
        t = ((corner - eye) @ n) / denom
    hit = eye[None, :] + dirs * t[:, None]
    s = ((hit - corner[None, :]) @ wvec) / (w_cm ** 2)      # доля по ширине грани
    v = hit[:, 1] / max(h_cm, 1e-6)                         # доля по высоте
    ok = np.isfinite(t) & (t > 0) & (s >= -0.02) & (s <= 1.02) & (v >= -0.02) & (v <= 1.02)
    if ok.sum() < 200:
        return 0

    cut = trim_alpha(photo)
    src = np.asarray(cut)
    sh, sw = src.shape[:2]
    px = np.clip((s[ok] * (sw - 1)).astype(int), 0, sw - 1)
    py = np.clip(((1 - v[ok]) * (sh - 1)).astype(int), 0, sh - 1)
    rgb = src[py, px][:, :3]
    alpha = (src[py, px][:, 3] > 128) if src.shape[2] > 3 else np.ones(len(px), bool)
    yy, xx = ys[ok][alpha], xs[ok][alpha]
    pano[yy, xx] = rgb[alpha]
    return int(alpha.sum())


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
    base = f'{prefix}-base-clean.jpg'
    if not os.path.exists(base):
        base = f'{prefix}-base-sdxl.jpg'
    pano = np.asarray(Image.open(base).convert('RGB')).copy()
    H, W = pano.shape[:2]
    inst = Image.open(f'{prefix}-instances.png').convert('RGB').resize((W, H), Image.NEAREST)
    ids = np.asarray(inst)[..., 0] // 8
    id_map = json.load(open(f'{prefix}-frame.json'))['ids']

    room, placements = load_scene(n)
    cam = next(c for c in cameras_for(room, placements) if c.name == cam_name)
    by = {p.role: p for p in placements}

    total = 0
    angled: list[str] = []
    for sid, role in id_map.items():
        if role in SKIP or (only and role != only) or role not in by:
            continue
        try:
            it, photo_path = product(n, role)
        except KeyError:
            continue
        if not os.path.exists(photo_path):
            print(f'  {role}: нет фото товара')
            continue
        px = paste_role(pano, ids, int(sid), cam, by[role], by[role].item,
                        cutout(photo_path))
        if px < 0:
            angled.append(role)
            print(f'  {role}: сильный ракурс — на нейросетевой проход')
            continue
        total += px
        print(f'  {role}: {px} px' if px else f'  {role}: грань не попала в кадр')
    img = Image.fromarray(pano)
    dst = f'{prefix}-pasted.jpg'
    img.save(dst, quality=93)
    print(f'{dst}  (закрашено {total} px, генераций 0)'
          + (f'; на нейросетевой проход: {", ".join(angled)}' if angled else ''))
    json.dump(angled, open(f'{prefix}-angled.json', 'w'), ensure_ascii=False)
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
