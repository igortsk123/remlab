"""ДРАЙВЕР StableGen БЕЗ ОКНА (T-20261119-90/5, этап 1). Запускается ВНУТРИ Blender (не `-b`: модальные операторы аддона тикают только в цикле окна):
  xvfb-run -a blender --factory-startup --python-use-system-env --python sg_drive.py -- <config.json>
Аддон не имеет готового пакетного режима (генерация — модальный оператор на таймере окна, `texturing/generator.py`), поэтому этот скрипт по таймеру (`bpy.app.timers`) ведёт шаги и ждёт,
пока `sg_modal_active` станет ложью:  импорт формы → пресет и настройки → камеры (`object.add_cameras`) → генерация (`object.test_stable`, ComfyUI на дальнем сервере) → запекание в НАШУ
развёртку (`object.bake_textures`, `try_unwrap=none`) → экспорт GLB. Форма и UV НЕ меняются. Ход пишется в `<out>/drive.log` и `<out>/status.json`.
Конфиг (JSON): glb, out, server ("127.0.0.1:8189"), preset ("QWEN PRECISE"|"QWEN SAFE"|…), prompt, cameras {mode,num}, texture_resolution, seed, style_image (путь к фото-образцу или null),
model_unet (имя GGUF, если не первое в списке), lora_name (другая Lightning-LoRA, для 2511), bake_samples, stop_after ("cameras"|"generate"|null), timeout_s."""
import json
import math
import os
import re
import sys
import time
import traceback

import addon_utils
import bpy
import importlib
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sg_views  # noqa: E402

ADDON = 'bl_ext.user_default.stablegen'


def sg(mod):
    return importlib.import_module(f'{ADDON}.{mod}')


ARGS = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
CFG = json.load(open(ARGS[0], encoding='utf-8'))
OUT = CFG['out']
os.environ['SG_MEGAPIXELS'] = str(CFG.get('megapixels', 1))      # размер видов для Qwen (в аддоне зашито 1 Мп; наша копия аддона читает эту переменную)
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


def _mask_norm(mask, h_out=96, w_out=384):
    """Силуэт → канон для сравнения: обрезка по рамке, масштаб с сохранением пропорций, по центру холста h_out×w_out (nearest)."""
    ys, xs = np.nonzero(mask)
    if len(ys) == 0:
        return np.zeros((h_out, w_out), bool)
    m = mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    s = min(h_out / m.shape[0], w_out / m.shape[1])
    hh, ww = max(1, int(round(m.shape[0] * s))), max(1, int(round(m.shape[1] * s)))
    yi = (np.arange(hh) / s).astype(int).clip(0, m.shape[0] - 1)
    xi = (np.arange(ww) / s).astype(int).clip(0, m.shape[1] - 1)
    out = np.zeros((h_out, w_out), bool)
    y0, x0 = (h_out - hh) // 2, (w_out - ww) // 2
    out[y0:y0 + hh, x0:x0 + ww] = m[np.ix_(yi, xi)]
    return out


def pick_seed_camera(sc, cams, photo_path, tmp_dir, prior_dir=(0.0, -1.0, 0.0), centre=None):
    """Камера, силуэт предмета с которой лучше всего совпадает с силуэтом фото (IoU по канону). Рендер — Workbench, маленький, без света.
    Возвращает (имя, {имя: IoU}, уверенно). Если среди равных по силуэту (в пределах SEED_TIE) есть камера из противоположной полусферы (перёд/зад неразличимы) → решает близость к «prior_dir» (−Y), уверенно=False."""
    old = (sc.render.engine, sc.render.resolution_x, sc.render.resolution_y, sc.render.resolution_percentage, sc.render.film_transparent, sc.render.filepath, sc.camera)
    img = bpy.data.images.load(photo_path)
    pw, ph = img.size
    pa = np.array(img.pixels[:], dtype=np.float32).reshape(ph, pw, 4)[::-1, :, 3] > 0.5
    ref = _mask_norm(pa)
    sc.render.engine = 'BLENDER_WORKBENCH'
    sc.render.film_transparent = True
    sc.render.resolution_percentage = 100
    sc.render.resolution_x, sc.render.resolution_y = 320, 280
    scores = {}
    os.makedirs(tmp_dir, exist_ok=True)
    for c in sorted(cams, key=lambda o: sg_views.natural_key(o.name)):
        sc.camera = c
        p = os.path.join(tmp_dir, f'sil-{c.name}.png')
        sc.render.filepath = p
        bpy.ops.render.render(write_still=True)
        im = bpy.data.images.load(p)
        w, h = im.size
        a = np.array(im.pixels[:], dtype=np.float32).reshape(h, w, 4)[::-1, :, 3] > 0.5
        m = _mask_norm(a)
        scores[c.name] = round(float((m & ref).sum() / max(1, (m | ref).sum())), 4)
    (sc.render.engine, sc.render.resolution_x, sc.render.resolution_y, sc.render.resolution_percentage, sc.render.film_transparent, sc.render.filepath, sc.camera) = old
    dirs = {c.name: ((c.location - centre).x, (c.location - centre).y) for c in cams} if centre is not None else {}
    seed, sure = sg_views.choose_seed(scores, dirs, prior_dir)
    return seed, scores, sure


