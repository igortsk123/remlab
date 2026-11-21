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

# 7б. входы по факту: фото камеры из extra.photo 04, фото для 6 — результат 05 или исходное; --body-only при bottom_shape_mismatch; допуск отказа 04 по этому флагу
def put(run, sku, stage, passed, metric=None, **extra):
    d = PS.stage_dir(run, sku, stage)
    PS.write_check(d, stage, sku, passed=passed, metric=metric or {'name': 'm', 'value': 1.0, 'threshold': 0.5, 'op': '>=', 'ok': passed}, reason='' if passed else 'не прошёл', **extra)
    return d


with tempfile.TemporaryDirectory() as run:
    ctx0 = RA.make_ctx(run, 'k', dict(A, photo='orig.png'), REAL)
    d = RA.dynamic_ctx(run, 'k', ctx0, REAL)
    ok(d['photo_cam'] == 'orig.png' and d['photo_vis'] == 'orig.png' and d['body_only_args'] == [], 'ничего ещё нет → фото исходное, --body-only нет')
    put(run, 'k', '04-camera', True, photo='cam.png')
    d = RA.dynamic_ctx(run, 'k', ctx0, REAL)
    ok(d['photo_cam'] == 'cam.png' and d['photo_vis'] == 'cam.png', 'фото камеры — extra.photo этапа 4; без этапа 5 фото для 6 то же')
    d5 = put(run, 'k', '05-delight', True, metric={'name': 'iid_shading_removed', 'value': 0.2, 'threshold': 0.5, 'op': '<=', 'ok': True, 'na': False})
    open(os.path.join(d5, 'delight.rgba.png'), 'wb').write(b'x')
    d = RA.dynamic_ctx(run, 'k', ctx0, REAL)
    ok(d['photo_vis'] == os.path.join(d5, 'delight.rgba.png'), '05 passed, не N/A, файл есть → этап 6 берёт снятое фото')
    put(run, 'k', '05-delight', True, metric={'name': 'iid_shading_removed', 'value': 0.9, 'threshold': 0.5, 'op': '<=', 'ok': None, 'na': True})
    ok(RA.dynamic_ctx(run, 'k', ctx0, REAL)['photo_vis'] == 'cam.png', '05 N/A → исходное фото камеры')
    put(run, 'k', '05-delight', False, metric={'name': 'iid_shading_removed', 'value': 0.9, 'threshold': 0.5, 'op': '<=', 'ok': False, 'na': False})
    ok(RA.dynamic_ctx(run, 'k', ctx0, REAL)['photo_vis'] == 'cam.png', '05 не прошёл (мягко) → исходное фото камеры')

with tempfile.TemporaryDirectory() as run:
    for stg in ('01-trellis', '02-prep'):
        put(run, 'k', stg, True)
    put(run, 'k', '04-camera', False, photo='cam.png', bottom_shape_mismatch=True)
    pl = {i['stage']: i for i in RA.plan(run, 'k', dict(A, photo='o.png'), REAL, CR)}
    ok(pl['05']['action'] == 'run', '04 отказ с bottom_shape_mismatch: 05 идёт (допуск отказа по флагу)')
    put(run, 'k', '05-delight', True, metric={'name': 'x', 'value': 1, 'threshold': 2, 'op': '<=', 'ok': True, 'na': True})
    pl = {i['stage']: i for i in RA.plan(run, 'k', dict(A, photo='o.png'), REAL, CR)}
    cmd = pl['06']['steps'][0]['argv']
    ok(pl['06']['action'] == 'run' and '--body-only' in cmd and 'cam.png' in cmd, '04 bottom_shape_mismatch + 05 готов → 06 с --body-only и фото камеры')
    put(run, 'k', '04-camera', False, photo='cam.png')
    pl = {i['stage']: i for i in RA.plan(run, 'k', dict(A, photo='o.png'), REAL, CR)}
    ok(pl['06']['action'] == 'blocked' and '04-camera' in pl['06']['why'], '04 отказ по иной причине → 05/06 заблокированы')

# 7в. каталог: тип и params — из записи; нет записи — этап 8 заблокирован, params не выдумываются
with tempfile.TemporaryDirectory() as run:
    cat = os.path.join(run, 'cat.json')
    json.dump([{'sid': 'k', 'name': 'Комод', 'role': 'комод', 'params': {'Материал фасада': 'МДФ'}}, {'sid': 'o', 'name': 'x', 'role': 'диван', 'params': {}}], open(cat, 'w'))
    rec = RA.product_record({'catalog': cat}, 'k')
    ok(rec == {'sid': 'k', 'name': 'Комод', 'role': 'комод', 'params': {'Материал фасада': 'МДФ'}}, 'запись товара из каталога по sid')
    ok(RA.product_record({'catalog': cat}, 'нет') is None and RA.product_record({}, 'k') is None, 'нет товара/каталога → None')
    ok(RA.make_ctx(run, 'k', dict(A, catalog=cat), REAL)['product_role'] == 'комод', 'тип товара берётся из каталога, если не задан')
    for stg in ('03-parts', '07-fill'):
        put(run, 'k', stg, True)
    pl = {i['stage']: i for i in RA.plan(run, 'k', dict(A, catalog=cat), REAL, CR)}
    ok(pl['08']['action'] == 'run' and list(pl['08']['files'].values())[0]['params'] == {'Материал фасада': 'МДФ'}, 'этап 8: product.json из записи каталога (params настоящие)')
    pl = {i['stage']: i for i in RA.plan(run, 'k', A, REAL, CR)}
    ok(pl['08']['action'] == 'blocked' and 'каталог' in pl['08']['why'], 'каталога нет → этап 8 заблокирован с понятной причиной')

