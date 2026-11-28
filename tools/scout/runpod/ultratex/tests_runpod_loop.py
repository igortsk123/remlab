#!/usr/bin/env python3
"""Тесты ЦИКЛА заданий и сторожей runpod_trial.run без сети и денег (T-178/2, 21.11): 429 «занят» — не провал, 2 провала подряд — стоп, сторож молчания, потолок денег,
ход задания из /health, строка учёта (provider=runpod), под удаляется и проверяется при любом исходе."""
import os as _rt_os  # noqa: E402
import sys as _rt_sys  # noqa: E402
_rt_sys.path.append(_rt_os.path.join(_rt_os.path.dirname(_rt_os.path.abspath(__file__)), '../..'))
import remlab_tmp  # noqa: E402,I001  — временное теста на диске и с уборкой при выходе (T-20261107-13)
remlab_tmp.use('tests_runpod_loop')
import contextlib
import io
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


GPU = {'id': 'NVIDIA H100 80GB HBM3', 'name': 'H100 SXM', 'memory': 80, 'price': 2.99, 'cloud': 'SECURE'}


class Api:
    def __init__(self):
        self.pods, self.log = [{'id': 'p1', 'status': 'RUNNING'}], []

    def call(self, method, path, body=None):
        self.log.append((method, path))
        if method == 'POST':
            return 201, {'id': 'p1', 'status': 'PROVISIONING', 'cost': 2.99}
        if method == 'DELETE':
            self.pods = []
            return 200, {}
        return 200, {'pods': self.pods}


class World:
    """Часы + воркер. busy_until — до этого момента воркер занят чужим заданием (429). dur — длительность задания; fail — задания падают; mute_after — воркер замолкает с этого момента;
    never_up — контейнер не поднимается."""
    def __init__(self, dur=100.0, fail=False, busy_until=0.0, mute_after=None, never_up=False, hang=False):
        self.t, self.dur, self.fail, self.busy_until, self.mute_after, self.never_up, self.hang = 1000.0, dur, fail, busy_until, mute_after, never_up, hang
        self.t0 = self.t
        self.jobs = {}

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += s

    def http(self, method, url, body=None, timeout=120):
        t = self.t
        if self.never_up or (self.mute_after is not None and t - self.t0 >= self.mute_after):
            return -1, {}
        if url.endswith('/health'):
            h = {'phase': 'ready', 'error': ''}
            run = [j for j, t0 in self.jobs.items() if t - t0 < self.dur]
            if run:
                h['job'] = {'id': run[0], 'elapsed_s': round(t - self.jobs[run[0]], 1), 'step': 'sampling', 'step_s': 7.0, 'done': ['перенос']}
            return 200, h
        if url.endswith('/generate'):
            if t < self.busy_until or any(t - t0 < self.dur for t0 in self.jobs.values()):
                return 429, {'error': 'занят другим заданием'}
            self.jobs[body['job_id']] = t
            return 202, {}
        if '/result/' in url:
            jid = url.rsplit('/', 1)[1]
            if self.hang or t - self.jobs[jid] < self.dur:
                return 200, {'status': 'running'}
            return 200, ({'status': 'failed', 'error': 'OOM'} if self.fail else {'status': 'done', 'metrics': {'vram_peak_gb': 62.2}})
        return 404, {}


def go(world, skus=('a', 'b'), cap=5.0, glb_ok=True, **extra):
    tmp = tempfile.mkdtemp()
    os.makedirs(tmp + '/in')
    for k in skus:
        open(f'{tmp}/{k}-hd.glb', 'wb').write(b'g')
        open(f'{tmp}/in/{k}.rgba.png', 'wb').write(b'p')
    args = types.SimpleNamespace(out=tmp + '/out', image='img', cap=cap, registry=None, pod_url='http://x', warm_timeout=3000, skus=list(skus), steps=[25], inputs=tmp + '/in',
                                 shape_dir=tmp, shape_tag='t', shape_name='{key}-hd.glb', resolution=2048, seed=42, **extra)
    T.http_json = world.http
    T.fetch_glb = (lambda url, tag, out: out + '/' + tag + '.glb') if glb_ok else (lambda url, tag, out: (_ for _ in ()).throw(OSError('нет GLB')))
    api, led, out = Api(), [], io.StringIO()
    with contextlib.redirect_stdout(out):
        res = T.run(api, args, GPU, sleep=world.sleep, now=world.now, ledger=lambda rec: led.append(rec))
    return res, api, led, out.getvalue()


