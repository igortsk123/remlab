#!/usr/bin/env python3
"""Обвязка сквозного прогона (T-20261121-169/4): синтетика — «этапы» это маленькие python-команды, пишущие свой check.json; настоящих этапов, Blender и платного не запускаем.
Запуск: python3 tools/scout/tests/test_paint_run_all.py"""
import json
import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'assets'))
import remlab_tmp  # noqa: E402
remlab_tmp.use('test_paint_run_all')
import paint_check as PC  # noqa: E402
import paint_run_all as RA  # noqa: E402
import paint_stage as PS  # noqa: E402

FAIL = 0
CR = PC.load_rules()
REAL = RA.load_rules()


def ok(cond, name):
    global FAIL
    print(('  ✓ ' if cond else '  ✗ ') + name)
    FAIL += 0 if cond else 1


def writer(stage, passed=True, rc=0, metric=None):
    """Команда-«этап»: пишет check.json (через общий писатель) и выходит с rc."""
    code = ('import sys,os\nsys.path.insert(0,%r)\nimport paint_stage as PS\nrun,sku=sys.argv[1],sys.argv[2]\n'
            'open(os.path.join(run,"calls.log"),"a").write(%r+"\\n")\n'
            'PS.write_check(PS.stage_dir(run,sku,%r),%r,sku,passed=%r,metric=%r,reason="" if %r else "не прошёл")\nsys.exit(%d)\n') % (
        os.path.join(HERE, '..'), stage, stage, stage, passed, metric or {'name': 'm', 'value': 1.0, 'threshold': 0.5, 'op': '>='}, passed, rc)
    return {'argv': [sys.executable, '-c', code, '{run}', '{sku}']}


def fake_rules(**over):
    st = {
        'a': {'produces': ['01-trellis'], 'needs': [], 'steps': [writer('01-trellis')]},
        'b': {'produces': ['02-prep'], 'needs': ['01-trellis'], 'steps': [writer('02-prep')]},
        'c': {'produces': ['03-parts'], 'needs': ['02-prep'], 'steps': [writer('03-parts')]},
        'd': {'produces': ['06-visible'], 'needs': ['03-parts'], 'steps': [writer('06-visible')]},
        'e': {'produces': ['07-fill'], 'needs': ['06-visible'], 'pending': 'не подключена', 'steps': []},
        'f': {'produces': ['08-material'], 'needs': ['07-fill'], 'steps': [writer('08-material')]},
        'z': {'produces': ['09-check'], 'needs': [], 'steps': [writer('09-check')]},
    }
    st.update(over)
    return {'heavy_slot': 'x', 'camera_stage': '04-camera', 'order': ['a', 'b', 'c', 'd', 'e', 'f', 'z'], 'stages': st}


def calls(run):
    p = os.path.join(run, 'calls.log')
    return open(p).read().split() if os.path.exists(p) else []


A = {'native': 'n.glb', 'photo': 'p.png', 'root': os.getcwd()}

# 1. порядок и гейт: пройденное идёт дальше; этап 7 не подключён → 08 заблокирован, 09 (без needs) всё равно запускается
with tempfile.TemporaryDirectory() as run:
    log = RA.execute(run, 's1', A, fake_rules(), CR)
    ok(calls(run) == ['01-trellis', '02-prep', '03-parts', '06-visible', '09-check'], 'порядок по `order`; 07 «не подключён», 08 не запускался, 09 запущен: ' + ' '.join(calls(run)))
    acts = {e['stage']: e['action'] for e in log['stages']}
    ok(acts['e'] == 'pending' and acts['f'] == 'blocked', 'этап без команды — pending, зависимый от него — blocked')
    ok(PS.read_check(os.path.join(run, 's1', '07-fill')) is None and PS.read_check(os.path.join(run, 's1', '08-material')) is None, 'заблокированный и неподключённый этапы check.json НЕ получают (этап 9 покажет «нет этапа»)')
    ok(os.path.exists(os.path.join(run, 's1', 'run_all.json')), 'журнал run_all.json записан')

