#!/usr/bin/env python3
"""ПОДДЕЛЬНЫЙ ComfyUI для бесплатной проверки аддона StableGen без видеокарты (T-20261119-90/5, этап 1, шаг А).
Говорит на том же протоколе, что аддон использует у настоящего ComfyUI (разобран по `stablegen/workflows.py`): /queue, /models/<папка>, /object_info/<узел>, /upload/image,
/prompt (POST), /ws (websocket: execution_start → executing → бинарный кадр SaveImageWebsocket → executing node=null), /history/<id>, /view.
«Рисует» не нейросеть, а предсказуемая заливка: берёт первую загруженную картинку (карта глубины/контекст) и красит её в оттенок, свой для каждого вызова по порядку, — этого хватает, чтобы
проверить камеры, проекцию, смешивание и запекание в нашу UV. Каждый принятый workflow пишется в --log-dir как JSON (для разбора, какие узлы и размеры просит аддон).
Запуск: PYTHONPATH=<deps с aiohttp, pillow, numpy> python3 fake_comfy.py --port 8189 --log-dir <папка> [--fail-after N]"""
import argparse
import asyncio
import colorsys
import io
import json
import os
import re
import time
import uuid

import numpy as np
from aiohttp import WSMsgType, web
from PIL import Image

MODELS = {
    'unet_gguf': ['Qwen-Image-Edit-2509-Q5_K_M.gguf'],
    'diffusion_models': ['Qwen-Image-Edit-2509-Q5_K_M.gguf'],
    'checkpoints': ['RealVisXL_V5.0_fp16.safetensors'],
    'loras': ['Qwen-Image-Edit-2509-Lightning-4steps-V1.0-bf16.safetensors', 'sdxl_lightning_8step_lora.safetensors'],
    'controlnet': ['controlnet_depth_sdxl.safetensors'],
    'vae': ['qwen_image_vae.safetensors'],
    'clip': ['qwen_2.5_vl_7b_fp8_scaled.safetensors'],
}


class State:
    def __init__(self, log_dir, fail_after):
        self.log_dir, self.fail_after = log_dir, fail_after
        self.inputs = {}                # имя файла → байты загруженной картинки
        self.sockets = {}               # clientId → websocket
        self.history = {}
        self.outputs = {}               # имя файла → png
        self.n_prompts = 0
        os.makedirs(log_dir, exist_ok=True)


def tint_image(png: bytes, k: int, size=None) -> bytes:
    im = Image.open(io.BytesIO(png)).convert('RGB')
    if size:
        im = im.resize(size, Image.LANCZOS)
    a = np.asarray(im, dtype=np.float32) / 255.0
    lum = a.mean(axis=2, keepdims=True)
    r, g, b = colorsys.hsv_to_rgb((0.07 + 0.12 * (k % 5)) % 1.0, 0.55, 0.85)
    col = np.array([r, g, b], dtype=np.float32)[None, None, :]
    out = np.clip(col * (0.45 + 0.8 * lum), 0, 1)
    out = np.where(lum < 0.02, 0.5, out)                     # фон — серый, как просит аддон («solid gray»)
    buf = io.BytesIO()
    Image.fromarray((out * 255).astype(np.uint8)).save(buf, 'PNG')
    return buf.getvalue()


def find_size(prompt):
    for n in prompt.values():
        i = n.get('inputs', {})
        if n.get('class_type', '').startswith('EmptyLatent') and isinstance(i.get('width'), int):
            return (i['width'], i['height'])
    return None


async def h_queue(req):
    return web.json_response({'queue_running': [], 'queue_pending': []})


async def h_models(req):
    return web.json_response(MODELS.get(req.match_info['folder'], []))


async def h_objinfo(req):
    cls = req.match_info['cls']
    return web.json_response({cls: {'input': {'required': {}}, 'output': [], 'name': cls}})


async def h_upload(req):
    st = req.app['st']
    reader = await req.multipart()
    name, data = None, b''
    async for part in reader:
        if part.name == 'image':
            name = part.filename
            data = bytes(await part.read())
    st.inputs[name] = data
    open(os.path.join(st.log_dir, 'up-' + re.sub(r'[^A-Za-z0-9._-]', '_', name or 'x')), 'wb').write(data)
    return web.json_response({'name': name, 'subfolder': '', 'type': 'input'})


