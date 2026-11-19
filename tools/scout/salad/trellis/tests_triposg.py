#!/usr/bin/env python3
"""Тесты `triposg-mv` — форма TripoSG → развёртка CuMesh → краска MV-Adapter (T-20261119-80, вариант 6): 24 поворота куба, подгонка кадра формы к фото по силуэту, чистка/развёртка CuMesh на подмене
(порядок шагов как в `o_voxel.postprocess.to_glb`), разбор «форма»/«краска» в бэкенде, проверка карта ↔ архитектура образа (урок 742), драйвер: две фазы на товар одним холодным стартом, очистка общим правилом
между фазами, счётчик отказов по классам, `not_run`, деньги/стоп. Без видеокарты, сети, ключей, torch, TripoSG и CuMesh. Разделы с настоящим trimesh (форма/очистка) пропускаются без него.

  ~/venvs/scout/bin/python tools/scout/salad/trellis/tests_triposg.py
"""
from __future__ import annotations

import base64
import contextlib
import io
import json
import os
import sys
import tempfile
import types
from contextlib import redirect_stdout
from types import SimpleNamespace as NS

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.normpath(os.path.join(HERE, '..', '..')))
import remlab_tmp  # noqa: E402
remlab_tmp.use('tests_triposg')
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402
import worker_trellis as W  # noqa: E402
import trellis_trial as T  # noqa: E402

bad = 0


def ok(name, cond, extra=''):
    global bad
    print(('  ✓ ' if cond else '  ✗ ') + name + (f' — {extra}' if extra and not cond else ''))
    bad += 0 if cond else 1


def box(lo, hi):
    x0, y0, z0 = lo
    x1, y1, z1 = hi
    v = np.array([[x0, y0, z0], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0], [x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1]], dtype=np.float64)
    f = np.array([[0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7], [0, 1, 5], [0, 5, 4], [2, 3, 7], [2, 7, 6], [1, 2, 6], [1, 6, 5], [3, 0, 4], [3, 4, 7]])
    return v, f


def merge(*parts):
    vs, fs, off = [], [], 0
    for v, f in parts:
        vs.append(v)
        fs.append(f + off)
        off += len(v)
    return np.concatenate(vs), np.concatenate(fs)


def l_shape():
    """Несимметричная фигура (буква Г с разными плечами и выступом, Y вверх, лицом +Z): силуэт не симметричен ни относительно диагонали, ни вертикали — различает все 24 поворота (у симметричных силуэтов
    «спереди/сзади» неразличимы — свойство метода, как у `mv_fit_yaw`; проверяется на коробке ниже)."""
    return merge(box((-0.30, -0.30, -0.10), (0.30, -0.10, 0.10)), box((-0.30, -0.10, -0.10), (-0.15, 0.35, 0.10)), box((0.10, -0.10, -0.10), (0.30, 0.0, 0.10)))


