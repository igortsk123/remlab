#!/usr/bin/env python3
"""ВОРКЕР ПРОБЫ ГЕНЕРАТОРА НА SALAD (T-20261118-91): одна нода, один генератор, результат отдаётся по HTTP через шлюз группы.

ЗАЧЕМ ОТДЕЛЬНО ОТ БОЕВОГО `worker.py`. Боевой воркер живёт за очередью заданий и кладёт меш в наш приёмник на проде (`/mesh-sink`). Для пробы
приёмник не нужен (диск прода красный, а проба — 3–6 GLB): воркер сам хранит результат и отдаёт его запросом, драйвер `trellis_trial.py`
забирает файл, замеряет и ГАСИТ группу. Только стандартная библиотека — образ тот же, что у модели.

Протокол (шлюз Salad с `Salad-Api-Key`; запросы короткие, генерация — асинхронно):
  GET  /health        живой ли процесс (всегда 200, в теле — фаза прогрева и тайминги) — стартовая проба группы
  GET  /ready         200 только когда модель на видеокарте и прогрета; 503 до того — проба готовности
  GET  /info          видеокарта (nvidia-smi), версии, тайминги холодного старта (контейнер → веса → видеокарта)
  POST /generate      {"job_id","image_b64","pipeline_type","seed","decimation_target","texture_size"} → 202; задания идут по одному (один GPU)
  GET  /job/<id>      состояние: queued|running|done|failed + замеры (секунды по стадиям, пик VRAM, треугольники, карты, МБ) или трассировка
  GET  /glb/<id>      байты `model.glb`

Бэкенд модели подключается по `MODEL` (`trellis2`); `MODEL=fake` — для теста без видеокарты (`tests_trellis_trial.py`). Токена Hugging Face в логи не пишем.
"""
from __future__ import annotations

import base64
import io
import json
import os
import subprocess
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

T_CONTAINER = time.time()
OUT = os.environ.get('OUT_DIR', '/tmp/trial-out')
PORT = int(os.environ.get('PORT', '8000'))
MAX_BODY = 40 * 2 ** 20
STATE = {'phase': 'starting', 'warm': False, 'error': None, 'timings': {'container_start_epoch': T_CONTAINER}}
JOBS: dict[str, dict] = {}
LOCK = threading.Lock()          # один GPU — задания по одному
JOBLOCK = threading.Lock()


def nvidia_smi() -> dict:
    """Видеокарта и занятая память ИЗ ДРАЙВЕРА (то, что видит Salad, а не только PyTorch)."""
    try:
        r = subprocess.run(['nvidia-smi', '--query-gpu=name,memory.total,memory.used,driver_version', '--format=csv,noheader,nounits'],
                           capture_output=True, text=True, timeout=20)
        n, t, u, d = [x.strip() for x in r.stdout.strip().splitlines()[0].split(',')]
        return {'name': n, 'memory_total_mib': int(t), 'memory_used_mib': int(u), 'driver': d}
    except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
        return {}


def glb_stats(path: str) -> dict:
    """Что внутри `model.glb`: размер файла, треугольники, вершины, карты PBR и их разрешения, габарит. Читает trimesh (в образе есть)."""
    import trimesh
    out = {'size_mb': round(os.path.getsize(path) / 2 ** 20, 2)}
    sc = trimesh.load(path, force='scene')
    tris = verts = 0
    maps: dict[str, list] = {}
    for g in sc.geometry.values():
        tris += len(getattr(g, 'faces', []))
        verts += len(getattr(g, 'vertices', []))
        mat = getattr(getattr(g, 'visual', None), 'material', None)
        for attr in ('baseColorTexture', 'metallicRoughnessTexture', 'normalTexture', 'emissiveTexture', 'occlusionTexture'):
            tex = getattr(mat, attr, None)
            if tex is not None:
                maps.setdefault(attr, []).append(list(getattr(tex, 'size', ())))
    out.update({'triangles': tris, 'vertices': verts, 'geometries': len(sc.geometry), 'maps': maps})
    try:
        out['bounds'] = [[round(float(x), 4) for x in row] for row in sc.bounds]
    except (TypeError, ValueError):
        pass
    return out


