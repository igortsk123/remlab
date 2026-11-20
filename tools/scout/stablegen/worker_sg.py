#!/usr/bin/env python3
"""ВОРКЕР ПРОБЫ «StableGen на Salad» (T-20261119-90/5, этап 1). Живёт внутри образа `Dockerfile.sg-comfy`; код едет в группе переменной TRIAL_WORKER_Z (как у р.4).

Что делает:
  1) СРАЗУ открывает порт 8000 — `/health` отвечает и во время докачки весов (иначе шлюз Salad даёт 503 и причина не видна);
  2) докачивает веса с публичных репозиториев Hugging Face (токен не нужен) в DATA_DIR с продолжением, кладёт ссылками в `models/<папка>` ComfyUI;
  3) запускает ComfyUI на 127.0.0.1:8188 (без веб-интерфейса);
  4) всё остальное (HTTP и WebSocket ComfyUI: /prompt, /upload/image, /ws, /history, /view, /models, /object_info …) ПРОПУСКАЕТ к ComfyUI как есть —
     аддон StableGen в Blender говорит с ним по обычному протоколу, через локальный мост `sg_relay.py`.
Контракт для драйвера: GET /health → {ok, phase, warm, error, broken, progress{hf_gb,file,gb,of_gb}, disk_gb, weights_gb, child{cpu_s}, comfy_log_tail}; GET /info.
Набор весов — переменная SG_WEIGHTS (имена из WEIGHTS через запятую)."""
import asyncio
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

import aiohttp
from aiohttp import WSMsgType, web

COMFY_DIR = os.environ.get('COMFY_DIR', '/opt/ComfyUI')
DATA = os.environ.get('DATA_DIR', '/data/weights')
OUT = os.environ.get('OUT_DIR', '/data/out')
PORT = int(os.environ.get('PORT', '8000'))
COMFY_PORT = 8188
COMFY_URL = f'http://127.0.0.1:{COMFY_PORT}'
T0 = time.time()

# имя → (репозиторий HF, путь в репозитории, папка models/ ComfyUI, имя файла у нас или None = как в репозитории)
WEIGHTS = {
    'te': ('Comfy-Org/Qwen-Image_ComfyUI', 'split_files/text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors', 'clip', None),
    'vae': ('Comfy-Org/Qwen-Image_ComfyUI', 'split_files/vae/qwen_image_vae.safetensors', 'vae', None),
    'q2509_q5': ('QuantStack/Qwen-Image-Edit-2509-GGUF', 'Qwen-Image-Edit-2509-Q5_K_M.gguf', 'unet', None),
    'q2509_q8': ('QuantStack/Qwen-Image-Edit-2509-GGUF', 'Qwen-Image-Edit-2509-Q8_0.gguf', 'unet', None),
    'q2511_q5': ('unsloth/Qwen-Image-Edit-2511-GGUF', 'qwen-image-edit-2511-Q5_K_M.gguf', 'unet', 'Qwen-Image-Edit-2511-Q5_K_M.gguf'),
    'q2511_q8': ('unsloth/Qwen-Image-Edit-2511-GGUF', 'qwen-image-edit-2511-Q8_0.gguf', 'unet', 'Qwen-Image-Edit-2511-Q8_0.gguf'),
    'lora2509': ('lightx2v/Qwen-Image-Lightning', 'Qwen-Image-Edit-2509/Qwen-Image-Edit-2509-Lightning-4steps-V1.0-bf16.safetensors', 'loras', None),
    'lora2511': ('lightx2v/Qwen-Image-Edit-2511-Lightning', 'Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors', 'loras', None),
    # Marigold V2 albedo (T-160/1, Apache-2.0; ≈22,5 ГБ): снимает свет и тени с видов. Имена файлов — как ждёт аддон (workflows.py generate_marigold_v2_map).
    'mv2_base': ('Comfy-Org/marigold-v2-0', 'diffusion_models/qwen_image_edit_2509_int8_convrot.safetensors', 'diffusion_models', None),    # 20,5 ГБ
    'mv2_lora': ('Comfy-Org/marigold-v2-0', 'loras/marigold_v2_albedo.safetensors', 'loras', None),                                          # 1,7 ГБ
    'mv2_vae': ('Comfy-Org/marigold-v2-0', 'vae/marigold_v2_albedo_vae.safetensors', 'vae', None),                                           # 0,25 ГБ
    'mv2_cond': ('Comfy-Org/marigold-v2-0', 'embeddings/marigold_v2_albedo_conditioning.safetensors', 'embeddings', None),                   # 2,5 МБ
}
DEFAULT_SET = 'te,vae,q2509_q5,lora2509,q2511_q5,lora2511'

