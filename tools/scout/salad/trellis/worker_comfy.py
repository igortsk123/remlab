"""ВОРКЕР ПРОБЫ «официальный TRELLIS.2 в ComfyUI v0.46.0» — T-20261119-94/2 (владелец TG 1960).
Тот же HTTP-контракт, что у `worker_trellis.py` (его читает драйвер `trellis_trial.py`), но внутри — настоящий ComfyUI (core-узлы TRELLIS.2 и постобработки меша, без nvdiffrast):
  GET  /health        фаза (downloading → starting_comfy → ready), warm, ошибка; GET /info — видеокарта
  POST /generate      {job_id, image_b64 (RGBA-вырезка с настоящей альфой), pipeline_type '1024_cascade'|'1536_cascade', seed, variants:[…], export_raw}
  GET  /job/<id>      queued|running|done|failed + metrics (секунды, grid_res_actual, треугольники, файлы вариантов)
  GET  /glb/<id>[?v=raw|<вариант>]  GLB: без v — первый вариант, v=raw — сырая форма после VAE, v=<имя> — вариант починки
Только форма (без краски): текстурная ветка не строится — не нужна для оценки сетки и экономит память/время (краску потом красит UltraTex).
Один ComfyUI на 127.0.0.1:8188, веса докачиваются с Hugging Face при старте (публичные репозитории Comfy-Org, токен не нужен и не отправляется).
Вариант (`variants[i]`): {name, mode: udf|solid|sdf|none, resolution (сетка remesh; по умолчанию = сетка формы, НЕ 512), band, project_back, fill (solid), qef,
drop_inverted, drop_enclosed, drop_small, smooth_iters, fix_poles, decimate (целевое число граней, 0 = без), fill_holes (макс. периметр, 0 = без)}.
Вся форма (три сэмплера + VAE) считается один раз: ComfyUI переиспользует результаты неизменённых узлов между запросами, поэтому варианты дешёвые.
Сборка workflow и разбор ответов — чистые функции без сети и видеокарты (tests_comfy.py)."""
import base64
import collections
import json
import os
import re
import socket
import struct
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

COMFY_DIR = os.environ.get('COMFY_DIR', '/opt/ComfyUI')
OUT = os.environ.get('OUT_DIR', '/data/out')
DATA = os.environ.get('COMFY_DATA', '/data/comfy-models')
PORT = int(os.environ.get('PORT', '8000'))
COMFY_PORT = 8188
COMFY_URL = f'http://127.0.0.1:{COMFY_PORT}'

# (репозиторий, путь в репозитории, подпапка models/) — публичные веса Comfy-Org (MIT для TRELLIS.2); bf16, не int8 (решение директора 19.11)
WEIGHTS = [
    ('Comfy-Org/TRELLIS.2', 'diffusion_models/trellis_2_bf16.safetensors', 'diffusion_models'),
    ('Comfy-Org/TRELLIS.2', 'vae/trellis_2_shape_vae_bf16.safetensors', 'vae'),
    ('Comfy-Org/Pixal3D', 'clip_vision/dino_v3_L_naf_fp32.safetensors', 'clip_vision'),
]
UNET, SHAPE_VAE, CLIP = 'trellis_2_bf16.safetensors', 'trellis_2_shape_vae_bf16.safetensors', 'dino_v3_L_naf_fp32.safetensors'

STATE = {'phase': 'boot', 'warm': False, 'error': None, 'progress': {}, 'gpu': None, 'timings': {}}
JOBS = {}
QUEUE = []
LOCK = threading.Lock()
T0 = time.time()


# ---------------------------------------------------------------- чистые функции (тестируются без сети)
def res_from_pipeline_type(pt: str) -> int:
    """'1024_cascade' → 1024, '1536_cascade' → 1536 (в узлах Comfy — `Trellis2UpsampleStage.target_resolution`; молчаливого снижения как в апстриме (max_num_tokens) здесь нет)."""
    m = re.fullmatch(r'(\d{3,4})(?:_cascade)?', str(pt or '1024_cascade'))
    if not m or not 1024 <= int(m.group(1)) <= 2048 or int(m.group(1)) % 128:
        raise ValueError(f'pipeline_type: ожидается 1024…2048 с шагом 128, получено {pt!r}')
    return int(m.group(1))


