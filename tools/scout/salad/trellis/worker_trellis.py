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
  GET  /glb/<id>      байты `model.glb`

Бэкенд модели — по `MODEL` (`trellis2` | `pixal3d` | `pixal3d-tex` (краска Pixal3D по готовой форме) | `hunyuan21`); `MODEL=fake` — для теста без видеокарты (`tests_trellis_trial.py`). Токена Hugging Face в логи не пишем.
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

    @staticmethod
    def _paint_only(P, PRE, shape_img, params: dict, path: str) -> dict:
        """ГИБРИД «чужая форма + покраска Hunyuan Paint 2.1» (T-20261118-91/2): форма приходит в задании (`shape_b64` — GLB, например TRELLIS.2), текстуру с неё
        снимаем (в покраску идёт голая геометрия), красит боевая покраска `paint_pipeline()` напрямую. Апстрим-покраска по умолчанию делает `use_remesh=True`
        (упрощает до ~40 тыс. граней и перестраивает сетку — форма меняется); `use_remesh` из задания включает/выключает это явно (по умолчанию в гибриде — False)."""
        import base64 as b64
        import inspect
        import shutil
        import tempfile
        import trimesh
        remesh = bool(params.get('use_remesh', False))
        work = tempfile.mkdtemp(prefix='hybrid-')
        try:
            src = trimesh.load(io_bytes(b64.b64decode(params['shape_b64'])), file_type='glb', force='mesh')
            v = src.vertices - (src.bounds[0] + src.bounds[1]) / 2.0
            v = v * (2.0 / float(max(src.extents)))                                                 # как у формы Hunyuan: центр в нуле, наибольший размер 2 (покраска ждёт такой масштаб)
            bare = trimesh.Trimesh(vertices=v, faces=src.faces, process=False)                      # без UV и материала: покраска строит свою развёртку
            shape = os.path.join(work, 'in-shape.glb')
            bare.export(shape)
            tris_in = int(len(bare.faces))
            pipe = P.paint_pipeline()
            cls = type(pipe)
            if 'use_remesh' not in inspect.signature(cls.__call__).parameters:
                raise RuntimeError('в Hunyuan3DPaintPipeline.__call__ нет параметра use_remesh — гибрид без него неуправляем')
            orig = cls.__call__

            def patched(self, *a, **k):
                k['use_remesh'] = remesh
                return orig(self, *a, **k)
            final = os.path.join(work, 'model.glb')
            t = time.time()
            cls.__call__ = patched
            try:
                # покраска напрямую (боевой `pipeline.generate(shape_glb=…)` есть не во всех образах: у `memtrim-d8c51952` его нет — TypeError 18.11 02:56)
                painted = pipe(mesh_path=shape, image_path=PRE._paint_crop(shape_img))
            finally:
                cls.__call__ = orig
            t_paint = round(time.time() - t, 1)
            P._save_painted(painted, final)
            shutil.copy(final, path)
            try:
                P._unload('paint')                      # как боевая стадийность: следующему заданию (форма Hunyuan) нужна видеопамять
            except Exception:  # noqa: BLE001
                pass
            return {'stage_s': {'paint': t_paint, 'total': round(time.time() - t, 1)}, 'mode': 'paint_only', 'use_remesh': remesh, 'tris_in': tris_in}
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def generate(self, image, params: dict, path: str) -> dict:
        import shutil
        import tempfile
        import pipeline as P
        import preprocess as PRE
        shape_img = image.convert('RGBA')
        if params.get('shape_b64'):
            return self._paint_only(P, PRE, shape_img, params, path)
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
    hk = {'seed': lambda s: None, 'sync': lambda: None, 'free': lambda: None, **(hooks or {})}
    stage: dict = {}
    t = time.time()

    def lap(name: str) -> None:
        hk['sync']()
        nonlocal t
        stage[name] = round(time.time() - t, 2)
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
    shape_slat = pipe.encode_shape_slat(enc_mesh, resolution)
    lap('encode_shape')
    cond = pipe.get_proj_cond_shape(pipe.image_cond_model_tex_1024, [cond_img], shape_slat.coords, camera_angle_x=float(cam['camera_angle_x']),
                                    distance=float(cam['distance']), mesh_scale=cam_scale, grid_resolution_override=resolution // 16)
    hk['free']()
    lap('cond')
    tex_slat = pipe.sample_tex_slat(cond, pipe.models['tex_slat_flow_model_1024'], shape_slat, params.get('sampler') or {})
    del cond
    hk['free']()
    lap('sample_tex')
    pbr = pipe.decode_tex_slat_plain(tex_slat)
    hk['free']()
    lap('decode_tex')
    out = pipe.postprocess_mesh(m_in, pbr, resolution, texture_size)
    lap('bake')
    v_back = from_cube(undo_upstream_swap(out.vertices), c, s, R).astype(np.float32).astype(np.float64)      # через float32, как лежит в GLB
    final = trimesh.Trimesh(vertices=v_back, faces=np.asarray(out.faces), visual=out.visual, process=False)
    shape = check_shape_unchanged(verts.astype(np.float32).astype(np.float64), faces, v_back, np.asarray(out.faces))
    lap('check_shape')
    return final, {'align': align, 'fit': fit, 'shape': shape, 'has_uv': bool(has_uv), 'stage_s': stage,
                   'smooth': smooth_info, 'cond_canvas': list(cond_img.size), 'cond_mesh_scale': round(cam_scale, 5), 'photo_crop': list(rgba.size), 'mesh_tris': int(len(faces)), 'tex_resolution': resolution}


class PixalTexBackend:
    """`pixal3d-tex`: форма TRELLIS.2 (готовый GLB, `<job>.mesh.glb`) + краска Pixal3D по одному фото. Грузим ТОЛЬКО то, что нужно покраске: поток краски 1024 и декодер краски из
    `TencentARC/Pixal3D`, кодировщик формы из `microsoft/TRELLIS.2-4B` (у Pixal3D его нет), экстрактор DINOv3 + NAF стадии tex_1024 и MoGe-2 (камера). Потоки формы и структуры не грузятся
    (минус ≈ 15 ГБ скачивания и видеопамяти против `pixal3d`). Методы пайплайна — апстрима: `get_proj_cond_shape`, `sample_tex_slat` (Pixal3D) и `encode_shape_slat`,
    `decode_tex_slat` без направляющих, `postprocess_mesh` (его Trellis2TexturingPipeline). Образ — тот же, что у `pixal3d` (`Dockerfile.pixal3d`), код едет через `command`."""
    name = 'pixal3d-tex'

    def load(self) -> dict:
        os.environ.setdefault('PYTORCH_CUDA_ALLOC_CONF', 'expandable_segments:True')
        os.environ.setdefault('OPENCV_IO_ENABLE_OPENEXR', '1')
        sys.path.insert(0, os.environ.get('PIXAL3D_DIR', '/opt/Pixal3D'))
        STATE['phase'] = 'importing'
        t_imp = time.time()
        import torch
        import inference as INF
        from pixal3d import models as PM
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
            encode_shape_slat = T2T.encode_shape_slat
            decode_tex_slat_plain = T2T.decode_tex_slat                                  # без guide_subs (форма не генерируется)
            postprocess_mesh = T2T.postprocess_mesh                                      # растеризация по развёртке, запекание, inpaint
        self.INF = INF
        STATE['phase'] = 'weights'
        t = time.time()
        pipe = TexOnly.from_pretrained(INF.MODEL_PATH)
        pipe.models['shape_slat_encoder'] = PM.from_pretrained('microsoft/TRELLIS.2-4B/ckpts/shape_enc_next_dc_f16c32_fp16')
        pipe.models['shape_slat_encoder'].eval()
        pipe.low_vram = False
        pipe.image_cond_model_tex_1024 = INF.build_image_cond_model(INF.IMAGE_COND_CONFIGS['tex_1024'])
        t_w = time.time() - t
        STATE['phase'] = 'to_gpu'
        t = time.time()
        pipe.cuda()
        pipe.image_cond_model_tex_1024.cuda()
        pipe.image_cond_model_tex_1024._load_naf()
        self.pipe = pipe
        t_gpu = time.time() - t
        STATE['phase'] = 'moge'
        t = time.time()
        self.moge = INF.load_moge_model(device='cuda')
        torch.cuda.synchronize()
        return {'weights_s': round(t_w, 1), 'to_gpu_s': round(t_gpu, 1), 'moge_s': round(time.time() - t, 1)}

    def generate(self, image, params: dict, path: str) -> dict:
        if not params.get('texture_mesh'):
            raise ValueError('pixal3d-tex красит готовую форму: нужен --texture-mesh <clean.glb>')
        import torch
        import trimesh
        torch.cuda.reset_peak_memory_stats()
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
        cam = self.INF.get_camera_params_wild_moge(tmp, self.moge, device='cuda', mesh_scale=1.0, extend_pixel=0, image_resolution=512)
        os.remove(tmp)
        camera_s = round(time.time() - t, 2)
        samp = {'steps': 12, 'guidance_strength': float(params.get('tex_guidance') or 1.0), 'guidance_rescale': 0.0, 'rescale_t': 3.0}
        hooks = {'seed': torch.manual_seed, 'sync': torch.cuda.synchronize, 'free': torch.cuda.empty_cache}
        with torch.no_grad():
            final, m = texture_on_shape(self.pipe, mesh, image, cam, {**params, 'sampler': samp}, hooks)
        final.export(path, extension_webp=bool(int(os.environ.get('EXPORT_WEBP', '0'))))
        m['stage_s'].update({'load_shape': load_s, 'camera': camera_s})
        m.update({'mode': 'pixal3d_tex', 'peak_vram_gb': round(torch.cuda.max_memory_allocated() / 2 ** 30, 2), 'peak_reserved_gb': round(torch.cuda.max_memory_reserved() / 2 ** 30, 2),
                  'camera_params': {'fov_rad': round(float(cam['camera_angle_x']), 4), 'distance': round(float(cam['distance']), 3)}})
        return m


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


def backend():
    return {'trellis2': Trellis2Backend, 'pixal3d': Pixal3DBackend, 'pixal3d-tex': PixalTexBackend, 'localmesh': LocalMeshBackend, 'hunyuan21': Hunyuan21Backend, 'fake': FakeBackend}[os.environ.get('MODEL', 'trellis2')]()


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


def io_bytes(b: bytes):
    import io
    return io.BytesIO(b)


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


def run_job(jid: str) -> None:
    """Одно задание из каталога заданий: png + req.json → res.json (+ glb в OUT). Исключение не роняет ребёнка — уходит в res.json."""
    from PIL import Image
    base = os.path.join(JOBS_DIR, jid)
    body = json.load(open(base + '.req.json', encoding='utf-8'))
    res = {'job_id': jid, 'status': 'running', 'params': body, 'started': time.time()}
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
    res['finished'] = time.time()
    atomic_write(base + '.res.json', json.dumps(res, ensure_ascii=False).encode())


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
    return {'ok': True, 'phase': phase, 'warm': bool(st.get('warm')) and bool(ci.get('alive')), 'error': err, 'timings': st.get('timings'),
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
            fp = os.path.join(OUT, f'{jid}.ai.glb' if 'v=ai' in self.path else f'{jid}.glb')      # ?v=ai — localmesh: текстура до проекции фото
            if not os.path.exists(rp) or json.load(open(rp, encoding='utf-8')).get('status') != 'done' or not os.path.exists(fp):
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
            jid = os.path.basename(str(body['job_id']))
            png = base64.b64decode(body.pop('image_b64'))
            mesh_glb = base64.b64decode(body.pop('texture_mesh_b64')) if body.get('texture_mesh_b64') else None      # контроль «перекраска готовой формы»
        except (ValueError, KeyError):
            return self._json(400, {'error': 'нужны job_id и image_b64'})
        h = health()
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
