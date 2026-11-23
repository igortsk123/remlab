#!/usr/bin/env python3
"""Тесты «тёплой ноды» (T-20261123-34): `--keep-warm` в kit_driver.run_probe — нода остаётся между прогонами, следующий прогон подхватывает её без создания и прогрева.
Без сети и денег (подставные Salad, шлюз, часы). Запуск: python3 tools/scout/salad/tests_kit_warm.py"""
import argparse
import contextlib
import io
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.append(os.path.abspath(os.path.join(HERE, '..')))
import remlab_tmp  # noqa: E402
remlab_tmp.use('tests_kit_warm')
import kit_driver as KD  # noqa: E402

TEST_PROF = {'card': 'RTX X', 'card_fallbacks': ['RTX 5090 (32 GB)'], 'cpu': 4, 'memory_mb': 8192, 'storage_gb': 10, 'shm_mb': 1024, 'tier': 'low', 'tier_fallback': 'medium',
             'expect': {}, 'basis': 'estimate', 'basis_note': 'тест'}
_real_profile = KD.resource_profile
KD.resource_profile = lambda wt, path=None: TEST_PROF if wt == 'kit-test' else _real_profile(wt, path)
KD.gpu_class = lambda MG_, name, tier, fetch=None: ('cls', 0.6)
FAILS = []


def check(cond, msg):
    print(('ok   ' if cond else 'FAIL ') + msg)
    if not cond:
        FAILS.append(msg)


class Clock:
    def __init__(self):
        self.t = 100000.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


class World:
    """Salad целиком: есть ли группа, её состояние, счётчики обращений."""
    def __init__(self, clock, exists=False, status='stopped', up_since=None):
        self.clock, self.exists, self.status, self.up_since = clock, exists, status, up_since
        self.creates = self.starts = self.stops = 0

    # --- Salad API (MG)
    def env_from_file(self):
        os.environ['SALAD_API_KEY'] = 'SECRET-SALAD'

    def ghcr_auth(self):
        return {'basic': {'username': 'u', 'password': 'SECRET-GHCR'}}

    def api(self, path, method='GET', body=None):
        if path == '' and method == 'GET':
            return 200, {'items': []}
        if method == 'GET':
            return (200, {'networking': {'dns': 'g.example'}}) if self.exists else (404, {})
        if method == 'POST' and path == '':
            self.exists, self.status = True, 'stopped'
            self.creates += 1
            return 201, {}
        if method == 'POST' and path.endswith('/start'):
            self.starts += 1
            self.status, self.up_since = 'running', self.clock()
            return 202, {}
        return 202, {}

    # --- bench_run (BR)
    def group_state(self, name):
        return 200, (self.status if self.exists else None), 1

    def instances(self, name):
        if self.up_since is None or self.status != 'running':
            return 200, []
        up = self.clock() - self.up_since >= 60
        return 200, [{'id': 'inst-0123456789', 'state': 'running' if up else 'creating', 'started': up}]

    def stop_and_verify(self, name):
        self.stops += 1
        self.status, self.up_since = 'stopped', None
        return True


class GW:
    def __init__(self, clock, bad=False):
        self.clock, self.bad, self.jobs = clock, bad, {}

    def call(self, method, path, body=None, timeout=60, raw=False):
        t = self.clock()
        if path == '/health':
            return 200, {'phase': 'ready', 'version': 'v', 'error': '', 'root_gb': 1.0}
        if path == '/generate':
            if self.bad:
                return 500, {'error': 'boom'}
            self.jobs[body['job_id']] = t
            return 202, {}
        if path.startswith('/result/'):
            return 200, {'status': 'done'}
        return 404, {}


def spec():
    def submit(gw, k, t):
        c, r = gw.call('POST', '/generate', {'job_id': f'{k}-{int(t)}'})
        return ({'key': k, 'id': f'{k}-{int(t)}', 't0': t}, {}) if c == 202 else (None, {'http': c, 'detail': r})

    def poll(gw, cur, t):
        c, r = gw.call('GET', f'/result/{cur["id"]}')
        return ('done', {'x': 1}) if r.get('status') == 'done' else ('running', {})
    return KD.Spec(prefix='kit-warm', card='RTX X', model='m', jobs=['a', 'b'], build_body=lambda n, c, a: KD.group_body(n, 'img@sha256:1', 'low', c, 8000, {}, a, work_type='kit-test'),
                   submit=submit, poll=poll, allow_no_worker_check=True, work_type='kit-test')


