#!/usr/bin/env python3
"""Тесты `supratex` — SUPRA-Tex КАК ЕСТЬ (с Qwen-Image-2.1) по готовой форме TRELLIS.2 (T-20261119-06/5): сдвиг наблюдения под нашу форму, кадр выпуска и расстояние к исходной форме
(ФОРМА И РАЗВЁРТКА МЕНЯЮТСЯ — вместо «не изменилась» замеры граней до/после и Хаусдорфа), геометрия `geometry.npz`, сборка команд апстрима, подпроцесс с журналом/таймаутом, докачка весов
на подмене Hugging Face, отказ без формы, фатальная ошибка CUDA в подпроцессе → «сломан», драйвер (тело группы, память 48 ГиБ, имя задания, своя папка результатов).
Без видеокарты, сети, ключей, torch и SUPRA-Tex. Разделы 1, 3, 4 — numpy/PIL (идут в CI); раздел 2 (настоящий trimesh) пропускается без trimesh.

  python3 tools/scout/salad/trellis/tests_supratex.py
"""
from __future__ import annotations

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
remlab_tmp.use('tests_supratex')
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402
import worker_trellis as W  # noqa: E402

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
    """Несимметричная фигура (буква Г из двух коробок, Y вверх): повороты, обмен осей и зеркала различимы по расстоянию."""
    return merge(box((-0.30, -0.30, -0.10), (0.30, -0.10, 0.10)), box((-0.30, -0.10, -0.10), (-0.10, 0.30, 0.10)))


def split3(v, f):
    """Каждый треугольник → три (вершина в центре): «ремеш» с другим числом граней и вершин на той же поверхности."""
    cen = v[f].mean(axis=1)
    nv = np.concatenate([v, cen])
    k = len(v)
    nf = []
    for i, (a, b, c) in enumerate(f):
        nf += [[a, b, k + i], [b, c, k + i], [c, a, k + i]]
    return nv, np.array(nf)


V, F = l_shape()
print('[1] чистые функции (numpy/PIL)')
a = np.arange(5 * 6 * 3).reshape(5, 6, 3).astype(np.uint8) + 1
s = W.supra_shift(a, 2, 1, 0)
ok('supra_shift: содержимое уходит вправо на 2 и вниз на 1, пустое — fill, размер тот же', s.shape == a.shape and (s[0] == 0).all() and (s[:, :2] == 0).all() and np.array_equal(s[1:, 2:], a[:-1, :-2]))
s = W.supra_shift(a, -3, -2, 9)
ok('supra_shift: отрицательные сдвиги (влево и вверх), fill=9', np.array_equal(s[:3, :3], a[2:, 3:]) and (s[3:] == 9).all() and (s[:, 3:] == 9).all())
ok('supra_shift: сдвиг больше кадра → всё fill; нулевой — копия', (W.supra_shift(a, 10, 0, 7) == 7).all() and np.array_equal(W.supra_shift(a, 0, 0, 7), a) and W.supra_shift(a, 0, 0, 7) is not a)

case = tempfile.mkdtemp(prefix='supra-case-')
cond = np.zeros((100, 100, 4), dtype=np.uint8)
cond[40:60, 40:60] = (200, 100, 50, 255)
Image.fromarray(cond).save(os.path.join(case, 'condition_rgba.png'))
Image.fromarray(cond[:, :, :3]).save(os.path.join(case, 'condition_rgb.png'))
alb = np.zeros((64, 64, 3), dtype=np.uint8)
alb[20:30, 20:30] = (10, 200, 10)
Image.fromarray(alb).save(os.path.join(case, 'albedo.png'))
Image.fromarray(alb).save(os.path.join(case, 'mra.png'))
dep = np.full((100, 100), 2.0, dtype=np.float32)
np.save(os.path.join(case, 'image_depth.npy'), dep)
json.dump({'camera_angle_x': 0.8, 'distance': 1.2, 'mesh_scale': 1.0}, open(os.path.join(case, 'camera.json'), 'w'))
info = W.supra_prepare_case(case, {'tx': 0.1, 'ty': -0.05, 'mesh_scale': 1.3, 'yaw_deg': 0})
c2 = np.asarray(Image.open(os.path.join(case, 'condition_rgba.png')))
al2 = np.asarray(Image.open(os.path.join(case, 'albedo.png')))
d2 = np.load(os.path.join(case, 'image_depth.npy'))
cam2 = json.load(open(os.path.join(case, 'camera.json')))
ok('сдвиг по долям кадра tx=0,1, ty=−0,05: фото 100 px → вправо 10, вверх 5; карты 64 px → вправо 6, вверх 3',
   info['dx_cond'] == 10 and info['dy_cond'] == -5 and info['dx_map'] == 6 and info['dy_map'] == -3 and c2[35, 50, 3] == 255 and c2[40, 40, 3] == 0 and al2[17, 26, 1] == 200 and al2[20, 20, 1] == 0, str(info))
ok('image_depth.npy сдвинут вместе с фото; пустое место — NaN (а не 0), размер сохранён', d2.shape == (100, 100) and np.isnan(d2[:, :10]).all() and np.isnan(d2[95:]).all() and d2[0, 10] == 2.0 and d2.dtype == np.float32)
ok('camera.json: mesh_scale из подгонки (1,3), остальное не тронуто', cam2['mesh_scale'] == 1.3 and cam2['camera_angle_x'] == 0.8 and cam2['distance'] == 1.2)