class FakeBackend:
    """Без видеокарты — для проверки протокола. Кладёт минимальный GLB (куб) и притворяется быстрой моделью."""
    name = 'fake'

    def load(self) -> dict:
        return {'weights_s': 0.0, 'to_gpu_s': 0.0}

    def generate(self, image, params: dict, path: str) -> dict:
        import trimesh
        trimesh.creation.box().export(path)
        return {'stage_s': {'run': 0.01, 'to_glb': 0.01}, 'peak_vram_gb': 0.0}


class Trellis2Backend:
    """TRELLIS.2-4B (MIT): `Trellis2ImageTo3DPipeline` → `o_voxel.postprocess.to_glb` (BaseColor/Metallic/Roughness/Alpha).
    Фон не удаляем: вход — наша вырезка с настоящей альфой (`preprocess_image` берёт её как есть), а модуль вырезки фона
    (`briaai/RMBG-2.0`: закрытый и некоммерческий) заменён заглушкой — не скачивается и не вызывается."""
    name = 'trellis2'

    def load(self) -> dict:
        os.environ.setdefault('PYTORCH_CUDA_ALLOC_CONF', 'expandable_segments:True')
        os.environ.setdefault('OPENCV_IO_ENABLE_OPENEXR', '1')
        sys.path.insert(0, os.environ.get('TRELLIS_DIR', '/opt/TRELLIS.2'))
        import torch
        from trellis2.pipelines import Trellis2ImageTo3DPipeline, rembg

        class NoRembg:                      # RMBG-2.0 не нужен и не разрешён (лицензия): с альфой на входе до него не доходит
            def __init__(self, **_kw):
                pass

            def to(self, *_a):
                return self

            def cpu(self):
                return self

            def __call__(self, *_a, **_k):
                raise RuntimeError('вырезка фона отключена: вход должен быть RGBA с настоящей альфой')
        rembg.BiRefNet = NoRembg
        t = time.time()
        self.pipe = Trellis2ImageTo3DPipeline.from_pretrained(os.environ.get('TRELLIS_MODEL', 'microsoft/TRELLIS.2-4B'))
        t_weights = time.time() - t
        t = time.time()
        self.pipe.cuda()
        torch.cuda.synchronize()
        return {'weights_s': round(t_weights, 1), 'to_gpu_s': round(time.time() - t, 1)}

    def generate(self, image, params: dict, path: str) -> dict:
        import o_voxel
        import torch
        torch.cuda.reset_peak_memory_stats()
        stage = {}
        t = time.time()
        mesh = self.pipe.run(image, seed=int(params.get('seed', 42)), pipeline_type=params.get('pipeline_type') or '1024_cascade')[0]
        torch.cuda.synchronize()
        stage['run'] = round(time.time() - t, 2)
        peak_run = torch.cuda.max_memory_allocated() / 2 ** 30
        t = time.time()
        mesh.simplify(16777216)             # предел nvdiffrast, как в example.py
        glb = o_voxel.postprocess.to_glb(
            vertices=mesh.vertices, faces=mesh.faces, attr_volume=mesh.attrs, coords=mesh.coords, attr_layout=mesh.layout,
            voxel_size=mesh.voxel_size, aabb=[[-0.5, -0.5, -0.5], [0.5, 0.5, 0.5]],
            decimation_target=int(params.get('decimation_target', 500000)), texture_size=int(params.get('texture_size', 2048)),
            remesh=True, remesh_band=1, remesh_project=0, verbose=False)
        torch.cuda.synchronize()
        stage['to_glb'] = round(time.time() - t, 2)
        # PNG-текстуры (без EXT_texture_webp): тот же вид GLB, что у Hunyuan, — наши рендеры читают его без расширений
        glb.export(path, extension_webp=bool(int(os.environ.get('EXPORT_WEBP', '0'))))
        return {'stage_s': stage, 'peak_vram_gb': round(max(peak_run, torch.cuda.max_memory_allocated() / 2 ** 30), 2),
                'peak_reserved_gb': round(torch.cuda.max_memory_reserved() / 2 ** 30, 2)}


