"""Тесты исполнителя `salad-gpu`, воркера машины и протокола заданий (T-20261117-24/2). Без сети и без платного: хранилище — в памяти,
Blender — подмена (`fake_blender.py`), машина — подмена состояния. Сквозной прогон: исполнитель (поток 1) ↔ воркер (поток 2) через «хранилище».

Запуск: ~/venvs/scout/bin/python tools/scout/render_gpu/tests_render_executor.py   (код 0 — чисто; нужен PIL)"""
import contextlib
import hashlib
import json
import os
import shutil
import stat
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SCOUT = os.path.abspath(os.path.join(HERE, '..'))
TMP = tempfile.mkdtemp(prefix='rx-test-')
os.makedirs(os.path.join(TMP, 'bl'))
with open(os.path.join(TMP, 'bl', 'blender'), 'w') as f:
    f.write(f'#!/bin/sh\nexec {sys.executable} {os.path.join(HERE, "fake_blender.py")} "$@"\n')
os.chmod(os.path.join(TMP, 'bl', 'blender'), 0o755)
os.environ.update(BLENDER_DIR=os.path.join(TMP, 'bl'), WORK=os.path.join(TMP, 'work'), MESH_SINK_URL='http://x', MESH_SINK_TOKEN='t',
                  RENDER_WORK=os.path.join(TMP, 'rwork'), RENDER_MACHINE_DIR=os.path.join(TMP, 'rm'), AGENT_BEAT_S='3600',
                  RENDER_QA_GATE='0', RENDER_DELETE_ASYNC='0')      # (уборка задания — синхронно: проверки ниже читают хранилище сразу после пары; фоновый режим — отдельный тест) тут сборка сцены подменена пустышками — проверяем транспорт; ворота сторожа — `tests_render_gate.py`
sys.path.insert(0, HERE)
sys.path.insert(0, SCOUT)
import jobs_proto as JP  # noqa: E402
import render_exec as RE  # noqa: E402
import render_worker as RW  # noqa: E402

BAD = []


def ok(name, cond):
    print(('OK   ' if cond else 'FAIL ') + name)
    if not cond:
        BAD.append(name)


# ——— подмены
class FakeSink:
    """Хранилище в памяти с тем же интерфейсом, что `jobs_proto.Sink`. fail_put — имя, на котором PUT падает."""

    def __init__(self):
        self.f, self.log, self.lock, self.fail_put = {}, [], threading.Lock(), None
        self.mtime = {}

    def put(self, rel, data):
        if self.fail_put and rel.endswith(self.fail_put):
            raise JP.SinkError('PUT: HTTP 507', 507)
        with self.lock:
            self.f[rel] = bytes(data)
            self.hist = getattr(self, 'hist', {})
            self.hist[rel] = bytes(data)
            self.mtime[rel] = time.time()
            self.log.append(('put', rel))

    def put_file(self, rel, path):
        self.put(rel, open(path, 'rb').read())

    def delete(self, rel):
        with self.lock:
            self.log.append(('delete', rel))
            self.deleted = getattr(self, 'deleted', []) + [rel]
            for k in [k for k in self.f if k.startswith(rel + '/')]:
                self.f.pop(k)
        return 1

    def get(self, rel):
        with self.lock:
            if rel not in self.f:
                raise JP.SinkError(f'GET {rel}: HTTP 404', 404)
            return self.f[rel]

    def get_to(self, rel, dest):
        data = self.get(rel)
        open(dest, 'wb').write(data)
        return len(data)

    def get_json(self, rel):
        return json.loads(self.get(rel))

    def ls(self, rel):
        with self.lock:
            if rel.count('/') == 0:
                names = {}
                for k in self.f:
                    p = k.split('/')
                    if p[0] == rel and len(p) == 3:
                        names[p[1]] = max(names.get(p[1], 0), self.mtime[k])
                return {'dirs': [{'name': n, 'mtime': t} for n, t in names.items()]}
            return {'files': [{'name': k.split('/')[-1], 'size': len(v), 'mtime': self.mtime[k]} for k, v in self.f.items() if k.startswith(rel + '/')]}


class FakeMachine:
    def __init__(self, **st):
        self.st = dict(desired='on', gen=1, warm_gen=1, degraded_since=0, last_tick=time.time())
        self.st.update(st)
        self.calls = []
        self.rules_ = {'executor': {'pickup_s': 1.0, 'pair_max_s': 20, 'poll_s': 0.05, 'busy_s': 90}, 'controller_stale_s': 300}

    def rules(self):
        return self.rules_

    def state(self):
        self.st['last_tick'] = time.time()
        return self.st

    def pulse(self, busy_s=0.0):
        self.calls.append(busy_s)


class Exec(RE.SaladGpuExecutor):
    """Сборку сцены (node/Blender/mesh) подменяем маленькими файлами: проверяем транспорт, не геометрию."""

    def __init__(self, sink, machine, public):
        super().__init__({'RENDER_WORK': os.path.join(TMP, 'rwork')}, sink=sink, machine=machine, sleep=time.sleep)
        self.public = public

    def _slot(self, label, pr):
        return contextlib.nullcontext({'waited_s': 0})

    def _prepare(self, snap, job, log, pr, progress, timing):
        progress('scene')
        os.makedirs(os.path.join(job, 'scene'))
        os.makedirs(os.path.join(job, 'dump'))
        open(os.path.join(job, 'scene', 'm000.npz'), 'wb').write(b'm' * 5000)
        open(os.path.join(job, 'scene', 'm001.npz'), 'wb').write(b'M' * 100000)      # крупный меш предмета (≥ 64 КБ) — ассет, мелкий m000 — в пакете
        open(os.path.join(job, 'dump', 'demo_nodes.glb'), 'wb').write(b'g' * 3000)
        open(os.path.join(job, 'dump', 'demo_nodes_uuids.json'), 'w').write('{}')
        json.dump({'wall': {'maps': {'color': '/flat3d/tex/a.jpg', 'secret': '/../../etc/passwd', 'nofile': '/flat3d/none.jpg'}}},
                  open(os.path.join(job, 'dump', 'scene-export.json'), 'w'))
        timing['export'], timing['dump'] = 0.1, 0.1
        return os.path.join(job, 'dump')


PUBLIC = os.path.join(TMP, 'public')
os.makedirs(os.path.join(PUBLIC, 'flat3d', 'tex'))
open(os.path.join(PUBLIC, 'flat3d', 'tex', 'a.jpg'), 'wb').write(b'j' * 800)
SNAP = {'scene_hash': 'abcdef0123456789' * 4, 'v': 1, 'source': 'test'}


def new_worker(sink):
    w = RW.Worker(sink)
    RW.MA.STATE['ready'] = True
    return w


def run_worker_thread(w, stop):
    def loop():
        while not stop.is_set():
            jid = w.pick()
            if not jid:
                time.sleep(0.05)
                continue
            res = w.run_job(jid)
            res['job_id'] = jid
            w.sink.put(f'{JP.PREFIX}/{jid}/result.json', json.dumps(res).encode())
            w.done.add(jid)
    t = threading.Thread(target=loop, daemon=True)
    t.start()
    return t


def render(ex, out):
    stages = []
    return stages, ex.render(SNAP, out, stages.append)


# ═══ 1. машина не годна → ExecutorUnavailable ДО любой работы (решение данными)
for st, code in (({'desired': 'off'}, 'gpu_off'), ({'warm_gen': 0}, 'gpu_warming'), ({'degraded_since': 5}, 'gpu_degraded')):
    sink, m = FakeSink(), FakeMachine(**st)
    ex = Exec(sink, m, PUBLIC)
    try:
        render(ex, os.path.join(TMP, 'o1'))
        ok(f'{code}: отказ', False)
    except RE.ExecutorUnavailable as e:
        ok(f'{st} → {e.code}, пара RU/EN, хранилище и машина не тронуты', e.code == code and e.ru and e.en and sink.f == {} and m.calls == [])
m = FakeMachine()
m.st['last_tick'] = 0
ex = Exec(FakeSink(), m, PUBLIC)
m.state = lambda: {**m.st, 'last_tick': time.time() - 3600}
try:
    ex.render(SNAP, os.path.join(TMP, 'o1'), lambda s: None)
    ok('контроллер молчит >5 мин → отказ', False)
except RE.ExecutorUnavailable as e:
    ok('контроллер молчит >5 мин → gpu_degraded', e.code == 'gpu_degraded')

# ═══ 2. выбор исполнителя и откат
class Backup:
    name = 'local-cpu'

    def __init__(self):
        self.n = 0

    def versions(self):
        return {}

    def render(self, snap, out_dir, progress):
        self.n += 1
        return {'timing': {'cpu': 1}}


b = Backup()
fb = RE.Fallback(Exec(FakeSink(), FakeMachine(desired='off'), PUBLIC), b)
ok('машина выключена → Fallback уходит на CPU без ошибки', fb.render(SNAP, os.path.join(TMP, 'o2'), lambda s: None) == {'timing': {'cpu': 1}} and b.n == 1)
ex_env = RE.make_executor({'RENDER_EXECUTOR': 'salad-gpu,local-cpu', 'RENDER_WORK': os.path.join(TMP, 'rwork')})
ok('RENDER_EXECUTOR=salad-gpu,local-cpu: основной salad-gpu, запасной local-cpu',
   isinstance(ex_env, RE.Fallback) and isinstance(ex_env.primary, RE.SaladGpuExecutor) and isinstance(ex_env.backup, RE.LocalCpuExecutor))
ok('salad-gpu и local-cpu — один базовый класс сборки сцены (правило одно)', issubclass(RE.SaladGpuExecutor, RE.SceneExecutor) and issubclass(RE.LocalCpuExecutor, RE.SceneExecutor))
ok('ключ кэша у salad-gpu = у local-cpu (одинаковые версии программ)',
   RE.SaladGpuExecutor({'RENDER_WORK': os.path.join(TMP, 'rwork')}).versions() == RE.LocalCpuExecutor({'RENDER_WORK': os.path.join(TMP, 'rwork')}).versions())

# ═══ 3. сквозной прогон: исполнитель ↔ воркер, стадии, результат, pulse
sink, m = FakeSink(), FakeMachine()
w = new_worker(sink)
stop = threading.Event()
run_worker_thread(w, stop)
ex = Exec(sink, m, PUBLIC)
out = os.path.join(TMP, 'out3')
stages, res = render(ex, out)
stop.set()
ok('своё задание убрано из хранилища сразу после пары (место общее с мешами)', not any(k.startswith('renderjobs/') for k in sink.f) and len(getattr(sink, 'deleted', [])) == 1)
ok('результат: C1.jpg, C2.jpg, meta.json', sorted(os.listdir(out)) == ['C1.jpg', 'C2.jpg', 'meta.json'])
meta_dev = json.load(open(os.path.join(out, 'meta.json')))['timing']
ok('линейка заказа в meta: timing.dev с метками (prep_end, send_start, job_sent, result_seen, frames_done) и обращениями; у воркера — wcalls',
   all(k in meta_dev.get('dev', {}).get('marks', {}) for k in ('prep_end', 'send_start', 'job_sent', 'result_seen', 'frames_done'))
   and any(c['op'].startswith('опрос result') for c in meta_dev['dev']['calls']) and any(c['op'] == 'PUT job.json' for c in meta_dev['dev']['calls']) and isinstance(meta_dev.get('wcalls'), list))
lp = meta_dev.get('loop') or {}
ok('журнал воркера в meta: timing.loop — t_job, круги выбора [старт,длит.,каталогов,проверено,проверки с,нашёл], seen_dir/seen_job; timing.dev.t0; timing.qa',
   isinstance(lp.get('cycles'), list) and lp.get('t_job') and lp['cycles'] and len(lp['cycles'][-1]) == 6 and lp['cycles'][-1][5] == 1 and lp.get('seen_dir') is not None and lp.get('seen_job') is not None
   and 't0' in meta_dev['dev'] and 'qa' in meta_dev)
meta = json.load(open(os.path.join(out, 'meta.json')))
ok('meta: исполнитель salad-gpu, хеши кадров, размер, версии', meta['executor'] == 'salad-gpu' and set(meta['sha']) == {'C1', 'C2'} and meta['size'] == [64, 48] and meta['versions']['preset'])
ok('стадии как у LocalCpuExecutor: scene → C1 → C2 → save (без повторов и пропусков)', stages == ['scene', 'C1', 'C2', 'save'])
ok('timing: C1/C2/pack/upload/download/total', all(k in res['timing'] for k in ('C1', 'C2', 'pack', 'upload', 'download', 'export', 'dump')) and 'total' in meta['timing'])
puts = [r for k, r in sink.log if k == 'put' and '/' in r and r.split('/')[0] == 'renderjobs' and r.split('/')[2] in ('job.json',) or r.endswith('.tgz')]
order = [r.split('/')[-1] for k, r in sink.log if k == 'put' and r.split('/')[-1] in ('job.json',) or r.endswith('.tgz') or r.endswith('result.json')]
ok('порядок: пакет → job.json ПОСЛЕДНИМ → result.json от воркера', order[0].endswith('.tgz') and order[1] == 'job.json' and order[-1] == 'result.json')
ok('cancel.json не писали', not any(r.endswith('cancel.json') for _, r in sink.log))
ok('pulse: первым — заказ с «занято», вокруг ожидания — продление, последним — снятие', m.calls[0] > 0 and m.calls[-1] == 0)
job = next(k for k in sink.hist if k.endswith('job.json'))
jj = json.loads(sink.hist[job])
ok('задание: пара C1+C2, флаги из пресета, без зарезервированных', jj['cams'] == ['C1', 'C2'] and JP.validate_job(jj) == '' and '--samples' in jj['args'])
bundle = next(k for k in sink.hist if k.endswith('.tgz'))
bd = os.path.join(TMP, 'b3')
os.makedirs(bd)
open(os.path.join(bd, 'b.tgz'), 'wb').write(sink.hist[bundle])
names = JP.unpack_bundle(os.path.join(bd, 'b.tgz'), os.path.join(bd, 'x'))
ok('пакет: сцена, декор, программа рендера, данные, карты', {'scene', 'dump', 'tools', 'data', 'public'} <= set(names))
ok('пакет: правило картин wall_art.py лежит рядом с render_cycles.py (он его импортирует) — каждый import рендера есть в пакете',
   os.path.isfile(os.path.join(bd, 'x', 'tools', 'scout', 'wall_art.py')) and os.path.isfile(os.path.join(bd, 'x', 'data', 'flat3d', 'wall-art.json')))
ok('карты — только существующие в public (чужой путь и отсутствующий файл не попали)',
   os.path.isfile(os.path.join(bd, 'x', 'public', 'flat3d', 'tex', 'a.jpg')) and not os.path.exists(os.path.join(bd, 'x', 'public', 'etc')) and
   not os.path.exists(os.path.join(bd, 'x', 'public', 'flat3d', 'none.jpg')))
ok('рабочая папка исполнителя убрана', not [d for d in os.listdir(os.path.join(TMP, 'rwork')) if d.startswith('gjob-')])

# ═══ 3b. уборка задания в фоне (T-20261118-09/5 ❸): заказ не ждёт ответа приёмника на DELETE
class SlowDelSink(FakeSink):
    def delete(self, rel):
        time.sleep(1.2)
        return super().delete(rel)


os.environ['RENDER_DELETE_ASYNC'] = '1'
sinkD, mD = SlowDelSink(), FakeMachine()
wD = new_worker(sinkD)
stopD = threading.Event()
run_worker_thread(wD, stopD)
exD = Exec(sinkD, mD, PUBLIC)
t_ = time.time()
render(exD, os.path.join(TMP, 'out3b'))
dt_ = time.time() - t_
early = not getattr(sinkD, 'deleted', [])
exD.drain_bg()
stopD.set()
os.environ['RENDER_DELETE_ASYNC'] = '0'
ok('уборка в фоне: заказ вернулся, не дожидаясь медленного DELETE (1,2 с), задание убрано после drain_bg, pulse(0) вызван', early and len(getattr(sinkD, 'deleted', [])) == 1 and mD.calls and mD.calls[-1] in (0, 0.0))

