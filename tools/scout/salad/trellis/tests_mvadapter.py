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
        # --- память процесса и группы на задание (T-20261119-06/6/1, issue #66: процесс убивали по обычной памяти при свободной видеопамяти) ---
        ok('метрики: peak_rss_gb (VmHWM процесса) числом, rss_peak_reset — булево, peak_cgroup_gb есть (число или None, если cgroup недоступен); на каждой стадии рядом с видеопамятью rss_gb и cgroup_gb',
           (met['peak_rss_gb'] is None or met['peak_rss_gb'] > 0) and isinstance(met['rss_peak_reset'], bool) and 'peak_cgroup_gb' in met and all('rss_gb' in v and 'cgroup_gb' in v for v in met['mem'].values()), str(met['mem'])[:300])
        cg_keep = W.cgroup_gb
        seq = iter([1.0, 2.0, 9.5, 4.0, 3.0] + [3.0] * 50)
        W.cgroup_gb = lambda: {'current': next(seq), 'max': 32.0}
        try:
            out2 = os.path.join(W.OUT, 'j1b-mvtex.glb')
            mesh_in.export(os.path.join(W.JOBS_DIR, 'j1b-mvtex.mesh.glb'))
            met2 = be.generate(photo0, {'job_id': 'j1b-mvtex', 'texture_mesh': True, 'texture_size': 64, 'mv_steps': 5}, out2)
            ok('peak_cgroup_gb — максимум current группы по стадиям (9,5), а не последнее значение', met2['peak_cgroup_gb'] == 9.5 and max(v['cgroup_gb'] for v in met2['mem'].values()) == 9.5, str(met2['peak_cgroup_gb']))
            W.cgroup_gb = lambda: {'current': 7.5, 'max': 32.0}
            d7 = be.on_error(RuntimeError('boom'))
            ok('on_error отдаёт и cgroup_gb, и rss_gb (память процесса), и пик VmHWM', d7['mem']['cgroup_gb'] == 7.5 and 'rss_gb' in d7['mem'] and 'peak_rss_gb' in d7)
            os.remove(out2)
        finally:
            W.cgroup_gb = cg_keep
        import unittest.mock as _um
        with _um.patch('builtins.open', side_effect=OSError('нет прав')):
            ok('сброс пика RSS не вышел (нет прав на clear_refs) — False, а не исключение; в метрике это видно', W.reset_rss_peak() is False)
        ok('сброс пика RSS: «5» пишется в /proc/self/clear_refs (где доступно)', (not os.path.exists('/proc/self/clear_refs')) or W.reset_rss_peak() in (True, False))
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

