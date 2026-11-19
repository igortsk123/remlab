#!/usr/bin/env python3
"""ВОРКЕР ПРОБЫ UltraTex (вариант 8, T-20261119-90/2): «готовая форма (GLB) + ОДНО фото (RGBA) → GLB с альбедо-текстурой».
Едет в образе `Dockerfile.ultratex` на под RunPod (карта 80 ГБ: A100 sm_80 / H100 sm_90). Один GPU — одно задание за раз.

ЧТО ДЕЛАЕТ (всё — наша сборка из трёх чужих MIT-частей, см. ultratex_core/NOTICE.md):
  1. `ultratex_core.prep` (из ComfyUI-UltraTex, MIT): нормирует форму, берёт её развёртку (или xatlas), рендерит 6 канонических видов карт нормалей
     (moderngl/EGL), подгоняет фото к фронтальному виду;
  2. код АВТОРОВ UltraTex (`train_flux2.inference`, MIT; база FLUX.2-klein-base-9B + LoRA UltraTex 9B + декодер) рисует 6 видов альбедо 2×3 по нормалям и фото;
  3. `ultratex_core.bake` (из ComfyUI-UltraTex, MIT) запекает 6 видов в UV 4096² → GLB.
Форма НЕ меняется (оптимизируется только текстура; грани и их число — в метриках), ключ — только в окружении пода, не в образе.

HTTP (порт $PORT, по умолчанию 8000; на RunPod — через прокси `https://<pod>-8000.proxy.runpod.net`):
  GET  /health                 → {"phase": weights|loading|ready|busy|broken, ...} (прогрев весов и модели — минуты; ход — в `weights`)
  POST /generate               {"job_id","image_b64"(RGBA PNG),"glb_b64","resolution"(1024|2048),"steps","guidance","seed","texture_size"} → 202
  GET  /result/<job_id>        → {"status": running|done|failed, "metrics": {...}, "error": "..."}
  GET  /result/<job_id>/glb    → байты GLB (только при done)
  POST /shutdown               → процесс завершается (под RunPod после выхода контейнера — «exited», счёт за GPU прекращается)
АВТОСТОП ПОДА: выход процесса при MAX_LIFETIME_S (по умолчанию 5400 с = 90 мин от старта) ИЛИ IDLE_S без заданий после готовности (по умолчанию 900 с);
драйвер всё равно удаляет под сам и проверяет, что его нет в списке.
"""
from __future__ import annotations

import base64
import io
import json
import logging
import os
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

log = logging.getLogger('ultratex-worker')

VERSION = 'ultratex-worker-1'
ULTRATEX_COMMIT = 'a726678f3f3631fe2c5e3d1fb4597114784c7a8b'     # код авторов (MIT), клонируется в образ
GRID_ORDER = [[0, 1, 3], [2, 4, 5]]                              # раскладка 2×3 как у авторов (render.GRID_ORDER)
RESOLUTIONS = (1024, 2048)                                       # разрешение вида; LoRA обучена на 2048 (FLUX.2-ветка)
DEFAULTS = {'resolution': 2048, 'steps': 25, 'guidance': 4.0, 'seed': 42, 'texture_size': 4096}
MAX_GLB_BYTES = 120 * 2 ** 20
MAX_IMAGE_BYTES = 30 * 2 ** 20