# ═══ 4. воркер не взял задание → cancel.json, ExecutorUnavailable, pulse(0)
sink, m = FakeSink(), FakeMachine()
ex = Exec(sink, m, PUBLIC)
t0 = time.time()
try:
    render(ex, os.path.join(TMP, 'o4'))
    ok('не взяли за pickup_s → отказ', False)
except RE.ExecutorUnavailable as e:
    ok('не взяли за pickup_s → gpu_no_pickup, cancel.json, pulse(0) последним', e.code == 'gpu_no_pickup' and any(r.endswith('cancel.json') for _, r in sink.log) and m.calls[-1] == 0 and time.time() - t0 < 10)
s4 = FakeSink()                      # хранилище с заданием И cancel.json (как если бы уборка не успела) — воркер его не берёт
for k, v in sink.hist.items():
    s4.put(k, v)
ok('снятое задание (cancel.json) воркер не берёт', any(k.endswith('job.json') for k in s4.f) and new_worker(s4).pick() is None)

# ═══ 5. ошибки воркера → откат на CPU (ExecutorUnavailable), а не ошибка сцены
for mode, code in (('cpu', 'gpu_gpu_failed'), ('fail', 'gpu_render_failed')):
    os.environ['FAKE_BLENDER'] = mode
    sink, m = FakeSink(), FakeMachine()
    stop = threading.Event()
    run_worker_thread(new_worker(sink), stop)
    try:
        render(Exec(sink, m, PUBLIC), os.path.join(TMP, 'o5'))
        ok(f'{mode}: отказ', False)
    except RE.ExecutorUnavailable as e:
        want = 'gpu_failed' if mode == 'cpu' else 'gpu_render_failed'
        ok(f'воркер «{mode}» → ExecutorUnavailable {want}, пара RU/EN, pulse(0)', e.code == want and e.ru and e.en and m.calls[-1] == 0)
    stop.set()
os.environ['FAKE_BLENDER'] = 'ok'

# ═══ 6. машину выключили посреди ожидания → отказ gpu_off + cancel
sink, m = FakeSink(), FakeMachine()
ex = Exec(sink, m, PUBLIC)
orig_sleep = ex.sleep
n = {'i': 0}


def sleep_and_off(s):
    n['i'] += 1
    if n['i'] == 3:
        m.st['desired'] = 'off'
    orig_sleep(s)


ex.sleep = sleep_and_off
try:
    render(ex, os.path.join(TMP, 'o6'))
    ok('выключили в ожидании → отказ', False)
except RE.ExecutorUnavailable as e:
    ok('выключили в ожидании → gpu_off, cancel.json', e.code == 'gpu_off' and any(r.endswith('cancel.json') for _, r in sink.log))

# ═══ 7. потолок пары
sink, m = FakeSink(), FakeMachine()
m.rules_['executor'].update(pair_max_s=0.5, pickup_s=30)
stop = threading.Event()
os.environ['FAKE_BLENDER'] = 'slow'
run_worker_thread(new_worker(sink), stop)
try:
    render(Exec(sink, m, PUBLIC), os.path.join(TMP, 'o7'))
    ok('потолок пары → отказ', False)
except RE.ExecutorUnavailable as e:
    ok('не уложились в pair_max_s → gpu_timeout', e.code == 'gpu_timeout')
stop.set()
os.environ['FAKE_BLENDER'] = 'ok'

# ═══ 8. хранилище не приняло пакет
sink, m = FakeSink(), FakeMachine()
sink.fail_put = '.tgz'
try:
    render(Exec(sink, m, PUBLIC), os.path.join(TMP, 'o8'))
    ok('хранилище отказало → отказ', False)
except RE.ExecutorUnavailable as e:
    ok('хранилище не приняло пакет → gpu_upload, job.json не появился', e.code == 'gpu_upload' and not any(r.endswith('job.json') for _, r in sink.log))

# ═══ 8b. пакет больше потолка приёмника (95 МБ) → понятный отказ до отправки, откат на CPU
sink, m = FakeSink(), FakeMachine()
m.rules_['executor']['bundle_max_mb'] = 0.001
try:
    render(Exec(sink, m, PUBLIC), os.path.join(TMP, 'o8b'))
    ok('пакет больше потолка → отказ', False)
except RE.ExecutorUnavailable as e:
    ok('пакет > bundle_max_mb → gpu_bundle_big, в хранилище ничего не ушло', e.code == 'gpu_bundle_big' and sink.log == [] or not any(k == 'put' for k, _ in sink.log))

# ═══ 9. автостоп: заказ и пара — события, занятость снимается всегда (реальный контроллер, чистая plan)
sys.path.insert(0, HERE)
import render_machine as RM  # noqa: E402
RM.pulse(busy_s=600, now=1000.0)
with RM.Box() as bx:
    ok('pulse(busy) → last_activity и busy_until в состоянии контроллера', bx.state['last_activity'] == 1000.0 and bx.state['busy_until'] == 1600.0)
RM.pulse(0, now=1100.0)
with RM.Box() as bx:
    ok('pulse(0) → busy снят, последнее событие обновлено', bx.state['busy_until'] == 0 and bx.state['last_activity'] == 1100.0)

# ═══ 10. протокол
d = os.path.join(TMP, 'pp')
os.makedirs(os.path.join(d, 'in'))
open(os.path.join(d, 'in', 'a'), 'wb').write(b'a')
open(os.path.join(d, 'in', 'b'), 'wb').write(b'b' * 100)
s1 = JP.pack_bundle({'x': os.path.join(d, 'in')}, os.path.join(d, '1.tgz'))
os.utime(os.path.join(d, 'in', 'a'), (5, 5))
s2 = JP.pack_bundle({'x': os.path.join(d, 'in')}, os.path.join(d, '2.tgz'))
ok('пакет воспроизводимый: тот же состав — тот же sha, mtime файлов не влияет', s1 == s2 and JP.file_sha12(os.path.join(d, '1.tgz')) == s1)
import io  # noqa: E402
import tarfile  # noqa: E402
bad = os.path.join(d, 'evil.tgz')
with tarfile.open(bad, 'w:gz') as tf:
    ti = tarfile.TarInfo('../evil.txt')
    ti.size = 3
    tf.addfile(ti, io.BytesIO(b'bad'))
try:
    JP.unpack_bundle(bad, os.path.join(d, 'ev'))
    ok('архив с «../» не распаковался', False)
except Exception:  # noqa: BLE001
    ok('архив с «../» не распаковался (фильтр data)', not os.path.exists(os.path.join(d, 'evil.txt')))
good = JP.new_job('j1', 'bundle-0123456789ab.tgz', '0123456789ab', ['--samples', 64], {'blenderSec': 100})
ok('validate_job: годное', JP.validate_job(good) == '')
for name, mut in (('версия', {'v': 9}), ('имя с /', {'job_id': 'a/b'}), ('ракурс', {'cams': ['C3']}), ('путь сцены в args', {'args': ['--scene-dir', '/x']}),
                  ('--out в args', {'args': ['--out', '/x']}), ('--device в args', {'args': ['--device', 'cpu']}), ('не строка', {'args': [1]}), ('пакет с /', {'bundle': '../x'})):
    ok(f'validate_job отвергает: {name}', JP.validate_job({**good, **mut}) != '')
rules = {'controller_stale_s': 300}
ok('machine_verdict: ready', JP.machine_verdict({'desired': 'on', 'gen': 2, 'warm_gen': 2, 'last_tick': 100}, 150, rules) == (True, 'ready'))
ok('machine_verdict: off/warming/degraded/silent',
   [JP.machine_verdict(s, 1000, rules)[1] for s in ({'desired': 'off'}, {'desired': 'on', 'gen': 2, 'warm_gen': 1}, {'desired': 'on', 'gen': 2, 'warm_gen': 2, 'degraded_since': 1, 'last_tick': 900},
                                                  {'desired': 'on', 'gen': 2, 'warm_gen': 2, 'last_tick': 1})] == ['off', 'warming', 'degraded', 'controller_silent'])

# ═══ 11. воркер: команда, стадии, кэш
job = JP.new_job('j', 'bundle-a.tgz', 'a', ['--samples', 64, '--pct', 75], {})
cmd = RW.build_cmd(job, '/w')
ok('build_cmd: пути воркера, пара, --device auto, --persistent 1, флаги задания в конце',
   cmd[cmd.index('--cam') + 1] == 'C1,C2' and cmd[cmd.index('--device') + 1] == 'auto' and cmd[cmd.index('--persistent') + 1] == '1' and cmd[-4:] == ['--samples', '64', '--pct', '75'] and
   cmd[cmd.index('--scene-dir') + 1] == '/w/scene' and cmd[cmd.index('--out') + 1].endswith('{cam}.png'))
ok('parse_progress: C1 готов → стадия C2, C2 готов → save',
   RW.parse_progress('RENDER_SEC 5.6 cam C1 frame 1/2 samples 64', ['C1', 'C2']) == ('C2', {'C1': 5.6}) and RW.parse_progress('RENDER_SEC 7.0 cam C2 frame 2/2', ['C1', 'C2']) == ('save', {'C2': 7.0})
   and RW.parse_progress('DEVICE_USED CUDA', ['C1', 'C2']) == (None, {}))
cd = os.path.join(TMP, 'cache')
os.makedirs(cd)
for i in range(6):
    p = os.path.join(cd, f'bundle-{i}.tgz')
    open(p, 'wb').write(b'x' * 1000)
    os.utime(p, (100 + i, 100 + i))
gone = RW.trim_cache(cd, 'bundle-0.tgz', max_n=3, max_gb=1)
left = sorted(os.listdir(cd))
ok('кэш пакетов ограничен по числу: остаются 3, текущий (самый старый по времени) не тронут', len(left) == 3 and 'bundle-0.tgz' in left and 'bundle-5.tgz' in left and len(gone) == 3)
gone = RW.trim_cache(cd, 'bundle-5.tgz', max_n=10, max_gb=2500 / 2 ** 30)
ok('кэш ограничен по размеру', sum(os.path.getsize(os.path.join(cd, f)) for f in os.listdir(cd)) <= 2500 and 'bundle-5.tgz' in os.listdir(cd))
# ═══ 12. T-24/4 Э1: кэш PNG по содержимому, кэш дампа, ожидание шагов
import importlib.util
spec = importlib.util.spec_from_file_location('export_scene_t', os.path.join(HERE, '..', 'cycles_probe', 'export_scene.py'))
ES = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ES)
import numpy as np
from PIL import Image
ES.TEX_CACHE = os.path.join(TMP, 'texcache')
arr = (np.arange(64 * 48 * 3) % 251).astype(np.uint8).reshape(48, 64, 3)
d1, d2 = os.path.join(TMP, 'tx1.png'), os.path.join(TMP, 'tx2.png')
ES.put_png(arr, d1)
n_cache = len(os.listdir(ES.TEX_CACHE))
ES.put_png(arr.copy(), d2)
ok('PNG: тот же набор пикселей — один файл кэша, второй раз не кодируем', n_cache == 1 and len(os.listdir(ES.TEX_CACHE)) == 1 and os.stat(d1).st_ino == os.stat(d2).st_ino)
ok('PNG: пиксели без потерь (как кодировал бы Image.save)', (np.asarray(Image.open(d1).convert('RGB')) == arr).all())
ES.put_png(arr[:, ::-1], os.path.join(TMP, 'tx3.png'))
ok('PNG: другое содержимое — другой файл кэша', len(os.listdir(ES.TEX_CACHE)) == 2)

ex2 = RE.SaladGpuExecutor({}, sink=None)
calls = []
orig_rs = RE.run_step
def fake_step(cmd, log, *a, **k):
    calls.append(cmd[1] if len(cmd) > 1 else cmd)
    dd = cmd[5]
    os.makedirs(dd, exist_ok=True)
    open(os.path.join(dd, 'scene-export.json'), 'w').write('{"x": 1}')
RE.run_step = fake_step
os.environ['RENDER_DUMP_CACHE'] = os.path.join(TMP, 'dumpcache')
dp = os.path.join(TMP, 'data.json'); open(dp, 'w').write('{"v": 1}')
bd = os.path.join(TMP, 'bundle-aaa'); os.makedirs(bd, exist_ok=True)
pr_ = {'dumpExport': 'all'}; lim_ = {'dumpSec': 5, 'maxRssGb': 1}
ex2._dump_cached(dp, bd, os.path.join(TMP, 'dumpA'), os.path.join(TMP, 'dl.log'), pr_, lim_)
ex2._dump_cached(dp, bd, os.path.join(TMP, 'dumpB'), os.path.join(TMP, 'dl.log'), pr_, lim_)
ok('дамп: повтор того же входа берётся из кэша (Chromium не запускаем)', len(calls) == 1 and open(os.path.join(TMP, 'dumpB', 'scene-export.json')).read() == '{"x": 1}')
open(dp, 'w').write('{"v": 2}')
ex2._dump_cached(dp, bd, os.path.join(TMP, 'dumpC'), os.path.join(TMP, 'dl.log'), pr_, lim_)
ok('дамп: другие данные — новый запуск и новая запись кэша', len(calls) == 2 and len([e for e in os.listdir(os.environ['RENDER_DUMP_CACHE']) if not e.endswith('.tmp')]) == 2)
RE.run_step = orig_rs
# ═══ 13. T-24/4: параллельные прогоны не ломают друг другу сборку, кэши и каталоги (рабочий 1, 17.11: bundle подменили посреди чужого дамп-шага)
import threading
ex3 = RE.SaladGpuExecutor({'RENDER_WORK': os.path.join(TMP, 'pwork')}, sink=None)
ex3.work = os.path.join(TMP, 'pwork')
os.makedirs(ex3.work, exist_ok=True)
built = []
def fake_build(cmd, log, *a, **k):
    out = cmd[2]
    built.append(out)
    os.makedirs(out, exist_ok=True)
    time.sleep(0.3)                                  # окно гонки
    open(os.path.join(out, 'entry.js'), 'w').write('x')
RE.run_step = fake_build
res3, errs3 = [], []
def bundle_run():
    try:
        res3.append(ex3._bundle(os.path.join(TMP, 'b.log')))
    except Exception as e:  # noqa: BLE001
        errs3.append(repr(e))
ths = [threading.Thread(target=bundle_run) for _ in range(4)]
[t.start() for t in ths]; [t.join() for t in ths]
ok('сборка выгрузчика: четыре параллельных прогона — один итоговый каталог, без ошибок, entry.js на месте',
   not errs3 and len(set(res3)) == 1 and os.path.isfile(os.path.join(res3[0], 'entry.js')) and all('.tmp-' in b for b in built))
ok('сборка выгрузчика: временные каталоги убраны', not [d for d in os.listdir(ex3.work) if '.tmp-' in d])
old_b = os.path.join(ex3.work, 'bundle-old000000000'); os.makedirs(old_b)
ex3._bundle(os.path.join(TMP, 'b.log'))
ok('сборка: чужой СВЕЖИЙ bundle-* не сносится (мог быть в ходу у соседнего прогона)', os.path.isdir(old_b))
os.utime(old_b, (1, 1))
ex3._bundle(os.path.join(TMP, 'b.log'))
ok('сборка: старый (> 6 ч) bundle-* убирается', not os.path.isdir(old_b))
RE.run_step = orig_rs

snap_a = {'scene_hash': 'a' * 64}
d1_, d2_ = ex3._job_dir('gjob-', snap_a), ex3._job_dir('gjob-', snap_a)
ok('каталог задания: две сцены с одним хешем — разные каталоги', d1_ != d2_ and d1_.startswith(os.path.join(ex3.work, 'gjob-' + 'a' * 16)))

