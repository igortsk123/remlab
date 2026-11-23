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
    def __init__(self, clock, running_after=60.0, started_delay=0.0):
        self.clock, self.t0, self.running_after, self.started_delay = clock, None, running_after, started_delay
        self.stopped = 0

    def group_state(self, name):
        return 200, ('stopped' if self.t0 is None else 'running'), 1

    def instances(self, name):
        if self.t0 is None:
            return 200, []
        run = self.clock() - self.t0 >= self.running_after
        return 200, [{'state': 'running' if run else 'creating', 'started': self.is_started()}]

    def is_started(self):
        return self.t0 is not None and self.clock() - self.t0 >= self.running_after + self.started_delay

    def stop_and_verify(self, name):
        self.stopped += 1
        return True


class GW:
    """ready_after — через сколько секунд после создания шлюза нода «готова»; job_s — длительность задания; fail — задание падает."""
    post_code = -1                                                   # что отвечает POST /generate, пока post_fail > 0 (-1 = нет ответа, 503 = HTML шлюза)
    post_fail = 0                                                    # сколько первых POST /generate остаются без ответа (-1)
    accepted_on_timeout = False                                      # воркер при этом задание всё-таки принял

    def __init__(self, clock, ready_after=120.0, job_s=200.0, fail=False, stuck=False, silent=False, up=lambda: True):
        self.up = up
        self.clock, self.ready_after, self.job_s, self.fail, self.stuck, self.silent = clock, ready_after, job_s, fail, stuck, silent
        self.t0 = clock()
        self.jobs = {}
        self.dur = {}                                                # длительность каждого принятого задания (job_s — число или список по порядку приёма)

    def _next_dur(self):
        n = len(self.jobs)
        return self.job_s[min(n, len(self.job_s) - 1)] if isinstance(self.job_s, (list, tuple)) else self.job_s

    def call(self, method, path, body=None, timeout=60, raw=False):
        t = self.clock()
        if path == '/health':
            if not self.up():                                        # контейнер ещё не запущен — шлюз Salad отдаёт 503
                return 503, {}
            if self.silent:
                return 502, {}
            if self.stuck:                                           # докачка встала: фаза weights, папка не растёт
                return 200, {'phase': 'weights', 'root_gb': 1.0, 'weights': {}, 'error': ''}
            if t - self.t0 < self.ready_after:
                return 200, {'phase': 'weights', 'root_gb': round((t - self.t0) * 0.3, 2), 'weights': {}, 'error': ''}
            h = {'phase': 'ready', 'version': 'v', 'offload': 'swap', 'sparse': {'enabled': False}, 'error': '', 'root_gb': 36.0}
            run = [j for j, t0 in self.jobs.items() if t - t0 < self.dur[j]]
            if run:                                                  # воркер набора отдаёт ход задания в /health (kit_worker State.job_view)
                h['job'] = {'id': run[0], 'elapsed_s': round(t - self.jobs[run[0]], 1), 'step': 'sampling', 'step_s': 12.0, 'done': ['перенос encoder→gpu']}
            return 200, h
        if path in ('/generate', '/diag'):
            if path == '/generate' and GW.post_fail > 0:                 # клиент не дождался ответа (-1); воркер мог при этом принять задание
                GW.post_fail -= 1
                if GW.accepted_on_timeout:
                    self.dur[body['job_id']] = self._next_dur()
                    self.jobs[body['job_id']] = t
                return GW.post_code, {}
            if any(t - t0 < self.dur[j] for j, t0 in self.jobs.items()):    # как настоящий воркер: одно задание за раз
                return 429, {'error': 'занят другим заданием'}
            self.dur[body['job_id']] = self._next_dur()
            self.jobs[body['job_id']] = t
            return 202, {}
        if path.endswith('/glb'):
            return 200, b'GLB'
        if path.startswith('/result/'):
            jid = path.split('/')[2]
            if jid not in self.jobs:
                return 404, {}
            if t - self.jobs[jid] < self.dur[jid]:
                return 200, {'status': 'running'}
            if self.fail:
                return 200, {'status': 'failed', 'error': 'OOM'}
            return 200, {'status': 'done', 'metrics': {'vram_peak_gb': 29.1, 'total_s': 190}}
        return 404, {}


