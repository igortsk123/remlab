"""Тесты ВОРОТ сторожа кадров (render-qa-gate-01, шаг 5, T-20261118-03/7): брак предпроверки — заказ не считается; кадровый брак — кадр не публикуется и не ложится в кэш;
MAIN_NOT_VISIBLE и «неопределимо» не блокируют; выключатель `RENDER_QA_GATE=0` — прежнее поведение; повтор того же ключа не жжёт рендер; заготовка не зацикливается.
Без сети, без платного и без настоящего Blender: Blender — подмена, которая пишет кадр и отчёт сторожа по режиму.

Запуск: python tools/scout/render_gpu/tests_render_gate.py   (код 0 — чисто; нужен PIL)"""
import contextlib
import functools
import json
import os
import shutil
import stat
import sys
import tempfile
import time
import types

HERE = os.path.dirname(os.path.abspath(__file__))
SCOUT = os.path.abspath(os.path.join(HERE, '..'))
PROBE = os.path.join(SCOUT, 'cycles_probe')
TMP = tempfile.mkdtemp(prefix='gate-test-')
os.environ.update(RENDER_WORK=os.path.join(TMP, 'rwork'), RENDER_PREP_CACHE=os.path.join(TMP, 'prep'), RENDER_MACHINE_DIR=os.path.join(TMP, 'rm'),
                  RENDER_PREWARM_STATUS=os.path.join(TMP, 'pw-status.json'))
os.environ.pop('RENDER_QA_GATE', None)
sys.path[:0] = [SCOUT, HERE, PROBE]
import render_exec as RE  # noqa: E402
import render_jobs as RJ  # noqa: E402
import render_prewarm as PW  # noqa: E402
import test_frame_qa as TF  # noqa: E402  (подмена мира сцены для предпроверки)

BAD = []


def ok(name, cond):
    print(('OK   ' if cond else 'FAIL ') + name)
    if not cond:
        BAD.append(name)


Q = RE.frame_qa_mod()
RULES = Q.load_rules()

# ——— 1. что блокирует
CLEAN = {'verdict': 'ok', 'preflight': {'findings': []}, 'slots': [{'slot': 'диван#0', 'class': 'main', 'state': 'ok', 'level': 'ok', 'why': ''}], 'frame': []}
ok('чистый отчёт — не блокирует', Q.blocking(CLEAN, RULES) == [])
r1 = {**CLEAN, 'slots': [{'slot': 'лампа#0', 'class': 'lamp', 'state': 'missing', 'level': 'brak', 'why': 'нет'}]}
ok('слот «брак» — блокирует, с классом и слотом', [(b['where'], b['slot']) for b in Q.blocking(r1, RULES)] == [('slot', 'лампа#0')])
r2 = {**CLEAN, 'slots': [{'slot': 'шкаф#0', 'class': 'furniture', 'state': 'indeterminate', 'level': 'indeterminate', 'why': 'вплотную к камере'},
                         {'slot': 'подушка#0', 'class': 'pillow', 'state': 'missing', 'level': 'warn', 'why': 'нет'}]}
ok('«неопределимо» (вплотную к камере) и предупреждения — не блокируют', Q.blocking(r2, RULES) == [])
r3 = {**CLEAN, 'frame': [{'code': 'MAIN_NOT_VISIBLE', 'level': 'brak', 'why': 'ракурс без главного'}]}
ok('MAIN_NOT_VISIBLE не блокирует, даже если правила поставят ему уровень «брак»', Q.blocking(r3, RULES) == [])
r4 = {**CLEAN, 'frame': [{'code': 'CAMERA_MISMATCH', 'level': 'brak', 'why': 'камера не та'}]}
ok('CAMERA_MISMATCH — блокирует', [b['code'] for b in Q.blocking(r4, RULES)] == ['CAMERA_MISMATCH'])
r5 = {**CLEAN, 'preflight': {'findings': [{'level': 'error', 'code': 'NOT_IN_SCENE', 'slot': 'carrier:лампа#0', 'why': 'нет'}, {'level': 'warn', 'code': 'MESH_HASH', 'slot': 'x', 'why': ''}]}}
ok('ошибка предпроверки в отчёте — блокирует, предупреждение — нет', [(b['where'], b['code']) for b in Q.blocking(r5, RULES)] == [('preflight', 'NOT_IN_SCENE')])
full = {**r1, 'frame': r4['frame'], 'preflight': r5['preflight']}
ok('урезанный отчёт машины блокирует ровно то же, что полный', Q.blocking(Q.brief_report(full), RULES) == Q.blocking(full, RULES))
ok('урезанный отчёт — без «ok»-слотов', Q.brief_report(CLEAN)['slots'] == [])

