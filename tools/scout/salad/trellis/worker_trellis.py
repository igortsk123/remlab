#!/usr/bin/env python3
"""ВОРКЕР ПРОБЫ ГЕНЕРАТОРА НА SALAD (T-20261118-91): одна нода, один генератор, результат отдаётся по HTTP через шлюз группы.

ЗАЧЕМ ОТДЕЛЬНО ОТ БОЕВОГО `worker.py`. Боевой воркер живёт за очередью заданий и кладёт меш в наш приёмник на проде (`/mesh-sink`). Для пробы
приёмник не нужен (диск прода красный, а проба — несколько десятков GLB): воркер сам хранит результат и отдаёт его запросом, драйвер `trellis_trial.py`
забирает файл, замеряет и ГАСИТ группу. Только стандартная библиотека — образ тот же, что у модели.

ДВА ПРОЦЕССА (урок первого запуска 18.11, шаг 0): прогон 1 — воркер был одним процессом (HTTP-сервер + загрузка модели в потоке), после загрузки DINOv3 вывод
оборвался, 20 минут стартовая проба `/health` не проходила, Salad перезапустил машину («Instance Interrupted (Startup Probe Failure)»); причину по журналу
установить нельзя (ни трассировки, ни `Exited`): либо убит по памяти, либо поток загрузки держал GIL. Теперь:
  • ГЛАВНЫЙ процесс — только лёгкий HTTP-сервер (без torch): `/health` отвечает ВСЕГДА, показывает фазу ребёнка, его память (RSS), память группы (cgroup),
    код выхода ребёнка (−9 = убит по памяти) и пишет строку состояния в журнал раз в 30 с;
  • ДОЧЕРНИЙ процесс — загрузка модели и генерация; раз в 5 с пишет состояние в файл; `faulthandler` печатает стеки всех потоков раз в 4 минуты (в журнал) — видно,
    где завис. Связь — файлами в `/tmp/trial_jobs` (запрос/результат), без общей памяти.

Протокол (шлюз Salad с `Salad-Api-Key`; запросы короткие, генерация — асинхронно):
  GET  /health        всегда 200: фаза, ошибка, тайминги, progress (ГБ в кэше Hugging Face), child{alive, returncode, rss_gb, state_age_s}, cgroup_gb
  GET  /ready         200 только когда модель на видеокарте, прогрета и ребёнок жив; иначе 503
  GET  /info          видеокарта (nvidia-smi), версии, тайминги холодного старта
  POST /generate      {"job_id","image_b64","pipeline_type","seed","decimation_target","texture_size","role","dims_cm"} → 202; задания идут по одному (один GPU)
  GET  /job/<id>      состояние: queued|running|done|failed + замеры (секунды по стадиям, пик VRAM, треугольники, карты, МБ) или трассировка
  GET  /glb/<id>      байты `model.glb` (`?v=ai` — localmesh: текстура до проекции фото; `?v=stages` — mvadapter-i2tex с `mv_keep_stages=1`: архив стадий `stages.zip`, А0)

Бэкенд модели — по `MODEL` (`trellis2` | `pixal3d` | `pixal3d-tex` (краска Pixal3D по готовой форме) | `mvadapter-i2tex` (краска MV-Adapter по готовой форме) | `mvpainter` (краска MVPainter по готовой форме; форму упрощает штатно) | `supratex` (краска SUPRA-Tex с Qwen-Image-2.1 по готовой форме; форму и развёртку выпуск меняет) | `hunyuan21`); `MODEL=fake` — для теста без видеокарты (`tests_trellis_trial.py`). Токена Hugging Face в логи не пишем.
"""
from __future__ import annotations

import base64
import io
import json
import os
import socket
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
STATE_PATH = os.environ.get('TRIAL_STATE', '/tmp/trial_state.json')
JOBS_DIR = os.environ.get('TRIAL_JOBS', '/tmp/trial_jobs')
STATE = {'phase': 'starting', 'warm': False, 'error': None, 'timings': {'container_start_epoch': T_CONTAINER}}      # состояние РЕБЁНКА (пишется в файл)
CHILD = None                                                                                                      # Popen ребёнка (в главном процессе)
CHILD_RC_LOGGED = False


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
        STATE['phase'] = 'importing'
        t_imp = time.time()
        import torch
        from trellis2.pipelines import Trellis2ImageTo3DPipeline, rembg
        STATE['timings']['import_s'] = round(time.time() - t_imp, 1)
        STATE['phase'] = 'weights'                       # докачка весов Hugging Face (размер — в progress.hf_gb)

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
        STATE['phase'] = 'to_gpu'
        t = time.time()
        self.pipe.cuda()
        torch.cuda.synchronize()
        return {'weights_s': round(t_weights, 1), 'to_gpu_s': round(time.time() - t, 1)}

    def texture_only(self, image, params: dict, path: str) -> dict:
        """Контроль (Codex, директор 19.11): `Trellis2TexturingPipeline` красит ГОТОВУЮ форму (`<job>.mesh.glb`) по фото — лечит ли узор своя же покраска TRELLIS.2, без новой формы."""
        import torch
        import trimesh
        from trellis2.pipelines import Trellis2TexturingPipeline
        torch.cuda.reset_peak_memory_stats()
        stage = {}
        t = time.time()
        if getattr(self, 'tex_pipe', None) is None:
            self.tex_pipe = Trellis2TexturingPipeline.from_pretrained(os.environ.get('TRELLIS_MODEL', 'microsoft/TRELLIS.2-4B'), config_file='texturing_pipeline.json')
            self.tex_pipe.cuda()
        stage['load_texturing'] = round(time.time() - t, 2)
        t = time.time()
        mesh = trimesh.load(os.path.join(JOBS_DIR, params['job_id'] + '.mesh.glb'), force='mesh')
        out = self.tex_pipe.run(mesh, image, seed=int(params.get('seed', 42)), resolution=1024, texture_size=int(params.get('texture_size', 2048)))
        torch.cuda.synchronize()
        stage['run'] = round(time.time() - t, 2)
        out.export(path, extension_webp=bool(int(os.environ.get('EXPORT_WEBP', '0'))))
        return {'mode': 'texture_only', 'stage_s': stage, 'peak_vram_gb': round(torch.cuda.max_memory_allocated() / 2 ** 30, 2), 'mesh_tris': int(len(mesh.faces))}

    def generate(self, image, params: dict, path: str) -> dict:
        import o_voxel
        import torch
        if params.get('texture_mesh'):
            return self.texture_only(image, params, path)
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
        STATE['phase'] = 'weights'
        t = time.time()
        fw = fetch_weights.ensure()                  # веса вшиты в образ — пусто; иначе докачка (холодный старт)
        t_w = time.time() - t
        STATE['phase'] = 'warmup_gen'
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


class Pixal3DBackend:
    """Pixal3D (Tencent ARC, MIT; дообучение TRELLIS.2 с попиксельной проекцией признаков, `inference.py` апстрима): образ лежит поверх образа TRELLIS.2 (`Dockerfile.pixal3d`).
    Порядок как в апстриме: `preprocess_image` (вход — наша RGBA-вырезка, фон не удаляем: BiRefNet заменён заглушкой) → камера по картинке (MoGe-2) → `pipeline.run(camera_params=…)` →
    `to_glb` + поворот в Y-up. DINOv3 берётся ИЗ ОФИЦИАЛЬНОГО (закрытого) репозитория facebook/…, зеркало camenduru из апстрима заменено sed-ом при сборке образа."""
    name = 'pixal3d'

    def load(self) -> dict:
        os.environ.setdefault('PYTORCH_CUDA_ALLOC_CONF', 'expandable_segments:True')
        os.environ.setdefault('OPENCV_IO_ENABLE_OPENEXR', '1')
        sys.path.insert(0, os.environ.get('PIXAL3D_DIR', '/opt/Pixal3D'))
        STATE['phase'] = 'importing'
        t_imp = time.time()
        import torch
        import inference as INF                                   # апстрим: сборка пайплайна, камера, константы
        from pixal3d.pipelines import rembg
        STATE['timings']['import_s'] = round(time.time() - t_imp, 1)

        class NoRembg:                                            # вход — RGBA с настоящей альфой; вырезка фона не нужна
            def __init__(self, **_kw):
                pass

            def to(self, *_a):
                return self

            def cpu(self):
                return self

            def __call__(self, *_a, **_k):
                raise RuntimeError('вырезка фона отключена: вход должен быть RGBA с настоящей альфой')
        rembg.BiRefNet = NoRembg
        self.INF = INF
        STATE['phase'] = 'weights'
        t = time.time()
        # px1 (19.11, 4090 24 ГБ): с low_vram=False всё лежит на карте (20 ГБ после прогрева) и первое же задание падает `CUDA out of memory`.
        # Режим low_vram (README Pixal3D: «для ≤ 24 ГБ») грузит модели на карту по очереди; разрешение 1024_cascade у нас и так
        low = os.environ.get('PIXAL3D_LOW_VRAM', '1') != '0'
        self.pipe = INF.init_pipeline(low_vram=low)               # веса Pixal3D + 4 экстрактора DINOv3 + NAF
        for _name in ('decode_tex_slat', 'decode_shape_slat', 'sample_tex_slat', 'sample_shape_slat'):     # перед каждой тяжёлой стадией отдаём кэш аллокатора (px2: «CUDA driver error: out of memory» в decode_tex_slat)
            _f = getattr(self.pipe, _name, None)
            if callable(_f):
                def _w(*a, _f=_f, **k):
                    torch.cuda.empty_cache()
                    return _f(*a, **k)
                setattr(self.pipe, _name, _w)
        t_w = time.time() - t
        STATE['phase'] = 'moge'
        t = time.time()
        self.moge = INF.load_moge_model(device='cuda')            # камера по картинке; маленькая, держим резидентно
        torch.cuda.synchronize()
        return {'weights_s': round(t_w, 1), 'moge_s': round(time.time() - t, 1)}

    def generate(self, image, params: dict, path: str) -> dict:
        import math
        import numpy as np
        import o_voxel
        import torch
        INF = self.INF
        torch.cuda.reset_peak_memory_stats()
        stage = {}
        seed = int(params.get('seed', 42))
        torch.cuda.empty_cache()
        t = time.time()
        pre = self.pipe.preprocess_image(image)
        tmp = os.path.join(OUT, f'_pre_{os.getpid()}_{int(time.time() * 1000)}.png')
        pre.save(tmp)
        cam = INF.get_camera_params_wild_moge(tmp, self.moge, device='cuda', mesh_scale=1.0, extend_pixel=0, image_resolution=512)
        os.remove(tmp)
        stage['preprocess_camera'] = round(time.time() - t, 2)
        t = time.time()
        torch.manual_seed(seed)
        ptype = params.get('pipeline_type') or '1024_cascade'
        samp = {'ss': {'steps': 12, 'guidance_strength': 7.5, 'guidance_rescale': 0.7, 'rescale_t': 5.0},
                'shape': {'steps': 12, 'guidance_strength': 7.5, 'guidance_rescale': 0.5, 'rescale_t': 3.0},
                'tex': {'steps': 12, 'guidance_strength': 1.0, 'guidance_rescale': 0.0, 'rescale_t': 3.0}}
        mesh_list, (_shape_slat, _tex_slat, res) = self.pipe.run(
            pre, camera_params=cam, seed=seed, sparse_structure_sampler_params=samp['ss'], shape_slat_sampler_params=samp['shape'],
            tex_slat_sampler_params=samp['tex'], preprocess_image=False, return_latent=True, pipeline_type=ptype, max_num_tokens=int(os.environ.get('PIXAL3D_MAX_TOKENS', '49152')))
        torch.cuda.synchronize()
        stage['run'] = round(time.time() - t, 2)
        peak_run = torch.cuda.max_memory_allocated() / 2 ** 30
        mesh = mesh_list[0]
        t = time.time()
        glb = o_voxel.postprocess.to_glb(
            vertices=mesh.vertices, faces=mesh.faces, attr_volume=mesh.attrs, coords=mesh.coords, attr_layout=self.pipe.pbr_attr_layout,
            grid_size=res, aabb=[[-0.5, -0.5, -0.5], [0.5, 0.5, 0.5]], decimation_target=int(params.get('decimation_target', 500000)),
            texture_size=int(params.get('texture_size', 2048)), remesh=True, remesh_band=1, remesh_project=0, use_tqdm=False)
        glb.apply_transform(np.array([[-1, 0, 0, 0], [0, 0, -1, 0], [0, -1, 0, 0], [0, 0, 0, 1]], dtype=np.float64))    # как в апстриме: Z-up → Y-up
        torch.cuda.synchronize()
        stage['to_glb'] = round(time.time() - t, 2)
        glb.export(path, extension_webp=bool(int(os.environ.get('EXPORT_WEBP', '0'))))        # PNG-текстуры: тот же вид GLB, что у остальных моделей
        return {'stage_s': stage, 'peak_vram_gb': round(max(peak_run, torch.cuda.max_memory_allocated() / 2 ** 30), 2),
                'peak_reserved_gb': round(torch.cuda.max_memory_reserved() / 2 ** 30, 2),
                'camera': {'fov_rad': round(float(cam['camera_angle_x']), 4), 'distance': round(float(cam['distance']), 3)}}


# ——— `pixal3d-tex`: КРАСКА Pixal3D ПО ГОТОВОЙ ФОРМЕ (T-20261119-05, П1.91) ———
# Геометрия ниже — чистый numpy/PIL (без видеокарты, без torch): ровно она проверяется тестами в CI (`tests_pixal_tex.py`). Видеокарта нужна только классу `PixalTexBackend`.
# Источник схемы — `texture_mesh_pixal3d` из github.com/visualbruno/ComfyUI-Trellis2 (MIT, коммит b0e84c0f, source: external:github): форма кодируется VAE формы TRELLIS.2,
# вместо сгенерированной скрытой формы стоит она, а условие краски — проекция признаков фото на сетку (`get_proj_cond_shape` из апстрима Pixal3D, TencentARC, MIT).
# Сам ComfyUI не используется: берутся методы апстрима Pixal3D (`pixal3d/pipelines`), сборка — здесь.
YAWS_DEG = (0, 90, 180, 270)
SHAPE_TOL = 1e-4                      # допуск формы: отклонение вершин от входа / диагональ габарита (float32 в GLB даёт ~1e-7)
FINE_YAW = (-10, -5, 0, 5, 10)         # тонкая доводка позы: шаги вокруг найденной (два круга → до ±20°)
FINE_PITCH = (-10, -5, 0, 5, 10)
FINE_YAW_MAX = 25                     # предел отклонения от угла, кратного 90°, и наклона, градусов
FINE_PITCH_MAX = 20
FINE_GAIN = 0.01                      # принимаем отклонение, только если IoU силуэта растёт хотя бы на столько (иначе поза «в лоб»)
FIT_N = 192                           # разрешение масок для подгонки фото к форме


class ShapeChanged(RuntimeError):
    """После краски форма отличается от входной (число треугольников или положение вершин) — результат не отдаём."""


def rot_y(deg: float):
    """Поворот вокруг вертикали Y (кадр сетки Pixal3D: Y вверх, лицом к камере +Z); кратные 90° — точные."""
    import numpy as np
    k = int(round(deg / 90.0)) if abs(deg / 90.0 - round(deg / 90.0)) < 1e-9 else None
    if k is not None:
        c, s = [(1, 0), (0, 1), (-1, 0), (0, -1)][k % 4]
    else:
        c, s = np.cos(np.radians(deg)), np.sin(np.radians(deg))
    return np.array([[c, 0.0, s], [0.0, 1.0, 0.0], [-s, 0.0, c]], dtype=np.float64)


def rot_x(deg: float):
    """Поворот вокруг горизонтальной оси X (наклон формы к камере/от неё); 0° — точная единица."""
    import numpy as np
    if deg == 0:
        return np.eye(3)
    c, s = np.cos(np.radians(deg)), np.sin(np.radians(deg))
    return np.array([[1.0, 0.0, 0.0], [0.0, c, -s], [0.0, s, c]], dtype=np.float64)


def to_cube(verts, yaw_deg: float = 0.0, pitch_deg: float = 0.0):
    """Вершины входного GLB (Y вверх) → кадр сетки Pixal3D: поворот на yaw, центр габарита в ноль, наибольшая сторона = 0,99999 (как `preprocess_mesh` апстрима, без его
    обмена осей: сетка Pixal3D — это Y вверх, лицом +Z, то есть кадр GLB; обмен осей апстрима для TRELLIS.2 даёт Z вверх, ComfyUI компенсирует его опцией «90 degrees»).
    `pitch_deg` — наклон формы вокруг X (после поворота на yaw). Возвращает (p, center, scale, R); обратное — `from_cube`."""
    import numpy as np
    v = np.asarray(verts, dtype=np.float64)
    R = rot_x(pitch_deg) @ rot_y(yaw_deg)
    vr = v @ R.T
    lo, hi = vr.min(axis=0), vr.max(axis=0)
    c = (lo + hi) / 2.0
    ext = float((hi - lo).max())
    if not ext > 0:
        raise ValueError('форма вырождена: габарит нулевой')
    s = 0.99999 / ext
    return (vr - c) * s, c, s, R


def from_cube(p, c, s, R):
    """Обратное к `to_cube`: куб → исходные координаты (кадр и масштаб входного GLB)."""
    import numpy as np
    return (np.asarray(p, dtype=np.float64) / s + c) @ R


def undo_upstream_swap(out_vertices):
    """`postprocess_mesh` апстрима в конце обменивает оси `(x, y, z) → (x, z, −y)` (Z вверх → Y вверх). Наш кадр уже Y вверх — возвращаем как было: `(x, y, z) → (x, −z, y)`."""
    import numpy as np
    o = np.asarray(out_vertices, dtype=np.float64)
    return np.stack([o[:, 0], -o[:, 2], o[:, 1]], axis=1)


def project_cube(p, fov: float, dist: float, mesh_scale: float = 1.0):
    """Куда камера Pixal3D (`ProjGrid`: камера на +Z на расстоянии `dist`, горизонтальный угол `fov`, `mesh_scale`) кладёт точки куба; координаты кадра [0, 1]².
    Вывод из `project_points_to_image_batch` и `ProjGrid.forward` апстрима: q = p / mesh_scale; глубина = dist − q_z; u = 0,5 + F·q_x / глубина; v = 0,5 − F·q_y / глубина;
    F = 0,5 / tan(fov / 2). `dist` от `get_camera_params_wild_moge` равен F: центральная плоскость куба (глубина = dist) занимает кадр ровно по ширине."""
    import numpy as np
    q = np.asarray(p, dtype=np.float64) / float(mesh_scale)
    focal = 0.5 / np.tan(float(fov) / 2.0)
    depth = float(dist) - q[:, 2]
    safe = np.where(depth > 1e-6, depth, np.nan)
    return 0.5 + focal * q[:, 0] / safe, 0.5 - focal * q[:, 1] / safe, depth


def _dilate(m):
    import numpy as np
    n0, n1 = m.shape
    pd = np.pad(m, 1)
    out = m.copy()
    for dy in range(3):
        for dx in range(3):
            out |= pd[dy:dy + n0, dx:dx + n1]
    return out


def surface_mask(u, v, faces, n: int = FIT_N, seed: int = 0):
    """Силуэт сетки на кадре n×n: вершины + случайные точки внутри треугольников (число — по площади на экране, ≈ 4 на пиксель), затем расширение на 1 пиксель (закрывает дыры)."""
    import numpy as np
    rng = np.random.default_rng(seed)
    P = np.stack([u * n, v * n], axis=1)
    f = np.asarray(faces)
    a, b, c = P[f[:, 0]], P[f[:, 1]], P[f[:, 2]]
    ok = np.isfinite(a).all(1) & np.isfinite(b).all(1) & np.isfinite(c).all(1)
    a, b, c = a[ok], b[ok], c[ok]
    area = 0.5 * np.abs((b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1]) - (b[:, 1] - a[:, 1]) * (c[:, 0] - a[:, 0]))
    cnt = np.maximum(np.ceil(area / 0.25), 1).astype(np.int64)       # ≥ 4 точек на пиксель площади: у крупных граней (малополигональная форма) дыр нет
    total = int(cnt.sum())
    if total > 3_000_000:                                               # потолок по времени и памяти: уменьшаем пропорционально (мелкие грани остаются по одной точке)
        cnt = np.maximum(1, (cnt * (3_000_000 / total)).astype(np.int64))
    idx = np.repeat(np.arange(len(a)), cnt)
    r1, r2 = rng.random(len(idx)), rng.random(len(idx))
    sq = np.sqrt(r1)
    w0, w1, w2 = 1 - sq, sq * (1 - r2), sq * r2
    S = w0[:, None] * a[idx] + w1[:, None] * b[idx] + w2[:, None] * c[idx]
    pts = np.concatenate([S, P[np.isfinite(P).all(1)]], axis=0)
    ix, iy = np.floor(pts[:, 0]).astype(np.int64), np.floor(pts[:, 1]).astype(np.int64)
    inside = (ix >= 0) & (ix < n) & (iy >= 0) & (iy < n)
    m = np.zeros((n, n), dtype=bool)
    m[iy[inside], ix[inside]] = True
    return _dilate(m)