VARIANT_KEYS = ('name', 'mode', 'resolution', 'band', 'project_back', 'fill', 'qef', 'drop_inverted', 'drop_enclosed', 'drop_small', 'smooth_iters', 'fix_poles', 'decimate', 'fill_holes')


def parse_variants(variants: list, grid: int) -> list[dict]:
    """Проверка и значения по умолчанию (разрешение remesh по умолчанию = сетке формы; 512 по умолчанию узла — ровно тот урез, который мы исследуем)."""
    out, seen = [], set()
    for v in variants or []:
        bad = [k for k in v if k not in VARIANT_KEYS]
        if bad:
            raise ValueError(f'variants: неизвестные ключи {bad}')
        nm = str(v.get('name') or '')
        if not nm or not re.fullmatch(r'[A-Za-z0-9_-]+', nm) or nm in ('raw', 'ai') or nm in seen:
            raise ValueError(f'variants: нужно уникальное имя из букв, цифр и «-_» (не raw/ai): {nm!r}')
        seen.add(nm)
        mode = v.get('mode', 'udf')
        if mode not in ('udf', 'solid', 'sdf', 'none'):
            raise ValueError(f'variants {nm}: mode udf|solid|sdf|none, получено {mode!r}')
        d = {'name': nm, 'mode': mode, 'resolution': int(v.get('resolution', grid)), 'band': float(v.get('band', 1.0)), 'project_back': float(v.get('project_back', 0.0)),
             'fill': float(v.get('fill', 20.0)), 'qef': bool(v.get('qef', mode == 'sdf')), 'drop_inverted': bool(v.get('drop_inverted', False)),
             'drop_enclosed': bool(v.get('drop_enclosed', False)), 'drop_small': float(v.get('drop_small', 0.01)), 'smooth_iters': int(v.get('smooth_iters', 0)),
             'fix_poles': bool(v.get('fix_poles', False)), 'decimate': int(v.get('decimate', 500000)), 'fill_holes': float(v.get('fill_holes', 0.03))}
        if not (32 <= d['resolution'] <= 2048 and 0.5 <= d['band'] <= 4 and 0 <= d['project_back'] <= 1 and 0 <= d['drop_small'] <= 0.5 and 0 <= d['smooth_iters'] <= 20
                and 0 <= d['decimate'] <= 50_000_000 and 0 <= d['fill_holes'] <= 10 and 0 <= d['fill'] <= 1000):
            raise ValueError(f'variants {nm}: значение вне диапазона узла')
        out.append(d)
    return out