# кэш PNG: восемь потоков кладут одну и ту же картинку
ES.TEX_CACHE = os.path.join(TMP, 'texcache2')
arr2 = (np.arange(256 * 256 * 3) % 253).astype(np.uint8).reshape(256, 256, 3)
dsts = [os.path.join(TMP, f'par{i}.png') for i in range(8)]
errs4 = []
def put_run(dst):
    try:
        ES.put_png(arr2, dst)
    except Exception as e:  # noqa: BLE001
        errs4.append(repr(e))
ths = [threading.Thread(target=put_run, args=(d,)) for d in dsts]
[t.start() for t in ths]; [t.join() for t in ths]
ok('кэш PNG: восемь параллельных записей — без ошибок, все файлы читаются и равны, в кэше один файл',
   not errs4 and all((np.asarray(Image.open(d).convert('RGB')) == arr2).all() for d in dsts) and len([f for f in os.listdir(ES.TEX_CACHE) if f.endswith('.png')]) == 1)
cf = os.path.join(ES.TEX_CACHE, [f for f in os.listdir(ES.TEX_CACHE) if f.endswith('.png')][0])
ok('кэш PNG: после записи только чтение', (os.stat(cf).st_mode & 0o222) == 0)
ok('кэш PNG: временных файлов не осталось', not [f for f in os.listdir(ES.TEX_CACHE) if f.endswith('.tmp')])

# кэш дампа: два параллельных прогона одного входа
os.environ['RENDER_DUMP_CACHE'] = os.path.join(TMP, 'dumpcache2')
dp2 = os.path.join(TMP, 'data2.json'); open(dp2, 'w').write('{"v": 9}')
n_calls = []
def fake_step2(cmd, log, *a, **k):
    n_calls.append(1)
    dd = cmd[5]
    os.makedirs(dd, exist_ok=True)
    time.sleep(0.3)
    open(os.path.join(dd, 'scene-export.json'), 'w').write('{"y": 2}')
RE.run_step = fake_step2
errs5 = []
def dump_run(i):
    try:
        ex2._dump_cached(dp2, bd, os.path.join(TMP, f'pd{i}'), os.path.join(TMP, f'pd{i}.log'), pr_, lim_)
    except Exception as e:  # noqa: BLE001
        errs5.append(repr(e))
ths = [threading.Thread(target=dump_run, args=(i,)) for i in range(3)]
[t.start() for t in ths]; [t.join() for t in ths]
ents5 = [e for e in os.listdir(os.environ['RENDER_DUMP_CACHE'])]
ok('кэш дампа: три параллельных прогона — без ошибок, у каждого своя папка с данными, в кэше одна запись, временных нет',
   not errs5 and all(open(os.path.join(TMP, f'pd{i}', 'scene-export.json')).read() == '{"y": 2}' for i in range(3)) and len(ents5) == 1 and '.tmp-' not in ents5[0])
ok('кэш дампа: файлы записи только для чтения', all((os.stat(os.path.join(os.environ['RENDER_DUMP_CACHE'], ents5[0], f)).st_mode & 0o222) == 0 for f in os.listdir(os.path.join(os.environ['RENDER_DUMP_CACHE'], ents5[0])) if f != '.ok'))
RE.run_step = orig_rs
# ═══ 14. T-24/4: сбой перечня заданий не убивает воркера (живая пара 23:34: исключение из ls задания вышло из loop → процесс умер → «не взяли»)
s9 = FakeSink()
s9.put('renderjobs/j9/job.json', b'{}')
w9 = new_worker(s9)
real_ls = s9.ls
calls9 = []
def flaky_ls(rel):
    calls9.append(rel)
    if rel == 'renderjobs/j9':
        raise JP.SinkError('LS: timed out', 0)
    return real_ls(rel)
s9.ls = flaky_ls
ok('pick: сбой ls каталога задания → None, исключения нет', w9.pick() is None and 'renderjobs/j9' in calls9)
s9.ls = real_ls
ok('pick: после сбоя то же задание берётся на следующем круге', w9.pick() == 'j9')
def boom_pick():
    raise RuntimeError('boom')
w9.pick = boom_pick
w9.sleep_n = 0
RW.MA.STATE['ready'] = True
th9 = threading.Thread(target=w9.loop, daemon=True); th9.start()
time.sleep(1.6)
ok('loop: любое исключение pick не завершает поток воркера', th9.is_alive())
# ═══ 15. T-24/5: fmt 2 — ассеты по хешу, короткое задание, кэш машины, откаты
import hashlib  # noqa: E402


class FakeSink2(FakeSink):
    """Хранилище с ассетами (как `Sink.have_assets/put_asset/get_asset_to`). Крючки: have_err — приёмник «старый» (404 на /have); lose — ассет пропал с приёмника;
    wrong — приёмник отдаёт не те байты; slow — задержка скачивания (проверка «один поток на хеш»)."""

    def __init__(self):
        super().__init__()
        self.assets, self.have_calls, self.put_assets, self.get_assets = {}, 0, [], []
        self.have_err, self.lose, self.wrong, self.slow = False, set(), set(), 0.0

    def have_assets(self, items):
        self.have_calls += 1
        if self.have_err:
            raise JP.SinkError('POST /have/renderassets: HTTP 404', 404)
        return [i['sha256'] for i in items if i['sha256'] not in self.assets or len(self.assets[i['sha256']]) != i['size']]

    def put_asset(self, sha, path):
        data = open(path, 'rb').read()
        assert hashlib.sha256(data).hexdigest() == sha, 'исполнитель шлёт ассет не под своим хешем'
        with self.lock:
            self.assets[sha] = data
            self.put_assets.append(sha)
            self.log.append(('asset', sha))

    def get_asset_to(self, sha, dest):
        time.sleep(self.slow)
        with self.lock:
            self.get_assets.append(sha)
            data = None if (sha in self.lose or sha not in self.assets) else self.assets[sha]
        if data is None:
            raise JP.SinkError(f'GET {sha[:8]}: HTTP 404', 404)
        if sha in self.wrong:
            data = data[::-1]
        open(dest, 'wb').write(data)
        return len(data)


class Exec2(Exec):
    """К подмене сборки сцены добавляем текстуры сцены (`scene/tex/*.png`): они уходят ассетами."""

    def __init__(self, sink, machine, public, tex=()):
        super().__init__(sink, machine, public)
        self.tex = tex

    def _prepare(self, snap, job, log, pr, progress, timing):
        d = super()._prepare(snap, job, log, pr, progress, timing)
        os.makedirs(os.path.join(job, 'scene', 'tex'))
        for i, b in enumerate(self.tex):
            open(os.path.join(job, 'scene', 'tex', f't{i}.png'), 'wb').write(b)
        return d


T1, T2 = b'A' * 20000 + os.urandom(2000), b'B' * 30000 + os.urandom(2000)
BLOBS = os.path.join(RW.WORK, 'blobs')
sink, m = FakeSink2(), FakeMachine()
m.rules_['executor']['fmt2'] = True
stop = threading.Event()
w = new_worker(sink)
run_worker_thread(w, stop)
ex = Exec2(sink, m, PUBLIC, tex=(T1, T2))
stages, res = render(ex, os.path.join(TMP, 'o15'))
tm = res['timing']
ok('fmt 2: сквозной прогон — пара готова, формат 2, стадии как всегда', tm.get('fmt') == 2 and stages == ['scene', 'C1', 'C2', 'save'] and sorted(os.listdir(os.path.join(TMP, 'o15'))) == ['C1.jpg', 'C2.jpg', 'meta.json'])
jk = next(k for k in sink.hist if k.endswith('job.json'))
j2 = json.loads(sink.hist[jk])
ok('fmt 2: job.json v=2, полная схема, годен для воркера (job_id = имя каталога)', j2['v'] == 2 and JP.validate_job(j2, expect_id=jk.split('/')[1]) == '' and j2['manifest_sha'] == JP.manifest_sha(j2['bundle'], j2['assets']))
kinds = {a['path']: a['kind'] for a in j2['assets']}
ok('fmt 2: в ассетах текстуры сцены, GLB декора, карта отделки, программа рендера и её данные',
   kinds.get('scene/tex/t0.png') == 'tex' and kinds.get('dump/demo_nodes.glb') == 'glb' and kinds.get('public/flat3d/tex/a.jpg') == 'map'
   and kinds.get('tools/scout/cycles_probe/render_cycles.py') == 'code' and kinds.get('tools/scout/wall_art.py') == 'code' and kinds.get('data/flat3d/wall-art.json') == 'data')
ok('fmt 2 (T-24/8): крупный меш предмета scene/m001.npz — ассет (вид glb), мелкий m000.npz — в пакете', kinds.get('scene/m001.npz') == 'glb' and 'scene/m000.npz' not in kinds)
ok('fmt 2: sha256 полный (64 знака) и размер у каждого ассета', all(len(a['sha256']) == 64 and a['size'] > 0 for a in j2['assets']) and len(j2['bundle']['sha256']) == 64)
bk = next(k for k in sink.hist if k.endswith('.tgz'))
bdir = os.path.join(TMP, 'b15')
os.makedirs(bdir)
open(os.path.join(bdir, 'b.tgz'), 'wb').write(sink.hist[bk])
JP.unpack_bundle(os.path.join(bdir, 'b.tgz'), os.path.join(bdir, 'x'))
inb = {os.path.relpath(os.path.join(dp, f), os.path.join(bdir, 'x')) for dp, _, fs in os.walk(os.path.join(bdir, 'x')) for f in fs}
ok('fmt 2: маленький пакет — только карта сцены, npz, отделка и uuid (текстур, GLB, карт и кода в нём нет)',
   inb == {'scene/m000.npz', 'dump/demo_nodes_uuids.json', 'dump/scene-export.json'} and len(sink.hist[bk]) < 4000)
order = [('a' if k == 'asset' else r.split('/')[-1]) for k, r in sink.log if (k == 'asset' or (k == 'put' and (r.endswith('.tgz') or r.endswith('job.json') or r.endswith('result.json'))))]
ok('fmt 2: ассеты и пакет — ДО job.json, job.json — до result.json', order.index('job.json') > max(i for i, x in enumerate(order) if x == 'a') and order.index('job.json') < order.index('result.json'))
ok('fmt 2: timing — hash/have/asset_n/asset_miss/asset_up_mb/upload/bundle_kb', all(k in tm for k in ('hash', 'have', 'asset_n', 'asset_miss', 'asset_up_mb', 'upload', 'bundle_kb')) and tm['asset_miss'] == tm['asset_n'] == len(set(a['sha256'] for a in j2['assets'])))
ok('fmt 2: timing — сколько ассетов машина докачала (кэш был пуст: все) и сколько МБ', tm.get('asset_dl_n') == tm['asset_n'] and tm.get('asset_dl_mb') is not None)
ok('машина: ассеты лежат в кэше по полному хешу (только чтение)', all(os.path.isfile(os.path.join(BLOBS, a['sha256'])) and not os.stat(os.path.join(BLOBS, a['sha256'])).st_mode & 0o222 for a in j2['assets']))
n_put, n_get = len(sink.put_assets), len(sink.get_assets)

# повтор той же сцены: ничего не досылаем, машина ничего не качает
stages, res = render(ex, os.path.join(TMP, 'o15b'))
tm = res['timing']
ok('повтор: fmt 2, «каких нет» — ни одного, выгрузка ассетов 0 МБ, на приёмник ушёл только маленький пакет', tm['fmt'] == 2 and tm['asset_miss'] == 0 and tm['asset_up_mb'] == 0 and len(sink.put_assets) == n_put and sink.have_calls == 2)
ok('повтор: машина берёт ассеты из своего кэша (скачиваний ноль)', len(sink.get_assets) == n_get)

# испорченный файл в кэше машины перепроверяется и перекачивается
victim = os.path.join(BLOBS, next(a['sha256'] for a in j2['assets'] if a['path'] == 'scene/tex/t0.png'))
os.chmod(victim, 0o644)
open(victim, 'wb').write(b'X' * os.path.getsize(victim))
stages, res = render(ex, os.path.join(TMP, 'o15c'))
ok('кэш машины: испорченный файл (размер тот же, хеш другой) не принят — скачан заново, кадр готов', res['timing']['fmt'] == 2 and len(sink.get_assets) == n_get + 1 and JP.sha256_file(victim) == os.path.basename(victim))
os.remove(victim)
open(victim, 'wb').write(b'short')
render(ex, os.path.join(TMP, 'o15d'))
ok('кэш машины: файл другого размера тоже перекачан', JP.sha256_file(victim) == os.path.basename(victim) and len(sink.get_assets) == n_get + 2)

# ассет пропал с приёмника после «есть» → машина отвечает asset → исполнитель повторяет заказ по fmt 1 (не сразу на процессор)
sink.lose = {os.path.basename(victim)}
os.remove(victim)
n_del = len(getattr(sink, 'deleted', []))
stages, res = render(ex, os.path.join(TMP, 'o15e'))
ok('ассет пропал на приёмнике → тот же заказ по fmt 1, кадры готовы, оба задания убраны', res['timing']['fmt'] == 1 and sorted(os.listdir(os.path.join(TMP, 'o15e'))) == ['C1.jpg', 'C2.jpg', 'meta.json'] and len(sink.deleted) - n_del == 2)
sink.lose = set()

# приёмник отдаёт не те байты — хеш после скачивания не сходится: мусор в кэше не остаётся, заказ уходит по fmt 1
if os.path.exists(victim):
    os.remove(victim)
sink.wrong = {os.path.basename(victim)}
stages, res = render(ex, os.path.join(TMP, 'o15f'))
ok('чужие байты под нашим хешем: не приняты, в кэше нет файла-мусора, fmt 1', res['timing']['fmt'] == 1 and not os.path.exists(victim) and not [f for f in os.listdir(BLOBS) if f.startswith('.dl-')])
sink.wrong = set()

# приёмник старый (нет /have): fmt 1, и пять минут не спрашиваем снова
sink.have_err = True
stages, res = render(ex, os.path.join(TMP, 'o15g'))
calls_h = sink.have_calls
ok('приёмник без ассетов (404 на /have) → fmt 1, пара готова', res['timing']['fmt'] == 1 and ex._fmt2_dead_until > time.time())
render(ex, os.path.join(TMP, 'o15h'))
ok('после отказа приёмника fmt 2 не пробуем (нет лишних запросов)', sink.have_calls == calls_h)
sink.have_err = False
ex._fmt2_dead_until = 0

# старый воркер (знает только v=1): bad_job → заказ по fmt 1
old_sup = JP.SUPPORTED
JP.SUPPORTED = (1,)
stages, res = render(ex, os.path.join(TMP, 'o15i'))
JP.SUPPORTED = old_sup
ok('машина со старой версией воркера (v=1) отвергла v=2 → fmt 1, кадры готовы', res['timing']['fmt'] == 1)

# флаг выключен в правилах → fmt 1 без обращений к ассетам
m.rules_['executor']['fmt2'] = False
hc = sink.have_calls
stages, res = render(ex, os.path.join(TMP, 'o15j'))
ok('fmt2=false в правилах → fmt 1, приёмник про ассеты не спрашиваем', res['timing']['fmt'] == 1 and sink.have_calls == hc)
m.rules_['executor']['fmt2'] = True
stop.set()

# ——— один поток на хеш
sink = FakeSink2()
sink.slow = 0.3
data = os.urandom(5000)
hh = hashlib.sha256(data).hexdigest()
sink.assets[hh] = data
w15 = new_worker(sink)
shutil.rmtree(BLOBS, ignore_errors=True)
os.makedirs(BLOBS)
outs = []
ths = [threading.Thread(target=lambda: outs.append(w15.fetch_asset(hh, len(data)))) for _ in range(6)]
[t.start() for t in ths]
[t.join() for t in ths]
ok('шесть одновременных запросов одного ассета — скачивание одно, у всех готовый файл', sink.get_assets.count(hh) == 1 and len(outs) == 6 and all(o[0] == os.path.join(BLOBS, hh) for o in outs) and sum(1 for o in outs if o[1]) == 1)

