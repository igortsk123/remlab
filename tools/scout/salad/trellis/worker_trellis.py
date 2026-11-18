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

Бэкенд модели — по `MODEL` (`trellis2` | `hunyuan21`); `MODEL=fake` — для теста без видеокарты (`tests_trellis_trial.py`). Токена Hugging Face в логи не пишем.
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


def backend():
    return {'trellis2': Trellis2Backend, 'hunyuan21': Hunyuan21Backend, 'fake': FakeBackend}[os.environ.get('MODEL', 'trellis2')]()


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
            'progress': st.get('progress'), 'child': ci, 'cgroup_gb': cgroup_gb(), 'uptime_s': round(time.time() - T_CONTAINER, 1)}


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
            fp = os.path.join(OUT, f'{jid}.glb')
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
        except (ValueError, KeyError):
            return self._json(400, {'error': 'нужны job_id и image_b64'})
        h = health()
        if not h['warm']:
            return self._json(503, {'error': 'модель ещё не готова', 'phase': h['phase']})
        base = os.path.join(JOBS_DIR, jid)
        if os.path.exists(base + '.req.json'):
            return self._json(409, {'error': 'такой job_id уже есть'})           # повтор не жжёт GPU второй раз
        atomic_write(base + '.png', png)
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
