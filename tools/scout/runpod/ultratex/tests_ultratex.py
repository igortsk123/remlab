#!/usr/bin/env python3
"""Тесты воркера пробы UltraTex (T-20261119-90/2) БЕЗ видеокарты и без сети.
  python tools/scout/runpod/ultratex/tests_ultratex.py
Нужны numpy и PIL; раздел «рендер/развёртка» пропускается без moderngl+EGL, trimesh или xatlas (в образе он идёт)."""
from __future__ import annotations

import base64
import json
import os
import sys
import tempfile
import threading
import types
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import numpy as np                                             # noqa: E402

import worker_ultratex as W                                    # noqa: E402

FAILS = []


def ok(cond, msg):
    print(('ok   ' if cond else 'FAIL ') + msg)
    if not cond:
        FAILS.append(msg)


# ---- веса
with tempfile.TemporaryDirectory() as root:
    plan = W.plan_weights(root)
    names = [w['name'] for w in plan]
    ok(names == ['ultratex_lora', 'ultratex_decoder', 'flux2_klein_base_9b', 'flux2_ae', 'qwen3_8b'], 'план весов: 5 частей в известном порядке')
    ok(all(w['dest'].startswith(root) for w in plan), 'все пути весов — внутри корня тома')
    ok({w['name'] for w in plan if w['gated']} == {'flux2_klein_base_9b', 'flux2_ae'}, 'закрытые: только 9B и ae из FLUX.2-dev')
    env = W.weights_env(root)
    ok(set(env) == {'KLEIN_9B_BASE_MODEL_PATH', 'AE_MODEL_PATH', 'QWEN3_8B_PATH'}, 'переменные, по которым код авторов находит базы')
    ok(env['QWEN3_8B_PATH'].endswith('qwen3-8b'), 'Qwen3 — каталог')

    # всё уже лежит → ни сети, ни ключа не нужно
    for w in plan:
        if w['src'] == 'hf_dir':
            os.makedirs(w['dest'], exist_ok=True)
            open(os.path.join(w['dest'], 'config.json'), 'w').close()
            open(os.path.join(w['dest'], '.complete'), 'w').close()
        else:
            os.makedirs(os.path.dirname(w['dest']), exist_ok=True)
            open(w['dest'], 'wb').write(b'x')
    seen = {}
    got = W.fetch_weights(root, '', lambda n, s: seen.__setitem__(n, s))
    ok(set(got.values()) == {'есть'} and set(seen.values()) == {'есть'}, 'всё на месте → докачка ничего не качает')

    # нет 9B → заглушка HF отвечает 403 → WeightsDenied с именем репозитория
    os.remove([w for w in plan if w['name'] == 'flux2_klein_base_9b'][0]['dest'])
    fake_hf = types.ModuleType('huggingface_hub')

    def deny(*a, **k):
        raise RuntimeError('403 Client Error. Cannot access gated repo')
    fake_hf.hf_hub_download = deny
    fake_hf.snapshot_download = deny
    sys.modules['huggingface_hub'] = fake_hf
    try:
        W.fetch_weights(root, 'tok', None)
        ok(False, '403 на закрытом → должно быть WeightsDenied')
    except W.WeightsDenied as e:
        ok('FLUX.2-klein-base-9B' in str(e), '403 на закрытом 9B → WeightsDenied с именем репозитория')
    except Exception as e:                                     # noqa: BLE001
        ok(False, f'ждали WeightsDenied, пришло {type(e).__name__}')

    # открытый вес с ошибкой сети — НЕ WeightsDenied
    os.remove([w for w in plan if w['name'] == 'ultratex_decoder'][0]['dest'])
    fake_ms = types.ModuleType('modelscope')

    def boom(*a, **k):
        raise ConnectionError('сеть')
    fake_ms.snapshot_download = boom
    sys.modules['modelscope'] = fake_ms
    try:
        W.fetch_weights(root, 'tok', None)
        ok(False, 'сбой сети на открытом весе → исключение')
    except W.WeightsDenied:
        ok(False, 'сбой сети на открытом весе не должен маскироваться под «нет допуска»')
    except ConnectionError:
        ok(True, 'сбой сети на открытом весе — своё исключение, не «нет допуска»')

# ---- холст 2×3 и условия
rng = np.random.default_rng(1)
tiles = [rng.integers(0, 255, (16, 16, 3), dtype=np.uint8) for _ in range(6)]
g = W.grid(tiles)
ok(g.shape == (32, 48, 3), 'холст 2×3: 2R × 3R')
ok(np.array_equal(g[:16, 16:32], tiles[1]) and np.array_equal(g[:16, 32:], tiles[3]) and np.array_equal(g[16:, :16], tiles[2]) and np.array_equal(g[16:, 16:32], tiles[4]) and np.array_equal(g[16:, 32:], tiles[5]),
   'раскладка: строка 1 = виды 0,1,3; строка 2 = 2,4,5')