def photo_of(V, F, size=(400, 300), n=240):
    p = W.to_cube(V, 0.0)[0]
    u, v = W.mv_ortho_uv(p)
    M = W.surface_mask(u, v, F, n)
    ys, xs = np.nonzero(M)
    crop = M[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    canvas = np.zeros((size[1], size[0]), dtype=bool)
    y0, x0 = 20, 50
    h, w = min(crop.shape[0], size[1] - y0), min(crop.shape[1], size[0] - x0)
    canvas[y0:y0 + h, x0:x0 + w] = crop[:h, :w]
    rgba = np.stack([np.where(canvas, 190, 0), np.where(canvas, 120, 0), np.where(canvas, 60, 0), canvas * 255], axis=-1).astype(np.uint8)
    return Image.fromarray(rgba, 'RGBA')


print('[1] 24 поворота куба')
rots = W.tp_rotations()
ok('ровно 24 поворота, все ортогональны с определителем +1, без повторов', len(rots) == 24 and all(np.allclose(R @ R.T, np.eye(3)) and np.isclose(np.linalg.det(R), 1.0) for _n, R in rots)
   and len({tuple(R.flatten()) for _n, R in rots}) == 24)
ok('«как есть» — первым (имя «X Y Z»), имена уникальны', np.array_equal(rots[0][1], np.eye(3)) and rots[0][0] == 'X Y Z' and len({n for n, _ in rots}) == 24, rots[0][0])

print('[2] подгонка кадра формы к фото (силуэт)')
V, F = l_shape()
photo = photo_of(V, F)
fit_id = W.tp_fit_orient(V, F, photo)
ok('форма уже в кадре «вверх Y, лицом +Z»: остаёмся как есть (switched=false), IoU ≥ 0,9', not fit_id['switched'] and fit_id['name'] == 'X Y Z' and fit_id['iou'] >= 0.9, str({k: v for k, v in fit_id.items() if k != 'R'}))
n_ok, n_all = 0, 0
for name, R in rots:
    n_all += 1
    raw = V @ R                                          # «сырая» форма TripoSG в чужом кадре: raw @ R.T == V
    fit = W.tp_fit_orient(raw, F, photo)
    back = raw @ fit['R'].T
    iou_ok = fit['iou'] >= 0.9
    same = np.allclose(back, V, atol=1e-9)
    n_ok += iou_ok and same
ok('для каждого из 24 кадров сырой формы подобранный поворот возвращает ТОТ ЖЕ предмет (вершины совпадают), IoU ≥ 0,9', n_ok == n_all, f'{n_ok}/{n_all}')
fit_z = W.tp_fit_orient(V @ rots[[n for n, _ in rots].index('X Z -Y')][1], F, photo)
ok('Z-вверх (частый кадр сырых форм): switched=true, в записи топ-3 и IoU «как есть» ниже выбранного', fit_z['switched'] and len(fit_z['top']) == 3 and fit_z['iou_identity'] < fit_z['iou'], str({k: v for k, v in fit_z.items() if k != 'R'}))
Vb, Fb = box((-0.3, -0.2, -0.1), (0.3, 0.2, 0.1))
fb = W.tp_fit_orient(Vb, Fb, photo_of(Vb, Fb))
ok('симметричный предмет (коробка): много поворотов дают тот же силуэт — «как есть» не меняется (допуск TP_ORIENT_MARGIN против дрожания)', not fb['switched'] and fb['name'] == 'X Y Z', fb['name'])
try:
    W.tp_fit_orient(V, F, Image.new('RGBA', (64, 64), (0, 0, 0, 0)))
    ok('фото без предмета — отказ', False)
except ValueError:
    ok('фото без предмета — отказ', True)
big_f = np.tile(F, (20000, 1))                           # 240 тыс. граней > TP_FIT_FACES: подвыборка, а не падение; силуэт тот же
fit_big = W.tp_fit_orient(V, big_f, photo)
ok('граней больше TP_FIT_FACES: считается по подвыборке, результат тот же', fit_big['name'] == 'X Y Z' and fit_big['iou'] >= 0.85, str(fit_big['iou']))

print('[3] нормализация')
vn, c, s = W.tp_normalize(V * 3.0 + np.array([5.0, -2.0, 1.0]))
ok('центр габарита — в нуле, наибольшая сторона — 1', np.allclose((vn.min(0) + vn.max(0)) / 2, 0.0) and np.isclose((vn.max(0) - vn.min(0)).max(), 1.0))
try:
    W.tp_normalize(np.zeros((4, 3)))
    ok('вырожденная форма — отказ', False)
except ValueError:
    ok('вырожденная форма — отказ', True)

print('[4] чистка и развёртка CuMesh (подмена модуля)')


class FakeCuMesh:
    calls: list = []
    faces_n = 1_200_000

    def __init__(self):
        self.verts = self.faces = None

    def init(self, v, f):
        FakeCuMesh.calls.append(('init', len(f)))
        self.verts, self.faces = np.asarray(v), np.asarray(f)

    @property
    def num_faces(self):
        return FakeCuMesh.faces_n

    def simplify(self, n):
        FakeCuMesh.calls.append(('simplify', n))
        FakeCuMesh.faces_n = min(FakeCuMesh.faces_n, n)

    def remove_duplicate_faces(self):
        FakeCuMesh.calls.append(('dups',))

    def repair_non_manifold_edges(self):
        FakeCuMesh.calls.append(('nonman',))

    def remove_small_connected_components(self, x):
        FakeCuMesh.calls.append(('small', x))

    def unify_face_orientations(self):
        FakeCuMesh.calls.append(('unify',))

    def read(self):
        FakeCuMesh.calls.append(('read',))
        v = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0], [2, 2, 2]], dtype=np.float32)
        f = np.array([[0, 1, 2], [1, 3, 2], [2, 2, 2], [0, 0, 1]])                     # две нормальные грани и две вырожденные (площадь 0)
        return v, f

    def uv_unwrap(self, compute_charts_kwargs=None, return_vmaps=False, **kw):
        FakeCuMesh.calls.append(('uv', len(self.faces), json.dumps(compute_charts_kwargs, sort_keys=True)))
        n = len(self.faces)
        return (np.zeros((n * 3, 3), dtype=np.float32), np.arange(n * 3).reshape(n, 3), np.tile(np.array([[0.25, 0.25]], dtype=np.float32), (n * 3, 1)), 'vmaps')


