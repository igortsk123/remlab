"""Подготовка формы к покраске StableGen (T-20261119-90, правило директора 21:54): форма без развёртки и с ~500 тыс. граней запекается в Blender однопоточно очень долго.
Здесь: склеить меши → упростить до целевого числа граней (Decimate collapse) → развёртка Smart UV Project в слой `BakeUV` → экспорт GLB.

    blender -b -P sg_prep_shape.py -- --glb <вход.glb> --out <выход.glb> [--faces 150000] [--angle 66] [--margin 0.003]
Запускать под `tools/ops/heavy-slot.sh`. Печатает «prep: …» строки с числами до/после.

Родной цвет TRELLIS.2 (T-20261120-167, шаг 0 плана paint-photo-fill-01): `--color-from <родной.glb>` (по умолчанию ВЫКЛ.) — после упрощения и новой развёртки родная форма с цветом
копируется рядом (`<выход>.native.glb`, если лежит в другом месте), а baseColor / металл-шероховатость / альфа переносятся на новую развёртку ближайшими точками 3D
(`sg_color_transfer.py`, numpy+scipy+trimesh во внешнем питоне: `--color-python`, иначе $SG_COLOR_PYTHON, иначе `~/venvs/scout/bin/python`). Доля текселей с цветом < 99 % или сбой →
выход 3 (срез плиты-подложки TRELLIS до упрощения — `plate_strip.py`, отчёт `<выход>.plate.json`, выключатель `--no-plate-strip`; мерки: доля текселей с цветом и доля граней с цветом верного места, обе ≥ 99 %; с флагом развёртка крупнее — угол 89, поле 0.0005, без флага прежняя 66 / 0.003), а форма без цвета остаётся как `<выход>.nocolor.glb` (под именем выхода файла НЕТ — пакетный скрипт не примет её за готовую)."""
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
ap.add_argument('--angle', type=float, default=None, help='угол разреза Smart UV; без --color-from 66, с --color-from 89 (крупные острова)')
ap.add_argument('--margin', type=float, default=None, help='поле между островками; без --color-from 0.003, с --color-from 0.0005 (T-167: поле 0.003 съедало карту, 45–61 %% граней оставались без текселя)')
ap.add_argument('--color-from', default=None, help='родной GLB TRELLIS.2 с цветом: перенести его baseColor/металл-шероховатость/альфа на новую развёртку (по умолчанию выкл.)')
ap.add_argument('--no-plate-strip', action='store_true', help='с --color-from срез плиты-подложки TRELLIS до упрощения включён; этим флагом выключить')
ap.add_argument('--color-python', default=None, help='питон с numpy+scipy+trimesh+PIL для переноса (иначе $SG_COLOR_PYTHON, иначе ~/venvs/scout/bin/python)')
ap.add_argument('--color-size', type=int, default=None, help='сторона новой карты цвета (по умолчанию — как у родной)')
a = ap.parse_args(argv)
if a.angle is None:
    a.angle = 89.0 if a.color_from else 66.0
if a.margin is None:
    a.margin = 0.0005 if a.color_from else 0.003

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

if a.color_from and not a.no_plate_strip:
    # Срез плиты-подложки TRELLIS ДО упрощения (после упрощения лист не плоский — не находится; plate_strip.py, T-20261121-170/2). Отчёт — рядом с выходом: `<выход>.plate.json`
    import json
    import os

    import bmesh
    import numpy as np
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import plate_strip as P
    me = obj.data
    me.calc_loop_triangles()
    if len(me.loop_triangles) != len(me.polygons):
        rep_plate = {'faces_before': len(me.polygons), 'plate_found': False, 'refused': 'грани не треугольники — срез плиты пропущен'}
    else:
        Vp = np.empty(len(me.vertices) * 3)
        me.vertices.foreach_get('co', Vp)
        Fp = np.empty(len(me.loop_triangles) * 3, np.int64)
        me.loop_triangles.foreach_get('vertices', Fp)
        remove, rep_plate = P.analyze(Vp.reshape(-1, 3), Fp.reshape(-1, 3))
        if remove.any():
            bm = bmesh.new()
            bm.from_mesh(me)
            bm.faces.ensure_lookup_table()
            bmesh.ops.delete(bm, geom=[bm.faces[i] for i in np.nonzero(remove)[0]], context='FACES')
            bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context='VERTS')
            bm.to_mesh(me)
            bm.free()
            me.update()
    with open((a.out[:-4] if a.out.endswith('.glb') else a.out) + '.plate.json', 'w', encoding='utf-8') as fp:
        json.dump(rep_plate, fp, ensure_ascii=False)
    n0 = len(obj.data.polygons)
    print(f'prep: плита {"срезана" if rep_plate.get("plate_found") and not rep_plate.get("refused") else "не срезана"} ({rep_plate.get("refused") or "нет плиты" if not rep_plate.get("plate_found") else "найдена"}); граней после среза {n0}, {time.time() - t0:.1f} с', flush=True)

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

export_to = (a.out[:-4] if a.out.endswith('.glb') else a.out) + '.nocolor.glb' if a.color_from else a.out
bpy.ops.export_scene.gltf(filepath=export_to, export_format='GLB', use_selection=False)
print(f'prep: записано {export_to} ({n1} граней), всего {time.time() - t0:.1f} с', flush=True)

if a.color_from:
    import os
    import shutil
    import subprocess
    native_copy = (a.out[:-4] if a.out.endswith('.glb') else a.out) + '.native.glb'
    if os.path.abspath(a.color_from) != os.path.abspath(native_copy) and not os.path.exists(native_copy):
        shutil.copy2(a.color_from, native_copy)          # родной GLB с цветом сохраняем до всего прочего: источник для переноса и для повторов
    py = a.color_python or os.environ.get('SG_COLOR_PYTHON') or os.path.expanduser('~/venvs/scout/bin/python')
    cmd = [py, '-I', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sg_color_transfer.py'), 'transfer', '--native', a.color_from, '--shape', export_to, '--out', a.out]
    if a.color_size:
        cmd += ['--size', str(a.color_size)]
    if a.no_plate_strip:
        cmd += ['--no-plate-strip']
    r = subprocess.run(cmd, capture_output=True, text=True)
    print(r.stdout.strip()[-800:], flush=True)
    if r.returncode == 0:
        os.remove(export_to)
        print(f'prep: цвет перенесён → {a.out}, всего {time.time() - t0:.1f} с', flush=True)
    else:
        print(f'prep: ЦВЕТ НЕ ПЕРЕНЕСЁН (код {r.returncode}): {r.stderr.strip()[-400:]} — форма без цвета осталась как {export_to}', flush=True)
        sys.exit(3)