Vc, c_, s_, R_ = W.to_cube(V, 0.0)
# кадр выпуска: как апстрим (`to_glb` обмен осей + M) — вместе поворот на 180° вокруг Y; ещё два кандидата — на случай, если апстрим окажется не таким
out_rot = Vc @ W.rot_y(180).T
name, back_cube, dist = W.supra_pick_frame(out_rot, Vc)
ok('кадр выпуска = поворот на 180° вокруг Y: найден по минимуму расстояния, вершины вернулись в куб', name == 'rot_y_180' and np.allclose(back_cube, Vc, atol=1e-9) and dist['rot_y_180'] < 1e-6 < min(dist['identity'], dist['swap_xz']), str(dist))
ident, _, _ = W.supra_pick_frame(Vc.copy(), Vc)
swapped = np.stack([Vc[:, 0], Vc[:, 2], -Vc[:, 1]], axis=1)                  # (x,y,z) → (x,z,−y)
nm_s, bc_s, _ = W.supra_pick_frame(swapped, Vc)
swapped2 = np.stack([Vc[:, 0], -Vc[:, 2], Vc[:, 1]], axis=1)
nm_s2, bc_s2, _ = W.supra_pick_frame(swapped2, Vc)
ok('кадры-запасные: тождество → identity; обмен осей (x,z,−y) → unswap_xz; обратный → swap_xz; во всех случаях вершины легли на вход',
   ident == 'identity' and nm_s == 'unswap_xz' and np.allclose(bc_s, Vc) and nm_s2 == 'swap_xz' and np.allclose(bc_s2, Vc))
ok('перебор кадров: четыре имени из SUPRA_FRAMES, и все кандидаты — того же размера', set(W.supra_frame_candidates(Vc)) == set(W.SUPRA_FRAMES) and all(v.shape == Vc.shape for v in W.supra_frame_candidates(Vc).values()))

V3, F3 = split3(V, F)
m0 = W.supra_shape_metrics(V, F, V3, F3, n=20000)
ok('замеры формы: «ремеш» на той же поверхности — граней в 3 раза больше (24 → 72), расстояние к исходной малое (макс < 0,05 диагонали)', m0['faces_in'] == 24 and m0['faces_out'] == 72 and m0['faces_ratio'] == 3.0 and m0['hausdorff_rel'] < 0.05 and m0['mean_rel'] < 0.02 and {'p99_rel', 'diag', 'verts_in', 'verts_out'} <= set(m0), str(m0))
m1 = W.supra_shape_metrics(V, F, V3 + np.array([0.3, 0.0, 0.0]), F3, n=20000)
ok('сдвинутая копия: расстояние растёт (≥ 0,2 диагонали по максимуму), среднее больше, чем у чистой', m1['hausdorff_rel'] >= 0.2 and m1['mean_rel'] > m0['mean_rel'] * 3, str(m1))
m2 = W.supra_shape_metrics(V, F, V3 * 1.5, F3, n=20000)
ok('увеличенная в 1,5 раза форма — Хаусдорф заметно выше «чистого»', m2['hausdorff_rel'] > 0.15 > m0['hausdorff_rel'], str(m2))
ok('манифест весов: из файла апстрима, если он есть; иначе зеркало с тремя пинами по 40 знаков', (lambda d: (os.makedirs(os.path.join(d, 'configs')), json.dump({'external_models': {k: {'repo_id': 'r/' + k, 'revision': 'f' * 40, 'allow_patterns': ['x']} for k in W.SUPRA_PINS}}, open(os.path.join(d, 'configs', 'pipeline.json'), 'w')),
                                                                W.supra_manifest(d))[2])(tempfile.mkdtemp(prefix='supra-man-'))['qwen-base']['revision'] == 'f' * 40
   and set(W.supra_manifest('/nonexistent')) == {'qwen-base', 'moge2', 'vae'} and all(len(v['revision']) == 40 for v in W.supra_manifest('/nonexistent').values()))
ok('закреплённые ревизии: Qwen-Image-2.1 d26bb612…, дополнение SUPRA 1bc02eb9…; закрытых весов (DINOv3, RMBG-2) в списке нет', W.SUPRA_PINS['qwen-base']['revision'].startswith('d26bb612') and W.SUPRA_REV.startswith('1bc02eb9') and set(W.SUPRA_PINS) == {'qwen-base', 'moge2', 'vae'})

print('[1b] подпроцесс стадии (настоящие подпроцессы Python)')
td0 = tempfile.mkdtemp(prefix='supra-run-')
r = W.run_logged([sys.executable, '-c', 'print("привет"); import sys; print("err", file=sys.stderr)'], dict(os.environ), None, 30, os.path.join(td0, 'a.log'), poll_s=0.1)
ok('успех: rc 0, журнал на диске (stdout и stderr вместе), хвост, замеры', r['rc'] == 0 and 'привет' in r['tail'] and 'err' in r['tail'] and 'привет' in open(os.path.join(td0, 'a.log'), encoding='utf-8').read() and {'s', 'peak_vram_mib', 'peak_cgroup_gb', 'child_maxrss_gb'} <= set(r), str(r))
try:
    W.run_logged([sys.executable, '-c', 'import sys; print("CUDA error: an illegal memory access was encountered"); sys.exit(1)'], dict(os.environ), None, 30, os.path.join(td0, 'b.log'), poll_s=0.1)
    ok('падение подпроцесса — SupraStageError', False)
except W.SupraStageError as e:
    ok('падение: SupraStageError с кодом выхода и хвостом журнала; классификатор видит ФАТАЛЬНУЮ ошибку CUDA', 'код выхода 1' in str(e) and 'illegal memory access' in str(e) and W.classify_cuda_error(e) == 'fatal', str(e)[:200])