def install_back_hook(info):
    """T-90/10: перехват генерации кадра Qwen: виду «строго сзади» — без фото магазина (no_photo) или с образцом = готовый вид бока (side_sample).
    Правило по углу от зерна (см. sg_views.back_cameras); флаги сцены на время вызова и возвращаются."""
    wf = sg('workflows')
    cls = wf.WorkflowManager
    orig = cls.generate_qwen_edit
    if getattr(orig, '_back_hook', False):
        return

    def hooked(self, context, camera_id=None):
        op = self.operator
        sc = context.scene
        name = op._cameras[op._current_image].name
        if name not in info['cameras'] or op._current_image == 0:
            return orig(self, context, camera_id=camera_id)
        saved = (sc.qwen_external_style_initial_only, sc.qwen_external_style_image, sc.sequential_ipadapter)
        try:
            if info['mode'] == 'no_photo':
                sc.qwen_external_style_initial_only = True
                say(f'вид {name}: фото магазина НЕ даём (только подпись и готовый контекст)')
            elif info['mode'] == 'side_sample' and info.get('sample_index') is not None:
                import glob
                fs = glob.glob(os.path.join(OUT, 'sg-output', '**', 'generated', f"generated_image{info['sample_index']}-0-0001.png"), recursive=True)
                if fs:
                    sc.qwen_external_style_image = fs[0]
                    say(f"вид {name}: вместо фото магазина — готовый вид бока {info['sample']} ({fs[0]})")
                else:
                    raise RuntimeError(f"образец бока {info['sample']} не найден — зад не генерируем")
            return orig(self, context, camera_id=camera_id)
        finally:
            sc.qwen_external_style_initial_only, sc.qwen_external_style_image, sc.sequential_ipadapter = saved
    hooked._back_hook = True
    cls.generate_qwen_edit = hooked


def apply_view_prompts(sc, bb, front, cat_role, seed_name):
    """Своя подсказка каждому виду: коллекция `scene.camera_prompts` + `use_camera_prompts` (аддон ставит её ПЕРЕД общим промптом). Возвращает ({камера: текст}, {камера: мета}, флаги)."""
    from mathutils import Vector
    ctr = sum(bb, Vector()) / 8
    out, metas, flags = {}, {}, []
    sc.camera_prompts.clear()
    for c in sorted([o for o in sc.objects if o.type == 'CAMERA'], key=lambda o: sg_views.natural_key(o.name)):
        text, meta = sg_views.view_text(cat_role, tuple(c.location - ctr), tuple(front), is_seed=(c.name == seed_name))
        item = sc.camera_prompts.add()
        item.name = c.name
        item.prompt = text
        out[c.name], metas[c.name] = text, meta
        if not meta['known'] and 'unknown_role' not in flags:
            flags.append('unknown_role')
    sc.use_camera_prompts = True
    return out, metas, flags


