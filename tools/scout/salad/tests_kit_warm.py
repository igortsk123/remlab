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


def spec(preflight=None):
    def submit(gw, k, t):
        c, r = gw.call('POST', '/generate', {'job_id': f'{k}-{int(t)}'})
        return ({'key': k, 'id': f'{k}-{int(t)}', 't0': t}, {}) if c == 202 else (None, {'http': c, 'detail': r})

    def poll(gw, cur, t):
        c, r = gw.call('GET', f'/result/{cur["id"]}')
        return ('done', {'x': 1}) if r.get('status') == 'done' else ('running', {})
    return KD.Spec(prefix='kit-warm', card='RTX X', model='m', jobs=['a', 'b'], build_body=lambda n, c, a: KD.group_body(n, 'img@sha256:1', 'low', c, 8000, {}, a, work_type='kit-test'),
                   submit=submit, poll=poll, allow_no_worker_check=True, work_type='kit-test', preflight=preflight)


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

# 7б. warm_sweep (T-34, замер 23.11): воркер при простое выходит, Salad поднимает его заново — гасим мы; занятых прогоном не трогаем
with tempfile.TemporaryDirectory() as wd:
    def rec(name, **kw):
        json.dump({'name': name, 'image': 'i', 'started_at': 1000.0, 'idle_min': 20.0, **kw}, open(os.path.join(wd, name + '.json'), 'w'))
    rec('trial-stage-a', expires_at=1000.0 + 7200, last_used=2000.0)        # простой 25 мин > 20 + 2 → гасим
    rec('trial-stage-b', expires_at=1000.0 + 7200, last_used=3000.0)        # простой 4 мин → живёт
    rec('trial-stage-c', expires_at=2500.0)                                 # предел жизни вышел (last_used нет) → гасим
    rec('trial-stage-d', expires_at=1000.0 + 7200)                          # запись старого кода: ни last_used, ни предела → не трогаем (р.5 на старых нодах)
    rec('trial-stage-e', expires_at=1000.0 + 7200, last_used=1500.0)        # просрочена, но занята прогоном (замок) → пропуск
    stopped = []
    res = KD.warm_sweep(wd, 3500.0, lambda n: stopped.append(n) or True, locked=lambda p: p.endswith('trial-stage-e.lock'))
    check(sorted(stopped) == ['trial-stage-a', 'trial-stage-c'] and all(r[2] for r in res), f'warm_sweep: гасит просроченных ({sorted(stopped)})')
    left = sorted(f for f in os.listdir(wd) if f.endswith('.json'))
    check(left == ['trial-stage-b.json', 'trial-stage-d.json', 'trial-stage-e.json'], f'warm_sweep: записи погашенных убраны, живые/занятые/старые остались ({left})')
    check('простой' in [r[1] for r in res if r[0] == 'trial-stage-a'][0] and 'предел' in [r[1] for r in res if r[0] == 'trial-stage-c'][0], 'warm_sweep: причина названа')
    res2 = KD.warm_sweep(wd, 3500.0, lambda n: False, grace_s=0, locked=lambda p: False)
    check(any(r[0] == 'trial-stage-e' and not r[2] for r in res2) and os.path.isfile(os.path.join(wd, 'trial-stage-e.json')), 'warm_sweep: остановка не подтверждена → запись остаётся, в итоге ❗')
    KD.warm_mark_used(os.path.join(wd, 'trial-stage-b.json'), 4242.0)
    check(json.load(open(os.path.join(wd, 'trial-stage-b.json')))['last_used'] == 4242.0, 'warm_mark_used: last_used записан')