# ---------------------------------------------------------------- веса: что и откуда
def plan_weights(root: str) -> list[dict]:
    """Список весов: куда кладём и откуда берём. Ничего не качает. `gated` — закрытые репозитории HF (нужен токен С ПРИНЯТЫМИ условиями)."""
    base = os.path.join(root, 'base', 'flux2')
    return [
        {'name': 'ultratex_lora', 'src': 'modelscope', 'repo': 'Yibo-Zhang/UltraTex', 'file': 'flux2/lora/dit_lora.safetensors',
         'dest': os.path.join(root, 'checkpoints', 'flux2', 'lora', 'dit_lora.safetensors'), 'gated': False, 'approx_gb': 0.46},
        {'name': 'ultratex_decoder', 'src': 'modelscope', 'repo': 'Yibo-Zhang/UltraTex', 'file': 'flux2/decoder.pt',
         'dest': os.path.join(root, 'checkpoints', 'flux2', 'decoder.pt'), 'gated': False, 'approx_gb': 0.1},
        {'name': 'flux2_klein_base_9b', 'src': 'hf', 'repo': 'black-forest-labs/FLUX.2-klein-base-9B', 'file': 'flux-2-klein-base-9b.safetensors',
         'dest': os.path.join(base, 'flux-2-klein-base-9b.safetensors'), 'gated': True, 'approx_gb': 18.0, 'env': 'KLEIN_9B_BASE_MODEL_PATH'},
        {'name': 'flux2_ae', 'src': 'hf', 'repo': 'black-forest-labs/FLUX.2-dev', 'file': 'ae.safetensors',
         'dest': os.path.join(base, 'ae.safetensors'), 'gated': True, 'approx_gb': 0.34, 'env': 'AE_MODEL_PATH'},
        {'name': 'qwen3_8b', 'src': 'hf_dir', 'repo': 'Qwen/Qwen3-8B', 'file': '',
         'dest': os.path.join(base, 'qwen3-8b'), 'gated': False, 'approx_gb': 16.4, 'env': 'QWEN3_8B_PATH'},
    ]


def weights_env(root: str) -> dict:
    """Переменные окружения, по которым код авторов находит веса (без скачивания)."""
    return {w['env']: w['dest'] for w in plan_weights(root) if w.get('env')}


class WeightsDenied(RuntimeError):
    """Закрытый репозиторий не пускает токен (403/401): условия лицензии не приняты или токена нет."""


def _present(w: dict) -> bool:
    if w['src'] == 'hf_dir':
        return os.path.isfile(os.path.join(w['dest'], 'config.json')) and os.path.isfile(os.path.join(w['dest'], '.complete'))
    return os.path.isfile(w['dest']) and os.path.getsize(w['dest']) > 0


def fetch_weights(root: str, hf_token: str, progress=None) -> dict:
    """Докачка недостающего (идемпотентно). progress(name, state) — для /health. Закрытое без допуска → WeightsDenied с именем репозитория."""
    progress = progress or (lambda name, state: None)
    done = {}
    for w in plan_weights(root):
        if _present(w):
            progress(w['name'], 'есть')
            done[w['name']] = 'есть'
            continue
        progress(w['name'], f"качаю ~{w['approx_gb']} ГБ")
        os.makedirs(os.path.dirname(w['dest']) if w['src'] != 'hf_dir' else w['dest'], exist_ok=True)
        try:
            if w['src'] == 'modelscope':
                from modelscope import snapshot_download      # noqa: WPS433 (в образе)
                tmp = snapshot_download(w['repo'], allow_patterns=[w['file']], local_dir=os.path.join(root, '_ms'))
                os.replace(os.path.join(tmp, w['file']), w['dest'])
            elif w['src'] == 'hf':
                from huggingface_hub import hf_hub_download
                p = hf_hub_download(w['repo'], w['file'], token=hf_token or None, local_dir=os.path.join(root, '_hf', w['name']))
                os.replace(p, w['dest'])
            else:
                from huggingface_hub import snapshot_download as hf_snap
                hf_snap(w['repo'], token=hf_token or None, local_dir=w['dest'], allow_patterns=['*.json', '*.safetensors', '*.txt', 'merges.txt', 'vocab.json'])
                open(os.path.join(w['dest'], '.complete'), 'w').close()
        except Exception as exc:                               # noqa: BLE001
            msg = str(exc)
            if w['gated'] and any(t in msg for t in ('401', '403', 'gated', 'GatedRepo', 'restricted', 'Access to model')):
                raise WeightsDenied(f"нет допуска к {w['repo']} (условия лицензии не приняты в аккаунте токена или токен не передан): {msg[:200]}") from exc
            raise
        progress(w['name'], 'готово')
        done[w['name']] = 'готово'
    return done


