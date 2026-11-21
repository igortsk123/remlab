#!/usr/bin/env python3
"""Тесты ЦИКЛА заданий `kit_driver.run_probe` без сети и денег (подставные Salad, шлюз, часы). Запуск: python3 tools/scout/salad/tests_kit_loop.py
Закрывают дефекты пробы p4 (21.11): (1) 429 «занят» на следующем задании сжигал серию провалов; (2) задание срезалось на 30-й минуте раньше потолка пробы;
(3) ход задания из /health воркера не был виден драйверу."""
import argparse
import contextlib
import io
import json
import os
import re
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
    return KD.Spec(prefix='kit-loop', card='RTX X', model='m', jobs=keys.split(','), build_body=lambda n, c, a: {'name': n}, submit=submit, poll=poll,
                   allow_no_worker_check=True)                      # поддельный воркер теста: кода воркера нет (в боевой пробе worker_file обязателен)


LEDGER = []


def drive(tmp, keys, job_s, job_min, price=0.6, gw_cls=None, **kw):
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
        rc = KD.run_probe(argparse.Namespace(**d), mg, br, make_spec(keys), gw_factory=lambda base, key: (gw_cls or GW)(clock, job_s), sleep=clock.sleep, clock=clock,
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

# 7. зависшее задание (урок b1, P3-SAM 21.11: 15 мин молчания): шаг тот же и GPU 0 % дольше порога → гасим по ходу, не ждём потолка
class GwGpu(GW):
    gpu = 0.0
    step_name = 'sampling'

    def call(self, method, path, body=None, timeout=60, raw=False):
        c, h = super().call(method, path, body, timeout, raw)
        if path == '/health' and h.get('job'):
            h['job'].update(gpu_util=self.gpu, gpu_mem_mb=900.0, line='sampler: тишина', step=self.step_name)
        return c, h


class GwGpuBusy(GwGpu):
    gpu = 88.0


class GwStepMoves(GwGpu):
    def call(self, method, path, body=None, timeout=60, raw=False):
        self.step_name = f'dit {int(self.clock() // 120)}/25'                  # шаг меняется каждые 2 мин, GPU при этом 0 % (например, CPU-подготовка частями)
        return super().call(method, path, body, timeout, raw)


with tempfile.TemporaryDirectory() as tmp:
    rc, summ, out, br = drive(tmp, 'a', job_s=10 ** 9, job_min=0, gw_cls=GwGpu, stuck_min=4)
    check(summ.get('stopped_by') == 'job_stuck' and summ.get('jobs', {}).get('a', {}).get('status') == 'stuck' and summ.get('stop_verified'),
          f'шаг тот же, GPU 0 % > 4 мин: стоп job_stuck с проверкой ({summ.get("stopped_by")})')
    check(summ.get('cost_usd_est', 9) < 0.2 and 'зависло' in out and 'sampler: тишина' in out and 'GPU 0.0 %' in out, f'остановка быстро (≈$0.0x, не потолок), в журнале последняя строка и GPU ({summ.get("cost_usd_est")})')
with tempfile.TemporaryDirectory() as tmp:
    rc, summ, out, br = drive(tmp, 'a', job_s=900.0, job_min=0, gw_cls=GwGpuBusy, stuck_min=4)
    check(summ.get('stopped_by') == 'done' and 'зависло' not in out, 'GPU 88 % — считает, не гасим')
with tempfile.TemporaryDirectory() as tmp:
    rc, summ, out, br = drive(tmp, 'a', job_s=900.0, job_min=0, gw_cls=GwStepMoves, stuck_min=4)
    check(summ.get('stopped_by') == 'done' and 'зависло' not in out, 'шаг меняется (GPU 0 %) — не зависло')
with tempfile.TemporaryDirectory() as tmp:
    rc, summ, out, br = drive(tmp, 'a', job_s=1500.0, job_min=0, gw_cls=GwGpu, stuck_min=0)
    check(summ.get('stopped_by') == 'done' and 'зависло' not in out, '--stuck-min 0 выключает сторож')
with tempfile.TemporaryDirectory() as tmp:
    rc, summ, out, br = drive(tmp, 'a', job_s=900.0, job_min=0)                 # воркер без GPU в ходе (старый) — GPU None не считаем «нулём»
    check(summ.get('stopped_by') == 'done' and 'зависло' not in out, 'нет GPU в ходе — по умолчанию не гасим (None не 0 %)')

# 8. до создания группы: воркер без хода задания в коде — отказ, деньги не тратятся
with tempfile.TemporaryDirectory() as tmp:
    bad = os.path.join(tmp, 'worker_bad.py')
    open(bad, 'w', encoding='utf-8').write('import kit_worker as KW\nKW.serve(1)\n')
    good = os.path.join(tmp, 'worker_good.py')
    open(good, 'w', encoding='utf-8').write('import kit_worker as KW\nstate.begin_job(j)\nengine.on_step = state.step\n')
    spec_bad = make_spec('a')
    spec_bad.worker_file = bad
    n0 = len(LEDGER)
    clock = Clock()
    mg, br = MG(), BR(clock)
    KD.gpu_class = lambda MG_, name, tier, fetch=None: ('cls', 0.6)
    a = argparse.Namespace(image='x@sha256:1', suffix='t', tier='high', apply=True, cap=4.0, probe_cap=1.0, max_min=600, running_min=30, start_min=20, health_min=8, ready_min=30,
                           stall_min=5, stall_gb=0.05, job_min=0, out=os.path.join(tmp, 'out'))
    o = io.StringIO()
    with contextlib.redirect_stdout(o):
        rc = KD.run_probe(a, mg, br, spec_bad, gw_factory=lambda base, key: GW(clock, 10.0), sleep=clock.sleep, clock=clock, slot_check=lambda: None,
                          image_check=lambda *x, **k: (True, 'ok', 1.0), ledger=lambda rec: LEDGER.append(rec))
    check(rc == 3 and 'нет живого хода задания' in o.getvalue() and 'денег не потрачено' in o.getvalue() and len(LEDGER) == n0 and not os.path.exists(os.path.join(tmp, 'out')),
          'воркер без хода: отказ ДО создания группы (код 3), денег нет')
    spec_none = make_spec('a')                                                   # боевая проба без worker_file и без явного пропуска — отказ до группы
    spec_none.allow_no_worker_check = False
    o2 = io.StringIO()
    with contextlib.redirect_stdout(o2):
        rc2 = KD.run_probe(a, mg, br, spec_none, gw_factory=lambda base, key: GW(clock, 10.0), sleep=clock.sleep, clock=clock, slot_check=lambda: None,
                           image_check=lambda *x, **k: (True, 'ok', 1.0), ledger=lambda rec: LEDGER.append(rec))
    check(rc2 == 3 and 'не указан код воркера' in o2.getvalue() and 'денег не потрачено' in o2.getvalue() and not os.path.exists(os.path.join(tmp, 'out')),
          'пустой worker_file без явного allow_no_worker_check: отказ ДО группы (код 3), денег нет')
    spec_good = make_spec('a')
    spec_good.worker_file = good
    spec_good.allow_no_worker_check = False
    with contextlib.redirect_stdout(io.StringIO()):
        rc3 = KD.run_probe(a, mg, br, spec_good, gw_factory=lambda base, key: GW(clock, 10.0), sleep=clock.sleep, clock=clock, slot_check=lambda: None,
                           image_check=lambda *x, **k: (True, 'ok', 1.0), ledger=lambda rec: LEDGER.append(rec))
    check(rc3 != 3 or os.path.exists(os.path.join(tmp, 'out')), 'worker_file с ходом: проверка пройдена, группа создаётся')
    check(not KD.worker_progress_refusal(good), 'воркер с begin_job и step проходит')
    check('не читается' in KD.worker_progress_refusal(os.path.join(tmp, 'нет.py')), 'нет файла воркера — отказ')

# ---- сторож докачки ОБРАЗА (уроки 734/357; проба d2 21.11: 30 мин «downloading», нода медленная)
def line(rate_pct_min, minutes, start=0.0, step_s=10.0):
    """Наблюдения каждые 10 с: прогресс растёт rate_pct_min %/мин."""
    n = int(minutes * 60 / step_s)
    return [(i * step_s, min(1.0, start + rate_pct_min / 100.0 * (i * step_s / 60.0))) for i in range(n + 1)]


check(KD.pull_verdict(line(14, 8)) is None, 'докачка: быстрая (14 %/мин: образ за 7 мин, как d1) — не трогаем')
check(KD.pull_verdict(line(0.5, 10)) is not None, 'докачка: 0,5 %/мин, 5 % за 10 мин → пересадка (прогноз ≫15 мин)')
check(KD.pull_verdict(line(0.5, 7)) is None, 'докачка: до 8-й минуты не судим')
stuck = [(i * 10.0, 0.5) for i in range(61)]
check('не растёт' in (KD.pull_verdict(stuck) or ''), 'докачка: стоит на 50 % 10 мин → пересадка («не растёт»)')
check(KD.pull_verdict(line(3.0, 9, start=0.65)) is None, 'докачка: 92 % и темп 3 %/мин — доедет за ~2,5 мин, не трогаем')
check(KD.pull_verdict(line(0, 10, start=1.0)) is None, 'докачка: догрузившую (100 %) не трогаем никогда')
check(KD.pull_verdict([(0.0, 0.1)]) is None, 'докачка: одно наблюдение — судить не по чему')


def guard_with(calls, slots=1, ok=True, **kw):
    def take():
        nonlocal slots
        slots, got = max(0, slots - 1), (1 if slots else 0)
        return got
    return KD.PullGuard('g', take_slot=take, realloc=lambda g, i, w: (calls.append((g, i)) or ok), say_fn=lambda *a: None, **kw)


def feed(guard, iid, minutes, rate, t0=0.0):
    """Прогнать ноду iid минуту за минутой; вернуть, пересадили ли."""
    for k in range(int(minutes * 6) + 1):
        t = t0 + k * 10.0
        if guard.step(t, [{'id': iid, 'state': 'downloading', 'pulling_progress': min(1.0, rate / 100.0 * (k * 10.0 / 60.0))}]):
            return True
    return False


calls = []
g = guard_with(calls, slots=10)
check(feed(g, 'n1', 10, 0.5) and calls == [('g', 'n1')] and g.culls == 1, 'сторож: медленная нода → одна пересадка через общий бюджет')
check(feed(g, 'n2', 12, 0.5, t0=1000.0) and feed(g, 'n3', 12, 0.5, t0=2000.0) and g.culls == 3 and not g.give_up, 'сторож: до 3 пересадок на запуск (n1, n2, n3 — медленные)')
check(not feed(g, 'n4', 12, 0.5, t0=3000.0) and len(calls) == 3 and 'медленно качают все 4' in g.give_up, 'урок 357: после 3 пересадок и 4-я нода медленная → give_up (образ/сеть), по кругу не пересаживаем')

# норма — от размера образа и здоровой скорости, не константы мешей (владелец 21.11)
mt_ut, mt_mesh = KD.max_total_for_image(6.87), KD.max_total_for_image(26.0)
check(16.0 <= mt_ut <= 17.5 and 60.0 <= mt_mesh <= 66.0 and KD.max_total_for_image(None) == 15.0 and KD.max_total_for_image(0.5) == KD.PULL_FLOOR_MIN,
      f'норма: образ 6,87 ГиБ → {mt_ut:.1f} мин, образ мешей 26 ГиБ → {mt_mesh:.1f} мин, размер неизвестен → 15, не строже 10 ({KD.PULL_FLOOR_MIN})')
d2like = [(i * 10.0, min(0.5, 0.5 * i * 10.0 / 600.0)) for i in range(0, 181)]          # d2: за 10 мин 50 %, дальше стоит до 30-й минуты
d2_at_20 = [o for o in d2like if o[0] <= 1200]
check(KD.pull_verdict(d2_at_20, max_total_min=mt_ut) is not None, 'образ UltraTex: d2 (50 % и стоит 20 мин) → пересадка по норме образа')
check(KD.pull_verdict(line(3.0, 20), max_total_min=mt_ut) is not None, 'образ UltraTex 6,87 ГиБ: 3 %/мин (норма мешей для 26 ГиБ) → медленно, пересадка')
check(KD.pull_verdict(line(3.0, 20), max_total_min=mt_mesh) is None, 'образ мешей 26 ГиБ: те же 3 %/мин — здоровая нода, не трогаем (меши не изменены)')
check(KD.pull_verdict(line(15, 6.7), max_total_min=mt_ut) is None, 'образ UltraTex: здоровые 15 %/мин (d1: образ за ~7 мин) — не трогаем')
check(KD.pull_txt({'state': 'downloading', 'pulling_progress': 0.372}) == ' 37%' and KD.pull_txt({'state': 'running', 'pulling_progress': 1.0}) == '' and KD.pull_txt({'state': 'downloading'}) == '',
      'журнал: процент докачки виден только у downloading и только если Salad его отдал')

calls = []
g = guard_with(calls, slots=0)
check(not feed(g, 'n1', 10, 0.5) and calls == [], 'сторож: общий бюджет пересадок исчерпан → не пересаживает, ждёт')

calls = []
g = guard_with(calls, ok=False)
check(not feed(g, 'n1', 10, 0.5) and g.culls == 0, 'сторож: пересадка не удалась (404/ошибка) → не засчитана')

calls = []
g = guard_with(calls, max_culls=0)
check(not feed(g, 'n1', 10, 0.5) and calls == [], 'сторож: предел пересадок на запуск')

calls = []
g = guard_with(calls)
check(not feed(g, 'n1', 10, 14) and calls == [], 'сторож: быстрая нода не трогается')
check(not g.step(0.0, [{'id': 'x', 'state': 'running', 'pulling_progress': 0.1}, {'id': 'y', 'state': 'downloading'}]), 'сторож: running и без pulling_progress игнорируются')


# ---- в цикле пробы: медленная нода пересажена, «нода не выдана» считается заново, замена качает быстро → проба доходит до готовности
class PullBR(BR):
    """Первая нода качает 0,5 %/мин; после пересадки замена качает 12 %/мин и становится running."""
    def __init__(self, clock, second_rate=0.12):
        super().__init__(clock)
        self.realloc_at, self.second_rate, self.n = None, second_rate, 1

    def instances(self, name):
        if self.t0 is None:
            return 200, []
        now = self.clock()
        if self.realloc_at is None:
            return 200, [{'id': 'n1', 'state': 'downloading', 'started': False, 'pulling_progress': 0.005 * (now - self.t0) / 60.0}]
        pr = self.second_rate * (now - self.realloc_at) / 60.0
        if pr >= 1.0:
            return 200, [{'id': f'n{self.n}', 'state': 'running', 'started': True, 'pulling_progress': 1.0}]
        return 200, [{'id': f'n{self.n}', 'state': 'downloading', 'started': False, 'pulling_progress': pr}]


def drive_pull(tmp, running_min, fast_second=True, second_rate=0.12, max_culls=3, guard_on=True, spec_mod=None):
    clock = Clock()
    mg, br = MG(), PullBR(clock, second_rate)
    KD.gpu_class = lambda MG_, name, tier, fetch=None: ('cls', 0.6)
    orig = mg.api
    mg.api = lambda path, method='GET', body=None: (setattr(br, 't0', clock()) if (method == 'POST' and path.endswith('/start')) else None) or orig(path, method, body)
    calls = []

    def realloc(g_, iid, why):
        calls.append(iid)
        br.realloc_at = clock()
        br.n += 1
        if not fast_second:
            br.realloc_at = None
        return True
    a = argparse.Namespace(image='x@sha256:1', suffix='t', tier='high', apply=True, cap=4.0, probe_cap=1.0, max_min=600, running_min=running_min, start_min=20, health_min=8, ready_min=30,
                           stall_min=5, stall_gb=0.05, job_min=0, out=os.path.join(tmp, 'out'), pull_guard=guard_on)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        spec = make_spec('a')
        for k, v in (spec_mod or {}).items():
            setattr(spec, k, v)
        rc = KD.run_probe(a, mg, br, spec, gw_factory=lambda base, key: GW(clock, 100.0), sleep=clock.sleep, clock=clock, slot_check=lambda: None,
                          image_check=lambda *x, **k: (True, 'ok', 1.0), ledger=lambda rec: LEDGER.append(rec),
                          pull_guard=lambda name: KD.PullGuard(name, max_culls=max_culls, take_slot=lambda: 1, realloc=realloc))
    p = os.path.join(tmp, 'out', 'summary-kit-loop-t.json')
    return rc, (json.load(open(p)) if os.path.exists(p) else {}), buf.getvalue(), calls


with tempfile.TemporaryDirectory() as tmp:
    rc, summ, out, calls = drive_pull(tmp, running_min=14)
    check(calls == ['n1'] and summ.get('pull_culls') == 1 and summ.get('stopped_by') == 'done' and summ['jobs']['a']['status'] == 'done',
          f'цикл: медленная нода пересажена, замена доехала, проба готова (пересадок {calls}, {summ.get("stopped_by")})')
    check('сторож докачки: нода n1' in out, 'цикл: пересадка видна в журнале драйвера')

with tempfile.TemporaryDirectory() as tmp:
    clock_probe = drive_pull(tmp, running_min=14)
    check(clock_probe[1].get('stopped_by') != 'no_machine', '«нода не выдана» считается от пересадки, а не от /start (иначе 14-минутный срок вышел бы в ту же минуту)')

with tempfile.TemporaryDirectory() as tmp:
    rc, summ, out, calls = drive_pull(tmp, running_min=14, guard_on=False)
    check(summ.get('stopped_by') == 'no_machine' and calls == [] and summ.get('stop_verified') and summ.get('cost_usd_est', 9) == 0.0,
          'цикл: сторож выключен (--no-pull-guard), нода так и не пришла → no_machine, стоп с проверкой, $0 (до running не списывается)')

with tempfile.TemporaryDirectory() as tmp:
    rc, summ, out, calls = drive_pull(tmp, running_min=60, second_rate=0.005, max_culls=1)
    check(summ.get('stopped_by') == 'pull_slow' and calls == ['n1'] and summ.get('stop_verified') and summ.get('cost_usd_est', 9) == 0.0 and 'урок 357' in out,
          f'цикл: замена тоже медленная при max_culls=1 → стоп pull_slow (образ/сеть), $0, стоп с проверкой ({summ.get("stopped_by")}, пересадок {calls})')
    check(re.search(r'downloading \d+%', out) is not None, 'цикл: в минутной строке журнала виден процент докачки образа (d2 21.11: его не было)')

with tempfile.TemporaryDirectory() as tmp:
    rc, summ, out, calls = drive_pull(tmp, running_min=14, spec_mod={'card': 'RTX 5090 (32 GB)', 'cuda_archs': ('8.9',)})
    check(rc == 3 and 'no kernel image' in out and 'группу НЕ создаю' in out and not os.path.exists(os.path.join(tmp, 'out')), 'цикл: образ под 8.9 на карте 5090 — отказ ДО создания группы, код 3, /bin/bash (урок 742)')

print('\nИТОГ:', 'ВСЁ ЗЕЛЁНОЕ' if not FAILS else f'ПАДЕНИЙ {len(FAILS)}')
sys.exit(1 if FAILS else 0)