# 1. воркер занят чужим заданием (429) — НЕ провал: ждём, потом оба задания готовы
res, api, led, out = go(World(busy_until=1000 + 400))
check('429 «занят»: оба задания готовы, не fail_streak', res.get('jobs_done') == 2 and res.get('stopped_by') == 'done' and not res.get('error'))
check('429: в журнале «жду, не провал», «отказ» нет', 'воркер занят (429)' in out and 'отказ' not in out)
check('под удалён и стоп проверен', res['stop_verified'] is True and ('DELETE', '/pods/p1') in api.log)

# 2. два задания подряд упали → стоп fail_streak, под гасится
res, api, led, out = go(World(fail=True), skus=('a', 'b', 'c'))
check('2 провала подряд → fail_streak, третье не гонялось', res.get('stopped_by') == 'fail_streak' and len(res['per_sku']) == 2 and res['stop_verified'] is True)

# 3. провал, потом успех — серия сбрасывается
w2 = World()
o2 = w2.http
w2.http = lambda m, u, b=None, timeout=120: ((200, {'status': 'failed', 'error': 'x'}) if (u.endswith('a-s25') and o2(m, u, b, timeout)[1].get('status') == 'done') else o2(m, u, b, timeout))
res, api, led, out = go(w2, skus=('a', 'b', 'c'))
check('провал → успех → успех: серия сброшена, стоп не по серии', res.get('stopped_by') == 'done' and res.get('jobs_done') == 2 and res['per_sku']['a-s25']['status'] == 'failed')

# 4. воркер замолчал посреди задания (>10 мин) → сторож молчания, под гасится
res, api, led, out = go(World(dur=5000, mute_after=300))
check('молчание >10 мин → гашение, причина в итоге', 'молчит' in res.get('error', '') and res['stop_verified'] is True)

# 5. контейнер не поднялся вовсе (boot 15 + 10 мин) → гашение
res, api, led, out = go(World(never_up=True))
check('контейнер не поднялся → гашение через boot+silence', 'не отвечает' in res.get('error', '') and res['stop_verified'] is True and res.get('uptime_s', 0) < 40 * 60)

# 6. потолок денег: задание бесконечное → стоп по потолку (цена 2,99/ч; потолок $1 = 20 мин)
res, api, led, out = go(World(hang=True, dur=10 ** 9), cap=1.0)
check('вечное задание: стоп по потолку денег, расход ≤ потолок + шаг опроса', 'потолок' in res.get('error', '') and res['stop_verified'] is True and res['cost_usd_est'] <= 1.1)

# 7. ход задания из /health в журнале
res, api, led, out = go(World(dur=200), skus=('a',))
check('ход задания: шаг «sampling» в журнале', 'ход задания a-s25: шаг «sampling»' in out)

# 8. учёт: provider=runpod, цена, расход, причина
res, api, led, out = go(World(dur=100), skus=('a',))
check('учёт: одна строка provider=runpod с ценой/расходом/причиной', len(led) == 1 and led[0]['provider'] == 'runpod' and led[0]['price_usd_h'] == 2.99 and led[0]['stopped_by'] == 'done'
      and led[0]['cost_usd_est'] == res['cost_usd_est'] and led[0]['jobs_done'] == 1 and led[0]['stop_verified'] is True)
res, api, led, out = go(World(never_up=True))
check('учёт пишется и при сбое', len(led) == 1 and led[0]['stopped_by'] == 'error' and led[0]['cost_usd_est'] > 0)

# 9. GLB не скачался — провал задания (не «готово»)
res, api, led, out = go(World(dur=100), skus=('a', 'b'), glb_ok=False)
check('GLB не получен: провал задания, 2 подряд → стоп', res['per_sku']['a-s25']['status'] == 'glb_not_received' and res.get('stopped_by') == 'fail_streak' and res['stop_verified'] is True)

# 10. настоящая ошибка приёма (500) — провал, не «занят»
w3 = World()
o3 = w3.http
w3.http = lambda m, u, b=None, timeout=120: ((500, {'error': 'boom'}) if u.endswith('/generate') else o3(m, u, b, timeout))
res, api, led, out = go(w3, skus=('a', 'b', 'c'))
check('500 при приёме — провал: 2 подряд → fail_streak', res.get('stopped_by') == 'fail_streak' and res['stop_verified'] is True)

print('ВСЁ ЗЕЛЁНОЕ' if not fails else f'ПРОВАЛЕНО: {fails}')
sys.exit(1 if fails else 0)
