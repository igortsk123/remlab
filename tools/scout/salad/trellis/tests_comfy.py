#!/usr/bin/env python3
"""Тесты воркера `worker_comfy.py` (официальный TRELLIS.2 в ComfyUI, T-20261119-94/2): сборка workflow-JSON, значения вариантов починки, разбор ответов `/history`, чтение GLB.
Без видеокарты, сети, ключей, torch и без самого ComfyUI (проверка настоящими узлами — `validate_comfy_prompt.py`, вручную на локальном ComfyUI).

  python3 tools/scout/salad/trellis/tests_comfy.py
"""
from __future__ import annotations

import json
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.normpath(os.path.join(HERE, '..', '..')))
import remlab_tmp  # noqa: E402
remlab_tmp.use('tests_comfy')
import worker_comfy as W  # noqa: E402

bad = 0


def ok(name, cond, extra=''):
    global bad
    print(('  ✓ ' if cond else '  ✗ ') + name + (f' — {extra}' if extra and not cond else ''))
    bad += 0 if cond else 1


def raises(fn, exc=ValueError):
    try:
        fn()
    except exc:
        return True
    return False


def refs_ok(wf: dict) -> bool:
    for nid, node in wf.items():
        for v in node['inputs'].values():
            if isinstance(v, list) and len(v) == 2 and isinstance(v[0], str) and isinstance(v[1], int) and v[0] not in wf:
                return False
    return True


print('1. pipeline_type → сетка формы')
ok('1024_cascade → 1024, 1536_cascade → 1536, «1280» тоже', W.res_from_pipeline_type('1024_cascade') == 1024 and W.res_from_pipeline_type('1536_cascade') == 1536 and W.res_from_pipeline_type('1280') == 1280)
ok('500, 1000 (не кратно 128), 4096 и мусор → ValueError', all(raises(lambda x=x: W.res_from_pipeline_type(x)) for x in ('512_cascade', '1000_cascade', '4096_cascade', 'abc')))

print('2. варианты починки: значения по умолчанию и отказы')
ok('нет вариантов → пусто', W.parse_variants([], 1536) == [])
v = W.parse_variants([{'name': 'R1', 'mode': 'udf', 'drop_inverted': True, 'drop_enclosed': True}], 1536)[0]
ok('разрешение remesh по умолчанию = сетке формы (1536), НЕ 512', v['resolution'] == 1536)
ok('по умолчанию: drop_small 0,01, decimate 500000, fill_holes 0,03', v['drop_small'] == 0.01 and v['decimate'] == 500000 and v['fill_holes'] == 0.03)
v2 = W.parse_variants([{'name': 'R2', 'mode': 'solid', 'band': 1.5, 'resolution': 1024}], 1024)[0]
ok('solid: fill 20 по умолчанию, band и разрешение — заданные', v2['fill'] == 20.0 and v2['band'] == 1.5 and v2['resolution'] == 1024)
bad_cases = [[{'name': 'raw'}], [{'name': 'a b'}], [{'name': 'a'}, {'name': 'a'}], [{'name': 'a', 'mode': 'xyz'}], [{'name': 'a', 'resolution': 4000}], [{'name': 'a', 'band': 9}],
             [{'name': 'a', 'oops': 1}], [{'name': 'a', 'project_back': 2}], [{'name': ''}]]
ok('имя raw/ai/пробел/повтор, режим, значения вне диапазона, неизвестный ключ → ValueError', all(raises(lambda b=b: W.parse_variants(b, 1024)) for b in bad_cases))

