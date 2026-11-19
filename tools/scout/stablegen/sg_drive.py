"""ДРАЙВЕР StableGen БЕЗ ОКНА (T-20261119-90/5, этап 1). Запускается ВНУТРИ Blender (не `-b`: модальные операторы аддона тикают только в цикле окна):
  xvfb-run -a blender --factory-startup --python-use-system-env --python sg_drive.py -- <config.json>
Аддон не имеет готового пакетного режима (генерация — модальный оператор на таймере окна, `texturing/generator.py`), поэтому этот скрипт по таймеру (`bpy.app.timers`) ведёт шаги и ждёт,
пока `sg_modal_active` станет ложью:  импорт формы → пресет и настройки → камеры (`object.add_cameras`) → генерация (`object.test_stable`, ComfyUI на дальнем сервере) → запекание в НАШУ
развёртку (`object.bake_textures`, `try_unwrap=none`) → экспорт GLB. Форма и UV НЕ меняются. Ход пишется в `<out>/drive.log` и `<out>/status.json`.
Конфиг (JSON): glb, out, server ("127.0.0.1:8189"), preset ("QWEN PRECISE"|"QWEN SAFE"|…), prompt, cameras {mode,num}, texture_resolution, seed, style_image (путь к фото-образцу или null),
model_unet (имя GGUF, если не первое в списке), lora_name (другая Lightning-LoRA, для 2511), bake_samples, stop_after ("cameras"|"generate"|null), timeout_s."""
import json
import os
import sys
import time
import traceback

import addon_utils
import bpy
import importlib

ADDON = 'bl_ext.user_default.stablegen'


def sg(mod):
    return importlib.import_module(f'{ADDON}.{mod}')


ARGS = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
CFG = json.load(open(ARGS[0], encoding='utf-8'))
OUT = CFG['out']
os.makedirs(OUT, exist_ok=True)
LOG = open(os.path.join(OUT, 'drive.log'), 'a', encoding='utf-8')
T0 = time.time()
ST = {'stage': 'init', 'error': '', 'done': False, 'steps': []}