STATE = {'phase': 'boot', 'warm': False, 'error': None, 'progress': {}, 'weights_gb': None, 'timings': {}, 'child': None, 'gpu': None}
_DL_BASE = [0]


def weights_plan(spec: str) -> list[tuple[str, str, str, str]]:
    """«te,vae,q2509_q5» → [(репо, путь, папка, имя у нас)]; неизвестное имя — ошибка сразу (а не после часа докачки)."""
    out = []
    if spec == 'none':                                  # бесплатная проверка без весов
        return out
    for key in [k.strip() for k in (spec or DEFAULT_SET).split(',') if k.strip()]:
        if key not in WEIGHTS:
            raise ValueError(f'неизвестный набор весов: {key}')
        repo, rel, sub, name = WEIGHTS[key]
        out.append((repo, rel, sub, name or os.path.basename(rel)))
    return out


def http_get(url: str, dest: str, label: str) -> None:
    """Докачка с продолжением (`.part` + Range): обрыв сети не стоит повторной загрузки 15 ГБ."""
    tmp = dest + '.part'
    have = os.path.getsize(tmp) if os.path.exists(tmp) else 0
    headers = {'User-Agent': 'remlab-mesh/1.0'}
    if have:
        headers['Range'] = f'bytes={have}-'
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=120) as r:
        if have and r.status != 206:
            have = 0                                    # сервер Range не понял — качаем сначала
        total = have + int(r.headers.get('Content-Length') or 0)
        done = have
        last = time.time()
        with open(tmp, 'ab' if have else 'wb') as f:
            while True:
                b = r.read(8 << 20)
                if not b:
                    break
                f.write(b)
                done += len(b)
                if time.time() - last > 5:
                    STATE['progress'] = {'file': label, 'gb': round(done / 2 ** 30, 2), 'of_gb': round(total / 2 ** 30, 2),
                                         'hf_gb': round((_DL_BASE[0] + done) / 2 ** 30, 2), 'at': time.time()}
                    last = time.time()
    os.replace(tmp, dest)


def fetch_weights(plan) -> dict:
    t = time.time()
    got = {}
    for repo, rel, sub, name in plan:
        dest_dir = os.path.join(DATA, sub)
        os.makedirs(dest_dir, exist_ok=True)
        dest = os.path.join(dest_dir, name)
        if not os.path.exists(dest):
            for attempt in (1, 2, 3):
                try:
                    http_get(f'https://huggingface.co/{repo}/resolve/main/{rel}', dest, name)
                    break
                except (urllib.error.URLError, OSError, TimeoutError) as e:
                    print(f'[weights] {name} попытка {attempt}: {e}', flush=True)
                    if attempt == 3:
                        raise
                    time.sleep(10)
        _DL_BASE[0] += os.path.getsize(dest)
        STATE['progress'] = dict(STATE.get('progress') or {}, hf_gb=round(_DL_BASE[0] / 2 ** 30, 2), at=time.time())
        link_dir = os.path.join(COMFY_DIR, 'models', sub)
        os.makedirs(link_dir, exist_ok=True)
        link = os.path.join(link_dir, name)
        if not os.path.lexists(link):
            os.symlink(dest, link)
        got[name] = round(os.path.getsize(dest) / 2 ** 30, 2)
    STATE['timings']['weights_s'] = round(time.time() - t, 1)
    return got


def comfy_get(path: str, timeout: int = 30):
    with urllib.request.urlopen(COMFY_URL + path, timeout=timeout) as r:
        return json.loads(r.read())