CM = types.SimpleNamespace(CuMesh=FakeCuMesh)
ov, of, ouv, info = W.tp_cumesh_uv(np.zeros((9, 3)), np.zeros((9, 3), dtype=np.int64), 500000, CM, lambda x: x)
seq = [c[0] if c[0] != 'simplify' else f'simplify{c[1]}' for c in FakeCuMesh.calls]
ok('порядок шагов как в to_glb(remesh=False): упрощение до 3×цели → чистка → упрощение до цели → чистка → единая ориентация → вырожденные → пересоздание → развёртка',
   seq[:12] == ['init', 'simplify1500000', 'dups', 'nonman', 'small', 'simplify500000', 'dups', 'nonman', 'small', 'unify', 'read', 'init'] or seq[:11] == ['init', 'simplify1500000', 'dups', 'nonman', 'small', 'simplify500000', 'dups', 'nonman', 'small', 'unify', 'read'], str(seq))
ok('вырожденные грани (2 из 4) убраны ДО развёртки: в `uv_unwrap` пришло 2 грани; число убранных — в замерах', info['degenerate_removed'] == 2 and any(c[0] == 'uv' and c[1] == 2 for c in FakeCuMesh.calls), str(info))
ok('V развёртки перевёрнут как у TRELLIS.2 (0,25 → 0,75); пороги кластеризации как в to_glb (угол 90°, 0 уточнений, 1 глобальная итерация, сглаживание 1)',
   np.allclose(ouv[:, 1], 0.75) and np.allclose(ouv[:, 0], 0.25) and json.loads([c for c in FakeCuMesh.calls if c[0] == 'uv'][0][2]) == {'global_iterations': 1, 'refine_iterations': 0, 'smooth_strength': 1, 'threshold_cone_half_angle_rad': float(np.radians(90.0))})
FakeCuMesh.calls, FakeCuMesh.faces_n = [], 400_000
W.tp_cumesh_uv(np.zeros((9, 3)), np.zeros((9, 3), dtype=np.int64), 500000, CM, lambda x: x)
ok('граней уже меньше цели: упрощение НЕ вызывается (форму не трогаем лишний раз), чистка — вызывается', not any(c[0] == 'simplify' for c in FakeCuMesh.calls) and ('dups',) in FakeCuMesh.calls)