def build_workflow(image_name: str, grid: int, seed: int, variant: dict | None, save_raw: bool, prefix: str) -> dict:
    """API-workflow (формат POST /prompt): форма TRELLIS.2 как в официальном шаблоне Comfy (`3d_pixal3d_trellis2_image_to_model`): те же CFG-подмены/RescaleCFG/ModelSamplingSD3, те же
    шаги и сэмплеры; вход — наша вырезка (маска = альфа, `LoadImage.MASK` = 1−альфа → InvertMask), без RemoveBackground/BiRefNet. Затем (при `variant`) RemeshMesh → DecimateMesh → FillHoles → SaveGLB."""
    n: dict = {
        'unet': {'class_type': 'UNETLoader', 'inputs': {'unet_name': UNET, 'weight_dtype': 'default'}},
        'clip': {'class_type': 'CLIPVisionLoader', 'inputs': {'clip_name': CLIP}},
        'vae': {'class_type': 'VAELoader', 'inputs': {'vae_name': SHAPE_VAE}},
        'img': {'class_type': 'LoadImage', 'inputs': {'image': image_name}},
        'fg': {'class_type': 'InvertMask', 'inputs': {'mask': ['img', 1]}},
        'crop': {'class_type': 'ImageCropToMask', 'inputs': {'images': ['img', 0], 'masks': ['fg', 0], 'width': 1024, 'height': 1024, 'pad_factor': 1.1, 'grow_mask': 0, 'background': '#000000'}},
        'cond': {'class_type': 'Trellis2Conditioning', 'inputs': {'clip_vision_model': ['clip', 0], 'image': ['crop', 0]}},
        # модель для структуры: CFG 0.667 → RescaleCFG 0.7 → shift 5; для формы: CFG 0.769 → RescaleCFG 0.5 (как в шаблоне Comfy; «CFG override … to match the original default pipeline»)
        'cfg_ss': {'class_type': 'CFGOverride', 'inputs': {'model': ['unet', 0], 'cfg': 1.0, 'start_percent': 0.667, 'end_percent': 1.0}},
        'rs_ss': {'class_type': 'RescaleCFG', 'inputs': {'model': ['cfg_ss', 0], 'multiplier': 0.7}},
        'ms_ss': {'class_type': 'ModelSamplingSD3', 'inputs': {'model': ['rs_ss', 0], 'shift': 5.0}},
        'cfg_sh': {'class_type': 'CFGOverride', 'inputs': {'model': ['unet', 0], 'cfg': 1.0, 'start_percent': 0.769, 'end_percent': 1.0}},
        'rs_sh': {'class_type': 'RescaleCFG', 'inputs': {'model': ['cfg_sh', 0], 'multiplier': 0.5}},
        'empty': {'class_type': 'EmptyTrellis2LatentStructure', 'inputs': {'batch_size': 1}},
        'ks_ss': {'class_type': 'KSampler', 'inputs': {'model': ['ms_ss', 0], 'seed': seed, 'steps': 12, 'cfg': 7.5, 'sampler_name': 'euler', 'scheduler': 'normal', 'positive': ['cond', 0], 'negative': ['cond', 1],
                                                      'latent_image': ['empty', 0], 'denoise': 1.0}},
        'struct': {'class_type': 'VaeDecodeStructureTrellis2', 'inputs': {'samples': ['ks_ss', 0], 'vae': ['vae', 0], 'resolution': '32'}},
        'stage': {'class_type': 'Trellis2ShapeStage', 'inputs': {'positive': ['cond', 0], 'negative': ['cond', 1], 'voxel': ['struct', 0]}},
        'ks_sh': {'class_type': 'KSampler', 'inputs': {'model': ['rs_sh', 0], 'seed': seed, 'steps': 20, 'cfg': 7.5, 'sampler_name': 'euler', 'scheduler': 'normal', 'positive': ['stage', 0], 'negative': ['stage', 1],
                                                      'latent_image': ['stage', 2], 'denoise': 1.0}},
        'up': {'class_type': 'Trellis2UpsampleStage', 'inputs': {'positive': ['stage', 0], 'negative': ['stage', 1], 'shape_latent': ['ks_sh', 0], 'vae': ['vae', 0], 'target_resolution': grid}},
        'ks_hr': {'class_type': 'KSampler', 'inputs': {'model': ['rs_sh', 0], 'seed': seed, 'steps': 12, 'cfg': 7.5, 'sampler_name': 'euler', 'scheduler': 'simple', 'positive': ['up', 0], 'negative': ['up', 1],
                                                      'latent_image': ['up', 2], 'denoise': 1.0}},
        'mesh': {'class_type': 'VaeDecodeShapeTrellis', 'inputs': {'samples': ['ks_hr', 0], 'vae': ['vae', 0]}},
    }
    if save_raw:
        n['save_raw'] = {'class_type': 'SaveGLB', 'inputs': {'mesh': ['mesh', 0], 'filename_prefix': f'{prefix}/raw'}}
    if variant:
        v = variant
        rin: dict = {'mesh': ['mesh', 0], 'resolution': v['resolution'], 'sign_mode': v['mode'], 'band': v['band'], 'project_back': v['project_back'], 'fix_poles': v['fix_poles'],
                     'smooth_iters': v['smooth_iters'], 'drop_small_components': v['drop_small'], 'precluster_max_verts': 20_000_000}
        if v['mode'] == 'udf':
            rin.update({'sign_mode.qef': v['qef'], 'sign_mode.drop_inverted_components': v['drop_inverted'], 'sign_mode.drop_enclosed_components': v['drop_enclosed']})
        elif v['mode'] == 'solid':
            rin.update({'sign_mode.fill': v['fill'], 'sign_mode.qef': v['qef']})
        elif v['mode'] == 'sdf':
            rin.update({'sign_mode.qef': v['qef'], 'sign_mode.manifold': False})
        last = ['mesh', 0]
        if v['mode'] != 'none':
            n['remesh'] = {'class_type': 'RemeshMesh', 'inputs': rin}
            last = ['remesh', 0]
        if v['decimate']:
            n['decimate'] = {'class_type': 'DecimateMesh', 'inputs': {'mesh': last, 'target_face_count': v['decimate'], 'placement_mode': 'midpoint'}}
            last = ['decimate', 0]
        if v['fill_holes']:
            n['fill'] = {'class_type': 'FillHoles', 'inputs': {'mesh': last, 'max_perimeter': v['fill_holes'], 'weld_epsilon_rel': 1e-5, 'max_vertices': 16, 'fill_chains': False}}
            last = ['fill', 0]
        n['save'] = {'class_type': 'SaveGLB', 'inputs': {'mesh': last, 'filename_prefix': f'{prefix}/{v["name"]}'}}
    return n