def start_comfy() -> subprocess.Popen:
    out_dir = os.path.join(OUT, 'comfy-out')
    os.makedirs(out_dir, exist_ok=True)
    os.makedirs(os.path.join(COMFY_DIR, 'input'), exist_ok=True)
    front = os.environ.get('COMFY_FRONT_ROOT', '/tmp/comfy-no-frontend')            # без веб-интерфейса, как у р.4
    os.makedirs(front, exist_ok=True)
    cmd = [sys.executable, '-u', 'main.py', '--listen', '127.0.0.1', '--port', str(COMFY_PORT), '--disable-auto-launch', '--output-directory', out_dir,
           '--temp-directory', '/tmp/comfy-temp', '--disable-metadata', '--front-end-root', front, '--disable-partner-nodes']
    if os.environ.get('SG_COMFY_CMD'):                   # ТОЛЬКО для бесплатной проверки на pakardev: вместо ComfyUI — поддельный сервер (JSON-список команды)
        cmd = json.loads(os.environ['SG_COMFY_CMD'])
    log = open(os.path.join(OUT, 'comfy.log'), 'ab')
    return subprocess.Popen(cmd, cwd=COMFY_DIR if os.path.isdir(COMFY_DIR) else None, stdout=log, stderr=subprocess.STDOUT)


def boot() -> None:
    try:
        STATE['phase'] = 'weights'
        STATE['weights_gb'] = fetch_weights(weights_plan(os.environ.get('SG_WEIGHTS', DEFAULT_SET)))
        STATE['phase'] = 'starting_comfy'
        t = time.time()
        STATE['child'] = start_comfy()
        for _ in range(240):
            try:
                st = comfy_get('/system_stats', 5)
                STATE['gpu'] = (st.get('devices') or [{}])[0]
                break
            except (urllib.error.URLError, OSError, TimeoutError, ValueError):
                if STATE['child'].poll() is not None:
                    raise RuntimeError(f'ComfyUI завершился с кодом {STATE["child"].returncode}')
                time.sleep(2)
        else:
            raise RuntimeError('ComfyUI не поднялся за 8 мин')
        STATE['timings']['comfy_start_s'] = round(time.time() - t, 1)
        STATE['phase'], STATE['warm'] = 'ready', True
    except Exception as e:          # noqa: BLE001 — любая ошибка старта видна в /health, воркер не падает молча
        STATE['error'] = f'{type(e).__name__}: {e}'
        STATE['phase'] = 'failed'
        print('[boot] ОШИБКА', STATE['error'], flush=True)


# ---------------------------------------------------------------- HTTP
def _disk(path: str) -> dict:
    try:
        u = shutil.disk_usage(path if os.path.exists(path) else '/')
        return {'free': round(u.free / 2 ** 30, 1), 'total': round(u.total / 2 ** 30, 1)}
    except OSError:
        return {}


def _tail(path: str, n: int = 12) -> list[str]:
    try:
        with open(path, 'rb') as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 6000))
            return f.read().decode('utf-8', 'replace').splitlines()[-n:]
    except OSError:
        return []


def _child_info() -> dict:
    child = STATE.get('child')
    if child is None:
        return {}
    alive = child.poll() is None
    info = {'alive': alive, 'rc': child.returncode}
    try:
        import psutil
        if alive:
            p = psutil.Process(child.pid)
            info['cpu_s'] = round(sum(p.cpu_times()[:2]), 1)
            info['rss_gb'] = round(p.memory_info().rss / 2 ** 30, 2)
    except Exception:  # noqa: BLE001 — нет psutil/процесса: просто без цифр
        pass
    return info


def health() -> dict:
    child = STATE.get('child')
    alive = child is not None and child.poll() is None
    broken = STATE['error'] if STATE['phase'] == 'failed' else (None if alive or STATE['phase'] in ('boot', 'weights', 'starting_comfy') else 'ComfyUI не работает')
    return {'ok': not broken, 'phase': STATE['phase'], 'warm': bool(STATE['warm']) and alive, 'error': STATE['error'] or broken, 'broken': broken, 'progress': STATE['progress'],
            'disk_gb': {'hf': _disk(DATA), 'out': _disk(OUT)}, 'timings': STATE['timings'], 'weights_gb': STATE.get('weights_gb'), 'child': _child_info(),
            'comfy_log_tail': _tail(os.path.join(OUT, 'comfy.log')), 'uptime_s': round(time.time() - T0, 1)}


async def h_health(req):
    return web.json_response(health())


async def h_info(req):
    g = STATE.get('gpu') or {}
    return web.json_response({'backend': 'comfy-0.46.0+gguf', 'gpu': g.get('name'), 'vram_total': g.get('vram_total'), 'vram_free': g.get('vram_free'),
                              'weights_gb': STATE.get('weights_gb')})