# ---------------------------------------------------------------- вход сети: чистая арифметика
def _resize_rgba(rgba: np.ndarray, size: int):
    from PIL import Image
    return Image.fromarray(rgba).resize((size, size), Image.Resampling.BILINEAR)


def _on_white(img) -> np.ndarray:
    from PIL import Image
    bg = Image.new('RGB', img.size, (255, 255, 255))
    bg.paste(img, mask=img.getchannel('A'))
    return np.asarray(bg)


def _small_mask(rgba: np.ndarray, size: int) -> np.ndarray:
    """alpha > 0 на разрешении токенов (R/16), раздутая как cv2.dilate(ones(2,2)) у авторов."""
    m = np.asarray(_resize_rgba(rgba, size).getchannel('A')) > 0
    d = m.copy()
    d[1:] |= m[:-1]
    d[:, 1:] |= m[:, :-1]
    d[1:, 1:] |= m[:-1, :-1]
    return d


def grid(tiles) -> np.ndarray:
    """6 плиток (view-порядок 0..5) → холст 2×3: строка 1 = виды 0,1,3; строка 2 = 2,4,5 (как у TexVerse)."""
    return np.concatenate([np.concatenate([tiles[v] for v in row], axis=1) for row in GRID_ORDER], axis=0)


def tiles_from_grid(img: np.ndarray, res: int) -> np.ndarray:
    """Холст 2R×3R → (6, R, R, C) в порядке видов (обратно к `grid`)."""
    out = np.zeros((6,) + (res, res) + img.shape[2:], dtype=img.dtype)
    for r, row in enumerate(GRID_ORDER):
        for c, v in enumerate(row):
            out[v] = img[r * res:(r + 1) * res, c * res:(c + 1) * res]
    return out


def build_conditions(normal_rgba: np.ndarray, reference_rgba: np.ndarray, res: int) -> dict:
    """Картинки и маски, как их собирает датасет авторов (альфа цели = альфа нормалей). normal_rgba: (6,S,S,4) uint8; reference_rgba: (S,S,4)."""
    s = res // 16
    normal_tiles, small, full = [], [], []
    for v in range(6):
        big = _resize_rgba(normal_rgba[v], res)
        normal_tiles.append(_on_white(big))
        full.append(np.asarray(big.getchannel('A')) > 0)
        small.append(_small_mask(normal_rgba[v], s))
    return {
        'normal_grid': grid(normal_tiles),                       # (2R, 3R, 3) uint8
        'reference': _on_white(_resize_rgba(reference_rgba, res)),   # (R, R, 3) uint8
        'mask_target': grid(small).astype(bool),                 # (2s, 3s)
        'mask_normals': grid(small).astype(bool),
        'mask_reference': _small_mask(reference_rgba, s).astype(bool),   # (s, s)
        'mask_full_grid': grid(full).astype(bool),               # (2R, 3R)
    }


def validate_job(body: dict) -> tuple[dict, str | None]:
    """Разбор задания: (параметры с умолчаниями, текст ошибки). Размер/формат — до всякой работы."""
    if not isinstance(body, dict):
        return {}, 'тело задания — не объект'
    for k in ('job_id', 'image_b64', 'glb_b64'):
        if not body.get(k):
            return {}, f'нет поля {k}'
    p = dict(DEFAULTS)
    for k in DEFAULTS:
        if body.get(k) is not None:
            p[k] = body[k]
    try:
        p['resolution'], p['steps'], p['seed'], p['texture_size'] = int(p['resolution']), int(p['steps']), int(p['seed']), int(p['texture_size'])
        p['guidance'] = float(p['guidance'])
    except (TypeError, ValueError):
        return {}, 'resolution/steps/seed/texture_size — целые, guidance — число'
    if p['resolution'] not in RESOLUTIONS:
        return {}, f'resolution должен быть из {RESOLUTIONS}'
    if not 1 <= p['steps'] <= 60:
        return {}, 'steps вне 1..60'
    if not 512 <= p['texture_size'] <= 8192 or p['texture_size'] % 512:
        return {}, 'texture_size — кратно 512, 512..8192'
    p['job_id'] = str(body['job_id'])
    if not p['job_id'].replace('-', '').replace('_', '').replace('.', '').replace(':', '').isalnum() or len(p['job_id']) > 160:
        return {}, 'job_id: буквы, цифры и - _ . :, до 160 знаков'
    return p, None


