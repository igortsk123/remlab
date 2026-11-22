#!/usr/bin/env python3
"""Marigold V2 albedo ОДНОЙ картинки через ComfyUI на ноде (T-20261120-160/1, директор 21.11: снимаем свет с ФОТО до переноса, без Blender и запекания).
Тот же граф, что строит аддон StableGen (`texturing/workflows.py: generate_marigold_v2_map`, задача albedo): один детерминированный шаг (сигмы 0.5 → 0), без шума,
`ModelSamplingAuraFlow(img_to_img_velocity)`; отличие одно — вместо `SaveImageWebsocket` стоит `SaveImage` (забираем по HTTP, веб-сокет не нужен).
Ходит к ноде через мост `sg_relay.py` (127.0.0.1:порт). Только стандартная библиотека + Pillow (на DEV есть).

  python sg_v2_albedo.py --server 127.0.0.1:18190 --in вырезка.rgba.png --out albedo.png [--max-res 1024] [--bg 200]
Вход с альфой кладётся на серый фон (--bg, как у проб IID на CPU) — albedo считается по картинке, а не по прозрачности. Выход — PNG того же размера, что вход; рядом `<out>.json`
(размер обработки, секунды, id задачи). Код выхода 0 — файл записан."""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

BASE = 'qwen_image_edit_2509_int8_convrot.safetensors'
LORA = 'marigold_v2_albedo.safetensors'
VAE = 'marigold_v2_albedo_vae.safetensors'
COND = 'marigold_v2_albedo_conditioning.safetensors'


def proc_size(w: int, h: int, max_res: int) -> tuple[int, int]:
    """Как в аддоне: самая длинная сторона — в пределах [1024, max_res], обе кратны 16."""
    longest = min(max(max(w, h), 1024), max_res)
    scale = longest / max(w, h)
    return max(16, int(round(w * scale / 16)) * 16), max(16, int(round(h * scale / 16)) * 16)


def build_prompt(uploaded: str, pw: int, ph: int, prefix: str = 'mv2') -> dict:
    return {
        '1': {'class_type': 'LoadImage', 'inputs': {'image': uploaded}},
        '2': {'class_type': 'ImageScale', 'inputs': {'image': ['1', 0], 'upscale_method': 'lanczos', 'width': pw, 'height': ph, 'crop': 'disabled'}},
        '3': {'class_type': 'UNETLoader', 'inputs': {'unet_name': BASE, 'weight_dtype': 'default'}},
        '4': {'class_type': 'LoraLoaderModelOnly', 'inputs': {'model': ['3', 0], 'lora_name': LORA, 'strength_model': 1.0}},
        '5': {'class_type': 'ModelSamplingAuraFlow', 'inputs': {'model': ['4', 0], 'shift': 1.73, 'sampling': 'img_to_img_velocity'}},
        '6': {'class_type': 'ConditioningLoader', 'inputs': {'conditioning_name': COND}},
        '7': {'class_type': 'VAELoader', 'inputs': {'vae_name': VAE}},
        '8': {'class_type': 'VAEEncode', 'inputs': {'pixels': ['2', 0], 'vae': ['7', 0]}},
        '9': {'class_type': 'DisableNoise', 'inputs': {}},
        '10': {'class_type': 'KSamplerSelect', 'inputs': {'sampler_name': 'euler'}},
        '11': {'class_type': 'ManualSigmas', 'inputs': {'sigmas': '0.5, 0'}},
        '12': {'class_type': 'BasicGuider', 'inputs': {'model': ['5', 0], 'conditioning': ['6', 0]}},
        '13': {'class_type': 'SamplerCustomAdvanced', 'inputs': {'noise': ['9', 0], 'guider': ['12', 0], 'sampler': ['10', 0], 'sigmas': ['11', 0], 'latent_image': ['8', 0]}},
        '14': {'class_type': 'VAEDecode', 'inputs': {'samples': ['13', 0], 'vae': ['7', 0]}},
        '15': {'class_type': 'MarigoldV2PostProcess', 'inputs': {'image': ['14', 0], 'prediction': 'albedo'}},
        '16': {'class_type': 'SaveImage', 'inputs': {'images': ['15', 0], 'filename_prefix': prefix}},
    }


