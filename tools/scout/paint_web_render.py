"""Этап 10 «сайт» (paint_web.py): кадры нескольких GLB ОДНОЙ камерой в Blender (Cycles ЦП, излучающие материалы: плоский свет, цвет текстуры как есть).

  blender -b -P paint_web_render.py -- <json: {"views": [...], "res": 768, "margin": 1.15, "items": [{"glb": "...", "out": "префикс"}]}>

Камера считается по ПЕРВОМУ GLB (полной модели) и общая для всех: кадры «полная» и «лёгкая» сравнимы пиксель в пиксель.
Кадр — `<out>-<вид>.png` (RGBA, фон прозрачный). Печатает `TRIS <glb> <число граней>` и `IMG <glb> <ширина> <высота>` (размер картинок после чтения).
Азимут 0 — камера на +Z модели glTF (передняя сторона по соглашению glTF), растёт против часовой; 180 — сзади.
Blender читает геометрию meshopt, но НЕ читает KTX2 — лёгкая копия для кадров берётся с JPEG-текстурой того же размера (см. paint_web.py).
"""
import json
import math
import sys

import bpy
from mathutils import Vector

cfg = json.loads(sys.argv[sys.argv.index('--') + 1])
res, margin = int(cfg['res']), float(cfg['margin'])


def load(path):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=path)
    meshes = [o for o in bpy.data.objects if o.type == 'MESH']
    tri = 0
    for o in meshes:
        o.data.calc_loop_triangles()
        tri += len(o.data.loop_triangles)
    print('TRIS', path, tri, flush=True)
    for im in bpy.data.images:
        if im.size[0]:
            print('IMG', path, im.size[0], im.size[1], flush=True)
    return meshes


def bbox(meshes):
    pts = [o.matrix_world @ Vector(c) for o in meshes for c in o.bound_box]
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    return lo, hi


def flat_materials():
    """Каждому материалу — излучение цвета текстуры (или базового цвета): кадр без освещения, сравниваем только цвет и форму."""
    for mat in bpy.data.materials:
        if not mat.use_nodes:
            continue
        nt = mat.node_tree
        out = next((n for n in nt.nodes if n.type == 'OUTPUT_MATERIAL'), None)
        if out is None:
            continue
        tex = next((n for n in nt.nodes if n.type == 'TEX_IMAGE'), None)
        emi = nt.nodes.new('ShaderNodeEmission')
        emi.inputs['Strength'].default_value = 1.0
        if tex is not None:
            nt.links.new(tex.outputs['Color'], emi.inputs['Color'])
        else:
            bsdf = next((n for n in nt.nodes if n.type == 'BSDF_PRINCIPLED'), None)
            if bsdf is not None:
                emi.inputs['Color'].default_value = bsdf.inputs['Base Color'].default_value
        nt.links.new(emi.outputs['Emission'], out.inputs['Surface'])


def setup_scene():
    """Cycles на ЦП (Workbench и Eevee на этой машине не стартуют: нет libEGL), излучающие материалы, цвет без тонового сжатия."""
    sc = bpy.context.scene
    sc.render.engine = 'CYCLES'
    sc.cycles.device = 'CPU'
    sc.cycles.samples = 16
    sc.cycles.use_denoising = False
    sc.cycles.seed = 0
    sc.render.threads_mode = 'FIXED'
    sc.render.threads = 2
    sc.render.film_transparent = True
    sc.render.resolution_x = sc.render.resolution_y = res
    sc.render.image_settings.file_format = 'PNG'
    sc.render.image_settings.color_mode = 'RGBA'
    sc.view_settings.view_transform = 'Standard'
    sc.view_settings.look = 'None'
    sc.display_settings.display_device = 'sRGB'
    flat_materials()
    return sc


cam_frame = None
for k, item in enumerate(cfg['items']):
    meshes = load(item['glb'])
    sc = setup_scene()
    if cam_frame is None:                       # камера — по первой (полной) модели
        lo, hi = bbox(meshes)
        cam_frame = ((lo + hi) / 2, max(hi.x - lo.x, hi.y - lo.y, hi.z - lo.z) * margin, max(hi.x - lo.x, hi.y - lo.y, hi.z - lo.z))
    centre, scale, size = cam_frame
    cam = bpy.data.objects.new('cam', bpy.data.cameras.new('cam'))
    bpy.context.scene.collection.objects.link(cam)
    cam.data.type = 'ORTHO'
    cam.data.ortho_scale = scale
    cam.data.clip_start, cam.data.clip_end = 0.01, size * 20
    sc.camera = cam
    for v in cfg['views']:
        az, el = math.radians(v['azimuth']), math.radians(v['elevation'])
        # glTF (x, y, z) → Blender (x, −z, y): камера на +Z glTF при азимуте 0
        d = Vector((math.sin(az) * math.cos(el), -math.cos(az) * math.cos(el), math.sin(el)))
        cam.location = centre + d * size * 5
        cam.rotation_euler = (centre - cam.location).to_track_quat('-Z', 'Y').to_euler()
        sc.render.filepath = f"{item['out']}-{v['name']}.png"
        bpy.ops.render.render(write_still=True)
print('RENDER_DONE', flush=True)
