"""Тесты исполнителя `salad-gpu`, воркера машины и протокола заданий (T-20261117-24/2). Без сети и без платного: хранилище — в памяти,
Blender — подмена (`fake_blender.py`), машина — подмена состояния. Сквозной прогон: исполнитель (поток 1) ↔ воркер (поток 2) через «хранилище».

Запуск: ~/venvs/scout/bin/python tools/scout/render_gpu/tests_render_executor.py   (код 0 — чисто; нужен PIL)"""
import contextlib
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
                  RENDER_WORK=os.path.join(TMP, 'rwork'), RENDER_MACHINE_DIR=os.path.join(TMP, 'rm'), AGENT_BEAT_S='3600')
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
ok('карты — только существующие в public (чужой путь и отсутствующий файл не попали)',
   os.path.isfile(os.path.join(bd, 'x', 'public', 'flat3d', 'tex', 'a.jpg')) and not os.path.exists(os.path.join(bd, 'x', 'public', 'etc')) and
   not os.path.exists(os.path.join(bd, 'x', 'public', 'flat3d', 'none.jpg')))
ok('рабочая папка исполнителя убрана', not [d for d in os.listdir(os.path.join(TMP, 'rwork')) if d.startswith('gjob-')])

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
good = JP.new_job('j1', 'bundle-aaa.tgz', 'aaa', ['--samples', 64], {'blenderSec': 100})
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
shutil.rmtree(TMP, ignore_errors=True)
print('итог:', 'чисто' if not BAD else f'ПРОВАЛЕНО {len(BAD)}: {BAD}')
sys.exit(1 if BAD else 0)
