#!/usr/bin/env python3
"""Тесты драйвера salad_trial.py БЕЗ сети и денег: подставные Salad/шлюз/часы. Запуск: python3 tests_salad_trial.py"""
import argparse
import io
import json
import os
import sys
import tempfile
import contextlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import salad_trial as S  # noqa: E402

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
    API = 'https://x/projects/p/containers'

    def __init__(self):
        self.calls = []
        self.created = False

    def env_from_file(self):
        os.environ['SALAD_API_KEY'] = 'SECRET-SALAD'
        os.environ['HF_TOKEN'] = 'SECRET-HF'

    def ghcr_auth(self):
        return {'basic': {'username': 'u', 'password': 'SECRET-GHCR'}}

    def api(self, path, method='GET', body=None):
        self.calls.append((method, path))
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
        self.clock, self.t0, self.running_after = clock, None, running_after
        self.stopped = 0

    def group_state(self, name):
        return 200, ('stopped' if self.t0 is None else 'running'), 1

    def instances(self, name):
        if self.t0 is None:
            return 200, []
        return 200, [{'state': 'running' if self.clock() - self.t0 >= self.running_after else 'creating'}]

    def stop_and_verify(self, name):
        self.stopped += 1
        return True


class GW:
    """ready_after — через сколько секунд после создания шлюза нода «готова»; job_s — длительность задания; fail — задание падает."""
    def __init__(self, clock, ready_after=120.0, job_s=200.0, fail=False):
        self.clock, self.ready_after, self.job_s, self.fail = clock, ready_after, job_s, fail
        self.t0 = clock()
        self.jobs = {}

    def call(self, method, path, body=None, timeout=60, raw=False):
        t = self.clock()
        if path == '/health':
            return 200, {'phase': 'ready' if t - self.t0 >= self.ready_after else 'loading', 'version': 'v', 'offload': 'swap', 'sparse': {'enabled': False}, 'error': ''}
        if path == '/generate':
            self.jobs[body['job_id']] = t
            return 202, {}
        if path.endswith('/glb'):
            return 200, b'GLB'
        if path.startswith('/result/'):
            jid = path.split('/')[2]
            if t - self.jobs[jid] < self.job_s:
                return 200, {'status': 'running'}
            if self.fail:
                return 200, {'status': 'failed', 'error': 'OOM'}
            return 200, {'status': 'done', 'metrics': {'vram_peak_gb': 29.1, 'total_s': 190}}
        return 404, {}


def setup(tmp, keys=('a', 'b')):
    sh, inp = os.path.join(tmp, 'shapes'), os.path.join(tmp, 'inputs')
    os.makedirs(sh)
    os.makedirs(inp)
    for k in keys:
        open(os.path.join(sh, f'{k}.prep.glb'), 'wb').write(b'g')
        open(os.path.join(inp, f'{k}.rgba.png'), 'wb').write(b'p')
    return sh, inp


def args(tmp, sh, inp, jobs, **kw):
    d = dict(image='ghcr.io/x/y:ultratex-bw', jobs=jobs, shape_dir=sh, shape_name='{key}.prep.glb', inputs=inp, out=os.path.join(tmp, 'out'), tier='high', cpu=8, mem_mb=49152,
             resolution=2048, steps=25, seed=42, texture=4096, probe_cap=1.0, cap=4.0, max_min=120, running_min=30, health_min=8, ready_min=75, job_min=30, idle_s=900,
             suffix='t', apply=True, stop_only=False)
    d.update(kw)
    return argparse.Namespace(**d)


def drive(tmp, jobs, price=0.6, ready_after=120.0, job_s=200.0, fail=False, head=lambda u, t='': 200, running_after=60.0, **kw):
    sh, inp = setup(tmp)
    clock = Clock()
    mg, br = MG(), BR(clock, running_after)
    S.lookup_class = lambda MG_, name, tier: ('cls-5090', price)
    orig_api = mg.api

    def api(path, method='GET', body=None):
        r = orig_api(path, method, body)
        if method == 'POST' and path.endswith('/start'):
            br.t0 = clock()
        return r
    mg.api = api
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = S.run(args(tmp, sh, inp, jobs, **kw), mg, br, gw_factory=lambda base, key: GW(clock, ready_after, job_s, fail), sleep=clock.sleep, clock=clock, head_fn=head)
    summ = json.load(open(os.path.join(tmp, 'out', 'summary-trial-ultratex-t.json'))) if os.path.exists(os.path.join(tmp, 'out', 'summary-trial-ultratex-t.json')) else {}
    return rc, summ, out.getvalue(), mg, br