def crop_square_rgba(img, pad: float = 1.1, max_side: int = 1024):
    """Квадратная вырезка вокруг предмета — ровно как `preprocess_image` Pixal3D (граница по альфе > 0,8, поле 1,1, вход ≤ 1024), но без заливки фона: нужна и альфа."""
    import numpy as np
    from PIL import Image
    im = img.convert('RGBA')
    ms = max(im.size)
    if ms > max_side:
        sc = max_side / ms
        im = im.resize((int(im.width * sc), int(im.height * sc)), Image.Resampling.LANCZOS)
    alpha = np.asarray(im)[:, :, 3]
    bb = np.argwhere(alpha > 0.8 * 255)
    if bb.size == 0:
        raise ValueError('на входной картинке нет предмета: альфа пустая')
    x0, y0, x1, y1 = bb[:, 1].min(), bb[:, 0].min(), bb[:, 1].max(), bb[:, 0].max()
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    size = int(max(x1 - x0, y1 - y0) * pad)
    return im.crop((cx - size // 2, cy - size // 2, cx + size // 2, cy + size // 2))


def compose_black(rgba):
    """RGBA → RGB на чёрном фоне (`rgb · alpha`), как в апстриме."""
    import numpy as np
    from PIL import Image
    a = np.asarray(rgba.convert('RGBA')).astype(np.float32) / 255.0
    return Image.fromarray((np.clip(a[:, :, :3] * a[:, :, 3:4], 0, 1) * 255).astype(np.uint8))


def photo_mask(rgba, n: int = FIT_N):
    import numpy as np
    from PIL import Image
    al = rgba.convert('RGBA').getchannel('A').resize((n, n), Image.Resampling.BILINEAR)
    return _dilate(np.asarray(al) > 127)


def _warp_mask(A, sigma: float, tx: float, ty: float):
    """Маска фото после «масштаб σ вокруг центра кадра, затем сдвиг (tx, ty)»: x_вых = 0,5 + σ·(x_вх − 0,5) + tx."""
    import numpy as np
    n = A.shape[0]
    xs = (np.arange(n) + 0.5) / n
    ix = np.floor((0.5 + (xs - 0.5 - tx) / sigma) * n).astype(np.int64)
    iy = np.floor((0.5 + (xs - 0.5 - ty) / sigma) * n).astype(np.int64)
    vx, vy = (ix >= 0) & (ix < n), (iy >= 0) & (iy < n)
    out = np.zeros((n, n), dtype=bool)
    out[np.ix_(vy, vx)] = A[np.ix_(iy[vy], ix[vx])]
    return out


def _iou(a, b) -> float:
    uni = int((a | b).sum())
    return float((a & b).sum()) / uni if uni else 0.0


def fit_similarity(A, M, max_iter: int = 120, fix_sigma: bool = False):
    """Подогнать маску фото A к силуэту формы M подобием (масштаб σ, сдвиг tx, ty) по IoU: старт — по центру тяжести и площади, затем спуск с уменьшением шага.
    `fix_sigma` — масштаб фото не трогать (σ = 1), подбирать только сдвиг. Возвращает (σ, tx, ty, IoU)."""
    import numpy as np
    n = A.shape[0]
    aA, aM = int(A.sum()), int(M.sum())
    if aA == 0 or aM == 0:
        raise ValueError('пустая маска фото или силуэта формы')

    def centroid(m):
        yy, xx = np.nonzero(m)
        return (xx.mean() + 0.5) / n, (yy.mean() + 0.5) / n
    cax, cay = centroid(A)
    cmx, cmy = centroid(M)
    sigma = 1.0 if fix_sigma else float(np.sqrt(aM / aA))
    tx, ty = cmx - (0.5 + sigma * (cax - 0.5)), cmy - (0.5 + sigma * (cay - 0.5))
    best = _iou(_warp_mask(A, sigma, tx, ty), M)
    ds, dt = 0.05, 0.02
    for _ in range(max_iter):
        improved = False
        moves = ((sigma, tx + dt, ty), (sigma, tx - dt, ty), (sigma, tx, ty + dt), (sigma, tx, ty - dt))
        if not fix_sigma:
            moves = ((sigma * (1 + ds), tx, ty), (sigma / (1 + ds), tx, ty)) + moves
        for cs, cx, cy in moves:
            sc = _iou(_warp_mask(A, cs, cx, cy), M)
            if sc > best + 1e-6:
                best, sigma, tx, ty, improved = sc, cs, cx, cy, True
        if not improved:
            ds, dt = ds / 2, dt / 2
            if dt < 0.0007:
                break
    return float(sigma), float(tx), float(ty), float(best)


def fit_photo(verts, faces, rgba, fov: float, dist: float, mesh_scale: float = 1.0, n: int = FIT_N) -> dict:
    """Поворот формы (0/90/180/270° вокруг вертикали), `mesh_scale` и сдвиг фото, при которых силуэт формы в камере Pixal3D лучше всего совпадает с вырезкой фото.
    ЗАЧЕМ. Краска читает фото по проекции сетки: форма из TRELLIS.2 обязана стоять в кадре так, как её видит камера (иначе текстура уходит в чёрный фон), а апстрим кадрирует
    фото с полем 1,1 (предмет занимает 0,909 кадра), тогда как куб формы заполнен целиком. Фото НЕ масштабируем (иначе его края срежет рамка кадра): масштаб подгоняется
    параметром `mesh_scale` самой камеры (больше — форма дальше и мельче), фото только сдвигается. Ничьи (симметричный предмет) уступают меньшему повороту.
    IoU «без подгонки» (`mesh_scale` как дан, сдвиг 0 — поведение апстрима) возвращается рядом: видно, что дала подгонка. `sigma` в ответе всегда 1,0 (масштаб фото не меняется)."""
    A = photo_mask(rgba, n)

    def evaluate(yaw, pitch, s_start, steps):
        """Для позы (yaw, pitch): подобрать mesh_scale (поиск вокруг s_start с уменьшающимся шагом) и сдвиг фото. → (IoU, mesh_scale, tx, ty, маска без подгонки)."""
        p, _c, _s, _R = to_cube(verts, yaw, pitch)
        cache: dict = {}

        def at(sc):
            k = round(sc, 5)
            if k not in cache:
                uu, vv, _dd = project_cube(p, fov, dist, k)
                cache[k] = fit_similarity(A, surface_mask(uu, vv, faces, n), fix_sigma=True)
            return cache[k]
        sb = s_start
        for step in steps:
            sb = max([sb * (1 + step * j) for j in (-2, -1, 0, 1, 2)], key=lambda c: at(c)[3])
        _sg, tx, ty, iou = at(sb)
        return iou, float(sb), tx, ty

    best = None
    by_yaw = {}
    for yaw in YAWS_DEG:
        p, _c, _s, _R = to_cube(verts, yaw)
        u, v, _d = project_cube(p, fov, dist, mesh_scale)
        M0 = surface_mask(u, v, faces, n)
        sig0 = fit_similarity(A, M0)[0]                              # грубая оценка масштаба: фото мельче силуэта в σ раз → форму отодвинуть в σ раз
        iou, sb, tx, ty = evaluate(yaw, 0.0, mesh_scale * sig0, (0.08, 0.03, 0.01))
        by_yaw[str(yaw)] = round(iou, 4)
        if best is None or iou > best['iou'] + 0.005:
            best = {'yaw_deg': yaw, 'yaw_base_deg': yaw, 'pitch_deg': 0.0, 'sigma': 1.0, 'tx': tx, 'ty': ty, 'mesh_scale': sb, 'iou': iou, 'iou_identity': _iou(A, M0), 'iou_coarse': iou}
    # тонкая доводка позы: фото снято не строго «в лоб» (форма сгенерирована по нему, но с поворотом в единицы и десятки градусов). Принимаем отклонение, только если оно даёт ≥ FINE_GAIN IoU
    cur = dict(best)
    for _round in range(2):
        for axis, offs in (('yaw', FINE_YAW), ('pitch', FINE_PITCH)):
            top = None
            for o in offs:
                if o == 0:
                    continue
                yy = cur['yaw_deg'] + (o if axis == 'yaw' else 0)
                pp = cur['pitch_deg'] + (o if axis == 'pitch' else 0)
                if abs(yy - best['yaw_base_deg']) > FINE_YAW_MAX or abs(pp) > FINE_PITCH_MAX:
                    continue
                iou, sb, tx, ty = evaluate(yy, pp, cur['mesh_scale'], (0.03, 0.01))
                if top is None or iou > top[0]:
                    top = (iou, yy, pp, sb, tx, ty)
            if top is not None and top[0] > cur['iou'] + FINE_GAIN:
                cur.update(iou=top[0], yaw_deg=top[1], pitch_deg=top[2], mesh_scale=top[3], tx=top[4], ty=top[5])
    best = cur
    best['iou_by_yaw'] = by_yaw
    return {k: (round(x, 4) if isinstance(x, float) else x) for k, x in best.items()}


def warp_photo(rgba, sigma: float, tx: float, ty: float, size: int = 1024):
    """Фото (RGBA) → RGB size×size на чёрном: содержимое масштабируется на σ вокруг центра кадра и сдвигается на (tx, ty) долей кадра (то же преобразование, что `_warp_mask`)."""
    from PIL import Image
    src = compose_black(rgba)
    w, h = src.size
    a = w / (sigma * size)
    e = h / (sigma * size)
    c = w * (0.5 - (0.5 + tx) / sigma)
    f = h * (0.5 - (0.5 + ty) / sigma)
    return src.transform((size, size), Image.Transform.AFFINE, (a, 0, c, 0, e, f), resample=Image.Resampling.BICUBIC, fillcolor=(0, 0, 0))


def hausdorff_vertices(a, b, max_n: int = 20000) -> float:
    """Симметричное расстояние Хаусдорфа между облаками вершин (по ближайшей вершине; не больше max_n точек с каждой стороны, равномерно по индексу). scipy — если есть."""
    import numpy as np
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    if len(a) > max_n:
        a = a[np.linspace(0, len(a) - 1, max_n).astype(np.int64)]
    if len(b) > max_n:
        b = b[np.linspace(0, len(b) - 1, max_n).astype(np.int64)]
    try:
        from scipy.spatial import cKDTree
        return float(max(cKDTree(b).query(a)[0].max(), cKDTree(a).query(b)[0].max()))
    except ImportError:
        pass

    def one_way(x, y):
        worst = 0.0
        for i in range(0, len(x), 512):
            d2 = ((x[i:i + 512, None, :] - y[None, :, :]) ** 2).sum(-1)
            worst = max(worst, float(np.sqrt(d2.min(axis=1).max())))
        return worst
    return max(one_way(a, b), one_way(b, a))


def check_shape_unchanged(v_in, f_in, v_out, f_out, tol: float = SHAPE_TOL) -> dict:
    """Форма после краски = форма на входе: ТО ЖЕ число треугольников и расстояние Хаусдорфа к входу ≈ 0 (в долях диагонали габарита). Нарушение — `ShapeChanged`.
    Вершины в том же порядке и грани те же (путь с готовой развёрткой) — проверяем поточечно (верхняя граница Хаусдорфа); иначе (развёртка расщепила вершины) — по ближайшим вершинам."""
    import numpy as np
    v_in = np.asarray(v_in, dtype=np.float64)
    v_out = np.asarray(v_out, dtype=np.float64)
    diag = float(np.linalg.norm(v_in.max(axis=0) - v_in.min(axis=0)))
    if not diag > 0:
        raise ShapeChanged('габарит входной формы нулевой')
    res = {'tris_in': int(len(f_in)), 'tris_out': int(len(f_out)), 'verts_in': int(len(v_in)), 'verts_out': int(len(v_out)), 'tol_rel': tol}
    if len(f_in) != len(f_out):
        raise ShapeChanged(f'число треугольников изменилось: {len(f_in)} → {len(f_out)}')
    same_topology = len(v_in) == len(v_out) and np.array_equal(np.asarray(f_in), np.asarray(f_out))
    if same_topology:
        dev = float(np.abs(v_out - v_in).max()) / diag
        res.update(mode='pointwise', hausdorff_rel=round(dev, 9), same_faces=True)
    else:
        hd = hausdorff_vertices(v_in, v_out) / diag
        res.update(mode='nearest_vertex', hausdorff_rel=round(hd, 9), same_faces=False)
    if res['hausdorff_rel'] > tol:
        raise ShapeChanged(f'форма сдвинулась: Хаусдорф {res["hausdorff_rel"]:.2e} диагонали габарита (допуск {tol:.0e})')
    return res


def texture_on_shape(pipe, mesh, image, cam: dict, params: dict, hooks: dict | None = None) -> tuple:
    """Покрасить ГОТОВУЮ форму `mesh` (trimesh, кадр GLB: Y вверх) по фото `image` (RGBA, настоящая альфа); `pipe` — методы апстрима Pixal3D (см. `PixalTexBackend.load`),
    `cam` — камера по картинке (`camera_angle_x`, `distance`, `mesh_scale`). Возвращает (trimesh с текстурой в исходном кадре и масштабе, замеры). Форма не меняется:
    вершины возвращаются из куба обратным преобразованием, затем `check_shape_unchanged` (иначе `ShapeChanged`)."""
    import numpy as np
    import trimesh
    hk = {'seed': lambda s: None, 'sync': lambda: None, 'free': lambda: None, 'mem': lambda name: None, 'enc_mesh': lambda m: None, **(hooks or {})}
    stage: dict = {}
    t = time.time()

    def lap(name: str) -> None:
        """Конец стадии: синхронизация видеокарты → время → освобождение памяти между стадиями (`free`: gc + empty_cache) → замер памяти (`mem`)."""
        hk['sync']()
        nonlocal t
        stage[name] = round(time.time() - t, 2)
        hk['free']()
        hk['mem'](name)
        t = time.time()

    align = params.get('align') or 'fit'
    if align not in ('fit', 'official'):
        raise ValueError(f'align: «fit» или «official», получено {align!r}')
    resolution = int(params.get('tex_resolution') or 1024)
    if resolution % 16:
        raise ValueError('разрешение краски кратно 16')
    texture_size = int(params.get('texture_size', 2048))
    mscale = float(cam.get('mesh_scale', 1.0))
    verts = np.asarray(mesh.vertices, dtype=np.float64)
    faces = np.asarray(mesh.faces, dtype=np.int64)
    uv = getattr(getattr(mesh, 'visual', None), 'uv', None)
    has_uv = uv is not None and len(uv) == len(verts)

    rgba = crop_square_rgba(image)
    fit = fit_photo(verts, faces, rgba, float(cam['camera_angle_x']), float(cam['distance']), mscale)
    lap('fit')
    cond_img = warp_photo(rgba, fit['sigma'], fit['tx'], fit['ty'], 1024) if align == 'fit' else compose_black(rgba)
    cam_scale = float(fit['mesh_scale']) if align == 'fit' else mscale                 # «fit»: форма подогнана к фото масштабом камеры; «official» — камера как дала MoGe
    p, c, s, R = to_cube(verts, fit['yaw_deg'], fit['pitch_deg']) if align == 'fit' else to_cube(verts, fit['yaw_base_deg'])          # «official» — только поворот, кратный 90°, как в апстриме
    m_in = trimesh.Trimesh(vertices=p, faces=faces, process=False)
    if has_uv:
        m_in.visual = trimesh.visual.TextureVisuals(uv=np.asarray(uv, dtype=np.float64).copy())
    hk['seed'](int(params.get('seed', 42)))
    enc_mesh, smooth_info = m_in, {'iterations': 0}
    smooth_n = int(params.get('shape_smooth') or 0)
    if smooth_n > 0:                       # рычаг «двойного узора»: ЛАТЕНТ формы (его краска читает как условие) считаем по сглаженной копии, а запекаем краску на настоящую форму (она не меняется)
        sm = trimesh.Trimesh(vertices=p.copy(), faces=faces, process=False)
        trimesh.smoothing.filter_taubin(sm, lamb=0.5, nu=-0.53, iterations=smooth_n)
        disp = float(np.linalg.norm(np.asarray(sm.vertices) - p, axis=1).max())
        enc_mesh = sm
        smooth_info = {'iterations': smooth_n, 'max_disp_rel': round(disp / float(np.linalg.norm(p.max(0) - p.min(0))), 5)}
    hk['enc_mesh'](enc_mesh)                 # для диагностики при нехватке памяти: тот же вход в кодировщик, но в 512 (`PixalTexBackend.on_error`)
    shape_slat = pipe.encode_shape_slat(enc_mesh, resolution)
    lap('encode_shape')
    cond = pipe.get_proj_cond_shape(pipe.image_cond_model_tex_1024, [cond_img], shape_slat.coords, camera_angle_x=float(cam['camera_angle_x']),
                                    distance=float(cam['distance']), mesh_scale=cam_scale, grid_resolution_override=resolution // 16)
    lap('cond')
    tex_slat = pipe.sample_tex_slat(cond, pipe.models['tex_slat_flow_model_1024'], shape_slat, params.get('sampler') or {})
    del cond
    lap('sample_tex')
    pbr = pipe.decode_tex_slat_plain(tex_slat)
    del shape_slat, tex_slat
    lap('decode_tex')
    out = pipe.postprocess_mesh(m_in, pbr, resolution, texture_size)
    del pbr
    lap('bake')
    v_back = from_cube(undo_upstream_swap(out.vertices), c, s, R).astype(np.float32).astype(np.float64)      # через float32, как лежит в GLB
    final = trimesh.Trimesh(vertices=v_back, faces=np.asarray(out.faces), visual=out.visual, process=False)
    shape = check_shape_unchanged(verts.astype(np.float32).astype(np.float64), faces, v_back, np.asarray(out.faces))
    lap('check_shape')
    return final, {'align': align, 'fit': fit, 'shape': shape, 'has_uv': bool(has_uv), 'stage_s': stage,
                   'smooth': smooth_info, 'cond_canvas': list(cond_img.size), 'cond_mesh_scale': round(cam_scale, 5), 'photo_crop': list(rgba.size), 'mesh_tris': int(len(faces)), 'tex_resolution': resolution}


FATAL_CUDA_MARKERS = ('device not ready', 'illegal memory access', 'internal assert', 'device-side assert', 'unspecified launch failure', 'cuda driver error',
                      'misaligned address', 'uncorrectable ecc', 'launch failure', 'cuda error', 'cudaerror', 'cublas_status', 'cudnn_status')


def classify_cuda_error(e: BaseException) -> str:
    """`oom` — обычная нехватка видеопамяти (`torch.cuda.OutOfMemoryError` или «out of memory» в тексте): процесс цел, память можно освободить и идти дальше;
    `fatal` — сбой драйвера/ядра/аллокатора («device not ready», «illegal memory access», «INTERNAL ASSERT» и т. п.): состояние CUDA в процессе испорчено (первая ошибка
    ломает аллокатор, вторая — её следствие, проба a0346 19.11), дальше задания не берём; `other` — остальное (ошибка входа, форма сдвинулась и т. д.)."""
    text = f'{type(e).__name__}: {e}'.lower()
    if type(e).__name__ == 'OutOfMemoryError' or 'out of memory' in text:
        return 'oom'
    if any(m in text for m in FATAL_CUDA_MARKERS):
        return 'fatal'
    return 'other'


def gpu_mem(reset_peak: bool = False) -> dict:
    """Память видеокарты: PyTorch (выделено/зарезервировано/пик с прошлого замера) и драйвер (`mem_get_info` — свободно/всего), ГБ. Без CUDA или при сбое — пусто, не исключение."""
    try:
        import torch
        g = 2 ** 30
        free, total = torch.cuda.mem_get_info()
        d = {'allocated_gb': round(torch.cuda.memory_allocated() / g, 3), 'reserved_gb': round(torch.cuda.memory_reserved() / g, 3),
             'peak_allocated_gb': round(torch.cuda.max_memory_allocated() / g, 3), 'peak_reserved_gb': round(torch.cuda.max_memory_reserved() / g, 3),
             'free_gb': round(free / g, 3), 'total_gb': round(total / g, 3)}
        if reset_peak:
            torch.cuda.reset_peak_memory_stats()
        return d
    except Exception:  # noqa: BLE001 — диагностика не должна ронять задание (после фатальной ошибки CUDA сама может не отвечать)
        return {}


def _status_gb(key: str) -> float | None:
    """Строка `/proc/self/status` (VmRSS — сейчас, VmHWM — пик) в ГБ; нет файла/строки — None."""
    try:
        for line in open('/proc/self/status'):
            if line.startswith(key + ':'):
                return round(int(line.split()[1]) / 2 ** 20, 3)      # кБ → ГиБ
    except (OSError, ValueError, IndexError):
        pass
    return None


def reset_rss_peak() -> bool:
    """Сбросить пик RSS процесса (VmHWM): «5» в /proc/self/clear_refs. Не вышло (нет прав/файла) — False, пик тогда считается с начала жизни процесса (задание это пишет: rss_peak_reset=False)."""
    try:
        with open('/proc/self/clear_refs', 'w') as f:
            f.write('5')
        return True
    except OSError:
        return False


def mem_snapshot(reset_peak: bool = False) -> dict:
    """Память на стадии: видеокарта (`gpu_mem`) + обычная память процесса (`rss_gb` — VmRSS ребёнка) и группы контейнера (`cgroup_gb` — current). Причина: issue #66 — процесс MV-Adapter
    убивали по обычной памяти (~31 ГБ) при свободной видеопамяти; по одной видеопамяти такое не увидеть."""
    d = gpu_mem(reset_peak)
    d['rss_gb'] = _status_gb('VmRSS')
    d['cgroup_gb'] = (cgroup_gb() or {}).get('current')
    return d


def job_mem_metrics(trace: dict, rss_reset: bool) -> dict:
    """Итог задания по обычной памяти: `peak_rss_gb` (VmHWM с начала задания), `peak_cgroup_gb` (максимум current группы по замерам стадий — между замерами пик может быть выше), `rss_peak_reset`."""
    cg = [v.get('cgroup_gb') for v in trace.values() if v.get('cgroup_gb') is not None]
    return {'peak_rss_gb': _status_gb('VmHWM'), 'peak_cgroup_gb': max(cg) if cg else None, 'rss_peak_reset': rss_reset}


def free_gpu() -> None:
    """Между стадиями: синхронизация → сборка мусора (отпускает тензоры, на которые держат ссылки циклы и кадры исключений) → возврат кэша аллокатора драйверу."""
    import gc
    try:
        import torch
        torch.cuda.synchronize()
        gc.collect()
        torch.cuda.empty_cache()
    except Exception:  # noqa: BLE001
        gc.collect()


def apply_alloc_conf(torch) -> dict:
    """Конфиг аллокатора CUDA для `pixal3d-tex` — ПОСЛЕ `import inference` и ДО первого выделения памяти на видеокарте. Апстрим Pixal3D в `inference.py:11` БЕЗУСЛОВНО пишет
    `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` при импорте, а `setdefault` у нас это не перебивал (a0346: «!handles_.at(i) INTERNAL ASSERT» в `CUDACachingAllocator.cpp:400` —
    путь расширяемых сегментов). Читает torch 2.6 так: единственный экземпляр `CUDAAllocatorConfig::instance()` создаётся ПРИ ПЕРВОМ обращении (статическая переменная функции,
    `getenv` в этот момент — `c10/cuda/CUDAAllocatorConfig.h:80-88`), НЕ при `import torch`; но и позже настройку можно сменить на ходу: `torch.cuda.memory._set_allocator_settings`
    (`torch/cuda/memory.py:921` → `Module.cpp:446` → `CUDAAllocatorConfig.cpp:412`) заново разбирает строку, `expandable_segments` читается при КАЖДОМ выделении (`CUDACachingAllocator.cpp:2542,2574,2719`).
    Поэтому и env, и вызов; действующее значение читаем из `torch.cuda.memory._snapshot()['allocator_settings']` (`memory_snapshot.cpp:371-375`) и отказываем, если оно не то."""
    want = os.environ.get('PIXTEX_ALLOC_CONF', 'expandable_segments:False')
    os.environ['PYTORCH_CUDA_ALLOC_CONF'] = want
    torch.cuda.memory._set_allocator_settings(want)
    eff = None
    try:
        eff = torch.cuda.memory._snapshot().get('allocator_settings') or {}
    except Exception:  # noqa: BLE001
        pass
    res = {'wanted': want, 'env': os.environ.get('PYTORCH_CUDA_ALLOC_CONF'), 'effective': eff}
    for item in want.split(','):
        k, _, v = item.partition(':')
        if k.strip() == 'expandable_segments' and eff and eff.get('expandable_segments') != (v.strip() == 'True'):
            raise RuntimeError(f'аллокатор CUDA не принял {item!r}: действует {eff.get("expandable_segments")}')
    return res


class PixalTexBackend:
    """`pixal3d-tex`: форма TRELLIS.2 (готовый GLB, `<job>.mesh.glb`) + краска Pixal3D по одному фото. Грузим ТОЛЬКО то, что нужно покраске: поток краски 1024 и декодер краски из
    `TencentARC/Pixal3D`, кодировщик формы из `microsoft/TRELLIS.2-4B` (у Pixal3D его нет), экстрактор DINOv3 + NAF стадии tex_1024 и MoGe-2 (камера). Потоки формы и структуры не грузятся
    (минус ≈ 15 ГБ скачивания и видеопамяти против `pixal3d`). Методы пайплайна — апстрима: `get_proj_cond_shape`, `sample_tex_slat` (Pixal3D) и `encode_shape_slat`,
    `decode_tex_slat` без направляющих, `postprocess_mesh` (его Trellis2TexturingPipeline). Образ — тот же, что у `pixal3d` (`Dockerfile.pixal3d`), код едет через `command`."""
    name = 'pixal3d-tex'

    low_vram = True                 # PIXTEX_LOW_VRAM (по умолчанию 1): модели на карту по очереди, не все сразу (a0346: 7,5 из 24 ГБ после прогрева и срыв на пике кодировщика формы)
    inference_mode = True           # PIXTEX_INFERENCE_MODE (по умолчанию 1): torch.inference_mode вместо no_grad
    probe512 = False                # PIXTEX_OOM_PROBE512 (по умолчанию 0): при обычной нехватке памяти — один диагностический проход кодировщика формы в 512
    pipe = None
    _enc_mesh = None                # вход кодировщика (куб) последнего задания — для диагностики 512
    _trace: dict = {}               # память по стадиям последнего задания

    def load(self) -> dict:
        os.environ.setdefault('OPENCV_IO_ENABLE_OPENEXR', '1')
        os.environ['PYTORCH_CUDA_ALLOC_CONF'] = os.environ.get('PIXTEX_ALLOC_CONF', 'expandable_segments:False')      # до импорта torch; апстрим перепишет при `import inference` — ниже вернём
        self.low_vram = os.environ.get('PIXTEX_LOW_VRAM', '1') != '0'
        self.inference_mode = os.environ.get('PIXTEX_INFERENCE_MODE', '1') != '0'
        self.probe512 = os.environ.get('PIXTEX_OOM_PROBE512', '0') == '1'
        sys.path.insert(0, os.environ.get('PIXAL3D_DIR', '/opt/Pixal3D'))
        STATE['phase'] = 'importing'
        t_imp = time.time()
        import torch
        import inference as INF                                   # inference.py:11 пишет expandable_segments:True БЕЗУСЛОВНО
        alloc = apply_alloc_conf(torch)                           # …поэтому сразу после импорта и до первого выделения на карте ставим своё
        STATE['config'] = {'alloc': alloc, 'low_vram': self.low_vram, 'inference_mode': self.inference_mode, 'oom_probe512': self.probe512,
                           'debug_env': {k: os.environ.get(k) for k in ('CUDA_LAUNCH_BLOCKING', 'TORCH_SHOW_CPP_STACKTRACES')}}
        print('[pixtex] конфиг:', json.dumps(STATE['config'], ensure_ascii=False), flush=True)
        import o_voxel
        from pixal3d import models as PM
        from pixal3d.modules.sparse import SparseTensor
        from pixal3d.pipelines import Pixal3DImageTo3DPipeline, rembg
        from pixal3d.pipelines.trellis2_texturing import Trellis2TexturingPipeline as T2T
        STATE['timings']['import_s'] = round(time.time() - t_imp, 1)

        class NoRembg:                                            # вход — RGBA с настоящей альфой; вырезка фона не нужна
            def __init__(self, **_kw):
                pass

            def to(self, *_a):
                return self

            def cpu(self):
                return self

            def __call__(self, *_a, **_k):
                raise RuntimeError('вырезка фона отключена: вход должен быть RGBA с настоящей альфой')
        rembg.BiRefNet = NoRembg

        class TexOnly(Pixal3DImageTo3DPipeline):
            model_names_to_load = ['tex_slat_flow_model_1024', 'tex_slat_decoder']       # Pipeline.from_pretrained качает и грузит только их
            decode_tex_slat_plain = T2T.decode_tex_slat                                  # без guide_subs (форма не генерируется); при low_vram сам переносит декодер на карту и назад (trellis2_texturing.py:280-284)
            postprocess_mesh = T2T.postprocess_mesh                                      # растеризация по развёртке, запекание, inpaint; моделей не трогает (только тензоры карты)
            diag: dict = {}

            def encode_shape_slat(self, mesh, resolution: int = 1024):
                """То же, что `Trellis2TexturingPipeline.encode_shape_slat` (trellis2_texturing.py:183-222: o_voxel.mesh_to_flexible_dual_grid → SparseTensor → кодировщик; при low_vram кодировщик
                сам идёт на карту и назад), плюс замеры ДО кодировщика: грани, вершины, число активных вокселей и `intersected`, память карты (`self.diag`). Апстрим обучали на ≤ 1 млн вокселей
                (flexi_dual_grid.py:67) — больше значит риск пика."""
                d = self.diag = {'resolution': int(resolution), 'verts': int(len(mesh.vertices)), 'faces': int(len(mesh.faces))}
                vertices = torch.from_numpy(mesh.vertices).float()
                faces = torch.from_numpy(mesh.faces).long()
                voxel_indices, dual_vertices, intersected = o_voxel.convert.mesh_to_flexible_dual_grid(
                    vertices.cpu(), faces.cpu(), grid_size=resolution, aabb=[[-0.5, -0.5, -0.5], [0.5, 0.5, 0.5]],
                    face_weight=1.0, boundary_weight=0.2, regularization_weight=1e-2, timing=True)
                d['active_voxels'] = int(voxel_indices.shape[0])
                d['over_1m_voxels'] = d['active_voxels'] > 1_000_000
                try:
                    d['intersected'] = int(intersected.reshape(len(intersected), -1).any(-1).sum())
                except Exception:  # noqa: BLE001
                    d['intersected'] = None
                vertices = SparseTensor(feats=dual_vertices * resolution - voxel_indices,
                                        coords=torch.cat([torch.zeros_like(voxel_indices[:, 0:1]), voxel_indices], dim=-1)).to(self.device)
                intersected = vertices.replace(intersected).to(self.device)
                d['mem_before_encoder'] = gpu_mem(reset_peak=True)
                print('[pixtex] до кодировщика:', json.dumps(d, ensure_ascii=False), flush=True)
                if self.low_vram:
                    self.models['shape_slat_encoder'].to(self.device)
                shape_slat = self.models['shape_slat_encoder'](vertices, intersected)
                if self.low_vram:
                    self.models['shape_slat_encoder'].cpu()
                d['mem_after_encoder'] = gpu_mem()
                return shape_slat
        self.INF = INF
        STATE['phase'] = 'weights'
        t = time.time()
        pipe = TexOnly.from_pretrained(INF.MODEL_PATH)
        pipe.models['shape_slat_encoder'] = PM.from_pretrained('microsoft/TRELLIS.2-4B/ckpts/shape_enc_next_dc_f16c32_fp16')
        pipe.models['shape_slat_encoder'].eval()
        pipe.low_vram = self.low_vram
        pipe.image_cond_model_tex_1024 = INF.build_image_cond_model(INF.IMAGE_COND_CONFIGS['tex_1024'])
        t_w = time.time() - t
        STATE['phase'] = 'to_gpu'
        t = time.time()
        if self.low_vram:
            # как `inference.init_pipeline(low_vram=True)` (inference.py:84-95): модели остаются на CPU, NAF докачивается на CPU, пайплайн знает карту (`_device`); каждая стадия сама переносит свою модель
            # на карту и назад: кодировщик формы — trellis2_texturing.py:217-221, DINOv3+NAF (одним `image_cond_model.to/.cpu`, он двигает и NAF) — pixal3d_image_to_3d.py:255-256 и 287-288,
            # поток краски — 533/544, декодер — trellis2_texturing.py:280-284
            pipe.image_cond_model_tex_1024._load_naf()
            pipe._device = torch.device('cuda')
        else:
            pipe.cuda()
            pipe.image_cond_model_tex_1024.cuda()
            pipe.image_cond_model_tex_1024._load_naf()
        self.pipe = pipe
        t_gpu = time.time() - t
        STATE['phase'] = 'moge'
        t = time.time()
        self.moge = INF.load_moge_model(device='cpu' if self.low_vram else 'cuda')           # при low_vram — на карту только на время расчёта камеры
        free_gpu()
        STATE['config']['mem_after_warm'] = gpu_mem()
        return {'weights_s': round(t_w, 1), 'to_gpu_s': round(t_gpu, 1), 'moge_s': round(time.time() - t, 1), 'mem_after_warm': STATE['config']['mem_after_warm']}

    def generate(self, image, params: dict, path: str) -> dict:
        if not params.get('texture_mesh'):
            raise ValueError('pixal3d-tex красит готовую форму: нужен --texture-mesh <clean.glb>')
        import torch
        import trimesh
        self._enc_mesh = None
        self.pipe.diag = {}
        trace: dict = {}                                                   # память карты после каждой стадии (пик — с прошлого замера); пишется и при падении (`on_error`)
        self._trace = trace

        rss_reset = reset_rss_peak()                                       # пик обычной памяти — с начала ЭТОГО задания (T-20261119-06/6/1)

        def mem(name: str) -> None:
            trace[name] = mem_snapshot(reset_peak=True)
        mem('start')
        t = time.time()
        sc = trimesh.load(os.path.join(JOBS_DIR, params['job_id'] + '.mesh.glb'), force='scene')
        parts = sc.dump()                                                  # геометрии с применёнными преобразованиями узлов
        if not parts:
            raise ValueError('в GLB формы нет мешей')
        mesh = parts[0] if len(parts) == 1 else trimesh.util.concatenate(parts)      # несколько кусков: сливаем, развёртка уйдёт в cumesh
        load_s = round(time.time() - t, 2)
        t = time.time()
        rgba = crop_square_rgba(image)
        tmp = os.path.join(OUT, f'_pre_{os.getpid()}_{int(time.time() * 1000)}.png')
        compose_black(rgba).save(tmp)
        ctx = torch.inference_mode if self.inference_mode else torch.no_grad
        try:
            if self.low_vram:
                self.moge.to('cuda')                                       # MoGe на карте только на время камеры
            with ctx():
                cam = self.INF.get_camera_params_wild_moge(tmp, self.moge, device='cuda', mesh_scale=1.0, extend_pixel=0, image_resolution=512)
        finally:
            if self.low_vram:
                self.moge.to('cpu')
            os.remove(tmp)
        free_gpu()
        mem('camera')
        camera_s = round(time.time() - t, 2)
        samp = {'steps': 12, 'guidance_strength': float(params.get('tex_guidance') or 1.0), 'guidance_rescale': 0.0, 'rescale_t': 3.0}
        hooks = {'seed': torch.manual_seed, 'sync': torch.cuda.synchronize, 'free': free_gpu, 'mem': mem, 'enc_mesh': lambda m_: setattr(self, '_enc_mesh', m_)}
        with ctx():
            final, m = texture_on_shape(self.pipe, mesh, image, cam, {**params, 'sampler': samp}, hooks)
        final.export(path, extension_webp=bool(int(os.environ.get('EXPORT_WEBP', '0'))))
        m['stage_s'].update({'load_shape': load_s, 'camera': camera_s})
        m.update({'mode': 'pixal3d_tex', 'peak_vram_gb': max([v.get('peak_allocated_gb', 0.0) for v in trace.values()] or [0.0]),
                  'peak_reserved_gb': max([v.get('peak_reserved_gb', 0.0) for v in trace.values()] or [0.0]), 'mem': trace, 'encoder': dict(self.pipe.diag),
                  'config': dict(STATE.get('config') or {}), **job_mem_metrics(trace, rss_reset),
                  'camera_params': {'fov_rad': round(float(cam['camera_angle_x']), 4), 'distance': round(float(cam['distance']), 3)}})
        return m

    def on_error(self, e: BaseException) -> dict:
        """Разбор упавшего задания (зовёт `run_job`): тип ошибки (`classify_cuda_error`), память по стадиям до падения, замеры кодировщика, действующий конфиг аллокатора. `fatal` — воркер помечается
        сломанным (`mark_broken`: /health ok=false, новые задания отказ), драйвер гасит группу сразу. Обычная нехватка памяти (`oom`) — освободить память и, при PIXTEX_OOM_PROBE512=1, один
        диагностический проход кодировщика формы в 512 (только он, без краски) — ответ «лезет ли форма в карту при меньшем разрешении»."""
        import traceback as tb
        kind = classify_cuda_error(e)
        tb.clear_frames(e.__traceback__)                      # кадры исключения держат тензоры — без этого освободить память нельзя
        diag = {'kind': kind, 'fatal': kind == 'fatal', 'mem': mem_snapshot(), 'peak_rss_gb': _status_gb('VmHWM'), 'stage_mem': dict(self._trace), 'encoder': dict(getattr(self.pipe, 'diag', {}) or {}),
                'config': STATE.get('config')}
        if kind == 'oom':
            free_gpu()
            diag['mem_after_free'] = gpu_mem()
            if self.probe512 and self._enc_mesh is not None:
                diag['probe512'] = self._probe512()
                if diag['probe512'].get('fatal'):
                    diag['fatal'] = True
        return diag

    def _probe512(self) -> dict:
        """Диагностика: кодировщик формы на той же форме, но в сетке 512 (в 8 раз меньше вокселей, чем в 1024), с теми же замерами. Краска не считается."""
        import torch
        t = time.time()
        r: dict = {}
        try:
            with (torch.inference_mode if self.inference_mode else torch.no_grad)():
                out = self.pipe.encode_shape_slat(self._enc_mesh, 512)
            r = {'ok': True, 'tokens': int(out.coords.shape[0]), **dict(self.pipe.diag)}
            del out
        except Exception as e2:  # noqa: BLE001
            r = {'ok': False, 'error': f'{type(e2).__name__}: {str(e2)[:300]}', 'fatal': classify_cuda_error(e2) == 'fatal', **dict(getattr(self.pipe, 'diag', {}) or {})}
        free_gpu()
        r.update(seconds=round(time.time() - t, 2), mem_after=gpu_mem())
        return r


class LocalMeshBackend:
    """LocalMesh Engine (Apache-2.0, github.com/Quentincls/localmesh-engine): TRELLIS.2 в FP8 + проекция самих пикселей фото на текстуру, режим ОДНОГО фото.
    Образ — отдельный (`Dockerfile.localmesh`: py3.12, torch 2.8/cu128). Веса докачиваются на старте в `$HF_HOME/lm/models`: открытое — из `Qtn-Cls/LocalMeshEngine` (без multivue),
    DINOv3 — из ОФИЦИАЛЬНОГО закрытого репозитория facebook/… по HF_TOKEN. Вырезка фона (BiRefNet_HR, `trust_remote_code`) отключена: движок берёт нашу настоящую альфу,
    а попытка загрузить BiRefNet падает с понятной ошибкой — чужой код с Hub в рантайме не исполняется. Выход: `model_<seed>.glb` (с проекцией) → `<id>.glb`, `.ai.glb` → `<id>.ai.glb`."""
    name = 'localmesh'

    def load(self) -> dict:
        os.environ.setdefault('PYTORCH_CUDA_ALLOC_CONF', 'expandable_segments:True')
        root = os.path.join(os.environ.get('HF_HOME', '/data/hf'), 'lm')
        models = os.path.join(root, 'models')
        os.environ['LOCALMESH_ROOT'] = root
        os.makedirs(models, exist_ok=True)
        STATE['phase'] = 'weights'                       # докачка весов (размер — в progress.hf_gb: корень весов лежит внутри HF_HOME)
        t = time.time()
        from huggingface_hub import snapshot_download
        tok = os.environ.get('HF_TOKEN') or None
        snapshot_download('Qtn-Cls/LocalMeshEngine', local_dir=models, allow_patterns=['TRELLIS.2-4B/*', 'microsoft/*'], token=tok)
        snapshot_download('facebook/dinov3-vitl16-pretrain-lvd1689m', local_dir=os.path.join(models, 'facebook', 'dinov3-vitl16-pretrain-lvd1689m'), token=tok)
        t_dl = time.time() - t
        STATE['phase'] = 'importing'
        t = time.time()
        import torch
        from localmesh_engine import matting

        def _no_matte(*_a, **_k):                        # BiRefNet_HR (trust_remote_code) не грузим: вход — RGBA с настоящей альфой
            raise RuntimeError('вырезка фона отключена: вход должен быть RGBA с настоящей альфой (BiRefNet из Hub не исполняем)')
        matting.Matter.load = _no_matte
        from localmesh_engine import Engine
        STATE['timings']['import_s'] = round(time.time() - t, 1)
        STATE['phase'] = 'to_gpu'
        t = time.time()
        self.engine = Engine()
        self.engine.load()
        # заглушки plyfile/nvdiffrast ставит `Engine.load()` (config.bootstrap) — o_voxel.convert можно трогать только ПОСЛЕ него (иначе «No module named plyfile»: lm1, lm2); модуль fdg_vae с этим импортом грузится лениво, при первом задании
        import o_voxel.convert as ovc
        if not hasattr(ovc, 'tiled_flexible_dual_grid_to_mesh'):      # в собранном o-voxel (TRELLIS.2 75fbf018) этой функции нет; движок импортирует её только для обходного пути LUMENGEN_FIX_TILED_MESH=0
            def _no_legacy_tiled(*_a, **_k):
                raise RuntimeError('устаревшая tiled_flexible_dual_grid_to_mesh отсутствует в o_voxel образа; движок должен идти по своей реализации (LUMENGEN_FIX_TILED_MESH=1)')
            ovc.tiled_flexible_dual_grid_to_mesh = _no_legacy_tiled
        os.environ.setdefault('LUMENGEN_FIX_TILED_MESH', '1')
        torch.cuda.synchronize()
        return {'weights_s': round(t_dl, 1), 'to_gpu_s': round(time.time() - t, 1)}

    def generate(self, image, params: dict, path: str) -> dict:
        import shutil
        from pathlib import Path
        from localmesh_engine import GenerateSettings
        seed = int(params.get('seed', 42))
        detail = params.get('detail') or 'high'
        work = os.path.join(OUT, f'_lm_{os.getpid()}_{int(time.time() * 1000)}')
        os.makedirs(work, exist_ok=True)
        src = os.path.join(work, 'in.png')
        image.save(src)
        st = GenerateSettings(images=[Path(src)], detail=detail, seed=seed, projection_texture=True)
        res = self.engine.generate(st, Path(work))
        shutil.move(str(res.glb_path), path)
        has_ai = bool(res.glb_ai and os.path.exists(str(res.glb_ai)))
        if has_ai:
            shutil.move(str(res.glb_ai), path[:-4] + '.ai.glb')
        shutil.rmtree(work, ignore_errors=True)
        return {'detail': detail, 'has_ai': has_ai, 'stage_s': res.stages, 'peak_vram_gb': res.peak_vram_gb, 'vram_source': res.vram_portee, 'vram_occupation_pct': res.vram_occupation_pct,
                'faces': res.faces, 'notes': res.notes[:12], 'engine_duration_s': round(res.duration_s, 1)}


# ——— mvadapter-i2tex: краска ГОТОВОЙ формы по MV-Adapter (T-20261119-06/2) ———
# Источник — github.com/huanngzh/MV-Adapter, коммит 4277e00 (source: external:github; код Apache-2.0, веса huanngzh/mv-adapter Apache-2.0, SDXL base — OpenRAIL++-M; nvdiffrast — некоммерческий).
# Что делает апстрим (`scripts/texture_i2tex.py`): 1) `run_pipeline` (scripts/inference_ig2mv_sdxl.py:122) рисует с формы карты позиций и нормалей в 6 видах 768² (ортографическая камера ±0,55,
# расстояние 1,8, подъём 0/0/0/0/+89,99/−89,99°, поворот [0,90,180,270,180,180]−90°) и SDXL с адаптером даёт 6 цветных видов с опорой на фото (50 шагов, guidance 3,0);
# 2) `TexturePipeline.__call__` (mvadapter/pipelines/pipeline_texture.py:136) увеличивает виды RealESRGAN ×2, проецирует их на развёртку 4096² (`CameraProjection`) и достраивает невидимое LaMa по видам.
# Мы подаём форму из GLB с ГОТОВОЙ развёрткой CuMesh (`uv_unwarp=False`: тяжёлую развёртку UVAtlas на процессоре не зовём — вершины, грани и UV остаются как были).
MV_ORTHO = 1.1                  # сторона ортографической камеры апстрима (left/right/bottom/top = ±0,55)
MV_VIEWS = 6
MV_BASE = 'stabilityai/stable-diffusion-xl-base-1.0'
MV_VAE = 'madebyollin/sdxl-vae-fp16-fix'
MV_ADAPTER = 'huanngzh/mv-adapter'
MV_NEG = 'watermark, ugly, deformed, noisy, blurry, low contrast'
MV_AZ = [x - 90 for x in [0, 90, 180, 270, 180, 180]]          # как в `scripts/texture_i2tex.py:118`; `TexturePipeline` вычитает ещё 90° и сама поворачивает форму (front_x_to_y) — вместе кадр тот же, что у `run_pipeline`
MV_EL = [0, 0, 0, 0, 89.99, -89.99]                            # подъём камер — по умолчанию `TexturePipeline.__call__` (camera_elevation_deg)
MV_STAGE_PX = 1536                                             # А0 (`mv_keep_stages`): кадр рендера в камере вида 0 — как вид после RealESRGAN ×2
MV_STAGE_SS = 2                                                # рендер в 2× и усреднение 2×2: текстура 4096² в кадре 1536² иначе даёт муар


def mv_norm_mask(m, n: int = FIT_N, fill: float = 0.9):
    """Маска → кадр n×n так, как апстрим готовит фото (`preprocess_image`, inference_ig2mv_sdxl.py:91): рамка по маске, длинная сторона = fill·n, по центру. Нужна, чтобы сравнивать силуэты
    формы и фото независимо от масштаба и сдвига. Пустая маска — ValueError."""
    import numpy as np
    from PIL import Image
    m = np.asarray(m)
    ys, xs = np.nonzero(m)
    if ys.size == 0:
        raise ValueError('пустая маска: на картинке или в проекции формы нет предмета')
    crop = (m[ys.min():ys.max() + 1, xs.min():xs.max() + 1] > 0).astype(np.uint8) * 255
    h, w = crop.shape
    k = fill * n / max(h, w)
    nh, nw = max(1, int(round(h * k))), max(1, int(round(w * k)))
    im = np.asarray(Image.fromarray(crop).resize((nw, nh), Image.Resampling.BILINEAR)) > 127
    out = np.zeros((n, n), dtype=bool)
    y0, x0 = (n - nh) // 2, (n - nw) // 2
    out[y0:y0 + nh, x0:x0 + nw] = im
    return out


def mv_photo_mask(rgba, n: int = FIT_N):
    """Силуэт фото как у апстрима: альфа > 0 (inference_ig2mv_sdxl.py:93), потом `mv_norm_mask`."""
    import numpy as np
    a = np.asarray(rgba.convert('RGBA').getchannel('A')) > 0
    return mv_norm_mask(a, n)


def mv_ortho_uv(p):
    """Куда ортографическая камера вида 0 (азимут −90°: смотрит на сторону +Z формы, вверх +Y, вправо +X; ±0,55) кладёт точки куба; кадр [0, 1]². Вывод: `get_orthogonal_camera` апстрима,
    `load_mesh(front_x_to_y=False)` — у `run_pipeline` форма идёт без поворота кадра; наш GLB — Y вверх, лицом +Z, то есть вид 0 = «в лоб»."""
    import numpy as np
    p = np.asarray(p, dtype=np.float64)
    return 0.5 + p[:, 0] / MV_ORTHO, 0.5 - p[:, 1] / MV_ORTHO


def mv_fit_yaw(verts, faces, rgba, n: int = FIT_N, force=None) -> dict:
    """Какой поворот формы вокруг вертикали (0/90/180/270°) ставит её «лицом» к виду 0, как на фото: IoU силуэтов (форма в ортографии и фото после рамки/масштаба апстрима).
    Ничья — меньший угол. Предупреждение: силуэт вида спереди и сзади — зеркальные, 0° и 180° различаются только несимметричностью предмета — потому есть `force` (`--mv-yaw`)."""
    A = mv_photo_mask(rgba, n)
    ious = {}
    for yaw in YAWS_DEG:
        p = to_cube(verts, yaw)[0]
        u, v = mv_ortho_uv(p)
        ious[str(yaw)] = round(_iou(A, mv_norm_mask(surface_mask(u, v, faces, n), n)), 4)
    best = max(YAWS_DEG, key=lambda y: (ious[str(y)], -y))
    if force is not None:
        if int(force) not in YAWS_DEG:
            raise ValueError(f'mv_yaw: auto или одно из {YAWS_DEG}, получено {force!r}')
        yaw = int(force)
    else:
        yaw = best
    return {'yaw_deg': yaw, 'forced': force is not None, 'iou': ious[str(yaw)], 'iou_best': ious[str(best)], 'iou_by_yaw': ious}


def mv_write_input_glb(path: str, p, faces, uv=None) -> None:
    """Входной GLB для апстрима: форма в кубе (повёрнутая на yaw) + ТА ЖЕ развёртка; текстура-заглушка 4×4 (без материала trimesh не пишет UV). Вершины идут float32 (формат GLB).
    `uv=None` — только форма, без развёртки (MVPainter строит свою, xatlas)."""
    import numpy as np
    import trimesh
    from PIL import Image
    visual = None
    if uv is not None:
        mat = trimesh.visual.material.PBRMaterial(baseColorTexture=Image.new('RGB', (4, 4), (255, 255, 255)))
        visual = trimesh.visual.TextureVisuals(uv=np.asarray(uv, dtype=np.float64), material=mat)
    m = trimesh.Trimesh(vertices=np.asarray(p, dtype=np.float64), faces=np.asarray(faces), visual=visual, process=False)
    m.export(path)


def mv_build_final(verts, faces, uv, texture, texture_size: int):
    """Итог: ИСХОДНЫЕ вершины, грани и развёртка + краска апстрима (его GLB хранит её JPEG 4096², здесь — к `texture_size`, PNG). Свойства материала — как у апстрима (металл 0, шероховатость 0,9)."""
    import numpy as np
    import trimesh
    from PIL import Image
    tex = texture.convert('RGB')
    if texture_size and tex.size != (texture_size, texture_size):
        tex = tex.resize((texture_size, texture_size), Image.Resampling.LANCZOS)
    mat = trimesh.visual.material.PBRMaterial(baseColorTexture=tex, baseColorFactor=[255, 255, 255, 255], metallicFactor=0.0, roughnessFactor=0.9)
    return trimesh.Trimesh(vertices=np.asarray(verts, dtype=np.float64), faces=np.asarray(faces), visual=trimesh.visual.TextureVisuals(uv=np.asarray(uv, dtype=np.float64), material=mat), process=False)


def mv_stub_modules() -> list:
    """`mesh_process.py` апстрима на уровне модуля импортирует open3d и pymeshlab (нужны только развёртке UVAtlas, мы её не зовём; `Percentage` — единственное имя, берётся при импорте). Не установлены —
    ставим пустые заглушки в `sys.modules` (вызов чего-либо из них — ошибка с понятным текстом). Возвращает имена подставленных."""
    import importlib
    import types
    done = []
    for name in ('open3d', 'pymeshlab'):
        try:
            importlib.import_module(name)
            continue
        except ImportError:
            pass
        mod = types.ModuleType(name)

        def _nope(*_a, _n=name, **_k):
            raise RuntimeError(f'{_n} в образе нет: нужен только развёртке UVAtlas (uv_unwarp=True), а мы берём готовую развёртку формы')

        def _getattr(attr, _f=_nope):
            if attr.startswith('__'):
                raise AttributeError(attr)
            return _f                                         # `from pymeshlab import Percentage` и т. п. импортируются, вызов — ошибка
        mod.__getattr__ = _getattr
        sys.modules[name] = mod
        done.append(name)
    return done


def mv_keep_flag(v) -> bool:
    """`mv_keep_stages` из задания: 1/true/'1' — включено; нет, 0, '', 'false' — выключено (по умолчанию выключено, ничего не меняет)."""
    return str(v).strip().lower() in ('1', 'true', 'yes', 'on')


def mv_split_views(views_png: str, out_dir: str, n: int = MV_VIEWS) -> list:
    """Сетка `mv.png` (n видов в ряд) → n отдельных PNG без потерь (`v0.png` … ). Возвращает относительные имена (от папки стадий: `views_768/vN.png`)."""
    from PIL import Image
    os.makedirs(out_dir, exist_ok=True)
    im = Image.open(views_png)
    im.load()
    w = im.width // n
    names = []
    for i in range(n):
        p = os.path.join(out_dir, f'v{i}.png')
        im.crop((i * w, 0, (i + 1) * w, im.height)).save(p)
        names.append(os.path.join(os.path.basename(out_dir), f'v{i}.png'))
    return names


def mv_zip_dir(src: str, zip_path: str) -> dict:
    """Папка стадий → архив (без сжатия: PNG и npz уже сжаты). Пути в архиве — от `src`, с `/`. → {'bytes', 'files'}."""
    import zipfile
    n = 0
    os.makedirs(os.path.dirname(zip_path) or '.', exist_ok=True)
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_STORED) as z:
        for root, _dirs, files in os.walk(src):
            for fn in sorted(files):
                full = os.path.join(root, fn)
                z.write(full, os.path.relpath(full, src).replace(os.sep, '/'))
                n += 1
    return {'bytes': os.path.getsize(zip_path), 'files': n}


def mv_keep_stages(runner, in_glb: str, uv_size: int, cap: dict, tex, final, views_png: str, stages_dir: str, zip_path: str, info: dict) -> dict:
    """А0 (`mv_keep_stages=1`, только проба): сохранить стадии без потерь и собрать `stages.zip`. Не меняет ни форму, ни краску итога. Сбой самого сохранения не отнимает у задания GLB (деньги уже потрачены):
    причина идёт в метрики (`error`), архив собирается из того, что успело сохраниться; фатальная ошибка CUDA — наружу (воркер помечается сломанным, как везде)."""
    t0 = time.time()
    os.makedirs(stages_dir, exist_ok=True)
    err = None
    ran: dict = {}
    try:
        info['views_768'] = mv_split_views(views_png, os.path.join(stages_dir, 'views_768'))
        import shutil
        shutil.copy(views_png, os.path.join(stages_dir, 'mv.png'))
        ran = runner.keep_stages(in_glb, uv_size, cap, tex, final.visual.material.baseColorTexture, stages_dir) or {}
    except Exception as e:  # noqa: BLE001
        if classify_cuda_error(e) == 'fatal':
            raise
        err = f'{type(e).__name__}: {str(e)[:300]}'
        print('[mvtex] keep_stages: сбой сохранения стадий —', err, '\n' + traceback.format_exc()[-1500:], flush=True)
    manifest = {**info, **ran, 'error': err}
    with open(os.path.join(stages_dir, 'manifest.json'), 'w', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1, default=str)
    z = mv_zip_dir(stages_dir, zip_path)
    return {'zip': os.path.basename(zip_path), **z, 'keep_s': round(time.time() - t0, 2), 'error': err, 'timing_s': ran.get('timing_s'), 'jpeg_mae_255': ran.get('jpeg_mae_255')}


def mv_texture_on_shape(runner, mesh, image, params: dict, hooks: dict | None = None, work: str | None = None, stages_zip: str | None = None) -> tuple:
    """Покрасить ГОТОВУЮ форму `mesh` (trimesh, кадр GLB: Y вверх; нужна развёртка UV на каждую вершину) по фото `image` (RGBA, настоящая альфа). `runner` — две стадии апстрима:
    `views(in_glb, image, params, work) → путь к PNG с 6 видами в ряд` и `unproject(in_glb, views_png, work, uv_size) → путь к GLB с краской`. Возвращает (trimesh: исходные вершины/грани/UV + краска, замеры).
    Форма не меняется: после апстрима GLB читается обратно, вершины возвращаются из куба и сверяются с входом (`check_shape_unchanged`, допуск 1e-4 диагонали), развёртка — тоже."""
    import tempfile
    import numpy as np
    import trimesh
    hk = {'sync': lambda: None, 'free': lambda: None, 'mem': lambda name: None, **(hooks or {})}
    stage: dict = {}
    t = time.time()

    def lap(name: str) -> None:
        hk['sync']()
        nonlocal t
        stage[name] = round(time.time() - t, 2)
        hk['free']()
        hk['mem'](name)
        t = time.time()

    verts = np.asarray(mesh.vertices, dtype=np.float64)
    faces = np.asarray(mesh.faces, dtype=np.int64)
    uv = getattr(getattr(mesh, 'visual', None), 'uv', None)
    if uv is None or len(uv) != len(verts):
        raise ValueError('у формы нет развёртки (UV на каждую вершину): mvadapter-i2tex использует готовую развёртку из GLB — нужен GLB от TRELLIS.2 (CuMesh), не «сырая» форма')
    uv = np.asarray(uv, dtype=np.float64)
    uv_size = int(params['mv_uv_size'] if params.get('mv_uv_size') is not None else 4096)
    steps = int(params['mv_steps'] if params.get('mv_steps') is not None else 50)
    if uv_size not in (1024, 2048, 4096) or not 1 <= steps <= 100:
        raise ValueError('mv_uv_size: 1024/2048/4096, mv_steps: 1..100')
    texture_size = int(params.get('texture_size', 2048))
    yaw_param = params.get('mv_yaw')
    fit = mv_fit_yaw(verts, faces, image, force=None if yaw_param in (None, '', 'auto') else yaw_param)
    lap('fit_yaw')
    work = work or tempfile.mkdtemp(prefix='mvtex-', dir=OUT if os.path.isdir(OUT) else None)
    p, c, s, R = to_cube(verts, fit['yaw_deg'])
    in_glb = os.path.join(work, 'in.glb')
    mv_write_input_glb(in_glb, p, faces, uv)
    lap('write_input')
    keep = mv_keep_flag(params.get('mv_keep_stages'))          # А0: сохранить стадии (только проба; выключено — поведение и вывод прежние)
    cap = {} if keep else None
    views_png = runner.views(in_glb, image, params, work)
    lap('views')
    shaded = runner.unproject(in_glb, views_png, work, uv_size, capture=cap) if keep else runner.unproject(in_glb, views_png, work, uv_size)
    lap('unproject')
    back = trimesh.load(shaded, force='mesh', process=False)
    v_back = from_cube(np.asarray(back.vertices, dtype=np.float64), c, s, R).astype(np.float32).astype(np.float64)       # через float32, как лежит в GLB
    shape = check_shape_unchanged(verts.astype(np.float32).astype(np.float64), faces, v_back, np.asarray(back.faces))
    uv_back = getattr(back.visual, 'uv', None)
    uv_dev = float(np.abs(np.asarray(uv_back, dtype=np.float64) - uv).max()) if uv_back is not None and len(uv_back) == len(uv) else float('inf')
    if not uv_dev <= 1e-4:
        raise ShapeChanged(f'развёртка изменилась: наибольшее расхождение UV {uv_dev:.2e} (допуск 1e-4)')
    tex = getattr(getattr(back.visual, 'material', None), 'baseColorTexture', None)
    if tex is None:
        raise RuntimeError('апстрим вернул GLB без текстуры')
    lap('check_shape')
    final = mv_build_final(verts, faces, uv, tex, texture_size)
    lap('build')
    stages = None
    if keep:                                                    # после защиты «форма и развёртка не изменились» и после сборки итога: итог от этого не меняется
        stages = mv_keep_stages(runner, in_glb, uv_size, cap, tex, final, views_png, os.path.join(work, 'stages'), stages_zip or os.path.join(work, 'stages.zip'),
                                {'uv_size': uv_size, 'texture_size': texture_size, 'steps': steps, 'yaw_deg': fit['yaw_deg'], 'mv_az': MV_AZ, 'mv_el': MV_EL, 'ortho': MV_ORTHO,
                                 'view_px': 768, 'tex_in_size': list(tex.size)})
        lap('keep_stages')
    thumb = None
    try:
        import base64
        from PIL import Image
        im = Image.open(views_png).convert('RGB')
        im = im.resize((max(1, im.width * 256 // im.height), 256), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, format='JPEG', quality=80)
        thumb = base64.b64encode(buf.getvalue()).decode()
    except Exception:  # noqa: BLE001 — миниатюра видов нужна для разбора, не для результата
        thumb = None
    out = {'fit': fit, 'shape': shape, 'uv_max_dev': round(uv_dev, 8), 'stage_s': stage, 'mesh_tris': int(len(faces)), 'mesh_verts': int(len(verts)),
           'uv_size': uv_size, 'steps': steps, 'texture_size': texture_size, 'tex_in_size': list(tex.size), 'views_jpeg_b64': thumb}
    if stages is not None:
        out['stages'] = stages                                  # {'zip', 'bytes', 'files', 'keep_s', 'error', …}; ключ появляется только при mv_keep_stages
    return final, out


class MVRunner:
    """Две стадии апстрима на настоящих моделях (`MVAdapterTexBackend.load`). `offload`: между стадиями SDXL уходит на процессор (освобождает ≈ 7 ГБ под проекцию на 4096²)."""

    def __init__(self, ig, tex_pipe, mod_cfg, pipe, offload: bool, torch):
        self.ig, self.tex_pipe, self.mod_cfg, self.pipe, self.offload, self.torch = ig, tex_pipe, mod_cfg, pipe, offload, torch

    def _pipe_to(self, dev: str) -> None:
        self.pipe.to(dev)
        self.pipe.cond_encoder.to(dev)           # адаптер не входит в компоненты конвейера (prepare_pipeline двигает его отдельно)

    def views(self, in_glb: str, image, params: dict, work: str) -> str:
        from PIL import Image
        if self.offload:
            self._pipe_to('cuda')
        try:
            images, _pos, _nrm, _ref = self.ig.run_pipeline(
                self.pipe, mesh_path=in_glb, num_views=MV_VIEWS, text=params.get('mv_text') or 'high quality', image=image, height=768, width=768,
                num_inference_steps=int(params['mv_steps'] if params.get('mv_steps') is not None else 50), guidance_scale=3.0, seed=int(params.get('seed', 42)),
                reference_conditioning_scale=float(params['mv_ref_scale'] if params.get('mv_ref_scale') is not None else 1.0), negative_prompt=MV_NEG, device='cuda', remove_bg_fn=None)
        finally:
            if self.offload:
                self._pipe_to('cpu')
        grid = Image.new('RGB', (768 * MV_VIEWS, 768))
        for i, im in enumerate(images):
            grid.paste(im.convert('RGB'), (768 * i, 0))
        path = os.path.join(work, 'mv.png')
        grid.save(path)
        return path

    def _unproject(self, in_glb: str, views_png: str, work: str, uv_size: int) -> str:
        out = self.tex_pipe(mesh_path=in_glb, save_dir=work, save_name='mv', uv_unwarp=False, preprocess_mesh=False, uv_size=uv_size, rgb_path=views_png,
                            rgb_process_config=self.mod_cfg(view_upscale=True, inpaint_mode='view'), camera_azimuth_deg=MV_AZ)
        return out.shaded_model_save_path

    def unproject(self, in_glb: str, views_png: str, work: str, uv_size: int, capture: dict | None = None) -> str:
        """Без `capture` — как раньше. С `capture` (А0, `mv_keep_stages`) тот же вызов апстрима, но с двумя «подслушивающими» обёртками, поведение которых не меняют:
        `maybe_upscale_image` (выход RealESRGAN: 6 видов 1536² → `capture['up_pil']`, вид 0 в float32 → `capture['up0']`) и `replace_mesh_texture_and_save` модуля `pipeline_texture`
        (картинка карты 4096² ДО JPEG, в который её жмёт апстрим при записи GLB → `capture['tex_lossless']`). Обе обёртки снимаются в `finally`."""
        if capture is None:
            return self._unproject(in_glb, views_png, work, uv_size)
        import importlib
        import numpy as np
        from PIL import Image
        torch = self.torch
        PT = importlib.import_module('mvadapter.pipelines.pipeline_texture')
        orig_up = self.tex_pipe.maybe_upscale_image
        orig_save = PT.replace_mesh_texture_and_save

        def spy_up(tensor, upscale, upscale_factor, batched=False):
            out = orig_up(tensor, upscale, upscale_factor, batched)
            if upscale and 'up_pil' not in capture:
                u8 = (out.detach().clamp(0, 1) * 255).round().to(torch.uint8).cpu().numpy()
                capture['up_pil'] = [Image.fromarray(np.ascontiguousarray(x)) for x in u8]
                capture['up0'] = out[0:1].detach().float().cpu().clone()
            return out

        def spy_save(*a, **kw):
            tx = kw.get('texture')
            if isinstance(tx, Image.Image):
                capture['tex_lossless'] = tx.copy()
            return orig_save(*a, **kw)
        self.tex_pipe.maybe_upscale_image = spy_up
        PT.replace_mesh_texture_and_save = spy_save
        try:
            return self._unproject(in_glb, views_png, work, uv_size)
        finally:
            PT.replace_mesh_texture_and_save = orig_save
            try:
                del self.tex_pipe.maybe_upscale_image                       # вернуть метод класса
            except AttributeError:
                pass

    def keep_stages(self, in_glb: str, uv_size: int, cap: dict, tex_glb, tex_final, out_dir: str) -> dict:
        """А0: всё, что нужно, чтобы сравнить стадии с видом 0 «пиксель в пиксель». Камера — ТА ЖЕ ортокамера вида 0, что у проекции (форма и камеры собраны точно как в `TexturePipeline.__call__`:
        `load_mesh(rescale=True, front_x_to_y=True, default_uv_size)`, `get_orthogonal_camera(… azimuth = MV_AZ − 90)`); рендер — `render` апстрима (nvdiffrast, видеокарта).
        Сохраняет в `out_dir`: `views_1536/vN.png` (после RealESRGAN), `maps/tex4096_lossless.png` (до JPEG), `tex4096_glb.png` (то, что лежит в GLB апстрима, после JPEG), `tex4096_from0.png` (запекание ТОЛЬКО из вида 0),
        `tex2048.png` (итог), `render_view0/*` (рендеры форм с четырьмя картами, маска, нормали, cos угла к камере, UV по пикселям). Запекание из вида 0: второй вызов `cam_proj` с ОДНИМ видом (его картинка после RealESRGAN
        и его камера) и теми же порогами, что у основного (aoi_cos 0,2, depth_grad 0,1/5, alpha 3): остальные виды физически не участвуют, веса нормируются на единицу; LaMa-достройка невидимого не делается
        (нужен только фасад вида 0). Возвращает описание файлов, время и измерение потери на JPEG."""
        import importlib
        import numpy as np
        from PIL import Image
        torch = self.torch
        TF = torch.nn.functional
        dev = getattr(self.tex_pipe, 'device', 'cuda')
        MU = importlib.import_module('mvadapter.utils.mesh_utils')
        MR = importlib.import_module('mvadapter.utils.mesh_utils.render')
        MUT = importlib.import_module('mvadapter.utils.mesh_utils.utils')
        files: dict = {}
        timing: dict = {}
        t = [time.time()]

        def lap(name: str) -> None:
            try:
                torch.cuda.synchronize()
            except Exception:  # noqa: BLE001 — без видеокарты (проверка на процессоре) синхронизировать нечего
                pass
            timing[name] = round(time.time() - t[0], 2)
            t[0] = time.time()

        def save(img, rel: str) -> None:
            p = os.path.join(out_dir, rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            img.save(p)
            files[rel] = os.path.getsize(p)

        def u8(x):                                               # float [0, 1] → uint8 без потерь, кроме округления
            return (x.detach().clamp(0, 1) * 255).round().to(torch.uint8).cpu().numpy()

        for i, im in enumerate(cap.get('up_pil') or []):
            save(im, f'views_{MV_STAGE_PX}/v{i}.png')
        lap('save_views_up')
        save(tex_glb.convert('RGB'), 'maps/tex4096_glb.png')
        if cap.get('tex_lossless') is not None:
            save(cap['tex_lossless'].convert('RGB'), 'maps/tex4096_lossless.png')
        save(tex_final.convert('RGB'), 'maps/tex2048.png')
        lap('save_maps')
        mesh = MU.load_mesh(in_glb, rescale=True, move_to_center=False, front_x_to_y=True, default_uv_size=uv_size, device=dev)
        cams = MU.get_orthogonal_camera(elevation_deg=MV_EL, distance=[1.0] * 6, left=-MV_ORTHO / 2, right=MV_ORTHO / 2, bottom=-MV_ORTHO / 2, top=MV_ORTHO / 2,
                                        azimuth_deg=[x - 90 for x in MV_AZ], device=dev)
        cam0 = cams[0:1]
        # --- запекание только из вида 0 ---
        texs = {'r4096_from6': tex_glb, 'r2048': tex_final}
        if cap.get('tex_lossless') is not None:
            texs['r4096_lossless'] = cap['tex_lossless']
        from0 = None
        if cap.get('up0') is not None:
            out = self.tex_pipe.cam_proj(cap['up0'].to(dev), mesh, cam0, from_scratch=True, poisson_blending=False, depth_grad_dilation=5, depth_grad_threshold=0.1,
                                         uv_exp_blend_alpha=3, uv_exp_blend_view_weight=torch.as_tensor([1]), aoi_cos_valid_threshold=0.2, uv_size=uv_size, uv_padding=True, return_dict=True)
            from0 = out.uv_proj.detach()
            valid0 = out.uv_proj_mask.detach()
            save(Image.fromarray(u8(from0)), 'maps/tex4096_from0.png')
            save(Image.fromarray(valid0.cpu().numpy().astype(np.uint8) * 255), 'maps/tex4096_from0_valid.png')
            del out
        lap('bake_from0')
        px, ss = MV_STAGE_PX, MV_STAGE_SS
        # --- геометрия в камере вида 0: маска, нормали, cos угла, UV по пикселям ---
        g = MR.render(self.tex_pipe.ctx, mesh, cam0, height=px, width=px, render_attr=False, render_depth=False, render_normal=True)
        mask = g.mask[0]
        n_cs = TF.normalize((g.normal[:, :, :, None, :] * cam0.w2c[:, None, None, :3, :3]).sum(-1), dim=-1)          # нормаль в системе камеры, как у `uv_render_geometry`
        n_cs = torch.where(mask[None, :, :, None], n_cs, torch.zeros_like(n_cs))
        aoi = n_cs[0, :, :, 2].clamp(0, 1)
        save(Image.fromarray(mask.cpu().numpy().astype(np.uint8) * 255), 'render_view0/mask.png')
        save(Image.fromarray(u8(n_cs[0] * 0.5 + 0.5)), 'render_view0/normal_cam.png')
        save(Image.fromarray((aoi.clamp(0, 1) * 65535).round().to(torch.int32).cpu().numpy().astype(np.uint16)), 'render_view0/aoi_cos16.png')
        clip = MUT.get_clip_space_position(mesh.v_pos, cam0.mvp_mtx)
        rast, _ = self.tex_pipe.ctx.rasterize(clip, mesh.t_pos_idx, (px, px), grad_db=False)
        uvm, _ = self.tex_pipe.ctx.interpolate(mesh.v_tex[None], rast, mesh.t_tex_idx)
        uvp = os.path.join(out_dir, 'render_view0', 'uv.npz')
        np.savez_compressed(uvp, uv=uvm[0].detach().float().cpu().numpy().astype(np.float32), mask=(rast[0, :, :, 3] > 0).cpu().numpy())
        files['render_view0/uv.npz'] = os.path.getsize(uvp)
        lap('geometry')
        # --- рендеры форм с картами (в 2× и усреднение) ---
        if from0 is not None:
            texs['r4096_from0'] = from0
        for name, tx in texs.items():
            ten = tx if torch.is_tensor(tx) else torch.from_numpy(np.asarray(tx.convert('RGB'), dtype=np.float32) / 255.0).to(dev)
            r = MR.render(self.tex_pipe.ctx, mesh, cam0, height=px * ss, width=px * ss, render_attr=True, render_depth=False, render_normal=False,
                          texture_override=ten.contiguous(), attr_background=0.5, texture_filter_mode='linear')
            a = r.attr[0].detach().float().reshape(px, ss, px, ss, 3).mean(dim=(1, 3))
            save(Image.fromarray(u8(a)), f'render_view0/{name}.png')
            del r, a, ten
            lap('render_' + name)
        jpeg_mae = None
        if cap.get('tex_lossless') is not None and cap['tex_lossless'].size == tex_glb.size:
            jpeg_mae = round(float(np.abs(np.asarray(cap['tex_lossless'].convert('RGB'), dtype=np.int16) - np.asarray(tex_glb.convert('RGB'), dtype=np.int16)).mean()), 4)
        try:
            torch.cuda.empty_cache()
        except Exception:  # noqa: BLE001
            pass
        return {'render_px': px, 'render_ss': ss, 'camera': {'view': 0, 'elevation_deg': MV_EL[0], 'azimuth_deg': MV_AZ[0] - 90, 'ortho': MV_ORTHO, 'distance': 1.0},
                'uv_flip_v': True, 'uv_note': 'uv.npz: uv[y,x]=(u, v_flipped) — столбец u·uv_size, строка v_flipped·uv_size (строка 0 — верх картинки карты)',
                'files': files, 'timing_s': timing, 'jpeg_mae_255': jpeg_mae, 'from0_bake': 'cam_proj по одному виду 0 (после RealESRGAN); без LaMa'}


class MVAdapterTexBackend:
    """`mvadapter-i2tex`: форма TRELLIS.2 (готовый GLB, `<job>.mesh.glb`) + краска MV-Adapter по одному фото (6 видов SDXL → проекция на готовую развёртку). Образ — `Dockerfile.mvadapter`
    (код MV-Adapter в /opt/MV-Adapter, чекпойнты RealESRGAN/LaMa вшиты; веса SDXL fp16 + VAE + mv-adapter докачиваются на старте ≈ 10 ГиБ). Код едет через `command`.
    Заплатки (ставит `load`, апстрим не правим): nvdiffrast «gl» → «cuda» (в контейнере без EGL/OpenGL), решатель Пуассона «torch-cuda» (JIT-сборка ядра при старте) → «torch-native» (мы его не зовём:
    poisson_blending=False), заглушки open3d/pymeshlab, `from_pretrained` базовой SDXL — вариант fp16 (иначе качается fp32 ≈ 13 ГБ)."""
    name = 'mvadapter-i2tex'
    offload = True                  # MVTEX_OFFLOAD (по умолчанию 1)
    runner = None
    _trace: dict = {}

    def load(self) -> dict:
        os.environ['PYTORCH_CUDA_ALLOC_CONF'] = os.environ.get('MVTEX_ALLOC_CONF', 'expandable_segments:False')      # урок pixal3d-tex (a0346): расширяемые сегменты — путь фатальной ошибки аллокатора
        self.offload = os.environ.get('MVTEX_OFFLOAD', '1') != '0'
        mva = os.environ.get('MVADAPTER_DIR', '/opt/MV-Adapter')
        sys.path.insert(0, mva)
        STATE['phase'] = 'importing'
        t_imp = time.time()
        try:                                                                            # `pipeline_texture` сохраняет GLB через gltflib (backend='gltflib' жёстко), а в requirements апстрима его нет — b0919 упала на сохранении после всех видов
            import gltflib  # noqa: F401
        except ImportError:
            subprocess.run([sys.executable, '-m', 'pip', 'install', '-q', 'gltflib==1.0.13'], check=True, timeout=600)
        import torch
        stubs = mv_stub_modules()
        from scripts import inference_ig2mv_sdxl as IG                                  # `scripts/__init__.py` есть; первым в sys.path — наш каталог
        from mvadapter.pipelines.pipeline_mvadapter_i2mv_sdxl import MVAdapterI2MVSDXLPipeline
        from mvadapter.pipelines.pipeline_texture import ModProcessConfig, TexturePipeline
        import importlib                                                                # `mesh_utils/__init__.py` экспортирует ФУНКЦИЮ `render` — она заслоняет подмодуль (a0852: 'function' has no attribute 'NVDiffRastContextWrapper'); берём сами модули
        MB = importlib.import_module('mvadapter.utils.mesh_utils.blend')
        MR = importlib.import_module('mvadapter.utils.mesh_utils.render')
        patches = []
        _init = MR.NVDiffRastContextWrapper.__init__

        def _init_cuda(self, device, context_type='gl'):                                # RasterizeGLContext в контейнере без дисплея падает; растеризатор CUDA даёт те же карты
            _init(self, device, 'cuda')
        MR.NVDiffRastContextWrapper.__init__ = _init_cuda
        patches.append('nvdiffrast_gl_to_cuda')
        MB.PBTorchCUDAKernelBackend = MB.PBTorchNativeBackend
        patches.append('poisson_torch_cuda_to_native')
        _fp = MVAdapterI2MVSDXLPipeline.from_pretrained.__func__

        def _fp16(cls, *a, **kw):
            kw.setdefault('variant', 'fp16')
            kw.setdefault('torch_dtype', torch.float16)
            kw.setdefault('use_safetensors', True)
            return _fp(cls, *a, **kw)
        MVAdapterI2MVSDXLPipeline.from_pretrained = classmethod(_fp16)
        patches.append('sdxl_fp16_variant')
        STATE['timings']['import_s'] = round(time.time() - t_imp, 1)
        STATE['config'] = {'alloc': os.environ['PYTORCH_CUDA_ALLOC_CONF'], 'offload': self.offload, 'patches': patches, 'stubs': stubs,
                           'debug_env': {k: os.environ.get(k) for k in ('CUDA_LAUNCH_BLOCKING', 'TORCH_SHOW_CPP_STACKTRACES')}}
        print('[mvtex] конфиг:', json.dumps(STATE['config'], ensure_ascii=False), flush=True)
        STATE['phase'] = 'weights'
        t = time.time()
        pipe = IG.prepare_pipeline(base_model=MV_BASE, vae_model=MV_VAE, unet_model=None, lora_model=None, adapter_path=MV_ADAPTER, scheduler=None, num_views=MV_VIEWS, device='cuda', dtype=torch.float16)
        t_w = time.time() - t
        STATE['phase'] = 'to_gpu'
        t = time.time()
        tex_pipe = TexturePipeline(upscaler_ckpt_path=os.path.join(mva, 'checkpoints', 'RealESRGAN_x2plus.pth'), inpaint_ckpt_path=os.path.join(mva, 'checkpoints', 'big-lama.pt'), device='cuda')
        self.runner = MVRunner(IG, tex_pipe, ModProcessConfig, pipe, self.offload, torch)
        if self.offload:
            self.runner._pipe_to('cpu')
        free_gpu()
        STATE['config']['mem_after_warm'] = gpu_mem()
        return {'weights_s': round(t_w, 1), 'to_gpu_s': round(time.time() - t, 1), 'mem_after_warm': STATE['config']['mem_after_warm']}

    def generate(self, image, params: dict, path: str) -> dict:
        if not params.get('texture_mesh'):
            raise ValueError('mvadapter-i2tex красит готовую форму: нужен --texture-mesh <clean.glb>')
        import shutil
        import torch
        import trimesh
        trace: dict = {}
        self._trace = trace

        rss_reset = reset_rss_peak()                                       # пик обычной памяти — с начала ЭТОГО задания (T-20261119-06/6/1)

        def mem(name: str) -> None:
            trace[name] = mem_snapshot(reset_peak=True)
        mem('start')
        t = time.time()
        sc = trimesh.load(os.path.join(JOBS_DIR, params['job_id'] + '.mesh.glb'), force='scene')
        parts = sc.dump()
        if not parts:
            raise ValueError('в GLB формы нет мешей')
        mesh = parts[0] if len(parts) == 1 else trimesh.util.concatenate(parts)
        load_s = round(time.time() - t, 2)
        work = os.path.join(OUT, f'_mv_{os.getpid()}_{int(time.time() * 1000)}')
        os.makedirs(work, exist_ok=True)
        try:
            hooks = {'sync': torch.cuda.synchronize, 'free': free_gpu, 'mem': mem}
            final, m = mv_texture_on_shape(self.runner, mesh, image, params, hooks, work, stages_zip=path[:-len('.glb')] + '.stages.zip' if mv_keep_flag(params.get('mv_keep_stages')) else None)
        finally:
            shutil.rmtree(work, ignore_errors=True)
        final.export(path)
        m['stage_s']['load_shape'] = load_s
        m.update({'mode': 'mvadapter_i2tex', 'peak_vram_gb': max([v.get('peak_allocated_gb', 0.0) for v in trace.values()] or [0.0]),
                  'peak_reserved_gb': max([v.get('peak_reserved_gb', 0.0) for v in trace.values()] or [0.0]), 'mem': trace, 'config': dict(STATE.get('config') or {}),
                  **job_mem_metrics(trace, rss_reset)})
        return m

    def on_error(self, e: BaseException) -> dict:
        """Разбор упавшего задания (зовёт `run_job`): тип ошибки CUDA, память по стадиям. `fatal` — воркер помечается сломанным (`mark_broken`), драйвер гасит группу. Нехватка памяти (`oom`) — освободить память."""
        import traceback as tb
        kind = classify_cuda_error(e)
        tb.clear_frames(e.__traceback__)
        diag = {'kind': kind, 'fatal': kind == 'fatal', 'mem': mem_snapshot(), 'peak_rss_gb': _status_gb('VmHWM'), 'stage_mem': dict(self._trace), 'config': STATE.get('config')}
        if kind == 'oom':
            try:
                if self.runner is not None and self.runner.offload:
                    self.runner._pipe_to('cpu')
            except Exception:  # noqa: BLE001
                pass
            free_gpu()
            diag['mem_after_free'] = gpu_mem()
        return diag


# ——— triposg-mv: форма TripoSG → чистка и развёртка CuMesh → краска MV-Adapter (T-20261119-80, вариант 6 владельца) ———
# Источник формы — github.com/VAST-AI-Research/TripoSG (source: external:github; код MIT, веса VAST-AI/TripoSG — MIT, 7,4 ГиБ, не закрытые; коммит — `Dockerfile.triposg`). У TripoSG нет ни цвета, ни развёртки UV:
# `TripoSGPipeline` (rectified flow, 50 шагов, guidance 7,0, декодер flash octree 9 → `diso.DiffDMC`) отдаёт только вершины и грани в своём кадре.
# Дальше — ТЕ ЖЕ шаги, что у TRELLIS.2 в `o_voxel.postprocess.to_glb` без запекания (ветка remesh=False): CuMesh simplify(3×цель) → чистка (дубли граней, неманифолдные рёбра, мелкие куски 1e-5)
# → simplify(цель) → чистка → единая ориентация граней → вырожденные грани < 1e-10 → `uv_unwrap` (быстрая кластеризация + xatlas, те же пороги). Затем драйвер на pakardev чистит форму общим правилом `mesh_clean`
# (плита у пола; одно правило для всех моделей) и возвращает её этой же ноде заданием «краска» — тот же `MVAdapterTexBackend.generate`, что у `mvadapter-i2tex` (код краски не дублируется).
# Кадр формы: TripoSG не обещает, какая ось «вверх» и куда «лицом» — выбираем из 24 поворотов куба тот, чей силуэт в ортографии лучше всего совпадает с фото (`tp_fit_orient`), иначе краска ляжет не на ту сторону.
TP_REPO = 'VAST-AI/TripoSG'
TP_STEPS = 50                 # как в апстриме (`scripts/inference_triposg.py`)
TP_GUIDANCE = 7.0
TP_FIT_FACES = 120000         # для подгонки кадра берём не больше граней (силуэт от этого не меняется, а 24 прохода по миллиону граней — минуты)
TP_ORIENT_MARGIN = 0.02       # уйти от «как есть» можно, только если лучший поворот лучше на столько IoU: иначе 0° и 180° (зеркальные силуэты) дрожали бы от шума
TP_CODE = '/opt/TripoSG'


def tp_rotations() -> list:
    """24 поворота куба (оси переставляются, знаки меняются, определитель +1): [(имя, R)], «как есть» — первым. Имя — какие оси исходной формы стали X, Y, Z (`-Z` — перевёрнутая)."""
    import itertools
    import numpy as np
    out = []
    for perm in itertools.permutations(range(3)):
        for signs in itertools.product((1, -1), repeat=3):
            R = np.zeros((3, 3))
            for i, (p, s) in enumerate(zip(perm, signs)):
                R[i, p] = s
            if np.linalg.det(R) > 0:
                out.append((' '.join(('-' if s < 0 else '') + 'XYZ'[p] for p, s in zip(perm, signs)), R))
    out.sort(key=lambda x: (not np.array_equal(x[1], np.eye(3)), x[0]))
    return out


def tp_fit_orient(verts, faces, rgba, n: int = FIT_N, max_faces: int = TP_FIT_FACES) -> dict:
    """Какой из 24 поворотов куба ставит форму TripoSG «вверх по Y, лицом +Z» как на фото: IoU силуэта формы (ортографическая камера вида 0 MV-Adapter) и силуэта фото (`mv_photo_mask`). Возвращает
    {'name','R','iou','iou_identity','switched','top': [(имя, IoU) ×3]}. «Как есть» остаётся, пока лучший не лучше его на `TP_ORIENT_MARGIN`."""
    import numpy as np
    verts = np.asarray(verts, dtype=np.float64)
    faces = np.asarray(faces)
    if len(faces) > max_faces:
        faces = faces[np.random.default_rng(0).choice(len(faces), size=max_faces, replace=False)]
    A = mv_photo_mask(rgba, n)
    rots = tp_rotations()
    ious = []
    for _name, R in rots:
        u, v = mv_ortho_uv(to_cube(verts @ R.T, 0.0)[0])
        ious.append(_iou(A, mv_norm_mask(surface_mask(u, v, faces, n), n)))
    best = max(range(len(rots)), key=lambda k: (round(ious[k], 4), -k))
    pick = 0 if ious[0] >= ious[best] - TP_ORIENT_MARGIN else best
    top = sorted(range(len(rots)), key=lambda k: (-ious[k], k))[:3]
    return {'name': rots[pick][0], 'R': rots[pick][1], 'iou': round(ious[pick], 4), 'iou_identity': round(ious[0], 4), 'switched': pick != 0, 'top': [(rots[k][0], round(ious[k], 4)) for k in top]}


def tp_normalize(verts):
    """Центр габарита — в ноль, наибольшая сторона — 1 (как у TRELLIS.2: aabb [−0,5; 0,5]); с ним пороги CuMesh (мелкие куски 1e-5) значат то же, что в `to_glb`. → (вершины, центр, масштаб)."""
    import numpy as np
    v = np.asarray(verts, dtype=np.float64)
    lo, hi = v.min(axis=0), v.max(axis=0)
    ext = float((hi - lo).max())
    if not ext > 0:
        raise ValueError('форма вырождена: габарит нулевой')
    c = (lo + hi) / 2.0
    return (v - c) / ext, c, 1.0 / ext


def _tp_np(x):
    import numpy as np
    return x.detach().cpu().numpy() if hasattr(x, 'detach') else np.asarray(x)


def tp_cumesh_uv(verts, faces, target: int, CM, to_gpu) -> tuple:
    """Чистка и развёртка CuMesh — шаги `o_voxel.postprocess.to_glb` (remesh=False) без запекания. `CM` — модуль cumesh (в тестах подмена), `to_gpu(массив numpy) → тензор на видеокарте`.
    Возвращает (вершины, грани, UV, замеры) numpy; вершины, грани и UV — уже после `uv_unwrap` (вершины размножены по швам, V перевёрнут как у TRELLIS.2)."""
    import numpy as np
    info: dict = {'faces_in': int(len(faces)), 'verts_in': int(len(verts)), 'target': int(target)}
    t = time.time()
    mesh = CM.CuMesh()
    mesh.init(to_gpu(np.ascontiguousarray(verts, dtype=np.float32)), to_gpu(np.ascontiguousarray(faces, dtype=np.int32)))

    def clean() -> None:
        mesh.remove_duplicate_faces()
        mesh.repair_non_manifold_edges()
        mesh.remove_small_connected_components(1e-5)
    if mesh.num_faces > target:
        mesh.simplify(target * 3)
        info['faces_after_simplify3'] = int(mesh.num_faces)
    clean()
    if mesh.num_faces > target:
        mesh.simplify(target)
    clean()
    mesh.unify_face_orientations()
    info['faces_clean'] = int(mesh.num_faces)
    info['clean_s'] = round(time.time() - t, 2)
    vt, ft = mesh.read()
    vn, fn = _tp_np(vt), _tp_np(ft)
    a = np.linalg.norm(np.cross(vn[fn[:, 1]] - vn[fn[:, 0]], vn[fn[:, 2]] - vn[fn[:, 0]]), axis=1)         # вырожденные (xatlas на них падает): тот же порог 1e-10, что в to_glb
    bad = a < 1e-10
    info['degenerate_removed'] = int(bad.sum())
    if bad.any():
        mesh = CM.CuMesh()
        mesh.init(to_gpu(np.ascontiguousarray(vn, dtype=np.float32)), to_gpu(np.ascontiguousarray(fn[~bad], dtype=np.int32)))
    t = time.time()
    out_v, out_f, out_uv, _vmaps = mesh.uv_unwrap(compute_charts_kwargs={'threshold_cone_half_angle_rad': float(np.radians(90.0)), 'refine_iterations': 0, 'global_iterations': 1, 'smooth_strength': 1},
                                                  return_vmaps=True)
    info['uv_s'] = round(time.time() - t, 2)
    out_v, out_f, out_uv = _tp_np(out_v).astype(np.float64), _tp_np(out_f).astype(np.int64), _tp_np(out_uv).astype(np.float64).copy()
    out_uv[:, 1] = 1.0 - out_uv[:, 1]                                                                     # как в to_glb: V наоборот (glTF)
    info.update(faces_out=int(len(out_f)), verts_out=int(len(out_v)))
    return out_v, out_f, out_uv, info


class TripoSGMVBackend(MVAdapterTexBackend):
    """`triposg-mv`: ОДНА нода, два вида заданий. БЕЗ `texture_mesh` — «форма»: фото → TripoSG → поворот кадра по силуэту фото → CuMesh (чистка + UV) → GLB формы без краски (текстура-заглушка 4×4).
    С `texture_mesh` — «краска»: форма, которую драйвер почистил общим правилом, красится MV-Adapter ровно как у `mvadapter-i2tex` (наследуем `generate`). Образ — `Dockerfile.triposg` (поверх образа MV-Adapter:
    TripoSG в /opt/TripoSG, `diso`, scikit-image). Веса: TripoSG ≈ 7,4 ГиБ + MV-Adapter ≈ 10 ГиБ докачиваются на старте. TripoSG на видеокарте только между «формой» и «краской» (перед краской уходит на процессор)."""
    name = 'triposg-mv'
    tp = None

    def check_arch(self) -> dict:
        """Образ собран под одну архитектуру CUDA (`IMAGE_CUDA_ARCH`, урок 742): другая карта — «no kernel image» на первом расширении. Падаем при прогреве, а не на задании."""
        import torch
        cap = '%d.%d' % torch.cuda.get_device_capability()
        built = (os.environ.get('IMAGE_CUDA_ARCH') or '').split()
        if built and cap not in built:
            raise RuntimeError(f'карта с архитектурой CUDA {cap} ({torch.cuda.get_device_name()}), образ собран под {" ".join(built)} — расширения (CuMesh, diso, nvdiffrast) на ней не заработают')
        return {'card_arch': cap, 'image_arch': built, 'card': torch.cuda.get_device_name()}

    def load(self) -> dict:
        import importlib
        import importlib.util
        import numpy as np  # noqa: F401
        import torch
        STATE['phase'] = 'importing'
        arch = self.check_arch()
        code = os.environ.get('TRIPOSG_DIR', TP_CODE)
        sys.path.insert(0, code)
        t_imp = time.time()
        CM = importlib.import_module('cumesh')                                           # те же расширения, что у TRELLIS.2 (образ-основа); нет — падаем ДО докачки 17 ГиБ весов
        importlib.import_module('diso')
        importlib.import_module('skimage.measure')
        TP = importlib.import_module('triposg.pipelines.pipeline_triposg')
        spec = importlib.util.spec_from_file_location('tripo_image_process', os.path.join(code, 'scripts', 'image_process.py'))      # не `scripts.*`: пакет `scripts` занят MV-Adapter
        self.prep = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.prep)
        self.cm = CM
        STATE['timings']['tp_import_s'] = round(time.time() - t_imp, 1)
        STATE['phase'] = 'weights'
        from huggingface_hub import snapshot_download
        t = time.time()
        wdir = snapshot_download(repo_id=TP_REPO, local_dir=os.path.join(os.environ.get('HF_HOME', '/data/hf'), 'TripoSG'))
        t_tp = time.time() - t
        info = super().load()                                                            # MV-Adapter: импорты, веса SDXL/адаптера, текстурный конвейер (на процессоре до задания)
        STATE['phase'] = 'to_gpu'
        t = time.time()
        self.tp = TP.TripoSGPipeline.from_pretrained(wdir).to('cuda', torch.float16)
        free_gpu()
        STATE['config']['triposg'] = {'dir': wdir, 'arch': arch, 'mem_after_warm': gpu_mem()}
        info.update({'triposg_weights_s': round(t_tp, 1), 'triposg_to_gpu_s': round(time.time() - t, 1), 'mem_after_warm': STATE['config']['triposg']['mem_after_warm']})
        return info

    def _tp_to(self, dev: str) -> None:
        if self.tp is not None:
            self.tp.to(dev)
            free_gpu()

    def generate(self, image, params: dict, path: str) -> dict:
        if params.get('texture_mesh'):                                                   # «краска»: готовая (почищенная) форма
            self._tp_to('cpu')
            m = super().generate(image, params, path)
            m['phase'] = 'paint'
            return m
        return self.shape(image, params, path)

    def shape(self, image, params: dict, path: str) -> dict:
        import numpy as np
        import torch
        trace: dict = {}
        self._trace = trace
        rss_reset = reset_rss_peak()
        stage: dict = {}
        t0 = [time.time()]

        def mem(name: str) -> None:
            trace[name] = mem_snapshot(reset_peak=True)

        def lap(name: str) -> None:
            torch.cuda.synchronize()
            stage[name] = round(time.time() - t0[0], 2)
            mem(name)
            t0[0] = time.time()
        mem('start')
        rgba = image.convert('RGBA')
        a = np.asarray(rgba.getchannel('A'))
        if not ((a < 13).mean() >= 0.01 and (a >= 243).mean() >= 0.01):                 # как `is_valid_alpha` апстрима: иначе он зовёт вырезку фона RMBG-1.4 (лицензия bria — не для нас)
            raise ValueError('вход без настоящей альфы: нужна вырезка (RGBA, ≥ 1 % прозрачных и ≥ 1 % непрозрачных пикселей)')
        work = os.path.join(OUT, f'_tp_{os.getpid()}_{int(time.time() * 1000)}')
        os.makedirs(work, exist_ok=True)
        try:
            png = os.path.join(work, 'in.png')
            rgba.save(png)
            if getattr(self, 'runner', None) is not None and not self.runner.offload:       # MVTEX_OFFLOAD=0: SDXL живёт на видеокарте — на время формы уводим на процессор
                self.runner._pipe_to('cpu')
                free_gpu()
            self._tp_to('cuda')
            lap('to_gpu')
            prepared = self.prep.prepare_image(png, bg_color=np.array([1.0, 1.0, 1.0]), rmbg_net=None)
            steps = int(params['tp_steps'] if params.get('tp_steps') is not None else TP_STEPS)
            guidance = float(params['tp_guidance'] if params.get('tp_guidance') is not None else TP_GUIDANCE)
            out = self.tp(image=prepared, generator=torch.Generator(device='cuda').manual_seed(int(params.get('seed', 42))), num_inference_steps=steps, guidance_scale=guidance).samples[0]
            v_raw, f_raw = out[0], out[1]
            if v_raw is None or f_raw is None or len(f_raw) == 0:
                raise ValueError('TripoSG не дал меш (DiffDMC вернул пусто — см. журнал воркера)')
            lap('triposg')
            fit = tp_fit_orient(v_raw, f_raw, rgba)
            v, c, s = tp_normalize(np.asarray(v_raw, dtype=np.float64) @ fit['R'].T)
            lap('orient')
            ov, of, ouv, cinfo = tp_cumesh_uv(v, f_raw, int(params.get('decimation_target', 500000)), self.cm, lambda x: torch.as_tensor(x, device='cuda'))
            lap('cumesh')
            mv_write_input_glb(path, ov, of, ouv)
            lap('write')
        finally:
            import shutil
            shutil.rmtree(work, ignore_errors=True)
        return {'mode': 'triposg_shape', 'phase': 'shape', 'stage_s': stage, 'steps': steps, 'guidance': guidance, 'raw_verts': int(len(v_raw)), 'raw_faces': int(len(f_raw)),
                'orient': {k: (v2 if k != 'R' else None) for k, v2 in fit.items() if k != 'R'}, 'cumesh': cinfo, 'peak_vram_gb': max([x.get('peak_allocated_gb', 0.0) for x in trace.values()] or [0.0]),
                'mem': trace, 'config': dict(STATE.get('config') or {}), **job_mem_metrics(trace, rss_reset)}


def _surface_samples(v, f, n: int, seed: int = 0):
    """n точек на поверхности (площадь-взвешенно) — для честного расстояния между поверхностями, а не между вершинами разной густоты."""
    import numpy as np
    v = np.asarray(v, dtype=np.float64)
    f = np.asarray(f, dtype=np.int64)
    a, b, c = v[f[:, 0]], v[f[:, 1]], v[f[:, 2]]
    area = np.linalg.norm(np.cross(b - a, c - a), axis=1) / 2.0
    tot = float(area.sum())
    if not tot > 0:
        return v[np.linspace(0, len(v) - 1, min(n, len(v))).astype(np.int64)]
    rng = np.random.default_rng(seed)
    idx = rng.choice(len(f), size=n, p=area / tot)
    r1, r2 = rng.random(n), rng.random(n)
    s = np.sqrt(r1)
    return (1 - s)[:, None] * a[idx] + (s * (1 - r2))[:, None] * b[idx] + (s * r2)[:, None] * c[idx]


def _nn_dist(x, y):
    """Расстояние от каждой точки x до ближайшей точки y (scipy, иначе кусками)."""
    import numpy as np
    try:
        from scipy.spatial import cKDTree
        return cKDTree(y).query(x)[0]
    except ImportError:
        out = np.empty(len(x))
        for i in range(0, len(x), 256):
            d2 = ((x[i:i + 256, None, :] - y[None, :, :]) ** 2).sum(-1)
            out[i:i + 256] = np.sqrt(d2.min(axis=1))
        return out


def shape_change_metrics(v_in, f_in, v_out, f_out, n: int = 30000) -> dict:
    """ОБЩАЯ для проб краски, которые меняют форму (supratex — ремеш, mvpainter — штатное упрощение): грани/вершины до и после и расстояние между ПОВЕРХНОСТЯМИ входной формы и выпуска (симметрично, по n точкам с каждой): макс, среднее, 99-й процентиль; в долях диагонали габарита входа.
    Форма меняться МОЖЕТ (ремеш), поэтому исключения нет — решает тот, кто читает замеры."""
    import numpy as np
    v_in = np.asarray(v_in, dtype=np.float64)
    diag = float(np.linalg.norm(v_in.max(axis=0) - v_in.min(axis=0)))
    if not diag > 0:
        raise ValueError('габарит входной формы нулевой')
    a = _surface_samples(v_in, f_in, n, 1)
    b = _surface_samples(v_out, f_out, n, 2)
    d = np.concatenate([_nn_dist(a, b), _nn_dist(b, a)])
    return {'faces_in': int(len(f_in)), 'faces_out': int(len(f_out)), 'verts_in': int(len(v_in)), 'verts_out': int(len(v_out)),
            'faces_ratio': round(len(f_out) / max(1, len(f_in)), 4), 'samples': int(n), 'diag': round(diag, 6),
            'hausdorff_rel': round(float(d.max()) / diag, 6), 'mean_rel': round(float(d.mean()) / diag, 6), 'p99_rel': round(float(np.percentile(d, 99)) / diag, 6)}


supra_shape_metrics = shape_change_metrics      # прежнее имя (SUPRA-Tex, T-20261119-06/5)


# ——— mvpainter: краска ГОТОВОЙ формы по MVPainter КАК ЕСТЬ (T-20261119-06/4) ———
# Источник — github.com/amap-cvlab/MV-Painter, коммит f714682 (source: external:github; основной код Apache-2.0; файлы с заголовком Tencent Non-Commercial — `mvpainter/differentiable_renderer/*`,
# `custom_rasterizer/**`, `utils.py` — только некоммерческое: для пробы допустимо; лицензия весов shaomq/MVPainter и lizb6626/IDArb не указана; Blender/bpy — GPL).
# Что делает апстрим, и мы его скрипты НЕ правим — запускаем подпроцессами из `MVPainter/` (обёртки — наши, внизу):
#   1) `infer_multiview.py`: Blender 4.2 рисует ортографические нормали и глубину формы (`scripts/blender_render_ortho.py`: `normalize_scene` :576-604 — габарит ×0,95/наибольшая сторона, центр в ноль),
#      диффузия (`MVPainter_Pipeline` + ControlNet, 75 шагов) даёт 6 видов 512² по фото (`result_1..6.png`), `blender.obj` — форма в этом кадре;
#   2) `infer_pbr.py` (по умолчанию): IDArb по видам даёт basecolor/metallic/roughness (`result_i_<карта>.png`);
#   3) `infer_paint.py:25` `reduce_mesh(... target_vertices=30000)`: ШТАТНОЕ УПРОЩЕНИЕ формы до 30 тыс. вершин → `blender_low.obj` (форма меняется законно — владелец 19.11, TG 2149/2150);
#      `mvpainter/bake_pipeline.py:173` `mesh_uv_wrap` (xatlas) строит свою развёртку, запекание видов в текстуру 1024², Blender собирает GLB (`scripts/blender_pbr_glb.py` для PBR).
# Мы повторяем последовательность команд `infer_paint.py` САМИ (у него `os.system` скрывает сбои, а bpy 3.6 из PyPI не ставится): упрощение и запекание идут в Blender 3.6 LTS, PBR-GLB — в Blender 4.2.9.
# Наше — только обёртки: `torch.load` на процессор (issue #13: 15 ГБ чекпойнт на видеокарту не помещается в 24 ГБ), чекпойнт `v29_25000.safetensors` вместо `.ckpt` 23,6 ГиБ (те же веса: ключи
# `unet.*`/`controlnet.*` — это `state_dict` без внешнего префикса `unet.`; строгая загрузка у апстрима отвергнет несовпадение), фото с рамкой как у `resize_foreground(0.85)`.
MVP_SIZE_MAX = 30000                                            # `infer_paint.py:25`
MVP_FRAME_OK = 0.02                                             # средняя дистанция вершин итога до формы входа, доля диагонали: больше — кадр итога не тот (`frame.ok=false`)
MVP_PATTERNS = ['model_index.json', 'feature_extractor_vae/*', 'scheduler/*', 'uc_text_emb.pt', 'uc_text_emb_2.pt', 'unet/*', 'vae/*', 'vision_encoder/*', 'vision_encoder_2/*', 'vision_processor/*']
MVP_PATTERNS_PBR = ['unet_pbr/*']
MVP_PATTERNS_IDARB = ['model_index.json', 'feature_extractor/*', 'scheduler/*', 'text_encoder/*', 'tokenizer/*', 'vae/*']

MVP_RUN_PY = r'''# обёртка: запускает скрипт апстрима как `python <скрипт>` (каталог скрипта = cwd первым в sys.path), с двумя заплатками загрузки весов (клон не правится)
import os
import runpy
import sys
script = sys.argv[1]
sys.argv = sys.argv[1:]
sys.path.insert(0, os.getcwd())
import torch
_orig_load = torch.load


def _load(f, *a, **k):
    if os.environ.get('MVP_LOAD_CPU', '1') != '0':
        k.setdefault('map_location', 'cpu')                  # issue #13: чекпойнт писался с видеокарты, torch.load без map_location кладёт его целиком на неё
    k.setdefault('weights_only', False)                      # torch 2.6: по умолчанию True, а их чекпойнт — не только тензоры
    if isinstance(f, (str, os.PathLike)) and str(f).endswith('.safetensors'):
        from safetensors.torch import load_file
        sd = load_file(str(f), device='cpu')
        return {'state_dict': {'unet.' + key: v for key, v in sd.items()}}      # формат .ckpt: их фильтр `"unet" in k` и срез `k[5:]` вернут ключи safetensors как есть
    return _orig_load(f, *a, **k)


torch.load = _load
if os.environ.get('MVP_CKPT', 'safetensors') == 'safetensors':
    import huggingface_hub
    _orig_dl = huggingface_hub.hf_hub_download

    def _dl(*a, **k):
        fn = k.get('filename')
        if fn and fn.endswith('v29_25000.ckpt'):
            k['filename'] = fn[:-len('.ckpt')] + '.safetensors'
        return _orig_dl(*a, **k)
    huggingface_hub.hf_hub_download = _dl
runpy.run_path(script, run_name='__main__')
'''
MVP_REDUCE_PY = r'''# внутри Blender 3.6: штатное упрощение апстрима (`infer_paint.py:25`), та же функция и те же аргументы
import os
import sys
root, obj, low, nv = sys.argv[sys.argv.index('--') + 1:][:4]
os.chdir(root)
sys.path.insert(0, root)
from scripts.remesh_reduce_blender_script import reduce_mesh
reduce_mesh(obj, target_vertices=int(nv), output_path=low)
'''
MVP_BAKE_PY = r'''# внутри Blender 3.6: их `scripts/blender_bake.py` как есть, но с аргументами без чужих ключей Blender
import runpy
import sys
a = sys.argv[sys.argv.index('--') + 1:]
sys.argv = [a[0]] + a[1:]
runpy.run_path(a[0], run_name='__main__')
'''


class MVPStageError(RuntimeError):
    """Стадия апстрима упала или не оставила ожидаемых файлов (их `os.system` такие сбои скрывает — мы проверяем сами). В тексте — хвост вывода (по нему `classify_cuda_error` отличает нехватку памяти от фатального сбоя)."""

    def __init__(self, msg: str, info: dict | None = None):
        super().__init__(msg)
        self.info = info or {}                                  # замеры упавшей стадии (секунды, пик памяти видеокарты) — в диагностику задания, чтобы при нехватке памяти пик был виден


def mvp_gpu_used_mib():
    """Занятая память видеокарты из драйвера (МиБ) или None (нет nvidia-smi — тест без видеокарты)."""
    d = nvidia_smi()
    return d.get('memory_used_mib') if d else None


def mvp_run_stage(name: str, cmd: list, cwd: str, env: dict | None = None, expect: tuple = (), timeout: float = 1800.0, smi=None, tail_n: int = 40) -> dict:
    """Одна стадия подпроцессом: секунды, пик занятой памяти видеокарты (опрос раз в секунду, отдельный поток), код выхода, хвост вывода; вывод идёт и в журнал контейнера.
    Упала (код ≠ 0, таймаут) или не оставила файлов из `expect` (шаблоны `*` — через glob) — `MVPStageError` с хвостом."""
    import collections
    import glob
    smi = smi or mvp_gpu_used_mib
    tail: collections.deque = collections.deque(maxlen=tail_n)
    peak: list = [None]
    stop = threading.Event()

    def sample():
        try:
            return smi()
        except Exception:  # noqa: BLE001 — замер памяти не должен ронять стадию
            return None

    base = sample()

    def poll() -> None:
        while not stop.is_set():
            v = sample()
            if v is not None:
                peak[0] = v if peak[0] is None else max(peak[0], v)
            stop.wait(1.0)
    th = threading.Thread(target=poll, daemon=True)
    th.start()
    t0 = time.time()
    p = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors='replace', bufsize=1)
    timed_out = []
    timer = threading.Timer(timeout, lambda: (timed_out.append(1), p.kill()))
    timer.start()
    try:
        for line in p.stdout:
            line = line.rstrip('\n')
            tail.append(line[-400:])
            print(f'[mvp:{name}] {line[-400:]}', flush=True)
        rc = p.wait()
    finally:
        timer.cancel()
        stop.set()
        th.join(3)
    info = {'name': name, 'rc': rc, 'seconds': round(time.time() - t0, 2), 'gpu_used_base_mib': base, 'gpu_peak_mib': peak[0], 'timed_out': bool(timed_out)}
    missing = [e for e in expect if not glob.glob(e)]
    if rc != 0 or missing:
        why = f'таймаут {timeout:.0f} с' if timed_out else f'код выхода {rc}'
        info['failed'] = True
        raise MVPStageError(f'стадия {name}: {why}' + (f'; нет файлов: {missing[:3]}' if missing else '') + '\n' + '\n'.join(list(tail)[-12:])[-1500:], info)
    info['tail'] = list(tail)[-3:]
    return info


def mvp_resize_foreground(image, ratio: float = 0.85):
    """Фото как у `resize_foreground(image, 0.85)` апстрима (`src/utils/infer_util.py:25-63`; он вызывается только без `--no_rembg`, а rembg и его загрузку весов нам не нужны — альфа у фото настоящая):
    рамка по альфа > 0 (последняя строка и столбец рамки отбрасываются, как у них), квадрат, поля до `1/ratio`."""
    import numpy as np
    from PIL import Image
    a = np.array(image.convert('RGBA'))
    ys, xs = np.where(a[..., 3] > 0)
    if ys.size == 0:
        raise ValueError('на фото нет предмета: альфа пустая')
    fg = a[ys.min():ys.max(), xs.min():xs.max()]
    if fg.shape[0] == 0 or fg.shape[1] == 0:
        fg = a[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    size = max(fg.shape[0], fg.shape[1])
    ph0, pw0 = (size - fg.shape[0]) // 2, (size - fg.shape[1]) // 2
    sq = np.pad(fg, ((ph0, size - fg.shape[0] - ph0), (pw0, size - fg.shape[1] - pw0), (0, 0)), mode='constant')
    new = int(sq.shape[0] / ratio)
    p0 = (new - size) // 2
    return Image.fromarray(np.pad(sq, ((p0, new - size - p0), (p0, new - size - p0), (0, 0)), mode='constant'))


def mvp_rotations() -> list:
    """24 поворота куба (знаковые перестановки осей, det = +1); первый — единичный."""
    import itertools
    import numpy as np
    out = [np.eye(3)]
    for perm in itertools.permutations(range(3)):
        for signs in itertools.product((1.0, -1.0), repeat=3):
            m = np.zeros((3, 3))
            for i, (j, sg) in enumerate(zip(perm, signs)):
                m[i, j] = sg
            if abs(np.linalg.det(m) - 1.0) < 1e-9 and not np.allclose(m, np.eye(3)):
                out.append(m)
    return out


def mvp_align_frame(v_out, p_ref, n: int = 6000, accept: float = MVP_FRAME_OK) -> tuple:
    """Вернуть вершины итога апстрима в кадр входа (куб `to_cube`). Теория: `blender.obj` лежит в кадре входного GLB (импорт glTF Y→Z и экспорт OBJ Z→Y взаимно обратны), меняются только масштаб ×0,95/габарит и
    сдвиг центра (`normalize_scene`), поворота нет. Значит достаточно подогнать габарит; но кадр проверяем ДАННЫМИ: средняя дистанция вершин итога до вершин входа (доля диагонали). Единичный поворот принимаем,
    пока она ≤ `accept`; иначе берём лучший из 24 поворотов куба. Возвращает (вершины в кадре входа, info: rotation, score_identity, score_chosen, top3, ok)."""
    import numpy as np
    from scipy.spatial import cKDTree
    v = np.asarray(v_out, dtype=np.float64)
    ref = np.asarray(p_ref, dtype=np.float64)
    lo_r, hi_r = ref.min(axis=0), ref.max(axis=0)
    diag = float(np.linalg.norm(hi_r - lo_r))
    ref_ext, ref_c = float((hi_r - lo_r).max()), (lo_r + hi_r) / 2.0
    tree = cKDTree(ref[np.linspace(0, len(ref) - 1, min(len(ref), 200000)).astype(np.int64)])
    idx = np.linspace(0, len(v) - 1, min(len(v), n)).astype(np.int64)

    def fit(rot):
        w = v @ rot.T
        lo, hi = w.min(axis=0), w.max(axis=0)
        return (w - (lo + hi) / 2.0) * (ref_ext / float((hi - lo).max())) + ref_c

    def score(w) -> float:
        return float(tree.query(w[idx])[0].mean()) / diag
    rots = mvp_rotations()
    s_id = score(fit(rots[0]))
    scored = [(s_id, 0)]
    best_i, best_s = 0, s_id
    if s_id > accept:
        scored = sorted((score(fit(r)), i) for i, r in enumerate(rots))
        best_s, best_i = scored[0]
    w = fit(rots[best_i])
    return w, {'rotation': 'identity' if best_i == 0 else f'cube_rot_{best_i}', 'score_identity': round(s_id, 6), 'score_chosen': round(best_s, 6),
               'top3': [[round(s, 6), i] for s, i in scored[:3]], 'ok': bool(best_s <= accept)}


class MVPRunner:
    """Стадии апстрима подпроцессами (см. шапку блока). `run_stage` подменяется в тестах."""

    def __init__(self, root: str, blender42: str, blender36: str, tools: str, env: dict, python: str | None = None, run_stage=None, timeout: float = 1800.0):
        self.root, self.blender42, self.blender36, self.tools, self.env = root, blender42, blender36, tools, env
        self.python = python or sys.executable
        self.run_stage = run_stage or mvp_run_stage
        self.timeout = timeout
        self.done: list = []                                    # замеры стадий этого задания по порядку (в том числе упавшей)

    def _stage(self, name: str, cmd: list, cwd: str, expect: tuple = ()) -> dict:
        try:
            info = self.run_stage(name, cmd, cwd, env=self.env, expect=expect, timeout=self.timeout)
        except MVPStageError as e:
            self.done.append({k: v for k, v in (e.info or {'name': name}).items() if k != 'tail'})      # упавшая стадия тоже в списке: её пик памяти нужен при нехватке видеопамяти
            raise
        self.done.append({k: v for k, v in info.items() if k != 'tail'})
        return info

    def _blender(self, binary: str, driver: str, args: list) -> list:
        return [binary, '--background', '-Y', '--python-exit-code', '1', '--python', driver, '--'] + [str(a) for a in args]

    def run(self, uid: str, work: str, params: dict) -> dict:
        """Вход: `work/in/glb/<uid>.glb` и `work/in/img/<uid>.png`. Выход: {'glb': путь, 'stages': [...], 'mv_dir': каталог с видами}."""
        j = os.path.join
        self.done = []
        steps, seed = int(params['steps']), int(params['seed'])
        reduce_on, pbr = bool(params['reduce']), bool(params['pbr'])
        mv_out = j(work, 'mv')
        mv_dir = j(mv_out, 'mvpainter')
        obj_dir = j(mv_dir, uid)
        res = j(work, 'res')
        py, root = self.python, self.root
        stages = [self._stage('multiview', [py, j(self.tools, 'mvp_run.py'), 'infer_multiview.py', '--input_glb_dir', j(work, 'in', 'glb'), '--input_img_dir', j(work, 'in', 'img'), '--output_dir', mv_out,
                                            '--geo_rotation', '-90', '--diffusion_steps', steps, '--seed', seed, '--no_rembg'], root,
                              tuple(j(obj_dir, f) for f in ['blender.obj'] + [f'result_{i}.png' for i in range(1, 7)]))]
        if pbr:
            stages.append(self._stage('pbr_views', [py, j(self.tools, 'mvp_run.py'), 'infer_pbr.py', '--mv_res_dir', mv_dir], root,
                                      tuple(j(obj_dir, f'result_{i}_{m}.png') for i in range(1, 7) for m in ('basecolor', 'metallic', 'roughness'))))
        low = j(obj_dir, 'blender_low.obj')
        if reduce_on:
            stages.append(self._stage('reduce', self._blender(self.blender36, j(self.tools, 'mvp_reduce.py'), [root, j(obj_dir, 'blender.obj'), low, MVP_SIZE_MAX]), root, (low,)))
        else:
            import shutil
            shutil.copy(j(obj_dir, 'blender.obj'), low)             # `infer_paint.py:17` пропускает упрощение, если `blender_low.obj` уже есть
        bake_cwd = j(root, 'mvpainter')
        if not pbr:
            stages.append(self._stage('bake', [py, 'bake_pipeline.py', '--input_dir', mv_dir, '--save_dir', j(res, 'glbs'), '--offset', '0'], bake_cwd, (j(res, 'glbs', '*.glb'),)))
            return {'glb': self._pick(j(res, 'glbs'), uid), 'stages': stages, 'mv_dir': obj_dir}
        for kind in ('basecolor', 'metallic', 'roughness'):
            stages.append(self._stage(f'bake_{kind}', [py, 'bake_pipeline.py', '--input_dir', mv_dir, '--save_dir', j(res, kind), '--offset', '0', '--suffix', f'_{kind}'], bake_cwd, (j(res, kind, '*.glb'),)))
            stages.append(self._stage(f'obj_{kind}', self._blender(self.blender36, j(self.tools, 'mvp_bake.py'), [j(root, 'scripts', 'blender_bake.py'), '--input_dir', j(res, kind), '--save_dir', j(res, kind + '_bake')]),
                                      j(root, 'scripts'), (j(res, kind + '_bake', '*.obj'),)))
        stages.append(self._stage('pbr_glb', [self.blender42, '--background', '-Y', '--python-exit-code', '1', '--python', j('scripts', 'blender_pbr_glb.py'), '--', '--basecolor_dir', j(res, 'basecolor_bake'),
                                              '--metallic_dir', j(res, 'metallic_bake'), '--roughness_dir', j(res, 'roughness_bake'), '--output_dir', j(res, 'combine_pbr')], root, (j(res, 'combine_pbr', '*.glb'),)))
        return {'glb': self._pick(j(res, 'combine_pbr'), uid), 'stages': stages, 'mv_dir': obj_dir}

    @staticmethod
    def _pick(folder: str, uid: str) -> str:
        want = os.path.join(folder, uid + '.glb')
        if os.path.exists(want):
            return want
        found = sorted(n for n in os.listdir(folder) if n.endswith('.glb'))
        if len(found) != 1:
            raise MVPStageError(f'в {folder} ожидался один GLB, найдено: {found}')
        return os.path.join(folder, found[0])


def mvp_flag(v, default: bool) -> bool:
    if v is None or v == '':
        return default
    if isinstance(v, str):
        return v.strip().lower() not in ('0', 'false', 'no', 'off')
    return bool(v)


def mvp_texture_on_shape(runner, mesh, image, params: dict, hooks: dict | None = None, work: str | None = None) -> tuple:
    """Покрасить ГОТОВУЮ форму `mesh` (trimesh, кадр GLB: Y вверх) по фото `image` (RGBA, настоящая альфа). `runner.run(uid, work, {steps, seed, reduce, pbr})` — стадии апстрима (`MVPRunner`),
    возвращает {'glb', 'stages', 'mv_dir'}. Форма меняется ЗАКОННО (штатное упрощение до 30 тыс. вершин, развёртка xatlas): итог — GLB апстрима, возвращённый в кадр и масштаб входа, + замеры упрощения
    (`shape_change_metrics`, общая с supratex). Возвращает (trimesh, замеры)."""
    import tempfile
    import numpy as np
    import trimesh
    hk = {'sync': lambda: None, 'free': lambda: None, 'mem': lambda name: None, **(hooks or {})}
    stage: dict = {}
    t = time.time()

    def lap(name: str) -> None:
        hk['sync']()
        nonlocal t
        stage[name] = round(time.time() - t, 2)
        hk['free']()
        hk['mem'](name)
        t = time.time()

    verts = np.asarray(mesh.vertices, dtype=np.float64)
    faces = np.asarray(mesh.faces, dtype=np.int64)
    steps = int(params['mvp_steps'] if params.get('mvp_steps') is not None else 75)
    if not 1 <= steps <= 150:
        raise ValueError('mvp_steps: 1..150')
    reduce_on, pbr = mvp_flag(params.get('mvp_reduce'), True), mvp_flag(params.get('mvp_pbr'), True)
    seed = int(params.get('seed', 12))
    yaw_param = params.get('mvp_yaw')
    fit = mv_fit_yaw(verts, faces, image, force=None if yaw_param in (None, '', 'auto') else yaw_param)
    lap('fit_yaw')
    work = work or tempfile.mkdtemp(prefix='mvp-', dir=OUT if os.path.isdir(OUT) else None)
    uid = f'm{int(time.time() * 1000)}'                                          # без «glb» в имени: infer_multiview.py заменяет эту подстроку при поиске PNG
    os.makedirs(os.path.join(work, 'in', 'glb'), exist_ok=True)
    os.makedirs(os.path.join(work, 'in', 'img'), exist_ok=True)
    p, c, s, R = to_cube(verts, fit['yaw_deg'])
    mv_write_input_glb(os.path.join(work, 'in', 'glb', uid + '.glb'), p, faces)
    mvp_resize_foreground(image, 0.85).save(os.path.join(work, 'in', 'img', uid + '.png'))
    lap('write_input')
    out = runner.run(uid, work, {'steps': steps, 'seed': seed, 'reduce': reduce_on, 'pbr': pbr})
    lap('upstream')
    sc = trimesh.load(out['glb'], force='scene', process=False)
    parts = sc.dump()
    if not parts:
        raise RuntimeError('апстрим вернул GLB без мешей')
    back = parts[0] if len(parts) == 1 else trimesh.util.concatenate(parts)
    aligned, frame = mvp_align_frame(np.asarray(back.vertices, dtype=np.float64), p)
    v_final = from_cube(aligned, c, s, R)
    lap('frame')
    final = back.copy()
    final.vertices = v_final
    simp = shape_change_metrics(verts, faces, v_final, np.asarray(final.faces))
    lap('metrics')
    tex = getattr(getattr(final.visual, 'material', None), 'baseColorTexture', None)
    thumb = None
    try:
        import base64
        from PIL import Image
        ims = [Image.open(os.path.join(out['mv_dir'], f'result_{i}.png')).convert('RGB') for i in range(1, 7)]
        h = 256
        ims = [im.resize((max(1, im.width * h // im.height), h), Image.Resampling.LANCZOS) for im in ims]
        strip = Image.new('RGB', (sum(im.width for im in ims), h))
        x = 0
        for im in ims:
            strip.paste(im, (x, 0))
            x += im.width
        buf = io.BytesIO()
        strip.save(buf, format='JPEG', quality=80)
        thumb = base64.b64encode(buf.getvalue()).decode()
    except Exception:  # noqa: BLE001 — миниатюра видов нужна для разбора, не для результата
        thumb = None
    stages = out['stages']
    return final, {'fit': fit, 'frame': frame, 'simplify': simp, 'stage_s': stage, 'upstream_stages': [{k: v for k, v in x.items() if k != 'tail'} for x in stages],
                   'upstream_s': round(sum(x['seconds'] for x in stages), 2), 'steps': steps, 'seed': seed, 'reduce': reduce_on, 'pbr': pbr, 'tex_in_size': list(tex.size) if tex is not None else None,
                   'mesh_tris': int(len(faces)), 'mesh_verts': int(len(verts)), 'views_jpeg_b64': thumb}


class MVPainterBackend:
    """`mvpainter`: форма TRELLIS.2 (готовый GLB, `<job>.mesh.glb`) + краска MVPainter по одному фото, КАК У АВТОРОВ (штатное упрощение до 30 тыс. вершин; PBR через IDArb). Образ — `Dockerfile.mvpainter`.
    Прогрев — только ДОКАЧКА весов в кэш Hugging Face (≈ 28 ГиБ): модели грузит каждый подпроцесс стадии заново (в память процессора, потом на видеокарту) — цена нескольких минут на задание. Родительский процесс
    видеокарту не трогает (CUDA живёт только в подпроцессах). Переменные: `MVP_CKPT` (safetensors|ckpt, по умолчанию safetensors 14 ГиБ), `MVP_LOAD_CPU` (1), `MVP_STAGE_TIMEOUT` (1800 с), `MVP_PREFETCH` (1)."""
    name = 'mvpainter'
    runner = None
    _trace: dict = {}

    def load(self) -> dict:
        root = os.environ.get('MVPAINTER_DIR', '/opt/MV-Painter/MVPainter')
        b42 = os.environ.get('BLENDER42', '/opt/MV-Painter/blender-4.2.9-linux-x64/blender')
        b36 = os.environ.get('BLENDER36', '/opt/blender-3.6.9-linux-x64/blender')
        for what, pth in (('код MV-Painter', root), ('Blender 4.2', b42), ('Blender 3.6', b36)):
            if not os.path.exists(pth):
                raise RuntimeError(f'в образе нет: {what} ({pth}) — собран ли образ по Dockerfile.mvpainter?')
        tools = os.environ.get('MVP_TOOLS', '/tmp/mvp_tools')
        for fname, body in (('mvp_run.py', MVP_RUN_PY), ('mvp_reduce.py', MVP_REDUCE_PY), ('mvp_bake.py', MVP_BAKE_PY)):
            atomic_write(os.path.join(tools, fname), body.encode())
        hf = os.environ.get('HF_HOME', '/data/hf')
        env = dict(os.environ, HF_HOME=hf, PYTHONUNBUFFERED='1', TOKENIZERS_PARALLELISM='false', PYTORCH_CUDA_ALLOC_CONF=os.environ.get('MVP_ALLOC_CONF', 'expandable_segments:False'),
                   MVP_LOAD_CPU=os.environ.get('MVP_LOAD_CPU', '1'), MVP_CKPT=os.environ.get('MVP_CKPT', 'safetensors'))
        ckpt = env['MVP_CKPT']
        STATE['config'] = {'ckpt': ckpt, 'load_cpu': env['MVP_LOAD_CPU'], 'hf_home': hf, 'tools': tools, 'blender42': b42, 'blender36': b36,
                           'debug_env': {k: os.environ.get(k) for k in ('CUDA_LAUNCH_BLOCKING', 'TORCH_SHOW_CPP_STACKTRACES')}}
        print('[mvp] конфиг:', json.dumps(STATE['config'], ensure_ascii=False), flush=True)
        STATE['phase'] = 'weights'
        t = time.time()
        if os.environ.get('MVP_PREFETCH', '1') != '0':
            from huggingface_hub import snapshot_download
            snapshot_download('shaomq/MVPainter', allow_patterns=MVP_PATTERNS + MVP_PATTERNS_PBR + [f'unet_w_controlnet/v29_25000.{"safetensors" if ckpt == "safetensors" else "ckpt"}'])
            snapshot_download('lizb6626/IDArb', allow_patterns=MVP_PATTERNS_IDARB)
        t_w = time.time() - t
        self.runner = MVPRunner(root, b42, b36, tools, env, timeout=float(os.environ.get('MVP_STAGE_TIMEOUT', '1800')))
        STATE['phase'] = 'to_gpu'
        return {'weights_s': round(t_w, 1), 'weights_gb': dir_gb(hf)}

    def generate(self, image, params: dict, path: str) -> dict:
        if not params.get('texture_mesh'):
            raise ValueError('mvpainter красит готовую форму: нужен --texture-mesh <clean.glb>')
        import shutil
        import trimesh
        trace: dict = {}
        self._trace = trace
        t = time.time()
        sc = trimesh.load(os.path.join(JOBS_DIR, params['job_id'] + '.mesh.glb'), force='scene')
        parts = sc.dump()
        if not parts:
            raise ValueError('в GLB формы нет мешей')
        mesh = parts[0] if len(parts) == 1 else trimesh.util.concatenate(parts)
        load_s = round(time.time() - t, 2)
        work = os.path.join(OUT, f'_mvp_{os.getpid()}_{int(time.time() * 1000)}')
        os.makedirs(work, exist_ok=True)
        try:
            final, m = mvp_texture_on_shape(self.runner, mesh, image.convert('RGBA'), params, {'mem': lambda name: trace.__setitem__(name, nvidia_smi())}, work)
        finally:
            shutil.rmtree(work, ignore_errors=True)
            shutil.rmtree(os.path.join(self.runner.root, 'render_temp'), ignore_errors=True)       # кэш видов апстрима (`render_temp/<uid>` относительно cwd) — убираем
        final.export(path)
        m['stage_s']['load_shape'] = load_s
        peaks = [x.get('gpu_peak_mib') or 0 for x in m['upstream_stages']]
        m.update({'mode': 'mvpainter', 'peak_vram_gb': round(max(peaks or [0]) / 1024, 3), 'peak_vram_source': 'nvidia-smi memory.used (драйвер, вся карта)', 'mem': trace, 'config': dict(STATE.get('config') or {})})
        return m

    def on_error(self, e: BaseException) -> dict:
        """Разбор упавшего задания: тип ошибки CUDA по тексту (включая хвост вывода стадии). `fatal` — воркер «сломан», драйвер гасит группу; `oom` — подпроцесс уже умер, память свободна."""
        kind = classify_cuda_error(e)
        stages = list(getattr(self.runner, 'done', None) or [])
        if isinstance(e, MVPStageError) and e.info and not any(x.get('name') == e.info.get('name') and x.get('failed') for x in stages):
            stages.append({k: v for k, v in e.info.items() if k != 'tail'})
        peaks = [x.get('gpu_peak_mib') or 0 for x in stages]
        return {'kind': kind, 'fatal': kind == 'fatal', 'gpu': nvidia_smi(), 'stage_mem': dict(self._trace), 'upstream_stages': stages, 'peak_vram_gb': round(max(peaks or [0]) / 1024, 3),
                'failed_stage': next((x.get('name') for x in stages if x.get('failed')), None), 'config': STATE.get('config')}


# ——— SUPRA-Tex КАК ЕСТЬ (T-20261119-06/5): фото → Qwen-Image-2.1 (альбедо + карта материала) → генератор SUPRA красит ФОРМУ и сам выпускает GLB ———
# Что апстрим (SUPRA-Tex cee4435) делает с формой — читать так (файл:строка в `/opt/SUPRA-Tex`, проверено по клону 19.11):
#   • `texturing.py` принимает меш в кубе [−0,5; 0,5]³ (`supratex/inference/pipeline.py:252` `_shape`, `aabb=[[-.5,-.5,-.5],[.5,.5,.5]]`, сетка `RESOLUTION`=1024);
#   • выпуск `pipeline.py:350` `_export` → `mesh_export.py` `to_glb(remesh=True, remesh_band=1, remesh_project=0, decimation_target=500000)`: заделка дыр, РЕМЕШ двойными контурами на сетке 1024
#     (`mesh_export.py` ≈ 205-225), упрощение до `decimation_target` граней, НОВАЯ развёртка (`uv_unwrap` ≈ 239), запекание 4096². Значит, форма, грани И развёртка МЕНЯЮТСЯ, UV входа не сохраняется;
#   • в конце `to_glb` обменивает оси (x,y,z) → (x,z,−y), `_export` применяет M=[[−1,0,0],[0,0,−1],[0,−1,0]]: вместе (x,y,z) → (−x,y,−z) = поворот на 180° вокруг Y кадра куба. Мы не верим этому на слово:
#     перебираем кадры-кандидаты (`SUPRA_FRAMES`), берём тот, где расстояние к входной форме наименьшее, и пишем его имя в замеры (`out_frame`) — ошибка предположения видна в цифрах;
#   • плавающие куски (`remove_floaters`) трогаются ТОЛЬКО с флагом — мы его не передаём; грани входа до экспорта не меняются.
# Поэтому здесь НЕТ проверки «форма не изменилась» (как у mvadapter-i2tex): вместо неё в замеры идут грани до/после и расстояние Хаусдорфа к исходной форме (макс/среднее/99-й процентиль, в долях диагонали).
SUPRA_REPO = 'supra3d/supra-tex'
SUPRA_REV = '1bc02eb969a8ed0f1418c2bbe1e409a8481f834c'
SUPRA_PATTERNS = ['completion/config.json', 'completion/partial_normalization.json', 'completion/denoiser_step0030000.safetensors', 'completion/LICENSE', 'material/*']
SUPRA_PINS = {                      # зеркало `configs/pipeline.json` апстрима (`external_models`); при старте читаем сам файл, это — запас
    'qwen-base': {'repo_id': 'Qwen/Qwen-Image-2.1', 'revision': 'd26bb61231c349cf6b7896fa83353113880e1ba3', 'allow_patterns': ['processor/*', 'vae/*', 'text_encoder/*', 'transformer/*', 'LICENSE*', 'README.md']},
    'moge2': {'repo_id': 'Ruicheng/moge-2-vitl-normal', 'revision': 'cb0e8bbd6b1e243589717c78e750b1ba4c093acf', 'allow_patterns': ['model.pt', 'README.md', 'LICENSE*']},
    'vae': {'repo_id': 'microsoft/TRELLIS.2-4B', 'revision': 'af44b45f2e35a493886929c6d786e563ec68364d',
            'allow_patterns': [f'ckpts/{s}_next_dc_f16c32_fp16.{e}' for s in ('shape_enc', 'tex_enc', 'shape_dec', 'tex_dec') for e in ('json', 'safetensors')]},
}
SUPRA_ENV = {'PYTHONNOUSERSITE': '1', 'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1', 'FLEX_GEMM_USE_AUTOTUNE_CACHE': '0', 'FLEX_GEMM_AUTOSAVE_AUTOTUNE_CACHE': '0'}
SUPRA_FRAMES = ('identity', 'rot_y_180', 'swap_xz', 'unswap_xz')      # как вернуть вершины выпуска в кадр куба (до `from_cube`)
SUPRA_STAGE_TIMEOUT = 2400            # секунд на стадию (фронт и текстурирование); на 3090 весь прогон — 665 с, на 4090 с докачкой ядер — до нескольких раз дольше


class SupraStageError(RuntimeError):
    """Стадия SUPRA (подпроцесс) упала: в тексте — код выхода и хвост журнала (по нему `classify_cuda_error` отличает фатальный сбой CUDA от нехватки памяти)."""


def supra_manifest(sdir: str) -> dict:
    """Пины внешних весов: из `configs/pipeline.json` клона апстрима, нет файла — зеркало `SUPRA_PINS`. Возвращает {qwen-base, moge2, vae: {repo_id, revision, allow_patterns}}."""
    try:
        ext = json.load(open(os.path.join(sdir, 'configs', 'pipeline.json'), encoding='utf-8'))['external_models']
        return {k: {kk: ext[k][kk] for kk in ('repo_id', 'revision', 'allow_patterns')} for k in SUPRA_PINS}
    except (OSError, KeyError, ValueError):
        return {k: dict(v) for k, v in SUPRA_PINS.items()}


def supra_frame_candidates(v_out):
    """Вершины выпуска → кадр куба: словарь {имя: массив}. Имена — `SUPRA_FRAMES`."""
    import numpy as np
    o = np.asarray(v_out, dtype=np.float64)
    return {'identity': o, 'rot_y_180': o @ rot_y(180).T, 'swap_xz': np.stack([o[:, 0], o[:, 2], -o[:, 1]], axis=1), 'unswap_xz': np.stack([o[:, 0], -o[:, 2], o[:, 1]], axis=1)}


def supra_pick_frame(v_out, v_ref_cube, max_n: int = 20000) -> tuple:
    """Какой кадр-кандидат лучше всего накладывает выпуск на входную форму в кубе (по расстоянию Хаусдорфа вершин). → (имя, вершины в кубе, {имя: расстояние})."""
    cands = supra_frame_candidates(v_out)
    dist = {k: hausdorff_vertices(v, v_ref_cube, max_n) for k, v in cands.items()}
    best = min(SUPRA_FRAMES, key=lambda k: dist[k])
    return best, cands[best], {k: round(float(x), 6) for k, x in dist.items()}


def supra_shift(arr, dx: int, dy: int, fill):
    """Сдвиг картинки/карты на целые пиксели: содержимое уходит вправо на dx и вниз на dy, пустое место — `fill`; размер не меняется."""
    import numpy as np
    a = np.asarray(arr)
    out = np.full_like(a, fill)
    h, w = a.shape[:2]
    if abs(dx) >= w or abs(dy) >= h:
        return out
    ys0, ys1 = max(0, dy), min(h, h + dy)
    xs0, xs1 = max(0, dx), min(w, w + dx)
    out[ys0:ys1, xs0:xs1] = a[ys0 - dy:ys1 - dy, xs0 - dx:xs1 - dx]
    return out


def supra_find_case(root: str) -> str:
    """Папка с результатом фронта (condition_rgba.png, camera.json, albedo.png, mra.png): сама `root` или подпапка на один уровень вглубь (куда апстрим кладёт по `--key`)."""
    need = ('condition_rgba.png', 'camera.json', 'albedo.png', 'mra.png')
    for d in [root] + sorted(os.path.join(root, x) for x in os.listdir(root) if os.path.isdir(os.path.join(root, x))):
        if all(os.path.isfile(os.path.join(d, n)) for n in need):
            return d
    raise SupraStageError(f'фронт SUPRA не оставил {need} ни в {root}, ни в подпапках')


def supra_prepare_case(case: str, fit: dict) -> dict:
    """Подгонка наблюдения под НАШУ форму: фото и обе карты сдвигаются на целые пиксели (доли кадра tx, ty из `fit_photo`; `image_depth.npy` — с NaN на пустом месте), `camera.json` получает
    `mesh_scale` из подгонки. Масштаб фото не трогаем (как у pixal3d-tex). Возвращает {dx_cond, dy_cond, dx_map, dy_map, mesh_scale}."""
    import numpy as np
    from PIL import Image
    tx, ty = float(fit.get('tx', 0.0)), float(fit.get('ty', 0.0))
    info = {}
    cond = Image.open(os.path.join(case, 'condition_rgba.png')).convert('RGBA')
    dxc, dyc = int(round(tx * cond.width)), int(round(ty * cond.height))
    Image.fromarray(supra_shift(np.asarray(cond), dxc, dyc, 0)).save(os.path.join(case, 'condition_rgba.png'))
    rgb = os.path.join(case, 'condition_rgb.png')
    if os.path.isfile(rgb):
        im = np.asarray(Image.open(rgb).convert('RGB'))
        Image.fromarray(supra_shift(im, dxc, dyc, 0)).save(rgb)
    dxm = dym = 0
    for name in ('albedo.png', 'mra.png'):
        im = Image.open(os.path.join(case, name))
        dxm, dym = int(round(tx * im.width)), int(round(ty * im.height))
        Image.fromarray(supra_shift(np.asarray(im), dxm, dym, 0)).save(os.path.join(case, name))
    dp = os.path.join(case, 'image_depth.npy')
    if os.path.isfile(dp):
        d = np.load(dp, allow_pickle=False).astype(np.float32)
        np.save(dp, supra_shift(d, dxc, dyc, np.nan))
    cj = os.path.join(case, 'camera.json')
    cam = json.load(open(cj, encoding='utf-8'))
    cam['mesh_scale'] = float(fit.get('mesh_scale', cam.get('mesh_scale', 1.0)))
    atomic_write(cj, json.dumps(cam).encode())
    info.update(dx_cond=dxc, dy_cond=dyc, dx_map=dxm, dy_map=dym, mesh_scale=cam['mesh_scale'])
    return info


def supra_texture_on_shape(runner, mesh, image, params: dict, hooks: dict | None = None, work: str | None = None, out_path: str | None = None) -> tuple:
    """Покрасить нашу форму `mesh` (trimesh, кадр GLB: Y вверх) по фото `image` (RGBA, настоящая альфа) пайплайном SUPRA-Tex. `runner`: `frontend(photo_png, out_dir) → dict замеров`
    и `texturing(case_dir, out_glb, params) → dict замеров` (подпроцессы апстрима; `SupraRunner`). Возвращает (trimesh выпуска В КАДРЕ ВХОДНОЙ ФОРМЫ — вершины возвращены из куба, грани и UV — как их сделал SUPRA, замеры)."""
    import tempfile
    import numpy as np
    import trimesh
    hk = {'sync': lambda: None, 'free': lambda: None, 'mem': lambda name: None, **(hooks or {})}
    stage: dict = {}
    t = time.time()

    def lap(name: str) -> None:
        nonlocal t
        stage[name] = round(time.time() - t, 2)
        hk['mem'](name)
        t = time.time()

    verts = np.asarray(mesh.vertices, dtype=np.float64)
    faces = np.asarray(mesh.faces, dtype=np.int64)
    work = work or tempfile.mkdtemp(prefix='supra-', dir=OUT if os.path.isdir(OUT) else None)
    photo = os.path.join(work, 'photo.png')
    image.convert('RGBA').save(photo)
    fdir = os.path.join(work, 'front')
    os.makedirs(fdir, exist_ok=True)
    lap('prepare')
    front = runner.frontend(photo, fdir)
    lap('material')
    case = supra_find_case(fdir)
    cam = json.load(open(os.path.join(case, 'camera.json'), encoding='utf-8'))
    fov, dist = float(cam['camera_angle_x']), float(cam['distance'])
    from PIL import Image
    cond = Image.open(os.path.join(case, 'condition_rgba.png')).convert('RGBA')
    fit = fit_photo(verts, faces, cond, fov, dist, float(cam.get('mesh_scale', 1.0)))
    lap('fit')
    shift = supra_prepare_case(case, fit)
    p, c, s, R = to_cube(verts, fit['yaw_deg'], fit['pitch_deg'])
    np.savez(os.path.join(case, 'geometry.npz'), verts=p.astype(np.float32), faces=faces.astype(np.int32))
    lap('write_case')
    glb = os.path.join(work, 'supra.glb')
    tex = runner.texturing(case, glb, params)
    lap('texturing')
    back = trimesh.load(glb, force='mesh', process=False)
    v_out = np.asarray(back.vertices, dtype=np.float64)
    frame, v_cube, frame_dist = supra_pick_frame(v_out, p)
    v_final = from_cube(v_cube, c, s, R)
    shape = supra_shape_metrics(verts, faces, v_final, np.asarray(back.faces))
    shape.update(out_frame=frame, frame_dist=frame_dist)
    lap('metrics')
    back.vertices = v_final
    tex_img = getattr(getattr(back.visual, 'material', None), 'baseColorTexture', None)
    if tex_img is None:
        raise RuntimeError('SUPRA вернул GLB без текстуры')
    return back, {'fit': fit, 'shift': shift, 'shape': shape, 'stage_s': stage, 'front': front, 'texturing': tex, 'camera': {'fov': fov, 'distance': dist},
                  'tex_size': list(tex_img.size), 'observation_iou': tex.get('observation_iou'), 'mesh_tris': int(len(faces)), 'mesh_verts': int(len(verts))}


def run_logged(cmd: list, env: dict, cwd: str | None, timeout: int, log_path: str, poll_s: float = 2.0) -> dict:
    """Подпроцесс стадии: журнал в файл, пик занятой видеопамяти (по `nvidia-smi`, то есть всех процессов карты) и пик памяти группы (cgroup) — опросом раз в `poll_s`; пик RSS детей — `getrusage`.
    → {rc, s, peak_vram_mib, peak_cgroup_gb, child_maxrss_gb, tail}. Не ноль или таймаут — `SupraStageError` с хвостом журнала (нужен классификатору ошибок CUDA)."""
    import resource
    stop = threading.Event()
    peaks = {'vram': 0, 'cg': 0.0}

    def watch() -> None:
        while not stop.wait(poll_s):
            peaks['vram'] = max(peaks['vram'], int(nvidia_smi().get('memory_used_mib') or 0))
            peaks['cg'] = max(peaks['cg'], float(cgroup_gb().get('current') or 0.0))
    th = threading.Thread(target=watch, daemon=True)
    r0 = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    t0 = time.time()
    th.start()
    rc, timed_out = None, False
    try:
        with open(log_path, 'wb') as lf:
            pr = subprocess.Popen(cmd, env=env, cwd=cwd, stdout=lf, stderr=subprocess.STDOUT)
            try:
                rc = pr.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                pr.terminate()
                try:
                    pr.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    pr.kill()
                    pr.wait()
                rc = pr.returncode
    finally:
        stop.set()
        th.join(timeout=5)
    try:
        tail = open(log_path, 'rb').read()[-3000:].decode('utf-8', 'replace')
    except OSError:
        tail = ''
    r1 = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    res = {'rc': rc, 's': round(time.time() - t0, 1), 'peak_vram_mib': peaks['vram'], 'peak_cgroup_gb': round(peaks['cg'], 2),
           'child_maxrss_gb': round(max(r0, r1) / 2 ** 20, 2), 'tail': tail[-600:]}
    if timed_out or rc != 0:
        why = f'таймаут {timeout} с' if timed_out else f'код выхода {rc}' + (' (убит, вероятно по памяти группы)' if rc == -9 else '')
        raise SupraStageError(f'{os.path.basename(cmd[1]) if len(cmd) > 1 else cmd[0]}: {why}; хвост журнала: {tail[-1500:]}')
    return res


class SupraRunner:
    """Две стадии апстрима подпроцессами (`/opt/SUPRA-Tex`): фронт (MoGe-2 + Qwen-Image-2.1 → камера, альбедо, карта материала) и `texturing.py` (генератор + выпуск GLB)."""

    def __init__(self, sdir: str, paths: dict, work_log: str | None = None, run=run_logged, python: str | None = None):
        self.sdir, self.paths, self.run, self.python = sdir, paths, run, python or sys.executable
        self.work_log = work_log or OUT

    def _env(self) -> dict:
        env = dict(os.environ)
        env.update(SUPRA_ENV)
        env['PYTHONPATH'] = os.pathsep.join([self.sdir] + ([env['PYTHONPATH']] if env.get('PYTHONPATH') else []))
        env.setdefault('PYTORCH_CUDA_ALLOC_CONF', 'expandable_segments:False')
        env.pop('HF_TOKEN', None)                                  # токен подпроцессам не нужен (всё скачано заранее) и в их журнал не должен попасть
        return env

    def frontend(self, photo: str, out_dir: str) -> dict:
        cmd = [self.python, '-m', 'supratex.frontend.pipeline', '--input', photo, '--output', out_dir, '--use-input-alpha', '--moge-model', self.paths['moge'],
               '--material-base', self.paths['qwen'], '--material-model', self.paths['material'], '--local-files-only', '--attention', 'sdpa', '--low-vram']
        return self.run(cmd, self._env(), self.sdir, SUPRA_STAGE_TIMEOUT, os.path.join(self.work_log, 'supra_front.log'))

    def texturing(self, case: str, out_glb: str, params: dict) -> dict:
        ts = int(params['supra_texture_size'] if params.get('supra_texture_size') is not None else 4096)
        dec = int(params['supra_decimation'] if params.get('supra_decimation') is not None else 500000)
        cmd = [self.python, os.path.join(self.sdir, 'texturing.py'), '--pretrained', self.paths['completion'], '--trellis-root', self.paths['vae'], '--local-files-only',
               '--input-dir', case, '--output', out_glb, '--texture-size', str(ts), '--decimation-target', str(dec), '--seed', str(int(params.get('seed', 42))),
               '--attention', 'sdpa', '--low-vram']
        if params.get('supra_refine'):
            cmd.append('--refine')
        res = self.run(cmd, self._env(), self.sdir, SUPRA_STAGE_TIMEOUT, os.path.join(self.work_log, 'supra_tex.log'))
        import re
        m = re.search(r'Observation: silhouette IoU ([0-9.]+)', res.get('tail', '') + _read_log(os.path.join(self.work_log, 'supra_tex.log')))
        res['observation_iou'] = float(m.group(1)) if m else None
        res.update(texture_size=ts, decimation_target=dec, refine=bool(params.get('supra_refine')))
        return res


def _read_log(path: str) -> str:
    try:
        return open(path, 'rb').read().decode('utf-8', 'replace')
    except OSError:
        return ''


class SupraTexBackend:
    """`supratex`: наша форма (готовый GLB, `<job>.mesh.glb`) + RGBA-фото → краска SUPRA-Tex КАК ЕСТЬ (с Qwen-Image-2.1). Образ — `Dockerfile.supratex` (код в /opt/SUPRA-Tex, веса ≈ 43 ГиБ докачиваются
    на старте по закреплённым ревизиям: Qwen-Image-2.1 ≈ 31 ГиБ, дополнение SUPRA 7,8, VAE TRELLIS.2 3,1, MoGe-2 1,2, адаптер материала 0,13). GPU трогают только подпроцессы; сам воркер видеокарту не занимает
    (замеры памяти — `nvidia-smi` и cgroup). Фатальный сбой CUDA в подпроцессе (`SupraStageError` с маркерами) — воркер «сломан», как у остальных."""
    name = 'supratex'
    runner = None
    _trace: dict = {}

    def load(self) -> dict:
        sdir = os.environ.get('SUPRATEX_DIR', '/opt/SUPRA-Tex')
        STATE['phase'] = 'weights'
        man = supra_manifest(sdir)
        from huggingface_hub import snapshot_download
        t_all = time.time()
        sizes, secs = {}, {}

        def get(key: str, repo: str, rev: str, patterns: list) -> str:
            t = time.time()
            path = snapshot_download(repo_id=repo, revision=rev, allow_patterns=patterns)
            secs[key] = round(time.time() - t, 1)
            sizes[key] = dir_gb(path)
            print(f'[supra] {key}: {repo}@{rev[:8]} → {sizes[key]} ГиБ за {secs[key]} с', flush=True)
            return path
        proj = get('project', SUPRA_REPO, SUPRA_REV, SUPRA_PATTERNS)
        qwen = get('qwen', man['qwen-base']['repo_id'], man['qwen-base']['revision'], man['qwen-base']['allow_patterns'])
        moge = get('moge', man['moge2']['repo_id'], man['moge2']['revision'], man['moge2']['allow_patterns'])
        vae = get('vae', man['vae']['repo_id'], man['vae']['revision'], man['vae']['allow_patterns'])
        paths = {'completion': os.path.join(proj, 'completion'), 'material': os.path.join(proj, 'material'), 'qwen': qwen, 'moge': os.path.join(moge, 'model.pt'), 'vae': vae}
        missing = [k for k, v in paths.items() if not os.path.exists(v)]
        if missing:
            raise RuntimeError(f'после докачки нет: {missing}')
        STATE['phase'] = 'importing'
        t = time.time()
        chk = subprocess.run([sys.executable, '-c', 'import supratex, natten, o_voxel, flex_gemm, cumesh, nvdiffrast, moge.model.v2, utils3d; print("imports ok")'],
                             capture_output=True, text=True, env={**os.environ, **SUPRA_ENV}, timeout=600)
        if chk.returncode != 0:
            raise RuntimeError('импорты SUPRA не прошли: ' + (chk.stderr or chk.stdout)[-600:])
        STATE['config'] = {'sdir': sdir, 'sizes_gb': sizes, 'download_s': secs, 'pins': {k: v['revision'] for k, v in man.items()}, 'project_rev': SUPRA_REV,
                           'debug_env': {k: os.environ.get(k) for k in ('CUDA_LAUNCH_BLOCKING', 'TORCH_SHOW_CPP_STACKTRACES')}, 'cgroup': cgroup_gb()}
        os.makedirs(OUT, exist_ok=True)
        self.runner = SupraRunner(sdir, paths)
        return {'weights_s': round(time.time() - t_all, 1), 'import_check_s': round(time.time() - t, 1), 'download_s': secs, 'download_gb': sizes, 'mem_after_warm': {'gpu': nvidia_smi(), 'cgroup': cgroup_gb()}}

    def generate(self, image, params: dict, path: str) -> dict:
        if not params.get('texture_mesh'):
            raise ValueError('supratex красит готовую форму: нужен --texture-mesh <clean.glb>')
        import shutil
        import trimesh
        trace: dict = {}
        self._trace = trace

        def mem(name: str) -> None:
            trace[name] = {'gpu': nvidia_smi(), 'cgroup': cgroup_gb()}
        mem('start')
        t = time.time()
        sc = trimesh.load(os.path.join(JOBS_DIR, params['job_id'] + '.mesh.glb'), force='scene')
        parts = sc.dump()
        if not parts:
            raise ValueError('в GLB формы нет мешей')
        mesh = parts[0] if len(parts) == 1 else trimesh.util.concatenate(parts)
        load_s = round(time.time() - t, 2)
        work = os.path.join(OUT, f'_supra_{os.getpid()}_{int(time.time() * 1000)}')
        os.makedirs(work, exist_ok=True)
        self.runner.work_log = work
        try:
            final, m = supra_texture_on_shape(self.runner, mesh, image, params, {'mem': mem}, work)
            final.export(path)
            log_tail = {k: _read_log(os.path.join(work, k))[-400:] for k in ('supra_front.log', 'supra_tex.log')}
        finally:
            shutil.rmtree(work, ignore_errors=True)
        m['stage_s']['load_shape'] = load_s
        m['stage_s']['front_s'] = (m.get('front') or {}).get('s')
        m['stage_s']['texturing_s'] = (m.get('texturing') or {}).get('s')
        peaks = [x for x in (m.get('front') or {}, m.get('texturing') or {})]
        m.update({'mode': 'supratex', 'peak_vram_mib': max([int(x.get('peak_vram_mib') or 0) for x in peaks] or [0]), 'peak_cgroup_gb': max([float(x.get('peak_cgroup_gb') or 0.0) for x in peaks] or [0.0]),
                  'child_maxrss_gb': max([float(x.get('child_maxrss_gb') or 0.0) for x in peaks] or [0.0]), 'mem': trace, 'log_tail': log_tail, 'config': dict(STATE.get('config') or {})})
        return m

    def on_error(self, e: BaseException) -> dict:
        """Разбор упавшего задания: тип ошибки CUDA по тексту (хвост журнала подпроцесса внутри), память. `fatal` — воркер «сломан» (`mark_broken`), драйвер гасит группу."""
        import traceback as tb
        kind = classify_cuda_error(e)
        tb.clear_frames(e.__traceback__)
        return {'kind': kind, 'fatal': kind == 'fatal', 'gpu': nvidia_smi(), 'cgroup': cgroup_gb(), 'stage_mem': dict(self._trace), 'config': STATE.get('config')}


def backend():
    return {'trellis2': Trellis2Backend, 'pixal3d': Pixal3DBackend, 'pixal3d-tex': PixalTexBackend, 'mvadapter-i2tex': MVAdapterTexBackend, 'triposg-mv': TripoSGMVBackend, 'mvpainter': MVPainterBackend, 'supratex': SupraTexBackend, 'localmesh': LocalMeshBackend, 'hunyuan21': Hunyuan21Backend, 'fake': FakeBackend}[os.environ.get('MODEL', 'trellis2')]()


def versions() -> dict:
    """Версии того, что реально стоит в контейнере (шаг 0: transformers 5.x вместо 4.x уронил задание) — по метаданным пакетов, без импорта."""
    out = {}
    from importlib import metadata
    for pkg in ('torch', 'torchvision', 'transformers', 'huggingface_hub', 'tokenizers', 'safetensors', 'timm', 'kornia', 'numpy', 'trimesh', 'pillow',
                'flash_attn', 'o_voxel', 'nvdiffrast', 'diffusers', 'accelerate', 'opencv-python-headless', 'utils3d', 'localmesh-engine', 'natten', 'cumesh', 'flex_gemm'):
        try:
            out[pkg] = metadata.version(pkg)
        except metadata.PackageNotFoundError:
            pass
    try:
        import torch
        out['cuda'] = torch.version.cuda
    except Exception:  # noqa: BLE001
        pass
    return out


def atomic_write(path: str, data: bytes) -> None:
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    tmp = f'{path}.tmp{os.getpid()}'
    with open(tmp, 'wb') as f:
        f.write(data)
    os.replace(tmp, path)


def dir_gb(path: str) -> float:
    n = 0
    for root, _d, files in os.walk(path):
        for f in files:
            try:
                n += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return round(n / 2 ** 30, 2)


def rss_gb(pid: int) -> float | None:
    """Резидентная память процесса (VmRSS) — читает ГЛАВНЫЙ процесс у ребёнка, ребёнок для этого не нужен."""
    try:
        for ln in open(f'/proc/{pid}/status'):
            if ln.startswith('VmRSS:'):
                return round(int(ln.split()[1]) / 2 ** 20, 2)
    except OSError:
        pass
    return None


def proc_cpu(pid: int) -> dict:
    """Состояние процесса (R работает / S ждёт / D диск) и сколько секунд процессорного времени съел (utime+stime): стоит ли ребёнок или считает."""
    try:
        parts = open(f'/proc/{pid}/stat').read().rsplit(')', 1)[1].split()
        tck = os.sysconf('SC_CLK_TCK')
        return {'state': parts[0], 'cpu_s': round((int(parts[11]) + int(parts[12])) / tck, 1), 'threads': int(parts[17])}
    except (OSError, ValueError, IndexError):
        return {}


def disk_gb() -> dict:
    """Свободное место на диске контейнера (кэш весов HF ≈ 42 ГиБ + результаты): падение «нет места» посреди 30 товаров ловим заранее."""
    import shutil
    out = {}
    for name, path in (('hf', os.environ.get('HF_HOME', '/data/hf')), ('out', OUT)):
        try:
            os.makedirs(path, exist_ok=True)
            u = shutil.disk_usage(path)
            out[name] = {'free': round(u.free / 2 ** 30, 1), 'total': round(u.total / 2 ** 30, 1)}
        except OSError:
            pass
    return out


def cgroup_gb() -> dict:
    """Память группы контейнера: `current/max`, ГБ (cgroup v2, затем v1). Приближение к «убит по памяти»: current подошёл к max."""
    for cur, mx in (('/sys/fs/cgroup/memory.current', '/sys/fs/cgroup/memory.max'),
                    ('/sys/fs/cgroup/memory/memory.usage_in_bytes', '/sys/fs/cgroup/memory/memory.limit_in_bytes')):
        try:
            c = int(open(cur).read().strip())
            m = open(mx).read().strip()
            return {'current': round(c / 2 ** 30, 2), 'max': None if m == 'max' or int(m) > 2 ** 50 else round(int(m) / 2 ** 30, 1)}
        except (OSError, ValueError):
            continue
    return {}


# ——— ДОЧЕРНИЙ ПРОЦЕСС: загрузка модели и генерация ———
def save_state() -> None:
    STATE['at'] = time.time()
    atomic_write(STATE_PATH, json.dumps(STATE, ensure_ascii=False).encode())


def warm() -> None:
    """Прогрев: загрузка весов (Hugging Face) и перенос на видеокарту. Всё тело обёрнуто, исключение — в STATE['error'] (урок боевого воркера 29.08)."""
    global BACKEND
    try:
        STATE['phase'] = 'loading'
        BACKEND = backend()
        t = time.time()
        STATE['timings'].update(BACKEND.load())
        STATE['timings']['warm_total_s'] = round(time.time() - t, 1)
        STATE['timings']['container_to_ready_s'] = round(time.time() - T_CONTAINER, 1)
        STATE['versions'] = versions()
        STATE['phase'] = 'ready'
        STATE['warm'] = True
    except Exception as e:  # noqa: BLE001
        STATE['phase'] = 'failed'
        STATE['error'] = f'{type(e).__name__}: {str(e)[:400]}'
        print('ПРОГРЕВ УПАЛ:\n' + traceback.format_exc()[-2500:], flush=True)


BACKEND = None


def mark_broken(reason: str) -> None:
    """Фатальная ошибка CUDA (не обычная нехватка памяти): состояние CUDA в процессе испорчено, дальше жечь деньги нельзя. /health → ok=false, phase=broken, warm=false;
    новые задания — отказ (HTTP 503 и `run_job`); драйвер видит это в /health и в ответе задания и гасит группу."""
    STATE['broken'] = reason[:300]
    STATE['warm'] = False
    STATE['phase'] = 'broken'
    STATE['error'] = STATE['broken']
    save_state()
    print(f'[child] ВОРКЕР СЛОМАН: {STATE["broken"]}', flush=True)


def run_job(jid: str) -> None:
    """Одно задание из каталога заданий: png + req.json → res.json (+ glb в OUT). Исключение не роняет ребёнка — уходит в res.json."""
    from PIL import Image
    base = os.path.join(JOBS_DIR, jid)
    body = json.load(open(base + '.req.json', encoding='utf-8'))
    res = {'job_id': jid, 'status': 'running', 'params': body, 'started': time.time()}
    if STATE.get('broken'):                    # после фатальной ошибки CUDA видеокарту не трогаем: отказ сразу (драйвер к этому моменту уже гасит группу)
        res.update(status='failed', error=f'воркер сломан: {STATE["broken"]}', finished=time.time())
        atomic_write(base + '.res.json', json.dumps(res, ensure_ascii=False).encode())
        return
    atomic_write(base + '.running', b'1')
    try:
        img = Image.open(base + '.png')
        img.load()
        res['input'] = {'mode': img.mode, 'size': list(img.size)}
        path = os.path.join(OUT, f'{jid}.glb')
        os.makedirs(OUT, exist_ok=True)
        t = time.time()
        m = BACKEND.generate(img, body, path)
        m['total_s'] = round(time.time() - t, 2)
        m['gpu_after'] = nvidia_smi()
        m['glb'] = glb_stats(path)
        res['metrics'] = m
        res['status'] = 'done'
    except Exception as e:  # noqa: BLE001
        res['status'] = 'failed'
        res['error'] = f'{type(e).__name__}: {str(e)[:400]}'
        res['trace'] = traceback.format_exc()[-2500:]
        print(f'ЗАДАНИЕ {jid} УПАЛО:\n' + res['trace'], flush=True)
        on_error = getattr(BACKEND, 'on_error', None)
        if on_error is not None:               # разбор падения бэкендом (pixal3d-tex): тип ошибки CUDA, память по стадиям; фатальная — воркер «сломан»
            try:
                res['diag'] = on_error(e)
            except Exception as e2:  # noqa: BLE001 — после фатальной ошибки разбор сам может упасть: не теряем сам факт
                res['diag'] = {'kind': 'unknown', 'fatal': True, 'error': f'{type(e2).__name__}: {str(e2)[:200]}'}
            print('[diag]', json.dumps(res['diag'], ensure_ascii=False, default=str)[:3000], flush=True)
            if res['diag'].get('fatal'):
                mark_broken(res['error'])
    res['finished'] = time.time()
    atomic_write(base + '.res.json', json.dumps(res, ensure_ascii=False, default=str).encode())


def child_main() -> None:
    import faulthandler
    faulthandler.dump_traceback_later(int(os.environ.get('STACK_DUMP_S', '240')), repeat=True, file=sys.stderr)      # C-поток без GIL: покажет, где завис
    os.makedirs(JOBS_DIR, exist_ok=True)
    os.makedirs(OUT, exist_ok=True)
    hf = os.environ.get('HF_HOME', '/data/hf')
    print(f'[child] pid {os.getpid()}, модель {os.environ.get("MODEL")}, HF_TOKEN: {"есть" if os.environ.get("HF_TOKEN") else "НЕТ"} (значение не печатается), HF_HOME {hf}', flush=True)

    ppid = os.getppid()

    def ticker() -> None:
        last = None
        while True:
            if os.getppid() != ppid:                  # главный процесс исчез — сироту не держим (память и видеокарта)
                os._exit(0)
            STATE['progress'] = {'hf_gb': dir_gb(hf), 'at': time.time()}
            save_state()
            if STATE['phase'] != last:
                last = STATE['phase']
                print(f'[child] фаза: {last}', flush=True)
            time.sleep(5)
    threading.Thread(target=ticker, daemon=True).start()
    warm()
    save_state()
    while True:
        try:
            names = sorted(n for n in os.listdir(JOBS_DIR) if n.endswith('.req.json'))
        except OSError:
            names = []
        for n in names:
            jid = n[:-len('.req.json')]
            if not os.path.exists(os.path.join(JOBS_DIR, jid + '.res.json')):
                run_job(jid)
        time.sleep(1)


# ——— ГЛАВНЫЙ ПРОЦЕСС: лёгкий HTTP-сервер и надзор за ребёнком ———
def child_script() -> str:
    """Путь к файлу кода ребёнка. Код, поданный через `python -c` (без `__file__`), — распаковываем из TRIAL_WORKER_Z в /tmp."""
    f = globals().get('__file__')
    if f and os.path.exists(f):
        return f
    import zlib
    p = '/tmp/trial_worker.py'
    atomic_write(p, zlib.decompress(base64.b64decode(os.environ['TRIAL_WORKER_Z'])))
    return p


def start_child() -> None:
    global CHILD
    env = dict(os.environ, TRIAL_CHILD='1')
    CHILD = subprocess.Popen([sys.executable, '-u', child_script()], env=env)       # вывод ребёнка — тот же журнал контейнера


def read_state() -> dict:
    try:
        return json.load(open(STATE_PATH, encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def child_info() -> dict:
    if CHILD is None:
        return {'started': False}
    rc = CHILD.poll()
    st = read_state()
    return {'started': True, 'alive': rc is None, 'returncode': rc, 'rss_gb': rss_gb(CHILD.pid) if rc is None else None, **(proc_cpu(CHILD.pid) if rc is None else {}),
            'state_age_s': round(time.time() - st['at'], 1) if st.get('at') else None}


def health() -> dict:
    st = read_state()
    ci = child_info()
    phase, err = st.get('phase') or 'starting', st.get('error')
    if ci.get('started') and not ci.get('alive'):
        phase = 'child_dead'
        err = f'дочерний процесс завершился, код {ci.get("returncode")} (−9 = убит ядром, почти наверняка нехватка памяти)'
    broken = st.get('broken')                   # фатальная ошибка CUDA в ребёнке: ok=false, новые задания отказ, драйвер гасит группу (`mark_broken`)
    return {'ok': not broken, 'phase': 'broken' if broken else phase, 'warm': bool(st.get('warm')) and bool(ci.get('alive')) and not broken, 'error': broken or err, 'broken': broken,
            'timings': st.get('timings'), 'config': st.get('config'),
            'progress': st.get('progress'), 'child': ci, 'cgroup_gb': cgroup_gb(), 'disk_gb': disk_gb(), 'uptime_s': round(time.time() - T_CONTAINER, 1)}


def watch_loop() -> None:
    """Раз в 30 с — строка состояния в журнал контейнера (видна через log-entries, даже когда шлюз отвечает 503)."""
    global CHILD_RC_LOGGED
    while True:
        h = health()
        print(f'[watch] фаза={h["phase"]} warm={h["warm"]} hf_gb={(h.get("progress") or {}).get("hf_gb")} child={h["child"]} cgroup_gb={h["cgroup_gb"]}'
              + (f' ОШИБКА={h["error"]}' if h['error'] else ''), flush=True)
        time.sleep(30)


class H(BaseHTTPRequestHandler):
    SEEN = [0]

    def log_message(self, fmt, *a):      # в журнал — только первые обращения (видно, дошла ли проба/шлюз: адрес клиента и путь); остальное тихо
        if self.SEEN[0] < 12:
            self.SEEN[0] += 1
            print(f'[http] {self.client_address[0]} {fmt % a}', flush=True)

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
            return self._json(200, health())
        if p == '/ready':
            h = health()
            return self._json(200 if h['warm'] else 503, {'ready': h['warm'], 'phase': h['phase'], 'error': h['error']})
        if p == '/info':
            st = read_state()
            return self._json(200, {'gpu': nvidia_smi(), 'python': sys.version.split()[0], 'model': os.environ.get('MODEL', 'trellis2'),
                                    'image_note': os.environ.get('IMAGE_NOTE', ''), 'timings': st.get('timings'), 'versions': st.get('versions')})
        if p.startswith('/job/'):
            jid = p[5:]
            base = os.path.join(JOBS_DIR, os.path.basename(jid))
            if os.path.exists(base + '.res.json'):
                return self._json(200, json.load(open(base + '.res.json', encoding='utf-8')))
            if os.path.exists(base + '.running'):
                return self._json(200, {'job_id': jid, 'status': 'running'})
            if os.path.exists(base + '.req.json'):
                return self._json(200, {'job_id': jid, 'status': 'queued'})
            return self._json(404, {'error': 'нет такого задания'})
        if p.startswith('/glb/'):
            jid = os.path.basename(p[5:])
            rp = os.path.join(JOBS_DIR, jid + '.res.json')
            stages = 'v=stages' in self.path                                                   # ?v=stages — mvadapter-i2tex с mv_keep_stages: архив стадий (А0)
            fp = os.path.join(OUT, f'{jid}.stages.zip' if stages else (f'{jid}.ai.glb' if 'v=ai' in self.path else f'{jid}.glb'))      # ?v=ai — localmesh: текстура до проекции фото
            if not os.path.exists(rp) or json.load(open(rp, encoding='utf-8')).get('status') != 'done' or not os.path.exists(fp):
                return self._json(404, {'error': 'GLB нет (задание не готово или упало)' if not stages else 'архива стадий нет (mv_keep_stages не было или сохранение упало)'})
            data = open(fp, 'rb').read()
            self.send_response(200)
            self.send_header('Content-Type', 'application/zip' if stages else 'model/gltf-binary')
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
            jid = os.path.basename(str(body['job_id']))
            png = base64.b64decode(body.pop('image_b64'))
            mesh_glb = base64.b64decode(body.pop('texture_mesh_b64')) if body.get('texture_mesh_b64') else None      # контроль «перекраска готовой формы»
        except (ValueError, KeyError):
            return self._json(400, {'error': 'нужны job_id и image_b64'})
        h = health()
        if h.get('broken'):
            return self._json(503, {'error': 'воркер сломан после фатальной ошибки CUDA, новые задания не берёт', 'broken': h['broken'], 'phase': h['phase']})
        if not h['warm']:
            return self._json(503, {'error': 'модель ещё не готова', 'phase': h['phase']})
        base = os.path.join(JOBS_DIR, jid)
        if os.path.exists(base + '.req.json'):
            return self._json(409, {'error': 'такой job_id уже есть'})           # повтор не жжёт GPU второй раз
        atomic_write(base + '.png', png)
        if mesh_glb:
            atomic_write(base + '.mesh.glb', mesh_glb)
            body['texture_mesh'] = True
        atomic_write(base + '.req.json', json.dumps(body, ensure_ascii=False).encode())
        self._json(202, {'job_id': jid, 'status': 'queued'})


class DualStackServer(ThreadingHTTPServer):
    """Слушает и IPv6, и IPv4 одним сокетом (`::`, IPV6_V6ONLY=0). Контейнеры и шлюз Salad ходят по IPv6 (docs.salad.com → gateway → enabling-ipv6):
    сервер только на `0.0.0.0` (шаги 0 и 0b–0c, 18.11) не отвечал шлюзу и пробам НИ РАЗУ — при живом процессе и без единой ошибки в журнале."""
    address_family = socket.AF_INET6
    daemon_threads = True

    def server_bind(self):
        self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        super().server_bind()


def make_server(port: int) -> ThreadingHTTPServer:
    try:
        return DualStackServer(('::', port), H)
    except OSError as e:                         # в окружении нет IPv6 (CI, часть хостов) — обычный IPv4
        print(f'[http] IPv6 недоступен ({e}) — слушаю только IPv4', flush=True)
        return ThreadingHTTPServer(('0.0.0.0', port), H)


def main() -> None:
    os.makedirs(JOBS_DIR, exist_ok=True)
    start_child()
    threading.Thread(target=watch_loop, daemon=True).start()
    print(f'воркер пробы: порт {PORT}, модель {os.environ.get("MODEL", "trellis2")}, ребёнок pid {CHILD.pid}', flush=True)
    make_server(PORT).serve_forever()


if __name__ == '__main__':
    if os.environ.get('TRIAL_CHILD') == '1':
        child_main()
    else:
        main()