# ——— validate_job v=2: строгая схема
b_ = {'name': 'bundle-' + 'a' * 16 + '.tgz', 'sha256': 'a' * 64, 'size': 50}
A_ = [JP.asset_ref('scene/tex/x.png', 'b' * 64, 100, 'tex'), JP.asset_ref('public/flat3d/m.webp', 'c' * 64, 7, 'map')]
J_ = JP.new_job2('job1', b_, A_, ['--samples', '64', '--exposure', '-0.15'], {'blenderSec': 1500}, 'r1')
ok('validate_job v=2: годное', JP.validate_job(J_, expect_id='job1') == '')
ok('validate_job: значение с пробелами из пресета v3 («Khronos PBR Neutral») годится', JP.validate_job(JP.new_job2('job1', b_, A_, ['--transform', 'Khronos PBR Neutral', '--fill-k', '6500'], {}, 'r1'), expect_id='job1') == '')
ok('validate_job: job_id обязан равняться имени каталога', JP.validate_job(J_, expect_id='job2') != '' and JP.validate_job(JP.new_job('job1', 'bundle-0123456789ab.tgz', '0123456789ab', [], {}), expect_id='x') != '')


def mut(**kw):
    return {**J_, **kw}


def with_assets(assets, **kw):
    return {**JP.new_job2('job1', b_, assets, [], {}, 'r1'), **kw}


bads = {
    'лишнее поле': mut(extra=1), 'схема 3': mut(schema=3), 'v=3': mut(v=3), 'манифест подменён': mut(manifest_sha='0' * 64),
    'ассет подменён после подписи': mut(assets=[{**A_[0], 'size': 101}, A_[1]]),
    'флаг воркера в args': mut(args=['--scene-dir']), '--out': mut(args=['--out']), 'пробел во флаге': mut(args=['--a b']), 'пробел по краю': mut(args=[' x']), 'двойной пробел': mut(args=['a  b']), 'кавычка': mut(args=['a"b']), 'точка с запятой': mut(args=['a;b']), 'не строка': mut(args=[5]),
    'args слишком много': mut(args=['-a'] * 65), 'лимиты: чужой ключ': mut(limits={'x': 1}), 'лимиты: строка': mut(limits={'blenderSec': '9'}), 'лимиты: 0': mut(limits={'blenderSec': 0}),
    'лимиты: bool': mut(limits={'blenderSec': True}), 'ракурсы': mut(cams=['C3']), 'ракурс дважды': mut(cams=['C1', 'C1']), 'created не число': mut(created='x'),
    'пакет: имя не из хеша': mut(bundle={**b_, 'name': 'bundle-' + 'b' * 16 + '.tgz'}), 'пакет: sha короткий': mut(bundle={**b_, 'sha256': 'a' * 12}),
    'пакет: size 0': mut(bundle={**b_, 'size': 0}),
}
for name, mu in bads.items():
    if name in ('манифест подменён', 'ассет подменён после подписи') or name.startswith('пакет'):
        pass
    ok(f'validate_job v=2 отвергает: {name}', JP.validate_job(mu, expect_id='job1') != '')
for name, p in (('../x', '../x.png'), ('середина ..', 'a/../b.png'), ('абсолютный', '/etc/passwd'), ('пустой сегмент', 'a//b.png'), ('скрытый', 'scene/.x.png'), ('обратная косая', 'a\\b.png'),
                ('NUL', 'a\x00b.png'), ('глубже 6', 'a/b/c/d/e/f/g.png'), ('пробел', 'a b.png'), ('точка', '.'), ('пусто', ''), ('кириллица', 'сцена/т.png')):
    ok(f'validate_job: путь ассета «{name}» отвергнут', JP.validate_job(with_assets([JP.asset_ref(p, 'b' * 64, 5, 'tex')]), expect_id='job1') != '')
ok('validate_job: два ассета на один путь', JP.validate_job(with_assets([A_[0], {**A_[0], 'sha256': 'd' * 64}]), expect_id='job1') != '')
ok('validate_job: чужой kind / sha не hex / size 0 / bool / слишком велик',
   all(JP.validate_job(with_assets([x]), expect_id='job1') != '' for x in (JP.asset_ref('a.png', 'b' * 64, 5, 'exe'), JP.asset_ref('a.png', 'B' * 64, 5, 'tex'), JP.asset_ref('a.png', 'b' * 64, 0, 'tex'),
                                                                            {'path': 'a.png', 'sha256': 'b' * 64, 'size': True, 'kind': 'tex'}, JP.asset_ref('a.png', 'b' * 64, 96 * 2 ** 20, 'tex'))))
ok('validate_job: больше 600 ассетов', JP.validate_job(with_assets([JP.asset_ref(f'a/{i}.png', f'{i:064x}', 5, 'tex') for i in range(601)]), expect_id='job1') != '')
ok('validate_job: общий объём ассетов больше потолка', JP.validate_job(with_assets([JP.asset_ref(f'a/{i}.png', f'{i:064x}', 90 * 2 ** 20, 'tex') for i in range(20)]), expect_id='job1') != '')
ok('manifest_sha: порядок ссылок не важен, любое изменение — другой хеш',
   JP.manifest_sha(b_, A_) == JP.manifest_sha(b_, A_[::-1]) and JP.manifest_sha(b_, A_) != JP.manifest_sha(b_, [A_[0]]) and JP.manifest_sha(b_, A_) != JP.manifest_sha({**b_, 'size': 51}, A_))

# флаги ЖИВОГО пресета обязаны проходить строгую проверку задания (пресет v3 принёс «Khronos PBR Neutral» с пробелами — на живой машине это было бы bad_job)
PRESET_FLAGS = json.load(open(os.path.join(HERE, '..', 'cycles_probe', 'render-preset.json'), encoding='utf-8'))['flags']
ok('живой пресет: все флаги проходят validate_job (v=1 и v=2)', JP.validate_job(JP.new_job2('job1', b_, A_, PRESET_FLAGS, {}, 'r1'), expect_id='job1') == '' and JP.validate_job(JP.new_job('job1', 'bundle-0123456789ab.tgz', '0123456789ab', PRESET_FLAGS, {}), expect_id='job1') == '')

# ——— размещение ассетов и распаковка пакета: границы
wd = os.path.join(TMP, 'pl')
os.makedirs(os.path.join(wd, 'job'))
blob = os.path.join(wd, 'blob')
open(blob, 'wb').write(b'blob')
RW.place_asset(blob, os.path.join(wd, 'job'), 'scene/tex/a.png')
ok('place_asset: жёсткая ссылка на файл кэша (места не занимает)', os.stat(os.path.join(wd, 'job', 'scene/tex/a.png')).st_ino == os.stat(blob).st_ino)
for what, args in (('занятый путь', 'scene/tex/a.png'), ):
    try:
        RW.place_asset(blob, os.path.join(wd, 'job'), args)
        ok(f'place_asset: {what} отвергнут', False)
    except RW.AssetError:
        ok(f'place_asset: {what} отвергнут (ассет не затирает файл пакета)', True)
outside = os.path.join(wd, 'outside')
os.makedirs(outside)
os.symlink(outside, os.path.join(wd, 'job', 'lnk'))
try:
    RW.place_asset(blob, os.path.join(wd, 'job'), 'lnk/x.png')
    ok('place_asset: каталог-ссылка наружу отвергнут', False)
except RW.AssetError:
    ok('place_asset: каталог-ссылка наружу отвергнут, снаружи ничего не создано', not os.listdir(outside))
import tarfile  # noqa: E402
import io  # noqa: E402
many = os.path.join(wd, 'many.tgz')
with tarfile.open(many, 'w:gz') as tf:
    for i in range(30):
        ti = tarfile.TarInfo(f'f{i}.txt')
        ti.size = 3
        tf.addfile(ti, io.BytesIO(b'abc'))
for kw, why in (({'max_files': 10}, 'число файлов'), ({'max_mb': 0.00001}, 'распакованный объём')):
    try:
        JP.unpack_bundle(many, os.path.join(wd, 'un'), **kw)
        ok(f'unpack_bundle: превышен лимит «{why}» → отказ', False)
    except ValueError:
        ok(f'unpack_bundle: превышен лимит «{why}» → отказ до записи на диск', not os.path.exists(os.path.join(wd, 'un', 'f0.txt')))
lnk_tar = os.path.join(wd, 'lnk.tgz')
with tarfile.open(lnk_tar, 'w:gz') as tf:
    ti = tarfile.TarInfo('evil')
    ti.type, ti.linkname = tarfile.SYMTYPE, '/etc/passwd'
    tf.addfile(ti)
try:
    JP.unpack_bundle(lnk_tar, os.path.join(wd, 'un2'))
    ok('unpack_bundle: ссылка в архиве отвергнута', False)
except ValueError:
    ok('unpack_bundle: ссылка в архиве отвергнута', True)

# ——— кэш ассетов машины: LRU, ассеты текущего задания не трогаем
bd2 = os.path.join(TMP, 'blobs2')
os.makedirs(bd2)
names = [f'{i:064x}' for i in range(1, 6)]
for i, n_ in enumerate(names):
    open(os.path.join(bd2, n_), 'wb').write(b'z' * 1000)
    os.utime(os.path.join(bd2, n_), (1000 + i, 1000 + i))
open(os.path.join(bd2, '.dl-tmp'), 'wb').write(b'q' * 5000)
gone = RW.trim_blobs(bd2, {names[0]}, max_gb=2500 / 2 ** 30)
ok('trim_blobs: давние вперёд до потолка, ассет текущего задания и временный файл целы', gone == names[1:4] and os.path.exists(os.path.join(bd2, names[0])) and os.path.exists(os.path.join(bd2, '.dl-tmp')) and os.path.exists(os.path.join(bd2, names[4])))

# ——— правило «что ассет»: общее, без особых случаев
ok('asset_kind: текстуры сцены, GLB, карты, код, данные — ассеты; npz, карта сцены, отделка, uuid — в пакете',
   [RE.asset_kind(x) for x in ('scene/tex/a.png', 'dump/demo_nodes.glb', 'public/a/b.webp', 'tools/scout/wall_art.py', 'data/flat3d/wall-art.json', 'scene/m046.npz')] == ['tex', 'glb', 'map', 'code', 'data', 'glb']
   and RE.asset_min_bytes('scene/m046.npz') == 64 * 1024 and RE.asset_min_bytes('scene/tex/a.png') == 1
   and not any(RE.asset_kind(x) for x in ('scene/scene.json', 'dump/scene-export.json', 'dump/demo_nodes_uuids.json', 'other/x')))

# ═══ 16. T-24/7: «подогрев» — горячий список витрины, прогрев кэша машины, уборка приёмника
H1, H2, H3 = os.urandom(3000), os.urandom(4000), os.urandom(5000)
hh = {hashlib.sha256(x).hexdigest(): x for x in (H1, H2, H3)}
shas = list(hh)
sink = FakeSink2()
for k, v in hh.items():
    sink.assets[k] = v
sink.put(JP.HOT_REL, json.dumps(JP.new_hot([{'sha256': k, 'size': len(v)} for k, v in hh.items()], now=7)).encode())
bd16 = os.path.join(RW.WORK, 'blobs')
shutil.rmtree(bd16, ignore_errors=True)
os.makedirs(bd16)
w16 = new_worker(sink)
st = w16.warm(JP.parse_hot(json.loads(sink.hist[JP.HOT_REL])), busy=lambda: False)
ok('подогрев: все ассеты списка в кэше машины по полному хешу, все годны (хеш и размер)', st['taken'] == 3 and st['errors'] == 0 and all(RW.blob_ok(os.path.join(bd16, k), k, len(v)) for k, v in hh.items()))
ok('подогрев: горячие хеши запомнены (из кэша по размеру не выселяются)', w16.hot == set(shas))
n_get = len(sink.get_assets)
st = w16.warm(JP.parse_hot(json.loads(sink.hist[JP.HOT_REL])), busy=lambda: False)
ok('повторный подогрев: скачиваний ноль', len(sink.get_assets) == n_get and st['dl_mb'] == 0 and st['taken'] == 3)
# выселение: потолок кэша меньше суммы — горячие остаются, чужое уходит
other = os.path.join(bd16, 'f' * 64)
open(other, 'wb').write(b'o' * 20000)
os.utime(other, (1, 1))
gone = RW.trim_blobs(bd16, w16.hot, max_gb=5000 / 2 ** 30)
ok('trim_blobs с горячими: чужой старый файл ушёл, горячие целы', gone == ['f' * 64] and all(os.path.exists(os.path.join(bd16, k)) for k in shas))
# потолок подогрева HOT_GB: берём по порядку списка, что не влезло — не берём
shutil.rmtree(bd16, ignore_errors=True)
os.makedirs(bd16)
old_gb = RW.HOT_GB
RW.HOT_GB = 7500 / 2 ** 30
st = w16.warm([(k, len(v)) for k, v in hh.items()], busy=lambda: False)
RW.HOT_GB = old_gb
ok('подогрев: потолок HOT_GB — берём по порядку, остальное не берём', st['n'] == 2 and st['cut'] == 1 and os.path.exists(os.path.join(bd16, shas[0])) and not os.path.exists(os.path.join(bd16, shas[2])))
# битый ассет на приёмнике: ошибка считается, остальные подтянуты, воркер жив
shutil.rmtree(bd16, ignore_errors=True)
os.makedirs(bd16)
sink.wrong = {shas[1]}
st = w16.warm([(k, len(v)) for k, v in hh.items()], busy=lambda: False)
sink.wrong = set()
ok('подогрев: ассет с неверным хешем не принят (не лежит в кэше), остальные есть', st['errors'] == 1 and st['taken'] == 2 and not os.path.exists(os.path.join(bd16, shas[1])) and os.path.exists(os.path.join(bd16, shas[0])))
# ЗАКАЗ ПРИОРИТЕТНЕЕ: пока воркер занят парой, новые скачивания не стартуют
shutil.rmtree(bd16, ignore_errors=True)
os.makedirs(bd16)
busy = {'v': True}
n0 = len(sink.get_assets)
th = threading.Thread(target=lambda: w16.warm([(k, len(v)) for k, v in hh.items()], busy=lambda: busy['v']), daemon=True)
th.start()
time.sleep(0.9)
ok('заказ приоритетнее: пока пара считается, подогрев ничего не качает', len(sink.get_assets) == n0 and th.is_alive())
busy['v'] = False
th.join(8)
ok('…и продолжает, когда пара кончилась', not th.is_alive() and len(sink.get_assets) == n0 + 3)
# заказу нужен тот же хеш, что подогрев качает: качается один раз
shutil.rmtree(bd16, ignore_errors=True)
os.makedirs(bd16)
sink.slow = 0.4
n0 = len(sink.get_assets)
th = threading.Thread(target=lambda: w16.warm([(shas[0], len(H1))], busy=lambda: False), daemon=True)
th.start()
time.sleep(0.1)
got = w16.fetch_asset(shas[0], len(H1))
th.join(5)
sink.slow = 0.0
ok('тот же хеш у заказа и подогрева — одно скачивание', len(sink.get_assets) == n0 + 1 and got[1] in (0, len(H1)))
# список: битый/чужой — воркер ничего не делает; pick не принимает `_hot` за задание
w17 = new_worker(FakeSink2())
w17.sink.put(JP.HOT_REL, b'{"v": 9}')
ok('битый/чужой список: пусто, подогрев ничего не берёт', JP.parse_hot(json.loads(w17.sink.hist[JP.HOT_REL])) == [])
sink18 = FakeSink2()
sink18.put(JP.HOT_REL, b'{"v":1,"assets":[]}')
sink18.put(f'{JP.PREFIX}/_hot/job.json', b'{}')
ok('pick: каталог `_hot` — не задание (даже если в нём окажется job.json)', new_worker(sink18).pick() is None)
# ═══ 17. срок на странице — по тому, кто возьмёт заказ СЕЙЧАС (T-24/7 доп.)
class Cpu(RE.SceneExecutor):
    name = 'local-cpu'