# 2. жёсткий отказ блокирует зависимых, мягкий — нет
with tempfile.TemporaryDirectory() as run:
    r = fake_rules(b={'produces': ['02-prep'], 'needs': ['01-trellis'], 'steps': [writer('02-prep', passed=False, metric={'name': 'faces', 'value': 9, 'threshold': 5, 'op': '<=', 'ok': False})]})
    RA.execute(run, 's2', A, r, CR)
    ok(calls(run) == ['01-trellis', '02-prep', '09-check'], 'отказ 02 (жёсткий) → 03 и 06 не получили вход: ' + ' '.join(calls(run)))
with tempfile.TemporaryDirectory() as run:
    r = fake_rules(d={'produces': ['06-visible'], 'needs': ['03-parts'], 'steps': [writer('06-visible', passed=False, metric={'name': 'known_share', 'value': 0.1, 'threshold': 0.15, 'op': '>=', 'ok': False})]},
                   e={'produces': ['07-fill'], 'needs': ['06-visible'], 'steps': [writer('07-fill')]})
    RA.execute(run, 's3', A, r, CR)
    ok('07-fill' in calls(run) and '08-material' in calls(run), 'мягкий провал 06 (known_share) не блокирует 07 и 08')

# 3. повтор пропускает готовое, --force гонит заново
with tempfile.TemporaryDirectory() as run:
    RA.execute(run, 's4', A, fake_rules(), CR)
    n = len(calls(run))
    RA.execute(run, 's4', A, fake_rules(), CR)
    ok(len(calls(run)) == n, 'повтор: этапы с готовым check.json пропущены (новых вызовов нет)')
    RA.execute(run, 's4', dict(A, force=True), fake_rules(), CR)
    ok(len(calls(run)) > n + 3, '--force: этапы идут заново')

# 4. --only
with tempfile.TemporaryDirectory() as run:
    pl = RA.plan(run, 's5', A, fake_rules(), CR, ['a', 'z'])
    ok([i['stage'] for i in pl] == ['a', 'z'], '--only оставляет выбранные этапы')

# 5. план ничего не запускает
with tempfile.TemporaryDirectory() as run:
    RA.plan(run, 's6', A, fake_rules(), CR)
    ok(calls(run) == [] and not os.path.exists(os.path.join(run, 's6')), 'plan: ничего не выполнено и ничего не создано')

# 6. повтор шага при отказе (retry_extra) и остановка при ошибке шага
with tempfile.TemporaryDirectory() as run:
    code = 'import sys,os\nrun=sys.argv[1]\nflag=os.path.join(run,"flag")\nif "X" in sys.argv:\n    sys.exit(0)\nsys.exit(3)\n'
    r = fake_rules(a={'produces': ['01-trellis'], 'needs': [], 'steps': [{'argv': [sys.executable, '-c', code, '{run}'], 'retry_extra': ['X']}, writer('01-trellis')]})
    log = RA.execute(run, 's7', A, r, CR)
    e = log['stages'][0]
    ok(e['steps'][0]['rc'] == 0 and e['steps'][0].get('first_rc') == 3, 'шаг упал rc=3 → повтор с retry_extra прошёл')
    r = fake_rules(a={'produces': ['01-trellis'], 'needs': [], 'steps': [{'argv': [sys.executable, '-c', 'import sys;sys.exit(5)']}, writer('01-trellis')]})
    log = RA.execute(run + '/b', 's8', A, r, CR)
    ok(len(log['stages'][0]['steps']) == 1 and '01-trellis' not in calls(run + '/b'), 'шаг упал → следующие шаги этапа не идут, check.json нет → этап «нет»')