print('[5] бэкенд: «форма» / «краска», карта ↔ архитектура образа')
b = W.TripoSGMVBackend.__new__(W.TripoSGMVBackend)
log = []
b.shape = lambda image, params, path: log.append('shape') or {'mode': 'triposg_shape'}
b._tp_to = lambda dev: log.append('tp->' + dev)
orig_gen = W.MVAdapterTexBackend.generate
W.MVAdapterTexBackend.generate = lambda self, image, params, path: log.append('paint') or {'mode': 'mvadapter_i2tex'}
try:
    r1 = b.generate(None, {'job_id': 'j'}, '/x')
    r2 = b.generate(None, {'job_id': 'j', 'texture_mesh': True}, '/x')
finally:
    W.MVAdapterTexBackend.generate = orig_gen
ok('без texture_mesh — «форма»; с ним — «краска» (код MV-Adapter тот же, `MVAdapterTexBackend.generate`), перед краской TripoSG уходит на процессор', log == ['shape', 'tp->cpu', 'paint'] and r2.get('phase') == 'paint' and r1.get('mode') == 'triposg_shape', str(log))
ok('бэкенд зарегистрирован под именем triposg-mv и наследует MV-Adapter (on_error и охрана формы — те же)', (os.environ.__setitem__('MODEL', 'triposg-mv') or True) and type(W.backend()) is W.TripoSGMVBackend and issubclass(W.TripoSGMVBackend, W.MVAdapterTexBackend) and W.TripoSGMVBackend.name == 'triposg-mv')


def fake_torch(cap, name):
    t = types.ModuleType('torch')
    t.cuda = types.SimpleNamespace(get_device_capability=lambda: cap, get_device_name=lambda: name)
    return t


@contextlib.contextmanager
def torch_as(cap, name, built):
    old_t, old_e = sys.modules.get('torch'), os.environ.get('IMAGE_CUDA_ARCH')
    sys.modules['torch'] = fake_torch(cap, name)
    if built is None:
        os.environ.pop('IMAGE_CUDA_ARCH', None)
    else:
        os.environ['IMAGE_CUDA_ARCH'] = built
    try:
        yield
    finally:
        if old_t is None:
            sys.modules.pop('torch', None)
        else:
            sys.modules['torch'] = old_t
        if old_e is None:
            os.environ.pop('IMAGE_CUDA_ARCH', None)
        else:
            os.environ['IMAGE_CUDA_ARCH'] = old_e


with torch_as((8, 9), 'RTX 4090', '8.9'):
    r = b.check_arch()
ok('воркер: карта 8.9 = образ 8.9 — прогрев идёт', r['card_arch'] == '8.9' and r['image_arch'] == ['8.9'])
with torch_as((8, 6), 'RTX 3090', '8.9'):
    try:
        b.check_arch()
        ok('воркер: карта 8.6, образ 8.9 — отказ на прогреве (до докачки весов), а не «no kernel image» на задании', False)
    except RuntimeError as e:
        ok('воркер: карта 8.6, образ 8.9 — отказ на прогреве (до докачки весов), а не «no kernel image» на задании', '8.6' in str(e) and '8.9' in str(e))
with torch_as((12, 0), 'RTX 5090', None):
    ok('воркер: IMAGE_CUDA_ARCH не задан (чужой образ) — сверка пропускается', b.check_arch()['image_arch'] == [])

print('[6] драйвер: проверка карта ↔ образ и параметры')
ok('card_arch: 4090 → 8.9, 3090 → 8.6, 5090 → 12.0, «RTX 6000 Ada (48 GB)» → 8.9, незнакомая карта → None', T.card_arch('RTX 4090 (24 GB)') == '8.9' and T.card_arch('RTX 3090 (24 GB)') == '8.6'
   and T.card_arch('RTX 5090 (32 GB)') == '12.0' and T.card_arch('RTX 6000 Ada (48 GB)') == '8.9' and T.card_arch('Mystery X (99 GB)') is None)
