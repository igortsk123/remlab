"""Облёт модели в Blender для этапа 3 «части меша» (paint-photo-fill-01, T-20261120-169): кадры + какие грани в каждом кадре видны и где на картинке.

ЗАЧЕМ. SAM2 обводит области на картинке, а красить надо грани. Для каждого кадра пишем: картинку предмета (серый фон), маску предмета и по каждой грани —
пиксель центра, видна ли (луч от камеры до центра грани не упирается в другую), косинус угла к камере. Дальше всё считает `parts_vote.py` без Blender.
Запуск (Blender без окна, на pakardev; тяжёлое — под heavy-slot):
    blender -b -P tools/assets/parts_orbit_blender.py -- <model.glb> <папка> [--rules data/flat3d/parts-sam-rules.json] [--views N] [--size PX]
Выход: <папка>/view_NN.png (RGB), mask_NN.png (предмет), vis_NN.npz (u, v, vis, cos по граням), orbit.json (камеры, число граней).
Порядок граней = порядок треугольников в GLB (как `trimesh.load(process=False)`); число граней сверяется в orbit.json."""
import json
import math
import os
import sys
import time

import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

argv = sys.argv[sys.argv.index('--') + 1:]
glb, out = argv[0], argv[1]
here = os.path.dirname(os.path.abspath(__file__))
rules_path = os.path.join(here, '..', '..', 'data', 'flat3d', 'parts-sam-rules.json')
n_views_cap, size_over = None, None
i = 2
while i < len(argv):
    if argv[i] == '--rules':
        rules_path = argv[i + 1]; i += 2
    elif argv[i] == '--views':
        n_views_cap = int(argv[i + 1]); i += 2
    elif argv[i] == '--size':
        size_over = int(argv[i + 1]); i += 2
    else:
        i += 1
R = json.load(open(rules_path, encoding='utf-8'))['orbit']
size = size_over or R['size_px']
os.makedirs(out, exist_ok=True)

for o in list(bpy.data.objects):
    bpy.data.objects.remove(o, do_unlink=True)
bpy.ops.import_scene.gltf(filepath=glb)
meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
obj = meshes[0]
bpy.ops.object.select_all(action='DESELECT')
obj.select_set(True)
bpy.context.view_layer.objects.active = obj
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)   # локальные = мировые (луч и проекция в одних осях)
me = obj.data
nf = len(me.polygons)
tri = all(len(p.vertices) == 3 for p in me.polygons)
co = np.empty(len(me.vertices) * 3, dtype=np.float64)
me.vertices.foreach_get('co', co)
vco = co.reshape(-1, 3)
fv = np.empty(nf * 3, dtype=np.int64)
if tri:
    me.polygons.foreach_get('vertices', fv)
fv = fv.reshape(-1, 3)
cent = vco[fv].mean(axis=1) if tri else np.zeros((nf, 3))
nrm = np.empty(nf * 3, dtype=np.float64)
me.polygons.foreach_get('normal', nrm)
nrm = nrm.reshape(-1, 3)
lo, hi = vco.min(axis=0), vco.max(axis=0)
ctr = Vector(((lo + hi) / 2).tolist())
radius = float(np.linalg.norm(hi - lo) / 2)

sc = bpy.context.scene
sc.render.engine = 'CYCLES'
sc.cycles.device = 'CPU'
sc.cycles.samples = int(R['samples'])
sc.render.threads_mode = 'FIXED'
sc.render.threads = 4
sc.render.resolution_x = sc.render.resolution_y = size
sc.render.film_transparent = True
sc.render.image_settings.file_format = 'PNG'
sc.render.image_settings.color_mode = 'RGBA'
sc.view_settings.view_transform = 'Standard'
w = bpy.data.worlds.new('w')
w.use_nodes = True
w.node_tree.nodes['Background'].inputs[0].default_value = (1, 1, 1, 1)
w.node_tree.nodes['Background'].inputs[1].default_value = 1.0
sc.world = w
cam = bpy.data.objects.new('cam', bpy.data.cameras.new('cam'))
sc.collection.objects.link(cam)
sc.camera = cam
cam.data.lens = R['lens_mm']
cam.data.sensor_fit = 'AUTO'
sensor = cam.data.sensor_width
f_px = R['lens_mm'] / sensor * size
half_fov = math.atan(sensor / 2 / R['lens_mm'])
dist = radius / (R['fill'] * math.tan(half_fov))

bvh = BVHTree.FromObject(obj, bpy.context.evaluated_depsgraph_get())
views = []
for v in R['views']:
    for az in v['az_deg']:
        views.append((float(az), float(v['el_deg'])))
if n_views_cap:
    views = views[:n_views_cap]

info = {'faces': nf, 'triangles_only': tri, 'size': size, 'f_px': f_px, 'views': []}
if not tri:
    json.dump(info, open(os.path.join(out, 'orbit.json'), 'w'), ensure_ascii=False)
    print('ORBIT FAIL not triangles')
    sys.exit(0)

t0 = time.time()
for k, (az, el) in enumerate(views):
    a, e = math.radians(az), math.radians(el)
    cam.location = ctr + Vector((-math.sin(a) * math.cos(e) * dist, -math.cos(a) * math.cos(e) * dist, math.sin(e) * dist))
    cam.rotation_euler = (ctr - cam.location).to_track_quat('-Z', 'Y').to_euler()
    bpy.context.view_layer.update()
    name = f'{k:02d}'
    sc.render.filepath = os.path.join(out, f'rgba_{name}.png')
    bpy.ops.render.render(write_still=True)
    # проекция центров граней: камера смотрит вдоль −Z своей системы, Y вверх
    mw = np.array(cam.matrix_world.inverted())
    pc = (mw[:3, :3] @ cent.T).T + mw[:3, 3]
    zc = -pc[:, 2]
    u = size / 2 + f_px * pc[:, 0] / np.maximum(zc, 1e-9)
    vv = size / 2 - f_px * pc[:, 1] / np.maximum(zc, 1e-9)
    cpos = np.array(cam.location)
    d = cent - cpos
    dn = np.linalg.norm(d, axis=1)
    dirs = d / np.maximum(dn[:, None], 1e-12)
    cosv = -(dirs * nrm).sum(axis=1)
    cand = np.nonzero((cosv > R['min_cos']) & (zc > 0) & (u >= 0) & (u < size) & (vv >= 0) & (vv < size))[0]
    vis = np.zeros(nf, dtype=bool)
    tol = 1e-4 * radius
    origin = Vector(cpos.tolist())
    for f in cand:
        hit = bvh.ray_cast(origin, Vector(dirs[f].tolist()))
        if hit[2] is None:
            continue
        if hit[2] == f or hit[3] >= dn[f] - tol:
            vis[f] = True
    np.savez_compressed(os.path.join(out, f'vis_{name}.npz'), u=u.astype(np.float32), v=vv.astype(np.float32), vis=vis, cos=np.clip(cosv, 0, 1).astype(np.float32))
    info['views'].append({'name': name, 'az': az, 'el': el, 'visible_faces': int(vis.sum())})
    print(f'VIEW {name} az={az} el={el} видно {int(vis.sum())} из {nf}, {time.time() - t0:.0f} с', flush=True)
json.dump(info, open(os.path.join(out, 'orbit.json'), 'w'), ensure_ascii=False, indent=1)
print('ORBIT OK', nf, len(views))
