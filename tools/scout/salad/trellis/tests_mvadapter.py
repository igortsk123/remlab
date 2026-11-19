#!/usr/bin/env python3
"""Тесты `mvadapter-i2tex` — краска MV-Adapter по готовой форме TRELLIS.2 (T-20261119-06/2): геометрия видов, поворот по силуэту, «форма и развёртка не изменились» (допуск 1e-4),
путь вызова на заглушке апстрима (без видеокарты, сети, ключей, torch и MV-Adapter), отказ без формы, фатальная ошибка CUDA → «сломан», драйвер (тело группы, имя задания, своя папка результатов).
Разделы 1 и 3 — numpy/PIL (идут в CI); раздел 2 (заглушка апстрима, настоящий trimesh) пропускается без trimesh.

  python3 tools/scout/salad/trellis/tests_mvadapter.py
"""
from __future__ import annotations

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
remlab_tmp.use('tests_mvadapter')
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
    """Несимметричная фигура (буква Г из двух коробок, Y вверх): силуэт различает повороты на 90°."""
    return merge(box((-0.30, -0.30, -0.10), (0.30, -0.10, 0.10)), box((-0.30, -0.10, -0.10), (-0.10, 0.30, 0.10)))


def photo_of(V, F, yaw, size=(400, 300), n=240):
    """«Фото»: ортографический силуэт формы при повороте yaw, на непрозрачной альфе, в картинке НЕ квадратной формы (чтобы проверить рамку и масштаб апстрима)."""
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


print('[1] геометрия (numpy/PIL)')
m = np.zeros((100, 100), dtype=bool)
m[10:30, 20:70] = True                                   # 20×50: длинная сторона по x
nm = W.mv_norm_mask(m, 192)
ys, xs = np.nonzero(nm)
ok('рамка как у апстрима: длинная сторона = 0,9·n (±1 пиксель), предмет по центру кадра', abs((xs.max() - xs.min() + 1) - int(0.9 * 192)) <= 2 and abs((xs.min() + xs.max()) / 2 - 95.5) <= 1.5 and abs((ys.min() + ys.max()) / 2 - 95.5) <= 1.5, f'{xs.min()} {xs.max()} {ys.min()} {ys.max()}')
try:
    W.mv_norm_mask(np.zeros((8, 8), dtype=bool))
    ok('пустая маска — отказ', False)
except ValueError:
    ok('пустая маска — отказ', True)
u, v = W.mv_ortho_uv(np.array([[0.0, 0.0, 0.3], [0.55, 0.0, 0.0], [0.0, 0.55, 0.0], [-0.55, -0.55, 0.0]]))
ok('ортографика вида 0: центр — в середине кадра, +X — вправо до края (±0,55), +Y — вверх, глубина Z на кадр не влияет', np.allclose(u, [0.5, 1.0, 0.5, 0.0]) and np.allclose(v, [0.5, 0.5, 0.0, 1.0]))
V, F = l_shape()
fit = W.mv_fit_yaw(V, F, photo_of(V, F, 90))
ok('поворот по силуэту: фото снято с 90° (буква Г несимметрична) → 90°, IoU ≥ 0,9; в записи IoU по всем 4 поворотам, у выбранного — наибольший',
   fit['yaw_deg'] == 90 and fit['iou'] >= 0.9 and not fit['forced'] and len(fit['iou_by_yaw']) == 4 and fit['iou_by_yaw']['90'] == max(fit['iou_by_yaw'].values()), str(fit))
fit0 = W.mv_fit_yaw(V, F, photo_of(V, F, 0))
ok('фото с 0° → 0°', fit0['yaw_deg'] == 0, str(fit0))
fit_f = W.mv_fit_yaw(V, F, photo_of(V, F, 90), force='180')
ok('поворот задан руками (--mv-yaw 180): берётся он, forced=true, лучший по силуэту всё равно записан', fit_f['yaw_deg'] == 180 and fit_f['forced'] and fit_f['iou_best'] >= fit_f['iou'])
try:
    W.mv_fit_yaw(V, F, photo_of(V, F, 90), force=45)
    ok('поворот 45° не из списка — отказ', False)