def saved_files(history_entry: dict) -> list[dict]:
    """Из ответа `/history/<id>` — все сохранённые файлы {filename, subfolder, type} по всем выходным узлам (ключ вывода у SaveGLB не фиксируем — берём любой список словарей с filename)."""
    out = []
    for node_out in (history_entry.get('outputs') or {}).values():
        for items in node_out.values():
            if isinstance(items, list):
                out += [x for x in items if isinstance(x, dict) and x.get('filename')]
    return out


def history_state(entry: dict) -> tuple[str, str | None]:
    """('running'|'success'|'error', текст ошибки из messages `execution_error`)."""
    st = (entry.get('status') or {})
    s = st.get('status_str') or ('success' if st.get('completed') else 'running')
    err = None
    for m in st.get('messages') or []:
        if isinstance(m, list) and len(m) == 2 and m[0] == 'execution_error':
            d = m[1] or {}
            err = f'{d.get("node_type")}: {d.get("exception_type")}: {str(d.get("exception_message"))[:300]}'
    return ('error' if err else s), err


def glb_stats(data: bytes) -> dict:
    """Вершины и треугольники GLB по заголовку (без trimesh): сумма count у accessor'ов индексов/позиций всех примитивов."""
    if data[:4] != b'glTF' or len(data) < 20:
        raise ValueError('не GLB')
    jlen, jtype = struct.unpack('<II', data[12:20])
    if jtype != 0x4E4F534A:
        raise ValueError('нет JSON-чанка')
    g = json.loads(data[20:20 + jlen])
    acc = g.get('accessors', [])
    verts = tris = 0
    for mesh in g.get('meshes', []):
        for p in mesh.get('primitives', []):
            if 'POSITION' in (p.get('attributes') or {}):
                verts += acc[p['attributes']['POSITION']]['count']
            if 'indices' in p:
                tris += acc[p['indices']]['count'] // 3
    return {'verts': verts, 'tris': tris}


# ---------------------------------------------------------------- загрузка весов и ComfyUI
_DL_BASE = [0]            # байт уже докачанных файлов — `hf_gb` в /health растёт монотонно по всем весам (по нему драйвер ловит зависшую докачку)