print('[2b] А0: mv_keep_stages — стадии сохраняются, итог не меняется (T-20261119-47/1)')
if have_tm:
    import zipfile

    class KeepRunner(FakeRunner):
        """Заглушка с поддержкой А0: `unproject(…, capture=)` кладёт «перехваченное» (как подслушивающие обёртки настоящего раннера), `keep_stages` пишет файлы и возвращает описание."""
        def __init__(self, fail=None, **kw):
            super().__init__(**kw)
            self.fail, self.capture_seen = fail, None

        def unproject(self, in_glb, views_png, work, uv_size, capture=None):
            self.capture_seen = capture
            if capture is not None:
                capture['up_pil'] = [Image.new('RGB', (12, 12), (i, i, i)) for i in range(6)]
            return super().unproject(in_glb, views_png, work, uv_size)

        def keep_stages(self, in_glb, uv_size, cap, tex_glb, tex_final, out_dir):
            self.calls.append(('keep_stages', uv_size, len(cap['up_pil']), tex_glb.size, tex_final.size))
            if self.fail:
                os.makedirs(os.path.join(out_dir, 'maps'), exist_ok=True)
                Image.new('RGB', (4, 4)).save(os.path.join(out_dir, 'maps', 'half.png'))
                raise self.fail
            os.makedirs(os.path.join(out_dir, 'render_view0'), exist_ok=True)
            tex_final.save(os.path.join(out_dir, 'render_view0', 'r2048.png'))
            return {'files': {'render_view0/r2048.png': 1}, 'timing_s': {'x': 0.1}, 'jpeg_mae_255': 0.5}

    base_final, base_mt = W.mv_texture_on_shape(FakeRunner(), mesh_in, photo0, params, None, tempfile.mkdtemp(prefix='mvw-'))
    ok('без флага: прежний вызов `unproject` (без capture — заглушка прежней подписи не падает), метрики без ключа stages и без стадии keep_stages',
       'stages' not in base_mt and 'keep_stages' not in base_mt['stage_s'])
    kr = KeepRunner()
    zp = os.path.join(tempfile.mkdtemp(prefix='mvz-'), 'o.stages.zip')
    fk, mk = W.mv_texture_on_shape(kr, mesh_in, photo0, {**params, 'mv_keep_stages': 1}, None, tempfile.mkdtemp(prefix='mvw-'), stages_zip=zp)
    ok('с флагом: итог тот же — вершины, грани, развёртка и ТОЧНО та же текстура (байты), что без флага',
       np.array_equal(np.asarray(fk.vertices), np.asarray(base_final.vertices)) and np.array_equal(np.asarray(fk.faces), np.asarray(base_final.faces))
       and np.array_equal(np.asarray(fk.visual.uv), np.asarray(base_final.visual.uv)) and np.array_equal(np.asarray(fk.visual.material.baseColorTexture), np.asarray(base_final.visual.material.baseColorTexture)))
    ok('с флагом: `unproject` получил capture, `keep_stages` — размер развёртки, 6 видов после апскейла, карту из GLB и итоговую 128²; guard формы сработал до него (метрики shape есть)',
       kr.capture_seen is not None and ('keep_stages', 2048, 6, (64, 64), (128, 128)) in kr.calls and [c[0] for c in kr.calls] == ['views', 'unproject', 'keep_stages'] and mk['shape']['hausdorff_rel'] <= 1e-4)
    with zipfile.ZipFile(zp) as z:
        names = sorted(z.namelist())
        mani = json.loads(z.read('manifest.json'))
        mv_cols = Image.open(io.BytesIO(z.read('views_768/v3.png')))
    ok('stages.zip: 6 видов по отдельности (v0…v5, каждый — своя шестая часть сетки без потерь), сетка mv.png, файлы раннера, manifest.json',
       all(f'views_768/v{i}.png' in names for i in range(6)) and 'mv.png' in names and 'render_view0/r2048.png' in names and 'manifest.json' in names and mv_cols.size == (8, 8), str(names))
    ok('manifest: размер развёртки, поворот, камеры (азимуты, подъёмы, ортокамера), ошибки нет, время стадий и потеря на JPEG от раннера',
       mani['uv_size'] == 2048 and mani['yaw_deg'] == 0 and mani['mv_az'] == W.MV_AZ and mani['mv_el'] == W.MV_EL and mani['ortho'] == 1.1 and mani['error'] is None and mani['jpeg_mae_255'] == 0.5 and mani['view_px'] == 768)
    st = mk['stages']
    ok('метрики задания: архив, размер в байтах, число файлов, время стадии сохранения (keep_s и stage_s.keep_stages), ошибка None', st['zip'] == 'o.stages.zip' and st['bytes'] == os.path.getsize(zp) and st['files'] == len(names)
       and st['error'] is None and st['keep_s'] >= 0 and 'keep_stages' in mk['stage_s'])
    # сбой самого сохранения: GLB не теряется, архив — из того, что успело сохраниться, причина — в метриках
    kf = KeepRunner(fail=ValueError('нет места'))
    zp2 = os.path.join(tempfile.mkdtemp(prefix='mvz-'), 'f.stages.zip')
    ff, mf = W.mv_texture_on_shape(kf, mesh_in, photo0, {**params, 'mv_keep_stages': '1'}, None, tempfile.mkdtemp(prefix='mvw-'), stages_zip=zp2)
    with zipfile.ZipFile(zp2) as z2:
        n2 = z2.namelist()
    ok('сбой в keep_stages (обычный): итог отдаётся, ошибка в метриках, архив есть и содержит уже сохранённое + manifest с ошибкой', np.array_equal(np.asarray(ff.visual.material.baseColorTexture), np.asarray(base_final.visual.material.baseColorTexture))
       and 'нет места' in mf['stages']['error'] and 'maps/half.png' in n2 and 'manifest.json' in n2 and 'views_768/v0.png' in n2, str(mf['stages']))
    try:
        W.mv_texture_on_shape(KeepRunner(fail=RuntimeError('CUDA error: an illegal memory access was encountered')), mesh_in, photo0, {**params, 'mv_keep_stages': 1}, None, tempfile.mkdtemp(prefix='mvw-'))
        ok('фатальная ошибка CUDA в keep_stages — наружу (воркер помечается сломанным, как везде)', False)
    except RuntimeError as e:
        ok('фатальная ошибка CUDA в keep_stages — наружу (воркер помечается сломанным, как везде)', 'illegal memory' in str(e))
    for off in (None, 0, '0', '', 'false'):
        rn_off = FakeRunner()
        _f, m_off = W.mv_texture_on_shape(rn_off, mesh_in, photo0, {**params, 'mv_keep_stages': off}, None, tempfile.mkdtemp(prefix='mvw-'))
        if 'stages' in m_off:
            ok(f'mv_keep_stages={off!r} — выключено', False)
            break
    else:
        ok('mv_keep_stages = None / 0 / «0» / «» / «false» — выключено: ни архива, ни ключа в метриках', True)
    ok('mv_keep_flag: 1, «1», True, «true» — включено; прочее — нет', all(W.mv_keep_flag(v) for v in (1, '1', True, 'true', 'True')) and not any(W.mv_keep_flag(v) for v in (None, 0, '0', '', 'false', False)))
    # делит сетку на шесть без потерь
    gd = tempfile.mkdtemp(prefix='mvs-')
    grid = Image.new('RGB', (6 * 10, 10))
    for i in range(6):
        grid.paste(Image.new('RGB', (10, 10), (i * 40, 255 - i * 40, 7)), (10 * i, 0))
    gp = os.path.join(gd, 'mv.png')
    grid.save(gp)
    rel = W.mv_split_views(gp, os.path.join(gd, 'views_768'))
    ok('mv_split_views: 6 файлов v0…v5, у каждого свой цвет, размер шестой части', rel == [f'views_768/v{i}.png' for i in range(6)]
       and all(tuple(Image.open(os.path.join(gd, r_)).getpixel((3, 3))) == (i * 40, 255 - i * 40, 7) and Image.open(os.path.join(gd, r_)).size == (10, 10) for i, r_ in enumerate(rel)))
    # generate: архив рядом с GLB (его отдаёт воркер как /glb/<id>?v=stages), рабочая папка убрана; без флага рядом только GLB (проверено выше)
    sav2 = {k: getattr(W, k) for k in ('JOBS_DIR', 'OUT', 'STATE_PATH')}
    td2 = tempfile.mkdtemp(prefix='mvb2-')
    W.JOBS_DIR, W.OUT, W.STATE_PATH = os.path.join(td2, 'jobs'), os.path.join(td2, 'out'), os.path.join(td2, 'state.json')
    os.makedirs(W.JOBS_DIR)
    os.makedirs(W.OUT)
    torch_keep2 = sys.modules.get('torch')
    sys.modules['torch'] = fake_torch()
    try:
        be2 = W.MVAdapterTexBackend()
        be2.runner = KeepRunner()
        mesh_in.export(os.path.join(W.JOBS_DIR, 'k1-mvtex.mesh.glb'))
        met_k = be2.generate(photo0, {'job_id': 'k1-mvtex', 'texture_mesh': True, 'texture_size': 64, 'mv_steps': 5, 'mv_keep_stages': 1}, os.path.join(W.OUT, 'k1-mvtex.glb'))
        ok('generate с mv_keep_stages: рядом с GLB лежит k1-mvtex.stages.zip, в метриках — stages (размер, файлы), рабочая папка убрана',
           sorted(os.listdir(W.OUT)) == ['k1-mvtex.glb', 'k1-mvtex.stages.zip'] and met_k['stages']['bytes'] == os.path.getsize(os.path.join(W.OUT, 'k1-mvtex.stages.zip')) and met_k['stages']['files'] >= 8, str(os.listdir(W.OUT)))
    finally:
        for k, v in sav2.items():
            setattr(W, k, v)
        if torch_keep2 is None:
            sys.modules.pop('torch', None)
        else:
            sys.modules['torch'] = torch_keep2

    # настоящий MVRunner на заглушке апстрима и настоящем torch (процессор): обёртки подслушивают, поведение не меняют, снимаются; keep_stages сохраняет все файлы
    try:
        import torch as real_torch
    except ImportError:
        real_torch = None
        print('  · SKIP: нет torch в этом окружении (раннер проверяется на pakardev)')
    if real_torch is not None:
        wk_ = tempfile.mkdtemp(prefix='mvr-')
        PT = types.ModuleType('mvadapter.pipelines.pipeline_texture')
        saved_calls: list = []
        PT.replace_mesh_texture_and_save = lambda *a, **kw: saved_calls.append(kw.get('texture')) or None
        MUm = types.ModuleType('mvadapter.utils.mesh_utils')
        MRm = types.ModuleType('mvadapter.utils.mesh_utils.render')
        MUTm = types.ModuleType('mvadapter.utils.mesh_utils.utils')

        class FakeCam:
            def __init__(self, n):
                self.w2c = real_torch.eye(4)[None].repeat(n, 1, 1)
                self.mvp_mtx = real_torch.eye(4)[None].repeat(n, 1, 1)
                self.n = n

            def __getitem__(self, i):
                return FakeCam(len(range(*i.indices(self.n))))

            def __len__(self):
                return self.n
        cam_args: dict = {}
        MUm.load_mesh = lambda path, **kw: (cam_args.__setitem__('load', kw), NS(v_pos=real_torch.zeros(3, 3), v_tex=real_torch.zeros(3, 2), t_pos_idx=real_torch.zeros(1, 3, dtype=real_torch.int64), t_tex_idx=real_torch.zeros(1, 3, dtype=real_torch.int64)))[1]
        MUm.get_orthogonal_camera = lambda **kw: (cam_args.__setitem__('cam', kw), FakeCam(6))[1]
        render_log: list = []

        def fake_render(ctx, mesh, cam, height, width, render_attr=True, render_depth=True, render_normal=True, texture_override=None, attr_background=0.5, texture_filter_mode='linear', **kw):
            render_log.append((height, render_attr, render_normal, None if texture_override is None else tuple(texture_override.shape)))
            attr = None if texture_override is None else texture_override.mean(dim=(0, 1)).expand(1, height, width, 3).contiguous()
            return NS(mask=real_torch.ones(1, height, width, dtype=real_torch.bool), normal=real_torch.tensor([0.0, 0.6, 0.8]).expand(1, height, width, 3).contiguous(), attr=attr)
        MRm.render = fake_render
        MUTm.get_clip_space_position = lambda v, mvp: real_torch.zeros(3, 4)
        for nm_, mod_ in (('mvadapter', types.ModuleType('mvadapter')), ('mvadapter.pipelines', types.ModuleType('mvadapter.pipelines')), ('mvadapter.pipelines.pipeline_texture', PT), ('mvadapter.utils', types.ModuleType('mvadapter.utils')),
                          ('mvadapter.utils.mesh_utils', MUm), ('mvadapter.utils.mesh_utils.render', MRm), ('mvadapter.utils.mesh_utils.utils', MUTm)):
            sys.modules[nm_] = mod_
        proj_calls: list = []

        class FakeTexPipe:
            device = 'cpu'

            def __init__(self):
                self.ctx = NS(rasterize=lambda clip, tri, res, grad_db=True: (real_torch.ones(1, res[0], res[1], 4), None), interpolate=lambda attr, rast, tri: (real_torch.full((1, rast.shape[1], rast.shape[2], 2), 0.25), None))

            def maybe_upscale_image(self, tensor, upscale, upscale_factor, batched=False):
                return tensor.repeat_interleave(2, dim=1).repeat_interleave(2, dim=2) if upscale else tensor

            def __call__(self, **kw):
                x = real_torch.rand(6, 4, 4, 3)
                self.maybe_upscale_image(x, True, 2)
                sys.modules['mvadapter.pipelines.pipeline_texture'].replace_mesh_texture_and_save('in', 'out', texture=Image.new('RGB', (16, 16), (10, 20, 30)), backend='gltflib')
                return NS(shaded_model_save_path=os.path.join(wk_, 'shaded.glb'))

            def cam_proj(self, images, mesh, cam, **kw):
                proj_calls.append((tuple(images.shape), len(cam), kw))
                return NS(uv_proj=real_torch.full((16, 16, 3), 0.25), uv_proj_mask=real_torch.ones(16, 16, dtype=real_torch.bool))
        tp_ = FakeTexPipe()
        orig_save = PT.replace_mesh_texture_and_save
        rr = W.MVRunner(None, tp_, lambda **k: k, None, False, real_torch)
        capn: dict = {}
        out_p = rr.unproject('in.glb', 'mv.png', wk_, 16, capture=capn)
        ok('MVRunner.unproject с capture: вызов апстрима прошёл, вернул путь; перехвачены 6 видов после апскейла (PNG), вид 0 в float32 [1,H,W,3], карта до JPEG 16²',
           out_p == os.path.join(wk_, 'shaded.glb') and len(capn['up_pil']) == 6 and capn['up_pil'][0].size == (8, 8) and tuple(capn['up0'].shape) == (1, 8, 8, 3) and capn['up0'].dtype == real_torch.float32
           and capn['tex_lossless'].size == (16, 16) and capn['tex_lossless'].getpixel((1, 1)) == (10, 20, 30))
        ok('обёртки сняты: `maybe_upscale_image` — снова метод класса (не атрибут экземпляра), `replace_mesh_texture_and_save` модуля — оригинал; оригинал при этом вызван (сохранение GLB не потеряно)',
           'maybe_upscale_image' not in vars(tp_) and PT.replace_mesh_texture_and_save is orig_save and len(saved_calls) == 1)
        out_n = rr.unproject('in.glb', 'mv.png', wk_, 16)
        ok('без capture — как раньше: ничего не перехвачено, оригинал вызван, обёртки не ставились', out_n == out_p and len(saved_calls) == 2 and 'maybe_upscale_image' not in vars(tp_))
        W_px = W.MV_STAGE_PX
        W.MV_STAGE_PX = 64
        try:
            out_dir = os.path.join(wk_, 'stages')
            tg = Image.new('RGB', (16, 16), (100, 110, 120))
            capn['tex_lossless'] = Image.new('RGB', (16, 16), (102, 110, 118))
            res = rr.keep_stages('in.glb', 16, capn, tg, Image.new('RGB', (8, 8), (50, 60, 70)), out_dir)
        finally:
            W.MV_STAGE_PX = W_px
        have_files = sorted(os.path.relpath(os.path.join(r_, f_), out_dir) for r_, _d, fs_ in os.walk(out_dir) for f_ in fs_)
        want = ([f'views_64/v{i}.png' for i in range(6)] + ['maps/tex4096_glb.png', 'maps/tex4096_lossless.png', 'maps/tex2048.png', 'maps/tex4096_from0.png', 'maps/tex4096_from0_valid.png',
                'render_view0/mask.png', 'render_view0/normal_cam.png', 'render_view0/aoi_cos16.png', 'render_view0/uv.npz'] + [f'render_view0/{n_}.png' for n_ in ('r4096_from6', 'r2048', 'r4096_lossless', 'r4096_from0')])
        ok('keep_stages: сохранены все файлы — виды после апскейла, четыре карты и валидность from0, маска, нормали, cos угла, UV, четыре рендера', have_files == sorted(want), str(set(want) ^ set(have_files)))
        ok('камера и форма — как в TexturePipeline: load_mesh(rescale, front_x_to_y, uv_size), орто ±0,55, расстояние 1, азимуты MV_AZ−90, подъёмы MV_EL; рендер от вида 0 (один вид)',
           cam_args['load'].get('rescale') is True and cam_args['load'].get('front_x_to_y') is True and cam_args['load'].get('move_to_center') is False and cam_args['load'].get('default_uv_size') == 16
           and cam_args['cam']['azimuth_deg'] == [x - 90 for x in W.MV_AZ] and cam_args['cam']['elevation_deg'] == W.MV_EL and abs(cam_args['cam']['right'] - 0.55) < 1e-9 and cam_args['cam']['distance'] == [1.0] * 6)
        pc = proj_calls[0]
        ok('запекание из вида 0: ОДИН вид (вид 0 после RealESRGAN, float), ОДНА камера, пороги как у основного (aoi 0,2; глубина 0,1/5; alpha 3), вес вида 1, from_scratch, без Пуассона; остальные виды не участвуют',
           pc[0] == (1, 8, 8, 3) and pc[1] == 1 and pc[2]['aoi_cos_valid_threshold'] == 0.2 and pc[2]['depth_grad_threshold'] == 0.1 and pc[2]['depth_grad_dilation'] == 5 and pc[2]['uv_exp_blend_alpha'] == 3
           and pc[2]['uv_exp_blend_view_weight'].tolist() == [1] and pc[2]['from_scratch'] is True and pc[2]['poisson_blending'] is False and pc[2]['uv_size'] == 16 and pc[2]['return_dict'] is True, str(pc[2]))
        ok('рендер с картой — в 2× (128) и усреднение до 64; текстуры переданы с их размерами (16 и 8)', (128, True, False, (16, 16, 3)) in render_log and (128, True, False, (8, 8, 3)) in render_log, str(render_log))
        rend = {n_: np.asarray(Image.open(os.path.join(out_dir, 'render_view0', n_ + '.png'))) for n_ in ('r4096_from6', 'r2048', 'r4096_lossless', 'r4096_from0')}
        ok('рендеры не перепутаны: каждый — цвет СВОЕЙ карты (из 6: 100/110/120, итог 2048: 50/60/70, до JPEG: 102/110/118, из вида 0: 64)', tuple(rend['r4096_from6'][5, 5]) == (100, 110, 120) and tuple(rend['r2048'][5, 5]) == (50, 60, 70)
           and tuple(rend['r4096_lossless'][5, 5]) == (102, 110, 118) and tuple(rend['r4096_from0'][5, 5]) == (64, 64, 64) and rend['r2048'].shape == (64, 64, 3))
        uvz = np.load(os.path.join(out_dir, 'render_view0', 'uv.npz'))
        aoi16 = np.asarray(Image.open(os.path.join(out_dir, 'render_view0', 'aoi_cos16.png')))
        ok('геометрия в камере вида 0: UV float32 [64,64,2] с маской, cos угла 16 бит (нормаль (0;0,6;0,8) → 0,8 → 52428), маска вся', uvz['uv'].shape == (64, 64, 2) and uvz['uv'].dtype == np.float32 and uvz['mask'].all() and aoi16.dtype == np.uint16
           and abs(int(aoi16[3, 3]) - 52428) <= 1 and np.asarray(Image.open(os.path.join(out_dir, 'render_view0', 'mask.png'))).all())
        ok('потеря на JPEG измерена: средняя |до JPEG − в GLB| по каналам = 1,3333 из 255 (2, 0, 2); описание: файлы, время стадий, UV-соглашение, камера',
           abs(res['jpeg_mae_255'] - 1.3333) < 1e-3 and 'bake_from0' in res['timing_s'] and res['uv_flip_v'] is True and res['camera']['azimuth_deg'] == W.MV_AZ[0] - 90 and set(res['files']) == set(want))
        for nm_ in ('mvadapter', 'mvadapter.pipelines', 'mvadapter.pipelines.pipeline_texture', 'mvadapter.utils', 'mvadapter.utils.mesh_utils', 'mvadapter.utils.mesh_utils.render', 'mvadapter.utils.mesh_utils.utils'):
            sys.modules.pop(nm_, None)

