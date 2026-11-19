#!/usr/bin/env python3
"""Тесты `pixal3d-tex` — краски Pixal3D по готовой форме TRELLIS.2 (T-20261119-05, П1.91): геометрия, проверка «форма не изменилась», путь вызова на заглушке, драйвер.
Без видеокарты, сети, ключей и без torch. Разделы 1 и 3 — только numpy и PIL (идут в CI); раздел 2 (заглушка пайплайна, настоящий trimesh) пропускается без trimesh.

  python3 tools/scout/salad/trellis/tests_pixal_tex.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.normpath(os.path.join(HERE, '..', '..')))
import remlab_tmp  # noqa: E402
remlab_tmp.use('tests_pixal_tex')
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402
import worker_trellis as W  # noqa: E402

bad = 0


def ok(name, cond, extra=''):
    global bad
    print(('  ✓ ' if cond else '  ✗ ') + name + (f' — {extra}' if extra and not cond else ''))
    bad += 0 if cond else 1


def box(lo, hi):
    """Коробка из 12 треугольников: (вершины, грани)."""
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
    """Несимметричная фигура (буква Г из двух коробок, Y вверх): её силуэт различает повороты на 90°."""
    return merge(box((-0.30, -0.30, -0.10), (0.30, -0.10, 0.10)), box((-0.30, -0.10, -0.10), (-0.10, 0.30, 0.10)))


def photo_from_mask(M0, sigma, tx, ty, n=256):
    """Фото, из которого подгонка σ, tx, ty вернёт силуэт M0: P[x_вх] = M0[0,5 + σ·(x_вх − 0,5) + t] (обратное к `_warp_mask`)."""
    xs = (np.arange(n) + 0.5) / n
    ix = np.floor((0.5 + sigma * (xs - 0.5) + tx) * n).astype(int)
    iy = np.floor((0.5 + sigma * (xs - 0.5) + ty) * n).astype(int)
    vx, vy = (ix >= 0) & (ix < n), (iy >= 0) & (iy < n)
    P = np.zeros((n, n), dtype=bool)
    P[np.ix_(vy, vx)] = M0[np.ix_(iy[vy], ix[vx])]
    a = (P * 255).astype(np.uint8)
    rgba = np.stack([np.where(P, 180, 0), np.where(P, 120, 0), np.where(P, 60, 0), a], axis=-1).astype(np.uint8)
    return Image.fromarray(rgba, 'RGBA')


FOV = 0.8
DIST = 0.5 / np.tan(FOV / 2)

print('[1] геометрия (numpy/PIL)')
R90 = W.rot_y(90)
ok('поворот на 90°: ось +Z → +X, ортогональный, определитель 1', np.allclose(R90 @ np.array([0, 0, 1.0]), [1, 0, 0]) and np.allclose(R90 @ R90.T, np.eye(3)) and abs(np.linalg.det(R90) - 1) < 1e-12)
ok('поворот на 360° — единичная матрица, на 45° — не «кратный» (обычный косинус)', np.array_equal(W.rot_y(360), np.eye(3)) and abs(W.rot_y(45)[0, 0] - np.cos(np.pi / 4)) < 1e-12)
V, F = l_shape()
worst_rt, worst_box = 0.0, 0.0
for yaw in W.YAWS_DEG:
    p, c, s, R = W.to_cube(V + np.array([5.0, -2.0, 1.0]), yaw)
    worst_rt = max(worst_rt, float(np.abs(W.from_cube(p, c, s, R) - (V + np.array([5.0, -2.0, 1.0]))).max()))
    worst_box = max(worst_box, float(np.abs(p).max()) - 0.5, abs(float((p.max(0) - p.min(0)).max()) - 0.99999))
ok('куб: туда-обратно без потерь на любом повороте со сдвигом; в [−0,5; 0,5], наибольшая сторона 0,99999', worst_rt < 1e-12 and worst_box < 1e-9, f'{worst_rt} {worst_box}')
fwd = np.stack([V[:, 0], V[:, 2], -V[:, 1]], axis=1)          # то, что делает postprocess_mesh апстрима в конце: (x, y, z) → (x, z, −y)
ok('обратный обмен осей возвращает вершины как были', np.allclose(W.undo_upstream_swap(fwd), V))
try:
    W.to_cube(np.zeros((4, 3)), 0)
    ok('вырожденная форма — отказ', False)
except ValueError:
    ok('вырожденная форма — отказ', True)


def upstream_project(p, fov, dist, mesh_scale=1.0, resolution=512):
    """Независимая запись апстрима (numpy): ProjGrid.forward + project_points_to_image_batch. Сетка g = 2p, поворот к Blender, камера на (0, −dist, 0), объектив 32 мм."""
    g = np.asarray(p, dtype=np.float64) * 2.0
    rot = np.array([[1.0, 0, 0], [0, 0, -1.0], [0, 1.0, 0]])
    gp = (g @ rot.T) / mesh_scale / 2.0
    tm = np.array([[1.0, 0, 0, 0], [0, 0, -1.0, -dist], [0, 1.0, 0, 0], [0, 0, 0, 1.0]])
    hom = np.concatenate([gp, np.ones((len(gp), 1))], axis=1)
    cam = (hom @ np.linalg.inv(tm).T)[:, :3]
    focal_px = (16.0 / np.tan(fov / 2.0)) * resolution / 32.0
    x = focal_px * cam[:, 0] / (-cam[:, 2] + 1e-8) + resolution / 2.0
    y = -(focal_px * cam[:, 1] / (-cam[:, 2] + 1e-8)) + resolution / 2.0
    return x / resolution, y / resolution


rng = np.random.default_rng(1)
pts = rng.uniform(-0.5, 0.5, (500, 3))
u, v, d = W.project_cube(pts, FOV, DIST)
uu, vv = upstream_project(pts, FOV, DIST)
ok('проекция совпадает с записью апстрима (ProjGrid + project_points_to_image_batch), 500 точек, расхождение < 1e-6 кадра', np.abs(u - uu).max() < 1e-6 and np.abs(v - vv).max() < 1e-6, f'{np.abs(u - uu).max()} {np.abs(v - vv).max()}')
uc, vc, _ = W.project_cube(np.array([[0.5, 0.0, 0.0], [0.0, 0.5, 0.0], [0.0, 0.0, 0.0], [0.5, 0.0, 0.25]]), FOV, DIST)
ok('центральная плоскость куба занимает кадр по ширине (u = 1,0), центр — в середине, вверх по Y — вверх в кадре, ближе к камере — крупнее',
   abs(uc[0] - 1.0) < 1e-9 and abs(vc[1] - 0.0) < 1e-9 and abs(uc[2] - 0.5) < 1e-12 and uc[3] > 1.0)


def distance_from_fov_upstream(fov, res=512):
    """Запись `distance_from_fov` апстрима для точки сетки (−1, 0, 0) и пикселя x = 0 (так её зовёт `get_camera_params_wild_moge`)."""
    f_pixels = (16.0 / np.tan(fov / 2.0)) * res / 32.0
    return f_pixels * (-0.5) / (0 - res / 2.0) - 0.0


ok('distance_from_fov апстрима даёт расстояние F = 0,5 / tan(fov/2) — на нём и стоит DIST в тестах', abs(distance_from_fov_upstream(FOV) - DIST) < 1e-9)

# вырезка как в апстриме
im = Image.new('RGBA', (300, 200), (0, 0, 0, 0))
im.paste(Image.new('RGBA', (100, 60), (200, 50, 50, 255)), (120, 70))
cr = W.crop_square_rgba(im)
ok('вырезка: квадрат со стороной int(99·1,1) = 108 (99 — разность крайних пикселей по альфе, как в апстриме), предмет по центру', cr.size == (108, 108) and np.asarray(cr)[:, :, 3][50:58, 50:58].min() == 255, str(cr.size))
try:
    W.crop_square_rgba(Image.new('RGBA', (20, 20), (0, 0, 0, 0)))
    ok('пустая альфа — отказ', False)
except ValueError:
    ok('пустая альфа — отказ', True)
bk = W.compose_black(Image.new('RGBA', (4, 4), (200, 100, 50, 128)))
ok('на чёрном: rgb · alpha', abs(int(np.asarray(bk)[0, 0, 0]) - 100) <= 1 and bk.mode == 'RGB')

# подгонка: фото получено из силуэта буквы Г, повёрнутой на 90°, с известным масштабом и сдвигом
p90, _c, _s, _R = W.to_cube(V, 90)
SS, TX, TY = 1.4, 0.03, -0.02
u90, v90, _ = W.project_cube(p90, FOV, DIST, SS)           # «фото» — силуэт формы при mesh_scale 1,4 (форма дальше и мельче), сдвинутый на (0,03; −0,02)
M0 = W.surface_mask(u90, v90, F, 256)
ph = photo_from_mask(M0, 1.0, TX, TY)
fit = W.fit_photo(V, F, ph, FOV, DIST)
ok('подгонка находит поворот 90° (буква Г несимметрична), IoU ≥ 0,93', fit['yaw_deg'] == 90 and fit['iou'] >= 0.93, str(fit))
ok('подгонка находит mesh_scale ≈ 1,4 (±4 %) и сдвиг tx ≈ 0,03, ty ≈ −0,02 (±0,02 кадра: сдвиг по вертикали и масштаб частично взаимозаменимы); масштаб фото не трогает (σ = 1)', abs(fit['mesh_scale'] - SS) / SS < 0.04 and abs(fit['tx'] - TX) < 0.02 and abs(fit['ty'] - TY) < 0.02 and fit['sigma'] == 1.0, str(fit))
ok('без подгонки (mesh_scale 1, сдвиг 0 — как в апстриме) силуэт хуже: IoU «до» < IoU «после»', fit['iou_identity'] < fit['iou'] - 0.05, str(fit))
ok('IoU по всем 4 поворотам записан, у выбранного — наибольший', len(fit['iou_by_yaw']) == 4 and fit['iou_by_yaw']['90'] == max(fit['iou_by_yaw'].values()))
Vb, Fb = box((-0.3, -0.2, -0.1), (0.3, 0.2, 0.1))
pb, _c, _s, _R = W.to_cube(Vb, 0)
fb = W.fit_photo(Vb, Fb, photo_from_mask(W.surface_mask(*W.project_cube(pb, FOV, DIST, 1.25)[:2], Fb, 256), 1.0, 0.0, 0.0), FOV, DIST)
ok('симметричный предмет (коробка): ничья между поворотами → наименьший, 0°', fb['yaw_deg'] == 0 and fb['iou'] > 0.95, str(fb))
try:
    W.fit_photo(V, F, Image.new('RGBA', (64, 64), (0, 0, 0, 0)), FOV, DIST)
    ok('фото без предмета — отказ', False)
except ValueError:
    ok('фото без предмета — отказ', True)

# перенос фото тем же преобразованием, что и маски
sq = Image.new('RGBA', (80, 80), (0, 0, 0, 0))
sq.paste(Image.new('RGBA', (40, 40), (255, 255, 255, 255)), (20, 20))
A64 = np.asarray(sq.getchannel('A').resize((64, 64), Image.Resampling.BILINEAR)) > 127
for sg, tx_, ty_ in ((1.0, 0.0, 0.0), (0.8, 0.05, -0.1), (1.3, -0.07, 0.04)):
    wp = np.asarray(W.warp_photo(sq, sg, tx_, ty_, 64))[:, :, 0] > 127
    mp = W._warp_mask(A64, sg, tx_, ty_)
    ok(f'фото и маска переносятся одним преобразованием (σ={sg}, t=({tx_}, {ty_})): IoU ≥ 0,93', W._iou(wp, mp) >= 0.93, f'{W._iou(wp, mp):.3f}')
wp_out = W.warp_photo(sq, 1.0, 5.0, 0.0, 32)
ok('сдвиг за кадр — чёрный, не ошибка', np.asarray(wp_out).max() == 0 and wp_out.size == (32, 32))

print('[1b] форма не изменилась')
v0 = V.astype(np.float32).astype(np.float64)
r_same = W.check_shape_unchanged(v0, F, v0.copy(), F.copy())
ok('те же вершины и грани: поточечно, Хаусдорф 0', r_same['mode'] == 'pointwise' and r_same['hausdorff_rel'] == 0 and r_same['tris_in'] == r_same['tris_out'] == len(F))
diag = float(np.linalg.norm(v0.max(0) - v0.min(0)))
for name, dv in (('вершина сдвинута на 1 % диагонали', 0.01), ('на 0,1 %', 0.001), ('на 0,02 %', 0.0002)):
    v1 = v0.copy()
    v1[3, 0] += dv * diag
    try:
        W.check_shape_unchanged(v0, F, v1, F.copy())
        ok(name + ' — отказ', False)
    except W.ShapeChanged:
        ok(name + ' — отказ (допуск 1e-4)', True)
v1 = v0.copy()
v1[3, 0] += 0.5e-4 * diag
ok('сдвиг в 0,005 % диагонали (ниже допуска) — проходит', W.check_shape_unchanged(v0, F, v1, F.copy())['hausdorff_rel'] <= W.SHAPE_TOL)
try:
    W.check_shape_unchanged(v0, F, v0, F[:-1])
    ok('потеряна грань — отказ', False)
except W.ShapeChanged as e:
    ok('потеряна грань — отказ с числами', 'число треугольников' in str(e) and str(len(F)) in str(e))
# развёртка расщепила вершины: другой порядок и число вершин, то же облако и те же треугольники
vs = np.concatenate([v0, v0[:5]])
fs = F.copy()
fs[0, 0] = len(v0)
r_split = W.check_shape_unchanged(v0, F, vs, fs)
ok('расщеплённые вершины (то же облако): по ближайшим вершинам, Хаусдорф 0, число треугольников то же', r_split['mode'] == 'nearest_vertex' and r_split['hausdorff_rel'] == 0 and r_split['verts_out'] == len(v0) + 5)
vs2 = vs.copy()
vs2[:, 1] += 0.02 * diag
try:
    W.check_shape_unchanged(v0, F, vs2, fs)
    ok('расщеплённые, но смещённые вершины — отказ', False)
except W.ShapeChanged:
    ok('расщеплённые, но смещённые вершины — отказ', True)
ok('Хаусдорф без scipy и с ним — одно число (проверка запасного пути)', abs(W.hausdorff_vertices(v0, v0 + np.array([0.0, 0.01, 0.0]), 50) - 0.01) < 1e-9)

print('[2] путь вызова на заглушке пайплайна (trimesh)')
try:
    import trimesh
    have_tm = True
except ImportError:
    have_tm = False
    print('  · SKIP: нет trimesh в этом окружении (проверяется на pakardev)')
if have_tm:
    class Slat:
        def __init__(self, n):
            self.coords = np.zeros((n, 4), dtype=np.int64)

    class FakePipe:
        """Те же методы, что у настоящего (`TexOnly`): записывает, что получил, и возвращает то, что вернул бы апстрим (меш с обменом осей, как `postprocess_mesh`)."""
        def __init__(self, perturb=None, drop_face=False):
            self.calls, self.perturb, self.drop_face = [], perturb, drop_face
            self.image_cond_model_tex_1024 = object()
            self.models = {'tex_slat_flow_model_1024': object()}

        def encode_shape_slat(self, mesh, resolution):
            self.enc_mesh = mesh
            self.calls.append(('encode', float(np.abs(mesh.vertices).max()), resolution, len(mesh.faces), getattr(mesh.visual, 'uv', None) is not None))
            return Slat(7)

        def get_proj_cond_shape(self, model, images, coords, camera_angle_x, distance, mesh_scale, grid_resolution_override):
            self.calls.append(('cond', images[0].size, images[0].mode, coords.shape, round(camera_angle_x, 4), round(distance, 4), mesh_scale, grid_resolution_override))
            return {'cond': 1, 'neg_cond': 2}

        def sample_tex_slat(self, cond, flow, shape_slat, params):
            self.calls.append(('sample', params.get('steps')))
            return 'tex'

        def decode_tex_slat_plain(self, slat):
            self.calls.append(('decode', slat))
            return 'pbr'

        def postprocess_mesh(self, mesh, pbr, resolution, texture_size):
            self.calls.append(('post', pbr, resolution, texture_size))
            v = np.asarray(mesh.vertices).copy()
            if self.perturb:
                v[self.perturb[0], self.perturb[1]] += self.perturb[2]
            out_v = np.stack([v[:, 0], v[:, 2], -v[:, 1]], axis=1)          # как апстрим: (x, y, z) → (x, z, −y)
            faces = np.asarray(mesh.faces)[:-1] if self.drop_face else np.asarray(mesh.faces)
            tex = Image.fromarray(np.full((8, 8, 4), 200, dtype=np.uint8))
            mat = trimesh.visual.material.PBRMaterial(baseColorTexture=tex)
            return trimesh.Trimesh(vertices=out_v, faces=faces, visual=trimesh.visual.TextureVisuals(uv=np.asarray(mesh.visual.uv), material=mat), process=False)

    # вход: форма не в единичном масштабе и не в нуле (как настоящий GLB: метры), с развёрткой
    shift = np.array([0.4, 0.15, -0.2])
    Vi = V * 0.8 + shift
    uvs = np.stack([(Vi[:, 0] - Vi[:, 0].min()) / 0.5, (Vi[:, 1] - Vi[:, 1].min()) / 0.5], axis=1)
    mesh_in = trimesh.Trimesh(vertices=Vi, faces=F, visual=trimesh.visual.TextureVisuals(uv=uvs), process=False)
    pc, _c, _s, _R = W.to_cube(Vi, 0)
    uf, vf, _ = W.project_cube(pc, FOV, DIST, 1.25)          # «фото» мельче куба (предмет занимает ~0,8 кадра, ничего не обрезано), как настоящее фото с полями
    n = 400
    Mp = W.surface_mask(uf, vf, F, n)
    photo = Image.fromarray(np.stack([np.where(Mp, 200, 0), np.where(Mp, 90, 0), np.where(Mp, 40, 0), Mp * 255], axis=-1).astype(np.uint8), 'RGBA')
    cam = {'camera_angle_x': FOV, 'distance': DIST, 'mesh_scale': 1.0}

    for align in ('fit', 'official'):
        fp = FakePipe()
        final, m = W.texture_on_shape(fp, mesh_in, photo, cam, {'align': align, 'seed': 7, 'texture_size': 512, 'sampler': {'steps': 12}})
        names = [c[0] for c in fp.calls]
        ok(f'[{align}] порядок: кодирование формы → условие по фото → поток краски → декодер → запекание', names == ['encode', 'cond', 'sample', 'decode', 'post'], str(names))
        enc = fp.calls[0]
        cond = fp.calls[1]
        ok(f'[{align}] кодировщик получил куб (|v| ≤ 0,5), разрешение 1024, развёртку; число граней то же', enc[1] <= 0.5 + 1e-9 and enc[2] == 1024 and enc[3] == len(F) and enc[4] is True, str(enc))
        want_canvas = (1024, 1024) if align == 'fit' else tuple(W.crop_square_rgba(photo).size)
        want_ms = m['fit']['mesh_scale'] if align == 'fit' else 1.0
        ok(f'[{align}] в камеру краски ушёл mesh_scale {want_ms}' + (' (подогнанный к фото)' if align == 'fit' else ' (как у MoGe, без подгонки)') + ', в метриках cond_mesh_scale тот же', abs(cond[6] - want_ms) < 1e-9 and abs(m['cond_mesh_scale'] - want_ms) < 1e-4, str(cond))
        ok(f'[{align}] условие: холст {want_canvas[0]}×{want_canvas[1]} RGB ({"подогнанный" if align == "fit" else "вырезка как в апстриме"}), камера как задана, сетка 64 (= 1024/16)',
           cond[1] == want_canvas and cond[2] == 'RGB' and cond[4] == round(FOV, 4) and cond[5] == round(DIST, 4) and cond[7] == 64, str(cond))
        ok(f'[{align}] форма на выходе = форма на входе (вершины в исходном кадре и метрах, развёртка та же)',
           m['shape']['mode'] == 'pointwise' and m['shape']['hausdorff_rel'] < 1e-6 and np.allclose(np.asarray(final.vertices), Vi, atol=1e-6) and len(final.faces) == len(F)
           and np.allclose(np.asarray(final.visual.uv), uvs), str(m['shape']))
        ok(f'[{align}] в метриках: подгонка, число граней, этапы, align', m['align'] == align and m['mesh_tris'] == len(F) and 'fit' in m['stage_s'] and 'check_shape' in m['stage_s'] and m['fit']['iou'] > 0.85 and m['fit']['iou_by_yaw']['0'] == m['fit']['iou'] and abs(m['fit']['mesh_scale'] - 1.25) < 0.05, str(m['fit']))
        if align == 'fit':
            ok('[fit] фигура несимметрична, фото снято с 0° — выбран поворот 0°, подгонка лучше «как в апстриме»', m['fit']['yaw_deg'] == 0 and m['fit']['iou'] >= m['fit']['iou_identity'], str(m['fit']))
        out_glb = os.path.join(tempfile.mkdtemp(prefix='ptx-'), 'o.glb')
        final.export(out_glb)
        back = trimesh.load(out_glb, force='mesh')
        ok(f'[{align}] GLB пишется и читается: те же грани, габарит как у входа', len(back.faces) == len(F) and np.allclose(back.extents, mesh_in.extents, atol=1e-5))

    # рычаги «двойного узора»: сглаживание копии формы для латента и сила направляющей
    fp = FakePipe()
    final, m = W.texture_on_shape(fp, mesh_in, photo, cam, {'align': 'fit', 'shape_smooth': 8})
    try:
        import scipy  # noqa: F401
        have_sp = True
    except ImportError:
        have_sp = False
    if have_sp:
        ok('shape_smooth=8: латент формы считается по сглаженной копии (вершины сдвинуты, без развёртки), а форма на выходе та же',
           m['smooth']['iterations'] == 8 and m['smooth']['max_disp_rel'] > 0 and getattr(fp.enc_mesh.visual, 'uv', None) is None
           and np.allclose(np.asarray(final.vertices), Vi, atol=1e-6) and m['shape']['hausdorff_rel'] < 1e-6, str(m['smooth']))
    else:
        print('  · SKIP: нет scipy — сглаживание Тобина не проверено здесь (проверяется на pakardev)')
    fp0 = FakePipe()
    W.texture_on_shape(fp0, mesh_in, photo, cam, {'align': 'fit'})
    ok('без shape_smooth в кодировщик идёт сама форма (с развёрткой)', getattr(fp0.enc_mesh.visual, 'uv', None) is not None)

    # повёрнутая форма: фото снято «сбоку» (форма повёрнута на 90°) — выбираем поворот, но возвращаем в исходный кадр
    rot_mesh = trimesh.Trimesh(vertices=(Vi - Vi.mean(0)) @ W.rot_y(-90).T, faces=F, visual=trimesh.visual.TextureVisuals(uv=uvs), process=False)
    fp = FakePipe()
    final, m = W.texture_on_shape(fp, rot_mesh, photo, cam, {'align': 'fit'})
    ok('форма в другом повороте: подгонка выбирает 90°, а результат возвращается в кадре входа', m['fit']['yaw_deg'] == 90 and np.allclose(np.asarray(final.vertices), np.asarray(rot_mesh.vertices), atol=1e-6), str(m['fit']))

    for name, kw, text in (('сдвинута вершина на 1 см (≈ 2 % габарита)', {'perturb': (5, 0, 0.01)}, 'форма сдвинулась'), ('потеряна грань', {'drop_face': True}, 'число треугольников')):
        try:
            W.texture_on_shape(FakePipe(**kw), mesh_in, photo, cam, {'align': 'fit'})
            ok(name + ' — ошибка, файл не отдаётся', False)
        except W.ShapeChanged as e:
            ok(name + ' — ошибка ShapeChanged с причиной', text in str(e), str(e))
    try:
        W.texture_on_shape(FakePipe(), mesh_in, photo, cam, {'align': 'whatever'})
        ok('неизвестный align — отказ до всякой работы', False)
    except ValueError:
        ok('неизвестный align — отказ до всякой работы', True)

    os.environ['MODEL'] = 'pixal3d-tex'
    ok('MODEL=pixal3d-tex → бэкенд PixalTexBackend (без загрузки)', type(W.backend()).__name__ == 'PixalTexBackend' and W.backend().name == 'pixal3d-tex')
    os.environ['MODEL'] = 'pixal3d'
    ok('MODEL=pixal3d — прежний бэкенд, не затронут', type(W.backend()).__name__ == 'Pixal3DBackend')
    os.environ.pop('MODEL', None)
    try:
        W.PixalTexBackend().generate(Image.new('RGBA', (8, 8)), {'job_id': 'x'}, '/nonexistent/x.glb')
        ok('без формы (--texture-mesh) бэкенд отказывает сразу', False)
    except ValueError as e:
        ok('без формы (--texture-mesh) бэкенд отказывает сразу, до torch и видеокарты', 'texture-mesh' in str(e))

print('[3] драйвер')
import trellis_trial as T  # noqa: E402
b = T.build_body('trial-pixal3d-tex-x', 'ghcr.io/x/y:t', 'high', 'pixal3d-tex', 'hf_SECRET', 8, 32768, 'note', {'basic': {'username': 'u', 'password': 'PW'}})
e = b['container']['environment_variables']
ok('тело группы: MODEL=pixal3d-tex, код воркера едет в command (как у pixal3d, без pip-пина TRELLIS.2), приёмника нет',
   e['MODEL'] == 'pixal3d-tex' and b['container']['command'][:3] == ['python3', '-u', '-c'] and not any(k.startswith('MESH_SINK') for k in e)
   and __import__('zlib').decompress(__import__('base64').b64decode(e['TRIAL_WORKER_Z'])) == open(os.path.join(HERE, 'worker_trellis.py'), 'rb').read())
ok('закрытые веса DINOv3 проверяются бесплатно до создания группы (как у pixal3d)', 'pixal3d-tex' in T.HF_GATED and T.HF_GATED['pixal3d-tex'] == T.HF_GATED['pixal3d'])
ok('только 4090, образ тот же', b['container']['resources']['gpu_classes'] == [T.CARD['class_id']] and b['container']['image'] == 'ghcr.io/x/y:t')

tp = tempfile.mkdtemp(prefix='ptxd-')
json.dump({'a:1': {'input_png_sha256': 'x'}, 'b:2': {'input_png_sha256': 'y'}}, open(os.path.join(tp, 'inputs.json'), 'w'))


class NoTouchMG:
    def env_from_file(self):
        raise AssertionError('Salad тронут до проверки аргументов')

    def __getattr__(self, k):
        raise AssertionError('Salad тронут до проверки аргументов: ' + k)


base = dict(model='pixal3d-tex', inputs=tp, skus=['a:1'], plan='1024:1', seed=42, texture_mesh=None, tex_align='fit', set=None, suffix='t', tier='high')
for name, kw in (('без --texture-mesh', {}), ('два товара', {'texture_mesh': '/x.glb', 'skus': ['a:1', 'b:2']}), ('неизвестный --tex-align', {'texture_mesh': '/x.glb', 'tex_align': 'fit,zzz'})):
    rc = T.run(types.SimpleNamespace(**{**base, **kw}), NoTouchMG(), NoTouchMG())
    ok(f'{name}: отказ (код 2) до обращения к Salad — группа не создаётся, денег 0', rc == 2)
js = [{'job_id': 'a_1-1024-42-0'}]
vs = [T.parse_tex_variant(x) for x in ('fit', 'official', 'fit+g3', 'fit+g2.5+s40')]
two = T.expand_align_jobs(js, vs)
one = T.expand_align_jobs(js, vs[1:2])
ok('варианты: суффиксы id, align, сила направляющей и сглаживание проставлены',
   [j['job_id'] for j in two] == ['a_1-1024-42-0-fit', 'a_1-1024-42-0-official', 'a_1-1024-42-0-fit-g3', 'a_1-1024-42-0-fit-g2.5-s40']
   and [(j['align'], j['tex_guidance'], j['shape_smooth']) for j in two] == [('fit', 1.0, 0), ('official', 1.0, 0), ('fit', 3.0, 0), ('fit', 2.5, 40)])
ok('один вариант: id как был', [j['job_id'] for j in one] == ['a_1-1024-42-0'] and one[0]['align'] == 'official')
ok('неверные записи вариантов отвергаются', all(T.parse_tex_variant(x) is None for x in ('zzz', 'fit+x3', 'fit+g0', 'fit+g11', 'fit+s0', 'fit+sabc', 'fit+s501', '')))
rc = T.run(types.SimpleNamespace(**{**base, 'texture_mesh': '/x.glb', 'tex_align': 'fit+g99'}), NoTouchMG(), NoTouchMG())
ok('--tex-align fit+g99: отказ (код 2) до обращения к Salad', rc == 2)

print('ИТОГО: ' + ('всё в норме' if not bad else f'провалов {bad}'))
sys.exit(1 if bad else 0)