def setup(tmp, keys=('a', 'b', 'c', 'd')):
    sh, inp = os.path.join(tmp, 'shapes'), os.path.join(tmp, 'inputs')
    os.makedirs(sh)
    os.makedirs(inp)
    for k in keys:
        open(os.path.join(sh, f'{k}.prep.glb'), 'wb').write(b'g')
        open(os.path.join(inp, f'{k}.rgba.png'), 'wb').write(b'p')
    return sh, inp


def args(tmp, sh, inp, jobs, **kw):
    d = dict(image='ghcr.io/x/y:ultratex-bw', jobs=jobs, shape_dir=sh, shape_name='{key}.prep.glb', inputs=inp, out=os.path.join(tmp, 'out'), tier='low',
             resolution=2048, steps=25, seed=42, texture=4096, probe_cap=1.0, cap=4.0, max_min=120, running_min=30, health_min=8, ready_min=75, job_min=30, idle_s=900,
             suffix='t', apply=True, stop_only=False, stall_min=5, stall_gb=0.05, worker_from_image=False, start_min=20)
    d.update(kw)
    return argparse.Namespace(**d)


LEDGER = []


def drive(tmp, jobs, price=0.6, ready_after=120.0, job_s=200.0, fail=False, head=lambda u, t='': 200, running_after=60.0, stuck=False, silent=False, started_delay=0.0,
          slot=lambda: None, image=lambda *x, **k: (True, 'образ по digest, сжатый 6,87 ГиБ', 6.87), **kw):
    sh, inp = setup(tmp)
    clock = Clock()
    mg, br = MG(), BR(clock, running_after, started_delay)
    globals()['CLK'] = clock                                         # часы последнего прогона: тест затвора подменяет S.time.time
    KD.gpu_class = lambda MG_, name, tier, fetch=None: ('cls-5090', price)
    LEDGER.clear()
    orig_api = mg.api

    def api(path, method='GET', body=None):
        r = orig_api(path, method, body)
        if method == 'POST' and path.endswith('/start'):
            br.t0 = clock()
        return r
    mg.api = api
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = S.run(args(tmp, sh, inp, jobs, **kw), mg, br, gw_factory=lambda base, key: GW(clock, ready_after, job_s, fail, stuck, silent, br.is_started), sleep=clock.sleep, clock=clock, head_fn=head,
                    slot_check=slot, image_check=image, ledger=lambda rec: LEDGER.append(rec))
    summ = json.load(open(os.path.join(tmp, 'out', 'summary-trial-ultratex-t.json'))) if os.path.exists(os.path.join(tmp, 'out', 'summary-trial-ultratex-t.json')) else {}
    return rc, summ, out.getvalue(), mg, br


# 1. стоимость и потолки
check(abs(S.cost_usd(3600, 0.6, 0) - 0.6) < 1e-9, 'цена: час × $0,6 = $0,6')
check(S.cost_usd(0, 0.6) == 0.0, 'цена: running=0 → 0 (запас не начисляется)')
check(S.effective_cap(False, 1.0, 4.0) == 1.0 and S.effective_cap(True, 1.0, 4.0) == 4.0, 'потолок: до успеха $1, после — $4')
check(S.effective_cap(False, 5.0, 4.0) == 4.0, 'потолок: проба не выше общего')

# 2. тело группы: секреты не печатаются
body = S.build_body('n', 'img', 'low', 'cls', {'basic': {'password': 'SECRET-GHCR'}}, 'SECRET-HF', 7800, 900)
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    S.safe_print(body)
check('SECRET' not in buf.getvalue(), 'разбор: секреты скрыты')
check(body['container']['environment_variables']['ULTRATEX_OFFLOAD'] == 'swap' and body['container']['resources']['memory'] == 49152, 'тело: выгрузка swap, ОЗУ 48 ГБ')
check(body['container']['resources']['gpu_classes'] == ['cls'], 'тело: класс карты из списка Salad')