try:
    W.run_logged([sys.executable, '-c', 'print("CUDA out of memory. Tried to allocate 2 GiB"); import sys; sys.exit(1)'], dict(os.environ), None, 30, os.path.join(td0, 'c.log'), poll_s=0.1)
except W.SupraStageError as e:
    ok('нехватка видеопамяти в подпроцессе — oom (не фатальная: воркер цел)', W.classify_cuda_error(e) == 'oom', str(e)[:200])
try:
    W.run_logged([sys.executable, '-c', 'import time; time.sleep(20)'], dict(os.environ), None, 1, os.path.join(td0, 'd.log'), poll_s=0.1)
except W.SupraStageError as e:
    ok('таймаут: подпроцесс остановлен, ошибка названа, не фатальная', 'таймаут 1' in str(e) and W.classify_cuda_error(e) == 'other', str(e)[:200])
try:
    W.run_logged([sys.executable, '-c', 'import os, signal; os.kill(os.getpid(), signal.SIGKILL)'], dict(os.environ), None, 30, os.path.join(td0, 'e.log'), poll_s=0.1)
except W.SupraStageError as e:
    ok('убит по памяти (−9): в тексте «по памяти группы», не фатальная ошибка CUDA', 'по памяти группы' in str(e) and W.classify_cuda_error(e) == 'other', str(e)[:200])

print('[1c] команды апстрима (подмена запуска)')
calls = []


def fake_run(cmd, env, cwd, timeout, log_path, poll_s=2.0):
    calls.append({'cmd': cmd, 'env': env, 'cwd': cwd, 'timeout': timeout, 'log': log_path})
    return {'rc': 0, 's': 1.0, 'peak_vram_mib': 11000, 'peak_cgroup_gb': 20.5, 'child_maxrss_gb': 18.0, 'tail': 'x\nObservation: silhouette IoU 0.931\n'}


os.environ['HF_TOKEN'] = 'hf_SECRET'
paths = {'moge': '/w/moge/model.pt', 'qwen': '/w/qwen', 'material': '/w/proj/material', 'completion': '/w/proj/completion', 'vae': '/w/vae'}
rn = W.SupraRunner('/opt/SUPRA-Tex', paths, work_log=td0, run=fake_run, python='/usr/bin/python3')
rn.frontend('/w/p.png', '/w/front')
cmd = calls[-1]['cmd']
ok('фронт: python -m supratex.frontend.pipeline, вход/выход, --use-input-alpha, MoGe/Qwen/адаптер материала — локальные папки, без сети; sdpa и low-vram',
   cmd[:3] == ['/usr/bin/python3', '-m', 'supratex.frontend.pipeline'] and cmd[cmd.index('--moge-model') + 1] == '/w/moge/model.pt' and cmd[cmd.index('--material-base') + 1] == '/w/qwen' and cmd[cmd.index('--material-model') + 1] == '/w/proj/material'
   and {'--use-input-alpha', '--local-files-only', '--low-vram'} <= set(cmd) and cmd[cmd.index('--attention') + 1] == 'sdpa' and calls[-1]['cwd'] == '/opt/SUPRA-Tex' and calls[-1]['timeout'] == W.SUPRA_STAGE_TIMEOUT, str(cmd))
env = calls[-1]['env']
ok('окружение подпроцесса: PYTHONNOUSERSITE, офлайн-режим HF, автонастройка FlexGEMM выключена, PYTHONPATH с корнем апстрима; токен Hugging Face подпроцессу НЕ передаётся',
   env['PYTHONNOUSERSITE'] == '1' and env['HF_HUB_OFFLINE'] == '1' and env['FLEX_GEMM_USE_AUTOTUNE_CACHE'] == '0' and env['PYTHONPATH'].split(os.pathsep)[0] == '/opt/SUPRA-Tex' and 'HF_TOKEN' not in env and os.environ.get('HF_TOKEN') == 'hf_SECRET')
res = rn.texturing('/w/case', '/w/o.glb', {'seed': 7})
cmd = calls[-1]['cmd']
ok('текстурирование: texturing.py по умолчанию 4096 / 500000 / seed / sdpa / low-vram, без --refine; IoU «Observation» разобран из журнала',
   cmd[1].endswith('texturing.py') and cmd[cmd.index('--texture-size') + 1] == '4096' and cmd[cmd.index('--decimation-target') + 1] == '500000' and cmd[cmd.index('--seed') + 1] == '7' and '--refine' not in cmd
   and cmd[cmd.index('--pretrained') + 1] == '/w/proj/completion' and cmd[cmd.index('--trellis-root') + 1] == '/w/vae' and cmd[cmd.index('--input-dir') + 1] == '/w/case' and cmd[cmd.index('--output') + 1] == '/w/o.glb'
   and res['observation_iou'] == 0.931 and res['texture_size'] == 4096 and res['refine'] is False, str(cmd))
rn.texturing('/w/case', '/w/o2.glb', {'supra_refine': True, 'supra_texture_size': 2048, 'supra_decimation': 100000})
cmd = calls[-1]['cmd']
ok('параметры задания доезжают: --refine, 2048, 100000', '--refine' in cmd and cmd[cmd.index('--texture-size') + 1] == '2048' and cmd[cmd.index('--decimation-target') + 1] == '100000')
os.environ.pop('HF_TOKEN', None)

print('[2] путь вызова на заглушке апстрима (trimesh)')
try:
    import trimesh
    have_tm = True
except ImportError:
    have_tm = False
    print('  · SKIP: нет trimesh в этом окружении (проверяется на pakardev)')