ok('check_image_arch: 4090 подходит triposg-mv; 3090 и 5090 — нет (с причиной); незнакомая карта — нет; модель без записи (mvadapter-i2tex) не проверяется',
   T.check_image_arch('triposg-mv', 'RTX 4090 (24 GB)')[0] and not T.check_image_arch('triposg-mv', 'RTX 3090 (24 GB)')[0] and not T.check_image_arch('triposg-mv', 'RTX 5090 (32 GB)')[0]
   and 'no kernel image' in T.check_image_arch('triposg-mv', 'RTX 5090 (32 GB)')[1] and not T.check_image_arch('triposg-mv', 'Mystery X (99 GB)')[0] and T.check_image_arch('mvadapter-i2tex', 'RTX 5090 (32 GB)')[0])
ok('tp_options: по умолчанию пусто (воркер берёт 50 шагов и guidance 7,0 апстрима); заданное передаётся; кривое — None', T.tp_options(NS()) == {} and T.tp_options(NS(tp_steps=30, tp_guidance=5.0)) == {'tp_steps': 30, 'tp_guidance': 5.0}
   and T.tp_options(NS(tp_steps=0)) is None and T.tp_options(NS(tp_guidance=99.0)) is None)
b1 = T.build_body('trial-triposg-mv-t', 'ghcr.io/x/mesh-triposg-trial@sha256:abc', 'high', 'triposg-mv', 'hf_SECRET', 8, 40960, 'abc', {'basic': {}})
e1 = b1['container']['environment_variables']
ok('тело группы: MODEL=triposg-mv, код воркера едет в command (python3, без pip на старте), 4090, память 40 ГиБ, приёмника на проде нет',
   e1['MODEL'] == 'triposg-mv' and b1['container']['command'][0] == 'python3' and 'TRIAL_WORKER_Z' in e1 and b1['container']['resources']['memory'] == 40960 and not any(k.startswith(('MESH_SINK', 'QUEUE')) for k in e1)
   and b1['container']['resources']['gpu_classes'] == [T.CARD['class_id']])
ok('HF_GATED: у triposg-mv бесплатная проверка VAST-AI/TripoSG до группы; окружение воркера ему разрешено (WENV_MODELS); память по умолчанию 40 ГиБ', 'VAST-AI/TripoSG' in T.HF_GATED['triposg-mv'] and 'triposg-mv' in T.WENV_MODELS
   and T.TP_MEM_MB == 40960 and 'triposg-mv' not in T.MODEL_MEM_MB)

print('[7] драйвер: две фазы на товар, одна нода (подмена Salad, шлюза и очистки)')
tmp = tempfile.mkdtemp(prefix='tp-')
inp = os.path.join(tmp, 'inputs')
os.makedirs(inp)
SK = ['a:1', 'b:2']
json.dump({k: {'input_png_sha256': 'x', 'role': 'sofa'} for k in SK}, open(os.path.join(inp, 'inputs.json'), 'w'))
for k in SK:
    Image.new('RGBA', (8, 8), (1, 2, 3, 255)).save(os.path.join(inp, k.replace(':', '_') + '.rgba.png'))


class MG:
    def __init__(self):
        self.calls = []

    def env_from_file(self):
        os.environ.setdefault('SALAD_API_KEY', 'k')
        os.environ.setdefault('HF_TOKEN', 'hf_x')

    def ghcr_auth(self):
        return {'basic': {'username': 'u', 'password': 'p'}}

    def api(self, path, method='GET', body=None):
        self.calls.append((method, path))
        if path == '' and method == 'GET':
            return 200, {'items': []}
        if method == 'GET' and path.startswith('/trial-'):
            return (404, {}) if not any(c == ('POST', '') for c in self.calls) else (200, {'networking': {'dns': 'trial.example'}})
        return 200, {}


class BR:
    def __init__(self):
        self.stops = []

    def group_state(self, name):
        return 200, 'stopped', {}

    def instances(self, name):
        return 200, [{'state': 'running'}]

    def stop_and_verify(self, name, timeout_s=300):
        self.stops.append(name)
        return True