HOP = {'host', 'connection', 'keep-alive', 'transfer-encoding', 'upgrade', 'content-length', 'content-encoding', 'sec-websocket-key', 'sec-websocket-version',
       'sec-websocket-extensions', 'sec-websocket-protocol', 'salad-api-key'}


async def h_ws(req):
    """WebSocket аддона ↔ WebSocket ComfyUI: кадры (текст и бинарные PNG) идут как есть в обе стороны."""
    if not STATE['warm']:
        return web.json_response({'error': 'воркер ещё не готов', 'phase': STATE['phase']}, status=503)
    ws_c = web.WebSocketResponse(max_msg_size=0)
    await ws_c.prepare(req)
    async with aiohttp.ClientSession() as sess:
        async with sess.ws_connect(f'ws://127.0.0.1:{COMFY_PORT}/ws?{req.query_string}', max_msg_size=0) as ws_s:
            async def up():
                async for m in ws_c:
                    if m.type == WSMsgType.TEXT:
                        await ws_s.send_str(m.data)
                    elif m.type == WSMsgType.BINARY:
                        await ws_s.send_bytes(m.data)
                    else:
                        break

            async def down():
                async for m in ws_s:
                    if m.type == WSMsgType.TEXT:
                        await ws_c.send_str(m.data)
                    elif m.type == WSMsgType.BINARY:
                        await ws_c.send_bytes(m.data)
                    else:
                        break

            done, pending = await asyncio.wait([asyncio.ensure_future(up()), asyncio.ensure_future(down())], return_when=asyncio.FIRST_COMPLETED)
            for p in pending:
                p.cancel()
    return ws_c


async def h_proxy(req):
    if not STATE['warm']:
        return web.json_response({'error': 'воркер ещё не готов', 'phase': STATE['phase']}, status=503)
    body = await req.read()
    headers = {k: v for k, v in req.headers.items() if k.lower() not in HOP}
    async with aiohttp.ClientSession() as sess:
        async with sess.request(req.method, COMFY_URL + req.path_qs, data=body or None, headers=headers, timeout=aiohttp.ClientTimeout(total=1800)) as r:
            data = await r.read()
            out_h = {k: v for k, v in r.headers.items() if k.lower() not in HOP}
            return web.Response(body=data, status=r.status, headers=out_h)


def main() -> None:
    global OUT, DATA
    print(f'[worker_sg] старт: python {sys.version.split()[0]}, uid {os.getuid()}, cwd {os.getcwd()}, порт {PORT}, веса: {os.environ.get("SG_WEIGHTS", DEFAULT_SET)}', flush=True)
    for name in ('OUT', 'DATA'):                      # нет /data или нет прав — не падаем до открытия порта: запасной путь в /tmp
        path = globals()[name]
        try:
            os.makedirs(path, exist_ok=True)
            if not os.access(path, os.W_OK):
                raise PermissionError(path)
        except OSError as e:
            alt = os.path.join('/tmp', 'sg-' + name.lower())
            print(f'[worker_sg] {path}: {e} — использую {alt}', flush=True)
            os.makedirs(alt, exist_ok=True)
            globals()[name] = alt
    app = web.Application(client_max_size=512 * 2 ** 20)
    app.add_routes([web.get('/health', h_health), web.get('/ready', h_health), web.get('/info', h_info), web.get('/ws', h_ws), web.route('*', '/{tail:.*}', h_proxy)])
    threading.Thread(target=boot, daemon=True).start()
    # Шлюз и пробы Salad ходят по IPv6 (урок 724; найдено 19.11 20:45 у trial-comfy): сервер только на 0.0.0.0 им НЕ отвечает → «running, started=false, 503».
    # Один сокет на `::` с IPV6_V6ONLY=0 слушает и IPv6, и IPv4; нет IPv6 в окружении — обычный IPv4.
    import socket
    try:
        sock = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        sock.bind(('::', PORT))
        kw = {'sock': sock}
    except OSError as e:
        print(f'[worker_sg] IPv6 недоступен ({e}) — слушаю только IPv4', flush=True)
        kw = {'host': '0.0.0.0', 'port': PORT}
    web.run_app(app, print=lambda *_: print(f'[worker_sg] HTTP слушает :{PORT} (IPv6+IPv4), запускаю докачку весов', flush=True), **kw)


if __name__ == '__main__':
    main()
