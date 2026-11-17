"""ПРОБА T-20261117-02: сборка сцены в Blender и рендер Cycles на ПРОЦЕССОРЕ (0 ₽). Запуск — внутри Blender:

  ~/opt/blender-4.5.9/blender -b -P render_cycles.py -- --scene-dir <папка выгрузки сцены> --cam C1 --out <png> [--samples 160] [--pct 100]

Вход — выгрузка `export_scene.py` (те же меши/текстуры/камеры, что у серверного кадра T-61). Комната: пол/стены/потолок — плиты
(свет не протекает в углах), проёмы — по `cuts`; небо Nishita + солнце сквозь окно + мягкий заполняющий свет.
"""
import argparse
import json
import math
import os
import sys
import time

import bpy
import numpy as np
from mathutils import Vector

argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
ap = argparse.ArgumentParser()
ap.add_argument('--scene-dir', required=True)
ap.add_argument('--cam', default='C1')
ap.add_argument('--out', required=True)
ap.add_argument('--samples', type=int, default=160)
ap.add_argument('--pct', type=int, default=100)
ap.add_argument('--threads', type=int, default=8)
ap.add_argument('--sun', type=float, default=4.0)
ap.add_argument('--sky', type=float, default=1.0)
ap.add_argument('--fill', type=float, default=60.0)
ap.add_argument('--view', type=float, default=1.2)
ap.add_argument('--exposure', type=float, default=0.0)
ap.add_argument('--lite-tex', type=int, default=0, help='>0: уменьшить текстуры до этой стороны (замер облегчённой версии)')
a = ap.parse_args(argv)

M = json.load(open(os.path.join(a.scene_dir, 'scene.json'), encoding='utf-8'))
W, D, H = M['W'], M['D'], M['H']
CORNER, THICK = 10.0, 12.0


def b(x, y, z):
    """сцена (см) → Blender (м)."""
    return (x / 100.0, -z / 100.0, y / 100.0)


def hexrgb(h):
    return tuple(int(h[i:i + 2], 16) / 255.0 for i in (1, 3, 5))


def srgb2lin(c):
    return tuple(((x + 0.055) / 1.055) ** 2.4 if x > 0.04045 else x / 12.92 for x in c)


bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
sc.render.engine = 'CYCLES'
cy = sc.cycles
cy.device = 'CPU'
cy.samples = a.samples
cy.use_adaptive_sampling = True
cy.adaptive_threshold = 0.01
cy.use_denoising = True
cy.denoiser = 'OPENIMAGEDENOISE'
cy.max_bounces = 8
cy.diffuse_bounces = 5
cy.glossy_bounces = 4
cy.transmission_bounces = 4
cy.sample_clamp_indirect = 10.0
cy.caustics_reflective = False
cy.caustics_refractive = False
sc.render.threads_mode = 'FIXED'
sc.render.threads = a.threads
sc.view_settings.view_transform = 'AgX'
sc.view_settings.look = 'AgX - Medium High Contrast'
sc.view_settings.exposure = a.exposure
sc.render.image_settings.file_format = 'PNG'
sc.render.image_settings.color_depth = '8'


def make_obj(name, verts, faces, uvs=None, mat=None, smooth=True):
    me = bpy.data.meshes.new(name)
    me.from_pydata([tuple(map(float, v)) for v in verts], [], [tuple(map(int, f)) for f in faces])
    me.update()
    if uvs is not None:
        uv = me.uv_layers.new(name='UV')
        loops = np.array([l.vertex_index for l in me.loops], np.int64)
        uv.data.foreach_set('uv', np.asarray(uvs, np.float32)[loops].ravel())
    if mat is not None:
        me.materials.append(mat)
    ob = bpy.data.objects.new(name, me)
    sc.collection.objects.link(ob)
    if smooth:
        for p in me.polygons:
            p.use_smooth = True
        try:
            me.shade_smooth_by_angle = None
        except Exception:
            pass
    return ob


def smooth_by_angle(ob, deg=45):
    bpy.context.view_layer.objects.active = ob
    ob.select_set(True)
    try:
        bpy.ops.object.shade_smooth_by_angle(angle=math.radians(deg))
    except Exception:
        bpy.ops.object.shade_smooth()
    ob.select_set(False)


