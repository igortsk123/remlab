#!/usr/bin/env python3
"""Тесты ЦИКЛА заданий `kit_driver.run_probe` без сети и денег (подставные Salad, шлюз, часы). Запуск: python3 tools/scout/salad/tests_kit_loop.py
Закрывают дефекты пробы p4 (21.11): (1) 429 «занят» на следующем задании сжигал серию провалов; (2) задание срезалось на 30-й минуте раньше потолка пробы;
(3) ход задания из /health воркера не был виден драйверу."""
import argparse
import contextlib
import io
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import kit_driver as KD  # noqa: E402

FAILS = []


def check(cond, msg):
    print(('ok   ' if cond else 'FAIL ') + msg)
    if not cond:
        FAILS.append(msg)


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


class MG:
    def __init__(self):
        self.created = False

    def env_from_file(self):
        os.environ['SALAD_API_KEY'] = 'SECRET-SALAD'

    def ghcr_auth(self):
        return {'basic': {'username': 'u', 'password': 'SECRET-GHCR'}}

    def api(self, path, method='GET', body=None):
        if path == '' and method == 'GET':
            return 200, {'items': []}
        if method == 'GET':
            return (200, {'networking': {'dns': 'g.example'}}) if self.created else (404, {})
        if method == 'POST' and path == '':
            self.created = True
            return 201, {}
        return 202, {}


class BR:
    def __init__(self, clock, running_after=60.0):
        self.clock, self.t0, self.running_after, self.stopped = clock, None, running_after, 0

    def group_state(self, name):
        return 200, ('stopped' if self.t0 is None else 'running'), 1

    def instances(self, name):
        if self.t0 is None:
            return 200, []
        up = self.clock() - self.t0 >= self.running_after
        return 200, [{'state': 'running' if up else 'creating', 'started': up}]

    def stop_and_verify(self, name):
        self.stopped += 1
        return True


class GW:
    """Шлюз воркера: ready сразу; одно задание за раз (как настоящий воркер: второе → 429); в /health — ход задания."""
    def __init__(self, clock, job_s):
        self.clock, self.jobs, self.dur = clock, {}, {}
        self.durs = list(job_s) if isinstance(job_s, (list, tuple)) else [job_s]       # длительность n-го принятого задания (последняя — для остальных)
        self.t0 = clock()

    def busy(self, t):
        return any(t - t0 < self.dur[j] for j, t0 in self.jobs.items())

    def call(self, method, path, body=None, timeout=60, raw=False):
        t = self.clock()
        if path == '/health':
            h = {'phase': 'ready', 'version': 'v', 'error': '', 'root_gb': 1.0}
            run = [j for j, t0 in self.jobs.items() if t - t0 < self.dur[j]]
            if run:
                h['job'] = {'id': run[0], 'elapsed_s': round(t - self.jobs[run[0]], 1), 'step': 'sampling', 'step_s': 12.0, 'done': ['перенос encoder→gpu']}
            return 200, h
        if path == '/generate':
            if self.busy(t):
                return 429, {'error': 'занят другим заданием'}
            self.jobs[body['job_id']] = t
            self.dur[body['job_id']] = self.durs[min(len(self.jobs) - 1, len(self.durs) - 1)]
            return 202, {}
        if path.startswith('/result/'):
            jid = path.split('/')[2]
            return 200, ({'status': 'running'} if t - self.jobs[jid] < self.dur[jid] else {'status': 'done'})
        return 404, {}


def make_spec(keys):
    def submit(gw, k, t):
        c, r = gw.call('POST', '/generate', {'job_id': f'{k}-{int(t)}'})
        return ({'key': k, 'id': f'{k}-{int(t)}', 't0': t}, {}) if c == 202 else (None, {'http': c, 'detail': r})

    def poll(gw, cur, t):
        c, r = gw.call('GET', f'/result/{cur["id"]}')
        return ('done', {'x': 1}) if r.get('status') == 'done' else ('running', {})
    return KD.Spec(prefix='kit-loop', card='RTX X', model='m', jobs=keys.split(','), build_body=lambda n, c, a: {'name': n}, submit=submit, poll=poll)


LEDGER = []


def drive(tmp, keys, job_s, job_min, price=0.6, **kw):
    clock = Clock()
    mg, br = MG(), BR(clock)
    KD.gpu_class = lambda MG_, name, tier, fetch=None: ('cls', price)
    orig = mg.api

    def api(path, method='GET', body=None):
        r = orig(path, method, body)
        if method == 'POST' and path.endswith('/start'):
            br.t0 = clock()
        return r
    mg.api = api
    d = dict(image='x@sha256:1', suffix='t', tier='high', apply=True, cap=4.0, probe_cap=1.0, max_min=600, running_min=30, start_min=20, health_min=8, ready_min=30,
             stall_min=5, stall_gb=0.05, job_min=job_min, out=os.path.join(tmp, 'out'))
    d.update(kw)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = KD.run_probe(argparse.Namespace(**d), mg, br, make_spec(keys), gw_factory=lambda base, key: GW(clock, job_s), sleep=clock.sleep, clock=clock,
                          slot_check=lambda: None, image_check=lambda *x, **k: (True, 'ok', 1.0), ledger=lambda rec: LEDGER.append(rec))
    p = os.path.join(tmp, 'out', 'summary-kit-loop-t.json')
    return rc, (json.load(open(p)) if os.path.exists(p) else {}), out.getvalue(), br