print('3. workflow: форма как в официальном шаблоне Comfy')
wf = W.build_workflow('job.png', 1536, 7, W.parse_variants([{'name': 'R1', 'mode': 'udf', 'drop_inverted': True, 'drop_enclosed': True}], 1536)[0], True, 'job')
ok('все ссылки [узел, слот] указывают на существующие узлы', refs_ok(wf))
ok('target_resolution = 1536', wf['up']['inputs']['target_resolution'] == 1536)
ok('seed во всех трёх сэмплерах = заданному', all(wf[k]['inputs']['seed'] == 7 for k in ('ks_ss', 'ks_sh', 'ks_hr')))
ok('без RemoveBackground / BiRefNet / текстурной ветки (вырезка своя, краска не нужна)', not any(n['class_type'] in ('RemoveBackground', 'LoadBackgroundRemovalModel', 'Trellis2TextureStage', 'BakeTextureFromVoxel', 'UnwrapMesh') for n in wf.values()))
ok('маска переднего плана = инвертированная LoadImage.MASK (1−альфа → альфа)', wf['fg']['class_type'] == 'InvertMask' and wf['fg']['inputs']['mask'] == ['img', 1] and wf['crop']['inputs']['masks'] == ['fg', 0])
ok('шаги/CFG как в шаблоне: структура 12 шагов, форма 20 + 12 шагов, cfg 7.5', wf['ks_ss']['inputs']['steps'] == 12 and wf['ks_sh']['inputs']['steps'] == 20 and wf['ks_hr']['inputs']['steps'] == 12 and wf['ks_hr']['inputs']['cfg'] == 7.5)
r = wf['remesh']['inputs']
ok('RemeshMesh: разрешение = сетке формы, режим udf, drop_inverted/drop_enclosed включены, drop_small 0,01', r['resolution'] == 1536 and r['sign_mode'] == 'udf' and r['sign_mode.drop_inverted_components'] is True
   and r['sign_mode.drop_enclosed_components'] is True and r['drop_small_components'] == 0.01)
ok('цепочка: mesh → remesh → decimate (500000, midpoint) → fill (0,03) → SaveGLB', wf['decimate']['inputs']['mesh'] == ['remesh', 0] and wf['decimate']['inputs']['target_face_count'] == 500000
   and wf['decimate']['inputs']['placement_mode'] == 'midpoint' and wf['fill']['inputs']['mesh'] == ['decimate', 0] and wf['fill']['inputs']['max_perimeter'] == 0.03 and wf['save']['inputs']['mesh'] == ['fill', 0])
ok('сырая форма сохраняется отдельным SaveGLB прямо с VaeDecodeShapeTrellis', wf['save_raw']['inputs']['mesh'] == ['mesh', 0] and wf['save_raw']['inputs']['filename_prefix'] == 'job/raw')
ok('имя файла варианта: <задание>/<вариант>', wf['save']['inputs']['filename_prefix'] == 'job/R1')
wfs = W.build_workflow('job.png', 1024, 42, W.parse_variants([{'name': 'R2', 'mode': 'solid', 'band': 1.5}], 1024)[0], False, 'job')
ok('solid: sign_mode.fill = 20, band 1,5, без сырой формы во втором запросе', wfs['remesh']['inputs']['sign_mode'] == 'solid' and wfs['remesh']['inputs']['sign_mode.fill'] == 20.0 and wfs['remesh']['inputs']['band'] == 1.5 and 'save_raw' not in wfs)
ok('solid: ключей udf нет', 'sign_mode.drop_inverted_components' not in wfs['remesh']['inputs'] and refs_ok(wfs))
wfn = W.build_workflow('job.png', 1024, 42, W.parse_variants([{'name': 'N', 'mode': 'none', 'decimate': 0, 'fill_holes': 0}], 1024)[0], False, 'job')
ok('mode none + decimate 0 + fill 0: SaveGLB прямо с формы, remesh/decimate/fill нет', 'remesh' not in wfn and 'decimate' not in wfn and 'fill' not in wfn and wfn['save']['inputs']['mesh'] == ['mesh', 0])
ok('только форма: без variant и без raw — SaveGLB нет, но граф цел', 'save' not in W.build_workflow('j.png', 1024, 1, None, False, 'j') and refs_ok(W.build_workflow('j.png', 1024, 1, None, False, 'j')))
ok('workflow сериализуется в JSON', bool(json.dumps(wf)))

print('4. ответы ComfyUI: /history')
hist_ok = {'status': {'status_str': 'success', 'completed': True, 'messages': []}, 'outputs': {'save': {'3d': [{'filename': 'R1_00001_.glb', 'subfolder': 'job', 'type': 'output'}]}, 'x': {'images': 'nope'}}}
hist_err = {'status': {'status_str': 'error', 'messages': [['execution_start', {}], ['execution_error', {'node_type': 'RemeshMesh', 'exception_type': 'OutOfMemoryError', 'exception_message': 'CUDA out of memory'}]]}, 'outputs': {}}
ok('saved_files: берёт списки с filename, пропускает остальное', W.saved_files(hist_ok) == [{'filename': 'R1_00001_.glb', 'subfolder': 'job', 'type': 'output'}])
ok('history_state: success / error с текстом узла', W.history_state(hist_ok) == ('success', None) and W.history_state(hist_err)[0] == 'error' and 'RemeshMesh' in (W.history_state(hist_err)[1] or '') and 'out of memory' in (W.history_state(hist_err)[1] or ''))
ok('history_state: пока идёт', W.history_state({'status': {'completed': False, 'messages': []}})[0] == 'running')

