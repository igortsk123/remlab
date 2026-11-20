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
import sg_guard  # noqa: E402
import sg_transient  # noqa: E402
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


SEED_STEP = 7919                                            # сдвиг seed повтора вида (простое число: не пересекается с seed соседних видов)
HOOK_PROPS = ('qwen_external_style_initial_only', 'qwen_external_style_image', 'sequential_ipadapter', 'seed', 'comfyui_prompt', 'qwen_context_render_mode')


def _sample_path(index):
    import glob
    fs = glob.glob(os.path.join(OUT, 'sg-output', '**', 'generated', f'generated_image{index}-0-0001.png'), recursive=True)
    return fs[0] if fs else None


def install_back_hook(info, gi=None):
    """T-90/10: перехват генерации кадра Qwen: виду «строго сзади» — без фото магазина (no_photo) или с образцом = готовый вид бока (side_sample).
    T-154/1: `side_sample_sign` — образец бока по ЗНАКУ угла каждого заднего вида (+135° → +90°, −135° → −90°, 180° → лучший из двух; полное фото фасада задним видам не даём),
    и сторож каждого вида (`gi` — данные сторожа): малиновое / цвет → 1 повтор (другой seed + образец бока) → запасной проход без контекста → иначе вид отклонён и очищен от малинового.
    Правило по углу от зерна (см. sg_views.back_cameras); флаги сцены на время вызова и возвращаются."""
    wf = sg('workflows')
    cls = wf.WorkflowManager
    orig = cls.generate_qwen_edit
    if getattr(orig, '_back_hook', False):
        return
    G = gi['rules'] if gi else None

    def one_try(self, context, camera_id, plan):
        sc = context.scene
        saved = {k: getattr(sc, k) for k in HOOK_PROPS}
        try:
            if plan.get('seed_shift'):
                sc.seed = int(sc.seed) + int(plan['seed_shift'])
            if plan.get('prompt') is not None:
                sc.comfyui_prompt = plan['prompt']
            if plan.get('context_none'):
                sc.qwen_context_render_mode = 'NONE'
            if plan.get('sample_path'):
                sc.qwen_external_style_image = plan['sample_path']
                sc.qwen_external_style_initial_only = False
            elif plan.get('no_photo'):
                sc.qwen_external_style_initial_only = True
            return orig(self, context, camera_id=camera_id)
        finally:
            for k, v in saved.items():
                setattr(sc, k, v)

    def base_plan(idx, name, accepted):
        """План обычной (первой) попытки вида — как раньше + образец бока по знаку угла."""
        plan = {}
        if idx == 0:
            if info.get('photo_prompt'):                       # T-90/11: ПЕРВЫЙ вид (зерно, с фото) — подпись без цвета (фото ведёт; цвет каталога «серит» узор)
                plan['prompt'] = info['photo_prompt']
            return plan
        if gi is not None and CFG.get('prompt_bare'):          # T-154/1: виды без фото — подпись БЕЗ слов рисунка + слово цвета (каталог, а нет его — из фото вида-зерна); слово не «пустое»
            plan['prompt'] = sg_views.add_colour(CFG['prompt_bare'], gi['state'].get('colour_word'), CFG.get('cat_role'), parts=CFG.get('parts_phrase'))
        if name not in info.get('cameras', ()):
            return plan
        mode = info.get('mode')
        if mode == 'no_photo':
            plan['no_photo'] = True
            say(f'вид {name}: фото магазина НЕ даём (только подпись и готовый контекст)')
        elif mode == 'side_sample' and info.get('sample_index') is not None:
            p = _sample_path(info['sample_index'])
            if not p:
                raise RuntimeError(f"образец бока {info['sample']} не найден — зад не генерируем")
            plan['sample_path'] = p
            say(f"вид {name}: вместо фото магазина — готовый вид бока {info['sample']} ({p})")
        elif mode == 'side_sample_sign':
            smp = sg_views.side_sample_for(gi['angles'][name], gi['angles'], gi['order'], set(accepted))
            if smp:
                plan['sample_path'] = _sample_path(gi['order'].index(smp))
            if plan.get('sample_path'):
                plan['sample_name'] = smp
                say(f"вид {name}: образец материала — готовый вид бока {smp} (знак угла {gi['angles'][name]:+.0f}°), фото фасада не даём")
            else:
                plan['no_photo'] = True
                say(f'вид {name}: подходящего принятого бока нет — без образца (только подпись и контекст)')
        return plan

    def next_plan(attempt, plans, ok_m, ok_c, idx, name):
        """План следующей попытки после провала `attempt` (None — попыток больше нет). Повтор: другой seed + образец бока (заднему виду; и любому при малиновом) + у вида-зерна, ушедшего от цвета каталога, подпись С цветом;
        запасной проход (данные none_fallback): тот же повтор, но без контекста-с-заливкой — малиновому в нём неоткуда взяться."""
        if attempt == 0 and int(G['retries']) >= 1:
            retry = dict(plans[0], seed_shift=SEED_STEP)
            if name in info.get('cameras', ()) or not ok_m:
                smp = sg_views.side_sample_for(gi['angles'][name], gi['angles'], gi['order'], set(gi['state']['accepted']))
                p = _sample_path(gi['order'].index(smp)) if smp else None
                if p:
                    retry.update(sample_path=p, sample_name=smp)
                    retry.pop('no_photo', None)
            if not ok_c and idx == 0 and info.get('photo_prompt'):
                retry['prompt'] = gi['full_prompt']
            return retry
        if attempt >= 1 and not ok_m and G.get('none_fallback') and not any(p.get('context_none') for p in plans):
            return dict(plans[-1], seed_shift=2 * SEED_STEP, context_none=True)
        return None

    def hooked(self, context, camera_id=None):
        op = self.operator
        idx = op._current_image
        name = op._cameras[idx].name
        if gi is None:                                          # прежнее поведение (T-90/10, T-90/11) — без сторожа
            return one_try(self, context, camera_id, base_plan(idx, name, ()))
        st = gi['state']
        rec = st['views'].setdefault(name, {'idx': idx, 'attempts': []})
        plans = [base_plan(idx, name, st['accepted'])]
        attempt = 0
        while True:
            res = one_try(self, context, camera_id, plans[attempt])
            if not isinstance(res, (bytes, bytearray)):         # {"error": "conn_failed"} и т.п. — не наше дело: аддон сам остановит прогон
                return res
            rgb = sg_guard.decode(bytes(res))
            sts = sg_guard.view_stats(rgb, G)
            ok_m, why_m = sg_guard.judge_magenta(sts, G, baseline=st['baseline'], exempt=gi['exempt'])
            nb = gi_neighbour(name, st, gi, G)
            ok_c, why_c, info_c = sg_guard.judge_colour(sts, G, neighbour_lab=nb if idx > 0 else None, catalog=gi['catalog_lab'] if idx == 0 else None)
            ok = ok_m and ok_c
            rec['attempts'].append({'try': attempt, 'plan': {k: v for k, v in plans[attempt].items() if k in ('seed_shift', 'context_none', 'no_photo', 'sample_name')}, 'mag_frac': sts['mag_frac'], 'comp_frac': sts['comp_frac'], **info_c, 'ok': ok, 'why': why_m or why_c})
            say(f"сторож вида {name} (попытка {attempt}): малиновое {sts['mag_frac'] * 100:.1f} %, кусок {sts['comp_frac'] * 100:.2f} %, {info_c or 'цвет не сверялся'} → {'годен' if ok else 'НЕ годен: ' + (why_m or why_c)}")
            if ok:
                break
            os.makedirs(os.path.join(OUT, 'guard'), exist_ok=True)         # неудачные попытки — для разбора (чистятся в sg_queue.slim_run, если вид не отклонён)
            with open(os.path.join(OUT, 'guard', f'{name}-try{attempt}.png'), 'wb') as fh:
                fh.write(bytes(res))
            nxt = next_plan(attempt, plans, ok_m, ok_c, idx, name)
            if nxt is None:
                break
            plans.append(nxt)
            attempt += 1
            say(f"вид {name}: повтор {attempt} ({ {k: v for k, v in nxt.items() if k != 'sample_path'} })")
        if attempt:
            st['views_retried'].append(name)
        if ok:
            rec['result'] = 'accepted' if attempt == 0 else 'accepted_after_retry'
        elif not ok_m:                                          # малиновое осталось после всех попыток — вид отклонён: заливку заменяем цветом соседа, чтобы она не попала в проекцию и контекст
            rec['result'] = 'rejected'
            st['views_rejected'].append(name)
            fill = nb if nb is not None else next((a['lab'] for a in st['accepted'].values() if a.get('lab')), None)
            if fill is not None:
                res = sg_guard.encode_png(sg_guard.repair_magenta(rgb, G, fill))
                rec['repaired_with_neighbour_colour'] = True
            say(f"!! вид {name} ОТКЛОНЁН (малиновое не ушло за {attempt + 1} попыток) — " + ('малиновые пиксели заменены цветом соседа' if fill is not None else 'соседей для замены нет'))
        else:                                                   # только цвет не сошёлся: малинового нет, вид не «заражает» — принимаем, но помечаем
            rec['result'] = 'colour_unresolved'
            st['colour_unresolved'].append(name)
        if rec['result'] != 'rejected':
            st['accepted'][name] = {'lab': sts['lab'], 'mag': sts['mag_frac']}
            if idx == 0:
                st['baseline'] = sts['mag_frac']
                st['catalog_dE'] = (rec['attempts'][-1].get('dE_catalog'))
                pw, pd_ = sg_guard.photo_colour_word(sts, G)
                cw = st.get('colour_word_catalog')
                if cw and (gi['catalog_lab'] is None or rec['result'] != 'colour_unresolved'):
                    st['colour_word'], st['colour_source'] = cw, 'catalog'      # цвет каталога сошёлся с видом-зерном (или проверить нечем, напр. дерево)
                elif pw:
                    st['colour_word'], st['colour_source'] = pw, 'photo' if not cw else 'photo (зерно не сошлось с каталогом)'    # слова нет, либо перёд по фото ушёл от слова — зад берёт цвет перёда
                else:
                    st['colour_word'], st['colour_source'] = cw, 'catalog' if cw else 'none'
                st['photo_colour'] = {'word': pw, 'dE_to_word': pd_}
                say(f"слово цвета для видов без фото: {st['colour_word']!r} (источник: {st['colour_source']}; из фото: {pw!r} ΔE {pd_}; каталог: {cw!r})")
        return res
    hooked._back_hook = True
    cls.generate_qwen_edit = hooked