def http_get(url: str, dest: str, label: str) -> None:
    tmp = dest + '.part'
    req = urllib.request.Request(url, headers={'User-Agent': 'remlab-mesh/1.0'})
    with urllib.request.urlopen(req, timeout=120) as r, open(tmp, 'wb') as f:
        total = int(r.headers.get('Content-Length') or 0)
        done = 0
        last = time.time()
        while True:
            b = r.read(8 << 20)
            if not b:
                break
            f.write(b)
            done += len(b)
            if time.time() - last > 5:
                STATE['progress'] = {'file': label, 'gb': round(done / 2 ** 30, 2), 'of_gb': round(total / 2 ** 30, 2), 'hf_gb': round((_DL_BASE[0] + done) / 2 ** 30, 2), 'at': time.time()}
                last = time.time()
    os.replace(tmp, dest)


def fetch_weights() -> dict:
    t = time.time()
    got = {}
    for repo, rel, sub in WEIGHTS:
        dest_dir = os.path.join(DATA, sub)
        os.makedirs(dest_dir, exist_ok=True)
        dest = os.path.join(dest_dir, os.path.basename(rel))
        if not os.path.exists(dest):
            for attempt in (1, 2, 3):
                try:
                    http_get(f'https://huggingface.co/{repo}/resolve/main/{rel}', dest, os.path.basename(rel))
                    break
                except (urllib.error.URLError, OSError, TimeoutError) as e:
                    print(f'[weights] {rel} попытка {attempt}: {e}', flush=True)
                    if attempt == 3:
                        raise
                    time.sleep(10)
        _DL_BASE[0] += os.path.getsize(dest)
        STATE['progress'] = dict(STATE.get('progress') or {}, hf_gb=round(_DL_BASE[0] / 2 ** 30, 2), at=time.time())
        link_dir = os.path.join(COMFY_DIR, 'models', sub)
        os.makedirs(link_dir, exist_ok=True)
        link = os.path.join(link_dir, os.path.basename(rel))
        if not os.path.lexists(link):
            os.symlink(dest, link)
        got[os.path.basename(rel)] = round(os.path.getsize(dest) / 2 ** 30, 2)
    STATE['timings']['weights_s'] = round(time.time() - t, 1)
    return got


def comfy_get(path: str, timeout: int = 30):
    with urllib.request.urlopen(COMFY_URL + path, timeout=timeout) as r:
        return json.loads(r.read())


