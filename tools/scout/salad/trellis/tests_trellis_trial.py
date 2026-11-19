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
# --- папка результатов у каждой модели своя; чужой файл не затирается (19.11: Hunyuan затёр 12 GLB TRELLIS.2) ---
ok('папка по умолчанию — по модели', T.default_out('pixal3d').endswith('/mesh-models-1118/pixal3d') and T.default_out('trellis2').endswith('/trellis2') and T.default_out('hunyuan21') != T.default_out('trellis2'))
with tempfile.TemporaryDirectory() as _d:
    _old = os.path.join(_d, 'trellis'); os.makedirs(_old)
    open(os.path.join(_old, 'k-1024-42-0.glb'), 'wb').write(b'x')
    ok('старая общая папка: файл без метки — чужой для любой модели', T.owner_conflicts(_old, ['k-1024-42-0'], 'pixal3d') == ['k-1024-42-0'] and T.owner_conflicts(_old, ['k-1024-42-0'], 'trellis2') == ['k-1024-42-0'])
    _own = os.path.join(_d, 'pixal3d'); os.makedirs(_own)
    ok('своя пустая папка — писать можно', T.owner_conflicts(_own, ['k-1024-42-0'], 'pixal3d') == [])
    open(os.path.join(_own, 'k-1024-42-0.glb'), 'wb').write(b'x'); open(os.path.join(_own, 'k-1024-42-0.model'), 'w').write('pixal3d')
    ok('метка своей модели — повтор можно, чужой моделью — отказ', T.owner_conflicts(_own, ['k-1024-42-0'], 'pixal3d') == [] and T.owner_conflicts(_own, ['k-1024-42-0'], 'hunyuan21') == ['k-1024-42-0'])
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
LIVE = [{'name': 'RTX 4090 (24 GB)', 'prices': [{'priority': 'high', 'price': '0.44'}, {'priority': 'low', 'price': '0.253'}]},
        {'name': 'RTX 4060 Ti (16 GB)', 'prices': [{'priority': 'high', 'price': '0.14'}]}]
ok('живая цена из ответа Salad: 4090 high = 0,44 (снимок 0,33 занижал на треть)', T.parse_live_price(LIVE, 'RTX 4090 (24 GB)', 'high') == 0.44 and T.price_usd_h('high') != 0.44)
ok('живая цена: другой класс и тариф; нет класса/тарифа/мусор — None',
   T.parse_live_price(LIVE, 'RTX 4060 Ti (16 GB)', 'high') == 0.14 and T.parse_live_price(LIVE, 'RTX 4090 (24 GB)', 'medium') is None
   and T.parse_live_price(LIVE, 'нет такой', 'high') is None and T.parse_live_price([{'name': 'RTX 4090 (24 GB)', 'prices': [{'priority': 'high', 'price': 'x'}]}], 'RTX 4090 (24 GB)', 'high') is None
   and T.parse_live_price(None, 'a', 'high') is None)
