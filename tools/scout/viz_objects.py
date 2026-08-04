#!/usr/bin/env python3
"""Ф2: врисовка КОНКРЕТНОГО товара в кадр по его маске (план viz-object-binding).

Ф1 добилась того, что предмет стоит на своём месте. Здесь он должен стать нашим товаром.
Маска берётся из НАШЕЙ геометрии (`instances.png`), а не угадывается сегментацией.

Два механизма (проба выбирает победителя):
  ref   — `fal-ai/nano-banana/edit`: на вход сцена И фотография товара, замена по описанию;
  mask  — `fal-ai/inpaint`: классический инпейнт по маске, товар только словами (контроль).

Результат всегда собирается обратно ЧЕРЕЗ МАСКУ: за её пределами пиксели исходного кадра
остаются нетронутыми — модель физически не может переставить соседей.

  ~/venvs/scout/bin/python viz_objects.py 21 диван --view center
  ~/venvs/scout/bin/python viz_objects.py 21 диван --mech mask
"""
import base64
import io
import json
import os
import re
import sys
import urllib.request
import uuid

import numpy as np
from PIL import Image, ImageFilter

from pano_views import crop_view
from viz_base import fal_key, fal_run, uri_from_image

HERE = os.path.dirname(os.path.abspath(__file__))
SCENE_DIR = os.environ.get('SCENE_DIR', os.path.expanduser('~/scout-scenes'))
MECHS = {'ref': 'fal-ai/nano-banana/edit', 'mask': 'fal-ai/inpaint',
         'gpt': 'openai/gpt-image-2 (images/edits)'}   # умеет и маску, и референсы разом
YAW = {'left': -45.0, 'center': 0.0, 'right': 45.0}


def product(n: int, role: str) -> tuple[dict, str]:
    """Карточка товара и путь к ПОЛНОРАЗМЕРНОМУ фото.

    Миниатюры `thumbs/` — 100 px по длинной стороне: по ним узнаваемость передать нельзя
    (поймано 2026-08-04). Полное фото берём из фида (`img`) и кэшируем в `refs/`.
    """
    s = json.load(open(os.path.join(HERE, 'sets3.json')))[n - 1]
    it = s['items'][role]
    key = re.sub(r'[^A-Za-z0-9]', '_', str(it['eid']))[:40]
    big = os.path.join(HERE, 'refs', f"{it['mid']}-{key}.jpg")
    if not os.path.exists(big) and it.get('img'):
        url = it['img']
        url = 'https:' + url if url.startswith('//') else url
        os.makedirs(os.path.dirname(big), exist_ok=True)
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=60) as r:
            open(big, 'wb').write(r.read())
    if os.path.exists(big):
        return it, big
    return it, os.path.join(HERE, 'thumbs', f"{it['mid']}-{key}.png")


def masks_for_view(n: int, view: str, size: tuple[int, int]) -> tuple[np.ndarray, dict]:
    """Маски объектов в системе ВЫРЕЗАННОГО кадра: та же геометрия, что и у картинки."""
    prefix = os.path.join(SCENE_DIR, f'scene{n}-P')
    meta = json.load(open(f'{prefix}-frame.json'))
    inst = np.asarray(Image.open(f'{prefix}-instances.png').convert('RGB'))
    if view in YAW:
        ids = crop_view(inst, meta['camera']['fov'], YAW[view], 65.0, size, nearest=True)
        ids = np.asarray(ids)
    else:
        ids = np.asarray(Image.fromarray(inst).resize(size, Image.NEAREST))
    return ids[..., 0] // 8, meta['ids']


def on_white(path: str, box: int = 1024) -> Image.Image:
    """Фото товара на белом фоне — прозрачность модели только мешает."""
    im = Image.open(path).convert('RGBA')
    im.thumbnail((box, box))
    bg = Image.new('RGBA', im.size, (255, 255, 255, 255))
    bg.alpha_composite(im)
    return bg.convert('RGB')


def edit_ref(scene: Image.Image, ref: Image.Image, role: str, name: str, key: str) -> Image.Image:
    prompt = (
        f'Replace ONLY the {role} in the first image with the exact {role} shown in the second '
        'image: same fabric, same colour, same shape, same proportions. Keep it in exactly the '
        'same position and the same size as the piece it replaces. Do not move, resize or change '
        'anything else in the room — walls, floor, window, other furniture, decor and lighting '
        'must stay pixel-identical. Photorealistic interior photo. '
        f'Product: {name}.'
    )
    res = fal_run(MECHS['ref'], {
        'prompt': prompt,
        'image_urls': [uri_from_image(scene), uri_from_image(ref)],
        'num_images': 1,
        'output_format': 'png',
    }, key)
    url = (res.get('images') or [{}])[0].get('url')
    if not url:
        raise SystemExit(f'nano-banana без картинки: {json.dumps(res)[:300]}')
    return Image.open(io.BytesIO(urllib.request.urlopen(url, timeout=180).read())).convert('RGB')


def edit_mask(scene: Image.Image, mask: Image.Image, role: str, name: str, key: str) -> Image.Image:
    res = fal_run(MECHS['mask'], {
        'prompt': f'{name} — {role}, photorealistic, exact same position and size, interior photo',
        'negative_prompt': 'different furniture type, extra objects, distorted perspective',
        'image_url': uri_from_image(scene),
        'mask_url': uri_from_image(mask.convert('RGB')),
        'num_inference_steps': 30,
    }, key)
    url = (res.get('images') or [{}])[0].get('url')
    if not url:
        raise SystemExit(f'inpaint без картинки: {json.dumps(res)[:300]}')
    return Image.open(io.BytesIO(urllib.request.urlopen(url, timeout=180).read())).convert('RGB')


