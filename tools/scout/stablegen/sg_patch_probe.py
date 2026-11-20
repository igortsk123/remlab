"""Разбор «куда делся рисунок ткани» по шагам (T-20261119-90/7, владелец TG 2305/2306): один и тот же участок дивана в состояниях
  ③ запечённая текстура (UV-атлас, выборка в те же пиксели вида), ④ кадр без света (emission), ⑤ кадр со светом стенда (как `render_stand.py`) — из ТОЙ ЖЕ камеры, что вид 0 генерации.
Запуск (Blender, без GPU): blender -b -P sg_patch_probe.py -- --glb painted.glb --plan view_plan.json --out <папка> --patches '{"seat":[290,390],"arm":[620,650]}' [--width-cm 240] [--patch-cm 20]
Пишет в --out: unlit.png, lit.png, tex_<имя>.png (текстура, выбранная лучами через UV, весь кадр, вне участков серый), probe.json (px на единицу/на 10 см, коробки участков, плотность текселей, параметры материала).
Размер предмета в кадре — в «единицах модели» (ширина = 1,0); сантиметры — через --width-cm (реальная ширина дивана НЕ известна из каталога → допущение, указывать в отчёте)."""
import argparse
import json
import math
import os
import sys
import time

import bpy
import numpy as np
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
ap = argparse.ArgumentParser()
ap.add_argument('--glb', required=True)
ap.add_argument('--plan', required=True)
ap.add_argument('--out', required=True)
ap.add_argument('--patches', required=True, help='JSON {имя: [x_центра, y_центра]} в пикселях вида')
ap.add_argument('--view', type=int, default=0)
ap.add_argument('--width-cm', type=float, default=240.0)
ap.add_argument('--patch-cm', type=float, default=20.0)
ap.add_argument('--samples', type=int, default=64)
ap.add_argument('--threads', type=int, default=4)
a = ap.parse_args(argv)
os.makedirs(a.out, exist_ok=True)
T0 = time.time()
plan = json.load(open(a.plan, encoding='utf-8'))['views'][a.view]
W, H = plan['resolution']
LENS, SENSOR = plan['camera']['lens'], plan['camera']['sensor_width']
M = Matrix(plan['matrix_world'])
PATCHES = json.loads(a.patches)

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=a.glb)
meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
sc = bpy.context.scene
dg = bpy.context.evaluated_depsgraph_get()

# --- геометрия в мировых координатах + UV по треугольникам
verts, tris, tri_uv = [], [], []
img = None
mat_info = {}
for o in meshes:
    me = o.evaluated_get(dg).to_mesh()
    me.calc_loop_triangles()
    uvl = me.uv_layers.active
    base = len(verts)
    mw = o.matrix_world
    verts += [tuple(mw @ v.co) for v in me.vertices]
    for t in me.loop_triangles:
        tris.append(tuple(base + i for i in t.vertices))
        tri_uv.append([tuple(uvl.data[li].uv) for li in t.loops] if uvl else [(0, 0)] * 3)
    for m_ in o.data.materials:
        if m_ and m_.use_nodes:
            bsdf = next((x for x in m_.node_tree.nodes if x.type == 'BSDF_PRINCIPLED'), None)
            if bsdf:
                mat_info = {'roughness': round(bsdf.inputs['Roughness'].default_value, 3), 'metallic': round(bsdf.inputs['Metallic'].default_value, 3),
                            'specular_ior_level': round(bsdf.inputs['Specular IOR Level'].default_value, 3)}
                bc = bsdf.inputs['Base Color']
                if bc.links and bc.links[0].from_node.type == 'TEX_IMAGE':
                    img = bc.links[0].from_node.image
                rg = bsdf.inputs['Roughness']
                mat_info['roughness_linked'] = bool(rg.links)
V = np.array(verts)
lo, hi = V.min(axis=0), V.max(axis=0)
centre = Vector((lo + hi) / 2)
bvh = BVHTree.FromPolygons(verts, tris)
tri_uv = np.array(tri_uv, dtype=float)
print('меш: вершин', len(verts), 'треугольников', len(tris), 'габарит', np.round(hi - lo, 3), 'текстура', img.size[:] if img else None, flush=True)
IW, IH = (img.size[0], img.size[1]) if img else (1, 1)
tex = np.array(img.pixels[:], dtype=np.float32).reshape(IH, IW, 4)[:, :, :3] if img else None     # sRGB-значения как в файле, строки снизу вверх


