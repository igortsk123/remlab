#!/usr/bin/env python3
"""Ф1: базовый кадр по КАРТЕ ГЛУБИНЫ через fal.ai (план viz-scene-compiler).

Модель получает не «картинку-подсказку», а управляющий сигнал: глубину сцены, посчитанную из
нашей геометрии. Композицию она изменить не может. Товары здесь ещё не врисовываются — это Ф2.

  ~/venvs/scout/bin/python viz_base.py 21 A            # базовый кадр камеры A
  ~/venvs/scout/bin/python viz_base.py 21 A --model sd15
"""
import base64
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
SCENE_DIR = os.environ.get('SCENE_DIR', '/tmp/room-scene')

MODELS = {
    # union принимает контроли ИМЕНОВАННЫМИ полями (depth/canny/openpose...), а не общим
    # control_image_url — иначе 422 «ControlNet must be enabled» (проверено 2026-08-04)
    'sdxl': ('fal-ai/sdxl-controlnet-union', 'depth_image_url'),
    'sd15': ('fal-ai/sd15-depth-controlnet', 'control_image_url'),
    # доводка поверх готового изображения сцены: union — text2img, image_url там игнорируется
    'i2i': ('fal-ai/fast-sdxl/image-to-image', None),
}


def fal_key() -> str:
    k = os.environ.get('FAL_KEY')
    if k:
        return k
    for p in ('/home/pakar/mltest/.env', os.path.join(HERE, '../../.env')):
        try:
            for line in open(p):
                m = re.match(r'FAL_KEY=(.+)', line.strip())
                if m:
                    return m.group(1).strip().strip('"')
        except OSError:
            continue
    raise SystemExit('нет FAL_KEY — см. .memory_bank/_secrets/ACCESS.md')


def depth_for_controlnet(path: str) -> str:
    """Наша глубина: тёмное = близко. ControlNet ждёт обратного (MiDaS: близко = светлое)."""
    d = np.asarray(Image.open(path)).astype(np.float32)
    d = (d - d.min()) / max(d.max() - d.min(), 1e-6)
    inv = (1.0 - d) ** 0.7                      # гамма: подчеркнуть передний план
    img = Image.fromarray((inv * 255).astype(np.uint8)).convert('RGB')
    buf = io.BytesIO()
    img.save(buf, 'PNG')
    return 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode()


def img_uri(path: str) -> str:
    """Готовое изображение сцены (clay) как data-URI — основа для доводки."""
    buf = io.BytesIO()
    Image.open(path).convert('RGB').save(buf, 'PNG')
    return 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode()


def fal_run(model: str, payload: dict, key: str, timeout: int = 300) -> dict:
    req = urllib.request.Request(
        f'https://queue.fal.run/{model}',
        data=json.dumps(payload).encode(),
        headers={'Authorization': f'Key {key}', 'Content-Type': 'application/json'},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            job = json.loads(r.read())
    except urllib.error.HTTPError as e:      # 422 = не тот набор полей: показываем схему ошибки
        raise SystemExit(f'fal {e.code}: {e.read().decode()[:600]}')
    status_url = job.get('status_url') or job.get('response_url')
    t0 = time.time()
    while time.time() - t0 < timeout:
        time.sleep(3)
        sreq = urllib.request.Request(status_url, headers={'Authorization': f'Key {key}'})
        with urllib.request.urlopen(sreq, timeout=60) as r:
            st = json.loads(r.read())
        if st.get('status') == 'COMPLETED':
            time.sleep(1)
            rreq = urllib.request.Request(job['response_url'], headers={'Authorization': f'Key {key}'})
            try:
                with urllib.request.urlopen(rreq, timeout=60) as r:
                    return json.loads(r.read())
            except urllib.error.HTTPError as e:
                raise SystemExit(f'fal результат {e.code}: {e.read().decode()[:500]}')
        if st.get('status') in ('FAILED', 'ERROR'):
            raise SystemExit(f'fal: {json.dumps(st)[:400]}')
    raise SystemExit('fal: таймаут ожидания результата')


def main() -> None:
    n = int(sys.argv[1])
    view = sys.argv[2] if len(sys.argv) > 2 else 'A'
    which = sys.argv[sys.argv.index('--model') + 1] if '--model' in sys.argv else 'sdxl'
    model, ctrl_field = MODELS[which]
    prefix = os.path.join(SCENE_DIR, f'scene{n}-{view}')
    meta = json.load(open(f'{prefix}-frame.json'))
    sets = json.load(open(os.path.join(HERE, 'sets3.json')))
    s = sets[n - 1]

    style_block = ''
    if s.get('style'):
        sp = json.load(open(os.path.join(HERE, 'styles.json')))['styles']
        if s['style'] in sp:
            style_block = ' ' + sp[s['style']]['prompt']

    visible = ', '.join(meta['visible'])
    shot = ('Orthographic doll-house top view of a living room, camera straight above, walls cut '
            'away at 1.2 m' if view == 'T' else
            'Photorealistic interior photo of a small city-flat living room, ceiling 2.7 m')
    prompt = (
        f'{shot}. '
        'The depth map defines the room and the furniture volumes exactly: keep every wall, '
        'window, door and furniture piece where the depth map puts them, with the same size. '
        f'In the frame: {visible}. Nothing else — do not add furniture, lamps, rugs or plants.'
        + style_block +
        ' Neutral matte upholstery and wood for the furniture (exact products are applied later), '
        'natural daylight, soft shadows, honest small-flat scale. No people, no text, no watermarks.'
    )

    key = fal_key()
    payload = {
        'prompt': prompt,
        'negative_prompt': 'extra furniture, duplicated objects, distorted perspective, text, watermark',
        'num_inference_steps': 30,
        'guidance_scale': 6.0,
        **({ctrl_field: depth_for_controlnet(f'{prefix}-depth16.png')} if ctrl_field else {}),
        # без явного размера модель отдаёт квадрат 1024² и кадр не совпадает с картой (2026-08-04)
        'image_size': {'width': meta['camera']['size'][0], 'height': meta['camera']['size'][1]},
    }
    if which == 'i2i' or '--from-clay' in sys.argv:
        # вид сверху: ортокарта глубины почти плоская, чистого depth-контроля не хватает — модель
        # рисовала планировку чужой квартиры. Поэтому идём доводкой поверх clay-рендера сцены.
        payload['image_url'] = img_uri(f'{prefix}-clay.png')
        payload['strength'] = float(os.environ.get('CLAY_STRENGTH', 0.42))
    if which == 'i2i':
        payload.pop('image_size', None)           # размер берётся из основы
        # без этого fal возвращает ЧЁРНЫЙ кадр: safety-checker ложно срабатывает на clay-рендере
        payload['enable_safety_checker'] = False
    if which == 'sdxl':
        payload['depth_preprocess'] = False       # карта уже готова, препроцесс не нужен
    t0 = time.time()
    out = fal_run(model, payload, key)
    url = (out.get('images') or [{}])[0].get('url')
    if not url:
        raise SystemExit(f'fal вернул без картинки: {json.dumps(out)[:300]}')
    img = urllib.request.urlopen(url, timeout=120).read()
    dst = f'{prefix}-base-{which}.jpg'
    open(dst, 'wb').write(img)
    print(f'{dst}  ({time.time() - t0:.0f} с, модель {model})')


if __name__ == '__main__':
    main()
