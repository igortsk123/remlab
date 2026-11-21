#!/usr/bin/env python3
"""Тесты `mvpainter` — краска MVPainter КАК У АВТОРОВ по готовой форме TRELLIS.2 (T-20261119-06/4). Без видеокарты, сети, ключей, torch, Blender и самого MVPainter (заглушки).
Что проверяется: штатное упрощение включено по умолчанию, флаг его выключает; вместо охраны «форма не меняется» — метрики упрощения (грани/вершины до и после, Хаусдорф в долях диагонали);
кадр итога возвращается в кадр входа (в том числе после поворота куба); выбор класса GPU (таблица от 40 ГБ, самый дешёвый, запасной тариф); отказ без формы ДО группы; результат не в `trellis/`;
порядок и пути стадий апстрима, проверка их выходных файлов, «сломан» после фатальной ошибки CUDA, обёртка загрузки весов (issue #13).

  python3 tools/scout/salad/trellis/tests_mvpainter.py
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
from contextlib import redirect_stdout
from types import SimpleNamespace as NS

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.normpath(os.path.join(HERE, '..', '..')))
import remlab_tmp  # noqa: E402
remlab_tmp.use('tests_mvpainter')
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
    """Несимметричная фигура (буква Г из двух коробок, Y вверх)."""
    return merge(box((-0.30, -0.30, -0.10), (0.30, -0.10, 0.10)), box((-0.30, -0.10, -0.10), (-0.10, 0.30, 0.10)))


def photo_of(V, F, yaw, size=(400, 300), n=240):
    p = W.to_cube(V, yaw)[0]
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


print('[1] числа и геометрия (numpy)')
rots = W.mvp_rotations()
ok('24 поворота куба: все с det=+1, первый — единичный, все разные', len(rots) == 24 and np.allclose(rots[0], np.eye(3)) and all(abs(np.linalg.det(r) - 1) < 1e-9 for r in rots)
   and len({tuple(np.round(r, 6).ravel()) for r in rots}) == 24)
photo = np.zeros((100, 80, 4), dtype=np.uint8)
photo[20:60, 10:50] = (200, 100, 50, 255)
rf = W.mvp_resize_foreground(Image.fromarray(photo, 'RGBA'), 0.85)
a = np.asarray(rf)
ys, xs = np.nonzero(a[..., 3] > 0)
ok('фото как у `resize_foreground(…, 0.85)`: квадрат, предмет занимает ≈ 85 % стороны по центру',
   rf.size[0] == rf.size[1] and abs((ys.max() - ys.min() + 1) / rf.size[0] - 0.85 * 39 / 40) < 0.05 and abs((ys.min() + ys.max()) / 2 - rf.size[0] / 2) < 2 and abs((xs.min() + xs.max()) / 2 - rf.size[0] / 2) < 2, str(rf.size))
try:
    W.mvp_resize_foreground(Image.new('RGBA', (10, 10), (0, 0, 0, 0)))
    ok('пустая альфа → ValueError', False)
except ValueError:
    ok('пустая альфа → ValueError (а не молчаливая пустая картинка)', True)

V, F = l_shape()
p_ref = W.to_cube(V, 0)[0]
# итог апстрима в «своём» кадре: тот же кадр, масштаб 0,95/габарит и сдвиг центра (`normalize_scene`)
ext = float((V.max(axis=0) - V.min(axis=0)).max())
v_theirs = (V - (V.max(axis=0) + V.min(axis=0)) / 2) * (0.95 / ext) + np.array([0.0, 0.0, 0.0])
al, info = W.mvp_align_frame(v_theirs, p_ref)
ok('кадр итога = кадр входа (масштаб и сдвиг): единичный поворот, оценка ≈ 0, ok', info['rotation'] == 'identity' and info['score_chosen'] < 1e-6 and info['ok'] and np.allclose(al, p_ref, atol=1e-6), str(info))
R90 = W.rot_y(90)
al2, info2 = W.mvp_align_frame(p_ref @ R90.T * 0.95 + 0.3, p_ref)
ok('итог в повёрнутом на 90° кадре → найден поворот куба из 24, вершины вернулись на место, ok', info2['rotation'] != 'identity' and info2['ok'] and np.allclose(al2, p_ref, atol=1e-6) and info2['score_identity'] > W.MVP_FRAME_OK, str(info2))
junk = np.random.default_rng(1).normal(size=(500, 3))
_al3, info3 = W.mvp_align_frame(junk, p_ref)
ok('чужая форма вместо итога → ok=false (проба это покажет, а не промолчит)', info3['ok'] is False, str(info3))

import trimesh  # noqa: E402
sph = trimesh.creation.icosphere(subdivisions=3)
sph_lo = trimesh.creation.icosphere(subdivisions=2)
sc = np.array([0.5, 0.3, 0.3])
met = W.shape_change_metrics(np.asarray(sph.vertices) * sc, sph.faces, np.asarray(sph_lo.vertices) * sc, sph_lo.faces, n=8000)
ok('метрики упрощения: грани/вершины до и после (1280 → 320 граней), Хаусдорф в долях диагонали — малый, но не нулевой',
   met['faces_in'] == 1280 and met['faces_out'] == 320 and met['verts_in'] == 642 and met['verts_out'] == 162 and 0 < met['hausdorff_rel'] < 0.06 and met['mean_rel'] > 0
   and met['p99_rel'] <= met['hausdorff_rel'] and abs(met['faces_ratio'] - 0.25) < 1e-6, str(met))
same = W.shape_change_metrics(np.asarray(sph.vertices), sph.faces, np.asarray(sph.vertices), sph.faces, n=4000)
ok('та же форма → расстояние почти 0 (только шаг выборки; метрика не выдумывает сдвиг), общая функция с supratex', same['hausdorff_rel'] < 0.03 and W.supra_shape_metrics is W.shape_change_metrics, str(same))

print('[2] стадии апстрима подпроцессами')
wd = tempfile.mkdtemp(prefix='mvps-')
tgt = os.path.join(wd, 'made.txt')
peaks = iter([100, 500, 300] + [300] * 200)
info = W.mvp_run_stage('t_ok', [sys.executable, '-c', f'import time; print("привет"); time.sleep(1.6); open({tgt!r}, "w").write("x")'], wd, expect=(tgt,), smi=lambda: next(peaks), timeout=60)
ok('стадия: код 0, секунды ≥ 1,6, пик памяти — максимум опроса (500), база — первый замер (100), хвост вывода сохранён', info['rc'] == 0 and info['seconds'] >= 1.6 and info['gpu_peak_mib'] == 500 and info['gpu_used_base_mib'] == 100
   and 'привет' in ' '.join(info['tail']), str(info))
try:
    W.mvp_run_stage('t_rc', [sys.executable, '-c', 'import sys; print("CUDA error: an illegal memory access was encountered"); sys.exit(3)'], wd, smi=lambda: None)
    ok('код выхода ≠ 0 → MVPStageError', False)
except W.MVPStageError as e:
    ok('код выхода ≠ 0 → MVPStageError с кодом и хвостом; по тексту это фатальная ошибка CUDA', 'код выхода 3' in str(e) and 'illegal memory access' in str(e) and W.classify_cuda_error(e) == 'fatal', str(e)[:200])
try:
    W.mvp_run_stage('t_miss', [sys.executable, '-c', 'print(1)'], wd, expect=(os.path.join(wd, 'нет', '*.glb'),), smi=lambda: None)
    ok('код 0, но ожидаемого файла нет → MVPStageError (os.system апстрима такие сбои скрывает)', False)
except W.MVPStageError as e:
    ok('код 0, но ожидаемого файла нет → MVPStageError «нет файлов» (os.system апстрима такие сбои скрывает)', 'нет файлов' in str(e), str(e)[:200])
try:
    W.mvp_run_stage('t_to', [sys.executable, '-c', 'import time; time.sleep(30)'], wd, smi=lambda: None, timeout=1.0)
    ok('таймаут → MVPStageError', False)
except W.MVPStageError as e:
    ok('таймаут → процесс убит, MVPStageError «таймаут»', 'таймаут' in str(e), str(e)[:200])

calls = []


def fake_stage_factory(calls):
    def fake_stage(name, cmd, cwd, env=None, expect=(), timeout=0):
        calls.append({'name': name, 'cmd': [str(x) for x in cmd], 'cwd': cwd, 'expect': list(expect)})
        for e in expect:
            e = e.replace('*', 'mt')
            os.makedirs(os.path.dirname(e), exist_ok=True)
            open(e, 'wb').write(b'x')
        return {'name': name, 'rc': 0, 'seconds': 1.0, 'gpu_peak_mib': 1024, 'gpu_used_base_mib': 0, 'timed_out': False, 'tail': []}
    return fake_stage


def runner_for(calls, root='/opt/MV-Painter/MVPainter'):
    return W.MVPRunner(root, '/b42/blender', '/b36/blender', '/tools', {}, python='/usr/bin/python3', run_stage=fake_stage_factory(calls))


work = tempfile.mkdtemp(prefix='mvpw-')
os.makedirs(os.path.join(work, 'in', 'glb'))
os.makedirs(os.path.join(work, 'in', 'img'))
r = runner_for(calls)
out = r.run('mt', work, {'steps': 75, 'seed': 12, 'reduce': True, 'pbr': True})
names = [c['name'] for c in calls]
ok('порядок стадий по умолчанию (PBR + штатное упрощение): виды → PBR-виды → упрощение → запекание ×3 (с Blender 3.6) → PBR-GLB (Blender 4.2.9)',
   names == ['multiview', 'pbr_views', 'reduce', 'bake_basecolor', 'obj_basecolor', 'bake_metallic', 'obj_metallic', 'bake_roughness', 'obj_roughness', 'pbr_glb'], str(names))
c0, creduce, cglb = calls[0], calls[2], calls[-1]
ok('infer_multiview: шаги/зерно/без rembg/geo_rotation -90 как у авторов, из каталога MVPainter, через обёртку загрузки',
   c0['cwd'] == '/opt/MV-Painter/MVPainter' and 'infer_multiview.py' in c0['cmd'] and '--no_rembg' in c0['cmd'] and c0['cmd'][c0['cmd'].index('--diffusion_steps') + 1] == '75'
   and c0['cmd'][c0['cmd'].index('--geo_rotation') + 1] == '-90' and c0['cmd'][1].endswith('mvp_run.py'), str(c0['cmd']))
ok('упрощение: Blender 3.6, `target_vertices` 30000 (как `infer_paint.py:25`)', creduce['cmd'][0] == '/b36/blender' and creduce['cmd'][-1] == str(W.MVP_SIZE_MAX) == '30000' and creduce['cmd'][-3].endswith('blender.obj') and creduce['cmd'][-2].endswith('blender_low.obj'), str(creduce['cmd']))
ok('PBR-GLB собирает Blender 4.2.9 и пишет в combine_pbr; итог — найденный GLB', cglb['cmd'][0] == '/b42/blender' and cglb['cmd'][-1].endswith('combine_pbr') and out['glb'].endswith(os.path.join('combine_pbr', 'mt.glb')) and os.path.exists(out['glb']), str(out))
calls.clear()
work2 = tempfile.mkdtemp(prefix='mvpw-')
r.run('mt', work2, {'steps': 30, 'seed': 1, 'reduce': False, 'pbr': False}) if os.makedirs(os.path.join(work2, 'mv', 'mvpainter', 'mt'), exist_ok=True) is None and open(os.path.join(work2, 'mv', 'mvpainter', 'mt', 'blender.obj'), 'w').write('o') is not None else None
n2 = [c['name'] for c in calls]
ok('«не упрощать» (reduce=False) и без PBR: стадии только виды → запекание; blender_low.obj — копия blender.obj без вызова Blender', n2 == ['multiview', 'bake'] and os.path.exists(os.path.join(work2, 'mv', 'mvpainter', 'mt', 'blender_low.obj')), str(n2))

print('[3] mvp_texture_on_shape на заглушке апстрима (упрощение — законно, кадр возвращается)')
Vs = np.asarray(sph.vertices) * np.array([0.5, 0.3, 0.3])
mesh_in = trimesh.Trimesh(vertices=Vs, faces=sph.faces, process=False)
photo0 = photo_of(Vs, np.asarray(sph.faces), 0)
seen = {}


class FakeRunner:
    """Вместо апстрима: читает вход, отдаёт ИЗМЕНЁННУЮ форму (в 4 раза меньше граней — «упрощение»), в масштабе и со сдвигом `normalize_scene`, с развёрткой и текстурой; пишет виды."""
    root = tempfile.mkdtemp(prefix='mvroot-')

    def run(self, uid, work, params):
        seen.update(params)
        seen['uid'] = uid
        seen['has_in_glb'] = os.path.exists(os.path.join(work, 'in', 'glb', uid + '.glb'))
        seen['has_in_png'] = os.path.exists(os.path.join(work, 'in', 'img', uid + '.png'))
        src = trimesh.load(os.path.join(work, 'in', 'glb', uid + '.glb'), force='mesh', process=False)
        lo = trimesh.creation.icosphere(subdivisions=2 if params['reduce'] else 3)
        v = np.asarray(lo.vertices) * np.array([0.5, 0.3, 0.3])
        ext_ = float((src.vertices.max(axis=0) - src.vertices.min(axis=0)).max())
        v = (v - (v.max(axis=0) + v.min(axis=0)) / 2) * (0.95 / (np.asarray(v).max(axis=0) - np.asarray(v).min(axis=0)).max()) * ext_ + np.array([0.2, -0.1, 0.05])
        uv = np.random.default_rng(0).random((len(v), 2))
        tex = Image.new('RGB', (16, 16), (200, 30, 30))
        mat = trimesh.visual.material.PBRMaterial(baseColorTexture=tex, metallicFactor=0.0, roughnessFactor=0.7)
        m = trimesh.Trimesh(vertices=v, faces=lo.faces, visual=trimesh.visual.TextureVisuals(uv=uv, material=mat), process=False)
        outd = os.path.join(work, 'res', 'combine_pbr')
        os.makedirs(outd)
        m.export(os.path.join(outd, uid + '.glb'))
        mv = os.path.join(work, 'mv', 'mvpainter', uid)
        os.makedirs(mv)
        for i in range(1, 7):
            Image.new('RGB', (64, 64), (i * 30, 100, 100)).save(os.path.join(mv, f'result_{i}.png'))
        return {'glb': os.path.join(outd, uid + '.glb'), 'mv_dir': mv, 'stages': [{'name': 'multiview', 'seconds': 2.0, 'gpu_peak_mib': 20480, 'rc': 0, 'tail': ['x']}]}


work3 = tempfile.mkdtemp(prefix='mvpt-')
final, m3 = W.mvp_texture_on_shape(FakeRunner(), mesh_in, photo0, {'seed': 7}, None, work3)
ok('по умолчанию упрощение ВКЛЮЧЕНО (reduce=True), PBR включён, 75 шагов, зерно из задания', seen['reduce'] is True and seen['pbr'] is True and seen['steps'] == 75 and seen['seed'] == 7, str(seen))
ok('апстриму ушли форма (GLB без развёртки) и фото (PNG), имя без «glb»', seen['has_in_glb'] and seen['has_in_png'] and 'glb' not in seen['uid'] and seen['uid'].startswith('m'))
ok('форма изменилась ЗАКОННО: охраны нет (исключения нет), в метриках 1280 → 320 граней, Хаусдорф к исходной — доли диагонали', m3['simplify']['faces_in'] == 1280 and m3['simplify']['faces_out'] == 320
   and 0 < m3['simplify']['hausdorff_rel'] < 0.06, str(m3['simplify']))
ok('кадр итога вернулся в кадр входа: идентичный поворот, оценка мала, ok; габарит итога ≈ габариту исходной формы',
   m3['frame']['rotation'] == 'identity' and m3['frame']['ok'] and np.allclose(final.bounds, mesh_in.bounds, atol=0.03), str(m3['frame']) + str(final.bounds) + str(mesh_in.bounds))
ok('материал и развёртка апстрима сохранены (текстура 16², UV на каждую вершину), замеры: стадии, пик, миниатюра видов', m3['tex_in_size'] == [16, 16] and len(final.visual.uv) == len(final.vertices) and m3['upstream_s'] == 2.0
   and m3['views_jpeg_b64'] and 'upstream' in m3['stage_s'] and 'metrics' in m3['stage_s'], str(m3)[:300])
_f2, m4 = W.mvp_texture_on_shape(FakeRunner(), mesh_in, photo0, {'mvp_reduce': 0, 'mvp_pbr': '0', 'mvp_steps': 30}, None, tempfile.mkdtemp(prefix='mvpt-'))
ok('флаги: mvp_reduce=0 → reduce=False (не упрощать), mvp_pbr="0" → pbr=False, шаги 30', seen['reduce'] is False and seen['pbr'] is False and seen['steps'] == 30 and m4['simplify']['faces_out'] == 1280, str(seen))
for bad_steps in (0, 151):
    try:
        W.mvp_texture_on_shape(FakeRunner(), mesh_in, photo0, {'mvp_steps': bad_steps}, None, tempfile.mkdtemp(prefix='mvpt-'))
        ok(f'mvp_steps={bad_steps} → ValueError', False)
    except ValueError:
        ok(f'mvp_steps={bad_steps} → ValueError до запуска стадий', True)

print('[4] бэкенд, «сломан», обёртка загрузки весов')
import types  # noqa: E402
sav = {k: getattr(W, k) for k in ('JOBS_DIR', 'OUT', 'STATE_PATH', 'BACKEND')}
sav_state = dict(W.STATE)
td = tempfile.mkdtemp(prefix='mvb-')
W.JOBS_DIR, W.OUT, W.STATE_PATH = os.path.join(td, 'jobs'), os.path.join(td, 'out'), os.path.join(td, 'state.json')
os.makedirs(W.JOBS_DIR)
os.makedirs(W.OUT)
try:
    os.environ['MODEL'] = 'mvpainter'
    be = W.backend()
    ok('MODEL=mvpainter → MVPainterBackend (без загрузки)', type(be).__name__ == 'MVPainterBackend' and be.name == 'mvpainter')
    os.environ['MODEL'] = 'mvadapter-i2tex'
    ok('MODEL=mvadapter-i2tex — прежний бэкенд, не затронут', type(W.backend()).__name__ == 'MVAdapterTexBackend')
    os.environ.pop('MODEL', None)
    try:
        be.generate(Image.new('RGBA', (8, 8)), {'job_id': 'x'}, os.path.join(W.OUT, 'x.glb'))
        ok('без формы (--texture-mesh) бэкенд отказывает сразу', False)
    except ValueError as e:
        ok('без формы (--texture-mesh) бэкенд отказывает сразу, до стадий и видеокарты', 'texture-mesh' in str(e))
    mesh_in.export(os.path.join(W.JOBS_DIR, 'j1-mvp.mesh.glb'))
    be.runner = FakeRunner()
    out_path = os.path.join(W.OUT, 'j1-mvp.glb')
    met = be.generate(photo0, {'job_id': 'j1-mvp', 'texture_mesh': True}, out_path)
    ok('generate: GLB записан, метрики: режим, пик памяти из стадий (20 ГиБ), упрощение, кадр итога; форма меняется без отказа',
       os.path.exists(out_path) and met['mode'] == 'mvpainter' and met['peak_vram_gb'] == 20.0 and met['simplify']['faces_out'] == 320 and met['frame']['ok'] and 'load_shape' in met['stage_s'], str(met)[:300])
    ok('рабочая папка задания убрана (в OUT только результат)', sorted(os.listdir(W.OUT)) == ['j1-mvp.glb'], str(os.listdir(W.OUT)))
    got = trimesh.load(out_path, force='mesh', process=False)
    ok('результат читается: 320 граней, текстура 16², габарит ≈ исходного', len(got.faces) == 320 and got.visual.material.baseColorTexture.size == (16, 16) and np.allclose(got.bounds, mesh_in.bounds, atol=0.03))
    cuda_fatal = W.MVPStageError('стадия multiview: код выхода 1\nRuntimeError: CUDA error: an illegal memory access was encountered')
    cuda_oom = W.MVPStageError('стадия multiview: код выхода 1\ntorch.cuda.OutOfMemoryError: CUDA out of memory. Tried to allocate 2.00 GiB')
    for exc, want, fatal in ((cuda_fatal, 'fatal', True), (cuda_oom, 'oom', False), (ValueError('форма: нет мешей'), 'other', False)):
        d = be.on_error(exc)
        ok(f'on_error: «{str(exc)[-50:]!r}» → {want}, fatal={fatal}', d['kind'] == want and d['fatal'] is fatal and 'stage_mem' in d, str(d)[:200])

    class Boom(W.MVPainterBackend):
        def generate(self, image, params, path):
            raise cuda_fatal
    W.BACKEND = Boom()
    W.STATE.update(phase='ready', warm=True, error=None)
    W.STATE.pop('broken', None)
    Image.new('RGBA', (8, 8), (1, 2, 3, 255)).save(os.path.join(W.JOBS_DIR, 'b1.png'))
    open(os.path.join(W.JOBS_DIR, 'b1.req.json'), 'w').write(json.dumps({'job_id': 'b1', 'texture_mesh': True}))
    W.run_job('b1')
    rb = json.load(open(os.path.join(W.JOBS_DIR, 'b1.res.json'), encoding='utf-8'))
    ok('фатальная ошибка CUDA в стадии: failed, diag.fatal, воркер помечен сломанным (/health ok=false) — драйвер гасит группу', rb['status'] == 'failed' and rb['diag']['fatal'] is True
       and 'illegal memory access' in str(W.STATE.get('broken')) and W.health()['ok'] is False, str(rb.get('diag'))[:200])
finally:
    for k, v in sav.items():
        setattr(W, k, v)
    W.STATE.clear()
    W.STATE.update(sav_state)
    os.environ.pop('MODEL', None)

# обёртка загрузки весов: поддельные torch / safetensors / huggingface_hub, настоящий runpy в подпроцессе
fk = tempfile.mkdtemp(prefix='mvfake-')
open(os.path.join(fk, 'torch.py'), 'w').write('calls = []\ndef load(f, *a, **k):\n    calls.append((str(f), dict(k)))\n    return {"state_dict": {"orig": 1}}\n')
os.makedirs(os.path.join(fk, 'safetensors'))
open(os.path.join(fk, 'safetensors', '__init__.py'), 'w').write('')
open(os.path.join(fk, 'safetensors', 'torch.py'), 'w').write('def load_file(p, device="cpu"):\n    return {"unet.up.w": 1, "controlnet.c.w": 2}\n')
open(os.path.join(fk, 'huggingface_hub.py'), 'w').write('def hf_hub_download(repo_id=None, filename=None, **k):\n    return "/cache/" + filename\n')
scr = os.path.join(fk, 's.py')
open(scr, 'w').write('import torch\nfrom huggingface_hub import hf_hub_download\np = hf_hub_download(repo_id="shaomq/MVPainter", filename="unet_w_controlnet/v29_25000.ckpt")\n'
                     'sd = torch.load(p)\nu = hf_hub_download(repo_id="shaomq/MVPainter", filename="uc_text_emb.pt")\nt = torch.load("/x/uc.pt")\nimport json\nprint(json.dumps({"p": p, "u": u, "sd": sd, "t_kw": torch.calls[-1][1]}))\n')
wrap = os.path.join(fk, 'mvp_run.py')
open(wrap, 'w').write(W.MVP_RUN_PY)


def run_wrap(extra_env):
    r = subprocess.run([sys.executable, wrap, scr], cwd=fk, env={**os.environ, 'PYTHONPATH': fk, **extra_env}, capture_output=True, text=True, timeout=60)
    return r.returncode, (json.loads(r.stdout.strip().splitlines()[-1]) if r.returncode == 0 and r.stdout.strip() else r.stderr[-300:])


rc, o = run_wrap({})
ok('обёртка (по умолчанию): .ckpt → .safetensors, ключи получают внешний префикс `unet.` как в .ckpt; torch.load — на процессор, weights_only=False; прочие файлы не тронуты',
   rc == 0 and o['p'].endswith('v29_25000.safetensors') and o['sd'] == {'state_dict': {'unet.unet.up.w': 1, 'unet.controlnet.c.w': 2}} and o['u'].endswith('uc_text_emb.pt')
   and o['t_kw'].get('map_location') == 'cpu' and o['t_kw'].get('weights_only') is False, str(o))
rc, o = run_wrap({'MVP_CKPT': 'ckpt', 'MVP_LOAD_CPU': '0'})
ok('обёртка с MVP_CKPT=ckpt, MVP_LOAD_CPU=0 — «как у авторов»: файл .ckpt как есть, без map_location', rc == 0 and o['p'].endswith('v29_25000.ckpt') and o['sd'] == {'state_dict': {'orig': 1}} and 'map_location' not in o['t_kw'], str(o))
for fname, body in (('mvp_run.py', W.MVP_RUN_PY), ('mvp_reduce.py', W.MVP_REDUCE_PY), ('mvp_bake.py', W.MVP_BAKE_PY)):
    import ast
    try:
        ast.parse(body)
        ok(f'{fname}: синтаксис верен', True)
    except SyntaxError as e:
        ok(f'{fname}: синтаксис верен', False, str(e))

print('[5] драйвер: выбор класса GPU, тело группы, отказы, папка результата')
import trellis_trial as T  # noqa: E402
items = [
    {'id': 'c4090', 'name': 'RTX 4090 (24 GB)', 'prices': [{'priority': 'high', 'price': '0.33'}, {'priority': 'medium', 'price': '0.3'}]},
    {'id': 'c5090', 'name': 'RTX 5090 (32 GB)', 'prices': [{'priority': 'high', 'price': '0.600'}, {'priority': 'medium', 'price': '0.483'}]},
    {'id': 'a6000', 'name': 'RTX A6000 (48 GB)', 'prices': [{'priority': 'high', 'price': '0.49'}, {'priority': 'medium', 'price': '0.40'}, {'priority': 'low', 'price': '0.35'}]},
    {'id': 'l40s', 'name': 'L40S (48 GB)', 'prices': [{'priority': 'high', 'price': '0.69'}, {'priority': 'low', 'price': '0.50'}]},
    {'id': 'a100', 'name': 'A100 (40 GB)', 'prices': [{'priority': 'high', 'price': '0.89'}]},
    {'id': 'h100', 'name': 'H100 (80 GB)', 'prices': [{'priority': 'medium', 'price': '1.50'}, {'priority': 'low', 'price': '1.2'}]},
    {'id': 'weird', 'name': 'Some GPU', 'prices': [{'priority': 'high', 'price': '0.01'}]},
]
ok('gpu_memory_gb: «(48 GB)» → 48, без памяти в имени → None', T.gpu_memory_gb('RTX A6000 (48 GB)') == 48 and T.gpu_memory_gb('Some GPU') is None)
rows = T.gpu_table(items, 40)
ok('таблица от 40 ГБ: 4090 (24) и безымянный не попали, порядок — дешёвые на high первыми (A6000, L40S, A100, потом H100 без high)', [r['name'] for r in rows] == ['RTX A6000 (48 GB)', 'L40S (48 GB)', 'A100 (40 GB)', 'H100 (80 GB)'], str([r['name'] for r in rows]))
row, used = T.pick_cheapest(items, 40, 'high')
ok('самый дешёвый от 40 ГБ на high — A6000 по $0,49', row['name'] == 'RTX A6000 (48 GB)' and used == 'high' and row['prices']['high'] == 0.49)
row, used = T.pick_cheapest([c for c in items if c['id'] in ('h100', 'c4090')], 40, 'high')
ok('на high нет ни одного класса от 40 ГБ → тариф ниже (medium), назван тариф', row['name'] == 'H100 (80 GB)' and used == 'medium', str((row, used)))
ok('совсем нет классов от 40 ГБ → (None, None)', T.pick_cheapest([items[0]], 40, 'high') == (None, None))
ok('таблица печатается: имя, ГБ и цены по тарифам', 'RTX A6000 (48 GB)' in T.format_gpu_table(rows) and '0.490' in T.format_gpu_table(rows) and 'high' in T.format_gpu_table(rows))
ok('rules/salad-groups.json даёт запасной список классов (снимок прайса)', any('4090' in c['name'] for c in T.rules_gpu_items()))
ok('fetch_gpu_items: сбой API → None (сухой прогон не падает), успех → цены в LIVE_PRICES', T.fetch_gpu_items(None, fetch=lambda: (_ for _ in ()).throw(OSError('нет сети'))) is None
   and T.fetch_gpu_items(None, fetch=lambda: items) == items and T.LIVE_PRICES[('RTX A6000 (48 GB)', 'high')] == 0.49)

b = T.build_body('trial-mvpainter-x', 'ghcr.io/x/y:t', 'high', 'mvpainter', 'hf_SECRET', 8, 32768, 'note', {'basic': {'username': 'u', 'password': 'PW'}}, extra_env={'MVP_CKPT': 'ckpt'})
e = b['container']['environment_variables']
ok('тело группы: MODEL=mvpainter, код воркера в command (python3 -u -c, без pip: версии в образе), приёмника на проде нет, окружение воркера (MVP_CKPT) доехало',
   e['MODEL'] == 'mvpainter' and b['container']['command'][:2] == ['python3', '-u'] and not any(k.startswith('MESH_SINK') for k in e) and e['MVP_CKPT'] == 'ckpt'
   and __import__('zlib').decompress(__import__('base64').b64decode(e['TRIAL_WORKER_Z'])) == open(os.path.join(HERE, 'worker_trellis.py'), 'rb').read())
ok('build_body без выбора класса — 4090 (CARD), диск 80 ГиБ (веса ≈ 28 ГиБ + кэш), образ тот же', b['container']['resources']['gpu_classes'] == [T.CARD['class_id']] and T.CARD['class_name'] == 'RTX 4090 (24 GB)'
   and b['container']['resources']['storage_amount'] == 80 * 2 ** 30 and b['container']['image'] == 'ghcr.io/x/y:t')
b2 = T.build_body('trial-trellis2-x', 'ghcr.io/x/y:t', 'high', 'trellis2', 'hf_SECRET', 8, 32768, 'note', {'basic': {}}, extra_env={'MVP_CKPT': 'ckpt'})
ok('окружение воркера чужим моделям не передаётся', 'MVP_CKPT' not in b2['container']['environment_variables'])
ok('--worker-env: MVP_*, MVTEX_*, PIXTEX_* проходят, чужое (HF_TOKEN, PATH) — отказ', T.parse_worker_env(['MVP_CKPT=ckpt', 'MVP_LOAD_CPU=0']) == {'MVP_CKPT': 'ckpt', 'MVP_LOAD_CPU': '0'}
   and T.parse_worker_env(['HF_TOKEN=x']) is None and T.parse_worker_env(['PATH=/x']) is None)
ok('mvp_options: по умолчанию auto/75/упрощение 1/PBR 1; кривое — None', T.mvp_options(NS()) == {'mvp_yaw': 'auto', 'mvp_steps': 75, 'mvp_reduce': 1, 'mvp_pbr': 1}
   and T.mvp_options(NS(mvp_yaw='45')) is None and T.mvp_options(NS(mvp_steps=0)) is None and T.mvp_options(NS(mvp_steps=151)) is None and T.mvp_options(NS(mvp_reduce='2')) is None
   and T.mvp_options(NS(mvp_pbr='x')) is None and T.mvp_options(NS(mvp_yaw='90', mvp_steps=30, mvp_reduce='0', mvp_pbr='0')) == {'mvp_yaw': '90', 'mvp_steps': 30, 'mvp_reduce': 0, 'mvp_pbr': 0})
ok('веса открытые: бесплатная проверка перед группой — только доступность репозитория', T.HF_GATED['mvpainter'].startswith('shaomq/MVPainter/'))

tp = tempfile.mkdtemp(prefix='mvd-')
json.dump({'a:1': {'input_png_sha256': 'x'}, 'b:2': {'input_png_sha256': 'y'}}, open(os.path.join(tp, 'inputs.json'), 'w'))
shape_path = os.path.join(tp, 'shape.glb')
open(shape_path, 'wb').write(b'glTF')


class NoTouchMG:
    def env_from_file(self):
        raise AssertionError('Salad тронут до проверки аргументов')

    def __getattr__(self, k):
        raise AssertionError('Salad тронут до проверки аргументов: ' + k)


base = dict(model='mvpainter', inputs=tp, skus=['a:1'], plan='1024:1', seed=42, texture_mesh=shape_path, set=None, suffix='t', tier='high', texture=2048, decimation=500000,
            mvp_yaw='auto', mvp_steps=75, mvp_reduce='1', mvp_pbr='1', worker_env=[], debug_cuda=False, out=None, apply=False, gpu=None)
for name, kw in (('без --texture-mesh', {'texture_mesh': None}), ('два товара', {'skus': ['a:1', 'b:2']}), ('--mvp-yaw 45', {'mvp_yaw': '45'}), ('--mvp-steps 0', {'mvp_steps': 0}),
                 ('--mvp-reduce 2', {'mvp_reduce': '2'}), ('--worker-env с чужой переменной', {'worker_env': ['HF_TOKEN=x']})):
    rc = T.run(NS(**{**base, **kw}), NoTouchMG(), NoTouchMG())
    ok(f'{name}: отказ (код 2) до обращения к Salad — группа не создаётся, денег 0', rc == 2)
rc = T.run(NS(**{**base, 'model': 'trellis2', 'worker_env': ['MVP_CKPT=ckpt'], 'texture_mesh': None}), NoTouchMG(), NoTouchMG())
ok('--worker-env для другой модели: отказ до Salad', rc == 2)


json.dump({k: {'input_png_sha256': 'x'} for k in ('a:1', 'b:2', 'c:3')}, open(os.path.join(tp, 'inputs.json'), 'w'))      # c:3 есть среди входов, но формы у него нет
cat = tempfile.mkdtemp(prefix='shp-')                         # каталог форм: у a:1 есть clean2, у b:2 только clean, у c:3 ничего (T-20261119-06/5/2)
for fn_ in ('a_1-1024-42-0.clean2.glb', 'b_2-1024-42-0.clean.glb'):
    open(os.path.join(cat, fn_), 'wb').write(b'glTF')
rc = T.run(NS(**{**base, 'skus': ['a:1', 'b:2', 'c:3'], 'texture_mesh': None, 'shape_dir': cat}), NoTouchMG(), NoTouchMG())
ok('несколько товаров из каталога форм, но у c:3 формы нет — отказ (код 2) ДО обращения к Salad: группа не создаётся, денег 0', rc == 2)
rc = T.run(NS(**{**base, 'skus': ['a:1', 'b:2'], 'texture_mesh': shape_path, 'shape_dir': cat}), NoTouchMG(), NoTouchMG())
ok('и --texture-mesh, и --shape-dir сразу — отказ до Salad (форма задаётся одним способом)', rc == 2)


class DryMG:
    API = 'https://api.salad.com/api/public/organizations/o/projects/p/containers'

    def env_from_file(self):
        pass

    def ghcr_auth(self):
        return {'basic': {'username': 'u', 'password': 'PW'}}


card_keep = dict(T.CARD)
ns = NS(**{**base, 'image': 'ghcr.io/x/y:t', 'cap': 1.0, 'cpu': 8, 'mem_mb': 32768, 'card': None, 'donor': 'd', 'force_out': False, 'tex_align': 'fit', 'gpu_fetch': lambda: items})
buf = io.StringIO()
with redirect_stdout(buf):
    rc = T.run(ns, DryMG(), NS())
txt = buf.getvalue()
ok('сухой прогон: код 0, задание `<ключ>-1024-42-0-mvp`, группа trial-mvpainter-t, карта по умолчанию RTX 5090 по имени из API, живая цена $0,60/ч, потолок $1,0; секретов в печати нет',
   rc == 0 and 'задание a_1-1024-42-0-mvp' in txt and 'trial-mvpainter-t' in txt and 'потолок $ 1.0' in txt and 'RTX 5090 (32 GB) тариф high цена $/ч 0.6 ' in txt and '"c5090"' in txt and 'hf_SECRET' not in txt and 'PW' not in txt and '<скрыто>' in txt, txt[:400])
ok('сухой прогон печатает таблицу классов от 40 ГБ с ценами (запасной путь), без 4090', 'классы GPU ≥ 40 ГБ' in txt and 'RTX A6000 (48 GB)' in txt and 'H100 (80 GB)' in txt and '0.490' in txt and 'RTX 4090 (24 GB)  ' not in txt.split('классы GPU')[1].split('группа')[0], txt[:600])
ns_m = NS(**{**ns.__dict__, 'skus': ['a:1', 'b:2'], 'texture_mesh': None, 'shape_dir': cat, 'out': None, 'suffix': 'm'})
buf = io.StringIO()
with redirect_stdout(buf):
    rc = T.run(ns_m, DryMG(), NS())
txt2 = buf.getvalue()
ok('два товара в ОДНОЙ группе (сухой прогон): код 0, одна группа trial-mvpainter-m, два задания — по товару, у каждого своя форма из каталога (clean2 / clean)',
   rc == 0 and txt2.count('  задание ') == 2 and 'задание a_1-1024-42-0-%s' % 'mvp' in txt2 and 'задание b_2-1024-42-0-%s' % 'mvp' in txt2 and txt2.count('группа trial-mvpainter-m ') == 1
   and 'a_1-1024-42-0.clean2.glb' in txt2 and 'b_2-1024-42-0.clean.glb' in txt2 and 'заданий 2' in txt2, txt2[:300])
ok('результаты — в СВОЕЙ папке модели (…/mesh-models-1118/mvpainter), не в общей `trellis/`', ns.out == T.default_out('mvpainter') and os.path.basename(ns.out) == 'mvpainter' and os.path.basename(ns.out) != 'trellis', str(ns.out))
open(os.path.join(tp, 'a_1-1024-42-0-mvp.model'), 'w').write('trellis2')
ok('чужой результат под тем же именем — отказ (owner_conflicts не ослаблен)', T.owner_conflicts(tp, ['a_1-1024-42-0-mvp'], 'mvpainter') == ['a_1-1024-42-0-mvp'])
T.CARD.update(card_keep)

ns2 = NS(**{**base, 'image': 'ghcr.io/x/y:t', 'cap': 1.0, 'cpu': 8, 'mem_mb': 32768, 'card': None, 'donor': 'd', 'force_out': False, 'tex_align': 'fit', 'gpu': 'cheapest', 'gpu_fetch': lambda: items})
buf = io.StringIO()
with redirect_stdout(buf):
    rc = T.run(ns2, DryMG(), NS())
txt2 = buf.getvalue()
ok('--gpu cheapest: выбран A6000 (самый дешёвый от 40 ГБ на high), в теле группы его id, цена $0,49/ч', rc == 0 and '--gpu cheapest: RTX A6000 (48 GB) (тариф high' in txt2 and '"a6000"' in txt2 and 'цена $/ч 0.49' in txt2, txt2[-700:])
T.CARD.update(card_keep)
items_med = [c for c in items if c['id'] in ('h100', 'c4090')]
ns3 = NS(**{**ns2.__dict__, 'gpu_fetch': lambda: items_med, 'tier': 'high'})
buf = io.StringIO()
with redirect_stdout(buf):
    rc = T.run(ns3, DryMG(), NS())
t3 = buf.getvalue()
ok('--gpu cheapest, на high ничего от 40 ГБ нет → тариф ниже, предупреждение «беру тариф medium», группа на нём', rc == 0 and 'беру тариф medium' in t3 and ns3.tier == 'medium' and '"priority": "medium"' in t3, t3[-500:])
T.CARD.update(card_keep)
ns4 = NS(**{**ns2.__dict__, 'gpu': 'list', 'gpu_fetch': lambda: items})
buf = io.StringIO()
with redirect_stdout(buf):
    rc4 = T.run(ns4, DryMG(), NS())
ok('--gpu list: только таблица и выход 0 (группу не собираем)', rc4 == 0 and 'RTX A6000 (48 GB)' in buf.getvalue() and 'группа trial' not in buf.getvalue())
T.CARD.update(card_keep)
ns5 = NS(**{**ns2.__dict__, 'gpu': 'RTX A6000 (48 GB)', 'gpu_fetch': lambda: items})
buf = io.StringIO()
with redirect_stdout(buf):
    rc5 = T.run(ns5, DryMG(), NS())
ok('--gpu "<полное имя>": класс и цена из ответа API (без второго обращения)', rc5 == 0 and '"a6000"' in buf.getvalue() and 'цена $/ч 0.49' in buf.getvalue(), buf.getvalue()[-400:])
T.CARD.update(card_keep)
ns6 = NS(**{**ns2.__dict__, 'gpu': 'cheapest', 'gpu_fetch': lambda: (_ for _ in ()).throw(OSError('нет сети'))})
buf = io.StringIO()
with redirect_stdout(buf):
    rc6 = T.run(ns6, DryMG(), NS())
ok('--gpu cheapest при недоступном API: отказ (код 2), а не выбор «наугад»; в печати — запасная таблица из rules', rc6 == 2 and 'снимок rules' in buf.getvalue())
T.CARD.update(card_keep)

# как в живой организации: классов от 40 ГБ нет, самый большой — 5090 (32 ГБ)
items_real = [{'id': 'c4090', 'name': 'RTX 4090 (24 GB)', 'prices': [{'priority': 'high', 'price': '0.440'}, {'priority': 'batch', 'price': '0.16'}]},
              {'id': 'c5090', 'name': 'RTX 5090 (32 GB)', 'prices': [{'priority': 'high', 'price': '0.600'}, {'priority': 'medium', 'price': '0.483'}]}]
ns7 = NS(**{**ns2.__dict__, 'gpu': None, 'gpu_fetch': lambda: items_real})
buf = io.StringIO()
with redirect_stdout(buf):
    rc7 = T.run(ns7, DryMG(), NS())
t7 = buf.getvalue()
ok('классов от 40 ГБ нет → печатается «нет ни одного» и следом все классы больше 24 ГБ (5090 — $0,60/ч); карта по умолчанию — 5090 с живой ценой 0,6',
   rc7 == 0 and 'нет ни одного класса от 40 ГБ' in t7 and 'RTX 5090 (32 GB)' in t7 and '0.600' in t7 and 'RTX 5090 (32 GB) тариф high цена $/ч 0.6 ' in t7, t7[:700])
T.CARD.update(card_keep)
ns8 = NS(**{**ns2.__dict__, 'gpu': 'cheapest', 'gpu_min_gb': 32, 'gpu_fetch': lambda: items_real})
buf = io.StringIO()
with redirect_stdout(buf):
    rc8 = T.run(ns8, DryMG(), NS())
ok('--gpu cheapest --gpu-min-gb 32: берёт 5090 (c5090, $0,60/ч)', rc8 == 0 and '--gpu cheapest: RTX 5090 (32 GB)' in buf.getvalue() and '"c5090"' in buf.getvalue() and 'цена $/ч 0.6' in buf.getvalue(), buf.getvalue()[-500:])
T.CARD.update(card_keep)
ns9 = NS(**{**ns2.__dict__, 'gpu': 'cheapest', 'gpu_fetch': lambda: items_real})
with redirect_stdout(io.StringIO()):
    rc9 = T.run(ns9, DryMG(), NS())
ok('--gpu cheapest при порогe 40 ГБ и без таких классов: отказ (код 2), а не молчаливая замена', rc9 == 2)
T.CARD.update(card_keep)
T.LIVE_PRICES.clear()

ns10 = NS(**{**ns2.__dict__, 'gpu': 'RTX 4090 (24 GB)', 'gpu_fetch': lambda: items})
buf = io.StringIO()
with redirect_stdout(buf):
    rc10 = T.run(ns10, DryMG(), NS())
ok('4090 — только явным `--gpu "RTX 4090 (24 GB)"`: класс 4090, цена живая $0,33 из ответа API (в тесте), не 5090', rc10 == 0 and 'RTX 4090 (24 GB) тариф high цена $/ч 0.33 ' in buf.getvalue() and '"c4090"' in buf.getvalue(), buf.getvalue()[-300:])
T.CARD.update(card_keep)
T.LIVE_PRICES.clear()
ns11 = NS(**{**ns2.__dict__, 'model': 'trellis2', 'texture_mesh': None, 'gpu': None, 'gpu_fetch': lambda: items, 'skus': ['a:1']})
buf = io.StringIO()
with redirect_stdout(buf):
    T.run(ns11, DryMG(), NS())
ok('деньги по живой цене для ВСЕХ моделей: у trellis2 (4090 по умолчанию) цена из API 0,33 берётся из LIVE_PRICES, а не из снимка rules (там 0,33 → отличим подменой)', ('цена $/ч 0.33 ' in buf.getvalue()) and ('RTX 4090 (24 GB)' in buf.getvalue()), buf.getvalue()[-300:])
T.CARD.update(card_keep)
T.LIVE_PRICES.clear()
items_live = [{'id': 'c4090', 'name': 'RTX 4090 (24 GB)', 'prices': [{'priority': 'high', 'price': '0.777'}]}]
ns12 = NS(**{**ns11.__dict__, 'gpu_fetch': lambda: items_live})
buf = io.StringIO()
with redirect_stdout(buf):
    T.run(ns12, DryMG(), NS())
ok('живая цена главнее снимка rules: API сказал 0,777 — в выводе 0,777', 'цена $/ч 0.777 ' in buf.getvalue(), buf.getvalue()[-300:])
T.CARD.update(card_keep)
T.LIVE_PRICES.clear()

# нехватка видеопамяти: пик памяти по стадиям попадает в диагностику задания (а оттуда — в summary-*.json драйвера)
oom_runner = W.MVPRunner('/opt/MV-Painter/MVPainter', '/b42', '/b36', '/tools', {}, run_stage=None)


def oom_stage(name, cmd, cwd, env=None, expect=(), timeout=0):
    if name == 'multiview':
        return {'name': name, 'rc': 0, 'seconds': 40.0, 'gpu_peak_mib': 20480, 'gpu_used_base_mib': 0, 'timed_out': False, 'tail': []}
    raise W.MVPStageError('стадия pbr_views: код выхода 1\ntorch.cuda.OutOfMemoryError: CUDA out of memory. Tried to allocate 3.00 GiB',
                          {'name': name, 'rc': 1, 'seconds': 12.0, 'gpu_peak_mib': 32000, 'gpu_used_base_mib': 0, 'timed_out': False, 'failed': True, 'tail': ['x']})


oom_runner.run_stage = oom_stage
wk = tempfile.mkdtemp(prefix='mvpo-')
try:
    oom_runner.run('mt', wk, {'steps': 5, 'seed': 1, 'reduce': True, 'pbr': True})
    ok('нехватка памяти на стадии → MVPStageError', False)
except W.MVPStageError as e_oom:
    be2 = W.MVPainterBackend()
    be2.runner = oom_runner
    d = be2.on_error(e_oom)
    ok('OOM: kind=oom, воркер жив, в диагностике пик по стадиям — multiview 20 ГиБ, упавшая pbr_views 31,25 ГиБ, общий пик 31,25 ГиБ, названа упавшая стадия',
       d['kind'] == 'oom' and d['fatal'] is False and d['peak_vram_gb'] == 31.25 and d['failed_stage'] == 'pbr_views' and [x['name'] for x in d['upstream_stages']] == ['multiview', 'pbr_views']
       and d['upstream_stages'][0]['gpu_peak_mib'] == 20480, str(d)[:300])
    import json as _j
    ok('диагностика сериализуется в JSON (уходит в res.json воркера и в summary драйвера)', len(_j.dumps(d, default=str)) > 50)
try:
    W.mvp_run_stage('t_oom', [sys.executable, '-c', 'import sys,time; time.sleep(1.3); print("CUDA out of memory"); sys.exit(1)'], wk, smi=lambda: 12345)
except W.MVPStageError as e3:
    ok('mvp_run_stage при сбое отдаёт замеры упавшей стадии (пик памяти) в исключении', e3.info.get('gpu_peak_mib') == 12345 and e3.info.get('failed') is True and e3.info.get('seconds', 0) >= 1.3, str(e3.info))

print('[6] скрипт пробы и образ (по тексту)')
sh = open(os.path.join(HERE, 'probe_mvpainter.sh'), encoding='utf-8').read()
lib = open(os.path.join(HERE, 'probe_lib.sh'), encoding='utf-8').read()
ok('probe_mvpainter.sh: товары — аргументы (отказ без них), в коде нет ни одного id товара', 'нужен хотя бы один товар' in lib and 'exit 2' in lib and 'probe_init "$@"' in sh
   and not __import__('re').search(r'\b\d{5,}:\d{10,}\b', sh + lib))
ok('форма: clean2, иначе clean; потолок CAP=1.0; вывод в t19-06-1119/mvp-<ЧЧММ>, НЕ в trellis/', 'clean2.glb' in lib and '.clean.glb' in lib and 'CAP="${CAP:-1.0}"' in sh and 't19-06-1119/mvp-$STAMP' in sh and 'OUT="${OUT:-$HOME/remlab-logs/mesh-models-1118/trellis' not in sh)
ok('несколько товаров в одной группе: --skus "${SKUS[@]}" и --shape-dir (форма на товар), кадры 0°/45° через render_stand.py, лист «гибрид р.3 | MV-Adapter | MVPainter» (общий `mv_sheet.py --cols`) — по товару в свою подпапку',
   '--skus "${SKUS[@]}"' in sh and '--shape-dir "$SHAPE_DIR"' in sh and 'probe_accept mvp "MVPainter"' in sh and '--only az000,az045' in lib and 'cols+=("MV-Adapter=${MVA[$s]}")' in lib
   and 'mv_sheet.py" --cols' in lib and 'd="$OUT/$skuf"' in lib and '$d/frames/$n' in lib)
ok('сухой прогон по умолчанию (APPLY=1 — платный), «денег 0»', 'APPLY:-0' in sh and 'денег 0' in sh)

# --- сами скрипты пробы, на подложном HOME и «питоне» echo: несколько товаров в одной команде драйверу, отказ до драйвера при отсутствии формы/фото ---
fh = tempfile.mkdtemp(prefix='fh-')
fb = os.path.join(fh, 'remlab-logs', 'mesh-models-1118', 'trellis')
os.makedirs(os.path.join(fb, 'inputs30'))
for fn in ('a_1-1024-42-0.clean2.glb', 'a_1-1024-42-0.clean.glb', 'b_2-1024-42-0.clean.glb'):
    open(os.path.join(fb, fn), 'wb').write(b'glTF')
for fn in ('a_1.rgba.png', 'b_2.rgba.png'):                      # c:3 — без формы и без фото
    open(os.path.join(fb, 'inputs30', fn), 'wb').write(b'\x89PNG')


def run_probe(script, *skus, **env):
    e = {**os.environ, 'HOME': fh, 'PY': '/bin/echo', 'OUT': os.path.join(fh, 'out-' + script), **env}
    e.pop('SKU', None)
    return subprocess.run(['bash', os.path.join(HERE, script), *skus], capture_output=True, text=True, env=e, timeout=60)


for script, model in (('probe_mvpainter.sh', 'mvpainter'), ('probe_supratex.sh', 'supratex'), ('probe_mvadapter.sh', 'mvadapter-i2tex')):
    r2 = run_probe(script, 'a:1', 'b:2')
    ok(f'{script} a:1 b:2 (сухой): код 0, «денег 0», драйверу ушли оба товара и каталог форм, без --apply и без одиночного --texture-mesh',
       r2.returncode == 0 and 'денег 0' in r2.stdout and f'--model {model}' in r2.stdout and '--skus a:1 b:2 ' in r2.stdout and f'--shape-dir {fb} ' in r2.stdout and '--apply' not in r2.stdout
       and '--texture-mesh' not in r2.stdout and 'clean2' in r2.stdout and '[a:1] форма' in r2.stdout and '[b:2] форма' in r2.stdout, r2.stdout[-400:] + r2.stderr[-300:])
    r3 = run_probe(script, 'a:1', 'c:3', 'b:2')
    ok(f'{script}: у c:3 нет ни формы, ни фото — отказ (код 2) ДО драйвера: драйвер не вызван, названы форма и фото, группа не создаётся',
       r3.returncode == 2 and '--model' not in r3.stdout and 'c:3] нет формы' in r3.stderr and 'c:3] нет фото' in r3.stderr and 'a:1] нет' not in r3.stderr and 'b:2] нет' not in r3.stderr
       and 'группа не создаётся' in r3.stderr, r3.stdout[-200:] + r3.stderr[-300:])
    r4 = run_probe(script)
    ok(f'{script} без товаров: отказ (код 2)', r4.returncode == 2 and 'нужен хотя бы один товар' in r4.stderr)
r5 = run_probe('probe_mvpainter.sh', 'a:1', 'a:1', 'b:2')
ok('повтор товара в аргументах не плодит заданий: a:1 один раз', '--skus a:1 b:2 ' in r5.stdout)
df = open(os.path.join(HERE, 'Dockerfile.mvpainter'), encoding='utf-8').read()
ok('Dockerfile.mvpainter: база по digest, коммит MV-Painter закреплён, оба Blender по sha256, пины версий, воркер и MODEL=mvpainter', '@sha256:' in df and 'f714682db5e6f78e8d1c7c0a43d1525638dda5a6' in df and df.count('sha256sum -c') >= 2
   and 'diffusers==0.20.2' in df and 'COPY worker_trellis.py' in df and 'MODEL=mvpainter' in df and 'blender-4.2.9-linux-x64' in df and 'blender-3.6.9-linux-x64' in df)
wf = open(os.path.join(HERE, '..', '..', '..', '..', '.github', 'workflows', 'build-mvpainter-trial.yml'), encoding='utf-8').read()
ok('workflow сборки: только ветки trial/trellis2*, Dockerfile.mvpainter, свой пакет mesh-mvpainter-trial, не трогает mvadapter', "branches: ['trial/trellis2*']" in wf and 'Dockerfile.mvpainter' in wf and 'mesh-mvpainter-trial' in wf and 'mvadapter' not in wf)

print('ИТОГО: ' + ('всё в норме' if not bad else f'провалов {bad}'))
sys.exit(1 if bad else 0)