# 7г. готовая форма: этапы 01–02 копируются из прогона готовой формы, не строятся; отказ у них или нет файла — блок
with tempfile.TemporaryDirectory() as base:
    prun, run = os.path.join(base, 'prep-run'), os.path.join(base, 'run')
    shapes = os.path.join(base, 'shapes')
    os.makedirs(shapes)
    open(os.path.join(shapes, 'k-n1024.glb'), 'wb').write(b'g')
    for stg in ('01-trellis', '02-prep'):
        put(prun, 'k', stg, True)
    open(os.path.join(prun, 'k', '02-prep', 'extra.txt'), 'w').write('x')
    aa = dict(A, native='', prep_dir=shapes, prep_run=prun)
    pl = {i['stage']: i for i in RA.plan(run, 'k', aa, REAL, CR)}
    ok(pl['01-02']['action'] == 'adopt' and not pl['01-02']['steps'], 'готовая форма: этап 01-02 — «adopt», команд построения нет')
    ok(RA.make_ctx(run, 'k', aa, REAL)['prep_glb'] == os.path.join(shapes, 'k-n1024.glb'), 'prep_glb — готовый файл формы, не work/')
    pl04 = pl['04']['steps'][0]['argv']
    ok(os.path.join(shapes, 'k-n1024.glb') in pl04, 'следующие этапы берут готовую форму')
    log = RA.execute(run, 'k', aa, dict(REAL, order=['01-02'], stages={'01-02': REAL['stages']['01-02']}), CR)
    ok(log['stages'][0]['action'] == 'adopt' and os.path.exists(os.path.join(run, 'k', '02-prep', 'extra.txt')) and PS.read_check(os.path.join(run, 'k', '02-prep')) is not None, 'execute: папки 01-trellis и 02-prep скопированы вместе с check.json')
    ok(log['stages'][0]['adopted_from'] == prun and log['stages'][0]['status'] == {'01-trellis': 'ok', '02-prep': 'ok'}, 'в журнале — откуда взято, статусы этапов')
    pl = {i['stage']: i for i in RA.plan(run, 'k', aa, REAL, CR)}
    ok(pl['01-02']['action'] == 'skip', 'повтор: этапы уже в run — пропуск')
    put(prun, 'z', '01-trellis', True)
    put(prun, 'z', '02-prep', False, metric={'name': 'faces', 'value': 9, 'threshold': 5, 'op': '<=', 'ok': False})
    open(os.path.join(shapes, 'z-n1024.glb'), 'wb').write(b'g')
    pl = {i['stage']: i for i in RA.plan(run, 'z', aa, REAL, CR)}
    ok(pl['01-02']['action'] == 'blocked' and '02-prep' in pl['01-02']['why'] and pl['04']['action'] == 'blocked', 'у готовой формы отказ 02 → блок, следующие этапы не идут')
    pl = {i['stage']: i for i in RA.plan(run, 'q', aa, REAL, CR)}
    ok(pl['01-02']['action'] == 'blocked' and 'нет файла формы' in pl['01-02']['why'], 'нет файла формы → блок с причиной')
    pl = {i['stage']: i for i in RA.plan(run, 'k2', dict(aa, prep_run=''), REAL, CR)}
    ok(pl['01-02']['action'] == 'blocked' and '--prep-run' in pl['01-02']['why'], 'не задан --prep-run → блок с причиной')

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
    ok(len(pl) == 8 and acts['07'] == 'run' and acts['08'] == 'blocked' and acts['09'] == 'run' and acts['01-02'] == 'run', 'настоящий план строится без запуска: 07 подключён; 08 без каталога заблокирован, 09 идёт')
    c07 = [i for i in pl if i['stage'] == '07'][0]['steps'][0]['argv']
    ok(c07[-4:] == ['tex_fill.py', 'run_stage', run, 'k'] or c07[-3:] == ['run_stage', run, 'k'], 'команда этапа 7: tex_fill.py run_stage <run> <sku>')

print(f'paint_run_all: ошибок {FAIL}')
sys.exit(1 if FAIL else 0)