# 7. подстановки: пустые флаги выпадают, азимут камеры — только если этап 4 passed
ctx = RA.make_ctx('/r', 'k', {'native': 'n', 'photo': 'p', 'product_role': '', 'channels': '', 'root': '/x'}, REAL)
st = RA.resolve_steps(REAL['stages']['03'], ctx, {'cam_az_args': []})[1]['argv']
ok('--product-role' not in st and '--channels' not in st and '--cam-az' not in st, 'пустые тип/каналы и нет камеры → флагов в команде нет')
ctx = RA.make_ctx('/r', 'k', {'native': 'n', 'photo': 'p', 'product_role': 'комод', 'channels': 'legs', 'root': '/x'}, REAL)
st = RA.resolve_steps(REAL['stages']['03'], ctx, {'cam_az_args': ['--cam-az', '12.5']})[1]['argv']
ok(st[st.index('--product-role') + 1] == 'комод' and st[st.index('--channels') + 1] == 'legs' and st[-2:] == ['--cam-az', '12.5'], 'заданные тип, каналы и азимут стоят в команде')
with tempfile.TemporaryDirectory() as run:
    ok(RA.cam_az_args(run, 'k', CR, REAL) == [], 'нет check.json этапа 4 → азимута нет')
    d = PS.stage_dir(run, 'k', '04-camera')
    PS.write_check(d, '04-camera', 'k', passed=False, metric={'name': 'm', 'value': 0, 'threshold': 1, 'op': '>=', 'ok': False}, reason='x')
    json.dump({'camera': {'az': 33.0}}, open(os.path.join(run, 'k', 'pose.json'), 'w'))
    ok(RA.cam_az_args(run, 'k', CR, REAL) == [], 'этап 4 не passed → азимута нет (роли с фронтом воздержатся)')
    PS.write_check(d, '04-camera', 'k', passed=True, metric={'name': 'm', 'value': 1, 'threshold': 0.5, 'op': '>=', 'ok': True})
    ok(RA.cam_az_args(run, 'k', CR, REAL) == ['--cam-az', '33.0'], 'этап 4 passed → азимут из pose.json')
try:
    RA.resolve_steps({'steps': [{'argv': ['{нет_такого}']}]}, ctx)
    ok(False, 'неизвестная подстановка — ошибка')
except KeyError:
    ok(True, 'неизвестная подстановка — ошибка до запуска')

# 8. настоящие правила: целостность
names = set(REAL['stages'])
ok(set(REAL['order']) == names, 'order и stages совпадают')
prod = {p for s in REAL['stages'].values() for p in s['produces']}
ok(all(n in prod for s in REAL['stages'].values() for n in s.get('needs', [])), 'каждый needs — этап, который кто-то производит')
ok(set(CR['required_stages']) <= prod, 'обвязка производит все 8 этапов, которых ждёт этап 9')
pos = {p: i for i, n in enumerate(REAL['order']) for p in REAL['stages'][n]['produces']}
ok(all(pos[n] < pos[p] for nm in REAL['order'] for p in REAL['stages'][nm]['produces'] for n in REAL['stages'][nm].get('needs', [])), 'зависимость всегда раньше зависимого в порядке')
txt = open(os.path.join(HERE, '..', 'paint_run_all.py'), encoding='utf-8').read() + open(os.path.join(HERE, '..', 'rules', 'paint-run-all.json'), encoding='utf-8').read()
ok(not re.search(r'\b\d{9,}\b', txt), 'ID товаров в коде и правилах нет')
with tempfile.TemporaryDirectory() as run:
    pl = RA.plan(run, 'k', dict(A, product_role='комод'), REAL, CR)
    acts = {i['stage']: i['action'] for i in pl}
    ok(len(pl) == 8 and acts['07'] == 'pending' and acts['08'] == 'blocked' and acts['09'] == 'run' and acts['01-02'] == 'run', 'настоящий план строится без запуска: 07 не подключён → 08 заблокирован, 09 идёт')

print(f'paint_run_all: ошибок {FAIL}')
sys.exit(1 if FAIL else 0)
