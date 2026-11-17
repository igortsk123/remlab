"""ГОТОВНОСТЬ РЕНДЕР-МАШИНЫ (T-20261117-22): Blender поднимает устройство и делает МАЛЫЙ НАСТОЯЩИЙ Cycles-прогон (не «процесс жив»).
Запуск: blender -b -P ready_probe.py -- [--device auto|optix|cuda|cpu] [--require-gpu 1] [--out probe.png]
Печатает: PROBE_DEVICE <что реально выбрано>, DEVICE_LIST …, PROBE_SEC <время прогона с компиляцией ядер>, PROBE_PIXELS <средняя яркость>;
код выхода 0 — готова, 3 — запрошен GPU, а рендер пошёл бы на CPU (или устройства нет), 4 — прогон дал пустой кадр.
Прогон включает шумоподавление OIDN — тот же путь, что у боевого кадра (на GPU OIDN тоже требует исправного устройства)."""
import argparse
import os
import sys
import time

import bpy
import numpy as np

argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
ap = argparse.ArgumentParser()
ap.add_argument('--device', default='auto', choices=['cpu', 'auto', 'optix', 'cuda'])
ap.add_argument('--require-gpu', type=int, default=1)
ap.add_argument('--out', default='/tmp/ready-probe.png')
a = ap.parse_args(argv)
t0 = time.time()

bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
sc.render.engine = 'CYCLES'
cy = sc.cycles

used = 'CPU'
cy.device = 'CPU'
if a.device != 'cpu':
    prefs = bpy.context.preferences.addons['cycles'].preferences
    for kind in (['OPTIX', 'CUDA'] if a.device == 'auto' else [a.device.upper()]):
        try:
            prefs.compute_device_type = kind
        except (TypeError, ValueError) as e:
            print(f'DEVICE_SKIP {kind}: {e}', flush=True)
            continue
        devs = [d for d in prefs.get_devices_for_type(kind) if d.type == kind]
        print(f'DEVICE_LIST {kind}: ' + (', '.join(d.name for d in devs) or 'нет'), flush=True)
        if devs:
            for d in prefs.devices:
                d.use = d.type == kind
            cy.device = 'GPU'
            used = f'{kind}:{devs[0].name}'
            try:
                cy.denoising_use_gpu = True
            except AttributeError:
                pass
            break
print('PROBE_DEVICE', used, flush=True)

cy.samples = 16
cy.use_denoising = True
cy.denoiser = 'OPENIMAGEDENOISE'
sc.render.resolution_x = sc.render.resolution_y = 128
sc.render.image_settings.file_format = 'PNG'
bpy.ops.mesh.primitive_plane_add(size=6)
bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, 0.5))
sun = bpy.data.objects.new('sun', bpy.data.lights.new('sun', 'SUN'))
sun.data.energy = 4.0
sun.rotation_euler = (0.8, 0.2, 0.5)
sc.collection.objects.link(sun)
cam = bpy.data.objects.new('cam', bpy.data.cameras.new('cam'))
cam.location = (3, -3, 2.2)
cam.rotation_euler = (1.1, 0, 0.78)
sc.collection.objects.link(cam)
sc.camera = cam
sc.render.filepath = a.out
bpy.ops.render.render(write_still=True)
sec = time.time() - t0
img = bpy.data.images.load(a.out)
px = np.array(img.pixels[:])
mean = float(px.mean()) if px.size else 0.0
print(f'PROBE_SEC {sec:.1f}', flush=True)
print(f'PROBE_PIXELS {mean:.4f}', flush=True)
if a.require_gpu and not used.startswith(('OPTIX', 'CUDA')):
    print('PROBE_FAIL: запрошен GPU, устройство не поднялось', flush=True)
    sys.exit(3)
if mean < 0.01:
    print('PROBE_FAIL: пустой кадр', flush=True)
    sys.exit(4)
print('PROBE_OK', used, flush=True)