# 1. p4: задание срезано по --job-min, нода ещё считает → 429 на следующем НЕ провал: ключ в очередь, ждём; серия не горит
with tempfile.TemporaryDirectory() as tmp:
    rc, summ, out, br = drive(tmp, 'a,b', job_s=[900.0, 300.0], job_min=10)
    st = {k: v.get('status') for k, v in summ.get('jobs', {}).items()}
    check(summ.get('stopped_by') != 'fail_streak' and st.get('a') == 'timeout' and st.get('b') == 'done', f'429 «занят» не провал: a срезано, b принято после освобождения ноды и готово ({summ.get("stopped_by")}, {st})')
    check('нода занята (429)' in out and 'не принято' not in out, '429: в журнале «жду, не провал»; «не принято» нет')
    check(summ.get('failed') == 1 and br.stopped >= 1 and summ.get('stop_verified'), 'failed=1 (только срезанное), стоп с проверкой')

# 2. job_min=0 (по умолчанию): задание живёт до потолка пробы, не срезается на 30-й минуте
with tempfile.TemporaryDirectory() as tmp:
    rc, summ, out, br = drive(tmp, 'a', job_s=3000.0, job_min=0)
    check(summ.get('jobs', {}).get('a', {}).get('status') == 'done' and 'снимаю' not in out, f'job_min=0: задание 50 мин дожило до готовности ({summ.get("jobs")})')

# 3. потолок пробы — последняя защита: вечное задание + job_min=0 → стоп по потолку, не вечный счёт
with tempfile.TemporaryDirectory() as tmp:
    rc, summ, out, br = drive(tmp, 'a', job_s=10 ** 9, job_min=0)
    check(summ.get('stopped_by') == 'probe_cap' and summ.get('stop_verified') and summ.get('cost_usd_est', 9) <= 1.05, f'вечное задание: стоп по потолку ({summ.get("stopped_by")}, ${summ.get("cost_usd_est")})')

# 4. явный --job-min по-прежнему срезает (и это один провал, не серия из двух)
with tempfile.TemporaryDirectory() as tmp:
    rc, summ, out, br = drive(tmp, 'a', job_s=10 ** 9, job_min=10)
    check(summ.get('jobs', {}).get('a', {}).get('status') == 'timeout' and 'дольше 10 мин' in out, 'явный --job-min срезает задание')

# 5. настоящая ошибка приёма (не 429) по-прежнему считается провалом: две подряд → стоп
with tempfile.TemporaryDirectory() as tmp:
    class Bad(GW):
        def call(self, method, path, body=None, timeout=60, raw=False):
            return (500, {'error': 'boom'}) if path == '/generate' else super().call(method, path, body, timeout, raw)
    clock = Clock()
    mg, br = MG(), BR(clock)
    KD.gpu_class = lambda MG_, name, tier, fetch=None: ('cls', 0.6)
    orig = mg.api
    mg.api = lambda path, method='GET', body=None: (setattr(br, 't0', clock()) if (method == 'POST' and path.endswith('/start')) else None) or orig(path, method, body)
    a = argparse.Namespace(image='x@sha256:1', suffix='t', tier='high', apply=True, cap=4.0, probe_cap=1.0, max_min=600, running_min=30, start_min=20, health_min=8, ready_min=30,
                           stall_min=5, stall_gb=0.05, job_min=0, out=os.path.join(tmp, 'out'))
    with contextlib.redirect_stdout(io.StringIO()):
        rc = KD.run_probe(a, mg, br, make_spec('a,b'), gw_factory=lambda base, key: Bad(clock, 100.0), sleep=clock.sleep, clock=clock, slot_check=lambda: None,
                          image_check=lambda *x, **k: (True, 'ok', 1.0), ledger=lambda rec: LEDGER.append(rec))
    summ = json.load(open(os.path.join(tmp, 'out', 'summary-kit-loop-t.json')))
    check(summ.get('stopped_by') == 'fail_streak' and summ.get('failed') == 2 and summ.get('stop_verified'), f'ошибка 500 при приёме: две подряд → fail_streak ({summ.get("stopped_by")})')

# 6. ход задания из /health воркера виден в журнале драйвера
with tempfile.TemporaryDirectory() as tmp:
    rc, summ, out, br = drive(tmp, 'a', job_s=400.0, job_min=0)
    check('ход задания a: шаг «sampling»' in out, 'ход задания из /health виден в журнале драйвера')

print('\nИТОГ:', 'ВСЁ ЗЕЛЁНОЕ' if not FAILS else f'ПАДЕНИЙ {len(FAILS)}')
sys.exit(1 if FAILS else 0)