class GW:
    """Шлюз: прогрет сразу; задания по сценарию. Форма — «GLB формы» (байты), краска — «GLB краски»."""
    posted: list = []
    fail = {}                                            # job_id (подстрока) → текст ошибки
    clock = None

    def __init__(self, base, key):
        self.jobs = {}

    def call(self, method, path, body=None, timeout=60, raw=False):
        if path == '/health':
            return 200, {'ok': True, 'warm': True, 'phase': 'ready', 'timings': {}, 'child': {'alive': True}, 'cgroup_gb': {'current': 1.0, 'max': 40.0}, 'disk_gb': {'hf': {'free': 50.0, 'total': 80.0}}}
        if path == '/info':
            return 200, {'gpu': {'name': 'RTX 4090'}}
        if path == '/generate':
            GW.posted.append(body)
            self.jobs[body['job_id']] = body
            return 202, {'status': 'queued'}
        if path.startswith('/job/'):
            b = self.jobs[path[5:]]
            for sub, err in GW.fail.items():
                if sub in b['job_id']:
                    return 200, {'status': 'failed', 'error': err, 'diag': {'kind': 'oom' if 'out of memory' in err else 'x', 'fatal': False}}
            return 200, {'status': 'done', 'metrics': {'peak_vram_gb': 17.0, 'phase': 'shape' if b['job_id'].endswith('-tpshape') else 'paint'}}
        if path.startswith('/glb/'):
            return 200, (b'SHAPE-' if path.endswith('-tpshape') else b'PAINT-') + path.split('/')[-1].encode()
        return 404, {}


def run_tp(model='triposg-mv', clean_fn=None, **kw):
    GW.posted = []
    clock = [0.0]

    def sleep(s):
        clock[0] += s
    d = dict(donor='d', set=None, fail_streak=2, model=model, image='ghcr.io/x/mesh-triposg-trial@sha256:abc', inputs=inp, skus=list(SK), plan='1024:1', seed=42, decimation=500000, texture=2048, tier='high', cpu=8, mem_mb=None,
             cap=0.30, max_min=90, ready_min=40, health_min=20, stall_min=10, disk_min_gb=3.0, job_timeout=15, suffix='t1', out=os.path.join(tmp, 'out-' + str(len(os.listdir(tmp)))), apply=True, stop_only=False,
             mv_yaw='auto', mv_uv_size=4096, mv_steps=50, mv_ref_scale=1.0, tp_steps=None, tp_guidance=None, worker_env=[], debug_cuda=False, card=None, gpu=None, gpu_min_gb=40, force_out=False, create_wait_min=30,
             gpu_fetch=lambda: [{'id': T.CARD['class_id'], 'name': 'RTX 4090 (24 GB)', 'prices': [{'priority': 'high', 'price': '0.40'}]}], texture_mesh=None, shape_dir=None, tex_align='fit')
    d.update(kw)
    a = NS(**d)
    mg, br = MG(), BR()
    cleaned_paths = []

    def fake_clean(path, dims_cm=None):
        cleaned_paths.append(path)
        open(path[:-4] + f'.clean{T.TP_CLEAN_TAG}.glb', 'wb').write(b'CLEAN-' + open(path, 'rb').read())
        return {'rule': 'E', 'removed': {'tris': 3}, 'clean_tris': 10, 'primitives': 1}
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = T.run(a, mg, br, gw_factory=GW, sleep=sleep, clock=lambda: clock[0], hf_head=lambda p, t: 200, clean_fn=clean_fn or fake_clean)
    return rc, a, mg, br, buf.getvalue(), cleaned_paths


rc, a, mg, br, txt, cl = run_tp()
order = [p['job_id'] for p in GW.posted]
ok('успех: код 0, группа одна, остановлена с проверкой; порядок заданий — товар целиком (форма → краска), потом следующий', rc == 0 and sum(1 for c in mg.calls if c == ('POST', '')) == 1 and br.stops == ['trial-triposg-mv-t1']
   and order == ['a_1-1024-42-0-tpshape', 'a_1-1024-42-0-tpmv', 'b_2-1024-42-0-tpshape', 'b_2-1024-42-0-tpmv'], str(order))