# 2б. сторож докачки по прогрессу
H = [(i * 10.0, i * 0.5) for i in range(40)]                 # растёт 0,5 ГБ / 10 с
check(not S.weights_stalled(H, 300, 0.05), 'сторож: растущая докачка — не стоп')
F = [(i * 10.0, 3.0) for i in range(40)]                     # 400 с на месте
check(S.weights_stalled(F, 300, 0.05), 'сторож: 5 мин без роста — стоп')
check(not S.weights_stalled(F[:20], 300, 0.05), 'сторож: история короче окна — ждём')
G = [(i * 10.0, i * 0.5) for i in range(20)] + [(200.0 + i * 10.0, 9.5) for i in range(1, 40)]
check(S.weights_stalled(G, 300, 0.05), 'сторож: росла, потом встала на 5 мин — стоп')

# 2в. код воркера в env группы (образ не пересобирается)
cmd, z = S.worker_command(os.path.join(HERE, 'worker_ultratex.py'))
check(cmd[:3] == ['python', '-u', '-c'] and len(z) > 1000, 'воркер: команда python -u -c и код в env')
b2 = S.build_body('n', 'img', 'low', 'cls', {}, 'T', 7800, 900, worker_z=z)
check(b2['container']['command'] == cmd and b2['container']['environment_variables']['KIT_WORKER_Z'] == z, 'тело: command и KIT_WORKER_Z заданы')
check(len(cmd[3]) < 1000, 'команда укладывается в лимит Salad 1000 знаков на элемент')
check('command' not in body['container'], 'тело без worker_z: команда из образа')
buf2 = io.StringIO()
with contextlib.redirect_stdout(buf2):
    S.safe_print(b2)
check(len(buf2.getvalue()) < 5000 and 'код воркера' in buf2.getvalue(), 'разбор: код воркера в печати не раздувает вывод')

# 2г. POST /generate без ответа (-1): таймаут по размеру тела, не отказ — воркера спрашиваем, один повтор в конец очереди (T-178 22.11, ваза Glasar)
with tempfile.TemporaryDirectory() as tmp:
    GW.post_fail, GW.accepted_on_timeout = 1, False
    try:
        rc, summ, out, mg, br = drive(tmp, 'a,b')
    finally:
        GW.post_fail = 0
    st = {k: v.get('status') for k, v in summ.get('jobs', {}).items()}
    check(st == {'a': 'done', 'b': 'done'} and summ.get('post_timeouts') and summ['post_timeouts'][0]['key'] == 'a' and 'один повтор в конец очереди' in out,
          'POST без ответа, воркер задание не видит → не провал: один повтор в конец очереди, оба готовы')
with tempfile.TemporaryDirectory() as tmp:
    GW.post_fail, GW.accepted_on_timeout = 1, True
    try:
        rc, summ, out, mg, br = drive(tmp, 'a,b')
    finally:
        GW.post_fail, GW.accepted_on_timeout = 0, False
    st = {k: v.get('status') for k, v in summ.get('jobs', {}).items()}
    check(st == {'a': 'done', 'b': 'done'} and not summ.get('post_timeouts') and 'воркер задание принял' in out, 'POST без ответа, но воркер задание принял → без повтора, то же задание считается')
with tempfile.TemporaryDirectory() as tmp:
    GW.post_fail, GW.accepted_on_timeout = 99, False
    try:
        rc, summ, out, mg, br = drive(tmp, 'a')
    finally:
        GW.post_fail = 0
    check(summ.get('jobs', {}).get('a', {}).get('status') == 'not_accepted' and len(summ.get('post_timeouts', [])) == int(KD.gateway_post_rules().get('requeue_max', 1)),f'повтор тоже без ответа → not_accepted (повторов ровно gateway_post.requeue_max={KD.gateway_post_rules().get("requeue_max", 1)}, не бесконечно)')

with tempfile.TemporaryDirectory() as tmp:
    GW.post_fail, GW.post_code, GW.accepted_on_timeout = 1, 503, False
    try:
        rc, summ, out, mg, br = drive(tmp, 'a,b')
    finally:
        GW.post_fail, GW.post_code = 0, -1
    st = {k: v.get('status') for k, v in summ.get('jobs', {}).items()}
    check(st == {'a': 'done', 'b': 'done'} and summ.get('post_timeouts') and summ['post_timeouts'][0].get('code') == 503 and 'код 503' in out,
          '503 (HTML шлюза) на POST → то же, что нет ответа: воркер задание не видит → один повтор в конец очереди, оба готовы, код 503 в сводке')
