"""Тесты НОЧНОГО ШАГА сторожа без рендера (`qa_night.py`, T-20261118-03/8): порядок и вердикты, брак по классам и слотам, дубль сцены, сбой сборки не роняет ночь, «снимок не принят» — своя строка,
потолок времени («не дошли»), память результатов (та же сцена и сторож — заново не собираем; сменился сторож — собираем), журнал пишется сразу, сводка и last.json, снимок тура по `pid`.
Без сети, Node и Chromium: сборка сцены — подмена, которая кладёт готовый мини-мир из `test_frame_qa._mk_world`.

Запуск: python tools/scout/render_gpu/tests_qa_night.py   (код 0 — чисто)"""
import contextlib
import functools
import io
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCOUT = os.path.abspath(os.path.join(HERE, '..'))
PROBE = os.path.join(SCOUT, 'cycles_probe')
TMP = tempfile.mkdtemp(prefix='qa-night-test-')
os.environ.update(RENDER_WORK=os.path.join(TMP, 'rwork'), RENDER_PREP_CACHE=os.path.join(TMP, 'prep'))
sys.path[:0] = [SCOUT, HERE, PROBE]
import qa_night as N  # noqa: E402
import render_exec as RE  # noqa: E402
import test_frame_qa as TF  # noqa: E402
import frame_qa as Q  # noqa: E402

BAD = []


def ok(name, cond):
    print(('OK   ' if cond else 'FAIL ') + name)
    if not cond:
        BAD.append(name)


# ——— миры: чистый, с потерей дивана в собранной сцене
WORLDS = {}
tx_by = {}
for name, kw in (('clean', {}), ('bad', {'drop_obj': True})):
    d = os.path.join(TMP, 'world-' + name)
    tx_by[d] = TF._mk_world(d, **kw)
    WORLDS[name] = d
orig_pf = Q.preflight


class QS:
    """Сторож с настоящей предпроверкой; путь к ткани — по миру, из которого собрана сцена."""
    load_rules = staticmethod(Q.load_rules)

    @staticmethod
    def preflight(dump, export, scene, rules=None):
        w = next(w for w in tx_by if dump.startswith(os.path.join(TMP, 'jobs')) and open(os.path.join(dump, '.world')).read() == w)
        return orig_pf(dump, export, scene, textile_path=tx_by[w], rules=rules)


class FakeEx:
    work = os.path.join(TMP, 'rwork')

    def __init__(self, clock=None, step=0.0):
        self.prepared, self.clock, self.step = [], clock, step

    def _prep_key(self, snap, bundle, pr):
        return 'pk-' + snap['scene_hash']

    def _bundle(self, log):
        return 'bundle'

    def _job_dir(self, prefix, snap):
        return os.path.join(TMP, 'jobs', prefix + snap['scene_hash'][:8])

    def _prepare(self, snap, job, log, pr, progress, timing):
        self.prepared.append(snap['scene_hash'])
        if self.clock:
            self.clock.t += self.step
        if snap.get('boom'):
            raise RE.RenderError('export_failed', 'ру', 'en')
        w = WORLDS[snap['world']]
        shutil.copytree(os.path.join(w, 'dump'), os.path.join(job, 'dump'))
        shutil.copytree(os.path.join(w, 'scene'), os.path.join(job, 'scene'))
        open(os.path.join(job, 'dump', '.world'), 'w').write(w)
        timing['prep_hit'] = 0
        return os.path.join(job, 'dump')


class Clock:
    t = 1_800_000_000.0

    def __call__(self):
        return self.t


@contextlib.contextmanager
def noslot(label, pr):
    yield {'waited_s': 0}


def snap(h, world='clean', **kw):
    return {'scene_hash': h * 64 if len(h) == 1 else (h + '0' * 64)[:64], 'world': world, **kw}


def night(ex, out, state=None, use_state=True, clock=None):
    return N.Night(ex, QS, Q.load_rules(), out, state if state is not None else {}, use_state, now=clock or Clock(), log=lambda *_: None, slot=noslot)


def rows(path):
    L = open(path, encoding='utf-8').read().splitlines()
    return [dict(zip(L[0].split('\t'), x.split('\t'))) for x in L[1:]]


PR = {'min_gb': 6}
RE.preset = lambda: PR