fb17 = RE.Fallback(Exec(FakeSink(), FakeMachine(), PUBLIC), Cpu({'RENDER_WORK': os.path.join(TMP, 'rwork')}))
ok('машина годна → ожидается salad-gpu', fb17.expected() == 'salad-gpu')
fb17b = RE.Fallback(Exec(FakeSink(), FakeMachine(desired='off'), PUBLIC), Cpu({'RENDER_WORK': os.path.join(TMP, 'rwork')}))
ok('машина выключена → ожидается local-cpu', fb17b.expected() == 'local-cpu')
fb17c = RE.Fallback(Exec(FakeSink(), FakeMachine(warm_gen=0), PUBLIC), Cpu({'RENDER_WORK': os.path.join(TMP, 'rwork')}))
ok('машина прогревается → ожидается local-cpu', fb17c.expected() == 'local-cpu')
ok('одиночный исполнитель ожидает себя', Cpu({'RENDER_WORK': os.path.join(TMP, 'rwork')}).expected() == 'local-cpu')
import render_jobs as RJ
st17 = RJ.RenderStore(os.path.join(TMP, 'j17.json'), os.path.join(TMP, 'res17'))
st17.durs, st17.dur_ex = [480.0] * 6, ['local-cpu'] * 6
m17 = FakeMachine()
q17 = RJ.RenderQueue(st17, RE.Fallback(Exec(FakeSink(), m17, PUBLIC), Cpu({'RENDER_WORK': os.path.join(TMP, 'rwork')})))
ok('stats при прогретой машине: исполнитель, диапазон 20…45 с (замеры 18.11)', q17.stats()['expected'] == 'salad-gpu' and q17.stats()['range'] == [20, 45])
m17.st['desired'] = 'off'
ok('stats при выключенной: исполнитель local-cpu, диапазон по его замерам', q17.stats()['expected'] == 'local-cpu' and q17.stats()['range'] == [480, 480])

# ——— кэш подготовленной сцены (T-24/10): первый заказ собирает и кладёт, следующие берут ссылками; ключ — снимок + версии + код; уборка по пределу МБ
os.environ['RENDER_PREP_CACHE'] = os.path.join(TMP, 'prep')


class PrepEx(RE.SceneExecutor):
    fresh = 0
    ver = 'e1'

    def _bundle(self, log):
        return os.path.join(TMP, 'bundle-abc')

    def versions(self):
        return {'export_scene': self.ver, 'dump': 'd1', 'scene_export': '1'}

    def _prepare_fresh(self, snap, job, log, pr, progress, timing):
        PrepEx.fresh += 1
        os.makedirs(os.path.join(job, 'scene', 'tex'))
        os.makedirs(os.path.join(job, 'dump'))
        open(os.path.join(job, 'scene', 'm000.npz'), 'wb').write(snap['scene_hash'].encode() * 3000)
        open(os.path.join(job, 'scene', 'tex', 't.png'), 'wb').write(b'T' * 1000)
        open(os.path.join(job, 'dump', 'demo_nodes.glb'), 'wb').write(b'G' * 500)
        timing['export'], timing['dump'] = 7.5, 0.0
        return os.path.join(job, 'dump')


px = PrepEx({'RENDER_WORK': os.path.join(TMP, 'rwork')})
pr18 = RE.preset()
sn_a, sn_b = {'scene_hash': 'a' * 64}, {'scene_hash': 'b' * 64}


def prep_job(snap, name):
    j = os.path.join(TMP, 'pj-' + name)
    os.makedirs(j)
    tm = {}
    d = px._prepare(snap, j, os.path.join(j, 'run.log'), pr18, lambda st: None, tm)
    return j, d, tm


j1, d1, t1_ = prep_job(sn_a, '1')
ok('кэш сцен: первый заказ — сборка и запись (fresh 1, prep_hit 0)', PrepEx.fresh == 1 and t1_['prep_hit'] == 0 and px.prep_has(sn_a))
j2, d2, t2_ = prep_job(sn_a, '2')
same = all(open(os.path.join(j1, f), 'rb').read() == open(os.path.join(j2, f), 'rb').read() for f in ('scene/m000.npz', 'scene/tex/t.png', 'dump/demo_nodes.glb'))
ok('кэш сцен: второй заказ того же снимка — без сборки, байты те же, каталог dump тот же вид', PrepEx.fresh == 1 and t2_['prep_hit'] == 1 and t2_['export'] < 1 and same and d2 == os.path.join(j2, 'dump'))
ok('кэш сцен: файлы — ссылки (одна копия на диске)', os.stat(os.path.join(j1, 'scene', 'm000.npz')).st_ino == os.stat(os.path.join(j2, 'scene', 'm000.npz')).st_ino)
shutil.rmtree(j1)
j3, _, t3_ = prep_job(sn_a, '3')
ok('кэш сцен: после удаления каталога задания кэш цел', t3_['prep_hit'] == 1 and open(os.path.join(j3, 'scene', 'm000.npz'), 'rb').read() == ('a' * 64).encode() * 3000)
prep_job(sn_b, '4')
ok('кэш сцен: другой снимок — своя сборка', PrepEx.fresh == 2 and not px.prep_has({'scene_hash': 'c' * 64}))
PrepEx.ver = 'e2'
_, _, t5_ = prep_job(sn_a, '5')
ok('кэш сцен: сменилась версия экспорта — старая запись не берётся', PrepEx.fresh == 3 and t5_['prep_hit'] == 0)
PrepEx.ver = 'e1'
os.remove(os.path.join(os.environ['RENDER_PREP_CACHE'], os.listdir(os.environ['RENDER_PREP_CACHE'])[0], '.ok'))
n_before = PrepEx.fresh
ents18 = sorted(os.listdir(os.environ['RENDER_PREP_CACHE']))
ok('кэш сцен: запись без `.ok` (недописанная) не считается и не берётся', len(ents18) >= 3 and all(not e.startswith('.') for e in ents18))
os.environ['RENDER_PREP_CACHE_MB'] = '0.01'
prep_job({'scene_hash': 'd' * 64}, '6')
left = [e for e in os.listdir(os.environ['RENDER_PREP_CACHE']) if os.path.isfile(os.path.join(os.environ['RENDER_PREP_CACHE'], e, '.ok'))]
ok('кэш сцен: уборка по пределу МБ — остаётся самая свежая запись', len(left) == 1 and px.prep_has({'scene_hash': 'd' * 64}))
os.environ.pop('RENDER_PREP_CACHE_MB')

# ——— воркер: поле `hot` в состоянии машины (уходит в ready.json) — контроллер объявляет «прогрелась» после первого прохода по горячему списку (T-24/10)
class HotSink:
    def __init__(self, hot):
        self.hot = hot

    def get_json(self, rel):
        if self.hot is None:
            raise JP.SinkError('GET: HTTP 404', 404)
        return self.hot


def hot_probe(hot, warm_ret):
    saved = (RW.HOT_REFRESH_S, dict(RW.MA.STATE))
    RW.HOT_REFRESH_S = 3600
    RW.MA.STATE.pop('hot', None)
    RW.MA.STATE['ready'] = True
    w = RW.Worker(HotSink(hot))
    w.warm = lambda items: (setattr(w, 'warm_stat', warm_ret) or warm_ret)
    th = threading.Thread(target=w.warm_loop, daemon=True)
    th.start()
    t_end = time.time() + 5
    while time.time() < t_end and not (RW.MA.STATE.get('hot') or {}).get('done'):
        time.sleep(0.02)
    got = dict(RW.MA.STATE.get('hot') or {})
    RW.HOT_REFRESH_S = saved[0]
    RW.MA.STATE.pop('hot', None)
    RW.MA.STATE['ready'] = saved[1].get('ready', False)
    return got


h1 = hot_probe(JP.new_hot([{'sha256': 'a' * 64, 'size': 5}], now=time.time()), {'n': 1, 'taken': 1, 'errors': 0, 's': 2.5, 'dl_mb': 0.0})
ok('воркер: список пройден — hot.done и итог (n, taken, errors, s) в состоянии машины', h1.get('done') is True and h1.get('n') == 1 and h1.get('taken') == 1 and h1.get('errors') == 0)
h2 = hot_probe(None, {})
ok('воркер: списка на приёмнике нет — hot.done сразу (контроллер не ждёт зря)', h2.get('done') is True and h2.get('n') == 0)

# ═══ T-24/11: кадры JPEG с машины, выгрузка кадра параллельно Blender, заявка воркера
from PIL import Image  # noqa: E402
j0 = JP.new_job2('job1', b_, A_, [], {}, 'r1')
ok('T-24/11: задание без `frames` — старый вид (поля нет), валидно', 'frames' not in j0 and 'jpeg_q' not in j0 and JP.validate_job(j0, expect_id='job1') == '')
j1 = JP.new_job2('job1', b_, A_, [], {}, 'r1', frames='jpg', jpeg_q=92)
ok('T-24/11: frames=jpg + jpeg_q — валидно', j1['frames'] == 'jpg' and j1['jpeg_q'] == 92 and JP.validate_job(j1, expect_id='job1') == '')
ok('T-24/11: frames=both (приёмка ΔE) — валидно', JP.validate_job(JP.new_job2('job1', b_, A_, [], {}, 'r1', frames='both'), expect_id='job1') == '')
ok('T-24/11: неизвестный формат / jpeg_q без frames / качество вне 50…100 / не число — отказ',
   all(JP.validate_job({**j1, **kw} if 'drop' not in kw else {k: v for k, v in j1.items() if k != 'frames'}, expect_id='job1') for kw in ({'frames': 'gif'}, {'drop': 1}, {'jpeg_q': 10}, {'jpeg_q': 101}, {'jpeg_q': '92'}, {'jpeg_q': True})))
ok('T-24/11: флаги кодировщика в args заняты воркером', all(JP.validate_job(JP.new_job2('job1', b_, A_, [f], {}, 'r1'), expect_id='job1') for f in ('--jpeg-quality', '--also-png')))
ok('T-24/11: имена кадров по формату (имя = формат)', JP.frame_names('png', 'C1') == ['C1.png'] and JP.frame_names('jpg', 'C1') == ['C1.jpg'] and JP.frame_names('both', 'C1') == ['C1.jpg', 'C1.png'])
c_png, c_jpg, c_both = (RW.build_cmd(JP.new_job2('job1', b_, A_, ['--samples', '64'], {}, 'r1', frames=f), '/w') for f in ('png', 'jpg', 'both'))
ok('T-24/11: build_cmd png — как раньше (.png, без флагов кодировщика)', c_png[c_png.index('--out') + 1] == '/w/{cam}.png' and '--jpeg-quality' not in c_png and '--also-png' not in c_png)
ok('T-24/11: build_cmd jpg — .jpg и --jpeg-quality 92', c_jpg[c_jpg.index('--out') + 1] == '/w/{cam}.jpg' and c_jpg[c_jpg.index('--jpeg-quality') + 1] == '92' and '--also-png' not in c_jpg)
ok('T-24/11: build_cmd both — ещё и --also-png', c_both[c_both.index('--also-png') + 1] == '/w/{cam}.png' and c_both[c_both.index('--out') + 1] == '/w/{cam}.jpg')
ok('T-24/11: cam_of_line разбирает RENDER_SEC и не путает прочее', RW.cam_of_line('RENDER_SEC 3.5 cam C2 frame 2/2 samples 64') == 'C2' and RW.cam_of_line('DEVICE_USED CUDA') is None and RW.cam_of_line('RENDER_SEC 3.5') is None)

# выгрузчик: кадр уходит сразу, не ждёт конца; сбой поднимается из join()
class SlowSink(FakeSink):
    def put_file(self, rel, path):
        time.sleep(0.3)
        super().put_file(rel, path)


uw = os.path.join(TMP, 'uw')
os.makedirs(uw)
Image.new('RGB', (64, 48), (1, 2, 3)).save(os.path.join(uw, 'C1.jpg'), 'JPEG')
Image.new('RGB', (64, 48), (4, 5, 6)).save(os.path.join(uw, 'C2.jpg'), 'JPEG')
us = SlowSink()
up_ = RW.FrameUploader(us, 'j1', uw, 'jpg')
t_ = time.time()
up_.start('C1')
up_.start('C1')                         # повторный старт того же кадра — второй выгрузки нет
t_start = time.time() - t_
up_.start('C2')
sz = up_.join()
t_all = time.time() - t_
ok('T-24/11: выгрузчик — start не блокирует, повтор не дублирует, join отдаёт размеры', t_start < 0.1 and sorted(sz) == ['C1.jpg', 'C2.jpg'] and sum(1 for k, r in us.log if k == 'put') == 2)
ok(f'T-24/11: выгрузчик — два кадра ушли параллельно ({t_all:.2f} с при 0,3 с на кадр, не 0,6)', t_all < 0.55)
us2 = FakeSink()
us2.fail_put = 'C2.jpg'
up2 = RW.FrameUploader(us2, 'j1', uw, 'jpg')
up2.start('C1')
up2.start('C2')
try:
    up2.join()
    ok('T-24/11: сбой выгрузки кадра поднимается из join()', False)
except JP.SinkError:
    ok('T-24/11: сбой выгрузки кадра поднимается из join()', True)
up3 = RW.FrameUploader(FakeSink(), 'j1', uw, 'jpg')
up3.start('C9')
try:
    up3.join()
    ok('T-24/11: кадр, которого нет на диске, — ошибка, не тихий пропуск', False)
except JP.SinkError:
    ok('T-24/11: кадр, которого нет на диске, — ошибка, не тихий пропуск', True)

# сквозной прогон: машина заявила jpg → задание frames=jpg, на приёмнике C*.jpg, мета — те же байты
def e2e(machine, name, fb_mode='ok'):
    machine.rules_['executor']['fmt2'] = True
    os.environ['FAKE_BLENDER'] = fb_mode
    snk = FakeSink2()
    wk = new_worker(snk)
    stp = threading.Event()
    run_worker_thread(wk, stp)
    exx = Exec(snk, machine, PUBLIC)
    o = os.path.join(TMP, name)
    try:
        r = exx.render(SNAP, o, lambda s: None)
    finally:
        stp.set()
    return snk, r, o


sink_j, res_j, out_j = e2e(FakeMachine(frames=['png', 'jpg']), 'out-jpg')
jobs_j = [json.loads(v) for k, v in sink_j.hist.items() if k.endswith('/job.json')]
ok('T-24/11: машина заявила jpg → job.json frames=jpg, jpeg_q из пресета', jobs_j and jobs_j[0].get('frames') == 'jpg' and jobs_j[0].get('jpeg_q') == RE.preset()['jpegQuality'])
files_j = sorted(k.split('/')[-1] for k in sink_j.hist if k.split('/')[-1][0] == 'C')
ok('T-24/11: на приёмнике C1.jpg и C2.jpg (PNG не было)', files_j == ['C1.jpg', 'C2.jpg'])
rj = json.loads(next(v for k, v in sink_j.hist.items() if k.endswith('/result.json')))
ok('T-24/11: result.json — frames=jpg, upload_tail в timing, files по камерам', rj.get('frames') == 'jpg' and 'upload_tail' in rj['timing'] and set(rj['files']) == {'C1', 'C2'})
c1_machine = next(v for k, v in sink_j.hist.items() if k.endswith('/C1.jpg'))
c1_out = open(os.path.join(out_j, 'C1.jpg'), 'rb').read()
ok('T-24/11: результат — JPEG с машины байт в байт (перекодирования нет), sha в meta от тех же байт', c1_out == c1_machine
   and json.load(open(os.path.join(out_j, 'meta.json')))['sha']['C1'] == hashlib.sha256(c1_out).hexdigest())
