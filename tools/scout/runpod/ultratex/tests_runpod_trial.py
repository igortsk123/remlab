#!/usr/bin/env python3
"""Тесты драйвера runpod_trial.py без сети и без денег: подмена транспорта RunPod и HTTP воркера."""
import json
import os
import sys
import tempfile
import types

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import runpod_trial as T  # noqa: E402

fails = []


def check(name, cond):
    print(('ok   ' if cond else 'FAIL ') + name)
    if not cond:
        fails.append(name)


CAT = {'gpus': [
    {'id': 'NVIDIA H100 80GB HBM3', 'name': 'H100 SXM', 'memory': 80, 'secure': True, 'price': {'secure': 2.99}, 'availability': 'HIGH'},
    {'id': 'NVIDIA A100 80GB PCIe', 'name': 'A100 PCIe', 'memory': 80, 'secure': True, 'price': {'secure': 2.09}, 'availability': 'LOW'},
    {'id': 'NVIDIA A100-SXM4-80GB', 'name': 'A100 SXM', 'memory': 80, 'secure': True, 'price': {'secure': 1.5}, 'availability': 'NONE'},
    {'id': 'NVIDIA H200', 'name': 'H200', 'memory': 141, 'secure': True, 'price': {'secure': 1.0}, 'availability': 'HIGH'},
    {'id': 'NVIDIA RTX 4090', 'name': 'RTX 4090', 'memory': 24, 'secure': True, 'price': {'secure': 0.5}, 'availability': 'HIGH'},
]}
g = T.pick_gpu(CAT)
check('карта: самая дешёвая в наличии A100/H100 80 ГБ (не H200, не 4090, не «нет в наличии»)', g and g['id'] == 'NVIDIA A100 80GB PCIe' and g['price'] == 2.09)
check('нет подходящей → None', T.pick_gpu({'gpus': CAT['gpus'][3:]}) is None)
check('срок жизни ≤ 90 мин и ≤ 85 % потолка', T.lifetime_for_cap(5, 2.09) == 5400 and T.lifetime_for_cap(2, 2.09) == int(2 / 2.09 * 3600 * 0.85) and T.lifetime_for_cap(0.01, 2.09) == 300)
body = T.pod_body(g, 'img:x', 5.0, 'hf_SECRET')
check('тело: образ, порт, карта, срок', body['image'] == 'img:x' and body['ports'] == ['8000/http'] and body['gpu']['id'] == g['id'] and body['env']['MAX_LIFETIME_S'] == '5400')
check('печать тела скрывает токен', 'hf_SECRET' not in json.dumps(T.shown_body(body)) and 'hf_SECRET' in json.dumps(body))
os.environ['RUNPOD_API_KEY'] = 'rpa_SECRET'
check('redact прячет ключ', 'rpa_SECRET' not in T.redact('x rpa_SECRET y'))

# ---- терминация: удалён с первой попытки / не удаляется
class Fake:
    def __init__(self, stuck=False):
        self.pods, self.log, self.stuck = [{'id': 'p1', 'status': 'RUNNING'}], [], stuck

    def call(self, method, path, body=None):
        self.log.append((method, path))
        if method == 'POST':
            return 201, {'id': 'p1', 'status': 'PROVISIONING', 'cost': 2.09}
        if method == 'DELETE':
            if not self.stuck:
                self.pods = []
            return 200, {}
        return 200, {'pods': self.pods}


f = Fake()
check('стоп подтверждается', T.terminate_and_verify(f, 'p1', sleep=lambda s: None) is True and ('DELETE', '/pods/p1') in f.log)
f2 = Fake(stuck=True)
check('не удалился → стоп НЕ подтверждён (громко)', T.terminate_and_verify(f2, 'p1', tries=2, sleep=lambda s: None) is False)

# ---- прогон на подмене воркера: при ошибке под всё равно гасится
args = types.SimpleNamespace(out=tempfile.mkdtemp(), image='img', cap=5.0, registry=None, pod_url='http://x', warm_timeout=60, skus=['1:2'], steps=[25], inputs='/nonexistent',
                             shape_dir='/nonexistent', shape_tag='clean2', resolution=2048, seed=42)
T.http_json = lambda method, url, body=None, timeout=120: (200, {'phase': 'ready'})
f3 = Fake()
clock = [0.0]
res = T.run(f3, args, g, sleep=lambda s: None, now=lambda: clock[0])
check('нет входного файла → ошибка записана, под удалён, стоп проверен', 'error' in res and res['stop_verified'] is True and ('DELETE', '/pods/p1') in f3.log)
check('итог записан без ключей', os.path.exists(os.path.join(args.out, 'summary-ultratex.json')) and 'rpa_SECRET' not in open(os.path.join(args.out, 'summary-ultratex.json')).read())

