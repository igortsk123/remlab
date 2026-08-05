#!/usr/bin/env python3
"""Фотореалистичная ПУСТАЯ комната по нашим картам — основа под вклейку товаров.

Зачем. Раньше товары клеились в наш clay-рендер: геометрия точная, но фон плоский, и доводящей
модели приходилось выдумывать свет, пол и стены с нуля — оттуда уезжал угол и появлялись лишние
предметы. Здесь фон делает ControlNet по НАШЕЙ карте глубины: геометрия остаётся нашей, а пол,
стены и свет становятся фотографическими (проверено 2026-08-05: приёмка вклейки 9 из 10).

Отправляем только карты и текст — фотографии товаров этот эндпоинт не принимает, да они тут и не
нужны: комната пустая, товары ставим сами.

Основа НЕ зависит от набора мебели, поэтому кэшируется по комнате и точке съёмки.

  ~/venvs/scout/bin/python shell_make.py 21 --cams C1,C2
"""
import io
import json
import os
import sys
import time
import urllib.request

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
SCENE_DIR = os.environ.get('SCENE_DIR', os.path.expanduser('~/scout-scenes'))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '../../services/planner-solver'))

from viz_base import depth_for_controlnet, fal_key, fal_run, uri_from_image  # noqa: E402

MODEL = 'fal-ai/sdxl-controlnet-union'
NEG = ('furniture, sofa, table, chairs, plants, decor, pictures, rug, cornice, crown moulding, '
       'spotlights, downlights, chandelier, lamps, clutter, text, watermark, cartoon, cgi render')


def normal_map(depth_path: str) -> Image.Image:
    """Карта нормалей из нашей же глубины: ориентация каждой поверхности, свет ложится честнее."""
    d = np.asarray(Image.open(depth_path)).astype(np.float32)
    if d.ndim == 3:
        d = d[..., 0]
    d = d / max(d.max(), 1)
    gy, gx = np.gradient(d)
    n = np.dstack([-gx, -gy, np.ones_like(d) * 0.02])
    n /= np.linalg.norm(n, axis=2, keepdims=True) + 1e-6
    return Image.fromarray(((n * 0.5 + 0.5) * 255).astype(np.uint8))


def style_words(n: int) -> str:
    """Отделка берётся из паспорта стиля комплекта — иначе доводка перекрашивает комнату дважды."""
    try:
        from viz_final import style_brief, style_name
        return f'{style_name(n)} style: {style_brief(n)}'
    except Exception:  # noqa: BLE001 — нет паспорта: нейтральная отделка
        return 'light oak plank floor, warm-white plaster walls, white flat skirting'


def make_shell(n: int, cam: str, key: str, force: bool = False) -> str:
    prefix = os.path.join(SCENE_DIR, f'scene{n}-{cam}')
    dst = f'{prefix}-shell.jpg'
    if os.path.exists(dst) and not force:
        return dst
    depth = f'{prefix}-empty-depth16.png'
    sem = f'{prefix}-empty-semantic.png'
    prompt = ('photorealistic interior photograph of an EMPTY room, no furniture at all, '
              + style_words(n) + ', plain flat ceiling with no mouldings and no spotlights, '
              'soft natural daylight, professional interior photography, 24 mm lens')
    payload = {
        'prompt': prompt, 'negative_prompt': NEG,
        'depth_image_url': depth_for_controlnet(depth),
        'normal_image_url': uri_from_image(normal_map(depth)),
        'depth_preprocess': False, 'normal_preprocess': False,
        'controlnet_conditioning_scale': 0.85,
        'image_size': {'width': 1344, 'height': 896},
        'num_inference_steps': 30, 'guidance_scale': 6.0, 'seed': 4242,
    }
    if os.path.exists(sem):
        payload['segmentation_image_url'] = uri_from_image(Image.open(sem).convert('RGB'))
        payload['segmentation_preprocess'] = False
    t0 = time.time()
    res = fal_run(MODEL, payload, key, timeout=900)
    url = (res.get('images') or [{}])[0].get('url')
    if not url:
        raise RuntimeError('основа не сгенерировалась')
    raw = urllib.request.urlopen(url, timeout=300).read()
    Image.open(io.BytesIO(raw)).convert('RGB').save(dst, quality=93)
    json.dump({'model': MODEL, 'prompt': prompt, 'seconds': round(time.time() - t0)},
              open(f'{prefix}-shell.json', 'w'), ensure_ascii=False, indent=1)
    print(f'{cam}: основа за {time.time() - t0:.0f} с → {dst}', flush=True)
    return dst


def main() -> None:
    n = int(sys.argv[1])
    cams = (sys.argv[sys.argv.index('--cams') + 1].split(',')
            if '--cams' in sys.argv else ['C1', 'C2'])
    key = fal_key()
    for cam in cams:
        print(make_shell(n, cam, key, force='--force' in sys.argv))


if __name__ == '__main__':
    main()