with tempfile.TemporaryDirectory() as tmp:
    GW.post_fail, GW.post_code = 99, 503
    try:
        rc, summ, out, mg, br = drive(tmp, 'a')
    finally:
        GW.post_fail, GW.post_code = 0, -1
    check(summ.get('jobs', {}).get('a', {}).get('status') == 'not_accepted' and summ['jobs']['a'].get('http') == 503, '503 два раза подряд → not_accepted с кодом 503 в причине')

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
    rc, summ, out, mg, br = drive(tmp, 'a', running_after=99999, running_min=5, tier_fallback=False)       # без перехода low→medium (его — тест в tests_kit_loop)
    check(rc == 1 and summ.get('stopped_by') == 'no_machine' and summ.get('stop_verified'), 'нода не выдана за 5 мин: стоп no_machine')

# 10. нет входных файлов
with tempfile.TemporaryDirectory() as tmp:
    rc, summ, out, mg, br = drive(tmp, 'zzz')
    check(rc == 3 and not mg.created, 'нет входных файлов: стоп до создания группы')

# 11. докачка встала — стоп по прогрессу раньше потолка прогрева
with tempfile.TemporaryDirectory() as tmp:
    rc, summ, out, mg, br = drive(tmp, 'a', stuck=True, ready_min=30)
    check(rc == 1 and summ.get('stopped_by') == 'download_stalled' and summ.get('stop_verified'), f'докачка встала: стоп download_stalled ({summ.get("stopped_by")})')
    check(summ.get('cost_usd_est', 9) < 0.2, f'расход при застое мал (${summ.get("cost_usd_est")})')

# 12. шлюз отвечает 502 — код ответа в журнале, стоп no_health
with tempfile.TemporaryDirectory() as tmp:
    rc, summ, out, mg, br = drive(tmp, 'a', silent=True)
    check(summ.get('stopped_by') == 'no_health' and '/health 502' in out and summ.get('last_health', {}).get('http') == 502, 'нет ответа: в журнале «/health 502», стоп no_health')

# 13. потолок прогрева 30 мин
with tempfile.TemporaryDirectory() as tmp:
    rc, summ, out, mg, br = drive(tmp, 'a', ready_after=99999, ready_min=30, stall_min=999, max_min=500)
    check(summ.get('stopped_by') == 'not_ready', f'прогрев дольше 30 мин: стоп not_ready ({summ.get("stopped_by")})')

# 14. в журнале есть ход докачки (root_gb)
with tempfile.TemporaryDirectory() as tmp:
    rc, summ, out, mg, br = drive(tmp, 'a')
    check('root_gb' in out, 'в минутной строке журнала — root_gb')

# 15. контейнер долго поднимается (шлюз 503 дольше health-min) — НЕ стоп; потом работа идёт
with tempfile.TemporaryDirectory() as tmp:
    rc, summ, out, mg, br = drive(tmp, 'a', started_delay=900.0, ready_min=60, max_min=300, probe_cap=2.0, cap=2.0)
    check(rc == 0 and summ.get('stopped_by') == 'done' and 'контейнер запущен' in out, f'контейнер стартовал через 15 мин: не гасим, задание готово ({summ.get("stopped_by")})')

# 16. контейнер так и не запустился — стоп no_start на start_min
with tempfile.TemporaryDirectory() as tmp:
    rc, summ, out, mg, br = drive(tmp, 'a', started_delay=99999.0, ready_min=60, max_min=300, start_min=20)
    check(summ.get('stopped_by') == 'no_start' and summ.get('stop_verified'), f'контейнер не стартует: стоп no_start ({summ.get("stopped_by")})')