def server_info(server: str) -> dict:
    import urllib.request
    try:
        with urllib.request.urlopen(urllib.request.Request(f'http://{server}/info', headers={'User-Agent': 'remlab-mesh/1.0'}), timeout=15) as r:
            d = json.loads(r.read() or b'{}')
            return {k: d.get(k) for k in ('backend', 'gpu', 'vram_total', 'weights_gb')} if isinstance(d, dict) else {}
    except Exception as e:  # noqa: BLE001 — нет /info (например fake_comfy) = «не воркер»
        return {'error': str(e)[:120]}


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
    yield 'server-identity'
    info = server_info(CFG['server'])                      # кто отвечает по адресу: воркер пода/ноды (/info с backend и картой) или чужой/поддельный сервер
    ST['server_info'] = info
    say(f'сервер {CFG["server"]}: {info}')
    if CFG.get('require_worker') and not (info.get('backend') and info.get('gpu')):
        raise RuntimeError(f'по адресу {CFG["server"]} отвечает не воркер пода (/info: {info}) — генерацию не начинаю (уроки 20.11: чужой fake_comfy на порту моста)')
    save_status()
    yield 'refresh-lists'
    sc.model_architecture = CFG.get('architecture', 'qwen_image_edit')
    sg_state = sg('core.state')
    bpy.ops.stablegen.refresh_checkpoint_list()
    bpy.ops.stablegen.refresh_lora_list()
    t_ref = time.time()
    while getattr(sg_state, '_pending_refreshes', 0) > 0 and time.time() - t_ref < 60:
        yield 'wait-refresh'
    while getattr(sg_state, '_cached_lora_list', [('NONE_AVAILABLE',)])[0][0] in ('NONE_AVAILABLE', 'NO_SERVER') and time.time() - t_ref < 90:
        yield 'wait-lora-list'                       # ответ на список LoRA приходит фоном; сервер далеко (прокси) — ждём, пока не придёт
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
    if CFG.get('no_lora'):                                # опыт «без Lightning»: обычные шаги/cfg из scene_props
        sc.lora_units.clear()
        say('LoRA-юниты убраны (без Lightning)')
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
    if CFG.get('fit_cameras', True):                      # T-90/6: орбитальное кольцо берёт радиус от камеры «окна просмотра» (≈18 м) — предмет 1 м занимал ≈10 % кадра; подгонка аддона — по силуэту с запасом 10 %
        for o in bpy.context.scene.objects:
            o.select_set(False)
        with bpy.context.temp_override(**view3d_override()):
            r = bpy.ops.object.apply_auto_aspect('EXEC_DEFAULT')
        say(f'подгонка камер по силуэту (apply_auto_aspect): {r}')
        bpy.context.view_layer.update()
    from bpy_extras.object_utils import world_to_camera_view
    from mathutils import Vector
    bb = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    ST['framing'] = []
    for c in sorted([o for o in bpy.context.scene.objects if o.type == 'CAMERA'], key=lambda o: o.name):
        pts = [world_to_camera_view(bpy.context.scene, c, p) for p in bb]
        w, h = max(p.x for p in pts) - min(p.x for p in pts), max(p.y for p in pts) - min(p.y for p in pts)
        dist = (c.location - Vector(sum(bb, Vector()) / 8)).length
        ST['framing'].append({'cam': c.name, 'dist': round(dist, 2), 'w': round(w, 3), 'h': round(h, 3)})
        say(f'кадрирование {c.name}: расстояние {dist:.2f}, bbox занимает {w * 100:.0f} % ширины и {h * 100:.0f} % высоты кадра')
    save_status()
    if CFG.get('view_prompts'):                           # T-90/7 ⑪: зерно по силуэту фото → порядок обхода → тексты видов по классу роли и зоне от «переда» (= направление зерна)
        scn = bpy.context.scene
        cams_all = [o for o in scn.objects if o.type == 'CAMERA']
        ctr = sum(bb, Vector()) / 8
        seed, scores, sure = pick_seed_camera(scn, cams_all, CFG['style_image'], os.path.join(OUT, 'seed-sil'), centre=ctr)
        ST['seed'] = {'camera': seed, 'iou': scores, 'confident': sure}
        say(f'зерно (камера передней полусферы с лучшим IoU силуэта): {seed}; IoU {scores}; {"лучший по IoU — и так спереди" if sure else "лучший по IoU был вне передней полусферы — взято лучшее внутри неё (допущение −Y = лицо формы)"}')
        sv = next(c for c in cams_all if c.name == seed)
        fv = sv.location - ctr
        front = CFG.get('front_vec') or (fv.x, fv.y, 0.0)
        if CFG.get('order_mode') == 'alternating':           # T-90/9 (T5c): зерно → ±45 → ±90 → ±135 → 180 по углам от переда, зад последним
            order = sg_views.alternating_order({c.name: (c.location.x - ctr.x, c.location.y - ctr.y) for c in cams_all}, front, seed)
        else:
            order = sg_views.camera_order([c.name for c in cams_all], seed)
        dirs_ = {c.name: (c.location.x - ctr.x, c.location.y - ctr.y) for c in cams_all}
        back_ = sg_views.back_cameras(dirs_, front, CFG.get('back_limit', sg_views.BACK_LIMIT_DEG)) if CFG.get('back_mode') else []
        if back_:
            ST['back'] = {'mode': CFG['back_mode'], 'cameras': back_}
            if CFG['back_mode'] == 'drop':                    # T5d: камеры строго сзади нет вовсе — зад красится из ±135
                for n_ in back_:
                    bpy.data.objects.remove(bpy.data.objects[n_], do_unlink=True)
                order = [n_ for n_ in order if n_ not in back_]
                cams_all = [o for o in scn.objects if o.type == 'CAMERA']
                cams = list(cams_all)
                ST['cameras'] = len(cams)
                say(f'камеры строго сзади убраны: {back_}')
            else:
                if CFG['back_mode'] == 'side_sample':          # T5e: вместо фото магазина — уже сгенерированный вид бока
                    smp_ = sg_views.side_sample_camera(dirs_, front, order)
                    ST['back']['sample'] = smp_
                    ST['back']['sample_index'] = order.index(smp_) if smp_ else None
                install_back_hook(ST['back'])
                say(f'виду сзади {back_}: режим {CFG["back_mode"]}, образец {ST["back"].get("sample")}')
        off = CFG.get('vp_off') or []                        # диагностика: что из ⑪ отключить
        scn.sg_camera_order.clear()
        if 'order' not in off:
            for n_ in order:
                scn.sg_camera_order.add().name = n_
        scn.sg_use_custom_camera_order = 'order' not in off
        ST['order'] = order
        say(f'порядок камер: {order}')
        ST['view_prompts'], ST['view_meta'], flags = apply_view_prompts(scn, bb, front, CFG.get('cat_role', ''), seed)
        if CFG.get('short_side'):                          # T-90/8 (T5): подпись только у видов сбоку/сзади, фронтальные — без подписи (штатный промпт)
            scn.camera_prompts.clear()
            ST['view_prompts'], ST['view_meta'] = {}, {}
            for c_ in sorted([o for o in scn.objects if o.type == 'CAMERA'], key=lambda o: sg_views.natural_key(o.name)):
                text_, meta_ = sg_views.short_side_text(CFG.get('cat_role', ''), tuple(c_.location - ctr), tuple(front), CFG.get('back_suffix', ''))
                ST['view_prompts'][c_.name], ST['view_meta'][c_.name] = text_, meta_
                if text_:
                    scn.camera_prompts.add().name = c_.name
                    scn.camera_prompts[c_.name].prompt = text_
            scn.use_camera_prompts = True
            flags.append('short_side')
        if 'text' in off:
            scn.use_camera_prompts = False
            flags.append('diag_no_view_text')
        if CFG.get('prompt_flags'):
            flags += list(CFG['prompt_flags'])
        if not sure:
            flags.append('seed_forced_to_front_hemisphere')
        ST['flags'] = flags
        for name_ in order:
            say(f"подсказка вида {name_} {ST['view_meta'][name_]}: {ST['view_prompts'][name_]}")
        if flags:
            say(f'ФЛАГИ: {flags}')
        save_status()
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
    import glob
    gen = glob.glob(os.path.join(OUT, 'sg-output', '**', 'generated', 'generated_image*.png'), recursive=True)     # молчаливый отказ сервера аддон не считает ошибкой: без картинок видов дальше нечего запекать
    say(f'картинок видов: {len(gen)} из {len(cams)}')
    if len(gen) < len(cams):
        raise RuntimeError(f'генерация не дала картинок видов: {len(gen)} из {len(cams)} (сервер не ответил? смотри журнал моста)')
    say('генерация завершена')
    if CFG.get('stop_after') == 'generate':
        return

    # 5. запекание в нашу UV
    yield 'bake'
    if CFG.get('bake_margin'):                              # запас запекания (пиксели за краем островка) — против тёмного ободка; в аддоне берётся max(этого, 16)
        bpy.context.scene.render.bake.margin = int(CFG['bake_margin'])
        say(f'запас запекания: {bpy.context.scene.render.bake.margin} px')
    with bpy.context.temp_override(**view3d_override()):
        bpy.ops.object.bake_textures('EXEC_DEFAULT',texture_resolution=int(CFG.get('texture_resolution', 2048)), try_unwrap='none', overlap_only=False,
                                     bake_pbr=False, add_material=True, flatten_for_refine=False, samples=int(CFG.get('bake_samples', 16)),
                                     use_denoise=bool(CFG.get('bake_denoise', True)))      # шумоподавление запекания темнит кромки островков (Blender T94573); по умолчанию — как в аддоне (вкл.)
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