def sample(u, v):
    x, y = (u % 1.0) * IW - 0.5, (v % 1.0) * IH - 0.5
    x0, y0 = int(math.floor(x)) % IW, int(math.floor(y)) % IH
    x1, y1 = (x0 + 1) % IW, (y0 + 1) % IH
    fx, fy = x - math.floor(x), y - math.floor(y)
    return (tex[y0, x0] * (1 - fx) * (1 - fy) + tex[y0, x1] * fx * (1 - fy) + tex[y1, x0] * (1 - fx) * fy + tex[y1, x1] * fx * fy)


def ray(px, py):
    nx, ny = (px + 0.5) / W - 0.5, 0.5 - (py + 0.5) / H
    d = Vector((nx * SENSOR / LENS, ny * SENSOR / LENS, -1.0))
    return M.translation.copy(), (M.to_3x3() @ d).normalized()


unit_cm = a.width_cm / float(hi[0] - lo[0])                    # сантиметров реального дивана в одной «единице модели»
info = {'width_cm_assumed': a.width_cm, 'unit_cm': unit_cm, 'tex_size': [IW, IH], 'material': mat_info, 'view': {'W': W, 'H': H, 'lens': LENS}, 'patches': {}}
tex_frames = {}
for name, (cx, cy) in PATCHES.items():
    o_, d_ = ray(cx, cy)
    hit = bvh.ray_cast(o_, d_)
    if hit[0] is None:
        info['patches'][name] = {'error': 'центр участка не попал в предмет'}
        continue
    dist = hit[3]
    px_per_unit = (LENS / SENSOR * W) / dist                    # пикселей вида на 1 единицу модели у центра участка
    box_px = int(round(a.patch_cm / unit_cm * px_per_unit))
    x0, y0 = int(cx - box_px // 2), int(cy - box_px // 2)
    frame = np.full((H, W, 3), 0.5, dtype=np.float32)
    dens, hits_n, u_all, v_all = [], 0, [], []
    for py in range(max(0, y0), min(H, y0 + box_px)):
        for px in range(max(0, x0), min(W, x0 + box_px)):
            o2, d2 = ray(px, py)
            h2 = bvh.ray_cast(o2, d2)
            if h2[0] is None:
                continue
            ti = h2[2]
            a_, b_, c_ = [Vector(verts[i]) for i in tris[ti]]
            p = h2[0]
            v0, v1, v2 = b_ - a_, c_ - a_, p - a_
            d00, d01, d11, d20, d21 = v0.dot(v0), v0.dot(v1), v1.dot(v1), v2.dot(v0), v2.dot(v1)
            den = d00 * d11 - d01 * d01 or 1e-12
            bv = (d11 * d20 - d01 * d21) / den
            bw = (d00 * d21 - d01 * d20) / den
            bu = 1 - bv - bw
            uv = tri_uv[ti]
            u = bu * uv[0][0] + bv * uv[1][0] + bw * uv[2][0]
            v = bu * uv[0][1] + bv * uv[1][1] + bw * uv[2][1]
            if tex is not None:
                frame[py, px] = sample(u, v)
            hits_n += 1
            u_all.append(u)
            v_all.append(v)
            if len(dens) < 400:                                    # плотность текселей — по первым 400 пикселям участка (достаточно, дёшево)
                area3 = 0.5 * v0.cross(v1).length
                area_uv = 0.5 * abs((uv[1][0] - uv[0][0]) * (uv[2][1] - uv[0][1]) - (uv[2][0] - uv[0][0]) * (uv[1][1] - uv[0][1]))
                if area3 > 1e-12 and area_uv > 0:
                    dens.append(math.sqrt(area_uv * IW * IH / area3))     # текселей на единицу модели
    tex_frames[name] = frame
    td = float(np.median(dens)) if dens else 0.0
    info['patches'][name] = {
        'center_px': [cx, cy], 'box_px': [x0, y0, box_px, box_px], 'dist': round(dist, 3), 'px_per_unit': round(px_per_unit, 1),
        'px_per_10cm': round(px_per_unit / unit_cm * 10, 1), 'texels_per_unit': round(td, 1), 'texels_per_10cm': round(td / unit_cm * 10, 1),
        'hit_share': round(hits_n / max(box_px * box_px, 1), 3), 'uv_bbox': [round(min(u_all), 4), round(min(v_all), 4), round(max(u_all), 4), round(max(v_all), 4)] if u_all else None}
    print('участок', name, info['patches'][name], flush=True)
json.dump(info, open(os.path.join(a.out, 'probe.json'), 'w'), ensure_ascii=False, indent=1)

for name, fr in tex_frames.items():                          # в Blender нет PIL: пишем PNG через bpy (строки снизу вверх; значения — sRGB как есть, без преобразования)
    im_ = bpy.data.images.new(f'tex_{name}', W, H, alpha=False, float_buffer=False)
    im_.colorspace_settings.name = 'Non-Color'
    rgba = np.concatenate([np.clip(fr, 0, 1)[::-1], np.ones((H, W, 1), dtype=np.float32)], axis=2)
    im_.pixels.foreach_set(rgba.ravel())
    im_.filepath_raw = os.path.join(a.out, f'tex_{name}.png')
    im_.file_format = 'PNG'
    im_.save()

# --- рендер из камеры вида 0: ④ без света и ⑤ со светом стенда (как render_stand.py)
floor_z = float(lo[2])
bpy.ops.mesh.primitive_plane_add(size=40, location=(0, 0, floor_z))
floor = bpy.context.active_object
fm = bpy.data.materials.new('floor')
fm.use_nodes = True
fm.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value = (0.62, 0.62, 0.60, 1)
fm.node_tree.nodes['Principled BSDF'].inputs['Roughness'].default_value = 0.9
floor.data.materials.append(fm)
w = bpy.data.worlds.new('w')
w.use_nodes = True
w.node_tree.nodes['Background'].inputs['Color'].default_value = (0.82, 0.83, 0.85, 1)
w.node_tree.nodes['Background'].inputs['Strength'].default_value = 0.45
sc.world = w
cam_d = bpy.data.cameras.new('cam')
cam_d.lens, cam_d.sensor_width = LENS, SENSOR
cam = bpy.data.objects.new('cam', cam_d)
sc.collection.objects.link(cam)
cam.matrix_world = M
sc.camera = cam
sun_d = bpy.data.lights.new('sun', 'SUN')
sun_d.energy, sun_d.angle = 1.8, math.radians(6)
sun = bpy.data.objects.new('sun', sun_d)
sc.collection.objects.link(sun)
rel = M.translation - centre
az = math.degrees(math.atan2(rel.x, -rel.y))
el = math.degrees(math.asin(rel.z / rel.length))


def polar(az_deg, el_deg, r):
    azr, elr = math.radians(az_deg), math.radians(el_deg)
    return centre + Vector((r * math.cos(elr) * math.sin(azr), -r * math.cos(elr) * math.cos(azr), r * math.sin(elr)))


sun.location = polar(az - 40, el + 35, 5)                    # как в render_stand: свет на 40° левее и на 35° выше камеры
sun.rotation_euler = (centre - sun.location).to_track_quat('-Z', 'Y').to_euler()
sc.render.engine = 'CYCLES'
sc.cycles.device, sc.cycles.samples, sc.cycles.use_denoising, sc.cycles.denoiser = 'CPU', a.samples, True, 'OPENIMAGEDENOISE'
sc.render.threads_mode, sc.render.threads = 'FIXED', a.threads
sc.render.resolution_x, sc.render.resolution_y, sc.render.resolution_percentage = W, H, 100
sc.view_settings.view_transform, sc.view_settings.look = 'Standard', 'None'
sc.render.image_settings.file_format = 'PNG'
sc.render.film_transparent = False
sc.render.filepath = os.path.join(a.out, 'lit.png')
bpy.ops.render.render(write_still=True)
print(f'lit готов {time.time() - T0:.0f} с, камера az={az:.1f} el={el:.1f}', flush=True)
for m_ in bpy.data.materials:
    if m_.name == 'floor' or not m_.use_nodes:
        continue
    bsdf = next((x for x in m_.node_tree.nodes if x.type == 'BSDF_PRINCIPLED'), None)
    if bsdf is None:
        continue
    bc = bsdf.inputs['Base Color']
    if bc.links:
        m_.node_tree.links.new(bc.links[0].from_socket, bsdf.inputs['Emission Color'])
    else:
        bsdf.inputs['Emission Color'].default_value = bc.default_value
    bsdf.inputs['Emission Strength'].default_value = 1.0
    bc.default_value = (0, 0, 0, 1)
    for l_ in list(bc.links):
        m_.node_tree.links.remove(l_)
    bsdf.inputs['Specular IOR Level'].default_value = 0.0
sc.cycles.use_denoising = False                              # без света шумить нечему; рисунок не размазываем
sc.render.filepath = os.path.join(a.out, 'unlit.png')
bpy.ops.render.render(write_still=True)
print(f'ГОТОВО за {time.time() - T0:.0f} с', flush=True)
