"""ЛОКАЛЬНАЯ ПЕРЕПРОЕКЦИЯ StableGen (T-20261119-90/6, идея директора 22:5x): те же сохранённые виды прогона, другие настройки смешивания → запекание → GLB. БЕЗ пода/GPU.
Запускается ВНУТРИ Blender с уже открытым session.blend прогона (таймер сохраняется только так):
  xvfb-run -a blender session.blend --factory-startup --python-use-system-env --python sg_reproject.py -- <config.json>
Конфиг: out (новая папка), sgout (копия `sg-output` прогона; аддон ищет виды по scene.output_timestamp), scene_props (например weight_exponent, discard_factor),
bake_margin, bake_denoise, texture_resolution, bake_samples, timeout_s. Шаги: перепроекция (`object.stablegen_reproject`) → запекание в слой BakeUV → экспорт GLB."""
import json
import os
import sys
import time
import traceback
import importlib

import addon_utils
import bpy

ADDON = 'bl_ext.user_default.stablegen'
ARGS = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
CFG = json.load(open(ARGS[0], encoding='utf-8'))
OUT = CFG['out']
os.makedirs(OUT, exist_ok=True)
LOG = open(os.path.join(OUT, 'drive.log'), 'a', encoding='utf-8')
T0 = time.time()
ST = {'stage': 'init', 'error': '', 'done': False, 'steps': []}


def sg(mod):
    return importlib.import_module(f'{ADDON}.{mod}')


def say(msg):
    line = f'{time.time() - T0:7.1f}s  {msg}'
    print('[reproject]', line, flush=True)
    LOG.write(line + '\n')
    LOG.flush()


def save_status():
    json.dump(ST, open(os.path.join(OUT, 'status.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)


def finish(error=''):
    ST['error'], ST['done'] = error, True
    save_status()
    say('ГОТОВО' if not error else f'ОШИБКА: {error}')
    bpy.ops.wm.quit_blender()


def view3d_override():
    for win in bpy.context.window_manager.windows:
        for area in win.screen.areas:
            if area.type == 'VIEW_3D':
                for region in area.regions:
                    if region.type == 'WINDOW':
                        return dict(window=win, screen=win.screen, area=area, region=region, space_data=area.spaces.active)
    raise RuntimeError('в окне нет 3D-вида')


def busy():
    return sg('utils').sg_modal_active(bpy.context)


def steps():
    addon_utils.enable(ADDON, default_set=True, persistent=True)
    prefs = bpy.context.preferences.addons[ADDON].preferences
    bpy.context.preferences.system.use_online_access = True            # как в sg_drive: без этого poll оператора отказывает (локально, наружу ничего не уходит)
    prefs.server_address = CFG.get('server', '127.0.0.1:9')          # сервер не нужен: генерации нет
    prefs.output_dir = CFG['sgout']
    prefs.server_online = True                                          # оператор перепроекции требует «сервер подключён» (poll), хотя ничего не генерирует — картинки видов уже на диске
    sc = bpy.context.scene
    yield 'open'
    meshes = [o for o in sc.objects if o.type == 'MESH']
    if len(meshes) != 1:
        raise RuntimeError(f'ожидался один меш, найдено {len(meshes)}')
    obj = meshes[0]
    bpy.context.view_layer.objects.active = obj
    for o in sc.objects:
        o.select_set(o == obj)
    say(f"сцена: меш {obj.name}, граней {len(obj.data.polygons)}, камер {len([o for o in sc.objects if o.type == 'CAMERA'])}, output_timestamp={sc.output_timestamp!r}")
    for k, v in (CFG.get('scene_props') or {}).items():
        say(f'  {k}: {getattr(sc, k, "—")} → {v}')
        setattr(sc, k, v)
    drop = set(CFG.get('drop_cameras') or [])
    if drop:                                                            # отбраковка видов: камеру удаляем, файлы видов сдвигаем так, чтобы номер файла = номер камеры (так аддон их ищет)
        import glob
        import shutil
        cams = [o for o in sc.objects if o.type == 'CAMERA']
        keep = [(j, o) for j, o in enumerate(cams) if o.name not in drop]
        gen_dirs = glob.glob(os.path.join(CFG['sgout'], '**', 'generated'), recursive=True)
        for d in gen_dirs:
            files = {j: glob.glob(os.path.join(d, f'generated_image{j}-*.png')) for j, _ in enumerate(cams)}
            for new, (old, _) in enumerate(keep):
                for f in files[old]:
                    if new != old:
                        shutil.copyfile(f, f.replace(f'generated_image{old}-', f'generated_image{new}-'))
        for o in cams:
            if o.name in drop:
                bpy.data.objects.remove(o, do_unlink=True)
        say(f'отбракованы камеры {sorted(drop)}; осталось {len(keep)} видов (файлы сдвинуты)')
    yield 'reproject'
    prefs.server_online = True                                         # аддон сбрасывает флаг при старте — ставим прямо перед вызовом
    with bpy.context.temp_override(**view3d_override()):
        res = bpy.ops.object.stablegen_reproject('INVOKE_DEFAULT')
    say(f'reproject → {res}')
    if 'RUNNING_MODAL' not in res and 'FINISHED' not in res:
        raise RuntimeError(f'перепроекция не запустилась: {res}')
    n = 0
    t_end = time.time() + 600
    while busy() or sc.generation_status == 'waiting':
        n += 1
        if n % 40 == 0:
            say('перепроекция идёт…')
        if time.time() > t_end:
            raise RuntimeError('перепроекция: таймаут 600 с')
        yield 'wait-reproject'
    say('перепроекция завершена')
    yield 'bake'
    if CFG.get('bake_margin'):
        sc.render.bake.margin = int(CFG['bake_margin'])
        say(f'запас запекания: {sc.render.bake.margin} px')
    with bpy.context.temp_override(**view3d_override()):
        bpy.ops.object.bake_textures('EXEC_DEFAULT', texture_resolution=int(CFG.get('texture_resolution', 2048)), try_unwrap='none', overlap_only=False,
                                     bake_pbr=False, add_material=True, flatten_for_refine=False, samples=int(CFG.get('bake_samples', 16)),
                                     use_denoise=bool(CFG.get('bake_denoise', True)))
    n = 0
    while busy():
        n += 1
        if n % 40 == 0:
            say('запекание идёт…')
        yield 'wait-bake'
    say('запекание завершено')
    yield 'export'
    glb = os.path.join(OUT, 'painted.glb')
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.ops.export_scene.gltf(filepath=glb, export_format='GLB', use_selection=True, export_image_format='AUTO')
    ST['glb'], ST['glb_bytes'] = glb, os.path.getsize(glb)
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, 'session.blend'))
    say(f'экспорт: {glb} ({ST["glb_bytes"]} байт)')


GEN = steps()
DEADLINE = T0 + float(CFG.get('timeout_s', 1800))


def tick():
    if ST['done']:
        return None
    if time.time() > DEADLINE:
        finish('таймаут')
        return None
    try:
        stage = next(GEN)
        if not stage.startswith('wait'):
            ST['stage'] = stage
            ST['steps'].append((round(time.time() - T0, 1), stage))
            save_status()
            say(f'шаг: {stage}')
        return 0.5
    except StopIteration:
        finish('')
        return None
    except Exception:  # noqa: BLE001
        say(traceback.format_exc())
        finish('исключение, см. журнал')
        return None


bpy.app.timers.register(tick, first_interval=2.0)