# ——— 2. предпроверка на настоящем (маленьком) мире сцены
orig_pf = Q.preflight
Q.preflight = functools.partial(orig_pf, textile_path=None)      # пока подменим ниже по миру
w1 = os.path.join(TMP, 'w1')
tx1 = TF._mk_world(w1)
Q.preflight = functools.partial(orig_pf, textile_path=tx1)
ok('предпроверка: чистый мир — пусто', RE.qa_preflight_brak(os.path.join(w1, 'dump'), os.path.join(w1, 'scene')) == [])
w2 = os.path.join(TMP, 'w2')
tx2 = TF._mk_world(w2, drop_obj=True)
Q.preflight = functools.partial(orig_pf, textile_path=tx2)
bk = RE.qa_preflight_brak(os.path.join(w2, 'dump'), os.path.join(w2, 'scene'))
ok('предпроверка: диван пропал из собранной сцены — брак со слотом', any(b['slot'] == 'диван#0' and b['where'] == 'preflight' for b in bk))
Q.preflight = lambda *a, **k: (_ for _ in ()).throw(RuntimeError('сломана'))
ok('предпроверка сама сломалась — заказ не блокируется (молча терять заказы из-за сторожа нельзя)', RE.qa_preflight_brak('x', 'y') == [])
Q.preflight = functools.partial(orig_pf, textile_path=tx1)

# ——— 3. локальный исполнитель: подмена Blender пишет кадр и отчёт по режиму
fake = os.path.join(TMP, 'blender')
open(os.path.join(TMP, 'fake_bl.py'), 'w').write('''import json, os, sys
from PIL import Image
a = sys.argv
out = a[a.index('--out') + 1]
Image.new('RGB', (64, 48), (200, 190, 180)).save(out)
mode = os.environ.get('FAKE_QA_MODE', 'clean')
rep = {'verdict': 'ok', 'preflight': {'findings': []}, 'slots': [], 'frame': []}
if mode == 'brak':
    rep['slots'] = [{'slot': 'лампа#0', 'class': 'lamp', 'state': 'missing', 'level': 'brak', 'why': 'нет'}]
    rep['verdict'] = 'brak'
elif mode == 'main':
    rep['frame'] = [{'code': 'MAIN_NOT_VISIBLE', 'level': 'warn', 'why': 'ракурс без главного'}]
    rep['verdict'] = 'warn'
elif mode == 'near':
    rep['slots'] = [{'slot': 'шкаф#0', 'class': 'furniture', 'state': 'indeterminate', 'level': 'indeterminate', 'why': 'вплотную к камере'}]
    rep['verdict'] = 'indeterminate'
json.dump(rep, open(out + '.qa.json', 'w'))
open(os.environ['FAKE_CALLS'], 'a').write(os.path.basename(out) + '\\n')
''')
open(fake, 'w').write(f'#!/bin/sh\nexec {sys.executable} {os.path.join(TMP, "fake_bl.py")} "$@"\n')
os.chmod(fake, os.stat(fake).st_mode | stat.S_IXUSR)
fh = types.ModuleType('heavy_slot')
fh.heavy_slot = lambda *a, **k: contextlib.nullcontext({'waited_s': 0})      # общая очередь тяжёлых прогонов в тестах не нужна
sys.modules['heavy_slot'] = fh


class Cpu(RE.LocalCpuExecutor):
    world = None

    def __init__(self):
        super().__init__({'RENDER_WORK': os.path.join(TMP, 'rwork'), 'RENDER_BLENDER': fake})
        self.blender = fake

    def _prepare(self, snap, job, log, pr, progress, timing):
        progress('scene')
        shutil.copytree(os.path.join(Cpu.world, 'dump'), os.path.join(job, 'dump'))
        shutil.copytree(os.path.join(Cpu.world, 'scene'), os.path.join(job, 'scene'))
        timing['export'], timing['dump'] = 0.1, 0.1
        return os.path.join(job, 'dump')


