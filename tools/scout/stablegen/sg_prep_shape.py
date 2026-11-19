"""Подготовка формы к покраске StableGen (T-20261119-90, правило директора 21:54): форма без развёртки и с ~500 тыс. граней запекается в Blender однопоточно очень долго.
Здесь: склеить меши → упростить до целевого числа граней (Decimate collapse) → развёртка Smart UV Project в слой `BakeUV` → экспорт GLB.

    blender -b -P sg_prep_shape.py -- --glb <вход.glb> --out <выход.glb> [--faces 150000] [--angle 66] [--margin 0.003]
Запускать под `tools/ops/heavy-slot.sh`. Печатает «prep: …» строки с числами до/после."""
import argparse
import math
import sys
import time

import bpy

argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
ap = argparse.ArgumentParser()
ap.add_argument('--glb', required=True)
ap.add_argument('--out', required=True)
ap.add_argument('--faces', type=int, default=150000)
ap.add_argument('--angle', type=float, default=66.0)
ap.add_argument('--margin', type=float, default=0.003)
a = ap.parse_args(argv)

t0 = time.time()
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=a.glb)
meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
if not meshes:
    raise SystemExit('prep: в файле нет мешей')
bpy.ops.object.select_all(action='DESELECT')
for o in meshes:
    o.select_set(True)
bpy.context.view_layer.objects.active = meshes[0]
if len(meshes) > 1:
    bpy.ops.object.join()
obj = bpy.context.view_layer.objects.active
n0 = len(obj.data.polygons)
uv0 = [u.name for u in obj.data.uv_layers]
print(f'prep: вход {n0} граней, UV {uv0}, {time.time() - t0:.1f} с', flush=True)

if n0 > a.faces:
    md = obj.modifiers.new('dec', 'DECIMATE')
    md.decimate_type = 'COLLAPSE'
    md.ratio = a.faces / n0
    md.use_collapse_triangulate = True
    bpy.ops.object.modifier_apply(modifier=md.name)
n1 = len(obj.data.polygons)
print(f'prep: после упрощения {n1} граней, {time.time() - t0:.1f} с', flush=True)

while obj.data.uv_layers:
    obj.data.uv_layers.remove(obj.data.uv_layers[0])
obj.data.uv_layers.new(name='BakeUV')
bpy.ops.object.mode_set(mode='EDIT')
bpy.ops.mesh.select_all(action='SELECT')
bpy.ops.uv.smart_project(angle_limit=math.radians(a.angle), island_margin=a.margin)
bpy.ops.object.mode_set(mode='OBJECT')
print(f'prep: развёртка готова, {time.time() - t0:.1f} с', flush=True)

bpy.ops.export_scene.gltf(filepath=a.out, export_format='GLB', use_selection=False)
print(f'prep: записано {a.out} ({n1} граней), всего {time.time() - t0:.1f} с', flush=True)