except ValueError:
    ok('поворот 45° не из списка — отказ', True)
Vb, Fb = box((-0.3, -0.2, -0.1), (0.3, 0.2, 0.1))
fb = W.mv_fit_yaw(Vb, Fb, photo_of(Vb, Fb, 0))
ok('симметричный предмет (коробка): ничья между 0° и 180° → меньший угол, 0°', fb['yaw_deg'] == 0 and fb['iou_by_yaw']['0'] == fb['iou_by_yaw']['180'], str(fb))
try:
    W.mv_fit_yaw(V, F, Image.new('RGBA', (64, 64), (0, 0, 0, 0)))
    ok('фото без предмета — отказ', False)
except ValueError:
    ok('фото без предмета — отказ', True)
stubbed = W.mv_stub_modules()
ok('заглушки open3d/pymeshlab: ставятся только там, где модуля нет; `from pymeshlab import Percentage` работает, вызов — понятная ошибка',
   set(stubbed) <= {'open3d', 'pymeshlab'} and (('pymeshlab' not in stubbed) or (__import__('pymeshlab').Percentage is not None)))
for nme in stubbed:
    sys.modules.pop(nme, None)
if 'pymeshlab' in stubbed:
    try:
        W.mv_stub_modules()
        sys.modules['pymeshlab'].Percentage(1)
        ok('вызов заглушки — ошибка с причиной', False)
    except RuntimeError as e:
        ok('вызов заглушки — ошибка с причиной «нужен только развёртке UVAtlas»', 'UVAtlas' in str(e))
    sys.modules.pop('pymeshlab', None)
    sys.modules.pop('open3d', None)

print('[2] путь вызова на заглушке апстрима (trimesh)')
try:
    import trimesh
    have_tm = True
except ImportError:
    have_tm = False
    print('  · SKIP: нет trimesh в этом окружении (проверяется на pakardev)')