# 1. стоимость и потолки
check(abs(S.cost_usd(3600, 0.6, 0) - 0.6) < 1e-9, 'цена: час × $0,6 = $0,6')
check(S.cost_usd(0, 0.6) == 0.0, 'цена: running=0 → 0 (запас не начисляется)')
check(S.effective_cap(False, 1.0, 4.0) == 1.0 and S.effective_cap(True, 1.0, 4.0) == 4.0, 'потолок: до успеха $1, после — $4')
check(S.effective_cap(False, 5.0, 4.0) == 4.0, 'потолок: проба не выше общего')

# 2. тело группы: секреты не печатаются
body = S.build_body('n', 'img', 'high', 'cls', 8, 49152, {'basic': {'password': 'SECRET-GHCR'}}, 'SECRET-HF', 7800, 900)
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    S.safe_print(body)
check('SECRET' not in buf.getvalue(), 'разбор: секреты скрыты')
check(body['container']['environment_variables']['ULTRATEX_OFFLOAD'] == 'swap' and body['container']['resources']['memory'] == 49152, 'тело: выгрузка swap, ОЗУ 48 ГБ')
check(body['container']['resources']['gpu_classes'] == ['cls'], 'тело: класс карты из списка Salad')

# 3. разбор без --apply: группа не создаётся
with tempfile.TemporaryDirectory() as tmp:
    rc, summ, out, mg, br = drive(tmp, 'a', apply=False)
    check(rc == 0 and not mg.created and 'SECRET' not in out, 'без --apply: код 0, группа не создана, секретов нет')

# 4. счастливый путь, 2 задания
with tempfile.TemporaryDirectory() as tmp:
    rc, summ, out, mg, br = drive(tmp, 'a,b')
    check(rc == 0 and summ.get('stopped_by') == 'done', f'2 задания: код 0, stopped_by=done ({summ.get("stopped_by")})')
    check(summ.get('stop_verified') is True and br.stopped == 1, 'гашение и проверка stopped — ровно раз')
    check(all(summ['jobs'][k]['status'] == 'done' for k in 'ab') and os.path.exists(os.path.join(tmp, 'out', 'a.ultratex.glb')), 'GLB обоих сохранены')
    check('SECRET' not in out, 'в журнале секретов нет')
    check(summ['jobs']['a']['metrics']['vram_peak_gb'] == 29.1, 'метрики (пик VRAM) в итоге')

# 5. потолок пробы: нода долго греется — стоп по probe_cap до готовности, деньги ≤ ~$1
with tempfile.TemporaryDirectory() as tmp:
    rc, summ, out, mg, br = drive(tmp, 'a', ready_after=99999, ready_min=500, max_min=500)
    check(rc == 1 and summ.get('stopped_by') == 'probe_cap' and summ.get('stop_verified'), f'потолок пробы: стоп probe_cap ({summ.get("stopped_by")})')
    check(summ.get('cost_usd_est', 9) <= 1.05, f'расход ≤ $1,05 (${summ.get("cost_usd_est")})')

# 6. нет допуска к весам — группа не создаётся
with tempfile.TemporaryDirectory() as tmp:
    rc, summ, out, mg, br = drive(tmp, 'a', head=lambda u, t='': 403)
    check(rc == 3 and not mg.created and br.stopped == 0, 'нет допуска к FLUX.2: группа не создана, денег нет')

# 7. две неудачи подряд
with tempfile.TemporaryDirectory() as tmp:
    rc, summ, out, mg, br = drive(tmp, 'a,b', fail=True)
    check(rc == 1 and summ.get('stopped_by') == 'fail_streak' and summ.get('failed') == 2 and summ.get('stop_verified'), f'2 неудачи: стоп fail_streak ({summ.get("stopped_by")})')

# 8. одна неудача из одного задания — не «done»
with tempfile.TemporaryDirectory() as tmp:
    rc, summ, out, mg, br = drive(tmp, 'a', fail=True)
    check(rc == 1 and summ.get('stopped_by') == 'first_failed', f'одно задание упало: first_failed ({summ.get("stopped_by")})')

# 9. нода не выдана
with tempfile.TemporaryDirectory() as tmp:
    rc, summ, out, mg, br = drive(tmp, 'a', running_after=99999, running_min=5)
    check(rc == 1 and summ.get('stopped_by') == 'no_machine' and summ.get('stop_verified'), 'нода не выдана за 5 мин: стоп no_machine')

# 10. нет входных файлов
with tempfile.TemporaryDirectory() as tmp:
    rc, summ, out, mg, br = drive(tmp, 'zzz')
    check(rc == 3 and not mg.created, 'нет входных файлов: стоп до создания группы')

print('\nИТОГ:', 'ВСЁ ЗЕЛЁНОЕ' if not FAILS else f'ПАДЕНИЙ {len(FAILS)}')
sys.exit(1 if FAILS else 0)