# 17. общий набор: учёт денег — ровно одна строка на пробу, с расходом и причиной
with tempfile.TemporaryDirectory() as tmp:
    rc, summ, out, mg, br = drive(tmp, 'a')
    check(len(LEDGER) == 1 and LEDGER[0]['group'] == 'trial-ultratex-t' and LEDGER[0]['stopped_by'] == 'done' and LEDGER[0]['cost_usd_est'] == summ['cost_usd_est'],
          'учёт денег: одна строка на пробу (группа, причина, расход)')
    check(LEDGER[0]['jobs_done'] == 1 and LEDGER[0]['model'] == 'ultratex', 'учёт: готовых заданий и модель')

# 18. нет heavy-slot --prio 2 — отказ ДО создания группы
with tempfile.TemporaryDirectory() as tmp:
    def no_slot():
        raise KD.SlotRefused('нет heavy-slot')
    rc, summ, out, mg, br = drive(tmp, 'a', slot=no_slot)
    check(rc == 4 and not mg.created and br.stopped == 0 and 'ОТКАЗ' in out, 'без heavy-slot: отказ (код 4), группа не создана, денег нет')

# 19. образ не по digest или тяжелее 30 ГиБ — отказ ДО создания группы
with tempfile.TemporaryDirectory() as tmp:
    rc, summ, out, mg, br = drive(tmp, 'a', image=lambda *x, **k: (False, 'сжатый образ 40.0 ГиБ больше 30', 40.0))
    check(rc == 3 and not mg.created and br.stopped == 0, 'образ не годится: код 3, группа не создана')

# 20. строка учёта пишется и при стопе по причине (деньги потрачены — должны быть в счёте)
with tempfile.TemporaryDirectory() as tmp:
    rc, summ, out, mg, br = drive(tmp, 'a', ready_after=99999, ready_min=500, max_min=500)
    check(len(LEDGER) == 1 and LEDGER[0]['stopped_by'] == 'probe_cap' and LEDGER[0]['cost_usd_est'] > 0.9, 'учёт: стоп по потолку тоже в счёте')

# 21. p4 21.11: задание срезано по --job-min, нода ещё считает → 429 на следующем НЕ провал (ключ в очередь, ждём), серия не горит
with tempfile.TemporaryDirectory() as tmp:
    rc, summ, out, mg, br = drive(tmp, 'a,b', job_s=[900.0, 300.0], job_min=10)         # a идёт 15 мин (срежут на 10-й), b — 5 мин
    check(summ.get('stopped_by') != 'fail_streak' and summ['jobs'].get('b', {}).get('status') == 'done' and summ['jobs'].get('a', {}).get('status') == 'timeout',
          f'429 «занят» не провал: a срезано, b принято после освобождения ноды и готово ({summ.get("stopped_by")}, {[(k, v.get("status")) for k, v in summ.get("jobs", {}).items()]})')
    check('нода занята (429)' in out and 'не принято' not in out, '429: в журнале «жду, не провал», «не принято» нет')
    check(summ.get('failed') == 1 and br.stopped >= 1 and summ.get('stop_verified'), 'после ожидания: failed=1 (только срезанное), стоп с проверкой')

# 22. job_min=0 (по умолчанию): задание живёт до потолка пробы, не срезается на 30-й минуте (p4: срезка лишила результата)
with tempfile.TemporaryDirectory() as tmp:
    rc, summ, out, mg, br = drive(tmp, 'a', job_s=3000.0, job_min=0)
    check(summ['jobs'].get('a', {}).get('status') == 'done' and 'снимаю' not in out, f'job_min=0: задание 50 мин дожило до готовности ({summ["jobs"]})')

# 23. потолок пробы остаётся последней защитой: задание бесконечное + job_min=0 → стоп по потолку, не вечный счёт
with tempfile.TemporaryDirectory() as tmp:
    rc, summ, out, mg, br = drive(tmp, 'a', job_s=10 ** 9, job_min=0)
    check(summ.get('stopped_by') == 'probe_cap' and summ.get('stop_verified') and summ.get('cost_usd_est', 9) <= 1.05, f'job_min=0 + вечное задание: стоп по потолку ({summ.get("stopped_by")}, ${summ.get("cost_usd_est")})')