if have_tm:
    class FakeRunner:
        """Две стадии апстрима на заглушке: записывает, что получила; `unproject` возвращает GLB «как после gltflib» — та же геометрия и развёртка, новая текстура (JPEG-подобная, 64²)."""
        def __init__(self, perturb=None, drop_face=False, uv_shift=0.0, no_tex=False):
            self.calls, self.perturb, self.drop_face, self.uv_shift, self.no_tex = [], perturb, drop_face, uv_shift, no_tex

        def views(self, in_glb, image, params, work):
            m_in = trimesh.load(in_glb, force='mesh', process=False)
            self.in_verts, self.in_uv, self.in_faces = np.asarray(m_in.vertices).copy(), np.asarray(m_in.visual.uv).copy(), np.asarray(m_in.faces).copy()
            self.calls.append(('views', os.path.basename(in_glb), image.mode, params.get('mv_steps'), os.path.isdir(work)))
            path = os.path.join(work, 'mv.png')
            Image.new('RGB', (48, 8), (120, 130, 140)).save(path)
            return path

        def unproject(self, in_glb, views_png, work, uv_size):
            self.calls.append(('unproject', os.path.basename(views_png), uv_size))
            m_in = trimesh.load(in_glb, force='mesh', process=False)
            v = np.asarray(m_in.vertices).copy()
            if self.perturb:
                v[self.perturb[0], self.perturb[1]] += self.perturb[2]
            f = np.asarray(m_in.faces)[:-1] if self.drop_face else np.asarray(m_in.faces)
            uv = np.asarray(m_in.visual.uv) + self.uv_shift
            mat = trimesh.visual.material.PBRMaterial(baseColorTexture=None if self.no_tex else Image.new('RGB', (64, 64), (30, 200, 90)))
            out = trimesh.Trimesh(vertices=v, faces=f, visual=trimesh.visual.TextureVisuals(uv=uv, material=mat), process=False)
            p = os.path.join(work, 'mv_shaded.glb')
            out.export(p)
            return p

    shift = np.array([0.4, 0.15, -0.2])
    Vi = V * 0.8 + shift                                       # форма не в нуле и не в единичном масштабе (метры), как настоящий GLB
    uvs = np.stack([(Vi[:, 0] - Vi[:, 0].min()) / 0.5, (Vi[:, 1] - Vi[:, 1].min()) / 0.5], axis=1)
    mesh_in = trimesh.Trimesh(vertices=Vi, faces=F, visual=trimesh.visual.TextureVisuals(uv=uvs), process=False)
    photo0 = photo_of(V, F, 0)
    params = {'texture_size': 128, 'mv_steps': 7, 'mv_uv_size': 2048, 'mv_yaw': 'auto'}
    wk = tempfile.mkdtemp(prefix='mvw-')
    ev: list = []
    hk = {'sync': lambda: ev.append('sync'), 'free': lambda: ev.append('free'), 'mem': lambda n_: ev.append('mem:' + n_)}
    rn = FakeRunner()
    final, mt = W.mv_texture_on_shape(rn, mesh_in, photo0, params, hk, wk)
    ok('порядок стадий: виды → проекция; параметры доехали (шаги, размер развёртки, RGBA-фото)', [c[0] for c in rn.calls] == ['views', 'unproject'] and rn.calls[0][3] == 7 and rn.calls[0][2] == 'RGBA' and rn.calls[1][2] == 2048, str(rn.calls))
    ok('в апстрим ушёл куб (|v| ≤ 0,5) с ТЕМИ ЖЕ гранями и развёрткой, что у входа', np.abs(rn.in_verts).max() <= 0.5 + 1e-6 and np.array_equal(rn.in_faces, F) and np.allclose(rn.in_uv, uvs, atol=1e-6))
    ok('итог: ИСХОДНЫЕ вершины (метры, не куб), те же грани и развёртка', np.allclose(np.asarray(final.vertices), Vi, atol=1e-9) and np.array_equal(np.asarray(final.faces), F) and np.allclose(np.asarray(final.visual.uv), uvs))
    tex = final.visual.material.baseColorTexture
    ok('краска доехала: текстура приведена к texture_size 128 (из 64), цвет сохранён; металл 0, шероховатость 0,9', tex.size == (128, 128) and tuple(np.asarray(tex)[5, 5][:3]) == (30, 200, 90) and final.visual.material.metallicFactor == 0.0 and abs(final.visual.material.roughnessFactor - 0.9) < 1e-9)
    ok('метрики: форма не изменилась (Хаусдорф ≤ 1e-4), развёртка (UV) та же, стадии, поворот, число граней, миниатюра видов',
       mt['shape']['hausdorff_rel'] <= 1e-4 and mt['shape']['tris_in'] == mt['shape']['tris_out'] == len(F) and mt['uv_max_dev'] <= 1e-6 and mt['fit']['yaw_deg'] == 0 and mt['mesh_tris'] == len(F)
       and {'fit_yaw', 'write_input', 'views', 'unproject', 'check_shape', 'build'} <= set(mt['stage_s']) and mt['uv_size'] == 2048 and mt['steps'] == 7 and bool(mt['views_jpeg_b64']), str(mt)[:300])
    names = [e for e in ev if e.startswith('mem:')]
    ok('замер памяти после каждой стадии, на границе — синхронизация → освобождение → замер', names == ['mem:fit_yaw', 'mem:write_input', 'mem:views', 'mem:unproject', 'mem:check_shape', 'mem:build']
       and all(ev[i - 2] == 'sync' and ev[i - 1] == 'free' for i, e in enumerate(ev) if e.startswith('mem:')), str(ev))
    out_glb = os.path.join(wk, 'o.glb')
    final.export(out_glb)
    back = trimesh.load(out_glb, force='mesh', process=False)
    ok('GLB пишется и читается: те же грани и вершины', len(back.faces) == len(F) and np.allclose(np.asarray(back.vertices), Vi, atol=1e-6))
    # поворот: фото с 90° — форма идёт в апстрим повёрнутой, на выходе возвращается в исходный кадр
    rn90 = FakeRunner()
    final90, m90 = W.mv_texture_on_shape(rn90, mesh_in, photo_of(V, F, 90), params, None, tempfile.mkdtemp(prefix='mvw-'))
    p90 = W.to_cube(Vi, 90)[0]
    ok('фото с 90°: в апстрим ушла форма, повёрнутая на 90° (как `to_cube(…, 90)`), а итог — снова в исходном кадре', m90['fit']['yaw_deg'] == 90 and np.allclose(rn90.in_verts, p90, atol=1e-6) and np.allclose(np.asarray(final90.vertices), Vi, atol=1e-9)
       and m90['shape']['hausdorff_rel'] <= 1e-6, str(m90['fit']))
    # защита «форма не изменилась»
    for name, kw, text in (('вершина сдвинута на ~1,6 % диагонали', {'perturb': (5, 0, 0.01)}, 'форма сдвинулась'), ('потеряна грань', {'drop_face': True}, 'число треугольников'),
                           ('развёртка сдвинута на 0,01', {'uv_shift': 0.01}, 'развёртка изменилась')):
        try:
            W.mv_texture_on_shape(FakeRunner(**kw), mesh_in, photo0, params, None, tempfile.mkdtemp(prefix='mvw-'))
            ok(name + ' — ошибка, файл не отдаётся', False)
        except W.ShapeChanged as e:
            ok(name + ' — ShapeChanged с причиной', text in str(e), str(e))
    v_ok = FakeRunner(perturb=(5, 0, 0.5e-4 * 0.9))
    r_ok = W.mv_texture_on_shape(v_ok, mesh_in, photo0, params, None, tempfile.mkdtemp(prefix='mvw-'))
    ok('сдвиг ниже допуска (порядка 0,003 % диагонали куба) — проходит', r_ok[1]['shape']['hausdorff_rel'] <= W.SHAPE_TOL)
    try:
        W.mv_texture_on_shape(FakeRunner(no_tex=True), mesh_in, photo0, params, None, tempfile.mkdtemp(prefix='mvw-'))
        ok('апстрим вернул GLB без текстуры — отказ', False)
    except RuntimeError as e:
        ok('апстрим вернул GLB без текстуры — отказ с причиной', 'без текстуры' in str(e))
    no_uv = trimesh.Trimesh(vertices=Vi, faces=F, process=False)
    for name, mesh_x, prm in (('у формы нет развёртки', no_uv, params), ('mv_uv_size 777', mesh_in, {**params, 'mv_uv_size': 777}), ('mv_steps 0', mesh_in, {**params, 'mv_steps': 0}), ('mv_yaw 45', mesh_in, {**params, 'mv_yaw': 45})):
        rz = FakeRunner()
        try:
            W.mv_texture_on_shape(rz, mesh_x, photo0, prm, None, tempfile.mkdtemp(prefix='mvw-'))
            ok(name + ' — отказ до апстрима', False)
        except ValueError:
            ok(name + ' — ValueError до вызова апстрима (видеокарта не тронута)', rz.calls == [])

    # настоящий `generate` бэкенда на поддельных torch и раннере: файл рядом с OUT, рабочая папка убрана, выход не в `trellis/`
    def fake_torch():
        g = 2 ** 30
        cuda = NS(mem_get_info=lambda: (10 * g, 24 * g), memory_allocated=lambda: g, memory_reserved=lambda: 2 * g, max_memory_allocated=lambda: 3 * g, max_memory_reserved=lambda: 4 * g,
                  reset_peak_memory_stats=lambda: None, synchronize=lambda: None, empty_cache=lambda: None)
        mod = types.ModuleType('torch')
        mod.cuda, mod.inference_mode, mod.no_grad = cuda, (lambda: contextlib.nullcontext()), (lambda: contextlib.nullcontext())
        return mod
    torch_keep = sys.modules.get('torch')
    sys.modules['torch'] = fake_torch()
    sav = {k: getattr(W, k) for k in ('JOBS_DIR', 'OUT', 'STATE_PATH', 'BACKEND')}
    sav_state = dict(W.STATE)
    td = tempfile.mkdtemp(prefix='mvb-')
    W.JOBS_DIR, W.OUT, W.STATE_PATH = os.path.join(td, 'jobs'), os.path.join(td, 'out'), os.path.join(td, 'state.json')
    os.makedirs(W.JOBS_DIR)
    os.makedirs(W.OUT)
    try:
        os.environ['MODEL'] = 'mvadapter-i2tex'
        be = W.backend()
        ok('MODEL=mvadapter-i2tex → бэкенд MVAdapterTexBackend (без загрузки)', type(be).__name__ == 'MVAdapterTexBackend' and be.name == 'mvadapter-i2tex')
        os.environ['MODEL'] = 'pixal3d-tex'
        ok('MODEL=pixal3d-tex — прежний бэкенд, не затронут', type(W.backend()).__name__ == 'PixalTexBackend')
        os.environ.pop('MODEL', None)
        try:
            be.generate(Image.new('RGBA', (8, 8)), {'job_id': 'x'}, os.path.join(W.OUT, 'x.glb'))
            ok('без формы (--texture-mesh) бэкенд отказывает сразу', False)
        except ValueError as e:
            ok('без формы (--texture-mesh) бэкенд отказывает сразу, до torch и видеокарты', 'texture-mesh' in str(e))
        mesh_in.export(os.path.join(W.JOBS_DIR, 'j1-mvtex.mesh.glb'))
        be.runner = FakeRunner()
        out_path = os.path.join(W.OUT, 'j1-mvtex.glb')
        met = be.generate(photo0, {'job_id': 'j1-mvtex', 'texture_mesh': True, 'texture_size': 64, 'mv_steps': 5}, out_path)
        ok('generate: GLB записан, метрики: режим, пик памяти по замерам, память по стадиям, форма и развёртка не изменились',
           os.path.exists(out_path) and met['mode'] == 'mvadapter_i2tex' and met['peak_vram_gb'] == 3.0 and 'views' in met['mem'] and met['shape']['hausdorff_rel'] <= 1e-4 and 'load_shape' in met['stage_s'], str(met)[:300])
        ok('рабочая папка задания убрана (в OUT только результат)', sorted(os.listdir(W.OUT)) == ['j1-mvtex.glb'], str(os.listdir(W.OUT)))
        got = trimesh.load(out_path, force='mesh', process=False)
        ok('результат читается: вершины исходные, текстура 64²', np.allclose(np.asarray(got.vertices), Vi, atol=1e-6) and got.visual.material.baseColorTexture.size == (64, 64))
        # фатальная ошибка CUDA: воркер «сломан», как у pixal3d-tex
        for exc, want, fatal in ((RuntimeError('CUDA error: an illegal memory access was encountered'), 'fatal', True), (type('OutOfMemoryError', (RuntimeError,), {})('CUDA out of memory.'), 'oom', False),
                                 (ValueError('форма: нет мешей'), 'other', False)):
            d = be.on_error(exc)
            ok(f'on_error: «{str(exc)[:40]}» → {want}, fatal={fatal}', d['kind'] == want and d['fatal'] is fatal and 'stage_mem' in d and 'mem' in d, str(d)[:200])

        class Boom(W.MVAdapterTexBackend):
            def generate(self, image, params, path):
                raise RuntimeError('CUDA driver error: device not ready')
        W.BACKEND = Boom()
        W.STATE.update(phase='ready', warm=True, error=None)
        W.STATE.pop('broken', None)
        Image.new('RGBA', (8, 8), (1, 2, 3, 255)).save(os.path.join(W.JOBS_DIR, 'b1.png'))
        open(os.path.join(W.JOBS_DIR, 'b1.req.json'), 'w').write(json.dumps({'job_id': 'b1', 'texture_mesh': True}))
        W.run_job('b1')
        rb = json.load(open(os.path.join(W.JOBS_DIR, 'b1.res.json'), encoding='utf-8'))
        ok('фатальная ошибка CUDA в задании: failed, diag.fatal, воркер помечен сломанным (/health ok=false) — драйвер гасит группу', rb['status'] == 'failed' and rb['diag']['fatal'] is True and 'device not ready' in str(W.STATE.get('broken'))
           and W.health()['ok'] is False, str(rb.get('diag'))[:200])
    finally:
        for k, v in sav.items():
            setattr(W, k, v)
        W.STATE.clear()
        W.STATE.update(sav_state)
        os.environ.pop('MODEL', None)
        if torch_keep is None:
            sys.modules.pop('torch', None)
        else:
            sys.modules['torch'] = torch_keep