# ---------------------------------------------------------------- автостоп
class Watchdog:
    """Решает, пора ли процессу выйти. Время и «занят» подаёт вызывающий (проверяется тестом без сна)."""

    def __init__(self, max_lifetime_s: float, idle_s: float, now=time.time):
        self.now, self.max_lifetime_s, self.idle_s = now, max_lifetime_s, idle_s
        self.t0 = now()
        self.last_activity = self.t0

    def touch(self):
        self.last_activity = self.now()

    def verdict(self, ready: bool, busy: bool) -> str | None:
        t = self.now()
        if t - self.t0 >= self.max_lifetime_s:
            return f'предел жизни {self.max_lifetime_s:.0f} с'
        if ready and not busy and t - self.last_activity >= self.idle_s:
            return f'простой {self.idle_s:.0f} с без заданий'
        return None


# ---------------------------------------------------------------- модель и задание (нужны GPU и тяжёлые пакеты — только здесь)
class Engine:
    """Загружает код авторов и модель один раз, потом принимает задания."""

    def __init__(self, root: str, upstream_dir: str):
        self.root, self.upstream = root, upstream_dir
        self.ready = False
        self.models = None

    def load(self, resolution_hint: int = 2048):
        env = weights_env(self.root)
        os.environ.update(env)
        os.environ.setdefault('WANDB_MODE', 'offline')
        sys.path.insert(0, self.upstream)
        os.chdir(self.upstream)
        import inference_flux2 as inf                          # код авторов
        from accelerate import Accelerator
        self.inf = inf
        self.accelerator = Accelerator(mixed_precision='bf16')
        ckpt = os.path.join(self.root, 'checkpoints', 'flux2', 'lora', 'dit_lora.safetensors')
        self.args = inf.InferenceArgs(resolution=resolution_hint, decoder_ckpt=os.path.join(self.root, 'checkpoints', 'flux2', 'decoder.pt'),
                                      resume_from_checkpoint=ckpt, project_dir=os.path.join(self.root, 'out'))
        self.trainer = inf.get_trainer('albedo')
        self.models = inf.load_inference_models(self.args, self.accelerator, inf.Path(ckpt), self.trainer)
        self.ready = True

    def _batch(self, cond: dict):
        import torch
        dev = self.accelerator.device

        def tf(arr):                                           # ToTensor + Normalize([0.5],[0.5]) как у датасета авторов
            return ((torch.from_numpy(np.ascontiguousarray(arr)).permute(2, 0, 1).float() / 255.0 - 0.5) / 0.5)[None]
        # цель (нужна только форма латента): серый холст той же формы, что холст нормалей
        target = np.zeros_like(cond['normal_grid'])
        masks = [torch.from_numpy(cond[k].astype(np.float32)) for k in ('mask_target', 'mask_normals', 'mask_reference')]
        return {'id': ['job'], 'txt': [''], 'img': tf(target), 'ref_imgs': [tf(cond['normal_grid']), tf(cond['reference'])],
                'masks': [masks], 'masks_full': [[torch.from_numpy(cond['mask_full_grid'].astype(np.float32))]]}, dev

    def run(self, p: dict, glb: bytes, png: bytes) -> tuple[bytes, dict]:
        import torch
        import trimesh
        from PIL import Image
        from ultratex_core import bake as bake_core, prep as prep_core
        m: dict = {'version': VERSION, 'params': {k: p[k] for k in DEFAULTS}}
        t0 = time.time()
        mesh = trimesh.load(io.BytesIO(glb), file_type='glb')
        ref = np.asarray(Image.open(io.BytesIO(png)).convert('RGBA'))
        if int((ref[..., 3] > 8).sum()) < 64:
            raise ValueError('фото без маски (альфа пустая): нужен RGBA-вырез')
        prep = prep_core.run_prep(mesh, ref, p['resolution'], p['texture_size'], 'keep_existing', 'fit_front_silhouette')
        m['prep_s'] = round(time.time() - t0, 2)
        m['faces'] = int(len(prep.faces))
        m['view_coverage_pct'] = [round(float((prep.normal_rgba[v, ..., 3] > 0).mean() * 100), 2) for v in range(6)]
        t1 = time.time()
        cond = build_conditions(prep.normal_rgba, prep.reference_rgba, p['resolution'])
        batch, dev = self._batch(cond)
        model, ae, te = self.models
        torch.cuda.reset_peak_memory_stats()
        black = Image.new('RGB', (p['resolution'], p['resolution']), (0, 0, 0))
        bt = ((torch.from_numpy(np.asarray(black)).permute(2, 0, 1).float() / 255.0 - 0.5) / 0.5)[None].to(dev)
        with torch.no_grad():
            background = ae.encode(bt.float()).repeat(1, 1, 2, 3)
            result = self.trainer.inference(batch, model, te, ae, self.accelerator, seed=p['seed'], resolution=p['resolution'], background=background,
                                            guidance=p['guidance'], remove_background=True, drop_background_tokens=True, num_steps=p['steps'])
        m['sample_s'] = round(time.time() - t1, 2)
        m['vram_peak_gb'] = round(torch.cuda.max_memory_allocated() / 2 ** 30, 2)
        views = tiles_from_grid(np.asarray(result.convert('RGB'), dtype=np.float32) / 255.0, p['resolution'])
        t2 = time.time()
        masks = np.stack([np.asarray(Image.fromarray(prep.normal_rgba[v, ..., 3]).resize((p['resolution'],) * 2, Image.Resampling.BILINEAR)) > 0 for v in range(6)])
        baker = bake_core.Baker(prep, p['texture_size'])
        try:
            albedo_np, conf = baker.bake([(views, masks, None)], bake_core.BakeSettings())
            albedo = bake_core.to_pil(albedo_np)
        finally:
            baker.release()
        out = bake_core.textured_mesh(prep, albedo, None)
        buf = io.BytesIO()
        out.export(buf, file_type='glb')
        m['bake_s'] = round(time.time() - t2, 2)
        m['texel_seen_pct'] = round(float((np.asarray(conf) > 0).mean() * 100), 2)
        m['total_s'] = round(time.time() - t0, 2)
        m['faces_out'] = int(len(out.faces))
        return buf.getvalue(), m