# ——— 1. порядок, вердикты, дубль, сбой, «не принят»
SC = [('demo', 'demo/set1', snap('a')), ('demo', 'demo/set4', snap('b', 'bad')), ('tour', 'tour:T1/set1', snap('a')),
      ('tour', 'tour:T1/bed', snap('c', boom=True)), ('tour', 'tour:T2/bed', snap('c', boom=True)), ('tour', 'tour:T1/bed2', snap('d'))]
REJ = [('tour', 'tour:T1/trial-living-2', 'bad_snapshot')]
out1 = os.path.join(TMP, 'o1')
ex = FakeEx()
n = night(ex, out1)
s = n.run(SC, 40, REJ)
R = rows(n.tsv)
v = [r['вердикт'] for r in R]
if os.environ.get('QA_DEBUG'):
    print(*[(r['метка'], r['вердикт'], r['брак (класс слот)'], r['предупреждения'], r['примечание']) for r in R], sep='\n')
ok('в журнале строка на каждую комнату, порядок «/demo → туры» сохранён', [r['метка'] for r in R][1:] == [x[1] for x in SC] and R[0]['вердикт'] == 'не принят')
ok('чистая комната — «чисто»; потеря дивана в сцене — «БРАК» с классом и слотом', v[1] == 'чисто' and v[2] == 'БРАК' and 'NOT_IN_SCENE' in R[2]['брак (класс слот)'] and 'диван#0' in R[2]['брак (класс слот)'])
ok('та же сцена в туре — «как <метка>» без второй сборки', R[3]['вердикт'] == 'чисто' and 'как demo/set1' in R[3]['примечание'] and ex.prepared.count(snap('a')['scene_hash']) == 1)
ok('сбой сборки — «не собрано» с причиной, ночь идёт дальше; дубль сбойной сцены пробует сам', R[4]['вердикт'] == 'не собрано' and 'RenderError' in R[4]['примечание'] and R[5]['вердикт'] == 'не собрано'
   and ex.prepared.count(snap('c')['scene_hash']) == 2 and R[6]['вердикт'] == 'чисто')
ok('снимок не принят — своя строка «не принят», а не «чисто»', R[0]['вердикт'] == 'не принят' and 'bad_snapshot' in R[0]['примечание'])
ok('каталоги заданий убраны после проверки', not os.path.isdir(os.path.join(TMP, 'jobs')) or not os.listdir(os.path.join(TMP, 'jobs')))
ok('сводка: счётчики и брак по классам со слотом и меткой', s['counts'] == {'не принят': 1, 'чисто': 3, 'БРАК': 1, 'не собрано': 2}
   and 'NOT_IN_SCENE' in s['by_code'] and 'demo/set4' in s['by_code']['NOT_IN_SCENE'][0] and s['brak'][0]['slot'] == 'диван#0')
buf = io.StringIO()
N.print_summary(s, lambda x: buf.write(x + '\n'))
ok('сводка в stdout: числа и строка по классу', 'БРАК 1' in buf.getvalue() and 'БРАК NOT_IN_SCENE: 1' in buf.getvalue() and 'снимок не принят 1' in buf.getvalue())

# ——— 2. память результатов
state: dict = {}
ex2 = FakeEx()
night(ex2, os.path.join(TMP, 'o2'), state).run(SC[:2], 40)
ok('результаты запомнены по ключу сцены и версии сторожа', len(state) == 2)
ex3 = FakeEx()
n3 = night(ex3, os.path.join(TMP, 'o3'), state)
n3.run(SC[:2], 40)
R3 = rows(n3.tsv)
ok('вторая ночь той же сценой и сторожем: сборки нет, вердикты из памяти (в том числе БРАК)', ex3.prepared == [] and [r['сборка'] for r in R3] == ['из памяти'] * 2 and R3[1]['вердикт'] == 'БРАК')
real_sig = RE.qa_signature
RE.qa_signature = lambda: 'другой-сторож'
ex4 = FakeEx()
night(ex4, os.path.join(TMP, 'o4'), state).run(SC[:2], 40)
RE.qa_signature = real_sig
ok('сменился сторож (подпись) — комнаты собираются и проверяются заново', len(ex4.prepared) == 2)
ex5 = FakeEx()
night(ex5, os.path.join(TMP, 'o5'), state, use_state=False).run(SC[:2], 40)
ok('--no-state: память не берём', len(ex5.prepared) == 2)