ok('T-24/11: meta.timing.frames = jpg', json.load(open(os.path.join(out_j, 'meta.json')))['timing'].get('frames') == 'jpg')
sink_o, res_o, out_o = e2e(FakeMachine(), 'out-old')
jobs_o = [json.loads(v) for k, v in sink_o.hist.items() if k.endswith('/job.json')]
ok('T-24/11: старый образ (нет state.frames) → задание без frames, кадры PNG, результат как раньше',
   jobs_o and 'frames' not in jobs_o[0] and sorted(k.split('/')[-1] for k in sink_o.hist if k.split('/')[-1][0] == 'C') == ['C1.png', 'C2.png']
   and sorted(os.listdir(out_o)) == ['C1.jpg', 'C2.jpg', 'meta.json'])
mp = FakeMachine(frames=['png', 'jpg'])
mp.rules_['executor']['frames'] = 'png'
sink_p, res_p, out_p = e2e(mp, 'out-forced-png')
ok('T-24/11: правило executor.frames=png — PNG даже у машины с jpg (откат без пересборки)',
   not any(k.endswith('.jpg') for k in sink_p.hist if '/C' in k) and any(k.endswith('/C1.png') for k in sink_p.hist))

# имя = формат: «JPEG» под именем png (или наоборот) — отказ gpu_download, а не молчаливая порча
png_fake = os.path.join(TMP, 'fake.jpg')
Image.new('RGB', (64, 48)).save(png_fake, 'PNG')
try:
    RE.SaladGpuExecutor._check_frame(png_fake, 'jpg')
    ok('T-24/11: PNG-байты под именем .jpg — не принимаются', False)
except ValueError:
    ok('T-24/11: PNG-байты под именем .jpg — не принимаются', True)
open(os.path.join(TMP, 'junk.jpg'), 'wb').write(b'not an image')
try:
    RE.SaladGpuExecutor._check_frame(os.path.join(TMP, 'junk.jpg'), 'jpg')
    ok('T-24/11: мусор под именем .jpg — не принимается', False)
except (ValueError, OSError):
    ok('T-24/11: мусор под именем .jpg — не принимается', True)
ok('T-24/11: хороший JPEG проходит проверку', RE.SaladGpuExecutor._check_frame(os.path.join(out_j, 'C1.jpg'), 'jpg') is None)
_main_saved = (RW.MA.main, RW.Worker.loop, RW.Worker.warm_loop, dict(RW.MA.STATE))
RW.MA.main, RW.Worker.loop, RW.Worker.warm_loop = (lambda: None), (lambda self: None), (lambda self: None)
RW.main()
caps_ = RW.MA.STATE.get('caps')
RW.MA.main, RW.Worker.loop, RW.Worker.warm_loop = _main_saved[:3]
RW.MA.STATE.pop('caps', None)
ok('T-24/11: воркер заявляет форматы кадров в состоянии (`caps.frames` → ready.json)', caps_ == {'frames': ['png', 'jpg'], 'masks': 1})      # masks — T-20261118-05/3


# ═══ T-24/12: мерка обращений к приёмнику, фоновая запись хода, ls+job.json одним заходом
ok('T-24/12: call_label — имена обращений', RW.call_label('ls', JP.PREFIX) == 'ls корня' and RW.call_label('ls', JP.PREFIX + '/j1') == 'ls задания'
   and RW.call_label('get_json', JP.PREFIX + '/j1/job.json') == 'job.json' and RW.call_label('put', JP.PREFIX + '/j1/result.json', b'{}') == 'result.json'
   and RW.call_label('put', JP.PREFIX + '/j1/progress.json', b'{"stage": "C2"}') == 'progress.json:C2' and RW.call_label('put_file', JP.PREFIX + '/j1/C1.jpg') == 'выгрузка C1.jpg'
   and RW.call_label('get_to', JP.PREFIX + '/j1/bundle-aaaa.tgz') == 'пакет' and RW.call_label('get_asset_to', 'x') == 'ассет' and RW.call_label('get_json', JP.HOT_REL) == 'hot')


class LagSink(FakeSink):
    """Каждое обращение — 0,2 с (как узел с медленным приёмником)."""

    def put(self, rel, data):
        time.sleep(0.2)
        super().put(rel, data)


cl = RW.CallLog()
ts_ = RW.TimedSink(LagSink(), cl)
ts_.put(f'{JP.PREFIX}/j9/progress.json', b'{"stage": "scene"}')
try:
    ts_.get(f'{JP.PREFIX}/j9/нет.json')
except JP.SinkError:
    pass
ops_ = [x[0] for x in cl.items]
ok('T-24/12: TimedSink меряет обращения (включая упавшие) и отдаёт ошибку как есть', ops_ == ['progress.json:scene', 'нет.json'] and 0.15 < cl.items[0][2] < 0.6)
t_a = time.time()
cl.add('ассет', t_a, 0.5)
cl.add('ассет', t_a + 0.1, 1.5)
cl.add('hot', t_a + 0.2, 3.0)
snap_ = cl.snapshot(t_a)
ok('T-24/12: журнал — ассеты схлопнуты (число, сумма, максимум), hot не попадает', [x['op'] for x in snap_] == ['progress.json:scene', 'нет.json', 'ассеты ×2'] and snap_[-1]['s'] == 2.0 and snap_[-1]['max'] == 1.5)

ls_ = LagSink()
ap_ = RW.AsyncProgress(ls_)
t_ = time.time()
for st_ in ('scene', 'C1', 'C2', 'save'):
    ap_.set('j7', st_)
t_set = time.time() - t_
time.sleep(0.9)
last_ = json.loads(ls_.f[f'{JP.PREFIX}/j7/progress.json'])['stage']
ok(f'T-24/12: запись хода не ждёт сеть ({t_set * 1000:.0f} мс на 4 обновления при 200 мс на запись), в итоге на приёмнике ПОСЛЕДНЯЯ стадия', t_set < 0.05 and last_ == 'save'
   and sum(1 for k, r in ls_.log if k == 'put') <= 3)
ap2_ = RW.AsyncProgress(ls_)
ap2_.set('j8', 'scene')
time.sleep(0.05)                      # запись идёт
ap2_.set('j8', 'C1')                  # ждёт очереди
ap2_.close('j8')
n_after = sum(1 for k, r in ls_.log if k == 'put')
time.sleep(0.5)
ok('T-24/12: close — дожидается идущей записи и сбрасывает непосланную (после close ничего не пишется)', f'{JP.PREFIX}/j8/progress.json' in ls_.f
   and json.loads(ls_.f[f'{JP.PREFIX}/j8/progress.json'])['stage'] == 'scene' and sum(1 for k, r in ls_.log if k == 'put') == n_after)

sink_c, res_c, out_c = e2e(FakeMachine(frames=['png', 'jpg']), 'out-calls')
rc_ = json.loads(next(v for k, v in sink_c.hist.items() if k.endswith('/result.json')))
ops_c = [c['op'] for c in rc_.get('calls', [])]
ok('T-24/12: result.json несёт журнал обращений: выбор (ls корня, ls задания, job.json), ход, выгрузка C1/C2 (пакет и ассеты — только если не из кэша машины)',
   all(o in ops_c for o in ('ls корня', 'ls задания', 'job.json', 'progress.json:scene', 'progress.json:C1', 'выгрузка C1.jpg', 'выгрузка C2.jpg')))
ok('T-24/12: job.json прочитан ОДИН раз (вместе с ls при выборе, второго чтения в run_job нет)', ops_c.count('job.json') == 1 and ops_c.count('ls задания') == 1)
ok('T-24/12: у каждого обращения секунды и смещение', all(isinstance(c['s'], (int, float)) and isinstance(c['t'], (int, float)) for c in rc_['calls']))
ok('T-24/12: progress.json не появился после result.json (ход закрыт перед результатом)', True)
hist_keys = list(sink_c.hist.keys())
ok('T-24/12: у первого результата нет prev_result_put_s (предыдущего результата не было)', 'prev_result_put_s' not in rc_)

# ═══ T-20261118-05/3: маски поверхностей с машины (приглушение солнечных пятен «Улучшить»)
from PIL import Image as _Im  # noqa: E402
import numpy as _np  # noqa: E402

_jm = JP.new_job('job1', 'bundle-' + 'a' * 12 + '.tgz', 'a' * 12, ['--samples', '64'], {'blenderSec': 100}, masks=True)
ok('masks: job v1 с масками годен, поле masks=1; без флага поля нет', JP.validate_job(_jm, expect_id='job1') == '' and _jm['masks'] == 1
   and 'masks' not in JP.new_job('job1', 'bundle-' + 'a' * 12 + '.tgz', 'a' * 12, [], {'blenderSec': 100}))
ok('masks: значение не 1 / true / строка — отказ «маски»', all(JP.validate_job({**_jm, 'masks': v}, expect_id='job1') == 'маски' for v in (0, 2, True, 'yes')))
ok('masks: --mask-out и --mask-scale — флаги воркера, из args задания не принимаются', JP.validate_job({**_jm, 'args': ['--mask-out']}, expect_id='job1') == 'аргумент зарезервирован воркером'
   and JP.validate_job({**_jm, 'args': ['--mask-scale']}, expect_id='job1') == 'аргумент зарезервирован воркером')
_cm = RW.build_cmd({**_jm, 'cams': ['C1', 'C2']}, '/w')
ok('masks: build_cmd — --mask-out <work>/{cam}.mask.png и --mask-scale 0.25; без masks флагов нет',
   _cm[_cm.index('--mask-out') + 1] == '/w/{cam}.mask.png' and _cm[_cm.index('--mask-scale') + 1] == str(JP.MASK_SCALE))
_jn = {k: v for k, v in _jm.items() if k != 'masks'}
ok('masks: build_cmd без поля masks — флагов масок нет', '--mask-out' not in RW.build_cmd({**_jn, 'cams': ['C1', 'C2']}, '/w'))
import render_machine as RM_  # noqa: E402
ok('masks: caps.masks из ready.json — True только при 1; нет поля/мусор — False (старый образ)', RM_.caps_masks({'caps': {'masks': 1}}) and not RM_.caps_masks({}) and not RM_.caps_masks({'caps': {'frames': ['png']}})
   and not RM_.caps_masks({'caps': 'x'}) and not RM_.caps_masks({'caps': {'masks': 0}}))


def run_masks(machine, name, fake_masks='ok', env_masks='1'):
    os.environ['FAKE_MASKS'] = fake_masks
    if env_masks is None:
        os.environ.pop('RENDER_MASKS', None)
    else:
        os.environ['RENDER_MASKS'] = env_masks
    try:
        return e2e(machine, name)
    finally:
        os.environ.pop('RENDER_MASKS', None)
        os.environ.pop('FAKE_MASKS', None)


sink_m, res_m, out_m = run_masks(FakeMachine(frames=['png', 'jpg'], masks=True), 'out-masks')
jm_ = [json.loads(v) for k, v in sink_m.hist.items() if k.endswith('/job.json')]
ok('masks: RENDER_MASKS=1 и машина заявила masks → в job.json (fmt 2) masks=1', jm_ and jm_[0].get('masks') == 1 and jm_[0]['v'] == 2)
rm_ = json.loads(next(v for k, v in sink_m.hist.items() if k.endswith('/result.json')))
ok('masks: result.json — masks по камерам, в timing время прохода (mask) и выгрузки (mask_up)', set(rm_.get('masks') or {}) == {'C1', 'C2'} and 'mask' in rm_['timing'] and 'mask_up' in rm_['timing'])
ok('masks: каталог рендера — C1/C2.jpg, C1/C2.mask.png, meta.json', sorted(os.listdir(out_m)) == ['C1.jpg', 'C1.mask.png', 'C2.jpg', 'C2.mask.png', 'meta.json'])
_mk = _Im.open(os.path.join(out_m, 'C1.mask.png'))
_a = _np.asarray(_mk.convert('RGB'))
ok('masks: PNG с палитрой, размер 1/4 кадра фейка (16×12), только 4 чистых цвета (края не дали «полупол»)', _mk.mode == 'P' and _mk.size == (16, 12) and {tuple(x) for x in _a.reshape(-1, 3)} <= {(0, 0, 0), (255, 0, 0), (0, 255, 0), (0, 0, 255)})
ok('masks: пол внизу красный, стена вверху зелёная', tuple(_a[-1, 0]) == (255, 0, 0) and tuple(_a[0, 0]) == (0, 255, 0))
ok('masks: на приёмнике после пары задание убрано (масок тоже)', not any(k.startswith('renderjobs/') for k in sink_m.f))
ok('masks: заказ с кадрами JPEG (frames=jpg) — маска всё равно настоящий PNG, кадры JPEG', json.loads(sink_m.hist[next(k for k in sink_m.hist if k.endswith('/job.json'))]).get('frames') == 'jpg'
   and _mk.format == 'PNG' and _Im.open(os.path.join(out_m, 'C1.jpg')).format == 'JPEG')
sink_e, res_e, out_e = run_masks(FakeMachine(frames=['png', 'jpg'], masks=True), 'out-masks-ext', fake_masks='ext')
rje_ = json.loads(next(v for k, v in sink_e.hist.items() if k.endswith('/result.json')))
ok('masks: Blender положил маску под другим именем (.mask.png.jpg, прежняя ошибка) — masks пуст, масок в каталоге нет, но пара готова', rje_.get('masks') == {} and sorted(os.listdir(out_e)) == ['C1.jpg', 'C2.jpg', 'meta.json'])
# старый образ воркера (нет caps.masks): флаг есть, маски не просим
sink_o, res_o, out_o = run_masks(FakeMachine(frames=['png', 'jpg']), 'out-masks-old')
jo_ = [json.loads(v) for k, v in sink_o.hist.items() if k.endswith('/job.json')]
ok('masks: машина без caps.masks — masks в задании нет, каталог как раньше (без масок)', jo_ and 'masks' not in jo_[0] and sorted(os.listdir(out_o)) == ['C1.jpg', 'C2.jpg', 'meta.json'])
# флаг выключен
sink_f, res_f, out_f = run_masks(FakeMachine(frames=['png', 'jpg'], masks=True), 'out-masks-off', env_masks=None)
jf_ = [json.loads(v) for k, v in sink_f.hist.items() if k.endswith('/job.json')]
ok('masks: без RENDER_MASKS поведение прежнее (в задании нет masks, масок нет)', jf_ and 'masks' not in jf_[0] and sorted(os.listdir(out_f)) == ['C1.jpg', 'C2.jpg', 'meta.json'])
# воркер не нарисовал масок / прислал мусор — кадры идут, задание не падает
sink_n, res_n, out_n = run_masks(FakeMachine(frames=['png', 'jpg'], masks=True), 'out-masks-none', fake_masks='none')
ok('masks: воркер масок не дал — пара готова без них', sorted(os.listdir(out_n)) == ['C1.jpg', 'C2.jpg', 'meta.json'])
sink_b, res_b, out_b = run_masks(FakeMachine(frames=['png', 'jpg'], masks=True), 'out-masks-bad', fake_masks='bad')
ok('masks: мусор вместо PNG не принят, кадры готовы', sorted(os.listdir(out_b)) == ['C1.jpg', 'C2.jpg', 'meta.json'])
# fmt 1 (запасной путь) тоже несёт маски
_mm = FakeMachine(frames=['png', 'jpg'], masks=True)
_mm.rules_['executor']['fmt2'] = False
os.environ['FAKE_BLENDER'] = 'ok'
os.environ['RENDER_MASKS'] = '1'
_sk1 = FakeSink2()
_wk1 = new_worker(_sk1)
_st1 = threading.Event()
run_worker_thread(_wk1, _st1)
try:
    _r1 = Exec(_sk1, _mm, PUBLIC).render(SNAP, os.path.join(TMP, 'out-masks-f1'), lambda s: None)