# 24. ход задания: из /health ready-ноды в журнал (какой шаг, сколько идёт)
with tempfile.TemporaryDirectory() as tmp:
    rc, summ, out, mg, br = drive(tmp, 'a', job_s=400.0)
    check('ход задания a: шаг «sampling»' in out, 'ход задания из /health виден в журнале драйвера')

# 25. диагностика без весов (T-178/1): тело группы — без ключа HF, ULTRATEX_NO_WEIGHTS=1, диск 20 ГиБ; переменные памяти проходят, посторонние — отказ
dbody = S.build_body('n', 'img', 'low', 'cls', {}, 'SECRET-HF', 7800, 900, diag=True, extra_env={'ULTRATEX_MEM_CHUNK': '2048'})
denv = dbody['container']['environment_variables']
check(denv.get('ULTRATEX_NO_WEIGHTS') == '1' and 'HF_TOKEN' not in denv and denv.get('ULTRATEX_MEM_CHUNK') == '2048', 'диагностика: без токена HF, режим без весов, переменная памяти передана')
check(dbody['container']['resources']['storage_amount'] == 20 * 2 ** 30, 'диагностика: диск 20 ГиБ вместо 80 (весов нет)')
check(S.parse_env(['ULTRATEX_CFG=off']) == {'ULTRATEX_CFG': 'off'}, '--env ULTRATEX_*=значение разобран')
check(S.parse_env(['PYTORCH_CUDA_ALLOC_CONF=garbage_collection_threshold:0.9']) == {'PYTORCH_CUDA_ALLOC_CONF': 'garbage_collection_threshold:0.9'}, '--env PYTORCH_CUDA_ALLOC_CONF разрешён (сравнение аллокаторов)')
try:
    S.parse_env(['HF_TOKEN=x'])
    check(False, '--env с посторонней переменной отклонён')
except SystemExit:
    check(True, '--env с посторонней переменной (секрет) отклонён')

# 26. диагностика: задание /diag проходит тем же общим ходом, результат — diag.json, стоп с проверкой, учёт
with tempfile.TemporaryDirectory() as tmp:
    rc, summ, out, mg, br = drive(tmp, '', ready_after=20.0, job_s=90.0, diag=True, diag_params='{"lengths": [1000]}', env=['ULTRATEX_MEM_CHUNK=2048'])
    check(rc == 0 and summ['jobs'].get('diag', {}).get('status') == 'done' and os.path.exists(os.path.join(tmp, 'out', 'diag.json')), f'диагностика: задание готово, diag.json записан ({summ.get("jobs")})')
    check(br.stopped >= 1 and summ.get('stop_verified') and LEDGER and LEDGER[0]['model'] == 'ultratex-diag', 'диагностика: стоп с проверкой и строка учёта с моделью ultratex-diag')

# 27. пакет «затвор → веса → задания» на одной ноде (--diag-first): в теле группы ULTRATEX_DIAG_FIRST=1, токен HF и веса остаются, диск 80 ГиБ; без флага — нет
os.environ['HF_TOKEN'] = 'SECRET-HF'
_a = argparse.Namespace(image='img@sha256:1', jobs='k1', shape_dir=tmp_shape if 'tmp_shape' in globals() else '/nonexistent', shape_name='{key}.prep.glb', inputs='/nonexistent', tier='low',
                        max_min=120, idle_s=900, env=['ULTRATEX_MEM_CHUNK=4096'], diag=False, diag_first=True)
_b = S.make_spec(_a).build_body('n', 'cls', {})
_e = _b['container']['environment_variables']
check(_e.get('ULTRATEX_DIAG_FIRST') == '1' and _e.get('HF_TOKEN') == 'SECRET-HF' and _e.get('ULTRATEX_MEM_CHUNK') == '4096' and 'ULTRATEX_NO_WEIGHTS' not in _e
      and _b['container']['resources']['storage_amount'] == 80 * 2 ** 30, '--diag-first: затвор включён, веса и ключ HF на месте, диск 80 ГиБ, переменные памяти проходят')