if have_tm:
    fov = 0.8
    dist = 0.5 / np.tan(fov / 2)

    def condition_photo(Vx, Fx, yaw):
        """Фото, как его кладёт фронт SUPRA: силуэт формы в камере SUPRA (mesh_scale 1) на квадрате 192² — подгонка должна найти тот же поворот и почти нулевой сдвиг."""
        p = W.to_cube(Vx, yaw)[0]
        u, v, _d = W.project_cube(p, fov, dist, 1.0)
        M = W.surface_mask(u, v, Fx, 192)
        rgba = np.stack([np.where(M, 190, 0), np.where(M, 120, 0), np.where(M, 60, 0), M * 255], axis=-1).astype(np.uint8)
        return Image.fromarray(rgba, 'RGBA')

    class FakeRunner:
        """Две стадии апстрима на заглушке. `frontend` кладёт результат в ПОДПАПКУ (как апстрим по --key); `texturing` читает `geometry.npz`, делает «ремеш» (×3 грани), НОВУЮ развёртку
        и отдаёт выпуск в кадре апстрима (поворот на 180° вокруг Y)."""
        def __init__(self, scale_out=1.0, no_tex=False, frame_rot=True):
            self.calls, self.scale_out, self.no_tex, self.frame_rot, self.work_log = [], scale_out, no_tex, frame_rot, None

        def frontend(self, photo, out_dir):
            self.calls.append(('frontend', os.path.basename(photo), Image.open(photo).mode))
            d = os.path.join(out_dir, 'input')
            os.makedirs(d)
            self.photo_in = Image.open(photo).convert('RGBA')
            condition_photo(*self.shape, self.yaw).save(os.path.join(d, 'condition_rgba.png'))
            Image.new('RGB', (64, 64), (200, 30, 30)).save(os.path.join(d, 'albedo.png'))
            Image.new('RGB', (64, 64), (0, 120, 0)).save(os.path.join(d, 'mra.png'))
            json.dump({'camera_angle_x': fov, 'distance': dist, 'mesh_scale': 1.0}, open(os.path.join(d, 'camera.json'), 'w'))
            return {'rc': 0, 's': 10.0, 'peak_vram_mib': 12000, 'peak_cgroup_gb': 25.0, 'child_maxrss_gb': 20.0}

        def texturing(self, case, out_glb, params):
            self.calls.append(('texturing', os.path.basename(case), params.get('supra_texture_size')))
            with np.load(os.path.join(case, 'geometry.npz')) as z:
                self.geom = {'verts': z['verts'].copy(), 'faces': z['faces'].copy()}
            self.cam = json.load(open(os.path.join(case, 'camera.json')))
            v, f = split3(self.geom['verts'].astype(np.float64), self.geom['faces'])
            v = (v @ W.rot_y(180).T if self.frame_rot else v) * self.scale_out
            uv = np.random.default_rng(1).random((len(v), 2))
            mat = trimesh.visual.material.PBRMaterial(baseColorTexture=None if self.no_tex else Image.new('RGB', (128, 128), (30, 200, 90)))
            trimesh.Trimesh(vertices=v, faces=f, visual=trimesh.visual.TextureVisuals(uv=uv, material=mat), process=False).export(out_glb)
            return {'rc': 0, 's': 20.0, 'peak_vram_mib': 15000, 'peak_cgroup_gb': 31.0, 'child_maxrss_gb': 30.5, 'observation_iou': 0.95}

    shift = np.array([0.4, 0.15, -0.2])
    Vi = V * 0.8 + shift
    mesh_in = trimesh.Trimesh(vertices=Vi, faces=F, process=False)                    # без развёртки: SUPRA делает свою — входная не нужна
    photo0 = Image.new('RGBA', (300, 200), (10, 20, 30, 255))
    wk = tempfile.mkdtemp(prefix='sup-w-')
    ev: list = []
    rn = FakeRunner()
    rn.shape, rn.yaw = (Vi, F), 0
    final, mt = W.supra_texture_on_shape(rn, mesh_in, photo0, {'supra_texture_size': 2048}, {'mem': lambda n_: ev.append(n_)}, wk)
    ok('порядок стадий: фронт → текстурирование; фото ушло как RGBA; параметры доехали', [c[0] for c in rn.calls] == ['frontend', 'texturing'] and rn.calls[0][2] == 'RGBA' and rn.calls[1][2] == 2048, str(rn.calls))
    ok('в апстрим ушёл КУБ (|v| ≤ 0,5): float32, грани int32, ТЕ ЖЕ грани, что у входа; подпапка результата фронта найдена',
       rn.geom['verts'].dtype == np.float32 and rn.geom['faces'].dtype == np.int32 and np.abs(rn.geom['verts']).max() <= 0.5 + 1e-6 and np.array_equal(rn.geom['faces'], F) and rn.geom['verts'].shape == Vi.shape)
    ok('подгонка нашла поворот 0° и совпадение силуэта (IoU > 0,9); mesh_scale записан в camera.json', mt['fit']['yaw_deg'] == 0 and mt['fit']['iou'] > 0.9 and abs(rn.cam['mesh_scale'] - mt['fit']['mesh_scale']) < 1e-9 and mt['camera']['fov'] == fov, str(mt['fit']))
    ok('кадр выпуска угадан по цифрам: rot_y_180; вершины итога вернулись в ИСХОДНЫЙ кадр и масштаб (метры), расстояние к исходной форме малое (< 0,05 диагонали)',
       mt['shape']['out_frame'] == 'rot_y_180' and mt['shape']['hausdorff_rel'] < 0.05 and np.abs(np.asarray(final.vertices) - shift).max() < 0.7 and np.allclose(np.asarray(final.vertices).mean(axis=0), Vi.mean(axis=0), atol=0.1), str(mt['shape']))
    ok('замеры формы: грани до 24, после 72 (развёртка и ремеш апстрима), вершин до 16, после 40; форма НЕ отвергается', mt['shape']['faces_in'] == 24 and mt['shape']['faces_out'] == 72 and len(final.faces) == 72 and mt['mesh_tris'] == 24 and mt['shape']['verts_out'] == 40)
    ok('развёртка выпуска — СВОЯ (случайная в заглушке), а не входная; текстура 128², IoU апстрима (0,95) вынесен наверх', len(final.visual.uv) == 40 and mt['tex_size'] == [128, 128] and mt['observation_iou'] == 0.95)
    ok('стадии: prepare, material, fit, write_case, texturing, metrics; замер памяти после каждой', list(mt['stage_s']) == ['prepare', 'material', 'fit', 'write_case', 'texturing', 'metrics'] and ev == list(mt['stage_s']), str(ev))
    # выпуск не в нашем кадре (идентичность): кадр определяется заново, а не принимается на веру
    rn_i = FakeRunner(frame_rot=False)
    rn_i.shape, rn_i.yaw = (Vi, F), 0
    _f, m_i = W.supra_texture_on_shape(rn_i, mesh_in, photo0, {}, None, tempfile.mkdtemp(prefix='sup-w-'))
    ok('если апстрим выдаст форму без поворота — кадр identity, расстояние снова малое (ошибка допущения видна в метрике)', m_i['shape']['out_frame'] == 'identity' and m_i['shape']['hausdorff_rel'] < 0.05, str(m_i['shape']))
    # форма, которую апстрим сильно изменил, НЕ приводит к исключению — только к цифрам
    rn_s = FakeRunner(scale_out=1.6)
    rn_s.shape, rn_s.yaw = (Vi, F), 0
    _f, m_s = W.supra_texture_on_shape(rn_s, mesh_in, photo0, {}, None, tempfile.mkdtemp(prefix='sup-w-'))
    ok('форма увеличена апстримом в 1,6 раза: исключения нет, Хаусдорф в замерах > 0,15 (решает тот, кто читает)', m_s['shape']['hausdorff_rel'] > 0.15, str(m_s['shape']))
    try:
        rt = FakeRunner(no_tex=True)
        rt.shape, rt.yaw = (Vi, F), 0
        W.supra_texture_on_shape(rt, mesh_in, photo0, {}, None, tempfile.mkdtemp(prefix='sup-w-'))
        ok('апстрим вернул GLB без текстуры — отказ', False)
    except RuntimeError as e:
        ok('апстрим вернул GLB без текстуры — отказ с причиной', 'без текстуры' in str(e))
    # фото повёрнуто на 90°: подгонка находит поворот, в куб уходит повёрнутая форма
    rn90 = FakeRunner()
    rn90.shape, rn90.yaw = (Vi, F), 90
    _f, m90 = W.supra_texture_on_shape(rn90, mesh_in, photo0, {}, None, tempfile.mkdtemp(prefix='sup-w-'))
    ok('фото с 90°: поворот найден, в куб ушла форма, повёрнутая на 90°, итог — снова в исходном кадре', m90['fit']['yaw_deg'] == 90 and np.allclose(rn90.geom['verts'], W.to_cube(Vi, 90)[0], atol=1e-5) and m90['shape']['hausdorff_rel'] < 0.05, str(m90['fit']))
    # фронт без нужных файлов
    d_empty = tempfile.mkdtemp(prefix='sup-e-')
    try:
        W.supra_find_case(d_empty)
        ok('пустой результат фронта — отказ', False)
    except W.SupraStageError as e:
        ok('пустой результат фронта — SupraStageError с перечнем файлов', 'albedo.png' in str(e))

    # настоящий `generate` бэкенда: файл в OUT, рабочая папка убрана, выход не в `trellis/`, пики из стадий
    sav = {k: getattr(W, k) for k in ('JOBS_DIR', 'OUT', 'STATE_PATH', 'BACKEND')}
    sav_state = dict(W.STATE)
    td = tempfile.mkdtemp(prefix='supb-')
    W.JOBS_DIR, W.OUT, W.STATE_PATH = os.path.join(td, 'jobs'), os.path.join(td, 'out'), os.path.join(td, 'state.json')
    os.makedirs(W.JOBS_DIR)
    os.makedirs(W.OUT)
    try:
        os.environ['MODEL'] = 'supratex'
        be = W.backend()
        ok('MODEL=supratex → SupraTexBackend (без загрузки)', type(be).__name__ == 'SupraTexBackend' and be.name == 'supratex')
        os.environ['MODEL'] = 'mvadapter-i2tex'
        ok('MODEL=mvadapter-i2tex — прежний бэкенд, не затронут', type(W.backend()).__name__ == 'MVAdapterTexBackend')
        os.environ.pop('MODEL', None)
        try:
            be.generate(Image.new('RGBA', (8, 8)), {'job_id': 'x'}, os.path.join(W.OUT, 'x.glb'))
            ok('без формы (--texture-mesh) бэкенд отказывает сразу', False)
        except ValueError as e:
            ok('без формы (--texture-mesh) бэкенд отказывает сразу, до подпроцессов и видеокарты', 'texture-mesh' in str(e))
        mesh_in.export(os.path.join(W.JOBS_DIR, 'j1-supra.mesh.glb'))
        gen = FakeRunner()
        gen.shape, gen.yaw = (Vi, F), 0
        be.runner = gen
        out_path = os.path.join(W.OUT, 'j1-supra.glb')
        met = be.generate(photo0, {'job_id': 'j1-supra', 'texture_mesh': True, 'supra_texture_size': 2048}, out_path)
        ok('generate: GLB записан; режим supratex; пики по стадиям (видеопамять 15000 МиБ, память группы 31 ГБ, дети 30,5 ГБ); форма меняется — грани до/после в замерах',
           os.path.exists(out_path) and met['mode'] == 'supratex' and met['peak_vram_mib'] == 15000 and met['peak_cgroup_gb'] == 31.0 and met['child_maxrss_gb'] == 30.5 and met['shape']['faces_out'] == 72 and 'load_shape' in met['stage_s']
           and met['stage_s']['front_s'] == 10.0 and met['stage_s']['texturing_s'] == 20.0 and 'start' in met['mem'] and 'texturing' in met['mem'], str(met)[:300])
        ok('рабочая папка задания убрана (в OUT только результат)', sorted(os.listdir(W.OUT)) == ['j1-supra.glb'], str(os.listdir(W.OUT)))
        got = trimesh.load(out_path, force='mesh', process=False)
        ok('результат читается: 72 грани, текстура 128², вершины в кадре входа', len(got.faces) == 72 and got.visual.material.baseColorTexture.size == (128, 128) and np.abs(np.asarray(got.vertices).mean(axis=0) - Vi.mean(axis=0)).max() < 0.1)
        for exc, want, fatal in ((W.SupraStageError('texturing.py: код выхода 1; хвост журнала: CUDA error: an illegal memory access was encountered'), 'fatal', True),
                                 (W.SupraStageError('frontend: код выхода 1; хвост журнала: torch.OutOfMemoryError: CUDA out of memory.'), 'oom', False), (ValueError('форма: нет мешей'), 'other', False)):
            d = be.on_error(exc)
            ok(f'on_error: «{str(exc)[:45]}…» → {want}, fatal={fatal}', d['kind'] == want and d['fatal'] is fatal and 'stage_mem' in d and 'cgroup' in d, str(d)[:200])

        class Boom(W.SupraTexBackend):
            def generate(self, image, params, path):
                raise W.SupraStageError('texturing.py: код выхода 1; хвост журнала: CUDA driver error: device not ready')
        W.BACKEND = Boom()
        W.STATE.update(phase='ready', warm=True, error=None)
        W.STATE.pop('broken', None)
        Image.new('RGBA', (8, 8), (1, 2, 3, 255)).save(os.path.join(W.JOBS_DIR, 'b1.png'))
        open(os.path.join(W.JOBS_DIR, 'b1.req.json'), 'w').write(json.dumps({'job_id': 'b1', 'texture_mesh': True}))
        W.run_job('b1')
        rb = json.load(open(os.path.join(W.JOBS_DIR, 'b1.res.json'), encoding='utf-8'))
        ok('фатальная ошибка CUDA в подпроцессе: failed, diag.fatal, воркер помечен сломанным (/health ok=false) — драйвер гасит группу', rb['status'] == 'failed' and rb['diag']['fatal'] is True and 'device not ready' in str(W.STATE.get('broken'))
           and W.health()['ok'] is False, str(rb.get('diag'))[:200])
    finally:
        for k, v in sav.items():
            setattr(W, k, v)
        W.STATE.clear()
        W.STATE.update(sav_state)
        os.environ.pop('MODEL', None)