def edit_gpt(scene: Image.Image, ref: Image.Image, mask: np.ndarray,
             role: str, name: str) -> Image.Image:
    """OpenAI images/edits: принимает и маску, и фотографию товара в одном запросе.

    Маска в их формате — ПРОЗРАЧНОЕ там, где разрешено рисовать (обратная нашей).
    """
    oai = os.environ.get('OPENAI_API_KEY') or _dotenv('OPENAI_API_KEY')
    if not oai:
        raise SystemExit('нет OPENAI_API_KEY — см. .memory_bank/_secrets/ACCESS.md')
    w, h = scene.size
    hole = Image.fromarray(np.dstack([np.zeros((h, w, 3), np.uint8),
                                      ((~mask) * 255).astype(np.uint8)]), 'RGBA')
    prompt = (f'Replace the {role} with the exact product from the reference photo: same fabric, '
              f'colour, shape and proportions, same position and size. Photorealistic interior '
              f'photo, consistent light. Product: {name}.')

    def png(im):
        b = io.BytesIO()
        im.save(b, 'PNG')
        return b.getvalue()

    B = uuid.uuid4().hex
    body = io.BytesIO()

    def part(field, val, fname=None, ctype=None):
        body.write(f'--{B}\r\n'.encode())
        if fname:
            body.write(f'Content-Disposition: form-data; name="{field}"; filename="{fname}"\r\n'
                       f'Content-Type: {ctype}\r\n\r\n'.encode())
            body.write(val)
            body.write(b'\r\n')
        else:
            body.write(f'Content-Disposition: form-data; name="{field}"\r\n\r\n{val}\r\n'.encode())

    part('model', 'gpt-image-2')
    part('prompt', prompt)
    part('size', '1536x1024')
    part('quality', 'high')
    part('n', '1')
    part('image[]', png(scene), 'scene.png', 'image/png')
    part('image[]', png(ref), 'product.png', 'image/png')
    part('mask', png(hole), 'mask.png', 'image/png')
    body.write(f'--{B}--\r\n'.encode())
    req = urllib.request.Request('https://api.openai.com/v1/images/edits', data=body.getvalue(),
                                 headers={'Authorization': f'Bearer {oai}',
                                          'Content-Type': f'multipart/form-data; boundary={B}'})
    with urllib.request.urlopen(req, timeout=900) as r:
        data = json.loads(r.read())
    return Image.open(io.BytesIO(base64.b64decode(data['data'][0]['b64_json']))).convert('RGB')


def _dotenv(name: str) -> str:
    for p in ('/home/pakar/mltest/.env', os.path.join(HERE, '../../.env'),
              os.path.join(HERE, '.env')):
        try:
            for line in open(p):
                m = re.match(rf'{name}=(.+)', line.strip())
                if m:
                    return m.group(1).strip().strip('"')
        except OSError:
            continue
    return ''


def blend(base: Image.Image, new: Image.Image, mask: np.ndarray, feather: int = 7) -> Image.Image:
    """Берём из результата ТОЛЬКО пиксели маски: остальное остаётся кадром Ф1."""
    new = new.resize(base.size)
    m = Image.fromarray((mask * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(feather))
    out = base.copy()
    out.paste(new, (0, 0), m)
    return out


def main() -> None:
    n = int(sys.argv[1])
    role = sys.argv[2]
    view = sys.argv[sys.argv.index('--view') + 1] if '--view' in sys.argv else 'center'
    mech = sys.argv[sys.argv.index('--mech') + 1] if '--mech' in sys.argv else 'ref'
    prefix = os.path.join(SCENE_DIR, f'scene{n}-P')
    scene = Image.open(f'{prefix}-{view}.jpg').convert('RGB')
    ids, id_map = masks_for_view(n, view, scene.size)
    sid = next((int(k) for k, v in id_map.items() if v == role), None)
    if sid is None:
        raise SystemExit(f'роли {role} нет в сцене: {sorted(id_map.values())}')
    mask = (ids == sid)
    if mask.sum() < 500:
        raise SystemExit(f'{role} почти не виден в кадре {view}: {int(mask.sum())} px')
    it, photo = product(n, role)
    if not os.path.exists(photo):
        raise SystemExit(f'нет фото товара: {photo}')

    key = fal_key() if mech != 'gpt' else ''
    name = (it.get('name') or role)[:90]
    if mech == 'ref':
        edited = edit_ref(scene, on_white(photo), role, name, key)
    elif mech == 'gpt':
        edited = edit_gpt(scene, on_white(photo), mask, role, name)
    else:
        edited = edit_mask(scene, Image.fromarray((mask * 255).astype(np.uint8)), role, name, key)
    out = blend(scene, edited, mask)
    dst = f'{prefix}-{view}-{role}-{mech}.jpg'
    out.save(dst, quality=93)
    edited.save(f'{prefix}-{view}-{role}-{mech}-raw.jpg', quality=90)
    print(f'{dst}  (маска {int(mask.sum())} px, {MECHS[mech]})')


if __name__ == '__main__':
    main()