print('5. чтение GLB')


def tiny_glb(nv: int, nt: int) -> bytes:
    js = json.dumps({'asset': {'version': '2.0'}, 'accessors': [{'count': nv}, {'count': nt * 3}], 'meshes': [{'primitives': [{'attributes': {'POSITION': 0}, 'indices': 1}]}]}).encode()
    js += b' ' * (-len(js) % 4)
    return b'glTF' + struct.pack('<II', 2, 12 + 8 + len(js)) + struct.pack('<II', len(js), 0x4E4F534A) + js


ok('glb_stats: вершины и треугольники', W.glb_stats(tiny_glb(1234, 567)) == {'verts': 1234, 'tris': 567})
ok('glb_stats: не GLB → ValueError', raises(lambda: W.glb_stats(b'not a glb at all, sorry')))

print('6. воркер: контракт и безопасность')
src = open(os.path.join(HERE, 'worker_comfy.py'), encoding='utf-8').read()
ok('веса — только публичные репозитории Comfy-Org, bf16 (не int8)', all(r.startswith('Comfy-Org/') for r, _, _ in W.WEIGHTS) and 'int8' not in src.split('WEIGHTS = [')[1].split(']')[0] and W.UNET == 'trellis_2_bf16.safetensors')
ok('HF_TOKEN в запросы за весами не уходит', 'HF_TOKEN' not in src and 'Authorization' not in src)
ok('ComfyUI слушает только 127.0.0.1 и без партнёрских узлов', "'--listen', '127.0.0.1'" in src and '--disable-partner-nodes' in src)
ok('по умолчанию разрешение remesh не 512: в коде нет числа 512 как значения по умолчанию', "'resolution', grid" in src)

print('7. драйвер: модель comfy, вход hdc')
import base64
import tempfile
import zlib
import trellis_trial as T  # noqa: E402
body = T.build_body('trial-comfy-x', 'ghcr.io/o/mesh-comfy-trial:trellis2-0460', 'high', 'comfy', 'hf_SECRET', 4, 30000, 'note', {})
env = body['container']['environment_variables']
ok('группа comfy: токен Hugging Face в окружение НЕ попадает (веса публичные)', 'HF_TOKEN' not in env and 'hf_SECRET' not in json.dumps(body))
ok('группа comfy: код воркера едет в TRIAL_WORKER_Z и это worker_comfy.py', 'ComfyUI' in zlib.decompress(base64.b64decode(env['TRIAL_WORKER_Z'])).decode() and body['container']['command'][0] == 'python3')
ok('группа comfy: образ как задан, MODEL=comfy', body['container']['image'].endswith('trellis2-0460') and env['MODEL'] == 'comfy')
lad = os.path.join(tempfile.gettempdir(), 'tests_comfy_ladder.json')
json.dump([{'name': 'hdc1024', 'input': 'hdc', 'res': 1024, 'variants': [{'name': 'R1', 'mode': 'udf'}]}], open(lad, 'w'))
pl = T.parse_ladder(lad)
ok('лесенка: input hdc принимается, variants едут в параметры задания', pl[0]['input'] == 'hdc' and pl[0]['params']['variants'][0]['name'] == 'R1')
jobs = T.expand_ladder_jobs([{'sku': '1:2', 'job_id': 'x', 'res': 1024}], pl)
ok('задание: id <товар>-<ступень>, input hdc', jobs[0]['job_id'] == '1_2-hdc1024' and jobs[0]['input'] == 'hdc')
bad_in = os.path.join(tempfile.gettempdir(), 'tests_comfy_ladder_bad.json')
json.dump([{'name': 'a', 'input': 'zzz'}], open(bad_in, 'w'))
json.dump([{'name': 'k', 'input': 'clean', 'res': 1024}], open(lad, 'w'))
ok('лесенка: input clean (чистая вырезка) принимается', T.parse_ladder(lad)[0]['input'] == 'clean')
ok('лесенка: неизвестный input → ValueError до группы', raises(lambda: T.parse_ladder(bad_in)))

print(f'\nИТОГО: {"всё в норме" if not bad else f"упало {bad}"}')
sys.exit(1 if bad else 0)
