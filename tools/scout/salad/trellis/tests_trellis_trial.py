#!/usr/bin/env python3
"""Тесты драйвера замера (`trellis_trial.py`) и воркера пробы (`worker_trellis.py`) — на подмене Salad, без сети, ключей и видеокарты (T-20261118-91).

Главное, что проверяется: (1) закрытые веса недоступны → группа НЕ создаётся, денег 0; (2) потолок денег, провал прогрева, два упавших задания подряд, исключение
посреди замера — во всех случаях группа гасится С ПРОВЕРКОЙ `stopped` ровно один раз; (3) тело группы: только 4090, без приёмника на проде, токен в печати скрыт;
(4) воркер по HTTP: 503 до прогрева, задание → GLB, повтор job_id не запускает второй раз.

  python3 tools/scout/salad/trellis/tests_trellis_trial.py
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import threading
import time
import types
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.normpath(os.path.join(HERE, '..', '..')))
import remlab_tmp  # noqa: E402
remlab_tmp.use('tests_trellis_trial')
import trellis_trial as T  # noqa: E402

bad = 0


def ok(name, cond, extra=''):
    global bad
    print(('  ✓ ' if cond else '  ✗ ') + name + (f' — {extra}' if extra and not cond else ''))
    bad += 0 if cond else 1


# ——— чистые функции ———
print('[1] план, задания, деньги')
ok('план 1024:1,1536:2 разбирается', T.parse_plan('1024:1,1536:2') == [{'res': 1024, 'n': 1}, {'res': 1536, 'n': 2}])
try:
    T.parse_plan('2048:1')
    ok('разрешение 2048 — отказ', False)
except ValueError:
    ok('разрешение 2048 — отказ', True)
ok('типы цепочки TRELLIS.2', [T.pipeline_type(r) for r in (512, 1024, 1536)] == ['512', '1024_cascade', '1536_cascade'])
INP = {'a:1': {'input_png_sha256': 'x'}, 'b:2': {'input_png_sha256': 'y'}}
js = T.build_jobs(['a:1', 'b:2'], T.parse_plan('1024:1,1536:1'), INP, 7)
ok('4 задания, id без «:», seed в id', len(js) == 4 and js[0]['job_id'] == 'a_1-1024-7-0' and all(':' not in j['job_id'] for j in js))
try:
    T.build_jobs(['zz:9'], T.parse_plan('1024:1'), INP)
    ok('товар без вырезки — отказ', False)
except ValueError:
    ok('товар без вырезки — отказ', True)
ok('цена 4090 есть по тарифам', all((T.price_usd_h(t) or 0) > 0 for t in ('batch', 'low', 'medium', 'high')))
ok('деньги: 0 с running — 0; 1 ч по $0,33 = $0,33 + запас 60 с', T.cost_usd(0, 0.33) == 0 and abs(T.cost_usd(3600, 0.33) - 0.33 * 3660 / 3600) < 1e-9)

print('[2] тело группы')
body = T.build_body('trial-trellis2-x', 'ghcr.io/x/y:t', 'high', 'trellis2', 'hf_SECRET', 8, 32768, 'note', {'basic': {'username': 'u', 'password': 'PW'}})
env = body['container']['environment_variables']
ok('карта — только RTX 4090', body['container']['resources']['gpu_classes'] == [T.CARD['class_id']])
ok('приёмника на проде нет (ни MESH_SINK_URL, ни токена приёмника)', not any(k.startswith('MESH_SINK') for k in env))
ok('шлюз с ключом Salad, порт 8000, проба готовности /health (не /ready: до её прохождения шлюз 503 на любой путь), перезапуска нет', body['networking']['auth'] is True and body['networking']['port'] == 8000
   and body['readiness_probe']['http']['path'] == '/health' and body['restart_policy'] == 'never' and body['replicas'] == 1 and body['autostart_policy'] is False)
ok('пороги проб в пределах API Salad (failure_threshold ≤ 20 — иначе 400 при создании, поймано 18.11)', body['startup_probe']['failure_threshold'] <= 20 and body['readiness_probe']['failure_threshold'] <= 20)
donor = {'container': {'image': 'ghcr.io/igortsk123/mesh-hunyuan@sha256:' + 'a' * 64, 'resources': {'cpu': 4, 'memory': 24576, 'storage_amount': 64424509440, 'shm_size': 64, 'gpu_classes': ['x', 'y']},
                       'environment_variables': {'STAGED': '1', 'PIPELINE_VERSION': 'v2', 'MESH_SINK_URL': 'https://sink', 'MESH_SINK_TOKEN': 'SINKSECRET',
                                                 'STORAGE_BACKEND': 'http', 'TQDM_DISABLE': '1'}}}
hb = T.build_body('trial-hunyuan21-x', donor['container']['image'], 'high', 'hunyuan21', '', 8, 32768, 'note', {'basic': {}}, donor)
henv = hb['container']['environment_variables']
ok('контроль: приёмник и очередь боевой группы НЕ попадают в пробную (ни URL, ни токен)', not any(k.startswith('MESH_SINK') for k in henv) and 'SINKSECRET' not in json.dumps(hb))
ok('контроль: боевые ручки образца (STAGED, PIPELINE_VERSION) сохранены, GPU — только 4090, ресурсы образца', henv.get('STAGED') == '1' and henv.get('PIPELINE_VERSION') == 'v2'
   and hb['container']['resources']['gpu_classes'] == [T.CARD['class_id']] and hb['container']['resources']['memory'] == 24576)
ok('контроль: код воркера едет в command + env TRIAL_WORKER_Z и распаковывается обратно в тот же файл',
   hb['container']['command'][:3] == ['python', '-u', '-c'] and __import__('zlib').decompress(__import__('base64').b64decode(henv['TRIAL_WORKER_Z'])) == open(os.path.join(HERE, 'worker_trellis.py'), 'rb').read())
ok('TRELLIS.2: воркер едет через command (bash: pip-пин transformers с повторами → exec python3) без пересборки образа',
   body['container']['command'][:2] == ['bash', '-c'] and 'transformers==4.56' in body['container']['command'][2] and 'exec python3 -u -c' in body['container']['command'][2] and __import__('zlib').decompress(__import__('base64').b64decode(env['TRIAL_WORKER_Z'])) == open(os.path.join(HERE, 'worker_trellis.py'), 'rb').read())
pb = T.build_body('trial-pixal3d-x', 'ghcr.io/x/y@sha256:' + 'b' * 64, 'high', 'pixal3d', 'hf_SECRET', 8, 32768, 'n', {'basic': {}})
ok('Pixal3D: MODEL=pixal3d, воркер через command (python3), pip-пин TRELLIS.2 НЕ ставится (образ с transformers 4.57.3), карта 4090, диск 80 ГиБ',
   pb['container']['environment_variables']['MODEL'] == 'pixal3d' and pb['container']['command'][:3] == ['python3', '-u', '-c'] and 'pip' not in json.dumps(pb['container']['command'])
   and pb['container']['resources']['gpu_classes'] == [T.CARD['class_id']] and pb['container']['resources']['storage_amount'] == 80 * 2 ** 30)
lb = T.build_body('trial-localmesh-x', 'ghcr.io/x/y@sha256:' + 'c' * 64, 'high', 'localmesh', 'hf_SECRET', 8, 32768, 'n', {'basic': {}})
ok('LocalMesh: MODEL=localmesh, воркер через command (python3), без pip-пина TRELLIS.2, HF_TOKEN только в env',
   lb['container']['environment_variables']['MODEL'] == 'localmesh' and lb['container']['command'][:3] == ['python3', '-u', '-c'] and 'pip' not in json.dumps(lb['container']['command'])
   and lb['container']['environment_variables']['HF_TOKEN'] == 'hf_SECRET' and 'hf_SECRET' not in json.dumps(lb['container']['command']))
buf = io.StringIO()
real = sys.stdout
sys.stdout = buf
T.safe_print(body)
sys.stdout = real
ok('печать скрывает HF_TOKEN и пароль реестра', 'hf_SECRET' not in buf.getvalue() and 'PW' not in buf.getvalue() and '<скрыто>' in buf.getvalue())


# ——— подмены Salad ———
class FakeMG:
    def __init__(self, groups=None, create_code=200):
        self.calls, self.groups, self.create_code = [], groups or [], create_code

    def env_from_file(self):
        os.environ.setdefault('SALAD_API_KEY', 'k')
        os.environ.setdefault('HF_TOKEN', 'hf_x')

    def ghcr_auth(self):
        return {'basic': {'username': 'u', 'password': 'p'}}

    def api(self, path, method='GET', body=None):
        self.calls.append((method, path))
        if path == '' and method == 'GET':
            return 200, {'items': self.groups}
        if method == 'GET' and path.startswith('/trial-'):
            return (404, {}) if not any(c == ('POST', '') for c in self.calls) else (200, {'networking': {'dns': 'trial.example'}})
        if method == 'POST' and path == '':
            return self.create_code, {}
        return 200, {}


class FakeBR:
    def __init__(self, running_after=1):
        self.stops, self.n = [], 0
        self.running_after = running_after

    def group_state(self, name):
        return 200, 'stopped', {}

    def instances(self, name):
        self.n += 1
        return 200, ([{'state': 'running'}] if self.n >= self.running_after else [])

    def stop_and_verify(self, name, timeout_s=300):
        self.stops.append(name)
        return True


class FakeGW:
    """Шлюз ноды: прогрет сразу; задания — по сценарию `fail_jobs` (сколько первых упадут)."""
    script = {'warm': True, 'fail_jobs': 0, 'health_error': None, 'raise_on': None, 'phase': None, 'no_health': False, 'hf_gb': None, 'disk_free': 50.0}

    def __init__(self, base, key):
        self.jobs, self.k = {}, 0

    def call(self, method, path, body=None, timeout=60, raw=False):
        s = FakeGW.script
        if s['raise_on'] and path.startswith(s['raise_on']):
            raise RuntimeError('сбой посреди замера')
        if path == '/health':
            if s['no_health']:
                return 503, {}
            return 200, {'warm': s['warm'], 'phase': s['phase'] or ('ready' if s['warm'] else 'loading'), 'error': s['health_error'], 'timings': {'weights_s': 5},
                         'progress': {'hf_gb': s['hf_gb']} if s['hf_gb'] is not None else None, 'child': {'alive': True}, 'cgroup_gb': {'current': 1.0, 'max': 24.0}, 'disk_gb': {'hf': {'free': s['disk_free'], 'total': 60.0}}}
        if path == '/info':
            return 200, {'gpu': {'name': 'RTX 4090'}}
        if path == '/generate':
            self.k += 1
            self.jobs[body['job_id']] = 'failed' if self.k <= s['fail_jobs'] else 'done'
            return 202, {'status': 'queued'}
        if path.startswith('/job/'):
            st = self.jobs[path[5:]]
            return 200, ({'status': 'done', 'metrics': {'peak_vram_gb': 19.0, 'glb': {'triangles': 10}}} if st == 'done'
                         else {'status': 'failed', 'error': 'OOM', 'trace': 't'})
        if path.startswith('/glb/'):
            return 200, b'GLBDATA'
        return 404, {}


def args(tmp, **kw):
    d = dict(donor='mesh-q-low-1', set=None, fail_streak=2, model='trellis2', image='ghcr.io/x/y:t', inputs=tmp, skus=['a:1'], plan='1024:1', seed=42, decimation=500000, texture=2048, tier='high', cpu=8,
             mem_mb=32768, cap=3.0, max_min=90, ready_min=40, health_min=20, stall_min=10, disk_min_gb=3.0, job_timeout=15, suffix='t1', out=os.path.join(tmp, 'out'), apply=True, stop_only=False)
    d.update(kw)
    return types.SimpleNamespace(**d)


def make_inputs(tmp, skus=('a:1',)):
    inp = {}
    for s in skus:
        open(os.path.join(tmp, s.replace(':', '_') + '.rgba.png'), 'wb').write(b'\x89PNG')
        inp[s] = {'input_png_sha256': 'x'}
    json.dump(inp, open(os.path.join(tmp, 'inputs.json'), 'w'))


def go(tmp, mg=None, br=None, hf=200, script=None, **kw):
    FakeGW.script = {'warm': True, 'fail_jobs': 0, 'health_error': None, 'raise_on': None, 'phase': None, 'no_health': False, 'hf_gb': None, 'disk_free': 50.0, **(script or {})}
    clock = [0.0]

    def sleep(s):
        clock[0] += s
    mg, br = mg or FakeMG(), br or FakeBR()
    try:
        rc = T.run(args(tmp, **kw), mg, br, gw_factory=FakeGW, sleep=sleep, clock=lambda: clock[0], hf_head=lambda p, t: hf)
    except RuntimeError as e:
        rc = f'exc:{e}'
    summ = None
    sp = os.path.join(tmp, 'out', f'summary-trial-trellis2-{kw.get("suffix", "t1")}.json')      # сводка именно этого прогона
    if os.path.exists(sp):
        summ = json.load(open(sp))
    return rc, mg, br, summ


print('[3] драйвер: закрытые веса, чужие группы, повтор')
d = tempfile.mkdtemp(prefix='tt-')
make_inputs(d)
rc, mg, br, _ = go(d, apply=False)
ok('без --apply — ничего не создаёт и не запускает', rc == 0 and not [c for c in mg.calls if c[0] in ('POST', 'PATCH')] and br.stops == [])
rc, mg, br, _ = go(d, hf=403)
ok('DINOv3 отдаёт 403 → группа НЕ создаётся, остановка не нужна, код 3', rc == 3 and ('POST', '') not in mg.calls and br.stops == [])
rc, mg, br, _ = go(d, mg=FakeMG(groups=[{'name': 'other-live', 'current_state': {'status': 'running'}}]))
ok('чужая живая группа → отказ, группа не создаётся', rc == 2 and ('POST', '') not in mg.calls)
rc, mg, br, _ = go(d, mg=FakeMG(groups=[{'name': 'mesh-q-low-1', 'current_state': {'status': 'running'}}]))
ok('боевая mesh-группа живая — не помеха (её не трогаем)', rc == 0 and all('mesh-q-low-1' not in c[1] for c in mg.calls))

print('[4] драйвер: нормальный ход и предохранители (стоп с проверкой — всегда)')
d = tempfile.mkdtemp(prefix='tt-')
make_inputs(d, ('a:1', 'b:2'))
rc, mg, br, s = go(d, skus=['a:1', 'b:2'], plan='1024:1,1536:1')
ok('успех: 4 задания, GLB скачаны, stopped_by=done, стоп подтверждён один раз', rc == 0 and s and len(s['jobs']) == 4 and s['stopped_by'] == 'done'
   and s['stop_verified'] and br.stops == ['trial-trellis2-t1'])
ok('GLB лежат файлами, метрики и тайминги в сводке', all(os.path.exists(j['glb_path']) and j['glb_bytes'] == 7 for j in s['jobs']) and s['timings'] == {'weights_s': 5} and s['info']['gpu']['name'] == 'RTX 4090')
ok('деньги посчитаны и не больше потолка', 0 < s['cost_usd_est'] < 3.0 and s['to_first_running_s'] is not None)
d = tempfile.mkdtemp(prefix='tt-')
make_inputs(d)
rc, mg, br, s = go(d, cap=0.001)
ok('потолок денег → stopped_by=money, стоп подтверждён', rc == 1 and s['stopped_by'] == 'money' and br.stops == ['trial-trellis2-t1'])
rc, mg, br, s = go(d, suffix='t2', script={'warm': False, 'health_error': 'OSError: 403 gated'})
ok('прогрев упал (например, закрытые веса) → гашу сразу, причина в сводке', s['stopped_by'] == 'warm_failed' and br.stops == ['trial-trellis2-t2'])
rc, mg, br, s = go(d, suffix='t3', script={'warm': False}, ready_min=1)
ok('нода не прогрелась за ready_min → гашу', s['stopped_by'] == 'not_ready' and br.stops == ['trial-trellis2-t3'])
rc, mg, br, s = go(d, suffix='t7', script={'no_health': True}, health_min=2)
ok('воркер не ответил на /health ни разу за health_min → гашу (мёртвый процесс не жжёт деньги до 75 мин)', s['stopped_by'] == 'no_health' and br.stops == ['trial-trellis2-t7'])
rc, mg, br, s = go(d, suffix='t8', script={'warm': False, 'phase': 'weights', 'hf_gb': 3.5}, stall_min=1, ready_min=30)
ok('докачка весов не растёт stall_min → гашу (причина — download_stalled)', s['stopped_by'] == 'download_stalled' and br.stops == ['trial-trellis2-t8'])
rc, mg, br, s = go(d, suffix='t10', script={'warm': False, 'phase': 'weights', 'hf_gb': 20.0, 'disk_free': 1.0})
ok('на диске контейнера < 3 ГиБ → гашу (disk_low), минимум свободного места в сводке', s['stopped_by'] == 'disk_low' and s['disk_free_gb_min'] == 1.0 and br.stops == ['trial-trellis2-t10'])
rc, mg, br, s = go(d, suffix='t9', script={'warm': False, 'phase': 'child_dead', 'health_error': 'дочерний процесс завершился, код -9'})
ok('ребёнок убит (−9) → гашу сразу, причина в сводке', s['stopped_by'] == 'warm_failed' and br.stops == ['trial-trellis2-t9'] and '-9' in str(s['health']['error']))
d2 = tempfile.mkdtemp(prefix='tt-')
make_inputs(d2, ('a:1', 'b:2', 'c:3'))
rc, mg, br, s = go(d2, skus=['a:1', 'b:2', 'c:3'], plan='1024:1', script={'fail_jobs': 5})
ok('два упавших задания подряд → гашу, счётчик отказов в сводке', s['stopped_by'] == 'failures' and s['failed'] == 2 and br.stops == ['trial-trellis2-t1'])
rc, mg, br, s = go(d, suffix='t4', script={'raise_on': '/generate'})
ok('исключение посреди замера → стоп с проверкой всё равно сделан', isinstance(rc, str) and rc.startswith('exc:') and br.stops == ['trial-trellis2-t4'])
rc, mg, br, s = go(d, suffix='t5', br=FakeBR(running_after=10 ** 6))
ok('нода не вышла в running за час → стоп (платили 0)', s['stopped_by'] == 'no_machine' and s['cost_usd_est'] == 0.0)
rc, mg, br, s = go(d, suffix='t6', mg=FakeMG(create_code=400))
ok('создание группы отвергнуто → код 1, гасить нечего', rc == 1 and br.stops == [])

print('[5] воркер по HTTP (бэкенд fake)')
os.environ['MODEL'] = 'fake'
os.environ['OUT_DIR'] = tempfile.mkdtemp(prefix='wk-')
try:
    import trimesh  # noqa: F401
    import PIL  # noqa: F401
    have = True
except ImportError:
    have = False
    print('  · SKIP: нет trimesh/PIL в этом окружении (проверяется на pakardev)')
if have:
    import base64
    import socket
    import subprocess
    sk = socket.socket()
    sk.bind(('127.0.0.1', 0))
    port = sk.getsockname()[1]
    sk.close()
    tmp = tempfile.mkdtemp(prefix='wk2-')
    env = dict(os.environ, MODEL='fake', PORT=str(port), OUT_DIR=os.path.join(tmp, 'out'), TRIAL_STATE=os.path.join(tmp, 'state.json'),
               TRIAL_JOBS=os.path.join(tmp, 'jobs'), HF_HOME=os.path.join(tmp, 'hf'), HF_TOKEN='hf_SECRETVALUE0123456789')
    env.pop('TRIAL_CHILD', None)
    proc = subprocess.Popen([sys.executable, '-u', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'worker_trellis.py')], env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

    def call(method, path, body=None):
        req = urllib.request.Request(f'http://127.0.0.1:{port}{path}', method=method, data=json.dumps(body).encode() if body is not None else None,
                                     headers={'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()
        except OSError:
            return 0, b''
    try:
        for _ in range(100):                      # главный процесс поднялся и отвечает на /health
            if call('GET', '/health')[0] == 200:
                break
            time.sleep(0.1)
        h0 = json.loads(call('GET', '/health')[1])
        ok('/health отвечает сразу (двухпроцессный воркер), в ответе ребёнок и память группы', h0['ok'] is True and h0['child']['started'] is True and 'cgroup_gb' in h0, str(h0)[:200])
        from PIL import Image
        png = io.BytesIO()
        Image.new('RGBA', (8, 8), (255, 0, 0, 255)).save(png, 'PNG')
        payload = {'job_id': 'j1', 'image_b64': base64.b64encode(png.getvalue()).decode(), 'pipeline_type': '1024_cascade'}
        for _ in range(150):                      # ждём прогрева ребёнка (fake — мгновенно)
            if call('GET', '/ready')[0] == 200:
                break
            time.sleep(0.1)
        ok('после прогрева /ready — 200, в /health тайминги и размер кэша HF', call('GET', '/ready')[0] == 200
           and 'container_to_ready_s' in json.loads(call('GET', '/health')[1])['timings'] and json.loads(call('GET', '/health')[1])['progress'] is not None)
        ok('кривой запрос — 400, нет такого пути — 404', call('POST', '/generate', {'x': 1})[0] == 400 and call('GET', '/net')[0] == 404)
        c, r = call('POST', '/generate', payload)
        ok('/generate → 202', c == 202 and json.loads(r)['status'] == 'queued')
        c2, _r2 = call('POST', '/generate', payload)
        ok('повтор job_id — 409 (второй раз GPU не жжём)', c2 == 409)
        j = {}
        for _ in range(150):
            j = json.loads(call('GET', '/job/j1')[1])
            if j.get('status') in ('done', 'failed'):
                break
            time.sleep(0.1)
        ok('задание done, замеры: стадии, пик VRAM, треугольники куба, размер файла', j.get('status') == 'done' and j['metrics']['glb']['triangles'] == 12
           and 'stage_s' in j['metrics'] and j['metrics']['glb']['size_mb'] >= 0, str(j)[:200])
        cg, rg = call('GET', '/glb/j1')
        ok('GLB отдаётся байтами (заголовок glTF)', cg == 200 and rg[:4] == b'glTF')
        ok('чужой job — 404', call('GET', '/job/net')[0] == 404 and call('GET', '/glb/net')[0] == 404)
        if socket.has_ipv6:                       # шлюз Salad ходит по IPv6: сервер обязан слушать `::` (поймано 18.11: на 0.0.0.0 /health не отвечал ни разу)
            try:
                s6 = socket.create_connection(('::1', port), timeout=5)
                s6.sendall(b'GET /health HTTP/1.0\r\n\r\n')
                ok('сервер отвечает и по IPv6 (::1), и по IPv4', s6.recv(20).startswith(b'HTTP/1.0 200') and call('GET', '/health')[0] == 200)
                s6.close()
            except OSError as e:
                print('  · SKIP IPv6: в окружении теста нет ::1', e)
        h1 = json.loads(call('GET', '/health')[1])['child']
        ok('в /health у ребёнка есть состояние процесса и CPU-секунды (стоит или считает)', 'cpu_s' in h1 and h1.get('state') in ('R', 'S', 'D'), str(h1))
        ok('путь с ../ не выходит из каталога заданий', call('GET', '/job/..%2f..%2fetc%2fpasswd')[0] == 404)
    finally:
        proc.terminate()
        try:
            out = proc.communicate(timeout=15)[0].decode('utf-8', 'replace')
        except subprocess.TimeoutExpired:
            proc.kill()
            out = ''
        ok('журнал воркера: «[child] … HF_TOKEN: …» без значения токена и строки [watch]', '[child]' in out and 'HF_TOKEN: есть' in out and '[watch]' in out and 'SECRETVALUE' not in out, out[:200])

print('[6] страница сверки (make_page): кадры → webp ≤1600, миниатюры, страницы товаров, подписи моделей')
try:
    from PIL import Image as PI
    have_pil = True
except ImportError:
    have_pil = False
    print('  · SKIP: нет PIL')
if have_pil:
    import make_page as MP
    tp = tempfile.mkdtemp(prefix='mp-')
    fr, inp, out = os.path.join(tp, 'frames'), os.path.join(tp, 'inputs'), os.path.join(tp, 'site')
    os.makedirs(inp)
    for sku in ('a:1', 'b:2'):
        PI.new('RGBA', (60, 40), (200, 100, 50, 255)).save(os.path.join(inp, sku.replace(':', '_') + '.cut-preview.png'))
    json.dump({'a:1': {'image_url': ''}, 'b:2': {}}, open(os.path.join(inp, 'inputs.json'), 'w'))
    sf = os.path.join(tp, 'set.json')
    json.dump([{'sku': 'a:1', 'name': 'Диван <тест>', 'role': 'диван', 'dims_cm': [200.0, 90.0, 80.0], 'hard': ['ткань']},
               {'sku': 'b:2', 'name': 'Стул', 'role': 'стул', 'dims_cm': [40.0, 40.0, 90.0], 'hard': []}], open(sf, 'w'))
    d1 = os.path.join(fr, 'trellis2', 'a_1')
    os.makedirs(d1)
    for k in range(3):
        PI.new('RGB', (2400 if k == 0 else 800, 1200), (k * 50, 90, 90)).save(os.path.join(d1, f'v{k:02d}_tex.png'))
    os.makedirs(os.path.join(fr, 'hunyuan21'))
    json.dump({'b:2': {'status': 'no_mesh', 'reason': 'нет меша: вход не подошёл'}}, open(os.path.join(fr, 'hunyuan21', 'results.json'), 'w'))
    json.dump({'a:1': {'total_s': 91.5, 'triangles': 480000, 'size_mb': 12.3}}, open(os.path.join(fr, 'trellis2', 'results.json'), 'w'))
    r = MP.build(fr, sf, inp, out, 50, fetch=lambda u, d: False)
    ix = open(os.path.join(out, 'index.html'), encoding='utf-8').read()
    pg = open(os.path.join(out, 'p', 'a_1.html'), encoding='utf-8').read()
    ok('страница: 2 товара, 3 кадра, модели подписаны открыто', r['products'] == 2 and r['frames'] == 3 and 'TRELLIS.2' in ix and 'Hunyuan3D-2.1' in ix)
    big = PI.open(os.path.join(out, 'img', 'trellis2', 'a_1', '00.webp'))
    th = PI.open(os.path.join(out, 'img', 'trellis2', 'a_1', '00.t.webp'))
    ok('кадр ≤1600 по большей стороне, миниатюра ≤480', max(big.size) == 1600 and max(th.size) == 480, f'{big.size} {th.size}')
    ok('страница товара: миниатюра ведёт на полный кадр, подпись кадра и замеры есть, HTML экранирован',
       'href="../img/trellis2/a_1/00.webp"' in pg and 'v00_tex' in pg and '480 000' in pg and '&lt;тест&gt;' in pg and '<тест>' not in pg)
    ok('нет меша — причина открыто в таблице', 'нет меша: вход не подошёл' in ix)
    try:
        MP.build(fr, sf, inp, out, 0.0001, fetch=lambda u, d: False)
        ok('предел веса картинок срабатывает', False)
    except SystemExit:
        ok('предел веса картинок срабатывает', True)

print('ИТОГО: ' + ('всё в норме' if not bad else f'провалов {bad}'))
sys.exit(1 if bad else 0)