print('[2c] вариант 5 «12 камер» (T-20261119-48/1): параметр, камеры, слияние проходов, путь вызова')
ok('mv_views_count: нет/пусто/None/6/"6" — 6 камер (прежний путь); 12/"12" — 12', [W.mv_views_count(x) for x in (None, '', '  ', 6, '6')] == [6] * 5 and [W.mv_views_count(x) for x in (12, '12')] == [12, 12])
for bad_v in (8, '7', 'x', 0, 13, 12.5):
    try:
        W.mv_views_count(bad_v)
        ok(f'mv_views={bad_v!r} — отказ', False)
    except ValueError:
        ok(f'mv_views={bad_v!r} — ValueError (до всяких затрат)', True)
ok('шесть прежних камер не тронуты (MV_AZ, MV_EL, MV_VIEWS, MV_ORTHO как в апстриме)', W.MV_AZ == [-90, 0, 90, 180, 90, 90] and W.MV_EL == [0, 0, 0, 0, 89.99, -89.99] and W.MV_VIEWS == 6 and W.MV_ORTHO == 1.1)
ok('камеры второго прохода: шесть мест (как у модели), кольцо 0-1-2-3 на одном подъёме (ряды внимания идут вдоль строк), сдвиг 45° от первых четырёх, места 4 и 5 — косые (не чистые верх и низ)',
   len(W.MV2_AZ) == len(W.MV2_EL) == 6 and len(set(W.MV2_EL[:4])) == 1 and 0 < W.MV2_EL[0] < 60 and all(abs(((a2 - a1 + 180) % 360) - 180) == 45 for a1, a2 in zip(W.MV_AZ[:4], W.MV2_AZ[:4]))
   and all(abs(e) < 89 for e in W.MV2_EL[4:]), str((W.MV2_AZ, W.MV2_EL)))