print('[3] драйвер')
import trellis_trial as T  # noqa: E402
b = T.build_body('trial-mvadapter-i2tex-x', 'ghcr.io/x/y:t', 'high', 'mvadapter-i2tex', 'hf_SECRET', 8, 32768, 'note', {'basic': {'username': 'u', 'password': 'PW'}}, extra_env={'MVTEX_OFFLOAD': '0'})
e = b['container']['environment_variables']
ok('тело группы: MODEL=mvadapter-i2tex, код воркера в command (python3 -u -c, без pip: версии закреплены в образе), приёмника на проде нет, окружение воркера доехало',
   e['MODEL'] == 'mvadapter-i2tex' and b['container']['command'][:2] == ['python3', '-u'] and not any(k.startswith('MESH_SINK') for k in e) and e['MVTEX_OFFLOAD'] == '0'
   and __import__('zlib').decompress(__import__('base64').b64decode(e['TRIAL_WORKER_Z'])) == open(os.path.join(HERE, 'worker_trellis.py'), 'rb').read())
ok('только 4090, образ тот же, веса открытые (закрытых весов проверять не надо)', b['container']['resources']['gpu_classes'] == [T.CARD['class_id']] and b['container']['image'] == 'ghcr.io/x/y:t' and 'mvadapter-i2tex' not in T.HF_GATED)
b2 = T.build_body('trial-trellis2-x', 'ghcr.io/x/y:t', 'high', 'trellis2', 'hf_SECRET', 8, 32768, 'note', {'basic': {}}, extra_env={'MVTEX_OFFLOAD': '0'})
ok('окружение воркера чужим моделям не передаётся', 'MVTEX_OFFLOAD' not in b2['container']['environment_variables'])
ok('--worker-env: MVTEX_* и PIXTEX_* проходят, чужое (HF_TOKEN, PATH) — отказ', T.parse_worker_env(['MVTEX_OFFLOAD=0', 'PIXTEX_LOW_VRAM=1']) == {'MVTEX_OFFLOAD': '0', 'PIXTEX_LOW_VRAM': '1'}
   and T.parse_worker_env(['HF_TOKEN=x']) is None and T.parse_worker_env(['PATH=/x']) is None)