# 7в. метка владельца и безопасный стоп (инцидент 23.11 19:43: стоп ×5 пришёлся на ноды, подхваченные прогоном р.2 в ту же минуту → его прогон завис)
with tempfile.TemporaryDirectory() as wd:
    def rec2(name, owner=None, **kw):
        st = {'name': name, 'image': 'i', 'started_at': 1000.0, 'idle_min': 20.0, 'expires_at': 9e9, **kw}
        if owner:
            st['owner'] = owner
        json.dump(st, open(os.path.join(wd, name + '.json'), 'w'))
    exists = lambda n: os.path.isfile(os.path.join(wd, n + '.json'))  # noqa: E731
    stopped = []
    stop_ok = lambda n: stopped.append(n) or True  # noqa: E731
    # а) нет записи (упавшая группа, старый код) — обычная остановка
    check(KD.warm_stop(wd, 'trial-stage-w3', stop_ok)[0] == 'stopped' and stopped == ['trial-stage-w3'], 'warm_stop: записи нет → обычная остановка')
    # б) свой владелец, замок свободен → стоп, запись убрана
    rec2('trial-stage-a', owner='r2all')
    st_a = KD.warm_stop(wd, 'trial-stage-a', stop_ok, owner='r2all')
    check(st_a[0] == 'stopped' and not exists('trial-stage-a'), f'warm_stop: свой владелец → остановлена, запись убрана ({st_a[0]})')
    # в) ЧУЖАЯ метка (ноду подхватил другой прогон) → отказ с названием метки, нода не тронута
    stopped.clear()
    rec2('trial-stage-b', owner='t243body')
    st_b = KD.warm_stop(wd, 'trial-stage-b', stop_ok, owner='r2all')
    check(st_b[0] == 'refused' and 't243body' in st_b[1] and not stopped and exists('trial-stage-b'), f'warm_stop: чужая метка → отказ, нода жива ({st_b[1][:70]})')
    # г) замок держит идущий прогон (подхватил и работает) → отказ даже без метки в вызове (ручной --stop-only)
    fh = KD.warm_lock(os.path.join(wd, 'trial-stage-c.lock'))
    rec2('trial-stage-c', owner='t243body')
    st_c = KD.warm_stop(wd, 'trial-stage-c', stop_ok)
    check(st_c[0] == 'refused' and 'занята' in st_c[1] and not stopped, f'warm_stop: занята прогоном (замок) → отказ ({st_c[0]})')
    fh.close()
    # д) ручной стоп без метки, замок свободен → гасим (человек знает, что делает)
    st_d = KD.warm_stop(wd, 'trial-stage-c', stop_ok)
    check(st_d[0] == 'stopped' and 'trial-stage-c' in stopped, 'warm_stop: замок свободен, метки в вызове нет → гасим')
    # е) остановка не подтверждена → failed, запись остаётся (sweep/повтор доделает)
    rec2('trial-stage-e', owner='r2all')
    st_e = KD.warm_stop(wd, 'trial-stage-e', lambda n: False, owner='r2all')
    check(st_e[0] == 'failed' and exists('trial-stage-e'), 'warm_stop: не подтверждено → failed, запись остаётся')
    # ж) warm_release: гасит ровно ноды с меткой владельца; подхваченные другим прогоном (метка/замок) не трогает
    stopped.clear()
    for n in ('trial-stage-r0', 'trial-stage-r1', 'trial-stage-r2', 'trial-stage-r3'):
        if exists(n):
            os.remove(os.path.join(wd, n + '.json'))
    rec2('trial-stage-r0', owner='r2all')
    rec2('trial-stage-r1', owner='r2all')
    rec2('trial-stage-r2', owner='t243body')                       # уже подхвачена другим: метка сменилась
    rec2('trial-stage-r3', owner='r2all')                          # метка наша, но замок держит чужой прогон в этот миг
    fh3 = KD.warm_lock(os.path.join(wd, 'trial-stage-r3.lock'))
    res = KD.warm_release(wd, 'r2all', stop_ok)
    got = {r[0]: r[1] for r in res}
    check(got.get('trial-stage-r0') == 'stopped' and got.get('trial-stage-r1') == 'stopped' and 'trial-stage-r2' not in got and got.get('trial-stage-r3') == 'refused', f'warm_release: свои погашены, чужая метка не трогается, занятая — отказ ({got})')
    check(sorted(n for n in stopped if n.startswith('trial-stage-r')) == ['trial-stage-r0', 'trial-stage-r1'] and exists('trial-stage-r2') and exists('trial-stage-r3'), 'warm_release: stop вызван только для своих; чужие записи на месте')
    fh3.close()
    check(KD.warm_release(wd, '', stop_ok) == [], 'warm_release: пустая метка → ничего не гасит')
    # з) метка владельца пишется: warm_set_owner (подхват) и сохраняется warm_mark_used
    rec2('trial-stage-o')
    KD.warm_set_owner(os.path.join(wd, 'trial-stage-o.json'), 'new-run', 5000.0)
    KD.warm_mark_used(os.path.join(wd, 'trial-stage-o.json'), 6000.0)
    so = json.load(open(os.path.join(wd, 'trial-stage-o.json')))
    check(so['owner'] == 'new-run' and so['claimed_at'] == 5000.0 and so['last_used'] == 6000.0, f'warm_set_owner/mark_used: метка и время сохранены ({so.get("owner")})')

# 7г. сквозь run_probe: создание ставит метку, подхват другим прогоном меняет её, а освобождение ПЕРВОГО владельца после этого уже ничего не гасит
with tempfile.TemporaryDirectory() as tmp:
    clock = Clock()
    w = World(clock)
    drive(tmp, w, clock, warm_owner='r2all')
    check(json.load(open(STATE(tmp)))['owner'] == 'r2all', 'run_probe: нода создана с меткой владельца')
    clock.sleep(300)
    rc, sm, out = drive(tmp, w, clock, warm_owner='t243body')
    check(sm.get('adopted_warm') and json.load(open(STATE(tmp)))['owner'] == 't243body', 'run_probe: подхват — метка сменилась на нового владельца')
    stopped2 = []
    res = KD.warm_release(os.path.join(tmp, 'warm'), 'r2all', lambda n: stopped2.append(n) or True)
    check(res == [] and not stopped2 and w.stops == 0, 'гонка «стоп vs подхват»: освобождение прежнего владельца после подхвата ноду не гасит')