def comfy_post(path: str, body: dict, timeout: int = 60):
    req = urllib.request.Request(COMFY_URL + path, data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'}, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except ValueError:
            return e.code, {}


LOG_TAIL = collections.deque(maxlen=50)                   # последние 50 строк журнала ComfyUI — в /health, чтобы причина падения не уходила вместе с группой (T-94/3, 19.11: t94l)


def _pump_log(child: subprocess.Popen) -> None:
    """Читает вывод ComfyUI: каждую строку — в кольцо LOG_TAIL и дальше в свой stdout (журнал Salad)."""
    try:
        for line in child.stdout:
            line = line.rstrip('\n')
            LOG_TAIL.append(line[:500])
            print(line, flush=True)
    except (ValueError, OSError):
        pass


def start_comfy() -> subprocess.Popen:
    out_dir = os.path.join(OUT, 'comfy-out')
    os.makedirs(out_dir, exist_ok=True)
    os.makedirs(os.path.join(COMFY_DIR, 'input'), exist_ok=True)
    front = os.environ.get('COMFY_FRONT_ROOT', '/tmp/comfy-no-frontend')          # без веб-интерфейса: пакет фронтенда не ставим, `--front-end-root` обходит его проверку (без него ComfyUI завершается)
    os.makedirs(front, exist_ok=True)
    cmd = [sys.executable, '-u', 'main.py', '--listen', '127.0.0.1', '--port', str(COMFY_PORT), '--disable-auto-launch', '--output-directory', out_dir,
           '--temp-directory', '/tmp/comfy-temp', '--disable-metadata', '--front-end-root', front, '--disable-partner-nodes']
    child = subprocess.Popen(cmd, cwd=COMFY_DIR, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, errors='replace')
    threading.Thread(target=_pump_log, args=(child,), daemon=True).start()
    return child


def boot() -> None:
    try:
        STATE['phase'] = 'weights'
        STATE['weights_gb'] = fetch_weights()
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
        threading.Thread(target=job_loop, daemon=True).start()
    except Exception as e:          # noqa: BLE001 — любая ошибка старта видна в /health, воркер не падает молча
        STATE['error'] = f'{type(e).__name__}: {e}'
        STATE['phase'] = 'failed'
        print('[boot] ОШИБКА', STATE['error'], flush=True)


# ---------------------------------------------------------------- задания
def run_prompt(wf: dict, timeout_s: int = 1500) -> dict:
    code, r = comfy_post('/prompt', {'prompt': wf, 'client_id': 'remlab-worker'})
    if code != 200:
        raise RuntimeError(f'/prompt HTTP {code}: {json.dumps(r, ensure_ascii=False)[:600]}')
    pid = r['prompt_id']
    t = time.time()
    while time.time() - t < timeout_s:
        h = comfy_get(f'/history/{pid}', 30)
        if pid in h:
            state, err = history_state(h[pid])
            if state in ('success', 'error'):
                if err or state == 'error':
                    raise RuntimeError(err or 'ComfyUI: ошибка выполнения')
                return h[pid]
        time.sleep(2)
    raise RuntimeError(f'ComfyUI: задание не закончилось за {timeout_s} с')


def job_path(jid: str) -> str:
    return os.path.join(OUT, f'{jid}.res.json')


def save_job(jid: str, d: dict) -> None:
    JOBS[jid] = d
    with open(job_path(jid), 'w', encoding='utf-8') as f:
        json.dump(d, f, ensure_ascii=False)


def copy_saved(entry: dict, dest: str) -> dict:
    files = saved_files(entry)
    if not files:
        raise RuntimeError('ComfyUI ничего не сохранил')
    f = files[-1]
    src = os.path.join(OUT, 'comfy-out', f.get('subfolder') or '', f['filename'])
    data = open(src, 'rb').read()
    open(dest, 'wb').write(data)
    return glb_stats(data) | {'bytes': len(data)}


def do_job(jid: str, p: dict) -> None:
    t0 = time.time()
    save_job(jid, {'status': 'running'})
    try:
        grid = res_from_pipeline_type(p.get('pipeline_type'))
        variants = parse_variants(p.get('variants'), grid)
        seed = int(p.get('seed', 42))
        os.makedirs(OUT, exist_ok=True)
        name = f'{jid}.png'
        open(os.path.join(COMFY_DIR, 'input', name), 'wb').write(base64.b64decode(p['image_b64']))
        m: dict = {'pipeline_type': p.get('pipeline_type'), 'grid_res_actual': grid, 'grid_note': 'ComfyUI: target_resolution как задан, без молчаливого снижения', 'variants': {}, 'backend': 'comfy-0.46.0'}
        want_raw = bool(p.get('export_raw', True))
        todo = variants or [None]
        for i, v in enumerate(todo):
            tv = time.time()
            wf = build_workflow(name, grid, seed, v, save_raw=(want_raw and i == 0), prefix=jid)
            try:
                entry = run_prompt(wf)
            except RuntimeError as e:
                if v is None:
                    raise
                m['variants'][v['name']] = {'error': str(e)[:600], 'seconds': round(time.time() - tv, 1)}
                continue
            if i == 0 and want_raw:
                raw_file = [f for f in saved_files(entry) if os.path.basename(f['filename']).startswith('raw')]
                if raw_file:
                    src = os.path.join(OUT, 'comfy-out', raw_file[0].get('subfolder') or '', raw_file[0]['filename'])
                    data = open(src, 'rb').read()
                    open(os.path.join(OUT, f'{jid}.raw.glb'), 'wb').write(data)
                    m.update({'has_raw': True, 'raw_tris': glb_stats(data)['tris'], 'raw_verts': glb_stats(data)['verts'], 'raw_glb_bytes': len(data)})
            if v is not None:
                dest = os.path.join(OUT, f'{jid}.glb' if i == 0 else f'{jid}.{v["name"]}.glb')
                st = copy_saved({'outputs': {k: o for k, o in entry['outputs'].items() if k == 'save'}} if 'save' in entry.get('outputs', {}) else entry, dest)
                if i == 0:                                              # первый вариант — основной `.glb` и одновременно файл `<имя>`
                    open(os.path.join(OUT, f'{jid}.{v["name"]}.glb'), 'wb').write(open(dest, 'rb').read())
                m['variants'][v['name']] = st | {'seconds': round(time.time() - tv, 1), 'params': v}
            else:
                st = {}
            m.setdefault('prompt_seconds', []).append(round(time.time() - tv, 1))
        m['variant_files'] = [k for k, x in m['variants'].items() if 'error' not in x and k != (variants[0]['name'] if variants else None)]
        m['seconds'] = round(time.time() - t0, 1)
        if not variants:                                               # без вариантов — основной файл = сырая форма
            if not m.get('has_raw'):
                raise RuntimeError('нет ни вариантов, ни сырой формы')
            open(os.path.join(OUT, f'{jid}.glb'), 'wb').write(open(os.path.join(OUT, f'{jid}.raw.glb'), 'rb').read())
        elif all('error' in x for x in m['variants'].values()):
            raise RuntimeError('все варианты упали: ' + '; '.join(f'{k}: {x["error"][:120]}' for k, x in m['variants'].items()))
        save_job(jid, {'status': 'done', 'metrics': m})
    except Exception as e:          # noqa: BLE001
        save_job(jid, {'status': 'failed', 'error': f'{type(e).__name__}: {str(e)[:700]}', 'seconds': round(time.time() - t0, 1)})


def job_loop() -> None:
    while True:
        with LOCK:
            item = QUEUE.pop(0) if QUEUE else None
        if item is None:
            time.sleep(1)
            continue
        do_job(*item)


# ---------------------------------------------------------------- HTTP
def _disk(path: str) -> dict:
    try:
        import shutil
        u = shutil.disk_usage(path if os.path.exists(path) else '/')
        return {'free': round(u.free / 2 ** 30, 1), 'total': round(u.total / 2 ** 30, 1)}
    except OSError:
        return {}


def health() -> dict:
    child = STATE.get('child')
    alive = child is not None and child.poll() is None
    broken = STATE['error'] if STATE['phase'] == 'failed' else (None if alive or STATE['phase'] in ('boot', 'weights', 'starting_comfy') else 'ComfyUI не работает')
    return {'ok': not broken, 'phase': STATE['phase'], 'warm': bool(STATE['warm']) and alive, 'error': STATE['error'] or broken, 'broken': broken, 'progress': STATE['progress'],
            'disk_gb': {'hf': _disk(DATA), 'out': _disk(OUT)}, 'timings': STATE['timings'], 'weights_gb': STATE.get('weights_gb'), 'uptime_s': round(time.time() - T0, 1), 'comfy_returncode': (child.returncode if child is not None else None),
            'log_tail': list(LOG_TAIL) if (broken or STATE['phase'] == 'failed') else list(LOG_TAIL)[-5:]}


class H(BaseHTTPRequestHandler):
    def log_message(self, fmt, *a):
        pass

    def _json(self, code: int, obj) -> None:
        b = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):  # noqa: N802
        p = self.path.split('?')[0]
        if p in ('/', '/health', '/ready'):
            return self._json(200, health())
        if p == '/info':
            return self._json(200, {'backend': 'comfy-0.46.0', 'gpu': (STATE.get('gpu') or {}).get('name'), 'vram_total': (STATE.get('gpu') or {}).get('vram_total'), 'weights_gb': STATE.get('weights_gb')})
        if p.startswith('/job/'):
            jid = os.path.basename(p[5:])
            d = JOBS.get(jid)
            if d is None and os.path.exists(job_path(jid)):
                d = json.load(open(job_path(jid), encoding='utf-8'))
            if d is None:
                return self._json(404, {'error': 'нет такого задания'})
            return self._json(200, {'job_id': jid, **d})
        if p.startswith('/glb/'):
            jid = os.path.basename(p[5:])
            vq = re.search(r'[?&]v=([A-Za-z0-9_-]+)', self.path)
            fp = os.path.join(OUT, f'{jid}.{vq.group(1)}.glb' if vq else f'{jid}.glb')
            d = JOBS.get(jid) or {}
            if d.get('status') != 'done' or not os.path.exists(fp):
                return self._json(404, {'error': 'GLB нет (задание не готово или упало)'})
            data = open(fp, 'rb').read()
            self.send_response(200)
            self.send_header('Content-Type', 'model/gltf-binary')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        self._json(404, {'error': 'нет такого пути'})

    def do_POST(self):  # noqa: N802
        if self.path.split('?')[0] != '/generate':
            return self._json(404, {'error': 'нет такого пути'})
        try:
            p = json.loads(self.rfile.read(int(self.headers.get('Content-Length') or 0)))
            jid = re.sub(r'[^A-Za-z0-9_.-]', '_', str(p['job_id']))
            p['image_b64']
        except (ValueError, KeyError) as e:
            return self._json(400, {'error': f'тело: {e}'})
        if not STATE['warm']:
            return self._json(503, {'error': 'воркер ещё не готов', 'phase': STATE['phase']})
        if jid in JOBS or os.path.exists(job_path(jid)):
            return self._json(409, {'error': 'такой job_id уже есть'})
        with LOCK:
            JOBS[jid] = {'status': 'queued'}
            QUEUE.append((jid, p))
        self._json(202, {'job_id': jid, 'status': 'queued'})