def gi_neighbour(name, st, gi, G):
    """Медианный Lab ближайшего (по углу) ПРИНЯТОГО вида в пределах `overlap_max_angle` — для сверки цвета в перекрытии; нет — None."""
    best, key = None, None
    for n, a in st['accepted'].items():
        if a.get('lab') is None or n == name:
            continue
        d = abs(gi['angles'][n] - gi['angles'][name])
        d = min(d, 360.0 - d)
        if d <= G['colour']['overlap_max_angle'] and (key is None or d < key):
            best, key = a['lab'], d
    return best


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
    if not obj.data.uv_layers:                              # T-90/11: без развёртки запекание не кончается (55 мин вместо 4) — стоп ДО генерации, платный под не греем; форму прогнать через sg_prep_shape.py
        raise RuntimeError('форма без развёртки (uv_layers пуст): сначала sg_prep_shape.py')
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
    TR = sg_transient.load_rules()                         # T-153/1: краткий сбой связи (сервер не отвечает на списки) — повторяем шаг сами, отказ только после повторов
    ST['server_retries'] = 0
    for attempt in range(TR['drive']['retries'] + 1):
        bpy.ops.stablegen.refresh_checkpoint_list()
        bpy.ops.stablegen.refresh_lora_list()
        t_ref = time.time()
        while getattr(sg_state, '_pending_refreshes', 0) > 0 and time.time() - t_ref < 60:
            yield 'wait-refresh'
        while getattr(sg_state, '_cached_lora_list', [('NONE_AVAILABLE',)])[0][0] in ('NONE_AVAILABLE', 'NO_SERVER') and time.time() - t_ref < (90 if attempt == 0 else 60):
            yield 'wait-lora-list'                       # ответ на список LoRA приходит фоном; сервер далеко (прокси) — ждём, пока не придёт
        if getattr(sg_state, '_cached_lora_list', [('NONE_AVAILABLE',)])[0][0] not in ('NONE_AVAILABLE', 'NO_SERVER') or attempt == TR['drive']['retries']:
            break
        ST['server_retries'] += 1
        p = sg_transient.pause_s(TR, attempt, 'drive')
        say(f"сервер не ответил на списки (повтор {attempt + 1}/{TR['drive']['retries']} через {p:.0f} с): {getattr(sg_state, '_cached_lora_list', None)}")
        save_status()
        t_p = time.time()
        while time.time() - t_p < p:
            yield 'retry-pause'
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
        t_mu = time.time()                                # список моделей приходит фоном и бывает пуст (NONE_FOUND) сразу после «нода готова» (T-154/1, группа gb 20.11) — ждём и переспрашиваем до 120 с
        while True:
            try:
                sc.model_name = CFG['model_unet']
                break
            except TypeError:
                if time.time() - t_mu > 120:
                    raise
                bpy.ops.stablegen.refresh_checkpoint_list()
                t_w = time.time()
                while time.time() - t_w < 6:
                    yield 'wait-model-list'
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
            if CFG.get('photo_no_colour') and CFG['back_mode'] in ('no_photo', 'side_sample_sign'):    # T-90/11: первый вид (с фото) — подпись без цвета, цвет каталога — всем остальным
                ST['back']['photo_prompt'] = sg_views.strip_colour(CFG['prompt'])
                say(f"подпись ПЕРВОГО вида (с фото, без цвета): {ST['back']['photo_prompt']}")
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
                say(f'виду сзади {back_}: режим {CFG["back_mode"]}, образец {ST["back"].get("sample")}')
        gi = None
        if CFG.get('guard'):                                 # T-154/1: сторож каждого вида до проекции и до использования как контекст (rules/stablegen-view-guard.json)
            g_rules = sg_guard.load_rules()
            word = CFG.get('colour')
            ST['guard'] = {'views': {}, 'accepted': {}, 'baseline': 0.0, 'views_retried': [], 'views_rejected': [], 'colour_unresolved': [], 'catalog_dE': None, 'review': '', 'colour_word': word, 'colour_word_catalog': word, 'colour_source': '', 'photo_colour': None}
            gi = {'rules': g_rules, 'angles': {c.name: sg_views.azimuth_deg((c.location.x - ctr.x, c.location.y - ctr.y, 0.0), front) for c in cams_all}, 'order': order,
                  'full_prompt': CFG['prompt'], 'exempt': sg_guard.is_pink_colour(word, g_rules), 'catalog_lab': sg_guard.catalog_lab(word, g_rules), 'state': ST['guard']}
            say(f"сторож видов включён: цвет каталога {word!r}, розовый/фиолетовый цвет каталога (исключение) {gi['exempt']}, сверка с каталогом {'есть' if gi['catalog_lab'] is not None else 'нет (слова нет в справочнике)'}")
        if back_ or gi:
            install_back_hook(ST.get('back') or {'cameras': [], 'mode': None}, gi)
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
    gst = ST.get('guard')
    if gst:                                                  # итоговый сторож модели (T-154/1): основной цвет далёк от цвета каталога — модель автоматически не принимается
        labs = [a['lab'] for a in gst['accepted'].values() if a.get('lab')]
        word_lab = sg_guard.catalog_lab(gst.get('colour_word_catalog'), sg_guard.load_rules())
        if labs and word_lab is not None:
            gst['model_dE_catalog'] = round(sg_guard.delta_e(np.median(np.array(labs), axis=0), word_lab, sg_guard.load_rules()), 1)
            if gst['model_dE_catalog'] > sg_guard.load_rules()['colour']['catalog_max']:
                gst['review'] = f"основной цвет модели далёк от цвета каталога {gst.get('colour_word_catalog')!r}: ΔE {gst['model_dE_catalog']}"
        if len(gst['views_rejected']) * 2 >= len(cams):
            gst['review'] = (gst['review'] + '; ' if gst['review'] else '') + f"отклонено видов {len(gst['views_rejected'])} из {len(cams)}"
        say(f"сторож видов — итог: повторено {gst['views_retried']}, отклонено {gst['views_rejected']}, цвет не сошёлся {gst['colour_unresolved']}, ΔE каталога {gst.get('model_dE_catalog')}, проверка модели: {gst['review'] or 'принимается'}")
        save_status()
    if CFG.get('stop_after') == 'generate':
        return

    # 5. запекание в нашу UV
    yield 'bake'
    try:                                                    # T-90/11 (директор 20.11): запекание под больше не ждёт — отдаём ядра тому, что ждёт оплаченный под (подготовка/приём видов следующего товара): nice 10 и 4 потока
        os.nice(10)
        bpy.context.scene.render.threads_mode = 'FIXED'
        bpy.context.scene.render.threads = int(CFG.get('bake_threads', 4))
    except Exception as e:  # noqa: BLE001
        say(f'приоритет запекания не понижен: {e}')
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