back = W.tiles_from_grid(g, 16)
ok(all(np.array_equal(back[v], tiles[v]) for v in range(6)), 'tiles_from_grid обратна grid')

R = 64
nrm = np.zeros((6, 128, 128, 4), np.uint8)
nrm[:, 32:96, 32:96, :] = 255
ref = np.zeros((128, 128, 4), np.uint8)
ref[20:100, 40:90, :] = 200
cond = W.build_conditions(nrm, ref, R)
ok(cond['normal_grid'].shape == (2 * R, 3 * R, 3) and cond['reference'].shape == (R, R, 3), 'условия: холст нормалей и фото на нужных размерах')
ok(cond['mask_target'].shape == (2 * (R // 16), 3 * (R // 16)) and cond['mask_reference'].shape == (R // 16, R // 16), 'маски — на разрешении токенов (R/16)')
ok(cond['mask_full_grid'].shape == (2 * R, 3 * R) and cond['mask_full_grid'].any() and not cond['mask_full_grid'].all(), 'полная маска холста: есть и фон, и тело')
ok(np.array_equal(cond['mask_target'], cond['mask_normals']), 'цель = нормали по маске (как у датасета авторов)')
ok(cond['normal_grid'][0, 0].tolist() == [255, 255, 255], 'вне тела — белый фон')

# ---- разбор задания
img_b64 = base64.b64encode(b'png').decode()
glb_b64 = base64.b64encode(b'glb').decode()
p, e = W.validate_job({'job_id': 'a:1', 'image_b64': img_b64, 'glb_b64': glb_b64})
ok(e is None and p['resolution'] == 2048 and p['steps'] == 25 and p['guidance'] == 4.0 and p['texture_size'] == 4096, 'умолчания: 2048, 25 шагов, guidance 4, текстура 4096')
for bad, why in (({'image_b64': 'x', 'glb_b64': 'y'}, 'нет job_id'), ({'job_id': 'a', 'glb_b64': 'y'}, 'нет фото'), ({'job_id': 'a', 'image_b64': 'x'}, 'нет формы'),
                 ({'job_id': 'a', 'image_b64': 'x', 'glb_b64': 'y', 'resolution': 1536}, 'разрешение вне списка'), ({'job_id': 'a', 'image_b64': 'x', 'glb_b64': 'y', 'steps': 0}, 'шаги 0'),
                 ({'job_id': 'a', 'image_b64': 'x', 'glb_b64': 'y', 'texture_size': 1000}, 'текстура не кратна 512'), ({'job_id': '../x', 'image_b64': 'x', 'glb_b64': 'y'}, 'job_id с путём'),
                 ({'job_id': 'a', 'image_b64': 'x', 'glb_b64': 'y', 'seed': 'абв'}, 'seed не число')):
    _, err = W.validate_job(bad)
    ok(bool(err), f'отказ: {why}')

# ---- автостоп
t = [1000.0]
wd = W.Watchdog(max_lifetime_s=100, idle_s=30, now=lambda: t[0])
ok(wd.verdict(False, False) is None, 'сторож: старт — молчит')
t[0] = 1031
ok(wd.verdict(False, False) is None, 'сторож: простой считается только после готовности (прогрев весов долгий)')
ok(wd.verdict(True, False) is not None and 'простой' in wd.verdict(True, False), 'сторож: готов и 31 с без дела → выход')
ok(wd.verdict(True, True) is None, 'сторож: занят заданием — не гасит')
wd.touch()
ok(wd.verdict(True, False) is None, 'сторож: касание сбрасывает простой')
t[0] = 1101
ok('предел' in (wd.verdict(True, True) or ''), 'сторож: предел жизни гасит даже занятого')

# ---- HTTP воркера на подмене движка
class FakeEngine:
    def __init__(self):
        self.calls = []
        self.release = threading.Event()

    def run(self, p, glb, png):
        self.calls.append(p)
        self.release.wait(5)
        if glb == b'FAIL':
            raise ValueError('плохая форма')
        return b'GLB!' + glb, {'total_s': 1.0}


state, eng, stop = W.State(), FakeEngine(), threading.Event()
wd2 = W.Watchdog(1e9, 1e9)
srv = ThreadingHTTPServer(('127.0.0.1', 0), W.make_handler(state, eng, wd2, stop))
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f'http://127.0.0.1:{srv.server_address[1]}'


def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method, headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if r.headers.get('Content-Type', '').startswith('application/json') else raw)
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b'{}')


c, h = call('GET', '/health')
ok(c == 200 and h['phase'] == 'weights', '/health: фаза «weights» до готовности')
job = {'job_id': 'j1', 'image_b64': img_b64, 'glb_b64': glb_b64}
c, r = call('POST', '/generate', job)
ok(c == 503, 'до готовности задание не берётся (503)')
state.phase = 'ready'
c, r = call('POST', '/generate', {'job_id': 'j1'})
ok(c == 400, 'без фото и формы — 400')
c, r = call('POST', '/generate', job)
ok(c == 202, 'задание принято (202)')
c, r = call('POST', '/generate', dict(job, job_id='j2'))
ok(c == 429, 'второе при занятом GPU — 429')
c, r = call('GET', '/result/j1')
ok(c == 200 and r['status'] == 'running', 'пока идёт — running')
c, r = call('GET', '/result/j1/glb')
ok(c == 409, 'GLB до готовности — 409')
eng.release.set()
for _ in range(100):
    c, r = call('GET', '/result/j1')
    if r.get('status') != 'running':
        break
    threading.Event().wait(0.05)
ok(r.get('status') == 'done' and r['metrics']['total_s'] == 1.0, 'готово: done и метрики')
c, raw = call('GET', '/result/j1/glb')
ok(c == 200 and raw == b'GLB!glb', 'GLB отдан байт в байт')
ok(state.busy is False, 'после задания GPU свободен')
c, r = call('POST', '/generate', dict(job, job_id='j3', glb_b64=base64.b64encode(b'FAIL').decode()))
for _ in range(100):
    c, r = call('GET', '/result/j3')
    if r.get('status') != 'running':
        break
    threading.Event().wait(0.05)
ok(r.get('status') == 'failed' and 'плохая форма' in r['error'] and state.busy is False and state.phase == 'ready', 'сбой задания: failed с причиной, нода жива')
c, r = call('POST', '/generate', dict(job, job_id='j4', glb_b64=base64.b64encode(b'CUDA').decode()))
for _ in range(100):
    if call('GET', '/result/j4')[1].get('status') != 'running':
        break
    threading.Event().wait(0.05)
c, r = call('POST', '/shutdown')
ok(c == 200 and stop.is_set(), '/shutdown выставляет остановку процесса')
srv.shutdown()

# фатальная CUDA → broken
class CudaEngine(FakeEngine):
    def run(self, p, glb, png):
        raise RuntimeError('CUDA error: an illegal memory access was encountered')


st2 = W.State()
st2.phase, st2.busy = 'ready', True
st2.jobs['z'] = {'status': 'running', 'metrics': {}, 'error': ''}
W._work(st2, CudaEngine(), {'job_id': 'z'}, b'', b'')
ok(st2.phase == 'broken' and st2.jobs['z']['status'] == 'failed' and st2.busy is False, 'фатальная ошибка CUDA → нода «broken», новые задания не берутся')

# ---- рендер + развёртка вшитого ultratex_core (в образе идёт; без moderngl/EGL/trimesh/xatlas — пропуск)
try:
    import moderngl
    import trimesh
    import xatlas                                              # noqa: F401
    ctx = moderngl.create_standalone_context(require=330, backend='egl')
    ctx.release()
    have_gl = True
except Exception as exc:                                       # noqa: BLE001
    have_gl = False
    print('пропуск раздела рендера:', type(exc).__name__, str(exc)[:80])
if have_gl:
    from PIL import Image
    from ultratex_core import prep as P
    box = trimesh.creation.box(extents=(1.0, 0.6, 0.4))
    rgba = np.zeros((96, 160, 4), np.uint8)
    rgba[10:90, 20:140] = (180, 120, 60, 255)
    pr = P.run_prep(box, rgba, 128, 512, 'xatlas', 'fit_front_silhouette')
    ok(pr.normal_rgba.shape == (6, 128, 128, 4) and all((pr.normal_rgba[v, ..., 3] > 0).any() for v in range(6)), 'рендер: 6 видов, во всех есть тело')
    ok(len(pr.faces) == len(box.faces), 'развёртка xatlas не меняет число граней')
    ok(pr.reference_rgba.shape == (128, 128, 4) and (pr.reference_rgba[..., 3] > 0).any(), 'фото подогнано к кадру 128×128')

print('\nИТОГ:', 'ВСЁ ЗЕЛЁНОЕ' if not FAILS else f'ПРОВАЛОВ: {len(FAILS)}')
sys.exit(1 if FAILS else 0)