_a.diag_first = False
_a.diag_params = ''
check(os.path.isfile(S.make_spec(_a).worker_file) and os.path.isfile(S.make_diag_spec(_a).worker_file)
      and not S.KD.worker_progress_refusal(S.make_spec(_a).worker_file), 'worker_file указан (оба Spec) и воркер UltraTex отдаёт ход задания (begin_job + шаги) — п.16')
check(S.make_spec(_a).cuda_archs == ('12.0',) and S.make_diag_spec(_a).cuda_archs == ('12.0',) and S.KD.arch_refusal(S.CARD_NAME, S.CUDA_ARCHS) == ''
      and S.KD.arch_refusal('RTX 4090 (24 GB)', S.CUDA_ARCHS) != '', 'п.6: образ заявляет sm_120; карта 5090 проходит, чужая архитектура — отказ до группы')
check('ULTRATEX_DIAG_FIRST' not in S.make_spec(_a).build_body('n', 'cls', {})['container']['environment_variables'], 'без --diag-first затвора нет')

# 28. пакет 27 (T-178/3): --fail-streak (по умолчанию 2, пакет 3), файл-стоп STOP, затвор контроля --gate-first-min (остальные — только после GO)
with tempfile.TemporaryDirectory() as tmp:
    rc, summ, out, mg, br = drive(tmp, 'a,b,c,d', ready_after=20.0, job_s=60.0, fail=True)
    check(summ.get('stopped_by') == 'fail_streak' and summ.get('failed') == 2, f'по умолчанию стоп на 2 отказах подряд ({summ.get("stopped_by")}, failed {summ.get("failed")})')
with tempfile.TemporaryDirectory() as tmp:
    rc, summ, out, mg, br = drive(tmp, 'a,b,c,d', ready_after=20.0, job_s=60.0, fail=True, fail_streak=3)
    check(summ.get('stopped_by') == 'fail_streak' and summ.get('failed') == 3 and br.stopped >= 1 and summ.get('stop_verified'), f'--fail-streak 3: стоп на 3-м отказе, не на 2-м, нода погашена ({summ.get("failed")})')
with tempfile.TemporaryDirectory() as tmp:
    os.makedirs(os.path.join(tmp, 'out'))
    open(os.path.join(tmp, 'out', 'STOP'), 'w').write('')
    rc, summ, out, mg, br = drive(tmp, 'a,b', ready_after=20.0, job_s=60.0)
    check(summ.get('stopped_by') == 'planned' and not summ.get('jobs') and 'файл-стоп' in summ.get('planned_reason', ''), 'файл STOP: плановый стоп до первого задания, ни одно не отправлено')
import types
_real_time = S.time
with tempfile.TemporaryDirectory() as tmp:
    S.time = types.SimpleNamespace(time=lambda: CLK.t, strftime=_real_time.strftime, gmtime=_real_time.gmtime)
    try:
        rc, summ, out, mg, br = drive(tmp, 'a,b,c', ready_after=20.0, job_s=60.0, gate_first_min=5)
    finally:
        S.time = _real_time
    check(summ.get('stopped_by') == 'planned' and set(summ.get('jobs', {})) == {'a'} and summ['jobs']['a']['status'] == 'done' and 'GO' in summ.get('planned_reason', '')
          and br.stopped >= 1, f'затвор: первое (контрольное) готово, GO нет → остальные не посланы, через 5 мин плановый стоп ({summ.get("stopped_by")}, {list(summ.get("jobs", {}))})')
with tempfile.TemporaryDirectory() as tmp:
    os.makedirs(os.path.join(tmp, 'out'))
    open(os.path.join(tmp, 'out', 'GO'), 'w').write('')
    S.time = types.SimpleNamespace(time=lambda: CLK.t, strftime=_real_time.strftime, gmtime=_real_time.gmtime)
    try:
        rc, summ, out, mg, br = drive(tmp, 'a,b,c', ready_after=20.0, job_s=60.0, gate_first_min=5)
    finally:
        S.time = _real_time
    check(rc == 0 and summ.get('stopped_by') == 'done' and set(summ.get('jobs', {})) == {'a', 'b', 'c'}, 'затвор: файл GO есть → все три задания идут на той же ноде')