def multipart(fields: dict, file_field: str, filename: str, data: bytes) -> tuple[bytes, str]:
    b = uuid.uuid4().hex
    out = io.BytesIO()
    for k, v in fields.items():
        out.write(f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    out.write(f'--{b}\r\nContent-Disposition: form-data; name="{file_field}"; filename="{filename}"\r\nContent-Type: image/png\r\n\r\n'.encode())
    out.write(data)
    out.write(f'\r\n--{b}--\r\n'.encode())
    return out.getvalue(), f'multipart/form-data; boundary={b}'


def http(server: str, path: str, data: bytes | None = None, headers: dict | None = None, timeout: int = 120, retries: int = 3):
    """Один запрос с повторами при сбоях связи (мост/шлюз иногда отвечает 5xx/403-страницей)."""
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(f'http://{server}{path}', data=data, headers=headers or {})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            body = e.read()
            if e.code < 500 and e.code != 403:
                return e.code, body
            last = f'HTTP {e.code}: {body[:200]!r}'
        except (urllib.error.URLError, OSError) as e:
            last = f'{type(e).__name__}: {e}'
        time.sleep(3 * (i + 1))
    raise RuntimeError(f'связь с нодой не удалась ({path}): {last}')


def flatten(path: str, bg: int):
    from PIL import Image
    im = Image.open(path).convert('RGBA')
    base = Image.new('RGB', im.size, (bg, bg, bg))
    base.paste(im, mask=im.split()[3])
    return base


def run(server: str, in_path: str, out_path: str, max_res: int = 1024, bg: int = 200, timeout_s: int = 1500, say=print) -> dict:
    from PIL import Image
    t0 = time.time()
    img = flatten(in_path, bg)
    w, h = img.size
    pw, ph = proc_size(w, h, max_res)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    name = f'mv2-{uuid.uuid4().hex[:10]}.png'
    body, ctype = multipart({'type': 'input', 'overwrite': 'true'}, 'image', name, buf.getvalue())
    code, resp = http(server, '/upload/image', body, {'Content-Type': ctype})
    if code != 200:
        raise RuntimeError(f'загрузка картинки: HTTP {code} {resp[:200]!r}')
    uploaded = json.loads(resp)['name']
    say(f'загружено {uploaded} ({w}×{h}), обработка {pw}×{ph}')
    payload = json.dumps({'prompt': build_prompt(uploaded, pw, ph), 'client_id': uuid.uuid4().hex}).encode()
    code, resp = http(server, '/prompt', payload, {'Content-Type': 'application/json'})
    if code != 200:
        raise RuntimeError(f'ComfyUI отклонил граф: HTTP {code} {resp[:600]!r}')
    pid = json.loads(resp)['prompt_id']
    t_sub = time.time()
    entry = None
    while time.time() - t_sub < timeout_s:
        code, resp = http(server, f'/history/{pid}', timeout=60)
        hist = json.loads(resp) if code == 200 and resp else {}
        if pid in hist:
            entry = hist[pid]
            st = (entry.get('status') or {})
            if st.get('status_str') == 'error':
                msgs = [m for m in (st.get('messages') or []) if m and m[0] == 'execution_error']
                raise RuntimeError(f'ComfyUI: ошибка выполнения: {json.dumps(msgs, ensure_ascii=False)[:800]}')
            if entry.get('outputs'):
                break
        time.sleep(3)
    if not entry or not entry.get('outputs'):
        raise RuntimeError(f'нет результата за {timeout_s} с (prompt {pid})')
    im0 = entry['outputs']['16']['images'][0]
    q = urllib.parse.urlencode({'filename': im0['filename'], 'subfolder': im0.get('subfolder', ''), 'type': im0.get('type', 'output')})
    code, data = http(server, f'/view?{q}', timeout=120)
    if code != 200:
        raise RuntimeError(f'выдача результата: HTTP {code}')
    out = Image.open(io.BytesIO(data)).convert('RGB')
    if out.size != (w, h):
        out = out.resize((w, h), Image.LANCZOS)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    out.save(out_path)
    info = {'in': in_path, 'size': [w, h], 'proc': [pw, ph], 'sec_total': round(time.time() - t0, 1), 'sec_graph': round(time.time() - t_sub, 1), 'prompt_id': pid, 'max_res': max_res, 'bg': bg}
    json.dump(info, open(out_path + '.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    say(f'albedo записан: {out_path} ({info["sec_graph"]} с на граф)')
    return info


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--server', required=True)
    ap.add_argument('--in', dest='inp', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--max-res', type=int, default=1024)
    ap.add_argument('--bg', type=int, default=200)
    ap.add_argument('--timeout', type=int, default=1500)
    a = ap.parse_args()
    try:
        run(a.server, a.inp, a.out, a.max_res, a.bg, a.timeout)
    except Exception as e:  # noqa: BLE001
        print(f'ОШИБКА: {type(e).__name__}: {e}', file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