def say(msg):
    line = f'{time.time() - T0:7.1f}s  {msg}'
    print('[drive]', line, flush=True)
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
    """Контекст окна с 3D-видом: операторы камер берут из него `region_data`."""
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
    prefs.server_address = CFG['server']
    bpy.context.preferences.system.use_online_access = True    # аддон ходит на сервер ComfyUI по сети; без этого poll оператора отказывает
    os.makedirs(os.path.join(OUT, 'sg-output'), exist_ok=True)
    prefs.output_dir = os.path.join(OUT, 'sg-output')      # аддон пишет сюда картинки видов, карты глубины и контекст — по ним потом разбор
    sc = bpy.context.scene

    # 1. форма
    yield 'import'
    for o in list(bpy.data.objects):                        # стандартная сцена Blender: куб, камера, лампа — убрать
        bpy.data.objects.remove(o, do_unlink=True)
    bpy.ops.import_scene.gltf(filepath=CFG['glb'])
    meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
    if len(meshes) != 1:
        raise RuntimeError(f'ожидался один меш, найдено {len(meshes)}')
    obj = meshes[0]
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    ST['mesh'] = {'name': obj.name, 'verts': len(obj.data.vertices), 'faces': len(obj.data.polygons), 'uv_layers': [u.name for u in obj.data.uv_layers]}
    say(f"форма: {ST['mesh']}")
    # слой нашей развёртки называем так, как аддон ищет для запекания
    if obj.data.uv_layers and 'BakeUV' not in obj.data.uv_layers:
        obj.data.uv_layers[0].name = 'BakeUV'
    bpy.context.view_layer.update()

    # 2. настройки: сперва списки моделей с сервера (энум-списки аддон заполняет фоновыми запросами)
    yield 'refresh-lists'
    sc.model_architecture = CFG.get('architecture', 'qwen_image_edit')
    sg_state = sg('core.state')
    bpy.ops.stablegen.refresh_checkpoint_list()
    bpy.ops.stablegen.refresh_lora_list()
    t_ref = time.time()
    while getattr(sg_state, '_pending_refreshes', 0) > 0 and time.time() - t_ref < 60:
        yield 'wait-refresh'
    say(f"списки: LoRA {getattr(sg_state, '_cached_lora_list', None)}")
    yield 'settings'
    sc.stablegen_preset = CFG['preset']
    bpy.ops.stablegen.apply_preset()
    sc.comfyui_prompt = CFG['prompt']
    sc.seed = int(CFG.get('seed', 42))
    if CFG.get('style_image'):
        sc.qwen_use_external_style_image = True
        sc.qwen_external_style_image = CFG['style_image']
    for k, v in (CFG.get('scene_props') or {}).items():
        setattr(sc, k, v)
    if CFG.get('model_unet'):
        sc.model_name = CFG['model_unet']
    if CFG.get('lora_name') and len(sc.lora_units):      # Qwen-Image-Edit-2511: пресет кладёт LoRA от 2509 — подменяем на свою Lightning-LoRA (`lightx2v/Qwen-Image-Edit-2511-Lightning`)
        sc.lora_units[0].model_name = CFG['lora_name']
        say(f'LoRA: {sc.lora_units[0].model_name}')
    say(f"архитектура {sc.model_architecture}, метод {sc.generation_method}, модель {sc.model_name!r}")

    # 3. камеры
    yield 'cameras'
    cam = CFG.get('cameras', {})
    with bpy.context.temp_override(**view3d_override()):
        bpy.ops.object.add_cameras('EXEC_DEFAULT', placement_mode=cam.get('mode', 'orbit_ring'), num_cameras=int(cam.get('num', 8)), center_type='object', review_placement=False)
    while busy():
        yield 'wait-cameras'
    cams = [o for o in bpy.context.scene.objects if o.type == 'CAMERA']
    ST['cameras'] = len(cams)
    say(f'камер: {len(cams)}')
    if not cams:
        raise RuntimeError('камеры не созданы')
    if CFG.get('stop_after') == 'cameras':
        return

    # 4. генерация
    yield 'generate'
    for o in list(bpy.context.scene.objects):
        o.select_set(o == obj)
    bpy.context.view_layer.objects.active = obj
    with bpy.context.temp_override(**view3d_override()):
        bpy.ops.object.test_stable('INVOKE_DEFAULT')
    n = 0
    while busy():
        n += 1
        if n % 40 == 0:
            say('генерация идёт…')
        yield 'wait-generate'
    err = getattr(sg('texturing.generator').ComfyUIGenerate, '_error', None)
    if err:
        raise RuntimeError(f'генерация: {err}')
    say('генерация завершена')
    if CFG.get('stop_after') == 'generate':
        return

    # 5. запекание в нашу UV
    yield 'bake'
    with bpy.context.temp_override(**view3d_override()):
        bpy.ops.object.bake_textures('EXEC_DEFAULT',texture_resolution=int(CFG.get('texture_resolution', 2048)), try_unwrap='none', overlap_only=False,
                                     bake_pbr=False, add_material=True, flatten_for_refine=False, samples=int(CFG.get('bake_samples', 16)))
    n = 0
    while busy():
        n += 1
        if n % 40 == 0:
            say('запекание идёт…')
        yield 'wait-bake'
    say('запекание завершено')

    # 6. экспорт
    yield 'export'
    glb = os.path.join(OUT, 'painted.glb')
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.ops.export_scene.gltf(filepath=glb, export_format='GLB', use_selection=True, export_image_format='AUTO')
    ST['glb'] = glb
    ST['glb_bytes'] = os.path.getsize(glb)
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, 'session.blend'))
    say(f'экспорт: {glb} ({ST["glb_bytes"]} байт)')


GEN = steps()
DEADLINE = T0 + float(CFG.get('timeout_s', 3600))


def tick():
    if ST['done']:
        return None
    if time.time() > DEADLINE:
        finish('таймаут драйвера')
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
    except Exception as exc:  # noqa: BLE001
        say(traceback.format_exc())
        finish(f'{type(exc).__name__}: {exc}')
        return None


bpy.app.timers.register(tick, first_interval=2.0)