ok('mv_options: по умолчанию auto/4096/50/1,0; кривое — None', T.mv_options(NS()) == {'mv_yaw': 'auto', 'mv_uv_size': 4096, 'mv_steps': 50, 'mv_ref_scale': 1.0}
   and T.mv_options(NS(mv_yaw='45')) is None and T.mv_options(NS(mv_uv_size=777)) is None and T.mv_options(NS(mv_steps=0)) is None and T.mv_options(NS(mv_ref_scale=3.0)) is None
   and T.mv_options(NS(mv_yaw='90', mv_uv_size=2048, mv_steps=30, mv_ref_scale=0.5)) == {'mv_yaw': '90', 'mv_uv_size': 2048, 'mv_steps': 30, 'mv_ref_scale': 0.5})

tp = tempfile.mkdtemp(prefix='mvd-')
json.dump({'a:1': {'input_png_sha256': 'x'}, 'b:2': {'input_png_sha256': 'y'}}, open(os.path.join(tp, 'inputs.json'), 'w'))
shape_path = os.path.join(tp, 'shape.glb')
open(shape_path, 'wb').write(b'glTF')


class NoTouchMG:
    def env_from_file(self):
        raise AssertionError('Salad тронут до проверки аргументов')

    def __getattr__(self, k):
        raise AssertionError('Salad тронут до проверки аргументов: ' + k)