print('[2b] докачка весов на подмене Hugging Face и проверка импортов')
dl_calls = []


def fake_snapshot_download(repo_id, revision=None, allow_patterns=None, **kw):
    d = tempfile.mkdtemp(prefix='hf-')
    for sub in ('completion', 'material'):
        os.makedirs(os.path.join(d, sub))
    open(os.path.join(d, 'model.pt'), 'wb').write(b'x' * 10)
    dl_calls.append((repo_id, revision, list(allow_patterns or []), sorted(kw)))
    return d


hub = types.ModuleType('huggingface_hub')
hub.snapshot_download = fake_snapshot_download
hub_keep = sys.modules.get('huggingface_hub')
sys.modules['huggingface_hub'] = hub
run_keep = W.subprocess.run
sav2 = dict(W.STATE)
try:
    W.subprocess.run = lambda *a_, **k_: types.SimpleNamespace(returncode=0, stdout='imports ok', stderr='')
    buf = io.StringIO()
    with redirect_stdout(buf):
        lm = W.SupraTexBackend().load()
    repos = [c[0] for c in dl_calls]
    ok('докачка: проектный репозиторий SUPRA, Qwen-Image-2.1, MoGe-2, VAE TRELLIS.2 — по закреплённым ревизиям; закрытых весов (DINOv3, RMBG-2) не просим',
       repos == ['supra3d/supra-tex', 'Qwen/Qwen-Image-2.1', 'Ruicheng/moge-2-vitl-normal', 'microsoft/TRELLIS.2-4B'] and dl_calls[0][1] == W.SUPRA_REV and dl_calls[1][1] == W.SUPRA_PINS['qwen-base']['revision']
       and dl_calls[0][2] == W.SUPRA_PATTERNS and 'transformer/*' in dl_calls[1][2] and not any('dino' in r_.lower() or 'rmbg' in r_.lower() for r_ in repos), str(dl_calls)[:300])
    ok('прогрев: тайминги и размеры по частям, проверка импортов пройдена; в журнал токен не попал', set(lm['download_s']) == {'project', 'qwen', 'moge', 'vae'} and 'weights_s' in lm and 'hf_' not in buf.getvalue(), str(lm)[:200])
    W.subprocess.run = lambda *a_, **k_: types.SimpleNamespace(returncode=1, stdout='', stderr='ModuleNotFoundError: No module named o_voxel')
    try:
        with redirect_stdout(io.StringIO()):
            W.SupraTexBackend().load()
        ok('импорты SUPRA не прошли — прогрев падает с причиной', False)
    except RuntimeError as e:
        ok('импорты SUPRA не прошли — прогрев падает с причиной (модуль назван), видеокарта не тронута', 'o_voxel' in str(e))