ok('форма очищена общим правилом (clean_fn вызван на ФАЙЛЕ формы каждого товара), чистая форма едет в задании «краска» (texture_mesh_b64 = очищенный GLB), в задании «форма» формы нет',
   len(cl) == 2 and all(p.endswith('-tpshape.glb') for p in cl) and GW.posted[0].get('texture_mesh_b64') is None
   and base64.b64decode(GW.posted[1]['texture_mesh_b64']).startswith(b'CLEAN-SHAPE-a_1-1024-42-0-tpshape') and base64.b64decode(GW.posted[3]['texture_mesh_b64']).startswith(b'CLEAN-SHAPE-b_2-'))
ok('параметры: «форма» получает tp_* (по умолчанию — ничего), «краска» — mv_* (yaw/uv/steps/ref_scale); у «формы» mv_* нет, у «краски» tp_* нет', 'mv_yaw' not in GW.posted[0] and 'tp_steps' not in GW.posted[1]
   and GW.posted[1]['mv_yaw'] == 'auto' and GW.posted[1]['mv_uv_size'] == 4096 and GW.posted[1]['mv_steps'] == 50)
s = json.load(open(os.path.join(a.out, 'summary-trial-triposg-mv-t1.json')))
ok('итог: stopped_by=done, 4 задания, отказов 0, not_run 0; по товару — форма и краска (статус, GLB), метрики очистки; GLB лежат в папке модели, у каждого метка .model = triposg-mv',
   s['stopped_by'] == 'done' and len(s['jobs']) == 4 and s['failed'] == 0 and s['fail_classes']['not_run'] == 0 and sum(s['fail_classes'].values()) == 0
   and s['by_sku']['a:1']['shape']['status'] == 'done' and s['by_sku']['a:1']['paint']['status'] == 'done' and s['by_sku']['a:1']['clean']['rule'] == 'E' and s['by_sku']['b:2']['paint']['glb'].endswith('b_2-1024-42-0-tpmv.glb')
   and open(os.path.join(a.out, 'a_1-1024-42-0-tpmv.model')).read() == 'triposg-mv' and os.path.isfile(os.path.join(a.out, 'a_1-1024-42-0-tpshape.clean2.glb')), str(s['fail_classes']))
ok('в сводку не попала форма base64 (файл сводки лёгкий)', os.path.getsize(os.path.join(a.out, 'summary-trial-triposg-mv-t1.json')) < 30000)

GW.fail = {'a_1-1024-42-0-tpshape': 'RuntimeError: CUDA out of memory'}
rc, a, mg, br, txt, cl = run_tp(suffix='t2')
s = json.load(open(os.path.join(a.out, 'summary-trial-triposg-mv-t2.json')))
order = [p['job_id'] for p in GW.posted]
ok('«форма» первого товара упала (OOM): краска ЭТОГО товара не создаётся (not_run), второй товар идёт дальше; класс отказа oom_gpu; замер доходит до конца (stopped_by=done, код 0 — как у всех моделей драйвера)', rc == 0 and 'a_1-1024-42-0-tpmv' not in order and 'b_2-1024-42-0-tpmv' in order
   and s['by_sku']['a:1']['shape']['fail_class'] == 'oom_gpu' and s['by_sku']['a:1']['paint']['status'] == 'not_run' and s['fail_classes']['oom_gpu'] == 1 and s['fail_classes']['not_run'] == 1 and s['stopped_by'] == 'done', str(s['fail_classes']) + str(order))
GW.fail = {'-tpmv': 'ShapeChanged: форма изменилась'}
rc, a, mg, br, txt, cl = run_tp(suffix='t3')
s = json.load(open(os.path.join(a.out, 'summary-trial-triposg-mv-t3.json')))
ok('обе «краски» упали, но между ними форма прошла (серия сбрасывается): замер доходит до конца; счётчик по классам shape_changed=2, формы обоих товаров сохранены, stop_verified',
   s['stopped_by'] == 'done' and s['fail_classes']['shape_changed'] == 2 and s['stop_verified'] and s['by_sku']['b:2']['shape']['status'] == 'done' and s['by_sku']['b:2']['paint']['fail_class'] == 'shape_changed', str(s['fail_classes']) + s['stopped_by'])