# ---------------------------------------------------------------- сервер
class State:
    def __init__(self):
        self.phase = 'weights'
        self.weights: dict = {}
        self.error = ''
        self.jobs: dict[str, dict] = {}
        self.busy = False
        self.lock = threading.Lock()
        self.t_start = time.time()


def make_handler(state: State, engine: Engine, wd: Watchdog, stop: threading.Event):
    class H(BaseHTTPRequestHandler):
        def log_message(self, fmt, *a):                        # тихо: журнал — в наш логгер
            log.debug(fmt, *a)

        def _json(self, code, obj):
            raw = json.dumps(obj, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):                                      # noqa: N802
            wd.touch()
            if self.path == '/health':
                return self._json(200, {'phase': state.phase, 'weights': state.weights, 'error': state.error, 'version': VERSION,
                                        'uptime_s': round(time.time() - state.t_start), 'busy': state.busy})
            parts = self.path.strip('/').split('/')
            if parts[0] == 'result' and len(parts) >= 2:
                j = state.jobs.get(parts[1])
                if not j:
                    return self._json(404, {'error': 'нет такого задания'})
                if len(parts) == 3 and parts[2] == 'glb':
                    if j['status'] != 'done':
                        return self._json(409, {'error': 'ещё не готово'})
                    self.send_response(200)
                    self.send_header('Content-Type', 'model/gltf-binary')
                    self.send_header('Content-Length', str(len(j['glb'])))
                    self.end_headers()
                    return self.wfile.write(j['glb'])
                return self._json(200, {k: v for k, v in j.items() if k != 'glb'})
            return self._json(404, {'error': 'нет такого пути'})

        def do_POST(self):                                     # noqa: N802
            wd.touch()
            n = int(self.headers.get('Content-Length') or 0)
            if self.path == '/shutdown':
                self._json(200, {'ok': True})
                stop.set()
                return
            if self.path != '/generate':
                return self._json(404, {'error': 'нет такого пути'})
            if n > MAX_GLB_BYTES + MAX_IMAGE_BYTES:
                return self._json(413, {'error': 'тело больше лимита'})
            try:
                body = json.loads(self.rfile.read(n) or b'{}')
            except ValueError:
                return self._json(400, {'error': 'не JSON'})
            p, err = validate_job(body)
            if err:
                return self._json(400, {'error': err})
            if state.phase != 'ready':
                return self._json(503, {'error': f'не готов: фаза {state.phase}'})
            with state.lock:
                if state.busy:
                    return self._json(429, {'error': 'занят другим заданием'})
                state.busy = True
            try:
                glb, png = base64.b64decode(body['glb_b64']), base64.b64decode(body['image_b64'])
            except Exception:                                  # noqa: BLE001
                state.busy = False
                return self._json(400, {'error': 'base64 не разобран'})
            state.jobs[p['job_id']] = {'status': 'running', 'metrics': {}, 'error': ''}
            threading.Thread(target=_work, args=(state, engine, p, glb, png), daemon=True).start()
            return self._json(202, {'job_id': p['job_id']})
    return H