class Hunyuan21Backend:
    """КОНТРОЛЬ: боевой Hunyuan3D-2.1 из боевого образа (`pipeline.generate`, ровно как `/generate` боевого воркера, но без очереди и приёмника): вход — наша
    RGBA-вырезка (то же `shape_img`, что у боевого пути), для покраски — `preprocess._paint_crop(shape_img)`, роль и габариты — из задания. Код воркера
    передаётся в боевой образ через `command` (как у боевых групп), образ не пересобирается. Модули `pipeline`/`preprocess`/`fetch_weights` — из /app образа."""
    name = 'hunyuan21'

    def load(self) -> dict:
        import fetch_weights
        import pipeline as P
        from PIL import Image, ImageDraw
        t = time.time()
        fw = fetch_weights.ensure()                  # веса вшиты в образ — пусто; иначе докачка (холодный старт)
        t_w = time.time() - t
        t = time.time()
        img = Image.new('RGBA', (512, 512), (0, 0, 0, 0))                    # прогрев как у боевого воркера: ядра и веса — не в замер первого задания
        ImageDraw.Draw(img).ellipse((128, 128, 384, 384), fill=(200, 180, 160, 255))
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            P.generate(img, d, seed=0, params={'num_inference_steps': 5, 'octree_resolution': 128})
        return {'weights_s': round(t_w, 1), 'weights_fetch': fw, 'warmup_gen_s': round(time.time() - t, 1)}

    def generate(self, image, params: dict, path: str) -> dict:
        import shutil
        import tempfile
        import pipeline as P
        import preprocess as PRE
        shape_img = image.convert('RGBA')
        dims = params.get('dims_cm') or []
        pp = {'_dims': {'w': dims[0], 'd': dims[1], 'h': dims[2], 'dia': None} if len(dims) == 3 else {},
              '_square_role': params.get('role') in ('кашпо', 'ваза', 'торшер', 'лампа', 'пуф')}
        work = tempfile.mkdtemp(prefix='mesh-')
        try:
            res = P.generate(shape_img, work, seed=int(params.get('seed', 0)), params=pp, paint_image=PRE._paint_crop(shape_img), role=params.get('role'))
            shutil.copy(res['glb'], path)
            g = res.get('gpu') or {}
            return {'stage_s': res['timings'], 'peak_vram_gb': max(g.get('shape_gb') or 0, g.get('paint_gb') or 0), 'gpu_pipeline': g, 'mode': res.get('mode', 'full')}
        finally:
            shutil.rmtree(work, ignore_errors=True)


def backend():
    return {'trellis2': Trellis2Backend, 'hunyuan21': Hunyuan21Backend, 'fake': FakeBackend}[os.environ.get('MODEL', 'trellis2')]()


BACKEND = None


def warm() -> None:
    """Прогрев: загрузка весов (Hugging Face) и перенос на видеокарту. Тело обёрнуто целиком, `warm` — в finally (урок боевого воркера 29.08)."""
    global BACKEND
    try:
        STATE['phase'] = 'loading'
        BACKEND = backend()
        t = time.time()
        STATE['timings'].update(BACKEND.load())
        STATE['timings']['warm_total_s'] = round(time.time() - t, 1)
        STATE['timings']['container_to_ready_s'] = round(time.time() - T_CONTAINER, 1)
        STATE['phase'] = 'ready'
        STATE['warm'] = True
    except Exception as e:  # noqa: BLE001
        STATE['phase'] = 'failed'
        STATE['error'] = f'{type(e).__name__}: {str(e)[:400]}'
        print('ПРОГРЕВ УПАЛ:\n' + traceback.format_exc()[-2500:], flush=True)