finally:
    W.subprocess.run = run_keep
    W.STATE.clear()
    W.STATE.update(sav2)
    if hub_keep is None:
        sys.modules.pop('huggingface_hub', None)
    else:
        sys.modules['huggingface_hub'] = hub_keep

print('[3] драйвер')
import trellis_trial as T  # noqa: E402
b = T.build_body('trial-supratex-x', 'ghcr.io/x/y:t', 'high', 'supratex', 'hf_SECRET', 8, 49152, 'note', {'basic': {'username': 'u', 'password': 'PW'}}, extra_env={'CUDA_LAUNCH_BLOCKING': '1'})
e = b['container']['environment_variables']
ok('тело группы: MODEL=supratex, код воркера в command (python3 -u -c; pip не нужен — всё в образе), приёмника на проде нет, отладочное окружение доехало, память 49152 МБ, диск 80 ГиБ',
   e['MODEL'] == 'supratex' and b['container']['command'][:2] == ['python3', '-u'] and 'pip install' not in ' '.join(b['container']['command'][2:3]) and not any(k.startswith('MESH_SINK') for k in e) and e['CUDA_LAUNCH_BLOCKING'] == '1'
   and b['container']['resources']['memory'] == 49152 and b['container']['resources']['storage_amount'] == 80 * 2 ** 30
   and __import__('zlib').decompress(__import__('base64').b64decode(e['TRIAL_WORKER_Z'])) == open(os.path.join(HERE, 'worker_trellis.py'), 'rb').read())