ok('нет связи с Salad — живая цена None (запасной путь — снимок)', T.live_price_usd_h(object(), 'RTX 4090 (24 GB)', 'high') is None)

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
ok('Pixal3D: MODEL=pixal3d, воркер через command (python3), при старте пин huggingface_hub==0.35.3, пина transformers TRELLIS.2 НЕТ (образ с 4.57.3), карта 4090, диск 80 ГиБ',
   pb['container']['environment_variables']['MODEL'] == 'pixal3d' and pb['container']['command'][-1] is not None and 'huggingface_hub==0.35.3' in json.dumps(pb['container']['command']) and T.TRELLIS_PIP_PIN not in json.dumps(pb['container']['command'])
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
    script = {'warm': True, 'fail_jobs': 0, 'health_error': None, 'raise_on': None, 'phase': None, 'no_health': False, 'hf_gb': None, 'disk_free': 50.0, 'fatal_jobs': False, 'broken': None, 'job_hangs': False}

    def __init__(self, base, key):
        self.jobs, self.k = {}, 0

    def call(self, method, path, body=None, timeout=60, raw=False):
        s = FakeGW.script
        if s['raise_on'] and path.startswith(s['raise_on']):
            raise RuntimeError('сбой посреди замера')
        if path == '/health':
            if s['no_health']:
                return 503, {}
            return 200, {'ok': s['broken'] is None, 'broken': s['broken'], 'warm': s['warm'], 'phase': s['phase'] or ('ready' if s['warm'] else 'loading'), 'error': s['health_error'], 'timings': {'weights_s': 5},
                         'progress': {'hf_gb': s['hf_gb']} if s['hf_gb'] is not None else None, 'child': {'alive': True}, 'cgroup_gb': {'current': 1.0, 'max': 24.0}, 'disk_gb': {'hf': {'free': s['disk_free'], 'total': 60.0}}}
        if path == '/info':
            return 200, {'gpu': {'name': 'RTX 4090'}}
        if path == '/generate':
            self.k += 1
            self.jobs[body['job_id']] = 'failed' if self.k <= s['fail_jobs'] else 'done'
            return 202, {'status': 'queued'}
        if path.startswith('/job/'):
            st = self.jobs[path[5:]]
            if s['job_hangs']:
                return 200, {'status': 'running'}
            if st == 'failed' and s['fatal_jobs']:
                return 200, {'status': 'failed', 'error': 'RuntimeError: CUDA driver error: device not ready', 'trace': 't', 'diag': {'kind': 'fatal', 'fatal': True}}
            return 200, ({'status': 'done', 'metrics': {'peak_vram_gb': 19.0, 'glb': {'triangles': 10}}} if st == 'done'
                         else {'status': 'failed', 'error': 'OOM', 'trace': 't', 'diag': {'kind': 'oom', 'fatal': False}})
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


def go(tmp, mg=None, br=None, hf=200, script=None, gw=None, **kw):
    FakeGW.script = {'warm': True, 'fail_jobs': 0, 'health_error': None, 'raise_on': None, 'phase': None, 'no_health': False, 'hf_gb': None, 'disk_free': 50.0,
                     'fatal_jobs': False, 'broken': None, 'job_hangs': False, **(script or {})}
    clock = [0.0]

    def sleep(s):
        clock[0] += s
    mg, br = mg or FakeMG(), br or FakeBR()
    try:
        rc = T.run(args(tmp, **kw), mg, br, gw_factory=gw or FakeGW, sleep=sleep, clock=lambda: clock[0], hf_head=lambda p, t: hf)
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
rc, mg, br, s = go(d2, suffix='t11', skus=['a:1', 'b:2', 'c:3'], script={'fail_jobs': 5, 'fatal_jobs': True})
ok('фатальная ошибка CUDA в задании (diag.fatal) → гашу сразу после ПЕРВОГО, не ждём серию отказов; стоп подтверждён', s['stopped_by'] == 'worker_broken' and s['failed'] == 1
   and len(s['jobs']) == 1 and 'device not ready' in str(s['broken']) and br.stops == ['trial-trellis2-t11'])
rc, mg, br, s = go(d2, suffix='t12', skus=['a:1', 'b:2', 'c:3'], script={'fail_jobs': 5})
ok('обычная нехватка памяти (diag.fatal=false) — прежнее правило: гасит только серия отказов', s['stopped_by'] == 'failures' and s['failed'] == 2 and 'broken' not in s)
rc, mg, br, s = go(d, suffix='t13', script={'job_hangs': True, 'broken': 'RuntimeError: !handles_.at(i) INTERNAL ASSERT'}, job_timeout=60)
ok('/health «сломан» во время задания → гашу сразу (до таймаута задания), причина и задание в сводке', s['stopped_by'] == 'worker_broken' and 'INTERNAL ASSERT' in str(s['broken'])
   and s['failed'] == 1 and s['jobs'][0]['status'] == 'failed' and br.stops == ['trial-trellis2-t13'])
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
        pm = dict(payload, job_id='j2', texture_mesh_b64=base64.b64encode(rg).decode())
        c3, _r3 = call('POST', '/generate', pm)
        j2 = {}
        for _ in range(150):
            j2 = json.loads(call('GET', '/job/j2')[1])
            if j2.get('status') in ('done', 'failed'):
                break
            time.sleep(0.1)
        ok('контроль перекраски: форма уходит файлом, в задании только флаг (base64 в ответ не попадает), ?v=ai без второго GLB — 404',
           c3 == 202 and j2.get('params', {}).get('texture_mesh') is True and 'texture_mesh_b64' not in json.dumps(j2) and call('GET', '/glb/j2?v=ai')[0] == 404, str(j2)[:200])
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

print('[4б] драйвер: долгое создание группы и отказ /start (живая группа MV-Adapter 19.11: stopped позже 10 минут, /start → HTTP 400)')


class SlowCreateBR(FakeBR):
    """Группа создаётся `slow_s` секунд (по часам теста), потом становится stopped; `stuck` — не станет никогда."""
    def __init__(self, clock_box, slow_s=0, stuck=False, **kw):
        super().__init__(**kw)
        self.cb, self.slow_s, self.stuck, self.state_calls = clock_box, slow_s, stuck, 0

    def group_state(self, name):
        self.state_calls += 1
        if self.stuck or self.cb[0] < self.slow_s:
            return 200, 'creating', {}
        return 200, 'stopped', {}


class StartCodesMG(FakeMG):
    def __init__(self, codes, **kw):
        super().__init__(**kw)
        self.codes, self.starts = list(codes), []

    def api(self, path, method='GET', body=None):
        if method == 'POST' and path.endswith('/start'):
            self.calls.append((method, path))
            self.starts.append(1)
            return (self.codes.pop(0) if self.codes else 202), {}
        return super().api(path, method, body)


def go2(tmp, mg, mkbr, **kw):
    FakeGW.script = {'warm': True, 'fail_jobs': 0, 'health_error': None, 'raise_on': None, 'phase': None, 'no_health': False, 'hf_gb': None, 'disk_free': 50.0, 'fatal_jobs': False, 'broken': None, 'job_hangs': False}
    clock = [0.0]
    br = mkbr(clock)
    naps = []

    def sleep(sec):
        naps.append(sec)
        clock[0] += sec
    rc = T.run(args(tmp, **kw), mg, br, gw_factory=FakeGW, sleep=sleep, clock=lambda: clock[0], hf_head=lambda p, t: 200)
    sp = os.path.join(tmp, 'out', f'summary-trial-trellis2-{kw.get("suffix", "t1")}.json')
    return rc, br, naps, (json.load(open(sp)) if os.path.exists(sp) else None)


d = tempfile.mkdtemp(prefix='tt-')
make_inputs(d)
mg = StartCodesMG([400, 202])
rc, br, naps, s = go2(d, mg, lambda c: SlowCreateBR(c, slow_s=15 * 60), suffix='c1')
ok('группа создаётся 15 мин (старое окно было 10): ждём stopped, /start идёт только после него — первый HTTP 400, второй 202, прогон идёт до конца', rc == 0 and s['stopped_by'] == 'done' and len(mg.starts) == 2
   and sum(x for x in naps[:200] if x == 5) >= 15 * 60 - 5 and 30 in naps, str((rc, mg.starts, s and s['stopped_by'])))
ok('при повторе /start пауза 30 с, стоп с проверкой — один раз', br.stops == ['trial-trellis2-c1'] and naps.count(30) == 1, str(naps[:5]))
mg = StartCodesMG([400] * 10)
rc, br, naps, s = go2(d, mg, lambda c: SlowCreateBR(c), suffix='c2')
ok('/start не принят ни разу: 1+5 попыток с паузой 30 с, потом стоп с проверкой и stopped_by=start_failed (а не тихое ожидание у остановленной группы)', rc == 1 and len(mg.starts) == 6 and naps.count(30) == 5
   and s['stopped_by'] == 'start_failed' and s['stop_verified'] and br.stops == ['trial-trellis2-c2'] and s['running_s'] == 0.0, str((rc, len(mg.starts), s and s['stopped_by'])))
mg = StartCodesMG([202])
rc, br, naps, s = go2(d, mg, lambda c: SlowCreateBR(c, stuck=True), suffix='c3', create_wait_min=2)
ok('группа так и не стала stopped за --create-wait-min → /start не шлём, стоп с проверкой, stopped_by=create_timeout', rc == 1 and mg.starts == [] and s['stopped_by'] == 'create_timeout' and br.stops == ['trial-trellis2-c3'], str((rc, mg.starts, s and s['stopped_by'])))
ok('по умолчанию ждём stopped 30 минут', T.CREATE_WAIT_MIN == 30 and T.START_RETRIES == 5 and T.START_RETRY_S == 30)


print('[5] текстурные модели: несколько товаров в одной группе, у каждого своя форма (T-20261119-06/5/2)')
import base64  # noqa: E402
cat = tempfile.mkdtemp(prefix='shp-')
for fn, data in (('a_1-1024-42-0.clean2.glb', b'glTF-A2'), ('a_1-1024-42-0.clean.glb', b'glTF-A1'), ('b_2-1024-42-0.clean.glb', b'glTF-B1')):
    open(os.path.join(cat, fn), 'wb').write(data)
ok('форма из каталога: clean2, если есть, иначе clean; нет ни той ни другой — None', T.find_shape(cat, 'a:1')[0].endswith('a_1-1024-42-0.clean2.glb') and T.find_shape(cat, 'b:2')[0].endswith('b_2-1024-42-0.clean.glb')
   and 'clean2' in T.find_shape(cat, 'a:1')[1] and T.find_shape(cat, 'c:3') is None)
NSx = types.SimpleNamespace
r_ok, why = T.resolve_shapes(NSx(model='supratex', texture_mesh=None, shape_dir=cat), ['a:1', 'b:2'])
ok('resolve_shapes: два товара — у каждого своя форма', why == '' and list(r_ok) == ['a:1', 'b:2'] and r_ok['a:1'].endswith('.clean2.glb') and r_ok['b:2'].endswith('.clean.glb'), str((r_ok, why)))
r_no, why = T.resolve_shapes(NSx(model='supratex', texture_mesh=None, shape_dir=cat), ['a:1', 'c:3', 'd:4'])
ok('resolve_shapes: формы нет у двух из трёх — отказ, названы ВСЕ без формы', r_no is None and 'c:3' in why and 'd:4' in why and 'a:1' not in why.split('у товаров:')[1], why)
ok('resolve_shapes: нет ни --shape-dir, ни --texture-mesh / оба сразу / --texture-mesh при двух товарах / файла нет — отказ',
   all(T.resolve_shapes(NSx(model='mvpainter', **kw), sk)[0] is None for kw, sk in (
       ({'texture_mesh': None, 'shape_dir': None}, ['a:1']), ({'texture_mesh': os.path.join(cat, 'a_1-1024-42-0.clean.glb'), 'shape_dir': cat}, ['a:1']),
       ({'texture_mesh': os.path.join(cat, 'a_1-1024-42-0.clean.glb'), 'shape_dir': None}, ['a:1', 'b:2']), ({'texture_mesh': '/нет/такого.glb', 'shape_dir': None}, ['a:1']),
       ({'texture_mesh': None, 'shape_dir': cat}, []))))
one_ok, _ = T.resolve_shapes(NSx(model='mvpainter', texture_mesh=os.path.join(cat, 'a_1-1024-42-0.clean.glb'), shape_dir=None), ['a:1'])
ok('прежний способ: --texture-mesh при одном товаре работает', one_ok == {'a:1': os.path.join(cat, 'a_1-1024-42-0.clean.glb')})


class RecGW(FakeGW):
    """Шлюз, запоминающий тело каждого задания: какая форма (`texture_mesh_b64`) уехала с каким job_id."""
    bodies: list = []

    def call(self, method, path, body=None, timeout=60, raw=False):
        if path == '/generate':
            RecGW.bodies.append((body['job_id'], body.get('texture_mesh_b64')))
        return super().call(method, path, body, timeout, raw)


d = tempfile.mkdtemp(prefix='tt-')
make_inputs(d, ('a:1', 'b:2', 'c:3'))
mg0 = FakeMG()
for model in ('supratex', 'mvpainter', 'mvadapter-i2tex', 'pixal3d-tex'):
    mg0 = FakeMG()
    rc, mg0, br0, _ = go(d, mg=mg0, model=model, skus=['a:1', 'c:3'], shape_dir=cat, texture_mesh=None, tex_align='fit', suffix='r-' + model)
    ok(f'{model}: форма есть не у всех (нет у c:3) — отказ (код 2) ДО группы: к Salad ни одного обращения, остановка не нужна', rc == 2 and mg0.calls == [] and br0.stops == [], str((rc, mg0.calls)))
mg1 = FakeMG()
rc, mg1, br1, _ = go(d, mg=mg1, model='supratex', skus=['a:1', 'b:2'], shape_dir=cat, texture_mesh=None, apply=False, suffix='dry')
ok('сухой прогон двух товаров: код 0, ничего не создано', rc == 0 and not [c for c in mg1.calls if c[0] in ('POST', 'PATCH')])
buf5 = io.StringIO()
with __import__('contextlib').redirect_stdout(buf5):
    go(d, model='supratex', skus=['a:1', 'b:2'], shape_dir=cat, texture_mesh=None, apply=False, mem_mb=None, suffix='dry2')
ok('сухой прогон: два задания (по товару), общая группа trial-supratex-dry2, память группы 49152', buf5.getvalue().count('  задание ') == 2 and 'a_1-1024-42-0-supra' in buf5.getvalue()
   and 'b_2-1024-42-0-supra' in buf5.getvalue() and 'trial-supratex-dry2' in buf5.getvalue() and '"memory": 49152' in buf5.getvalue(), buf5.getvalue()[:300])
buf6 = io.StringIO()
with __import__('contextlib').redirect_stdout(buf6):
    rc, *_ = go(d, model='pixal3d-tex', skus=['a:1', 'b:2'], shape_dir=cat, texture_mesh=None, tex_align='fit,official', apply=False, suffix='dry3')
ok('pixal3d-tex: два товара × два варианта кадрирования = четыре задания в одной группе', rc == 0 and buf6.getvalue().count('  задание ') == 4, buf6.getvalue()[-300:])

RecGW.bodies = []
rc, mg2, br2, _ = go(d, model='supratex', skus=['a:1', 'b:2'], shape_dir=cat, texture_mesh=None, gw=RecGW, suffix='m1')
sm = json.load(open(os.path.join(d, 'out', 'summary-trial-supratex-m1.json')))
got = dict(RecGW.bodies)
ok('боевой ход, два товара в ОДНОЙ группе: группа создана и остановлена с проверкой ровно один раз, оба задания выполнены', rc == 0 and [c for c in mg2.calls if c == ('POST', '')] == [('POST', '')] and br2.stops == ['trial-supratex-m1']
   and sm['stopped_by'] == 'done' and sm['stop_verified'] and len(sm['jobs']) == 2, str((rc, br2.stops, sm['stopped_by'])))
ok('в каждое задание уехала СВОЯ форма: a:1 — clean2 (A2), b:2 — clean (B1); тела разные',
   got.get('a_1-1024-42-0-supra') == base64.b64encode(b'glTF-A2').decode() and got.get('b_2-1024-42-0-supra') == base64.b64encode(b'glTF-B1').decode() and len(set(got.values())) == 2, str(got))
ok('итог по товару (by_sku): статус, id задания, файл результата; результаты — по товару', set(sm['by_sku']) == {'a:1', 'b:2'} and all(v['status'] == 'done' and v['glb'] for v in sm['by_sku'].values())
   and os.path.exists(os.path.join(d, 'out', 'trial-supratex', 'x')) is False and sm['by_sku']['a:1']['job_id'] == 'a_1-1024-42-0-supra', str(sm['by_sku']))
RecGW.bodies = []
rc, mg3, br3, _ = go(d, model='supratex', skus=['a:1', 'b:2'], shape_dir=cat, texture_mesh=None, gw=RecGW, script={'fail_jobs': 1}, suffix='m2')
sm = json.load(open(os.path.join(d, 'out', 'summary-trial-supratex-m2.json')))
ok('первый товар упал, второй всё равно идёт: итог по товару — failed с причиной и done; один стоп с проверкой', sm['by_sku']['a:1']['status'] == 'failed' and sm['by_sku']['a:1']['error'] and sm['by_sku']['b:2']['status'] == 'done'
   and br3.stops == ['trial-supratex-m2'], str(sm['by_sku']))
RecGW.bodies = []
rc, mg4, br4, _ = go(d, model='supratex', skus=['a:1', 'b:2'], shape_dir=cat, texture_mesh=None, gw=RecGW, script={'fail_jobs': 1, 'fatal_jobs': True}, suffix='m3')
sm = json.load(open(os.path.join(d, 'out', 'summary-trial-supratex-m3.json')))
ok('фатальная ошибка CUDA на первом товаре: группа гасится сразу, второй — not_run (в итоге по товару это видно), а не «пропал»', sm['stopped_by'] == 'worker_broken' and sm['by_sku']['a:1']['status'] == 'failed'
   and sm['by_sku']['b:2']['status'] == 'not_run' and br4.stops == ['trial-supratex-m3'], str(sm['by_sku']))
RecGW.bodies = []
rc, mg5, br5, _ = go(d, model='supratex', skus=['a:1'], texture_mesh=os.path.join(cat, 'b_2-1024-42-0.clean.glb'), gw=RecGW, suffix='m4')
ok('прежний способ (--texture-mesh, один товар) по-прежнему едет формой в задании', rc == 0 and dict(RecGW.bodies).get('a_1-1024-42-0-supra') == base64.b64encode(b'glTF-B1').decode(), str(RecGW.bodies)[:200])


print('[6] отказы по категориям и память по товару (T-20261119-06/6/1)')
cf = T.classify_failure
ok('категории: UVAtlas (в любом регистре и записи), контейнер убит (код -9/137, Killed), нехватка видеопамяти, форма/развёртка изменились, CUDA, прочее',
   cf('RuntimeError: UVAtlasPack failed') == 'uvatlas' and cf('uvatlas: bad') == 'uvatlas' and cf('дочерний процесс завершился, код -9 (−9 = убит ядром)') == 'oom_ram' and cf('exit code 137') == 'oom_ram'
   and cf('Killed') == 'oom_ram' and cf('CUDA out of memory.', {'kind': 'oom'}) == 'oom_gpu' and cf('x', {'kind': 'oom'}) == 'oom_gpu' and cf('ShapeChanged: развёртка изменилась: 3e-2') == 'shape_changed'
   and cf('RuntimeError: CUDA driver error', {'fatal': True}) == 'cuda' and cf('ValueError: форма: нет мешей') == 'other' and cf(None) == 'other')
ok('приоритеты: UVAtlas важнее прочего, убитый контейнер важнее «CUDA» в том же тексте', cf('CUDA out of memory in UVAtlas') == 'uvatlas' and cf('CUDA context lost; код -9') == 'oom_ram')
jm = T.job_mem({'metrics': {'peak_vram_gb': 18.5, 'peak_rss_gb': 21.0, 'peak_cgroup_gb': 27.5}}, 32.0)
ok('пики из метрик done: видео, процесс, группа и лимит группы', jm == {'peak_vram_gb': 18.5, 'peak_rss_gb': 21.0, 'peak_cgroup_gb': 27.5, 'mem_limit_gb': 32.0}, str(jm))
jf = T.job_mem({'diag': {'peak_rss_gb': 30.5, 'stage_mem': {'start': {'peak_allocated_gb': 1.0, 'cgroup_gb': 12.0}, 'views': {'peak_allocated_gb': 14.0, 'cgroup_gb': 29.0}}, 'mem': {'peak_allocated_gb': 2.0, 'cgroup_gb': 30.5}}}, 32.0)
ok('пики упавшего задания — из диагностики воркера (стадии до падения + текущий замер)', jf == {'peak_vram_gb': 14.0, 'peak_rss_gb': 30.5, 'peak_cgroup_gb': 30.5, 'mem_limit_gb': 32.0}, str(jf))
ok('нет данных — None, а не ноль', T.job_mem({}, 32.0) == {'peak_vram_gb': None, 'peak_rss_gb': None, 'peak_cgroup_gb': None, 'mem_limit_gb': 32.0})


class MemGW(FakeGW):
    """Метрики задания с памятью; второй товар падает «убит ядром» (код −9)."""
    def call(self, method, path, body=None, timeout=60, raw=False):
        c, r = super().call(method, path, body, timeout, raw)
        if path.startswith('/job/') and r.get('status') == 'done':
            r = {**r, 'metrics': {**r['metrics'], 'peak_vram_gb': 17.0, 'peak_rss_gb': 22.5, 'peak_cgroup_gb': 26.0}}
        if path.startswith('/job/') and r.get('status') == 'failed':
            r = {**r, 'error': 'дочерний процесс завершился, код -9 (−9 = убит ядром, почти наверняка нехватка памяти)', 'diag': {'kind': 'other', 'fatal': False, 'peak_rss_gb': 31.2,
                                                                                                                            'stage_mem': {'views': {'peak_allocated_gb': 15.0, 'cgroup_gb': 31.9}}}}
        return c, r


d = tempfile.mkdtemp(prefix='tt-')
make_inputs(d, ('a:1', 'b:2', 'c:3'))
cat2 = tempfile.mkdtemp(prefix='shp-')
for k in ('a_1', 'b_2', 'c_3'):
    open(os.path.join(cat2, k + '-1024-42-0.clean2.glb'), 'wb').write(b'glTF')
buf7 = io.StringIO()
with __import__('contextlib').redirect_stdout(buf7):
    rc, mg7, br7, _ = go(d, model='mvadapter-i2tex', skus=['a:1', 'b:2', 'c:3'], shape_dir=cat2, texture_mesh=None, gw=MemGW, script={'fail_jobs': 0}, mem_mb=None, fail_streak=9, suffix='q1')
sm7 = json.load(open(os.path.join(d, 'out', 'summary-trial-mvadapter-i2tex-q1.json')))
ok('итог по товару: пики видео/процесса/группы и лимит группы (32 ГБ) у каждого товара', all(sm7['by_sku'][k]['peak_rss_gb'] == 22.5 and sm7['by_sku'][k]['peak_cgroup_gb'] == 26.0 and sm7['by_sku'][k]['peak_vram_gb'] == 17.0
                                                                                      and sm7['by_sku'][k]['mem_limit_gb'] == 32.0 for k in ('a:1', 'b:2', 'c:3')), str(sm7['by_sku']))
ok('счётчик отказов в summary: все категории и not_run есть, при успехе — нули', sm7['fail_classes'] == {'uvatlas': 0, 'oom_gpu': 0, 'oom_ram': 0, 'shape_changed': 0, 'cuda': 0, 'other': 0, 'not_run': 0}, str(sm7['fail_classes']))
ok('в строке «товар …» память видна: видео, процесс, группа из лимита', 'видео 17.0 ГБ, процесс 22.5 ГБ, группа 26.0 из 32.0 ГБ' in buf7.getvalue() and '"fail_classes"' in buf7.getvalue())
buf8 = io.StringIO()
with __import__('contextlib').redirect_stdout(buf8):
    rc, mg8, br8, _ = go(d, model='mvadapter-i2tex', skus=['a:1', 'b:2', 'c:3'], shape_dir=cat2, texture_mesh=None, gw=MemGW, script={'fail_jobs': 2}, mem_mb=None, fail_streak=9, suffix='q2')
sm8 = json.load(open(os.path.join(d, 'out', 'summary-trial-mvadapter-i2tex-q2.json')))
ok('два отказа «убит ядром»: oom_ram = 2, остальные 0; у упавших пик процесса 31,2 ГБ и группы 31,9 ГБ из 32; у третьего done', sm8['fail_classes']['oom_ram'] == 2 and sum(sm8['fail_classes'].values()) == 2
   and sm8['by_sku']['a:1']['fail_class'] == 'oom_ram' and sm8['by_sku']['a:1']['peak_rss_gb'] == 31.2 and sm8['by_sku']['a:1']['peak_cgroup_gb'] == 31.9 and sm8['by_sku']['c:3']['status'] == 'done' and sm8['by_sku']['c:3']['fail_class'] is None, str(sm8['by_sku']['a:1']))
rc, mg9, br9, _ = go(d, model='mvadapter-i2tex', skus=['a:1', 'b:2', 'c:3'], shape_dir=cat2, texture_mesh=None, script={'fail_jobs': 3, 'fatal_jobs': True}, mem_mb=None, suffix='q3')
sm9 = json.load(open(os.path.join(d, 'out', 'summary-trial-mvadapter-i2tex-q3.json')))
ok('фатальный отказ на первом: failed 1 по своей категории, остальные два — not_run = 2', sm9['fail_classes']['not_run'] == 2 and sm9['fail_classes']['cuda'] == 1 and sum(v for k, v in sm9['fail_classes'].items() if k != 'not_run') == 1, str(sm9['fail_classes']))

print('[7] А0: --mv-keep-stages — архив стадий скачивается и раскладывается (T-20261119-47/1)')
import zipfile  # noqa: E402


def stages_zip_bytes(extra=None):
    bio = io.BytesIO()
    with zipfile.ZipFile(bio, 'w', zipfile.ZIP_STORED) as z:
        z.writestr('manifest.json', '{"error": null}')
        z.writestr('views_768/v0.png', b'PNG0')
        z.writestr('render_view0/r2048.png', b'PNG1')
        for name in (extra or []):
            z.writestr(name, b'x')
    return bio.getvalue()


class StagesGW(FakeGW):
    """Шлюз: задание отдаёт метрики с `stages` (как воркер при mv_keep_stages), `?v=stages` — архив; запоминает тела заданий и все запросы архива."""
    bodies: list = []
    zip_calls: list = []
    zip_data = b''
    zip_code = 200
    with_stages = True

    def call(self, method, path, body=None, timeout=60, raw=False):
        if path == '/generate':
            StagesGW.bodies.append(dict(body))
        if path.startswith('/glb/') and '?v=stages' in path:
            StagesGW.zip_calls.append((path, timeout))
            return StagesGW.zip_code, (StagesGW.zip_data if StagesGW.zip_code == 200 else {})
        c, r = super().call(method, path, body, timeout, raw)
        if path.startswith('/job/') and r.get('status') == 'done' and StagesGW.with_stages:
            r = {**r, 'metrics': {**r['metrics'], 'stages': {'zip': 'x.stages.zip', 'bytes': len(StagesGW.zip_data), 'files': 3}}}
        return c, r


ok('mv_options: без флага тело задания прежнее (ключа mv_keep_stages нет); с флагом — mv_keep_stages=1',
   'mv_keep_stages' not in T.mv_options(types.SimpleNamespace()) and T.mv_options(types.SimpleNamespace(mv_keep_stages=False)) == T.mv_options(types.SimpleNamespace())
   and T.mv_options(types.SimpleNamespace(mv_keep_stages=True))['mv_keep_stages'] == 1)
d7 = tempfile.mkdtemp(prefix='tt-')
make_inputs(d7, ('a:1',))
cat7 = tempfile.mkdtemp(prefix='shp-')
open(os.path.join(cat7, 'a_1-1024-42-0.clean2.glb'), 'wb').write(b'glTF')
StagesGW.bodies, StagesGW.zip_calls, StagesGW.zip_data = [], [], stages_zip_bytes()
rc, _mg, _br, _ = go(d7, model='mvadapter-i2tex', skus=['a:1'], shape_dir=cat7, texture_mesh=None, gw=StagesGW, mv_keep_stages=True, mem_mb=None, suffix='k1')
sk = json.load(open(os.path.join(d7, 'out', 'summary-trial-mvadapter-i2tex-k1.json')))
st = sk['jobs'][0].get('stages') or {}
dest = os.path.join(d7, 'out', 'a_1', 'stages')
ok('с флагом: в задание уехал mv_keep_stages=1; архив запрошен ОДИН раз тем же шлюзом (?v=stages, долгий таймаут)', rc == 0 and StagesGW.bodies[0].get('mv_keep_stages') == 1 and len(StagesGW.zip_calls) == 1
   and StagesGW.zip_calls[0][0] == '/glb/a_1-1024-42-0-mvtex?v=stages' and StagesGW.zip_calls[0][1] >= 600, str((StagesGW.bodies, StagesGW.zip_calls)))
ok('архив лёг в OUT/<ключ>/stages/ с подпапками; сам zip — рядом с GLB; в сводке — число файлов и размер', os.path.exists(os.path.join(dest, 'manifest.json')) and open(os.path.join(dest, 'views_768', 'v0.png'), 'rb').read() == b'PNG0'
   and os.path.exists(os.path.join(dest, 'render_view0', 'r2048.png')) and os.path.exists(os.path.join(d7, 'out', 'a_1-1024-42-0-mvtex.stages.zip')) and st.get('files') == 3 and st.get('bytes') == len(StagesGW.zip_data)
   and st.get('dir') == dest, str(st))
StagesGW.bodies, StagesGW.zip_calls = [], []
d8 = tempfile.mkdtemp(prefix='tt-')
make_inputs(d8, ('a:1',))
StagesGW.with_stages = False                                   # без флага воркер блока stages в метрики не кладёт
rc, _mg, _br, _ = go(d8, model='mvadapter-i2tex', skus=['a:1'], shape_dir=cat7, texture_mesh=None, gw=StagesGW, mem_mb=None, suffix='k2')
ok('без флага: ключа mv_keep_stages в теле задания нет, архив не запрашивается, папки stages нет', rc == 0 and 'mv_keep_stages' not in StagesGW.bodies[0] and StagesGW.zip_calls == [] and not os.path.exists(os.path.join(d8, 'out', 'a_1', 'stages')))
StagesGW.with_stages = True
StagesGW.zip_code, StagesGW.zip_calls = 404, []
d9 = tempfile.mkdtemp(prefix='tt-')
make_inputs(d9, ('a:1',))
rc, _mg, _br, _ = go(d9, model='mvadapter-i2tex', skus=['a:1'], shape_dir=cat7, texture_mesh=None, gw=StagesGW, mv_keep_stages=True, mem_mb=None, suffix='k3')
sk3 = json.load(open(os.path.join(d9, 'out', 'summary-trial-mvadapter-i2tex-k3.json')))
ok('архив не скачался (404): задание остаётся done, GLB на месте, причина — в сводке; группа остановлена', sk3['jobs'][0]['status'] == 'done' and os.path.exists(sk3['jobs'][0]['glb_path']) and 'HTTP 404' in str(sk3['jobs'][0].get('stages')) and sk3['stop_verified'])
StagesGW.zip_code = 200
evil = tempfile.mkdtemp(prefix='ev-')
try:
    T.save_stages(evil, 'a:1', 'j', stages_zip_bytes(['../../evil.txt']))
    ok('архив с путём вне папки — отказ, файл снаружи не создан', False)
except ValueError:
    ok('архив с путём вне папки — отказ, файл снаружи не создан', not os.path.exists(os.path.join(evil, 'evil.txt')) and not os.path.exists(os.path.join(os.path.dirname(evil), 'evil.txt')))

print('ИТОГО: ' + ('всё в норме' if not bad else f'провалов {bad}'))
sys.exit(1 if bad else 0)