def principled(name, rgb=None, tex=None, rough=0.6, spec=0.5, metallic=0.0, tex_lite=0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    bsdf = nt.nodes['Principled BSDF']
    bsdf.inputs['Roughness'].default_value = rough
    bsdf.inputs['Metallic'].default_value = metallic
    try:
        bsdf.inputs['Specular IOR Level'].default_value = spec
    except KeyError:
        pass
    if tex:
        node = nt.nodes.new('ShaderNodeTexImage')
        img = bpy.data.images.load(os.path.join(a.scene_dir, tex), check_existing=True)
        if tex_lite and max(img.size) > tex_lite:
            img.scale(tex_lite, tex_lite)
        node.image = img
        node.interpolation = 'Cubic'
        nt.links.new(node.outputs['Color'], bsdf.inputs['Base Color'])
    else:
        bsdf.inputs['Base Color'].default_value = (*srgb2lin(rgb), 1.0)
    return m


def camera_only(ob):
    ob.visible_diffuse = ob.visible_glossy = ob.visible_transmission = ob.visible_shadow = ob.visible_volume_scatter = False


ROUGH = {'диван': 0.9, 'кресло': 0.9, 'стул': 0.75, 'кровать': 0.9, 'пуф': 0.9, 'банкетка': 0.9, 'кашпо': 0.8, 'ваза': 0.35, 'торшер': 0.45}

# ---------------- комната (плиты — свет не протекает) ----------------
wall_mat = principled('wall', hexrgb(M['finish']['wall']['colorHex']), rough=0.92, spec=0.2)
ceil_mat = principled('ceiling', hexrgb(M['finish']['ceiling']['colorHex']), rough=0.95, spec=0.1)


def slab(name, x0, x1, y0, y1, z0, z1, mat):
    v = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0), (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
    f = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
    return make_obj(name, v, f, mat=mat, smooth=False)


# пол — плита вниз; дерево: процедурные доски цвета пола паспорта
floor_rgb = hexrgb(M['finish']['floor']['colorHex'])
fm = bpy.data.materials.new('floor')
fm.use_nodes = True
nt = fm.node_tree
bs = nt.nodes['Principled BSDF']
texcoord = nt.nodes.new('ShaderNodeTexCoord')
mapping = nt.nodes.new('ShaderNodeMapping')
nt.links.new(texcoord.outputs['Object'], mapping.inputs['Vector'])
brick = nt.nodes.new('ShaderNodeTexBrick')
brick.offset = 0.5
brick.offset_frequency = 2
brick.squash = 1.0
brick.inputs['Scale'].default_value = 1.0
brick.inputs['Mortar Size'].default_value = 0.004
brick.inputs['Mortar Smooth'].default_value = 0.1
brick.inputs['Bias'].default_value = 0.0
brick.inputs['Brick Width'].default_value = 1.2      # м, вдоль доски
brick.inputs['Row Height'].default_value = 0.14      # м, ширина доски
lin = srgb2lin(floor_rgb)
brick.inputs['Color1'].default_value = (lin[0] * 1.04, lin[1] * 1.03, lin[2] * 1.0, 1)
brick.inputs['Color2'].default_value = (lin[0] * 0.90, lin[1] * 0.88, lin[2] * 0.84, 1)
brick.inputs['Mortar'].default_value = (lin[0] * 0.35, lin[1] * 0.33, lin[2] * 0.30, 1)
nt.links.new(mapping.outputs['Vector'], brick.inputs['Vector'])
noise = nt.nodes.new('ShaderNodeTexNoise')
noise.inputs['Scale'].default_value = 40.0
noise.inputs['Detail'].default_value = 8.0
noise.inputs['Roughness'].default_value = 0.6
nt.links.new(mapping.outputs['Vector'], noise.inputs['Vector'])
mapping.inputs['Scale'].default_value = (1.0, 8.0, 1.0)     # вытянуть «волокно» вдоль досок
mix = nt.nodes.new('ShaderNodeMix')
mix.data_type = 'RGBA'
mix.blend_type = 'MULTIPLY'
mix.inputs['Factor'].default_value = 0.35
nt.links.new(brick.outputs['Color'], mix.inputs['A'])
nt.links.new(noise.outputs['Color'], mix.inputs['B'])
nt.links.new(mix.outputs['Result'], bs.inputs['Base Color'])
bump = nt.nodes.new('ShaderNodeBump')
bump.inputs['Strength'].default_value = 0.08
nt.links.new(noise.outputs['Fac'], bump.inputs['Height'])
nt.links.new(bump.outputs['Normal'], bs.inputs['Normal'])
bs.inputs['Roughness'].default_value = 0.42
try:
    bs.inputs['Specular IOR Level'].default_value = 0.45
except KeyError:
    pass
# доски вдоль длинной стороны
mapping.inputs['Rotation'].default_value = (0, 0, 0 if W >= D else math.pi / 2)
slab('floor', -CORNER / 100, (W + CORNER) / 100, -(D + CORNER) / 100, CORNER / 100, -THICK / 100, 0.0, fm)
slab('ceiling', -CORNER / 100, (W + CORNER) / 100, -(D + CORNER) / 100, CORNER / 100, H / 100, (H + THICK) / 100, ceil_mat)

# стены по правилам сервера (`planner/scene.py`: wall_rects, _wall_quad) + плита наружу
FR = {'south': ((0, 0), (1, 0), (0, 1)), 'north': ((W, D), (-1, 0), (0, -1)),
      'west': ((0, D), (0, -1), (1, 0)), 'east': ((W, 0), (0, 1), (-1, 0))}


def wall_rects(length, height, cuts):
    out, cursor = [], 0.0
    for u0, u1, bottom, top in sorted(cuts):
        u0, u1 = max(0.0, min(length, u0)), max(0.0, min(length, u1))
        if u1 <= u0:
            continue
        if u0 > cursor:
            out.append((cursor, u0, 0.0, height))
        if bottom > 0:
            out.append((u0, u1, 0.0, min(bottom, height)))
        if top < height:
            out.append((u0, u1, top, height))
        cursor = max(cursor, u1)
    if cursor < length:
        out.append((cursor, length, 0.0, height))
    return [r for r in out if r[1] - r[0] > 0.5 and r[3] - r[2] > 0.5]


for wall, ((ox, oz), (dx, dz), (nx, nz)) in FR.items():
    length = W if wall in ('north', 'south') else D
    cl = [(c['u0'], c['u1'], c['bottom'], c['top']) for c in M['cuts'].get(wall, [])]
    for k, (u0, u1, v0, v1) in enumerate(wall_rects(length, H, cl)):
        u0 = u0 - CORNER if u0 <= 0 else u0
        u1 = u1 + CORNER if u1 >= length else u1
        pts = []
        for back in (0.0, THICK):
            bx, bz = ox - nx * back, oz - nz * back
            for (u, v) in ((u0, v0), (u1, v0), (u1, v1), (u0, v1)):
                pts.append(b(bx + dx * u, v, bz + dz * u))
        f = [(0, 1, 2, 3), (4, 7, 6, 5), (0, 4, 5, 1), (1, 5, 6, 2), (2, 6, 7, 3), (3, 7, 4, 0)]
        # ориентация граней не важна для Cycles (двусторонние), нормали — по сглаживанию отключены
        make_obj(f'wall_{wall}_{k}', pts, f, mat=wall_mat, smooth=False)
    # за дверным проёмом — «коридор» (приглушённый светлый), чтобы дыра не читалась небом
    for c in M['cuts'].get(wall, []):
        if c['kind'] in ('window', 'balcony'):
            continue
        back = 90.0
        bx, bz = ox - nx * back, oz - nz * back
        pts = [b(bx + dx * u, v, bz + dz * u) for (u, v) in ((c['u0'] - 60, 0), (c['u1'] + 60, 0), (c['u1'] + 60, c['top'] + 40), (c['u0'] - 60, c['top'] + 40))]
        hall = bpy.data.materials.new('hall')
        hall.use_nodes = True
        hb = hall.node_tree.nodes['Principled BSDF']
        hb.inputs['Base Color'].default_value = (*srgb2lin((0.62, 0.6, 0.57)), 1)
        hb.inputs['Emission Color'].default_value = (*srgb2lin((0.62, 0.6, 0.57)), 1)
        hb.inputs['Emission Strength'].default_value = 0.5
        ho = make_obj('hall', pts, [(0, 1, 2, 3)], mat=hall, smooth=False)
        camera_only(ho)

# вид из окна (как у браузера и серверного кадра): картинка на плоскости за стеной, видна ТОЛЬКО камере — свет и тень не трогает
for k, bdv in enumerate(M.get('backdrops', [])):
    bd = bdv['bd']
    (ox, oz), (dx, dz), (nx, nz) = FR[bdv['wall']]
    bx, bz = ox - nx * bd['back'], oz - nz * bd['back']
    pts = [b(bx + dx * u, v, bz + dz * u) for (u, v) in ((bd['u0'], bd['bottom']), (bd['u1'], bd['bottom']), (bd['u1'], bd['top']), (bd['u0'], bd['top']))]
    uvr = bd['uv']
    uvs = [(uvr['u0'], uvr['v0']), (uvr['u1'], uvr['v0']), (uvr['u1'], uvr['v1']), (uvr['u0'], uvr['v1'])]
    vm = bpy.data.materials.new('view')
    vm.use_nodes = True
    n = vm.node_tree
    bsdf = n.nodes['Principled BSDF']
    ti = n.nodes.new('ShaderNodeTexImage')
    ti.image = bpy.data.images.load(os.path.join(a.scene_dir, bdv['tex']))
    n.links.new(ti.outputs['Color'], bsdf.inputs['Emission Color'])
    bsdf.inputs['Base Color'].default_value = (0, 0, 0, 1)
    bsdf.inputs['Emission Strength'].default_value = a.view
    vo = make_obj('view', pts, [(0, 1, 2, 3)], uvs=uvs, mat=vm, smooth=False)
    camera_only(vo)

# ---------------- предметы (меши с текстурами) ----------------
mat_cache = {}
for o in M['objs']:
    z = np.load(os.path.join(a.scene_dir, o['file']))
    role = o['role'].split(' ')[0]
    if o['tex']:
        key = ('t', o['tex'], role)
        if key not in mat_cache:
            mat_cache[key] = principled('m_' + os.path.basename(o['tex']), tex=o['tex'], rough=ROUGH.get(role, 0.55), tex_lite=a.lite_tex)
        mat = mat_cache[key]
    else:
        rgb = tuple(c / 255.0 for c in o['rgb'])
        key = ('c', rgb, role)
        if key not in mat_cache:
            rough = 0.3 if role == 'тв' else 0.6
            mat_cache[key] = principled('c_' + o['role'], rgb, rough=rough)
        mat = mat_cache[key]
    vv = z['v']
    if o['n_faces'] == 12 and not o['tex']:
        # простые коробки (рама окна, плинтус, карниз) касаются друг друга совпадающими гранями — в Cycles в углах чёрные пятна самотени;
        # растягиваем каждую на доли миллиметра по-разному, чтобы грани не лежали в одной плоскости
        k_ = int(o['file'][1:4])
        vv = vv.mean(axis=0) + (vv - vv.mean(axis=0)) * (1.0 + 0.0006 * (1 + k_ % 4))
    ob = make_obj(o['file'], vv, z['f'], uvs=z['uv'] if 'uv' in z.files else None, mat=mat, smooth=False)
    if o['tex']:
        smooth_by_angle(ob, 50)

# ковёр: фото сверху с вырезом по цвету фона (как `_paste_rug`)
for k, r in enumerate(M['rugs']):
    img = bpy.data.images.load(os.path.join(a.scene_dir, r['tex']))
    Wi, Hi = img.size
    px = np.array(img.pixels[:], np.float32).reshape(Hi, Wi, 4)[::-1]    # сверху вниз
    rgb = px[..., :3]
    corn = np.concatenate([rgb[:6, :6].reshape(-1, 3), rgb[:6, -6:].reshape(-1, 3), rgb[-6:, :6].reshape(-1, 3), rgb[-6:, -6:].reshape(-1, 3)])
    bg = np.median(corn, axis=0)
    dist = np.linalg.norm(rgb - bg, axis=2) * 255.0
    msk = dist > 22
    if msk.mean() < 0.30:
        msk[:] = True
    ys, xs = np.where(msk)
    bx0, bx1, by0, by1 = int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max())
    bw, bh = bx1 - bx0 + 1, by1 - by0 + 1
    mimg = bpy.data.images.new('rugmask', Wi, Hi)
    mm = np.zeros((Hi, Wi, 4), np.float32)
    mm[..., :3] = msk[..., None]
    mm[..., 3] = 1
    mimg.pixels = mm[::-1].ravel()
    hw, hd = r['w'] / 2, r['d'] / 2
    ang = math.radians(r['rot'])
    ca, sa = math.cos(ang), math.sin(ang)
    corners, uvs = [], []
    rot90 = (bw >= bh) != (r['w'] >= r['d'])
    for dx_, dz_, u, v in ((-hw, -hd, 0, 0), (hw, -hd, 1, 0), (hw, hd, 1, 1), (-hw, hd, 0, 1)):
        corners.append(b(r['x'] + dx_ * ca + dz_ * sa, 0.8, r['y'] - dx_ * sa + dz_ * ca))
        ua, va = (v, 1.0 - u) if rot90 else (u, v)
        uvs.append(((bx0 + ua * bw) / Wi, 1.0 - (by0 + va * bh) / Hi))
    rm = bpy.data.materials.new('rug')
    rm.use_nodes = True
    n = rm.node_tree
    bsdf = n.nodes['Principled BSDF']
    t1 = n.nodes.new('ShaderNodeTexImage')
    t1.image = img
    t2 = n.nodes.new('ShaderNodeTexImage')
    t2.image = mimg
    t2.interpolation = 'Closest'
    n.links.new(t1.outputs['Color'], bsdf.inputs['Base Color'])
    n.links.new(t2.outputs['Color'], bsdf.inputs['Alpha'])
    bsdf.inputs['Roughness'].default_value = 0.95
    make_obj(f'rug{k}', corners, [(0, 3, 2, 1)], uvs=uvs, mat=rm, smooth=False)