def run_cpu(world, mode, gate=None, h='h1'):
    Cpu.world = world
    os.environ['FAKE_QA_MODE'] = mode
    if gate is None:
        os.environ.pop('RENDER_QA_GATE', None)
    else:
        os.environ['RENDER_QA_GATE'] = gate
    out = os.path.join(TMP, 'res', f'{h}-{mode}-{gate}')
    log = os.environ['FAKE_CALLS'] = os.path.join(TMP, 'blender-calls.log')
    if os.path.exists(log):
        os.remove(log)
    stages = []
    try:
        res = Cpu().render({'scene_hash': h * 64 if len(h) == 1 else (h + '0' * 64)[:64], 'v': 1, 'source': 'test'}, out, stages.append)
        err = None
    except RE.RenderError as e:
        res, err = None, e
    calls = open(log).read().split() if os.path.exists(log) else []
    return res, err, out, calls, stages


RE.preset = lambda _p=RE.preset: {**_p(), 'limits': {**_p()['limits'], 'blenderSecPerFrame': 60}}
Q.preflight = functools.partial(orig_pf, textile_path=tx1)
res, err, out, calls, st = run_cpu(w1, 'clean')
ok('чистый заказ проходит: пара кадров в кэше, оба кадра посчитаны', err is None and os.path.isfile(os.path.join(out, 'C1.jpg')) and os.path.isfile(os.path.join(out, 'C2.jpg')) and len(calls) == 2)
res, err, out, calls, st = run_cpu(w1, 'main', h='h2')
ok('MAIN_NOT_VISIBLE (предупреждение) не блокирует', err is None and os.path.isfile(os.path.join(out, 'C2.jpg')))
res, err, out, calls, st = run_cpu(w1, 'near', h='h3')
ok('«вплотную к камере» (неопределимо) не блокирует', err is None and os.path.isfile(os.path.join(out, 'C2.jpg')))
Q.preflight = functools.partial(orig_pf, textile_path=tx2)
res, err, out, calls, st = run_cpu(w2, 'clean', h='h4')
ok('инъекция в предпроверку: заказ НЕ рендерится (Blender не вызван ни разу), код render_brak, находка со слотом',
   isinstance(err, RE.RenderBrak) and err.code == 'render_brak' and calls == [] and any(b['slot'] == 'диван#0' for b in err.brak) and not os.path.exists(out))
ok('тексты покупателю — те же, что у обычной ошибки рендера (пара RU/EN, без новых надписей)', err.ru == 'Рендер не удался. Нажмите «Повторить».' and err.en == 'The render failed. Press "Retry".')
res, err, out, calls, st = run_cpu(w2, 'clean', gate='0', h='h5')
ok('RENDER_QA_GATE=0: тот же заказ идёт на рендер, как раньше', err is None and len(calls) == 2 and os.path.isfile(os.path.join(out, 'C1.jpg')))
Q.preflight = functools.partial(orig_pf, textile_path=tx1)
res, err, out, calls, st = run_cpu(w1, 'brak', h='h6')
ok('инъекция в кадр: брак на C1 — C2 не считается, пара не публикуется и не ложится в кэш',
   isinstance(err, RE.RenderBrak) and calls == ['C1.png'] and not os.path.exists(out) and any(b['cam'] == 'C1' and b['slot'] == 'лампа#0' for b in err.brak))
res, err, out, calls, st = run_cpu(w1, 'brak', gate='0', h='h7')
ok('RENDER_QA_GATE=0: брак кадра публикуется как раньше (отчёт пишется, кадр не блокируется)', err is None and os.path.isfile(os.path.join(out, 'C2.jpg')))

# ——— 4. машина рендера: отчёт в result.json, исполнитель решает до скачивания кадров
os.environ.pop('RENDER_QA_GATE', None)
rep_bad = Q.brief_report({'verdict': 'brak', 'slots': [{'slot': 'лампа#0', 'class': 'lamp', 'state': 'missing', 'level': 'brak', 'why': 'нет'}], 'frame': [], 'preflight': {'findings': []}})
ok('отчёт машины с браком C2 даёт находку с камерой C2', [(b['cam'], b['slot']) for b in RE.qa_frame_brak(rep_bad, 'C2')] == [('C2', 'лампа#0')])
ok('нет отчёта от машины (старый воркер) — не блокируем', RE.qa_frame_brak(None, 'C1') == [])
wd = os.path.join(TMP, 'wk')
os.makedirs(os.path.join(wd, 'tools', 'scout', 'cycles_probe'))
shutil.copy(os.path.join(PROBE, 'frame_qa.py'), os.path.join(wd, 'tools', 'scout', 'cycles_probe', 'frame_qa.py'))
for c, rep in (('C1', CLEAN), ('C2', full)):
    json.dump(rep, open(os.path.join(wd, f'{c}.png.qa.json'), 'w'))