class DualStackServer(ThreadingHTTPServer):
    """Слушает и IPv6, и IPv4 одним сокетом (`::`, IPV6_V6ONLY=0). Шлюз и пробы Salad ходят по IPv6 (урок 724; docs.salad.com → gateway → enabling-ipv6): сервер только на `0.0.0.0` НЕ отвечал им ни разу —
    у comfy-проб t94h/t94i/t94k это дало «running, started=false, /health 503» при живом процессе (причина найдена 19.11 20:45)."""
    address_family = socket.AF_INET6
    daemon_threads = True

    def server_bind(self):
        self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        super().server_bind()


def make_server(port: int) -> ThreadingHTTPServer:
    try:
        return DualStackServer(('::', port), H)
    except OSError as e:                         # в окружении нет IPv6 — обычный IPv4
        print(f'[worker_comfy] IPv6 недоступен ({e}) — слушаю только IPv4', flush=True)
        return ThreadingHTTPServer(('0.0.0.0', port), H)


def main() -> None:
    global OUT, DATA
    print(f'[worker_comfy] старт: python {sys.version.split()[0]}, uid {os.getuid()}, cwd {os.getcwd()}, порт {PORT}', flush=True)
    for name in ('OUT', 'DATA'):                      # нет /data или нет прав — не падаем до открытия порта (иначе шлюз 503 и причины не видно): запасной путь в /tmp
        path = globals()[name]
        try:
            os.makedirs(path, exist_ok=True)
            if not os.access(path, os.W_OK):
                raise PermissionError(path)
        except OSError as e:
            alt = os.path.join('/tmp', 'comfy-' + name.lower())
            print(f'[worker_comfy] {path}: {e} — использую {alt}', flush=True)
            os.makedirs(alt, exist_ok=True)
            globals()[name] = alt
    server = make_server(PORT)                                   # порт открыт СРАЗУ, на IPv6+IPv4: /health отвечает 200 и во время докачки весов
    print('[worker_comfy] HTTP слушает, запускаю докачку весов', flush=True)
    threading.Thread(target=boot, daemon=True).start()
    server.serve_forever()


if __name__ == '__main__':
    main()