async def h_ws(req):
    st = req.app['st']
    ws = web.WebSocketResponse()
    await ws.prepare(req)
    st.sockets[req.query.get('clientId', '')] = ws
    await ws.send_json({'type': 'status', 'data': {'status': {'exec_info': {'queue_remaining': 0}}}})
    async for msg in ws:
        if msg.type in (WSMsgType.CLOSE, WSMsgType.ERROR):
            break
    return ws


async def run_prompt(st, client_id, pid, prompt):
    ws = st.sockets.get(client_id)
    save = next((i for i, n in prompt.items() if n.get('class_type') == 'SaveImageWebsocket'), None)
    # какая картинка идёт на вход: первая загруженная, на которую ссылается узел LoadImage
    srcs = [st.inputs.get(n['inputs'].get('image')) for n in prompt.values() if n.get('class_type', '').startswith('LoadImage')]
    srcs = [s for s in srcs if s]
    k = st.n_prompts
    if st.fail_after is not None and k >= st.fail_after:
        if ws:
            await ws.send_json({'type': 'execution_error', 'data': {'prompt_id': pid, 'node_id': save or '?', 'exception_message': 'fake: заданный отказ'}})
        return
    png = tint_image(srcs[0], k, find_size(prompt)) if srcs else tint_image(_blank(), k)
    if ws:
        await ws.send_json({'type': 'execution_start', 'data': {'prompt_id': pid}})
        for nid in list(prompt)[:3]:
            await ws.send_json({'type': 'executing', 'data': {'node': nid, 'prompt_id': pid}})
        await asyncio.sleep(0.2)
        if save:
            await ws.send_json({'type': 'executing', 'data': {'node': save, 'prompt_id': pid}})
            await ws.send_bytes(b'\x00\x00\x00\x01\x00\x00\x00\x02' + png)
        await ws.send_json({'type': 'executing', 'data': {'node': None, 'prompt_id': pid}})
    fname = f'fake_{k:03d}.png'
    st.outputs[fname] = png
    fb = next((i for i, n in prompt.items() if n.get('class_type') == 'SaveImage'), save)
    st.history[pid] = {'outputs': {fb: {'images': [{'filename': fname, 'subfolder': '', 'type': 'output'}]}}, 'status': {'completed': True, 'status_str': 'success'}}


def _blank():
    buf = io.BytesIO()
    Image.new('RGB', (512, 512), (128, 128, 128)).save(buf, 'PNG')
    return buf.getvalue()


async def h_prompt(req):
    st = req.app['st']
    body = await req.json()
    prompt = body['prompt']
    pid = str(uuid.uuid4())
    json.dump(prompt, open(os.path.join(st.log_dir, f'prompt-{st.n_prompts:03d}.json'), 'w'), ensure_ascii=False, indent=1)
    asyncio.get_event_loop().create_task(run_prompt(st, body.get('client_id', ''), pid, prompt))
    st.n_prompts += 1
    return web.json_response({'prompt_id': pid, 'number': st.n_prompts, 'node_errors': {}})


async def h_history(req):
    st = req.app['st']
    pid = req.match_info.get('pid')
    return web.json_response({pid: st.history[pid]} if pid in st.history else {})


async def h_view(req):
    st = req.app['st']
    data = st.outputs.get(req.query.get('filename', ''))
    return web.Response(body=data, content_type='image/png') if data else web.Response(status=404)


async def h_any(req):
    print('FAKE: нет обработчика', req.method, req.path_qs, flush=True)
    return web.json_response({})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--port', type=int, default=8189)
    ap.add_argument('--log-dir', required=True)
    ap.add_argument('--fail-after', type=int, default=None, help='после N принятых заданий отвечать ошибкой выполнения')
    a = ap.parse_args()
    app = web.Application(client_max_size=512 * 2 ** 20)
    app['st'] = State(a.log_dir, a.fail_after)
    app.add_routes([web.route('*', '/queue', h_queue), web.get('/models/{folder}', h_models), web.get('/object_info/{cls}', h_objinfo),
                    web.post('/upload/image', h_upload), web.get('/ws', h_ws), web.post('/prompt', h_prompt), web.get('/history/{pid}', h_history),
                    web.get('/view', h_view), web.route('*', '/{tail:.*}', h_any)])
    web.run_app(app, host='127.0.0.1', port=a.port, print=lambda *_: print(f'fake ComfyUI на 127.0.0.1:{a.port}', flush=True))


if __name__ == '__main__':
    main()