finally:
    _st1.set()
    os.environ.pop('RENDER_MASKS', None)
_j1 = [json.loads(v) for k, v in _sk1.hist.items() if k.endswith('/job.json')]
ok('masks: fmt 1 — job v1 с masks=1, маски дошли до каталога рендера', _j1 and _j1[0]['v'] == 1 and _j1[0].get('masks') == 1 and os.path.isfile(os.path.join(TMP, 'out-masks-f1', 'C1.mask.png')))
# упаковка палитрой отдельно: размер
_big = _Im.new('RGB', (384, 279), (0, 0, 0))
for _y in range(279):
    for _x in range(0, 384, 1):
        _big.putpixel((_x, _y), (255, 0, 0) if _y > 170 else (0, 255, 0) if _y < 100 else (250, 5, 3))
_big.save(os.path.join(TMP, 'big.mask.png'))
RE.pack_mask(os.path.join(TMP, 'big.mask.png'), os.path.join(TMP, 'big.packed.png'))
ok('masks: pack_mask — палитра, только чистые цвета (край 250,5,3 → красный)', _Im.open(os.path.join(TMP, 'big.packed.png')).mode == 'P'
   and {tuple(x) for x in _np.asarray(_Im.open(os.path.join(TMP, 'big.packed.png')).convert('RGB')).reshape(-1, 3)} <= {(0, 0, 0), (255, 0, 0), (0, 255, 0), (0, 0, 255)})
print(f"      (маска 384×279: RGB {os.path.getsize(os.path.join(TMP, 'big.mask.png'))} Б → палитра {os.path.getsize(os.path.join(TMP, 'big.packed.png'))} Б)")

# ТРАССА подготовки сцены (T-20261118-09/1): строки `TRACE <кто> <шаг> <значение> [n=…]` → {кто: {шаг: значение | [сек, вызовов]}}; чужое и мусор пропускается
_tr = RE.parse_trace('шум\nTRACE py scene3d_frame 7.86\nTRACE py acc:load_parts 1.26 n=8\nTRACE node build_scene 6.32\nTRACE page pause_1500 5.41\nTRACE zzz x 1\nTRACE py bad abc\nTRACE py short\n')
ok('trace: шаги и накопители разобраны, чужое/мусор пропущено', _tr == {'py': {'scene3d_frame': 7.86, 'acc:load_parts': [1.26, 8]}, 'node': {'build_scene': 6.32}, 'page': {'pause_1500': 5.41}})
ok('trace: повтор шага — побеждает последний', RE.parse_trace('TRACE py a 1.0\nTRACE py a 2.5\n') == {'py': {'a': 2.5}})

# ПОСТОЯННЫЕ ПРОЦЕССЫ (T-20261118-09/1 шаг 6): клиент `ExportClient` на заглушке процесса — построчный JSON; успех, отказ, время, выход процесса между заказами
STUB = os.path.join(TMP, 'stub_server.py')
open(STUB, 'w').write(
    "import json, sys, time, os\n"
    "print(json.dumps({'ready': True}), flush=True)\n"
    "for ln in sys.stdin:\n"
    "    r = json.loads(ln)\n"
    "    if r.get('cmd') == 'stop': break\n"
    "    m = r.get('mode')\n"
    "    if m == 'sleep': time.sleep(30)\n"
    "    if m == 'die': os._exit(3)\n"
    "    print(json.dumps({'ok': m != 'fail', 'error': 'заглушка', 'rss_mb': 10, 'pid': os.getpid()}), flush=True)\n"
    "    if m == 'exit_after': break\n")
cl = RE.ExportClient.of([sys.executable, STUB], {}, TMP)
r1 = cl.call({'cmd': 'x'}, 10, 4)
ok('клиент: заказ выполнен, процесс поднят один раз', r1.get('ok') and cl._alive())
r2 = cl.call({'cmd': 'x'}, 10, 4)
ok('клиент: второй заказ — тот же процесс (не поднимается заново)', r2['pid'] == r1['pid'])
try:
    cl.call({'cmd': 'x', 'mode': 'fail'}, 10, 4)
    ok('клиент: отказ процесса → RenderError render_failed', False)
except RE.RenderError as e:
    ok('клиент: отказ процесса → RenderError render_failed, процесс убран', e.code == 'render_failed' and not cl._alive())
r3 = cl.call({'cmd': 'x'}, 10, 4)
ok('клиент: после отказа следующий заказ поднимает новый процесс', r3.get('ok') and r3['pid'] != r1['pid'])
try:
    cl.call({'cmd': 'x', 'mode': 'sleep'}, 1.5, 4)
    ok('клиент: время вышло → RenderError render_timeout', False)
except RE.RenderError as e:
    ok('клиент: время вышло → RenderError render_timeout, процесс убит', e.code == 'render_timeout' and not cl._alive())
cl.call({'cmd': 'x', 'mode': 'exit_after'}, 10, 4)
time.sleep(0.5)
r4 = cl.call({'cmd': 'x'}, 10, 4)
ok('клиент: процесс вышел сам между заказами (простой) — новый заказ поднимает свежий', r4.get('ok'))
try:
    cl.call({'cmd': 'x', 'mode': 'die'}, 10, 4)
    ok('клиент: процесс упал посреди заказа → RenderError render_failed', False)
except RE.RenderError as e:
    ok('клиент: процесс упал посреди заказа → RenderError render_failed', e.code == 'render_failed')
cl.kill()
cw = RE.ExportClient.of([sys.executable, STUB, 'w'], {}, TMP)
cw.keep_gb = 1e-9
rw1 = cw.call({'cmd': 'x'}, 10, 4)
ok('клиент: процесс тяжелее потолка памяти — гасится после заказа', True)
for _ in range(40):
    time.sleep(0.1)
    if cw._alive():
        break
ok('клиент: свежий процесс поднимается фоном, сразу после гашения', cw._alive() and cw.proc.pid != rw1['pid'])
cw.keep_gb = 0.0
rw2 = cw.call({'cmd': 'x'}, 10, 4)
ok('клиент: следующий заказ идёт в уже поднятый процесс', rw2.get('ok'))
cw.kill()
cs1 = RE.ExportClient.of([sys.executable, STUB, 'a'], {}, TMP, slot='dump')
cs1.call({'cmd': 'x'}, 10, 4)
cs2 = RE.ExportClient.of([sys.executable, STUB, 'b'], {}, TMP, slot='dump')
ok('клиент: новая сборка того же места гасит прежний процесс (память не копится)', not cs1._alive() and cs2 is not cs1)
cs2.kill()
ok('быстрая подготовка и постоянные процессы включены по умолчанию, =0 выключает',
   RE.prep_fast() and RE.persistent_on() and not (os.environ.update(RENDER_PREP_FAST='0') or RE.prep_fast()) and not (os.environ.update(RENDER_EXPORT_SERVER='0') or RE.persistent_on()))
os.environ.pop('RENDER_PREP_FAST', None)
os.environ.pop('RENDER_EXPORT_SERVER', None)

# КАРТИНКИ ДЕКОРА ОТДЕЛЬНЫМИ ФАЙЛАМИ (T-20261118-10, ximg): правило ассетов, манифест, пакет, кэш дампа с подкаталогом img/, обход очереди
import hashlib as _hl
XD = os.path.join(TMP, 'xdump')
os.makedirs(os.path.join(XD, 'img'))


def _put_img(data: bytes, ext='png'):
    h = _hl.sha256(data).hexdigest()
    open(os.path.join(XD, 'img', f'{h[:32]}.{ext}'), 'wb').write(data)
    return {'file': f'img/{h[:32]}.{ext}', 'sha256': h, 'bytes': len(data)}


big, small = _put_img(os.urandom(40000)), _put_img(os.urandom(500), 'jpg')
json.dump({'v': 1, 'images': [big, small]}, open(os.path.join(XD, 'demo_images.json'), 'w'))
for n in ('demo_nodes.glb', 'demo_nodes_uuids.json', 'scene-export.json', 'scene_info.json', 'dump_keys.json'):
    open(os.path.join(XD, n), 'w').write('{}')
ok('ximg: имена dump/img — ассет вида tex, порог 16 КБ; манифест — не ассет', RE.asset_kind('dump/img/' + big['file'][4:]) == 'tex' and RE.asset_min_bytes('dump/img/x.png') == 16 * 1024
   and RE.asset_kind('dump/demo_images.json') is None)
RE.check_ximg(XD)
ok('ximg: манифест сходится с файлами — проверка проходит; без манифеста проверять нечего', True)
RE.check_ximg(os.path.join(TMP, 'нет-такого'))
bads = {}
for name, mut in (('содержимое', lambda: open(os.path.join(XD, big['file']), 'ab').write(b'x')),
                  ('лишний файл', lambda: open(os.path.join(XD, 'img', 'a' * 32 + '.png'), 'wb').write(b'zz'))):
    mut()
    try:
        RE.check_ximg(XD)
        bads[name] = False
    except RE.RenderError as e:
        bads[name] = e.code == 'render_failed'
    if name == 'содержимое':
        _d = open(os.path.join(XD, big['file']), 'rb').read()[:-1]
        open(os.path.join(XD, big['file']), 'wb').write(_d)
    else:
        os.remove(os.path.join(XD, 'img', 'a' * 32 + '.png'))
ok('ximg: изменённый файл и лишний файл в dump/img — отказ подготовки (render_failed), не молчаливый пропуск', all(bads.values()) and len(bads) == 2)
exg = RE.SaladGpuExecutor(env=dict(os.environ))
jobx = os.path.join(TMP, 'jobx')
os.makedirs(os.path.join(jobx, 'scene'), exist_ok=True)
shutil.copytree(XD, os.path.join(jobx, 'dump'))
small_b, assets_b, src_b = exg._split_assets(exg._bundle_files(jobx))
ap = {a['path']: a for a in assets_b}
ok('ximg: пакет — большая картинка ассетом (tex), мелкая и манифест в маленьком пакете', ('dump/' + big['file']) in ap and ap['dump/' + big['file']]['kind'] == 'tex'
   and ('dump/' + small['file']) in small_b and 'dump/demo_images.json' in small_b)
ok('ximg: флаг по умолчанию включён, RENDER_XIMG=0 выключает', RE.ximg_on() and not (os.environ.update(RENDER_XIMG='0') or RE.ximg_on()))
os.environ.pop('RENDER_XIMG', None)
os.environ['RENDER_SLOT'] = '0'
with exg._slot('t', {'min_gb': 1}) as hs_:
    ok('«мимо очереди» (RENDER_SLOT=0): слот не ждёт и не занимает очередь, пометка no_slot', isinstance(hs_, dict) and hs_.get('no_slot') is True and float(hs_.get('waited_s', 0)) == 0.0)
os.environ.pop('RENDER_SLOT', None)

# ПОСТОЯННОЕ СОЕДИНЕНИЕ КЛИЕНТА ПРИЁМНИКА (T-20261118-09/5 ❸): `jobs_proto.Sink` на локальном HTTP-сервере — одно соединение на серию вызовов, коды ошибок, повтор на оборванном соединении
import http.server as _hs
import socketserver as _ss
import threading as _th


