"""ПРЕДМЕТНЫЙ СТЕНД ПРОБЫ МЕШЕЙ (T-20261118-91): один GLB → 20 кадров (10 видов × текстура/«глина»), Cycles на процессоре, 0 ₽. Запуск — внутри Blender:

  ~/opt/blender-4.5.9/blender -b -P render_stand.py -- --glb <model.glb> --out <папка> [--samples 64] [--w 1600 --h 1200] [--threads 4]

ЗАЧЕМ. Сравнивать модели можно только на ОДИНАКОВЫХ камере и свете: вид — 8 ракурсов по кругу (0…315°, наклон 15°) + сверху 55° + снизу −20°; свет «за камерой»
(ключевой солнечный сверху-сбоку от камеры + ровный фон) — один и тот же относительно камеры в каждом кадре и у каждой модели; пол — нейтральный серый
(в виде снизу пола нет); «глина» — тот же меш с одним серым матовым материалом (видна форма без цвета и текстуры). Модель масштабируется ТОЛЬКО для кадра
(в единичный габарит по большей стороне), реальные размеры не трогаем. Рядом кладётся `bbox.json` — габарит меша по осям Blender (X ширина, Y глубина, Z высота после
импорта glTF) и доли к большей стороне: по ним считаем, не сплющена ли модель (пропорции из фида — в `set30.json`).

Выход: <out>/NN_<вид>_<tex|clay>.png (NN — порядок просмотра: текстура и глина каждого вида рядом), полный размер, отдельными файлами.
"""
import argparse
import json
import math
import os
import sys
import time

import bpy
from mathutils import Vector

argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
ap = argparse.ArgumentParser()
ap.add_argument('--glb', required=True)
ap.add_argument('--out', required=True)
ap.add_argument('--samples', type=int, default=64)
ap.add_argument('--w', type=int, default=1600)
ap.add_argument('--h', type=int, default=1200)
ap.add_argument('--threads', type=int, default=4)
ap.add_argument('--analyze', action='store_true', help='только разбор кусков меша и габарита (без кадров)')
ap.add_argument('--only', default='', help='отладка: список видов через запятую (az000,top55,bot-20)')
a = ap.parse_args(argv)
T0 = time.time()
os.makedirs(a.out, exist_ok=True)

bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
bpy.ops.import_scene.gltf(filepath=a.glb)
meshes = [o for o in sc.objects if o.type == 'MESH']
if not meshes:
    raise SystemExit('в GLB нет мешей')


def bounds():
    pts = [o.matrix_world @ Vector(c) for o in meshes for c in o.bound_box]
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    return lo, hi


lo, hi = bounds()
ext = hi - lo
mx = max(ext)


info = {'extent_xyz': [round(ext.x, 4), round(ext.y, 4), round(ext.z, 4)], 'ratio_to_max_xyz': [round(ext.x / mx, 3), round(ext.y / mx, 3), round(ext.z / mx, 3)],
        'axes': 'Blender после импорта glTF: X — ширина, Y — глубина, Z — высота (Z-up)', 'glb': os.path.basename(a.glb)}


def components():
    """Связные куски меша (по рёбрам): треугольники и габарит каждого (мировые координаты). Нужно, чтобы увидеть лишнее — «плиту под предметом», висящие обрывки."""
    out = []
    for o in meshes:
        me = o.data
        n = len(me.vertices)
        par = list(range(n))

        def find(x):
            while par[x] != x:
                par[x] = par[par[x]]
                x = par[x]
            return x
        for e in me.edges:
            ra, rb = find(e.vertices[0]), find(e.vertices[1])
            if ra != rb:
                par[ra] = rb
        mw = o.matrix_world
        co = [mw @ v.co for v in me.vertices]
        comp = {}
        for pl in me.polygons:
            r = find(pl.vertices[0])
            c = comp.setdefault(r, {'tris': 0, 'v': set()})
            c['tris'] += len(pl.vertices) - 2
            c['v'].update(pl.vertices)
        for c in comp.values():
            pts = [co[i] for i in c['v']]
            lo_ = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
            hi_ = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
            out.append({'tris': c['tris'], 'min': lo_, 'max': hi_})
    return sorted(out, key=lambda c: -c['tris'])



# в единичный габарит, низ — на пол, центр по X/Y в нуле (только для кадра)
root = bpy.data.objects.new('root', None)
sc.collection.objects.link(root)
for o in sc.objects:
    if o is not root and o.parent is None:
        o.parent = root
k = 1.0 / mx
root.scale = (k, k, k)
bpy.context.view_layer.update()
lo, hi = bounds()
root.location = Vector((-(lo.x + hi.x) / 2, -(lo.y + hi.y) / 2, -lo.z))
bpy.context.view_layer.update()
lo, hi = bounds()
centre = (lo + hi) / 2
radius = max((hi - lo).length / 2, 0.5)

comps = components()
tot = sum(c['tris'] for c in comps) or 1
info['components'] = [{'tris': c['tris'], 'share': round(c['tris'] / tot, 3), 'min': [round(x, 3) for x in c['min']], 'max': [round(x, 3) for x in c['max']],
                       'size': [round(c['max'][i] - c['min'][i], 3) for i in range(3)]} for c in comps[:8]]