def run_job(job_id: str, body: dict) -> None:
    from PIL import Image
    job = JOBS[job_id]
    with LOCK:
        job['status'] = 'running'
        job['started'] = time.time()
        try:
            img = Image.open(io.BytesIO(base64.b64decode(body['image_b64'])))
            img.load()
            job['input'] = {'mode': img.mode, 'size': list(img.size)}
            path = os.path.join(OUT, f'{job_id}.glb')
            os.makedirs(OUT, exist_ok=True)
            t = time.time()
            m = BACKEND.generate(img, body, path)
            m['total_s'] = round(time.time() - t, 2)
            m['gpu_after'] = nvidia_smi()
            m['glb'] = glb_stats(path)
            job['metrics'] = m
            job['status'] = 'done'
        except Exception as e:  # noqa: BLE001
            job['status'] = 'failed'
            job['error'] = f'{type(e).__name__}: {str(e)[:400]}'
            job['trace'] = traceback.format_exc()[-2500:]
            print(f'ЗАДАНИЕ {job_id} УПАЛО:\n' + job['trace'], flush=True)
        finally:
            job['finished'] = time.time()


class H(BaseHTTPRequestHandler):
    def log_message(self, *_a):          # в журнал контейнера — только своё
        pass

    def _json(self, code: int, obj) -> None:
        raw = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):  # noqa: N802
        p = self.path.split('?')[0]
        if p == '/health':
            return self._json(200, {'ok': True, 'phase': STATE['phase'], 'warm': STATE['warm'], 'error': STATE['error'], 'timings': STATE['timings'],
                                    'uptime_s': round(time.time() - T_CONTAINER, 1)})
        if p == '/ready':
            return self._json(200 if STATE['warm'] else 503, {'ready': STATE['warm'], 'phase': STATE['phase'], 'error': STATE['error']})
        if p == '/info':
            return self._json(200, {'gpu': nvidia_smi(), 'python': sys.version.split()[0], 'model': os.environ.get('MODEL', 'trellis2'),
                                    'image_note': os.environ.get('IMAGE_NOTE', ''), 'timings': STATE['timings'], 'versions': versions()})
        if p.startswith('/job/'):
            j = JOBS.get(p[5:])
            return self._json(200 if j else 404, j or {'error': 'нет такого задания'})
        if p.startswith('/glb/'):
            j = JOBS.get(p[5:])
            fp = os.path.join(OUT, f'{p[5:]}.glb')
            if not j or j.get('status') != 'done' or not os.path.exists(fp):
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
        n = int(self.headers.get('Content-Length') or 0)
        if n <= 0 or n > MAX_BODY:
            return self._json(413, {'error': 'тело пустое или больше 40 МБ'})
        try:
            body = json.loads(self.rfile.read(n))
            jid = str(body['job_id'])
            body['image_b64']
        except (ValueError, KeyError):
            return self._json(400, {'error': 'нужны job_id и image_b64'})
        if not STATE['warm']:
            return self._json(503, {'error': 'модель ещё не готова', 'phase': STATE['phase']})
        with JOBLOCK:
            if jid in JOBS:
                return self._json(409, {'error': 'такой job_id уже есть', 'status': JOBS[jid].get('status')})     # повтор не жжёт GPU второй раз
            JOBS[jid] = {'job_id': jid, 'status': 'queued', 'queued': time.time(), 'params': {k: v for k, v in body.items() if k != 'image_b64'}}
        threading.Thread(target=run_job, args=(jid, body), daemon=True).start()
        self._json(202, {'job_id': jid, 'status': 'queued'})


def versions() -> dict:
    out = {}
    for mod in ('torch', 'trimesh', 'transformers', 'flash_attn', 'o_voxel', 'nvdiffrast'):
        try:
            m = __import__(mod)
            out[mod] = getattr(m, '__version__', 'ok')
        except Exception:  # noqa: BLE001
            out[mod] = None
    try:
        import torch
        out['cuda'] = torch.version.cuda
    except Exception:  # noqa: BLE001
        pass
    return out


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    threading.Thread(target=warm, daemon=True).start()
    print(f'воркер пробы: порт {PORT}, модель {os.environ.get("MODEL", "trellis2")}', flush=True)
    ThreadingHTTPServer(('0.0.0.0', PORT), H).serve_forever()


if __name__ == '__main__':
    main()