def drive(tmp, world, clock, image='x@sha256:1', keep_warm=20.0, bad=False, **kw):
    d = dict(image=image, suffix='w0', tier='low', apply=True, cap=4.0, probe_cap=1.0, max_min=600, running_min=30, start_min=20, health_min=8, ready_min=30, stall_min=5,
             stall_gb=0.05, job_min=0, out=os.path.join(tmp, 'out'), keep_warm=keep_warm, warm_dir=os.path.join(tmp, 'warm'), warm_life_min=120, warm_min_left_min=25)
    d.update(kw)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = KD.run_probe(argparse.Namespace(**d), world, world, spec(), gw_factory=lambda base, key: GW(clock, bad), sleep=clock.sleep, clock=clock, slot_check=lambda: None,
                          image_check=lambda *x, **k: (True, 'ok', 1.0), ledger=lambda rec: None)
    p = os.path.join(tmp, 'out', 'summary-kit-warm-w0.json')
    return rc, (json.load(open(p)) if os.path.exists(p) else {}), out.getvalue()


STATE = lambda tmp: os.path.join(tmp, 'warm', 'kit-warm-w0.json')  # noqa: E731

# 1. первый прогон: группа создана, прогон чистый → нода ОСТАВЛЕНА (не гасится), запись о сроке жизни есть
with tempfile.TemporaryDirectory() as tmp:
    clock = Clock()
    w = World(clock)
    rc, sm, out = drive(tmp, w, clock)
    st = json.load(open(STATE(tmp))) if os.path.exists(STATE(tmp)) else {}
    check(rc == 0 and w.creates == 1 and w.starts == 1 and w.stops == 0 and sm.get('kept_warm'), f'1-й прогон: создана, не погашена, kept_warm (rc={rc}, creates={w.creates}, stops={w.stops})')
    check(st.get('image') == 'x@sha256:1' and st.get('expires_at', 0) - st.get('started_at', 0) == 7200, f'запись: образ и предел жизни 120 мин ({st})')
    check('ОСТАНОВИТСЯ' not in out.upper() or 'ОСТАВЛЕНА' in out, 'журнал: нода оставлена, как гасить сразу')

    # 2. второй прогон: нода жива → подхват: ни создания, ни /start, ни стопа, прогрева нет
    clock.sleep(300)
    rc, sm, out = drive(tmp, w, clock)
    check(rc == 0 and w.creates == 1 and w.starts == 1 and w.stops == 0 and sm.get('adopted_warm') and sm.get('kept_warm'), f'2-й прогон: подхват без создания и старта (creates={w.creates}, starts={w.starts}, stops={w.stops})')
    check('прогрева нет' in out, 'журнал: «прогрева нет»')

    # 3. у ноды мало жизни (< warm_min_left) → гасим и стартуем заново (без POST создания)
    clock.sleep(7200 - 300 - 200 - 60 * 20)
    rc, sm, out = drive(tmp, w, clock)
    check(rc == 0 and w.stops == 1 and w.creates == 1 and w.starts == 2 and not sm.get('adopted_warm'), f'мало жизни: стоп + старт той же группы (stops={w.stops}, creates={w.creates}, starts={w.starts})')

# 4. группа остановлена (воркер ушёл по простою): только старт, без создания
with tempfile.TemporaryDirectory() as tmp:
    clock = Clock()
    w = World(clock, exists=True, status='stopped')
    rc, sm, out = drive(tmp, w, clock)
    check(rc == 0 and w.creates == 0 and w.starts == 1 and w.stops == 0 and sm.get('kept_warm'), f'stopped: старт без создания (creates={w.creates}, starts={w.starts})')

# 5. у живой группы другой образ → отказ, ничего не трогаем
with tempfile.TemporaryDirectory() as tmp:
    clock = Clock()
    w = World(clock)
    drive(tmp, w, clock, image='x@sha256:1')
    clock.sleep(60)
    rc, sm, out = drive(tmp, w, clock, image='x@sha256:2')
    check(rc == 2 and w.stops == 0 and w.creates == 1 and w.starts == 1 and 'другой образ' in out, f'другой образ: отказ, нода не тронута (rc={rc}, stops={w.stops})')

# 6. прогон с отказами → нода гасится с проверкой, запись удалена (больную ноду не греем)
with tempfile.TemporaryDirectory() as tmp:
    clock = Clock()
    w = World(clock)
    rc, sm, out = drive(tmp, w, clock, bad=True)
    check(rc != 0 and w.stops >= 1 and not sm.get('kept_warm') and sm.get('stop_verified') and not os.path.exists(STATE(tmp)), f'отказ заданий: стоп с проверкой, не тёплая, записи нет (rc={rc}, stops={w.stops}, stopped_by={sm.get("stopped_by")})')