# ---- потолок денег: воркер не готовится → под гасится по потолку
T.http_json = lambda method, url, body=None, timeout=120: (200, {'phase': 'loading'})
f4 = Fake()
t = [0.0]


def now4():
    t[0] += 1800.0           # +30 мин за вызов: $1,04 за вызов при $2,09/ч
    return t[0]


args.cap = 1.0
args.warm_timeout = 10**9
res4 = T.run(f4, args, g, sleep=lambda s: None, now=now4)
check('потолок денег срабатывает до готовности, под погашен', 'потолок' in res4.get('error', '') and res4['stop_verified'] is True)


# ---- User-Agent (Cloudflare прокси RunPod режет Python-urllib → 403) и режим --pod-id
import urllib.request as _ur
seen = []


class _R:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return b'{"phase": "ready"}'


_orig = _ur.urlopen
_ur.urlopen = lambda req, timeout=0: (seen.append(req.get_header('User-agent')), _R())[1]
import importlib
importlib.reload(T)
T.http_json('GET', 'https://x-8000.proxy.runpod.net/health')
_ur.urlopen = _orig
check('запрос к прокси идёт с User-Agent как у curl (не Python-urllib)', seen == ['curl/8.5.0'])


class FakeExisting(Fake):
    def call(self, method, path, body=None):
        if method == 'GET' and path == '/pods/p1':
            self.log.append((method, path))
            return 200, {'id': 'p1', 'status': 'RUNNING', 'cost': 2.09, 'createdAt': '1970-01-01T00:00:00Z'}
        return super().call(method, path, body)


args2 = types.SimpleNamespace(out=tempfile.mkdtemp(), image='img', cap=5.0, registry=None, pod_url='http://x', warm_timeout=60, skus=['1:2'], steps=[25], inputs='/nonexistent',
                              shape_dir='/nonexistent', shape_tag='clean2', resolution=2048, seed=42, pod_id='p1')
T.http_json = lambda method, url, body=None, timeout=120: (200, {'phase': 'ready'})
f5 = FakeExisting()
res5 = T.run(f5, args2, {'id': 'existing', 'price': 0.0, 'cloud': 'SECURE'}, sleep=lambda s: None, now=lambda: 1000.0)
check('--pod-id: под не создаётся (нет POST), цена из API, в конце удалён и стоп проверен',
      not any(m == 'POST' for m, _ in f5.log) and res5.get('price_per_h') == 2.09 and res5['stop_verified'] is True and ('DELETE', '/pods/p1') in f5.log)

# ---- --jobs: точный порядок и состав заданий (товар@шаги)
seen_jobs = []
T.Api = lambda key: Fake()
T.run = lambda api, a, gpu, **kw: (seen_jobs.append((list(a.skus), dict(a.steps_by_sku))), {'per_sku': {}, 'stop_verified': True})[1]
_mi = T.missing_inputs
T.missing_inputs = lambda a: []
T.main(['--pod-id', 'p1', '--cap', '3', '--jobs', 'B@25', 'B@8', 'A@8'])
T.missing_inputs = _mi
check('--jobs: комод s25, комод s8, диван s8 — без лишнего «диван s25»', seen_jobs == [(['B', 'A'], {'B': [25, 8], 'A': [8]})])

# ---- шаблон имени формы и проверка входных файлов до создания пода
d = tempfile.mkdtemp()
os.makedirs(d + '/in')
open(d + '/B-hd.glb', 'wb').write(b'x')
open(d + '/in/B.rgba.png', 'wb').write(b'x')
a3 = types.SimpleNamespace(skus=['B'], shape_dir=d, shape_tag='clean2', shape_name='{key}-hd.glb', inputs=d + '/in')
check('шаблон имени формы: файл найден', T.missing_inputs(a3) == [] and T.shape_path(a3, 'B') == d + '/B-hd.glb')
a3.shape_name = None
check('умолчание {key}-1024-42-0.{tag}.glb: нет файла → в списке пропавших', T.missing_inputs(a3) == [d + '/B-1024-42-0.clean2.glb'])

# ---- платное без --cap не стартует
T.Api = lambda key: Fake()
check('платное без --cap отказывает', T.main(['--skus', '1:2']) == 2)
check('--cap > 5 отказывает', T.main(['--skus', '1:2', '--cap', '9']) == 2)

print('ВСЁ ЗЕЛЁНОЕ' if not fails else f'ПРОВАЛЕНО: {fails}')
sys.exit(1 if fails else 0)