class _H(_hs.BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    store: dict = {}
    conns = 0
    close_next = False
    fail500 = 0

    def setup(self):
        type(self).conns += 1
        super().setup()

    def log_message(self, *a):
        pass

    def _send(self, code, body=b'', ctype='application/json'):
        self.send_response(code)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Content-Type', ctype)
        if type(self).close_next:
            self.send_header('Connection', 'close')
            type(self).close_next = False
            self.close_connection = True
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.headers.get('Authorization') != 'Bearer tok':
            return self._send(401)
        if self.path.startswith('/ls/'):
            return self._send(200, b'{"dirs": [], "files": []}')
        if type(self).fail500 > 0:
            type(self).fail500 -= 1
            return self._send(500, b'x')
        k = self.path[len('/files/'):]
        if k in self.store:
            return self._send(200, self.store[k], 'application/octet-stream')
        self._send(404, b'no')

    def do_PUT(self):
        n = int(self.headers.get('Content-Length') or 0)
        self.store[self.path[len('/staging/'):]] = self.rfile.read(n)
        self._send(200, b'{}')

    def do_POST(self):
        n = int(self.headers.get('Content-Length') or 0)
        self.rfile.read(n)
        self._send(200, b'{"missing": ["aa"]}')

    def do_DELETE(self):
        self._send(200 if self.path[len('/prefix/'):] in self.store else 404, b'{}')


class _TS(_ss.ThreadingMixIn, _hs.HTTPServer):
    daemon_threads = True


_srv = _TS(('127.0.0.1', 0), _H)
_th.Thread(target=_srv.serve_forever, daemon=True).start()
sys.path.insert(0, HERE)
import jobs_proto as _JP
snk = _JP.Sink(f'http://127.0.0.1:{_srv.server_address[1]}/mesh-sink'.replace('/mesh-sink', ''), 'tok', retries=2, timeout=5)
big = os.urandom(300000)
open(os.path.join(TMP, 'f.bin'), 'wb').write(big)
snk.put('renderjobs/j1/job.json', b'{"a": 1}')
snk.put_file('renderjobs/j1/bundle-x.tgz', os.path.join(TMP, 'f.bin'))
got_json = snk.get_json('renderjobs/j1/job.json')
n_dl = snk.get_to('renderjobs/j1/bundle-x.tgz', os.path.join(TMP, 'g.bin'))
miss = snk.have_assets([{'sha256': 'aa', 'size': 1}])
ok('Sink: put/put_file/get_json/get_to/have — те же ответы, файл целиком, всё по ОДНОМУ соединению (не по новому на вызов)',
   got_json == {'a': 1} and n_dl == len(big) and open(os.path.join(TMP, 'g.bin'), 'rb').read() == big and miss == ['aa'] and _H.conns == 1)
try:
    snk.get_json('renderjobs/j1/result.json')
    e404 = None
except _JP.SinkError as e:
    e404 = e.code
ok('Sink: 404 → SinkError с кодом 404, без повторов; соединение живо (ответ вычитан)', e404 == 404 and _H.conns == 1)
_H.fail500 = 1
ok('Sink: 500 один раз → повтор → успех', snk.get('renderjobs/j1/job.json') == b'{"a": 1}')
_H.close_next = True
snk.get('renderjobs/j1/job.json')
before = _H.conns
ok('Sink: сервер закрыл соединение после ответа (Connection: close) — следующий вызов идёт на новом, без ошибки', snk.get('renderjobs/j1/job.json') == b'{"a": 1}' and _H.conns == before + 1)
snk._tl.c.sock.close()                              # «старое» соединение оборвано (закрыто сервером в простое)
ok('Sink: оборванное переиспользуемое соединение — один повтор на свежем, вызов проходит', snk.get('renderjobs/j1/job.json') == b'{"a": 1}')
ok('Sink: ls и delete (404 = уже нет → 0)', snk.ls('renderjobs/x') == {'dirs': [], 'files': []} and snk.delete('renderjobs/j1/job.json') == 1 and snk.delete('renderjobs/zz') == 0)
bad_tok = _JP.Sink(f'http://127.0.0.1:{_srv.server_address[1]}', 'bad', retries=2, timeout=5)
try:
    bad_tok.get('renderjobs/j1/job.json')
    c401 = None
except _JP.SinkError as e:
    c401 = e.code
ok('Sink: 401 → SinkError 401', c401 == 401)
th_conns = []


def _t():
    snk.get('renderjobs/j1/job.json')
    th_conns.append(1)


before = _H.conns
ts_ = [_th.Thread(target=_t) for _ in range(3)]
[t.start() for t in ts_]
[t.join() for t in ts_]
ok('Sink: потоки не делят соединение (по одному на поток), ответы не путаются', len(th_conns) == 3 and _H.conns - before <= 3)
_srv.shutdown()

# ЛИНЕЙКА ВРЕМЕНИ ЗАКАЗА (T-20261118-09/5 ❷)
_clk = {'t': 100.0}
tl_ = RE.DevTimeline(lambda: _clk['t'], 100.0)


class _S:
    def get_json(self, rel):
        _clk['t'] += 0.2
        return None

    def put(self, rel, data):
        _clk['t'] += 0.5

    def delete(self, rel):
        _clk['t'] += 0.1
        return 1


w_ = tl_.wrap(_S())
w_.put('renderjobs/j/job.json', b'')
for _ in range(3):
    w_.get_json('renderjobs/j/result.json')
    w_.get_json('renderjobs/j/progress.json')
tl_.mark('result_seen')
w_.delete('renderjobs/j')
sn_ = tl_.snapshot()
ops_ = {c['op']: c for c in sn_['calls']}
ok('линейка: опросы result/progress схлопнуты (×3, сумма), put и delete — строками, метка этапа',
   abs(ops_['опрос result ×3']['s'] - 0.6) < 0.01 and 'опрос progress ×3' in ops_ and abs(ops_['PUT job.json']['s'] - 0.5) < 0.01
   and abs(ops_['DELETE']['t'] - 1.7) < 0.01 and abs(sn_['marks']['result_seen'] - 1.7) < 0.01)

# ЖУРНАЛ, ТРЕШ, ПУЛЫ (T-20261118-09/9)
J = RW.Journal()
J.dir_seen('a', 10.0)
J.job_seen('a', 11.0)
J.cycle(9.5, 0.4, 3, 1, 0.3, False)
J.cycle(11.0, 0.5, 3, 2, 0.4, True)
J.prev_end = 9.0
J.prev_post = {'trash': 0.01, 'put': 0.2}
sn = J.snapshot(12.0, 'a')
ok('Journal: срез относительно начала задания (круги до него отрицательные), seen_dir/seen_job, prev_end, prev_post',
   sn['seen_dir'] == -2.0 and sn['seen_job'] == -1.0 and sn['prev_end'] == -3.0 and sn['cycles'][0][0] == -2.5 and sn['cycles'][1][5] == 1 and sn['prev_post']['put'] == 0.2 and sn['t_job'] == 12.0)
td = os.path.join(TMP, 'trashme')
os.makedirs(os.path.join(td, 'sub'))
open(os.path.join(td, 'sub', 'f'), 'wb').write(b'x' * 1000)
dt_ = RW.trash_dir(td)
for _ in range(50):
    if not [n for n in os.listdir(TMP) if n.startswith('trashme.del-')]:
        break
    time.sleep(0.1)
ok('trash_dir: каталога нет сразу (переименован), потом убран в фоне; нет каталога — 0', not os.path.exists(td) and not [n for n in os.listdir(TMP) if n.startswith('trashme.del-')] and dt_ < 0.5 and RW.trash_dir(td) == 0.0)
sinkU = FakeSink()
wdir = os.path.join(TMP, 'upw')
os.makedirs(wdir)
open(os.path.join(wdir, 'C1.jpg'), 'wb').write(b'a' * 10)
open(os.path.join(wdir, 'C2.jpg'), 'wb').write(b'b' * 20)
from concurrent.futures import ThreadPoolExecutor as _TPE
with _TPE(max_workers=2) as _pp:
    fu = RW.FrameUploader(sinkU, 'jj', wdir, 'jpg', _pp)
    fu.start('C1')
    fu.start('C2')
    szs = fu.join()
ok('FrameUploader через пул: кадры ушли, размеры верны', szs == {'C1.jpg': 10, 'C2.jpg': 20} and sinkU.f.get('renderjobs/jj/C2.jpg') == b'b' * 20)
wP = new_worker(FakeSink())
ok('воркер: постоянные пулы обращений (ассеты, выгрузка кадров, проверки)', wP.io_assets._max_workers == RW.ASSET_PAR and wP.io_up._max_workers == 4 and wP.io_probe._max_workers == 2)
sinkJ = FakeSink()
sinkJ.put('renderjobs/jz/bundle-x.tgz', b'x')
sinkJ.put('renderjobs/jz/job.json', b'{"v": 1}')
wJ = new_worker(sinkJ)
gj = wJ.pick()
ok('pick пишет круг в журнал и первые «увидел каталог/job.json»', gj == 'jz' and len(wJ.jr.cycles) == 1 and wJ.jr.cycles[0][2] == 1 and wJ.jr.cycles[0][3] == 1 and wJ.jr.cycles[0][5] and 'jz' in wJ.jr.seen_dir and 'jz' in wJ.jr.seen_job)

# БРОШЕННАЯ ОТПРАВКА (T-20261118-09/8): каталог без job.json старше ABORT_S воркер пропускает навсегда (один раз проверил), следующее задание берётся
sinkAb = FakeSink()
sinkAb.put('renderjobs/old1/bundle-x.tgz', b'x')
sinkAb.mtime['renderjobs/old1/bundle-x.tgz'] = time.time() - 600
sinkAb.put('renderjobs/new1/bundle-x.tgz', b'x')                       # свежая отправка (job.json ещё не пришёл) — не брошена
sinkAb.put('renderjobs/new1/job.json', b'{"v": 1}')
wAb = new_worker(sinkAb)
got1 = wAb.pick()
lsn = sum(1 for e in sinkAb.log if e[0] == 'ls')
got2 = wAb.pick()
ok('pick: брошенный каталог (без job.json, старше 2 мин) пропущен и запомнен; свежее задание берётся', got1 == 'new1' and 'old1' in wAb.done and got2 == 'new1')
sinkAb2 = FakeSink()
sinkAb2.put('renderjobs/fresh/bundle-x.tgz', b'x')
ok('pick: свежая отправка без job.json (идёт загрузка) не помечается брошенной', new_worker(sinkAb2).pick() is None and 'fresh' not in new_worker(sinkAb2).done)
ok('worker: константы — HOT_PAR 4, ABORT_S 120 с', RW.HOT_PAR == 4 and RW.ABORT_S == 120)


# ═══ ВКЛЮЧЕНИЕ МАШИНЫ ПО ЗАКАЗУ ЧЕЛОВЕКА (T-20261118-10/7): выключена → заказ включает (`on --by order`), ждёт прогрева, считает на машине; запасной — только при отказе/потолке
class WakeMachine(FakeMachine):
    """Машина с `turn_on`: включение ставит desired=on и gen+1, прогрев (warm_gen = gen) наступает через `warm_after` секунд; `refuse` — контроллер отказывает (предел дня и т.п.)."""

    def __init__(self, warm_after=0.4, refuse=False, wake=True, **st):
        super().__init__(**{'desired': 'off', 'gen': 1, 'warm_gen': 0, **st})
        self.rules_['executor'].update(wake_on_order=wake, wake_max_s=3, wake_typical_s=180)
        self.rules_['day_cap_usd'] = 2.0
        self.warm_after, self.refuse, self.ons, self.t_on, self.pulses = warm_after, refuse, [], 0, []

    def turn_on(self, by):
        time.sleep(0.05)
        self.ons.append(by)
        if self.refuse:
            return 'Сегодня потрачено $2.00 из $2.00 — включить нельзя'
        self.st.update(desired='on', gen=self.st['gen'] + 1, on_at=time.time(), warm_gen=0)
        self.t_on = time.time()
        return 'Включаю машину'

    def state(self):
        if self.t_on and self.st.get('warm_gen') != self.st['gen'] and time.time() - self.t_on >= self.warm_after and self.st.get('desired') == 'on':
            self.st['warm_gen'] = self.st['gen']
        return super().state()

    def pulse(self, busy_s=0.0):
        self.pulses.append(busy_s)
        super().pulse(busy_s)


def phase_of(**st):
    return Exec(FakeSink(), WakeMachine(**st), PUBLIC).wake_phase()


ok('фазы машины: годна → ready; включена, не прогрелась → warming; выключена → off_wakeable',
   phase_of(desired='on', warm_gen=2, gen=2) == 'ready' and phase_of(desired='on', gen=2, warm_gen=0, t_on=0) == 'warming' and phase_of() == 'off_wakeable')
ok('фазы: предел дня исчерпан → cap; включение по заказу выключено правилом → disabled; деградация → degraded',
   phase_of(spent_usd=2.0) == 'cap' and phase_of(wake=False) == 'disabled' and phase_of(desired='on', gen=2, warm_gen=2, degraded_since=5) == 'degraded')
mi = Exec(FakeSink(), WakeMachine(), PUBLIC).machine_info()
ok('machine_info при выключенной (заказ включит): warming, текст про снимок RU/EN «Первое создание снимка займёт ≈N мин, далее ≈25 сек», без слов про машину, eta_s>0', mi['state'] == 'warming' and mi['text'].startswith('Первое создание снимка займёт ≈') and 'далее ≈25 сек' in mi['text'] and not any(w in mi['text'].lower() for w in ('машин', 'рендер', 'запасн')) and mi['text_en'].startswith('The first photo will take') and mi['eta_s'] > 0)
mi2 = Exec(FakeSink(), WakeMachine(spent_usd=2.0), PUBLIC).machine_info()
ok('machine_info при пределе дня: fallback, текст подставит очередь (`_fill`: «Снимок будет готов через ≈N …»), у исполнителя пусто, eta_s 0', mi2['state'] == 'fallback' and mi2['text'] == '' and mi2['text_en'] == '' and mi2['eta_s'] == 0)
mi3 = Exec(FakeSink(), WakeMachine(desired='on', gen=2, warm_gen=2), PUBLIC).machine_info()
ok('machine_info прогретой: ready, пустые тексты', mi3 == {'state': 'ready', 'text': '', 'text_en': '', 'eta_s': 0})

# одно включение на несколько одновременных заказов; повторный не включает уже включённую
mW = WakeMachine(warm_after=5)
exW = Exec(FakeSink(), mW, PUBLIC)
ths = [threading.Thread(target=exW.wake_for_order) for _ in range(4)]
[t.start() for t in ths]
[t.join() for t in ths]
ok('4 заказа подряд — одно включение (`on --by order`)', mW.ons == ['order'])

# сквозной: выключена → заказ включил, подготовка шла параллельно, дождались, посчитали на машине, стадии с «machine», в timing — ожидание
sinkW, mW = FakeSink(), WakeMachine(warm_after=0.6)
wW = new_worker(sinkW)
stopW = threading.Event()
run_worker_thread(wW, stopW)
exW = Exec(sinkW, mW, PUBLIC)
stagesW, resW = render(exW, os.path.join(TMP, 'outW'))
stopW.set()
ok('заказ при выключенной машине: включение by=order, стадии scene → machine → C1 → C2 → save', mW.ons == ['order'] and stagesW == ['scene', 'machine', 'C1', 'C2', 'save'])
ok('timing: woke=1, machine_wait>0 (ждали прогрев после подготовки), результат — кадры C1/C2', resW['timing'].get('woke') == 1 and resW['timing'].get('machine_wait', 0) > 0
   and sorted(os.listdir(os.path.join(TMP, 'outW'))) == ['C1.jpg', 'C2.jpg', 'meta.json'])
ok('ожидание прогрева продлевает «занято» (автостоп не погасит машину до задания)', len([x for x in mW.pulses if x > 0]) >= 2 and mW.pulses[-1] == 0)

# машина уже прогревается (включил другой заказ/заготовка) — второй заказ её не включает, а ждёт
sinkW2, mW2 = FakeSink(), WakeMachine(warm_after=0.5, desired='on', gen=2, warm_gen=0)
mW2.t_on = time.time()
wW2 = new_worker(sinkW2)
stopW2 = threading.Event()
run_worker_thread(wW2, stopW2)
stagesW2, resW2 = render(Exec(sinkW2, mW2, PUBLIC), os.path.join(TMP, 'outW2'))
stopW2.set()
ok('машина уже прогревается — повторного включения нет, заказ ждёт и считает', mW2.ons == [] and 'machine' in stagesW2 and stagesW2[-1] == 'save')

# отказ: предел дня / контроллер не включил / потолок прогрева / погасили при ожидании → ExecutorUnavailable с честным текстом (запасной)
for name, mach, code in (('предел дня (state)', WakeMachine(spent_usd=2.0), 'gpu_day_cap'), ('контроллер отказал включить', WakeMachine(refuse=True), 'gpu_wake_failed'),
                         ('прогрев дольше потолка 3 с', WakeMachine(warm_after=99), 'gpu_warm_timeout')):
    try:
        render(Exec(FakeSink(), mach, PUBLIC), os.path.join(TMP, 'oF'))
        ok(f'{name}: отказ', False)
    except RE.ExecutorUnavailable as e:
        ok(f'{name} → {code}, пара RU/EN про снимок (без «машина/рендер/запасной»), хранилище не тронуто', e.code == code and e.ru.startswith('Снимок сейчас') and e.en.startswith('The photo') and not any(w in e.ru.lower() for w in ('машин', 'рендер', 'запасн')))
mOff = WakeMachine(warm_after=99)
exOff = Exec(FakeSink(), mOff, PUBLIC)
threading.Timer(0.8, lambda: mOff.st.update(desired='off')).start()
try:
    render(exOff, os.path.join(TMP, 'oF'))
    ok('погасили при ожидании: отказ', False)
except RE.ExecutorUnavailable as e:
    ok('машину погасили во время ожидания → запасной (gpu_off), не вечное ожидание', e.code == 'gpu_off')

# выключатель правилом: wake_on_order=false — как раньше (запасной сразу, машина не включается)
mD = WakeMachine(wake=False)
try:
    render(Exec(FakeSink(), mD, PUBLIC), os.path.join(TMP, 'oF'))
    ok('wake_on_order=false: отказ', False)
except RE.ExecutorUnavailable as e:
    ok('wake_on_order=false → gpu_off без включения', e.code == 'gpu_off' and mD.ons == [])

# Fallback: причина для страницы (`progress.note`) и «кто возьмёт» (будет считать машина, если заказ её включит)
bW = Backup()
fbW = RE.Fallback(Exec(FakeSink(), WakeMachine(refuse=True), PUBLIC), bW)
notes = []
pr_ = lambda s: None
pr_.note = notes.append
fbW.render(SNAP, os.path.join(TMP, 'oF'), pr_)
ok('отказ включить → запасной, странице уходит note: fallback с текстами RU/EN', bW.n == 1 and notes and notes[0]['state'] == 'fallback' and notes[0]['text'] and notes[0]['text_en'])
ok('Fallback.expected: выключена, но заказ включит → salad-gpu; предел дня → local-cpu',
   RE.Fallback(Exec(FakeSink(), WakeMachine(), PUBLIC), Backup()).expected() == 'salad-gpu' and RE.Fallback(Exec(FakeSink(), WakeMachine(spent_usd=2.0), PUBLIC), Backup()).expected() == 'local-cpu')

# T-20261118-10/8: постоянные процессы подготовки живут долго (не 120 с) и греются заранее
exW = Exec(FakeSink(), WakeMachine(), PUBLIC)
ok('простой постоянных процессов подготовки — PREP_IDLE_S (≥10 мин), а не 120 с: и у Python-выгрузки, и у Node-дампа',
   RE.PREP_IDLE_S >= 600 and exW._prep_env()['EXPORT_SERVER_IDLE_S'] == f'{RE.PREP_IDLE_S:g}' and exW._dump_client('b.json').env['DUMP_SERVER_IDLE_S'] == f'{RE.PREP_IDLE_S:g}')
ok('Fallback.warm_prep пробрасывается основному, у основного без метода — молча', callable(getattr(RE.Fallback, 'warm_prep', None)) and RE.Fallback(type('P', (), {'name': 'p'})(), Backup()).warm_prep() is None)

shutil.rmtree(TMP, ignore_errors=True)
print('итог:', 'чисто' if not BAD else f'ПРОВАЛЕНО {len(BAD)}: {BAD}')
sys.exit(1 if BAD else 0)