def _work(state: State, engine: Engine, p: dict, glb: bytes, png: bytes):
    j = state.jobs[p['job_id']]
    try:
        out, metrics = engine.run(p, glb, png)
        j.update(status='done', metrics=metrics, glb=out)
    except Exception as exc:                                   # noqa: BLE001
        j.update(status='failed', error=f'{type(exc).__name__}: {exc}', trace=traceback.format_exc()[-1500:])
        if 'CUDA error' in str(exc) or 'illegal memory access' in str(exc):
            state.phase = 'broken'                             # фатальная ошибка CUDA: нода непригодна, новые задания не берём
    finally:
        state.busy = False


def main() -> int:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
    root = os.environ.get('ULTRATEX_ROOT', '/workspace/ultratex')
    upstream = os.environ.get('ULTRATEX_DIR', '/opt/UltraTex')
    port = int(os.environ.get('PORT', '8000'))
    wd = Watchdog(float(os.environ.get('MAX_LIFETIME_S', '5400')), float(os.environ.get('IDLE_S', '900')))
    state, stop = State(), threading.Event()
    engine = Engine(root, upstream)
    srv = ThreadingHTTPServer(('0.0.0.0', port), make_handler(state, engine, wd, stop))
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    def warm():
        try:
            fetch_weights(root, os.environ.get('HF_TOKEN', ''), lambda n, s: state.weights.__setitem__(n, s))
            state.phase = 'loading'
            engine.load()
            state.phase = 'ready'
            wd.touch()
        except WeightsDenied as exc:
            state.phase, state.error = 'broken', f'WEIGHTS_DENIED: {exc}'
        except Exception as exc:                               # noqa: BLE001
            state.phase, state.error = 'broken', f'{type(exc).__name__}: {exc}'
            log.error('прогрев упал: %s', traceback.format_exc())
    threading.Thread(target=warm, daemon=True).start()
    while not stop.is_set():
        why = wd.verdict(state.phase == 'ready', state.busy)
        if why:
            log.warning('АВТОСТОП: %s', why)
            break
        stop.wait(5)
    log.warning('выход процесса (под остановится сам)')
    srv.shutdown()
    return 0


if __name__ == '__main__':
    sys.exit(main())