# ---------------- камера ----------------
cd = next(c for c in M['cams'] if c['name'] == a.cam)
cam = bpy.data.cameras.new('cam')
cam.sensor_fit = 'HORIZONTAL'
cam.lens_unit = 'FOV'
cam.angle = math.radians(cd['fov'])
cam.shift_y = cd['shift_y'] * cd['h'] / cd['w']   # у кадра сервера минус — картинка вверх; у Blender так же (проверено по кадру T-61)
cam.clip_start = 0.06    # как NEAR_CM=5 см серверного кадра: то, что вплотную к объективу, не рисуется
cam.clip_end = 100.0
co = bpy.data.objects.new('cam', cam)
sc.collection.objects.link(co)
right, up, fwd = (Vector(cd[k]).normalized() for k in ('right', 'up', 'fwd'))
rot = np.array([[right.x, up.x, -fwd.x], [right.y, up.y, -fwd.y], [right.z, up.z, -fwd.z]])
from mathutils import Matrix
mat4 = Matrix.Identity(4)
for i in range(3):
    for j in range(3):
        mat4[i][j] = rot[i, j]
mat4.translation = Vector(cd['eye'])
co.matrix_world = mat4
sc.camera = co
sc.render.resolution_x, sc.render.resolution_y = cd['w'], cd['h']
sc.render.resolution_percentage = a.pct
print('det камеры', float(np.linalg.det(rot)))