# 7д. stage_trial.stop_only / warm_release_cmd: коды возврата (0 — погашено, 1 — не подтверждено, 3 — отказ)
try:
    sys.path.insert(0, os.path.join(HERE, 'stage'))
    import stage_trial as ST0  # noqa: E402
    with tempfile.TemporaryDirectory() as wd:
        json.dump({'name': 'trial-stage-w0', 'owner': 'p2', 'expires_at': 9e9}, open(os.path.join(wd, 'trial-stage-w0.json'), 'w'))
        with contextlib.redirect_stdout(io.StringIO()):
            rc_ref = ST0.stop_only(argparse.Namespace(suffix='w0', warm_dir=wd, warm_owner='r1'), lambda n: True)
            rc_fail = ST0.stop_only(argparse.Namespace(suffix='w0', warm_dir=wd, warm_owner='p2'), lambda n: False)
            rc_plain = ST0.stop_only(argparse.Namespace(suffix='zz', warm_dir=wd, warm_owner=''), lambda n: True)
        check(rc_ref == 3 and rc_fail == 1 and rc_plain == 0, f'stage_trial --stop-only: чужая метка → 3, не подтверждено → 1, обычная группа → 0 ({rc_ref}, {rc_fail}, {rc_plain})')
        with contextlib.redirect_stdout(io.StringIO()):
            rc_rel = ST0.warm_release_cmd(argparse.Namespace(warm_dir=wd, warm_owner='r1'), lambda n: True)
        check(rc_rel == 0 and os.path.isfile(os.path.join(wd, 'trial-stage-w0.json')), 'stage_trial --warm-release чужого владельца: код 0, нода p2 не тронута')
except ImportError as exc:
    print('SKIP stage_trial stop_only (нет зависимостей):', exc)

# 7е. --dry (без --apply): бесплатные проверки входов тоже идут, провал → код 3 (раньше dry давал 0 и «входы на месте» не проверял: круг 2 не стартовал 18:59, а dry был «зелёный»)
def dry(preflight):
    out = io.StringIO()
    with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(out):
        d = dict(image='x@sha256:1', suffix='w0', tier='low', apply=False, cap=4.0, probe_cap=1.0, max_min=600, running_min=30, start_min=20, health_min=8, ready_min=30, stall_min=5,
                 stall_gb=0.05, job_min=0, out=os.path.join(tmp, 'out'), keep_warm=0.0, warm_dir=os.path.join(tmp, 'warm'), warm_life_min=120, warm_min_left_min=25)
        clock = Clock()
        rc = KD.run_probe(argparse.Namespace(**d), World(clock), World(clock), spec(preflight), gw_factory=lambda base, key: GW(clock, False), sleep=clock.sleep, clock=clock,
                          slot_check=lambda: None, image_check=lambda *x, **k: (True, 'ok', 1.0), ledger=lambda rec: None)
    return rc, out.getvalue()


rc_bad, out_bad = dry(lambda: (False, "входы не готовы: ['sku1: в камере /x нет 04-camera/check.json']"))
rc_good, out_good = dry(lambda: (True, 'входы на месте: 29 товаров'))
rc_none, _o = dry(None)
check(rc_bad == 3 and 'входы не готовы' in out_bad and 'НЕ создаю' in out_bad, f'dry: проверка входов провалена → код 3, причина названа (rc={rc_bad})')
check(rc_good == 0 and 'входы на месте' in out_good and rc_none == 0, f'dry: входы на месте → 0; Spec без preflight → 0 как раньше ({rc_good}, {rc_none})')

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
    # A/B размера ноды: --variant big → 8 vCPU / 16 ГБ из профиля (не мимо профиля); без — 4 vCPU / 8 ГБ
    res0 = ST.make_spec(a, {}).build_body('n', 'cls', {'basic': {'username': 'u', 'password': 'p'}})['container']['resources']
    a.variant = 'big'
    res1 = ST.make_spec(a, {}).build_body('n', 'cls', {'basic': {'username': 'u', 'password': 'p'}})['container']['resources']
    check((res0['cpu'], res0['memory']) == (4, 8192) and (res1['cpu'], res1['memory']) == (8, 16384), f'вариант big: 8 vCPU/16 ГБ, по умолчанию 4/8 ({res0["cpu"]}/{res0["memory"]}, {res1["cpu"]}/{res1["memory"]})')
except ImportError as exc:
    print('SKIP stage_trial (нет зависимостей):', exc)

print('\nИТОГ:', 'ВСЁ ЗЕЛЁНОЕ' if not FAILS else f'ПАДЕНИЙ {len(FAILS)}')
sys.exit(1 if FAILS else 0)