ok('только 4090; веса открытые (проверка закрытых весов не нужна: модели нет в HF_GATED); память по умолчанию для supratex 48 ГиБ, для остальных 32 ГиБ', b['container']['resources']['gpu_classes'] == [T.CARD['class_id']] and 'supratex' not in T.HF_GATED
   and T.MODEL_MEM_MB == {'supratex': 49152} and 'supratex' in T.WENV_MODELS)
b2 = T.build_body('trial-trellis2-x', 'ghcr.io/x/y:t', 'high', 'trellis2', 'hf_SECRET', 8, 32768, 'note', {'basic': {}}, extra_env={'CUDA_LAUNCH_BLOCKING': '1'})
ok('окружение воркера моделям вне белого списка не передаётся', 'CUDA_LAUNCH_BLOCKING' not in b2['container']['environment_variables'])
ok('supra_options: по умолчанию без refine / 4096 / 500000; кривое — None',
   T.supra_options(NS()) == {'supra_refine': False, 'supra_texture_size': 4096, 'supra_decimation': 500000} and T.supra_options(NS(supra_texture_size=777)) is None and T.supra_options(NS(supra_decimation=5)) is None
   and T.supra_options(NS(supra_decimation=5000000)) is None and T.supra_options(NS(supra_refine=True, supra_texture_size=2048, supra_decimation=100000)) == {'supra_refine': True, 'supra_texture_size': 2048, 'supra_decimation': 100000})

tp = tempfile.mkdtemp(prefix='supd-')
json.dump({'a:1': {'input_png_sha256': 'x'}, 'b:2': {'input_png_sha256': 'y'}}, open(os.path.join(tp, 'inputs.json'), 'w'))
shape_path = os.path.join(tp, 'shape.glb')
open(shape_path, 'wb').write(b'glTF')


class NoTouchMG:
    def env_from_file(self):
        raise AssertionError('Salad тронут до проверки аргументов')

    def __getattr__(self, k):
        raise AssertionError('Salad тронут до проверки аргументов: ' + k)


base = dict(model='supratex', inputs=tp, skus=['a:1'], plan='1024:1', seed=42, texture_mesh=shape_path, set=None, suffix='t', tier='high', texture=2048, decimation=500000,
            supra_refine=False, supra_texture_size=4096, supra_decimation=500000, worker_env=[], debug_cuda=False, out=None, apply=False)
for name, kw in (('без --texture-mesh', {'texture_mesh': None}), ('два товара', {'skus': ['a:1', 'b:2']}), ('--supra-texture-size 777', {'supra_texture_size': 777}), ('--supra-decimation 5', {'supra_decimation': 5}),
                 ('--worker-env с чужой переменной', {'worker_env': ['HF_TOKEN=x']})):
    rc = T.run(NS(**{**base, **kw}), NoTouchMG(), NoTouchMG())
    ok(f'{name}: отказ (код 2) до обращения к Salad — группа не создаётся, денег 0', rc == 2)


json.dump({k: {'input_png_sha256': 'x'} for k in ('a:1', 'b:2', 'c:3')}, open(os.path.join(tp, 'inputs.json'), 'w'))      # c:3 есть среди входов, но формы у него нет
cat = tempfile.mkdtemp(prefix='shp-')                         # каталог форм: у a:1 есть clean2, у b:2 только clean, у c:3 ничего (T-20261119-06/5/2)
for fn_ in ('a_1-1024-42-0.clean2.glb', 'b_2-1024-42-0.clean.glb'):
    open(os.path.join(cat, fn_), 'wb').write(b'glTF')
rc = T.run(NS(**{**base, 'skus': ['a:1', 'b:2', 'c:3'], 'texture_mesh': None, 'shape_dir': cat}), NoTouchMG(), NoTouchMG())
ok('несколько товаров из каталога форм, но у c:3 формы нет — отказ (код 2) ДО обращения к Salad: группа не создаётся, денег 0', rc == 2)
rc = T.run(NS(**{**base, 'skus': ['a:1', 'b:2'], 'texture_mesh': shape_path, 'shape_dir': cat}), NoTouchMG(), NoTouchMG())
ok('и --texture-mesh, и --shape-dir сразу — отказ до Salad (форма задаётся одним способом)', rc == 2)


