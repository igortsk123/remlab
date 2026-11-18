"""Карточки растений (T-20261117-21): каждое растение отдельным кадром Cycles на нейтральном фоне, полный размер, процессор (0 ₽). Запуск — внутри Blender:

  ~/opt/blender-4.5.9/blender -b -P plant_cards.py -- --glb <растение.glb> --out <png> [--size 1400] [--samples 96] [--azim 35] [--elev 12]

Растение (`plant_from_scan.py` / `plant_candidates.py`: Y вверх, низ в нуле, основание на оси) стоит на светло-сером «столе»; камера на уровне середины
высоты растения, кадр подгоняется по габаритам (растение — 80 % высоты кадра). Свет: мягкий белый мир + большой источник сверху-слева и слабый
контровый — как в живой комнате, без цветных бликов. Линейка 10 см рядом — чтобы на кадре читался настоящий размер."""
import argparse
import math
import os
import sys

import bpy
from mathutils import Vector

argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
ap = argparse.ArgumentParser()
ap.add_argument('--glb', required=True)
ap.add_argument('--out', required=True)
ap.add_argument('--size', type=int, default=1400)
ap.add_argument('--samples', type=int, default=96)
ap.add_argument('--azim', type=float, default=35.0)
ap.add_argument('--elev', type=float, default=12.0)
ap.add_argument('--threads', type=int, default=4)
a = ap.parse_args(argv)

bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
bpy.ops.import_scene.gltf(filepath=a.glb)
objs = [o for o in bpy.context.scene.objects if o.type == 'MESH']
if not objs:
    raise SystemExit('нет мешей в ' + a.glb)

lo = Vector((1e9, 1e9, 1e9)); hi = Vector((-1e9, -1e9, -1e9))
for o in objs:
    for c in o.bound_box:
        w = o.matrix_world @ Vector(c)
        lo = Vector(map(min, lo, w)); hi = Vector(map(max, hi, w))
size = hi - lo                                 # Blender: Z вверх (импорт glTF переворачивает Y→Z)
h = size.z
cx, cy = (lo.x + hi.x) / 2, (lo.y + hi.y) / 2
R = max(size.x, size.y, h * 0.6)

# стол и фон — светло-серый, матовый
for name, loc, scale in (('table', (cx, cy, lo.z - 0.002), 3.0),):
    bpy.ops.mesh.primitive_plane_add(size=1, location=loc)
    t = bpy.context.object; t.scale = (scale * 2, scale * 2, 1); t.name = name
    m = bpy.data.materials.new('grey'); m.use_nodes = True
    m.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value = (0.62, 0.62, 0.60, 1)
    m.node_tree.nodes['Principled BSDF'].inputs['Roughness'].default_value = 0.9
    t.data.materials.append(m)

# линейка 10 см: тонкий брусок рядом, чтобы читался размер
bpy.ops.mesh.primitive_cube_add(size=1, location=(cx + R * 0.9, cy - R * 0.2, lo.z + 0.05))
ruler = bpy.context.object; ruler.scale = (0.012, 0.012, 0.10); ruler.name = 'ruler10cm'
rm = bpy.data.materials.new('ruler'); rm.use_nodes = True
rm.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value = (0.9, 0.15, 0.1, 1)
ruler.data.materials.append(rm)

# мир и свет
w = bpy.data.worlds.new('w'); sc.world = w; w.use_nodes = True
bg = w.node_tree.nodes['Background']; bg.inputs['Color'].default_value = (0.85, 0.87, 0.9, 1); bg.inputs['Strength'].default_value = 0.7
for nm, loc, energy, sz in (('key', (-2.5, -2.0, 3.0), 400, 2.5), ('rim', (2.5, 2.5, 2.0), 120, 2.0)):
    bpy.ops.object.light_add(type='AREA', location=(cx + loc[0], cy + loc[1], lo.z + loc[2]))
    l = bpy.context.object; l.data.energy = energy; l.data.size = sz; l.name = nm
    d = Vector((cx, cy, lo.z + h / 2)) - l.location
    l.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()

# камера
az, el = math.radians(a.azim), math.radians(a.elev)
dist = max(h, R * 2) * 2.2
cam_loc = Vector((cx + dist * math.sin(az) * math.cos(el), cy - dist * math.cos(az) * math.cos(el), lo.z + h * 0.5 + dist * math.sin(el)))
bpy.ops.object.camera_add(location=cam_loc)
cam = bpy.context.object
target = Vector((cx, cy, lo.z + h / 2))
cam.rotation_euler = (target - cam_loc).to_track_quat('-Z', 'Y').to_euler()
cam.data.lens = 70
cam.data.sensor_width = 36
need = max(h, R * 1.3) / 0.8                  # видимая высота кадра
cam.data.lens = cam.data.sensor_width * dist / need
sc.camera = cam

sc.render.engine = 'CYCLES'
sc.cycles.device = 'CPU'
sc.cycles.samples = a.samples
sc.cycles.use_denoising = True
sc.render.threads_mode = 'FIXED'; sc.render.threads = a.threads
sc.render.resolution_x = sc.render.resolution_y = a.size
sc.render.image_settings.file_format = 'PNG'
sc.view_settings.view_transform = 'AgX'
sc.render.filepath = a.out
os.makedirs(os.path.dirname(a.out), exist_ok=True)
bpy.ops.render.render(write_still=True)
print('CARD', a.glb, a.out, 'h_cm', round(h * 100, 1))
