"""Контрольный кадр этапа 08 «материал» (paint-photo-fill-01, T-20261121-170/1): модель при студийном свете — видно блеск и матовость, стекло и металл.

ЗАЧЕМ. Рецепт материала виден только в свете: ткань держит мягкий ворсовый блик, дерево — полуматовое, металл и стекло отражают окно-софтбокс. Кадр — перёд (азимут по умолчанию 35°,
чтобы блик лёг на боковую грань), серый фон-пол, два светлых окна-софтбокса и тёмная рамка вокруг для контраста отражений; Cycles на процессоре (0 ₽).
Запуск (Blender без окна; тяжёлое — под heavy-slot):
    blender -b -P tools/assets/material_frame_blender.py -- <model.glb> <out.png> [--size 768] [--samples 48] [--az 35] [--el 12]
"""
import math
import os
import sys

import bpy
import numpy as np
from mathutils import Vector

argv = sys.argv[sys.argv.index('--') + 1:]
glb, out = argv[0], argv[1]
opt = {'--size': 768, '--samples': 48, '--az': 35.0, '--el': 12.0}
i = 2
while i < len(argv):
    if argv[i] in opt:
        opt[argv[i]] = type(opt[argv[i]])(argv[i + 1])
        i += 2
    else:
        i += 1
size = int(opt['--size'])

for o in list(bpy.data.objects):
    bpy.data.objects.remove(o, do_unlink=True)
bpy.ops.import_scene.gltf(filepath=glb)
meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
if not meshes:
    print('FRAME FAIL нет меша')
    sys.exit(1)
# границы по 1–99 % вершин (одиночные обломки у края не раздувают кадр); пол — под самой нижней точкой
vs = np.concatenate([np.array([(o.matrix_world @ v.co)[:] for v in o.data.vertices]) for o in meshes])
lo, hi = np.percentile(vs, 1, axis=0), np.percentile(vs, 99, axis=0)
ctr = Vector(((lo + hi) / 2).tolist())
radius = float(np.linalg.norm(hi - lo) / 2)
floor_z = float(lo[2])

sc = bpy.context.scene
sc.render.engine = 'CYCLES'
sc.cycles.device = 'CPU'
sc.cycles.samples = int(opt['--samples'])
sc.cycles.use_denoising = True
sc.cycles.transmission_bounces = 8
sc.cycles.glossy_bounces = 6
sc.render.threads_mode = 'FIXED'
sc.render.threads = 2
sc.render.resolution_x = sc.render.resolution_y = size
sc.render.image_settings.file_format = 'PNG'
sc.view_settings.view_transform = 'Standard'

# фон-«студия»: светло-серый мир + пол
w = bpy.data.worlds.new('w')
w.use_nodes = True
w.node_tree.nodes['Background'].inputs[0].default_value = (0.45, 0.45, 0.47, 1)
w.node_tree.nodes['Background'].inputs[1].default_value = 0.35
sc.world = w
bpy.ops.mesh.primitive_plane_add(size=radius * 14, location=(ctr.x, ctr.y, floor_z))
floor = bpy.context.active_object
fm = bpy.data.materials.new('floor')
fm.use_nodes = True
fm.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value = (0.4, 0.4, 0.4, 1)
fm.node_tree.nodes['Principled BSDF'].inputs['Roughness'].default_value = 0.9
floor.data.materials.append(fm)


def area(name, loc, energy, size_m, color=(1, 1, 1)):
    d = bpy.data.lights.new(name, 'AREA')
    d.energy = energy
    d.size = size_m
    d.color = color
    o = bpy.data.objects.new(name, d)
    sc.collection.objects.link(o)
    o.location = loc
    o.rotation_euler = (ctr - Vector(loc)).to_track_quat('-Z', 'Y').to_euler()
    return o


r = radius
area('key', (ctr.x - 2.2 * r, ctr.y - 2.2 * r, ctr.z + 2.0 * r), 170 * r * r, 2.2 * r)
area('rim', (ctr.x + 2.6 * r, ctr.y + 1.2 * r, ctr.z + 1.4 * r), 90 * r * r, 1.8 * r, (0.9, 0.95, 1.0))
area('fill', (ctr.x + 1.6 * r, ctr.y - 2.6 * r, ctr.z + 0.6 * r), 45 * r * r, 2.6 * r)

cam = bpy.data.objects.new('cam', bpy.data.cameras.new('cam'))
sc.collection.objects.link(cam)
sc.camera = cam
cam.data.lens = 60
a, e = math.radians(opt['--az']), math.radians(opt['--el'])
half_fov = math.atan(cam.data.sensor_width / 2 / cam.data.lens)
dist = radius / (1.0 * math.tan(half_fov))
cam.location = ctr + Vector((-math.sin(a) * math.cos(e) * dist, -math.cos(a) * math.cos(e) * dist, math.sin(e) * dist))
cam.rotation_euler = (ctr - cam.location).to_track_quat('-Z', 'Y').to_euler()
bpy.context.view_layer.update()
sc.render.filepath = out
bpy.ops.render.render(write_still=True)
print('FRAME OK', out, os.path.getsize(out))