info['components_total'] = len(comps)
# «плоский слой»: куски тоньше 2 % габарита (стопка листов у пола — рисуется как тёмная плита; поймано на комоде 19.11) — считаем отдельно, камеру наводим на остальное
flat = [c for c in comps if (c['max'].z - c['min'].z) < 0.02]
main = [c for c in comps if (c['max'].z - c['min'].z) >= 0.02]
info['flat_layer'] = {'pieces': len(flat), 'tris_share': round(sum(c['tris'] for c in flat) / tot, 3)}
if main:
    mlo = Vector((min(c['min'].x for c in main), min(c['min'].y for c in main), min(c['min'].z for c in main)))
    mhi = Vector((max(c['max'].x for c in main), max(c['max'].y for c in main), max(c['max'].z for c in main)))
    msz = mhi - mlo
    info['main_extent_xyz'] = [round(msz.x, 4), round(msz.y, 4), round(msz.z, 4)]
    info['main_ratio_to_max_xyz'] = [round(x / max(msz), 3) for x in msz]       # доли предмета без плоского слоя: ширина : глубина : высота
    info['main_tris_share'] = round(sum(c['tris'] for c in main) / tot, 3)
    centre, radius = (mlo + mhi) / 2, max(msz.length / 2, 0.15)
json.dump(info, open(os.path.join(a.out, 'bbox.json'), 'w'), ensure_ascii=False, indent=1)
print('куски меша:', json.dumps(info['components'][:5], ensure_ascii=False), flush=True)
if a.analyze:
    raise SystemExit(0)

# пол: нейтральный серый, большая плита
bpy.ops.mesh.primitive_plane_add(size=40, location=(0, 0, 0))
floor = bpy.context.active_object
fm = bpy.data.materials.new('floor')
fm.use_nodes = True
fm.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value = (0.62, 0.62, 0.60, 1)
fm.node_tree.nodes['Principled BSDF'].inputs['Roughness'].default_value = 0.9
floor.data.materials.append(fm)

# ровный фон + «глина»
w = bpy.data.worlds.new('w')
w.use_nodes = True
w.node_tree.nodes['Background'].inputs['Color'].default_value = (0.82, 0.83, 0.85, 1)
w.node_tree.nodes['Background'].inputs['Strength'].default_value = 0.45
sc.world = w
clay = bpy.data.materials.new('clay')
clay.use_nodes = True
clay.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value = (0.50, 0.50, 0.49, 1)
clay.node_tree.nodes['Principled BSDF'].inputs['Roughness'].default_value = 0.85

cam_d = bpy.data.cameras.new('cam')
cam_d.lens = 50
cam_d.sensor_width = 36
cam = bpy.data.objects.new('cam', cam_d)
sc.collection.objects.link(cam)
sc.camera = cam
sun_d = bpy.data.lights.new('sun', 'SUN')
sun_d.energy = 1.8
sun_d.angle = math.radians(6)
sun = bpy.data.objects.new('sun', sun_d)
sc.collection.objects.link(sun)

fov = 2 * math.atan(cam_d.sensor_width / 2 / cam_d.lens)
dist = radius / math.sin(min(fov, 2 * math.atan(cam_d.sensor_width * a.h / a.w / 2 / cam_d.lens)) / 2) * 1.12

sc.render.engine = 'CYCLES'
sc.cycles.device = 'CPU'
sc.cycles.samples = a.samples
sc.cycles.use_denoising = True
sc.cycles.denoiser = 'OPENIMAGEDENOISE'
sc.render.threads_mode = 'FIXED'
sc.render.threads = a.threads
sc.render.resolution_x, sc.render.resolution_y, sc.render.resolution_percentage = a.w, a.h, 100
sc.view_settings.view_transform = 'Standard'
sc.view_settings.look = 'None'
sc.render.image_settings.file_format = 'PNG'
sc.render.film_transparent = False


def aim(obj, pos, target):
    obj.location = pos
    obj.rotation_euler = (target - pos).to_track_quat('-Z', 'Y').to_euler()


def polar(az_deg, el_deg, r):
    az, el = math.radians(az_deg), math.radians(el_deg)
    # az 0 — смотрим на предмет со стороны −Y (спереди), по часовой сверху
    return centre + Vector((r * math.cos(el) * math.sin(az), -r * math.cos(el) * math.cos(az), r * math.sin(el)))


views = [(f'az{az:03d}', az, 15) for az in range(0, 360, 45)] + [('top55', 45, 55), ('bot-20', 45, -20)]
if a.only:
    views = [v for v in views if v[0] in a.only.split(',')]
n = 0
for vi, (name, az, el) in enumerate(views):
    floor.hide_render = el < 0                       # снизу пола нет
    aim(cam, polar(az, el, dist), centre)
    aim(sun, polar(az - 40, el + 35, 5), centre)     # свет — на 40° левее и на 35° выше камеры: одинаков относительно камеры во всех кадрах
    for mode in ('tex', 'clay'):
        bpy.context.view_layer.material_override = clay if mode == 'clay' else None
        n += 1
        p = os.path.join(a.out, f'{n:02d}_{name}_{mode}.png')
        sc.render.filepath = p
        t = time.time()
        bpy.ops.render.render(write_still=True)
        print(f'кадр {n}/{2 * len(views)} {name} {mode}: {time.time() - t:.0f} с', flush=True)
print(f'ГОТОВО {n} кадров за {time.time() - T0:.0f} с, габарит {tuple(round(x, 3) for x in ext)}', flush=True)