base = dict(model='mvadapter-i2tex', inputs=tp, skus=['a:1'], plan='1024:1', seed=42, texture_mesh=shape_path, set=None, suffix='t', tier='high', texture=2048, decimation=500000,
            mv_yaw='auto', mv_uv_size=4096, mv_steps=50, mv_ref_scale=1.0, worker_env=[], debug_cuda=False, out=None, apply=False)
for name, kw in (('без --texture-mesh', {'texture_mesh': None}), ('два товара', {'skus': ['a:1', 'b:2']}), ('--mv-yaw 45', {'mv_yaw': '45'}), ('--mv-uv-size 777', {'mv_uv_size': 777}),
                 ('--mv-steps 0', {'mv_steps': 0}), ('--worker-env с чужой переменной', {'worker_env': ['HF_TOKEN=x']})):
    rc = T.run(NS(**{**base, **kw}), NoTouchMG(), NoTouchMG())
    ok(f'{name}: отказ (код 2) до обращения к Salad — группа не создаётся, денег 0', rc == 2)
rc = T.run(NS(**{**base, 'model': 'trellis2', 'worker_env': ['MVTEX_OFFLOAD=0'], 'texture_mesh': None}), NoTouchMG(), NoTouchMG())
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
    def env_from_file(self):
        pass

    def ghcr_auth(self):
        return {'basic': {'username': 'u', 'password': 'PW'}}