class DryMG:
    def env_from_file(self):
        pass

    def ghcr_auth(self):
        return {'basic': {'username': 'u', 'password': 'PW'}}


ns = NS(**{**base, 'image': 'ghcr.io/x/y:t', 'cap': 0.35, 'cpu': 8, 'mem_mb': None, 'card': None, 'donor': 'd', 'force_out': False, 'tex_align': 'fit'})
buf = io.StringIO()
with redirect_stdout(buf):
    rc = T.run(ns, DryMG(), NS())
txt = buf.getvalue()
ok('сухой прогон: код 0, задание `<ключ>-1024-42-0-supra`, группа trial-supratex-…, потолок $0,35, память группы 49152 МБ; секретов в печати нет',
   rc == 0 and 'задание a_1-1024-42-0-supra' in txt and 'trial-supratex-t' in txt and 'потолок $ 0.35' in txt and '"memory": 49152' in txt and 'hf_SECRET' not in txt and 'PW' not in txt and '<скрыто>' in txt, txt[:300])
ns_m = NS(**{**ns.__dict__, 'skus': ['a:1', 'b:2'], 'texture_mesh': None, 'shape_dir': cat, 'out': None, 'suffix': 'm'})
buf = io.StringIO()
with redirect_stdout(buf):
    rc = T.run(ns_m, DryMG(), NS())
txt2 = buf.getvalue()
ok('два товара в ОДНОЙ группе (сухой прогон): код 0, одна группа trial-supratex-m, два задания — по товару, у каждого своя форма из каталога (clean2 / clean)',
   rc == 0 and txt2.count('  задание ') == 2 and 'задание a_1-1024-42-0-%s' % 'supra' in txt2 and 'задание b_2-1024-42-0-%s' % 'supra' in txt2 and txt2.count('группа trial-supratex-m ') == 1
   and 'a_1-1024-42-0.clean2.glb' in txt2 and 'b_2-1024-42-0.clean.glb' in txt2 and 'заданий 2' in txt2, txt2[:300])
ok('результаты — в СВОЕЙ папке модели (…/mesh-models-1118/supratex), не в общей `trellis/`', ns.out == T.default_out('supratex') and os.path.basename(ns.out) == 'supratex' and os.path.basename(ns.out) != 'trellis', ns.out)
ns2 = NS(**{**base, 'model': 'trellis2', 'texture_mesh': None, 'image': 'ghcr.io/x/y:t', 'cap': 0.35, 'cpu': 8, 'mem_mb': None, 'card': None, 'donor': 'd', 'force_out': False, 'tex_align': 'fit'})
buf = io.StringIO()
with redirect_stdout(buf):
    T.run(ns2, DryMG(), NS())
ok('trellis2 без явной памяти — прежние 32768 МБ (общее правило не сломано)', '"memory": 32768' in buf.getvalue())
ns3 = NS(**{**ns.__dict__, 'mem_mb': 32768, 'out': None})
buf = io.StringIO()
with redirect_stdout(buf):
    T.run(ns3, DryMG(), NS())
ok('явная --mem-mb перебивает умолчание модели', '"memory": 32768' in buf.getvalue())
ok('чужой результат в папке — отказ (owner_conflicts не ослаблен): файл от другой модели под тем же именем',
   (lambda: (open(os.path.join(tp, 'x-1024-42-0-supra.model'), 'w').write('trellis2'), T.owner_conflicts(tp, ['x-1024-42-0-supra'], 'supratex'))[1])() == ['x-1024-42-0-supra'])

print('[4] образ и сборка')
df = open(os.path.join(HERE, 'Dockerfile.supratex'), encoding='utf-8').read()
wf = open(os.path.join(HERE, '..', '..', '..', '..', '.github', 'workflows', 'build-supratex-trial.yml'), encoding='utf-8').read()
ok('Dockerfile: поверх образа TRELLIS.2 по digest, код SUPRA по коммиту cee4435, четыре расширения на пинах апстрима, NATTEN 0.17.5, веса НЕ в образе, ENV MODEL=supratex',
   'FROM ${BASE}' in df and '@sha256:d7beac21' in df and 'cee4435652d0f23737bd28d5704e0fae9830b411' in df and all(x in df for x in ('ef40f3ae4612ea3ec934b4151e019dc95c5d276b', 'b1965ad0ae4bc8488d13b5280afb54439ce27359', '253ac4fcea7de5f396371124af597e6cc957bfae', '5565d240c4a494caaf9ece7a554542b76ffa36d3'))
   and 'natten-0.17.5' in df and 'ENV MODEL=supratex' in df and 'snapshot_download' not in df and 'huggingface-cli' not in df)
ok('Dockerfile: лицензии названы (Qwen Research License — не коммерческая; nvdiffrast/nvdiffrec — NC)', 'Qwen Research License' in df and 'Source Code License-NC' in df)
ok('сборка: только пуш в ветки trial/trellis2*, образ mesh-supratex-trial:supratex-trial, только своя ветка, порог 30 ГБ сжатого', "branches: ['trial/trellis2*']" in wf and 'mesh-supratex-trial:supratex-trial' in wf and "startsWith(github.ref, 'refs/heads/trial/trellis2')" in wf and '> 30' in wf and 'Dockerfile.supratex' in wf)

print('ИТОГО: ' + ('всё в норме' if not bad else f'провалов {bad}'))
sys.exit(1 if bad else 0)