with tempfile.TemporaryDirectory() as tmp:
    S.time = types.SimpleNamespace(time=lambda: CLK.t, strftime=_real_time.strftime, gmtime=_real_time.gmtime)
    try:
        rc, summ, out, mg, br = drive(tmp, 'a,b,c', ready_after=20.0, job_s=60.0, fail=True, gate_first_min=5)
    finally:
        S.time = _real_time
    check(set(summ.get('jobs', {})) == {'a'} and str(summ.get('stopped_by', '')).startswith('контрольное') and br.stopped >= 1, f'затвор: первое упало → остальные не шлём, аварийный стоп ({summ.get("stopped_by")})')

# T-178/3 (22.11): параметры по заданию — пара «штатно | лёгкий» на одной группе
check(S.split_job('112923_1@lite') == ('112923_1', 'lite') and S.split_job('112923_1') == ('112923_1', ''), 'задание key@вариант: товар и вариант разделяются, без @ — вариант пуст')
V = S.parse_variants('{"std": {}, "lite": {"resolution": 1024, "steps": 12, "texture_size": 1024}}')
_a = types.SimpleNamespace(resolution=2048, steps=25, seed=42, texture=4096)
check(S.job_params(_a, V, 'x@lite') == {'resolution': 1024, 'steps': 12, 'seed': 42, 'texture_size': 1024} and S.job_params(_a, V, 'x@std') == {'resolution': 2048, 'steps': 25, 'seed': 42, 'texture_size': 4096}
      and S.job_params(_a, V, 'x') == {'resolution': 2048, 'steps': 25, 'seed': 42, 'texture_size': 4096}, 'параметры задания: вариант переопределяет только свои ключи, остальное — общие')
check((S.DEF_RESOLUTION, S.DEF_STEPS, S.DEF_TEXTURE) == (1024, 20, 1024), 'T-189/5: режим UltraTex по умолчанию — 1024·20 (текстура 1024), качественный — только вариантом')
for bad in ('{"lite": {"foo": 1}}', '{"lite": {"steps": "12"}}', '{"li te": {"steps": 12}}', '[1]', 'не json'):
    try:
        S.parse_variants(bad)
        check(False, f'--variants {bad}: должен отказать')
    except SystemExit:
        check(True, f'--variants {bad}: отказ до группы')
try:
    S.job_params(_a, V, 'x@нет')
    check(False, 'неизвестный вариант: отказ')
except SystemExit:
    check(True, 'неизвестный вариант задания: отказ до денег')

# в тело /generate уходят параметры варианта (проверка через настоящий submit спецификации, подставной шлюз)
with tempfile.TemporaryDirectory() as tmp:
    sh_, inp_ = setup(tmp)
    got = []

    class _G:
        def call(self, method, path, body=None, timeout=60, raw=False):
            if method == 'POST':
                got.append(body)
            return 202, {}
    spec = S.make_spec(args(tmp, sh_, inp_, 'a@std,a@lite', variants='{"std": {}, "lite": {"resolution": 1024, "steps": 12, "texture_size": 1024}}'))
    for j in ('a@std', 'a@lite'):
        cur, _x = spec.submit(_G(), j, 1000.0)
    ps = [{k: b[k] for k in ('resolution', 'steps', 'texture_size', 'seed')} for b in got if b and 'job_id' in b]
    check(ps == [{'resolution': 2048, 'steps': 25, 'texture_size': 4096, 'seed': 42}, {'resolution': 1024, 'steps': 12, 'texture_size': 1024, 'seed': 42}]
          and got[0]['job_id'] != got[1]['job_id'] and '@' not in got[1]['job_id'], f'submit: штатно 2048/25/4096, лёгкий 1024/12/1024, разные job_id без «@» ({ps})')
    try:
        S.make_spec(args(tmp, sh_, inp_, 'a@нет'))
        check(False, 'make_spec: неизвестный вариант должен отказать')
    except SystemExit:
        check(True, 'make_spec: задание с неизвестным вариантом — отказ до группы')

print('\nИТОГ:', 'ВСЁ ЗЕЛЁНОЕ' if not FAILS else f'ПАДЕНИЙ {len(FAILS)}')
sys.exit(1 if FAILS else 0)
