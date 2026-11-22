#!/usr/bin/env python3
"""Тест воркера разметки частей на kit (Ш5/T-183): сервер `::`, /health с ходом, POST /run → /job → /file, 429 на занятой ноде. MODEL=fake — без GPU и весов.
Запуск: python tools/scout/salad/parts/tests_parts.py"""
import base64
import io
import json
import os
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

os.environ['MODEL'] = 'fake'
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
import numpy as np  # noqa: E402
import trimesh  # noqa: E402
import kit_worker as KW  # noqa: E402
import worker_parts as W  # noqa: E402
import kit_driver as KD  # noqa: E402

FAILS = []


def check(cond, msg):
    print(('OK   ' if cond else 'FAIL ') + msg)
    if not cond:
        FAILS.append(msg)


def get(port, path):
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}{path}', timeout=10) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def post(port, path, body):
    req = urllib.request.Request(f'http://127.0.0.1:{port}{path}', data=json.dumps(body).encode(), method='POST')
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b'{}')


def main() -> int:
    tmp = tempfile.mkdtemp()
    W.OUT_DIR = tmp
    glb = trimesh.creation.box(extents=(1, 2, 3)).export(file_type='glb')
    stop = threading.Event()
    wd = KW.Watchdog(600, 600)
    # --- фейковая модель, медленная: чтобы поймать «занято» и ход
    class Slow(W.FakeBackend):
        def segment(self, mesh, params, outdir):
            W.set_step('predict_aabb', 'Timer: 0.5 s')
            time.sleep(1.5)
            return super().segment(mesh, params, outdir)
    W.BACKEND = None
    orig = W.make_backend
    W.make_backend = lambda: Slow()
    handler = W.PartsHandler.bind(W.STATE, wd, stop, W.VERSION, root_dir=tmp, health_extra=W.health_extra)
    srv = KW.make_server(0, handler, host='::1')
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    threading.Thread(target=W.worker_loop, args=(W.QUEUE,), daemon=True).start()
    threading.Thread(target=KW.run_warm, args=(W.STATE, wd, [('loading', W.load_backend)], None, False), daemon=True).start()
    base = '::1'
    # urllib не ходит на ::1 без скобок — подменим адрес
    global get, post
    def _u(p): return f'http://[{base}]:{port}{p}'
    def get(port_, path):  # noqa: F811
        try:
            with urllib.request.urlopen(_u(path), timeout=10) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()
    def post(port_, path, body):  # noqa: F811
        req = urllib.request.Request(_u(path), data=json.dumps(body).encode(), method='POST')
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b'{}')
    for _ in range(50):
        c, b = get(port, '/health')
        if c == 200 and json.loads(b).get('phase') == 'ready':
            break
        time.sleep(0.1)
    h = json.loads(b)
    check(h['phase'] == 'ready' and h['model'] == 'fake' and h['job'] is None, f'/health: ready, модель fake, ход пуст до задания ({h["phase"]})')
    c, r = post(port, '/run', {'job_id': 'j1', 'items': [{'sid': 's1', 'glb_b64': base64.b64encode(glb).decode()}], 'params': {}})
    check(c == 202, f'POST /run → 202 ({c})')
    time.sleep(0.5)
    c2, r2 = post(port, '/run', {'job_id': 'j2', 'items': [{'sid': 's2', 'glb_b64': base64.b64encode(glb).decode()}]})
    check(c2 == 429, f'второе задание на занятой ноде → 429, не провал ({c2})')
    for _ in range(100):                                       # первый import torch в reset_peak может занять секунды
        c, b = get(port, '/health')
        j = json.loads(b)['job']
        if j and j['step'] == 'predict_aabb':
            break
        time.sleep(0.05)
    check(j and j['id'] == 'j1/s1' and j['step'] == 'predict_aabb' and 'Timer' in (j['line'] or ''), f'/health.job отдаёт шаг и строку: {j and (j["step"], j["line"])}')
    for _ in range(60):
        c, b = get(port, '/job/j1')
        if json.loads(b)['state'] == 'done':
            break
        time.sleep(0.2)
    jb = json.loads(b)
    check(jb['state'] == 'done' and jb['results'][0]['rc'] == 0, f'задание готово, rc=0 ({jb["state"]})')
    c, fb = get(port, '/file/j1/s1/faces.npy')
    f = np.load(io.BytesIO(fb))
    check(c == 200 and f.dtype == np.int32 and f.shape == (12,), f'faces.npy int32[F=12] ({c}, {f.dtype}, {f.shape})')
    c, b = get(port, '/health')
    check(json.loads(b)['job'] is None and json.loads(b)['busy'] is False, '/health: после задания ход пуст, busy=False')
    c, fb = get(port, '/archive/j1')
    check(c == 200 and len(fb) > 100, f'/archive/j1 отдаёт tar.gz ({c}, {len(fb)} Б)')
    c, fb = get(port, '/file/j1/../../etc/passwd')
    check(c == 404, f'выход за папку заданий закрыт ({c})')
    # фатальная CUDA → broken, новые задания не берём
    W.STATE.phase, W.STATE.error = 'broken', 'broken: CUDA error'
    c, r = post(port, '/run', {'job_id': 'j3', 'items': [{'sid': 's3', 'glb_b64': base64.b64encode(glb).decode()}]})
    check(c == 503, f'после фатальной CUDA задания не берёт ({c})')
    # --- драйвер parts_trial поверх настоящего сервера воркера: submit → poll → файлы → проверка граней, before_job
    import argparse
    import parts_trial as PT
    ico = trimesh.creation.icosphere(subdivisions=3)
    gp = os.path.join(tmp, 'ico.glb')
    ico.export(gp)
    W.STATE.phase, W.STATE.error = 'ready', ''
    W.BACKEND = W.FakeBackend()
    out_dir = os.path.join(tmp, 'drv')
    a = argparse.Namespace(model='fake', params='{}', max_meshes=2, stop_file='', out=out_dir)
    plan = PT.make_plan([{'sid': 'm1', 'path': gp}], [{'tag': 'v1', 'params': {}}, {'tag': 'v2', 'params': {}}, {'tag': 'v3', 'params': {}}])
    check([k for k, _i, _v in plan] == ['m1__v1', 'm1__v2', 'm1__v3'], 'make_plan: ключ = sid__tag, меш за мешом')
    spec = PT.make_spec(a, plan, [0.44])
    gw = KD.Gateway(f'http://[{base}]:{port}', 'k')
    cur, info = spec.submit(gw, 'm1__v1', time.time())
    check(cur and cur['id'] == 'fake-m1__v1', f'драйвер: submit принят ({info})')
    st = 'running'
    for _ in range(100):
        st, pi = spec.poll(gw, cur, time.time())
        if st != 'running':
            break
        time.sleep(0.1)
    check(st == 'done' and pi['check']['order_ok'] and os.path.exists(os.path.join(out_dir, 'v1', 'm1', 'faces.npy')) and os.path.exists(os.path.join(out_dir, 'v1', 'm1', 'meta.json')),
          f'драйвер: poll → done, faces.npy и meta.json скачаны в <out>/<tag>/<sid>/, порядок граней ок ({st}, {pi.get("check")})')
    check(spec.before_job('m1__v2', 0.0, 0.3) is None, 'before_job: одно готовое из двух разрешённых — шлём дальше')
    cur2, _ = spec.submit(gw, 'm1__v2', time.time())
    for _ in range(100):
        st, pi = spec.poll(gw, cur2, time.time())
        if st != 'running':
            break
        time.sleep(0.1)
    check(spec.before_job('m1__v3', 0.0, 0.3) == '--max-meshes 2 достигнут', 'before_job: --max-meshes 2 → плановый стоп перед третьим')
    a.max_meshes = 0
    spec3 = PT.make_spec(a, plan, [0.44])
    check(spec3.before_job('m1__v1', 0.0, 0.3) is None, 'before_job: без ограничений — шлём')
    # --- образ без CMD и без запечённого воркера: нода стартует командой группы (python -u -c BOOT + KIT_WORKER_Z) из пустой папки, доходит до ready и гаснет сама по простою
    import socket
    import subprocess
    sk = socket.socket()
    sk.bind(('', 0))
    bport = sk.getsockname()[1]
    sk.close()
    cmd, z = KW.bundle(W.__file__)
    benv = {**os.environ, 'KIT_WORKER_Z': z, 'MODEL': 'fake', 'PORT': str(bport), 'OUT_DIR': tempfile.mkdtemp(), 'IDLE_S': '3', 'MAX_LIFETIME_S': '90'}
    proc = subprocess.Popen([sys.executable] + cmd[1:], env=benv, cwd=tempfile.mkdtemp(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    hb = None
    for _ in range(80):
        try:
            with urllib.request.urlopen(f'http://[::1]:{bport}/health', timeout=2) as r:
                hb = json.loads(r.read())
            if hb.get('phase') == 'ready':
                break
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.25)
    check(hb and hb.get('phase') == 'ready' and hb.get('model') == 'fake', f'старт командой группы (bundle, без /app и CMD): ready ({hb and hb.get("phase")})')
    try:
        proc.wait(timeout=30)
        check(proc.returncode == 0, f'автостоп по простою — процесс вышел сам, rc={proc.returncode}')
    except subprocess.TimeoutExpired:
        proc.kill()
        check(False, 'автостоп по простою не сработал')
    # --- PartLLM: argv ссылается на существующий пустой YAML (в репозитории апстрима infer_config.yaml нет — pl1 22.11 упал на прогреве)
    import yaml
    av = W.partllm_argv('/x/model', 'general', tempfile.mkdtemp())
    cfgp = av[av.index('--config') + 1]
    check(os.path.isfile(cfgp) and (yaml.safe_load(open(cfgp)) or {}) == {} and av[av.index('--prompt_set') + 1] == 'general' and '--model_path' in av,
          f'PartLLM argv: --config → существующий пустой YAML ({cfgp})')
    W.make_backend = orig
    srv.shutdown()
    print('FAILS:', FAILS or 'нет')
    return 1 if FAILS else 0


if __name__ == '__main__':
    sys.exit(main())