import render_worker as RW  # noqa: E402
qa = RW.qa_reports(wd, 'png', ['C1', 'C2'])
ok('воркер: урезанные отчёты по кадрам попадают в result.json', set(qa) == {'C1', 'C2'} and qa['C1']['slots'] == [] and qa['C2']['slots'][0]['slot'] == 'лампа#0')
ok('воркер: нет отчёта у кадра — камеры в словаре нет', set(RW.qa_reports(wd, 'jpg', ['C1'])) == set())


class Stub:
    """Приёмник: кадры скачивать не должны, если отчёт машины — брак; задание убирается."""

    def __init__(self):
        self.gets, self.deleted = [], []

    def get_to(self, rel, dest):
        self.gets.append(rel)
        raise AssertionError('кадр скачан')

    def delete(self, rel):
        self.deleted.append(rel)


class StubMachine:
    def pulse(self, busy_s=0.0):
        pass


class Gpu(RE.SaladGpuExecutor):
    res = {'ok': True, 'frames': 'png', 'timing': {}, 'device': 'x'}
    sent = 0

    def __init__(self):
        super().__init__({'RENDER_WORK': os.path.join(TMP, 'rwork')}, sink=Stub(), machine=StubMachine(), sleep=lambda s: None)

    def gate(self):
        return {'executor': {'fmt2': False}}

    def _slot(self, label, pr):
        return contextlib.nullcontext({'waited_s': 0})

    def _prepare(self, snap, job, log, pr, progress, timing):
        shutil.copytree(os.path.join(Cpu.world, 'dump'), os.path.join(job, 'dump'))
        shutil.copytree(os.path.join(Cpu.world, 'scene'), os.path.join(job, 'scene'))
        return os.path.join(job, 'dump')

    def _send_fmt1(self, *a, **k):
        Gpu.sent += 1

    def _wait(self, *a, **k):
        return Gpu.res


os.environ.pop('RENDER_QA_GATE', None)
Cpu.world = w2
Q.preflight = functools.partial(orig_pf, textile_path=tx2)
g = Gpu()
try:
    g.render({'scene_hash': 'g' * 64, 'v': 1}, os.path.join(TMP, 'res', 'g1'), lambda s_: None)
    e_ = None
except RE.RenderBrak as e:
    e_ = e
ok('машина рендера: брак предпроверки — на машину ничего не отправлено (ни GPU, ни запасной), заказ отказан', e_ is not None and Gpu.sent == 0 and not g.sink().gets)
Cpu.world = w1
Q.preflight = functools.partial(orig_pf, textile_path=tx1)
Gpu.res = {'ok': True, 'frames': 'png', 'timing': {}, 'device': 'x', 'qa': {'C1': Q.brief_report(CLEAN), 'C2': rep_bad}}
g = Gpu()
try:
    g.render({'scene_hash': 'g' * 64, 'v': 1}, os.path.join(TMP, 'res', 'g2'), lambda s_: None)
    e_ = None
except RE.RenderBrak as e:
    e_ = e
ok('машина рендера: кадровый брак по отчёту C2 — кадры не скачаны, в кэш не положено, задание на машине убрано',
   e_ is not None and [(b['cam'], b['slot']) for b in e_.brak] == [('C2', 'лампа#0')] and not g.sink().gets and not os.path.exists(os.path.join(TMP, 'res', 'g2')) and g.sink().deleted)
Gpu.res = {'ok': True, 'frames': 'png', 'timing': {}, 'device': 'x'}
g = Gpu()
try:
    g.render({'scene_hash': 'g' * 64, 'v': 1}, os.path.join(TMP, 'res', 'g3'), lambda s_: None)
    e_ = 'дошло до скачивания'
except AssertionError:
    e_ = 'дошло до скачивания'
except RE.RenderBrak:
    e_ = 'заблокирован'
ok('машина рендера: отчёта нет (старый воркер) — не блокируем, идём к скачиванию кадров', e_ == 'дошло до скачивания')

# ——— 5. очередь заданий: статус, метка, повтор без рендера
st5 = RJ.RenderStore(os.path.join(TMP, 'jobs.json'), os.path.join(TMP, 'res5'))


class BrakEx:
    name = 'fake'

    def __init__(self):
        self.calls = 0

    def render(self, snap, out_dir, progress):
        self.calls += 1
        raise RE.RenderBrak([{'where': 'preflight', 'code': 'NOT_IN_SCENE', 'slot': 'carrier:лампа#0', 'why': 'нет'}], 'до рендера')


ex5 = BrakEx()
q5 = RJ.RenderQueue(st5, ex5)