import tex_coverage as TCV  # noqa: E402
cam1 = TCV.mv_views(W.MV_AZ, W.MV_EL)
cam2 = TCV.mv_views(W.MV2_AZ, W.MV2_EL)
ok('направления второго прохода не повторяют первые (угол между камерами ≥ 20°) — иначе проход пустой', all(float(np.dot(a[0], b[0])) < np.cos(np.radians(20)) for a in cam1 for b in cam2),
   str(max(float(np.dot(a[0], b[0])) for a in cam1 for b in cam2)))

# --- слияние проходов: mv_merge (numpy) ---
H_ = 40
rng_ = np.random.RandomState(5)
u1 = rng_.rand(H_, H_, 3).astype(np.float32)
u2 = (0.15 + 0.7 * rng_.rand(H_, H_, 3)).astype(np.float32)
allT = np.ones((H_, H_), bool)
conf_half = np.where(np.arange(H_)[None, :] < H_ // 2, 0.9, 0.3).astype(np.float32) * np.ones((H_, 1), np.float32)         # левая половина: первый проход видит хорошо, правая — слабо
m_off = {'match': False}
uo, vo, io_ = W.mv_merge(u1, allT, conf_half, u2, allT, np.full((H_, H_), 0.9, np.float32), m_off)
ok('хорошо видимое (|cos| 0,9 ≥ cos_hi) НЕ меняется ни на один бит; strong_changed = 0', np.array_equal(uo[:, :H_ // 2], u1[:, :H_ // 2]) and io_['strong_changed'] == 0 and io_['strong_pct'] == 50.0, str(io_))
need_ = (W.MV2_MERGE['cos_hi'] - 0.3) / (W.MV2_MERGE['cos_hi'] - W.MV2_MERGE['cos_lo'])
ok('плохо видимое (|cos| 0,3): второй проход подмешан с весом need·gain = (0,5−0,3)/0,3 = 0,667 — между проходами', np.allclose(uo[:, H_ // 2:], (1 - need_) * u1[:, H_ // 2:] + need_ * u2[:, H_ // 2:], atol=1e-5) and abs(io_['blended_pct'] - 50.0) < 1e-6, str(io_))
v1 = np.ones((H_, H_), bool)
v1[:, H_ // 2:] = False                                                                                    # правая половина первым проходом не видна вовсе
c1_ = np.where(v1, 0.9, 0.0).astype(np.float32)
v2 = np.ones((H_, H_), bool)
v2[:, :6] = False
v2[:5, :] = False                                                                                          # второй не видит левые 6 столбцов и верхние 5 строк
c2_ = np.where(v2, 0.8, 0.0).astype(np.float32)
uo, vo, io_ = W.mv_merge(u1, v1, c1_, u2, v2, c2_, m_off)
fill = ~v1 & v2
ok('невидимое первым и видимое вторым — берётся из второго проходом целиком (вес 1), «есть краска» поднимается', np.array_equal(uo[fill], u2[fill]) and vo[fill].all())
ok('невидимое обоими — остаётся как у первого (достроит LaMa), «краски нет» сохраняется', np.array_equal(uo[~v1 & ~v2], u1[~v1 & ~v2]) and not vo[~v1 & ~v2].any())
ok('то, что первый видит хорошо, а второй нет, — как у первого; счётчик «заполнено» = доля невидимого, которое увидел второй', np.array_equal(uo[v1], u1[v1]) and abs(io_['filled_pct'] - 100.0 * fill.sum() / fill.size) < 1e-3, str(io_))
uo, vo, io_ = W.mv_merge(u1, allT, np.full((H_, H_), 0.3, np.float32), u2, allT, np.full((H_, H_), 0.25, np.float32), m_off)
ok('второй видит ХУЖЕ первого — первый не трогаем (вес 0)', np.array_equal(uo, u1) and io_['blended_pct'] == 0.0, str(io_))
uo, vo, io_ = W.mv_merge(u1, v1, c1_, u2, np.zeros((H_, H_), bool), np.zeros((H_, H_), np.float32))
ok('второй проход пуст — итог равен первому (краска и «есть краска»): с пустым вторым путь тот же, что у апстрима', np.array_equal(uo, u1) and np.array_equal(vo, v1))
# подгонка цвета второго к первому по общим хорошо видимым текселям
a_c = rng_.rand(H_, H_, 3).astype(np.float32) * 0.6 + 0.2
b_c = np.clip(0.7 * a_c + 0.05, 0, 1)                                                                      # второй проход темнее и контрастнее ниже: известное линейное искажение
v1m = np.ones((H_, H_), bool)
v1m[:, H_ // 2:] = False
c1m = np.where(v1m, 0.9, 0.0).astype(np.float32)
v2m = np.ones((H_, H_), bool)
c2m = np.full((H_, H_), 0.9, np.float32)
uo, vo, io_ = W.mv_merge(a_c, v1m, c1m, b_c, v2m, c2m, {'match_min': 100})
ok('подгонка включилась по общим текселям (левая половина) и зажала усиление 1/0,7 = 1,43 до gain_max 1,4', io_['match'] == 'on' and io_['match_texels'] == (H_ * H_) // 2 and abs(io_['gain'][0] - W.MV2_MERGE['gain_max']) < 1e-6, str(io_))
fl = ~v1m
raw_err = float(np.abs(b_c[fl] - a_c[fl]).mean())
fit_err = float(np.abs(uo[fl] - a_c[fl]).mean())
ok('после подгонки заполненные тексели ближе к «истинному» цвету, чем без неё (и всё в [0, 1])', fit_err < raw_err * 0.7 and uo.min() >= 0.0 and uo.max() <= 1.0, f'{raw_err:.4f} -> {fit_err:.4f}')
uo, vo, io_ = W.mv_merge(a_c, v1m, c1m, b_c, v2m, c2m, {'match_min': 10 ** 9})
ok('общих текселей мало — подгонка пропущена (второй проход как есть)', io_['match'] == 'skipped' and np.array_equal(uo[fl], b_c[fl]), str(io_))
uo, vo, io_ = W.mv_merge(a_c, v1m, c1m, b_c, v2m, c2m, {'match_min': 100, 'match': False})
ok('подгонку можно выключить (match=False): второй проход как есть', io_['match'] == 'off' and np.array_equal(uo[fl], b_c[fl]))
ok('в info есть всё для отчёта: доли валидности до/после, заполнено, подмешано, заменено, strong', {'texels', 'valid1_pct', 'valid_pct', 'filled_pct', 'blended_pct', 'replaced_pct', 'strong_pct', 'strong_changed'} <= set(io_))

if have_tm:
    class Fake12(FakeRunner):
        """Заглушка с вариантом 5: вторая стадия видов и запекание двух проходов."""
        def views2(self, in_glb, image, params, work):
            self.calls.append(('views2', os.path.basename(in_glb), params.get('mv_views')))
            path = os.path.join(work, 'mv2.png')
            Image.new('RGB', (48, 8), (200, 100, 50)).save(path)
            return path

        def unproject12(self, in_glb, views1_png, views2_png, work, uv_size):
            n_ = len(self.calls)
            out = FakeRunner.unproject(self, in_glb, views1_png, work, uv_size)              # общий код сборки GLB заглушки; его запись в calls убираем — это не вызов шести видов
            del self.calls[n_:]
            self.calls.append(('unproject12', os.path.basename(views1_png), os.path.basename(views2_png), uv_size))
            self.merge_info = {'match': 'on', 'filled_pct': 12.5, 'strong_changed': 0}
            return out

    p12 = {**params, 'mv_views': 12}
    r12 = Fake12()
    f12, m12 = W.mv_texture_on_shape(r12, mesh_in, photo0, p12, None, tempfile.mkdtemp(prefix='mvw-'))
    ok('12 камер: порядок стадий виды → виды2 → запекание двух проходов (одноразовый `unproject` шести видов не зовётся)', [c[0] for c in r12.calls] == ['views', 'views2', 'unproject12'] and r12.calls[2][1:3] == ('mv.png', 'mv2.png'), str(r12.calls))
    ok('12 камер: метрики — mv_views, камеры, итог слияния, миниатюра видов 2 и время обоих проходов; стадии views2 и unproject в stage_s',
       m12['mv_views'] == 12 and m12['mv12']['az'] == W.MV2_AZ and m12['mv12']['el'] == W.MV2_EL and m12['mv12']['merge']['filled_pct'] == 12.5 and bool(m12['views2_jpeg_b64'])
       and {'views', 'views2', 'unproject'} <= set(m12['stage_s']) and m12['mv12']['views_s']['pass2'] == m12['stage_s']['views2'], str(m12)[:300])
    ok('12 камер: защита «форма и развёртка не изменились» работает так же — итог те же вершины/грани/развёртка', np.allclose(np.asarray(f12.vertices), Vi, atol=1e-9) and np.array_equal(np.asarray(f12.faces), F) and m12['shape']['hausdorff_rel'] <= 1e-4)
    try:
        W.mv_texture_on_shape(Fake12(perturb=(5, 0, 0.01)), mesh_in, photo0, p12, None, tempfile.mkdtemp(prefix='mvw-'))
        ok('12 камер: сдвинутая форма — ошибка', False)
    except W.ShapeChanged:
        ok('12 камер: сдвинутая форма — ShapeChanged (файл не отдаётся)', True)
    for nm, prm in (('mv_views=8', {**params, 'mv_views': 8}), ('mv_views=12 вместе с mv_keep_stages', {**p12, 'mv_keep_stages': 1})):
        rz = Fake12()
        try:
            W.mv_texture_on_shape(rz, mesh_in, photo0, prm, None, tempfile.mkdtemp(prefix='mvw-'))
            ok(nm + ' — отказ до вызова апстрима', False)
        except ValueError:
            ok(nm + ' — ValueError до вызова апстрима (видеокарта не тронута, платить не за что)', rz.calls == [])
    # по умолчанию — прежний путь: заглушка БЕЗ views2/unproject12, набор метрик без новых ключей
    base_calls = FakeRunner()
    f6, m6 = W.mv_texture_on_shape(base_calls, mesh_in, photo0, params, None, tempfile.mkdtemp(prefix='mvw-'))
    f6b, m6b = W.mv_texture_on_shape(FakeRunner(), mesh_in, photo0, {**params, 'mv_views': 6}, None, tempfile.mkdtemp(prefix='mvw-'))
    f6c, m6c = W.mv_texture_on_shape(FakeRunner(), mesh_in, photo0, {**params, 'mv_views': ''}, None, tempfile.mkdtemp(prefix='mvw-'))
    new_keys = {'mv_views', 'mv12', 'views2_jpeg_b64'}
    ok('без параметра, с mv_views=6 и с пустым — РОВНО прежний путь (views → unproject; у заглушки нет views2/unproject12), новых ключей метрик нет',
       [c[0] for c in base_calls.calls] == ['views', 'unproject'] and not (new_keys & set(m6)) and not (new_keys & set(m6b)) and not (new_keys & set(m6c)) and set(m6) == set(m6b) == set(m6c))
    ok('итог шести камер не зависит от наличия параметра (те же байты текстуры и вершин)', np.array_equal(np.asarray(f6.visual.material.baseColorTexture), np.asarray(f6b.visual.material.baseColorTexture))
       and np.array_equal(np.asarray(f6.vertices), np.asarray(f6b.vertices)))

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
ok('mv_options: --mv-views 12 → ключ mv_views=12; 6/нет → ключа НЕТ (тело задания прежнее); 8 и 12 вместе с --mv-keep-stages → None',
   T.mv_options(NS(mv_views=12)) == {'mv_yaw': 'auto', 'mv_uv_size': 4096, 'mv_steps': 50, 'mv_ref_scale': 1.0, 'mv_views': 12}
   and T.mv_options(NS(mv_views=6)) == T.mv_options(NS()) == {'mv_yaw': 'auto', 'mv_uv_size': 4096, 'mv_steps': 50, 'mv_ref_scale': 1.0} and T.mv_options(NS(mv_views=8)) is None
   and T.mv_options(NS(mv_views=12, mv_keep_stages=True)) is None and 'mv_views' in T.mv_options(NS(mv_views=12, mv_yaw='90')))
cat3 = tempfile.mkdtemp(prefix='shp3-')                        # SHAPE_TAG / --shape-tag: форма ТОЛЬКО заданного вида, без запасных
for fn_ in ('a_1-1024-42-0.clean2.glb', 'a_1-1024-42-0.clean3.glb', 'b_2-1024-42-0.clean2.glb'):
    open(os.path.join(cat3, fn_), 'wb').write(b'glTF')
ok('find_shape: без тега — прежний порядок clean2 → clean; с тегом clean3 — только он; тега нет у товара — None (не подменяем формой clean2)',
   T.find_shape(cat3, 'a:1')[0].endswith('a_1-1024-42-0.clean2.glb') and T.find_shape(cat3, 'a:1', 'clean3')[0].endswith('a_1-1024-42-0.clean3.glb') and T.find_shape(cat3, 'b:2', 'clean3') is None
   and T.find_shape(cat3, 'b:2')[0].endswith('b_2-1024-42-0.clean2.glb'))
rc = T.run(NS(**{**base, 'skus': ['a:1', 'b:2'], 'texture_mesh': None, 'shape_dir': cat3, 'shape_tag': 'clean3'}), NoTouchMG(), NoTouchMG())
ok('--shape-tag clean3, а у b:2 такой формы нет — отказ (код 2) ДО Salad, группа не создаётся, денег 0', rc == 2)
rc = T.run(NS(**{**base, 'skus': ['a:1'], 'texture_mesh': None, 'shape_dir': cat3, 'shape_tag': '../x'}), NoTouchMG(), NoTouchMG())
ok('--shape-tag с путём вместо имени — отказ до Salad', rc == 2)
rc = T.run(NS(**{**base, 'texture_mesh': None, 'shape_dir': cat3, 'mv_views': 12, 'mv_keep_stages': True}), NoTouchMG(), NoTouchMG())
ok('--mv-views 12 вместе с --mv-keep-stages — отказ до Salad', rc == 2)
ns12 = NS(**{**ns.__dict__, 'skus': ['a:1'], 'texture_mesh': None, 'shape_dir': cat3, 'shape_tag': 'clean3', 'mv_views': 12, 'out': None, 'suffix': 'v'})
buf = io.StringIO()
with redirect_stdout(buf):
    rc = T.run(ns12, DryMG(), NS())
t12 = buf.getvalue()
ok('сухой прогон с --mv-views 12 --shape-tag clean3: код 0, форма clean3, в печати параметров задания mv_views=12, секретов нет, группа не создаётся (денег 0)',
   rc == 0 and 'a_1-1024-42-0.clean3.glb' in t12 and '"mv_views": 12' in t12 and 'hf_SECRET' not in t12 and 'PW' not in t12 and 'задание a_1-1024-42-0-mvtex' in t12, t12[:400])
ns6 = NS(**{**ns.__dict__, 'skus': ['a:1'], 'texture_mesh': None, 'shape_dir': cat3, 'out': None, 'suffix': 'w'})
buf = io.StringIO()
with redirect_stdout(buf):
    rc = T.run(ns6, DryMG(), NS())
t6 = buf.getvalue()
ok('сухой прогон БЕЗ параметров: форма по прежнему порядку (clean2), в параметрах задания нет mv_views', rc == 0 and 'a_1-1024-42-0.clean2.glb' in t6 and 'mv_views' not in t6, t6[:300])
ok('чужой результат в папке — отказ (owner_conflicts не ослаблен): файл от другой модели под тем же именем', T.owner_conflicts(tp, ['x'], 'mvadapter-i2tex') == [] and (lambda: (open(os.path.join(tp, 'x-1024-42-0-mvtex.model'), 'w').write('trellis2'), T.owner_conflicts(tp, ['x-1024-42-0-mvtex'], 'mvadapter-i2tex'))[1])() == ['x-1024-42-0-mvtex'])

print('ИТОГО: ' + ('всё в норме' if not bad else f'провалов {bad}'))
sys.exit(1 if bad else 0)