# ---------------- свет ----------------
world = bpy.data.worlds.new('w')
sc.world = world
world.use_nodes = True
wn = world.node_tree
bgn = wn.nodes['Background']
sky = wn.nodes.new('ShaderNodeTexSky')
sky.sky_type = 'NISHITA'
sky.sun_disc = False
sky.sun_elevation = math.radians(38)
sky.air_density = 1.0
sky.dust_density = 1.2
wn.links.new(sky.outputs['Color'], bgn.inputs['Color'])
bgn.inputs['Strength'].default_value = a.sky

win = next((o['wall'] for o in M['openings'] if o['kind'] in ('window', 'balcony')), 'west')
(_, _), (_, _), (nx, nz) = FR[win]
inward = Vector((nx, -nz, 0.0))               # внутрь комнаты, мир Blender
el = math.radians(38)
tr = Vector((inward.x * math.cos(el), inward.y * math.cos(el), -math.sin(el)))   # куда идёт свет
sun = bpy.data.lights.new('sun', 'SUN')
sun.energy = a.sun
sun.angle = math.radians(1.5)
sun.color = (1.0, 0.95, 0.86)
so = bpy.data.objects.new('sun', sun)
sc.collection.objects.link(so)
so.rotation_euler = tr.to_track_quat('-Z', 'Y').to_euler()

fill = bpy.data.lights.new('fill', 'AREA')
fill.shape = 'RECTANGLE'
fill.size, fill.size_y = 1.6, 1.6
fill.energy = a.fill
fill.color = (1.0, 0.97, 0.92)
fo = bpy.data.objects.new('fill', fill)
sc.collection.objects.link(fo)
fo.location = (W / 200.0, -D / 200.0, (H - 6) / 100.0)
fo.rotation_euler = (0, 0, 0)
fo.visible_camera = False

os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
sc.render.filepath = a.out
t0 = time.time()
bpy.ops.render.render(write_still=True)
print(f'RENDER_SEC {time.time() - t0:.1f} samples {a.samples} pct {a.pct} threads {a.threads}', flush=True)