def run_job(snap, key, warm=False):
    r = q5.submit(snap, key, warm=warm)
    jid = r['job']
    with st5.lock:
        st5.jobs[jid].update(status='running', started=time.time(), stage='scene', attempts=1)
    q5.run_one(jid)
    return jid


j1 = run_job({'scene_hash': 'a' * 64}, 'k-brak')
v = q5.view(j1)
ok('задание: статус error для страницы (тот же экран), код render_brak, тексты RU/EN, «Повторить»', v['status'] == 'error' and v['code'] == 'render_brak' and v['error'] and v['error_en'] and v['retry'] is True)
ok('в статусе страницы нет находок (только в журнале и в записи задания)', 'brak' not in v and st5.jobs[j1]['brak'][0]['slot'] == 'carrier:лампа#0')
ok('ключ помечен браком текущей версией сторожа', st5.brak_of('k-brak') is not None and ex5.calls == 1)
j2 = run_job({'scene_hash': 'a' * 64}, 'k-brak')
ok('«Повторить» того же ключа: отказ без вызова исполнителя (рендер на то же самое не жжём)', q5.view(j2)['code'] == 'render_brak' and ex5.calls == 1)
st5.brak['k-brak']['sig'] = 'старый-сторож'
ok('метка другой версии сторожа не действует — починили сторож, комнату считаем заново', st5.brak_of('k-brak') is None)
os.environ['RENDER_QA_GATE'] = '0'
st5.brak['k-brak']['sig'] = RE.qa_signature()
j3 = run_job({'scene_hash': 'a' * 64}, 'k-brak')
ok('RENDER_QA_GATE=0: метка не действует, заказ идёт исполнителю как раньше', ex5.calls == 2)
os.environ.pop('RENDER_QA_GATE', None)
st6 = RJ.RenderStore(os.path.join(TMP, 'jobs.json'), os.path.join(TMP, 'res5'))
st6.load()
ok('метка брака переживает перезапуск сервиса', 'k-brak' in st6.brak)

# ——— 6. заготовка: брак — отметка и строка в журнал, не по кругу
VERS = {'x': 1}


class Mach:
    def rules(self):
        return {'day_cap_usd': 100, 'price_usd_h': 1.0, 'prewarm': {'start_delay_s': 0, 'interval_s': 1, 'batch': 2, 'off_idle_s': 0}, 'executor': {}}

    def state(self):
        return {'desired': 'on', 'spent_usd': 0, 'spent_date': None}

    def turn_on(self, by):
        return ''

    def turn_off(self, by):
        return ''

    def set_note(self, t):
        pass


class WarmEx(BrakEx):
    def warm_ok(self):
        return True


st7 = RJ.RenderStore(os.path.join(TMP, 'jobs7.json'), os.path.join(TMP, 'res7'))
ex7 = WarmEx()
q7 = RJ.RenderQueue(st7, ex7)
q7.start()
log7 = []
key_of = lambda snap: RE.cache_key(snap['scene_hash'], VERS)  # noqa: E731
sc = [('комната-брак', {'scene_hash': 'b' * 64})]
pw = PW.Prewarmer(q7, ex7, VERS, Mach(), lambda snap: {}, scenes_fn=lambda pw_: sc, sleep=lambda s: time.sleep(0.01), log=log7.append)
import render_machine as RM  # noqa: E402
RM.price_usd_h = lambda rules: 1.0
RM.london_date = lambda now: 'd'
pw.spent_today = lambda: 0.0
s1 = pw.once()
calls1 = ex7.calls
ok('заготовка: комната дала брак — задание отказано, метка поставлена', calls1 == 1 and st7.brak_of(key_of(sc[0][1])) is not None)
ok('заготовка: строка в журнал с комнатой, классом и слотом', any('комната в браке сторожа' in l and 'NOT_IN_SCENE' in l and 'комната-брак' in l for l in log7))
s2 = pw.once()
s3 = pw.once()
ok('заготовка не зацикливается: повторные проходы не ставят комнату снова (исполнитель вызван один раз)', ex7.calls == calls1 == 1)
ok('статус заготовки считает комнаты в браке отдельно', s3.get('brak') == 1 and 'В браке сторожа' in s3.get('note', ''))
ok('строка про брак в журнале — один раз на ключ', sum('комната в браке сторожа' in l for l in log7) == 1)
q7.stop = True

shutil.rmtree(TMP, ignore_errors=True)
print('\nВСЕГО провалов:', len(BAD))
sys.exit(1 if BAD else 0)