# ——— 3. потолок времени
clk = Clock()
ex6 = FakeEx(clk, 600.0)          # каждая сборка «длится» 10 мин
n6 = night(ex6, os.path.join(TMP, 'o6'), clock=clk)
many = [('demo' if i < 2 else 'tour', f'room{i}', snap(chr(ord('e') + i))) for i in range(6)]
s6 = n6.run(many, 15)
R6 = rows(n6.tsv)
ok('потолок 15 мин при 10 мин на комнату: сделаны две (после второй время вышло), остальные «не дошли»', [r['вердикт'] for r in R6] == ['чисто', 'чисто'] + ['не дошли'] * 4 and len(ex6.prepared) == 2)
ok('«не дошли» не считаются проверенными и не пишутся в память', s6['counts'].get('не дошли') == 4 and len(n6.state) == 2)
ok('журнал дописывается сразу: файл с шапкой и строками есть без финала', open(n6.tsv, encoding='utf-8').read().startswith('время\t'))

# ——— 4. main: правила (потолок — данные), last.json, коды выхода
out7 = os.path.join(TMP, 'o7')
os.environ['QA_NIGHT_STATE'] = os.path.join(TMP, 'st7.json')
N.STATE_FILE = os.environ['QA_NIGHT_STATE']
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    rc = N.main(['--out', out7], ex=FakeEx(), scenes_fn=lambda: (SC[:2], REJ), qa=QS, slot=noslot)
last = json.load(open(os.path.join(out7, 'last.json'), encoding='utf-8'))
ok('main: код 0, last.json с итогом и списком брака, состояние сохранено', rc == 0 and last['counts']['БРАК'] == 1 and last['brak'][0]['code'] == 'NOT_IN_SCENE' and os.path.isfile(N.STATE_FILE))
ok('потолок времени и охват туров — данные правил сторожа', Q.load_rules()['night']['maxMinutes'] > 0 and 'toursMax' in Q.load_rules()['night'] and last['max_minutes'] == Q.load_rules()['night']['maxMinutes'])
with contextlib.redirect_stdout(io.StringIO()):
    ok('нет комнат — код 2', N.main(['--out', out7], ex=FakeEx(), scenes_fn=lambda: ([], []), qa=QS) == 2)
    ok('--list ничего не собирает', N.main(['--list'], ex=FakeEx(), scenes_fn=lambda: (SC[:2], REJ), qa=QS) == 0)

# ——— 5. публичный бандл тура: заказ называет товар ключом `pid` (T-20261118-03/9), без подмен данных
import render_snapshot as RS  # noqa: E402
pa = 'p1:' + 'a' * 24
tour = {'apartment_id': 't', 'build': 'b', 'room': {'w': 400, 'd': 300}, 'rules': {}, 'rooms_geo': {}, 'variants': [{'id': 'tv', 'room_id': 'living', 'style': 'x', 'cams': [
    {'name': 'C1', 'x': 50, 'y': 40, 'rot': 105, 'fov': 90}, {'name': 'C2', 'x': 300, 'y': 200, 'rot': -69, 'fov': 90}], 'decor': [],
    'items': [{'role': 'ковёр', 'x': 200, 'y': 150, 'rot': 0, 'w': 230, 'd': 160, 'h': 1, 'sku': {'name': 'К', 'msid': None, 'pid': pa, 'w': 230, 'd': 160, 'h': 1}}]}]}
okk, badd = N.snaps(tour, 'tour', 'T')
ok('тур с `pid` (ковёр без msid и sid) — снимок принят как есть, без подмены `sid`', len(okk) == 1 and not badd)
old_tour = json.loads(json.dumps(tour))
del old_tour['variants'][0]['items'][0]['sku']['pid']
okk, badd = N.snaps(old_tour, 'tour', 'T')
ok('тур до `pid` (ковёр без ключа) — «не принят» (bad_item): живой дефект виден ночью, а не прячется', not okk and badd and badd[0][2] == 'bad_item')

shutil.rmtree(TMP, ignore_errors=True)
print('\nВСЕГО провалов:', len(BAD))
sys.exit(1 if BAD else 0)