# 7. замок: пока один прогон держит ноду, второй не лезет (код 4)
with tempfile.TemporaryDirectory() as tmp:
    clock = Clock()
    w = World(clock)
    lock = KD.warm_lock(os.path.join(tmp, 'warm', 'kit-warm-w0.lock'))
    rc, sm, out = drive(tmp, w, clock)
    check(lock is not None and rc == 4 and w.creates == 0 and 'занята другим прогоном' in out, f'замок: второй прогон отказан до создания (rc={rc}, creates={w.creates})')
    lock.close()

# 7б. группа «running», а экземпляра нет (воркер ушёл по простою) → не подхват, а перезапуск
with tempfile.TemporaryDirectory() as tmp:
    clock = Clock()
    w = World(clock)
    drive(tmp, w, clock)
    clock.sleep(600)
    w.up_since = None                                              # экземпляр исчез, статус группы остался running
    rc, sm, out = drive(tmp, w, clock)
    check(rc == 0 and not sm.get('adopted_warm') and w.stops == 1 and w.starts == 2 and 'живого экземпляра нет' in out, f'running без экземпляра: перезапуск, не подхват (stops={w.stops}, starts={w.starts})')

# 8. warm_decide — таблица решений
D = KD.warm_decide
check(D(None, {}, 'i', 0, 1500)[0] == 'create' and D('stopped', {}, 'i', 0, 1500)[0] == 'restart' and D('stopping', {}, 'i', 0, 1500)[0] == 'refuse', 'warm_decide: нет → create, stopped → restart, stopping → refuse')
check(D('running', {'image': 'i', 'expires_at': 10000}, 'i', 0, 1500)[0] == 'adopt' and D('running', {'image': 'i', 'expires_at': 1000}, 'i', 0, 1500)[0] == 'restart_stop'
      and D('running', {}, 'i', 0, 1500)[0] == 'refuse' and D('running', {'image': 'i'}, 'i', 0, 1500)[0] == 'restart_stop', 'warm_decide: жива и жизни хватает → adopt; мало/нет записи → restart_stop; чужой образ → refuse')

# 9. stage_trial: с --keep-warm в теле группы IDLE_S = простой, MAX_LIFETIME_S = предел жизни (воркер сам гасится — страховка, если драйвер умер)
try:
    sys.path.insert(0, os.path.join(HERE, 'stage'))
    import stage_trial as ST  # noqa: E402
    a = argparse.Namespace(image='x@sha256:1', tier='low', max_min=45, idle_s=900, procs=4, fill_procs=2, threads=1, stage_timeout_s=900, keep_warm=20.0, warm_life_min=120, stages='07', out='/x', card='c')
    body = ST.make_spec(a, {}).build_body('n', 'cls', {'basic': {'username': 'u', 'password': 'p'}})
    env = body['container']['environment_variables']
    check(env.get('IDLE_S') == '1200' and env.get('MAX_LIFETIME_S') == '7200', f'тело группы: IDLE_S=1200, MAX_LIFETIME_S=7200 ({env.get("IDLE_S")}, {env.get("MAX_LIFETIME_S")})')
    # 404 на опросе задания (нода перезапущена, записи нет) → отказ job_lost, а не вечное «идёт»
    class Gw404:
        def call(self, method, path, body=None, timeout=60, raw=False):
            return 404, {'error': 'нет такого задания'}
    with tempfile.TemporaryDirectory() as tmp404:
        a404 = argparse.Namespace(out=tmp404, code=None)
        st404, info404 = ST.poll_stage(Gw404(), a404, {'key': '07', 'ids': {'sku1': 'j1'}, 'got': {}, 'skipped': {}}, 0.0)
        check(st404 == 'failed' and 'job_lost' in str(info404.get('error', '')) + str(info404.get('items')), f'404 на опросе: задание потеряно, не вечный опрос ({st404})')
    a.keep_warm = 0.0
    env = ST.make_spec(a, {}).build_body('n', 'cls', {'basic': {'username': 'u', 'password': 'p'}})['container']['environment_variables']
    check(env.get('IDLE_S') == '900' and env.get('MAX_LIFETIME_S') == str(45 * 60 + 600), f'без --keep-warm прежние значения ({env.get("IDLE_S")}, {env.get("MAX_LIFETIME_S")})')
except ImportError as exc:
    print('SKIP stage_trial (нет зависимостей):', exc)

print('\nИТОГ:', 'ВСЁ ЗЕЛЁНОЕ' if not FAILS else f'ПАДЕНИЙ {len(FAILS)}')
sys.exit(1 if FAILS else 0)