ns = NS(**{**base, 'image': 'ghcr.io/x/y:t', 'cap': 0.35, 'cpu': 8, 'mem_mb': 32768, 'card': None, 'donor': 'd', 'force_out': False, 'tex_align': 'fit'})
buf = io.StringIO()
with redirect_stdout(buf):
    rc = T.run(ns, DryMG(), NS())
txt = buf.getvalue()
ok('сухой прогон: код 0, задание `<ключ>-1024-42-0-mvtex`, группа trial-mvadapter-i2tex-…, потолок $0,35; секретов в печати нет', rc == 0 and 'задание a_1-1024-42-0-mvtex' in txt and 'trial-mvadapter-i2tex-t' in txt and 'потолок $ 0.35' in txt
   and 'hf_SECRET' not in txt and 'PW' not in txt and '<скрыто>' in txt, txt[:300])
ns_m = NS(**{**ns.__dict__, 'skus': ['a:1', 'b:2'], 'texture_mesh': None, 'shape_dir': cat, 'out': None, 'suffix': 'm'})
buf = io.StringIO()
with redirect_stdout(buf):
    rc = T.run(ns_m, DryMG(), NS())
txt2 = buf.getvalue()
ok('два товара в ОДНОЙ группе (сухой прогон): код 0, одна группа trial-mvadapter-i2tex-m, два задания — по товару, у каждого своя форма из каталога (clean2 / clean)',
   rc == 0 and txt2.count('  задание ') == 2 and 'задание a_1-1024-42-0-%s' % 'mvtex' in txt2 and 'задание b_2-1024-42-0-%s' % 'mvtex' in txt2 and txt2.count('группа trial-mvadapter-i2tex-m ') == 1
   and 'a_1-1024-42-0.clean2.glb' in txt2 and 'b_2-1024-42-0.clean.glb' in txt2 and 'заданий 2' in txt2, txt2[:300])
ok('результаты — в СВОЕЙ папке модели (…/mesh-models-1118/mvadapter-i2tex), не в общей `trellis/`', ns.out == T.default_out('mvadapter-i2tex') and os.path.basename(ns.out) == 'mvadapter-i2tex' and os.path.basename(ns.out) != 'trellis', ns.out)
ok('чужой результат в папке — отказ (owner_conflicts не ослаблен): файл от другой модели под тем же именем', T.owner_conflicts(tp, ['x'], 'mvadapter-i2tex') == [] and (lambda: (open(os.path.join(tp, 'x-1024-42-0-mvtex.model'), 'w').write('trellis2'), T.owner_conflicts(tp, ['x-1024-42-0-mvtex'], 'mvadapter-i2tex'))[1])() == ['x-1024-42-0-mvtex'])

print('ИТОГО: ' + ('всё в норме' if not bad else f'провалов {bad}'))
sys.exit(1 if bad else 0)