GW.fail = {'-tpshape': 'RuntimeError: boom'}
rc, a, mg, br, txt, cl = run_tp(suffix='t3b')
s = json.load(open(os.path.join(a.out, 'summary-trial-triposg-mv-t3b.json')))
ok('две «формы» подряд упали — стоп по серии (fail_streak=2, чинить в коде, не жечь деньги); other=2, не дошедшие до запуска — not_run=2; группа остановлена с проверкой', s['stopped_by'] == 'failures' and s['fail_classes']['other'] == 2
   and s['fail_classes']['not_run'] == 2 and s['stop_verified'], str(s['fail_classes']) + s['stopped_by'])
GW.fail = {}


def bad_clean(path, dims_cm=None):
    raise RuntimeError('trimesh: битый GLB')
rc, a, mg, br, txt, cl = run_tp(suffix='t4', clean_fn=bad_clean)
s = json.load(open(os.path.join(a.out, 'summary-trial-triposg-mv-t4.json')))
ok('сбой очистки (mesh_clean) — отказ задания «форма» с причиной «очистка формы», а не падение замера; краска не создаётся; 2 отказа подряд — стоп', s['failed'] == 2 and 'очистка формы' in s['by_sku']['a:1']['shape']['error'] and s['by_sku']['a:1']['paint']['status'] == 'not_run'
   and s['stopped_by'] == 'failures' and s['stop_verified'], str(s['by_sku']['a:1']['shape']))
rc, a, mg, br, txt, cl = run_tp(suffix='t5', cap=0.0001)
s = json.load(open(os.path.join(a.out, 'summary-trial-triposg-mv-t5.json')))
ok('потолок денег срабатывает и в двухфазном замере: stopped_by=money, группа остановлена с проверкой; всё не дошедшее — not_run (4)', s['stopped_by'] == 'money' and s['stop_verified'] and s['fail_classes']['not_run'] == 4, str(s['fail_classes']))
rc, a, mg, br, txt, cl = run_tp(suffix='t6', card='RTX 3090 (24 GB)', gpu_fetch=lambda: [{'id': 'x', 'name': 'RTX 3090 (24 GB)', 'prices': [{'priority': 'high', 'price': '0.3'}]}])
ok('карта 3090 для образа 8.9: отказ (код 2) ДО создания группы — в Salad не было ни одного POST, денег 0', rc == 2 and not any(c[0] == 'POST' for c in mg.calls), str(mg.calls))
rc, a, mg, br, txt, cl = run_tp(suffix='t7', apply=False)
ok('сухой прогон: код 0, ни одного POST, в печати оба задания (форма → краска), проверка «карта ↔ образ» пройдена, цена живая', rc == 0 and not any(c[0] == 'POST' for c in mg.calls) and '-tpshape' in txt and 'затем краска a_1-1024-42-0-tpmv' in txt
   and 'входит в сборку образа' in txt and 'живая' in txt, txt[:400])
for kw, name in (({'tp_steps': 0}, '--tp-steps 0'), ({'mv_yaw': '45'}, '--mv-yaw 45')):
    class Never:
        def __getattr__(self, k):
            raise AssertionError('Salad тронут до проверки аргументов: ' + k)
    a2 = NS(**{**vars(a), **kw, 'skus': ['a:1']})
    with redirect_stdout(io.StringIO()):
        try:
            rc2 = T.run(a2, Never(), Never())
        except AssertionError as e:
            rc2 = str(e)
    ok(f'{name}: отказ (код 2) до обращения к Salad', rc2 == 2, str(rc2))

print('ИТОГО: ' + ('всё в норме' if not bad else f'провалов {bad}'))
sys.exit(1 if bad else 0)
