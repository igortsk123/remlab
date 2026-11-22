#!/usr/bin/env python3
"""Тесты ПРОБЫ SALAD «ЭТАПЫ 06/07» (T-189/1) и «КОД ЭТАПА В ЗАДАНИИ» (T-193/1/1) БЕЗ сети, денег и видеокарты: воркер на настоящем HTTP (поддельный запуск этапа), распаковка, лимит 07, драйвер, список файлов образа.
Запуск: python3 tools/scout/salad/stage/tests_stage.py   (в CI — внутри образа, `build-stage-trial.yml`)"""
from __future__ import annotations

import ast
import base64
import hashlib
import io
import json
import os
import subprocess
import sys
import tarfile
import threading
import time
import urllib.error
import urllib.request
import zipfile
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
SALAD = os.path.abspath(os.path.join(HERE, '..'))
SCOUT = os.path.abspath(os.path.join(HERE, '..', '..'))
ROOT = os.path.abspath(os.path.join(SCOUT, '..', '..'))
sys.path.insert(0, HERE)
sys.path.insert(0, SALAD)
sys.path.append(SCOUT)
import remlab_tmp  # noqa: E402  временное теста — на диске, папка убирается при выходе
TMP = remlab_tmp.use('tests_stage')
import code_tar as CT  # noqa: E402
import kit_driver as KD  # noqa: E402
import kit_worker as KW  # noqa: E402
import stage_stage_code as SSC  # noqa: E402
import stage_trial as ST  # noqa: E402
import worker_stage as WS  # noqa: E402

FAILS: list[str] = []


def ok(cond, msg):
    print(('ok   ' if cond else 'FAIL ') + msg)
    if not cond:
        FAILS.append(msg)


def mkzip(files: dict[str, bytes]) -> bytes:
    b = io.BytesIO()
    with zipfile.ZipFile(b, 'w') as z:
        for n, d in files.items():
            z.writestr(n, d)
    return b.getvalue()


def tmpdir(name: str) -> str:
    d = os.path.join(str(TMP) if TMP else '/tmp', name)
    os.makedirs(d, exist_ok=True)
    return d


# ---------------------------------------------------------------- распаковка
d = tmpdir('ex1')
ok(WS.safe_extract(mkzip({'a/b.txt': b'1', 'c.txt': b'2'}), d) == ['a/b.txt', 'c.txt'] and os.path.isfile(os.path.join(d, 'a', 'b.txt')), 'safe_extract: обычный архив распакован')
for bad in ('../x', '/etc/x', 'a/../../x', 'a\\b'):
    try:
        WS.safe_extract(mkzip({bad: b'x'}), tmpdir('ex2'))
        ok(False, f'safe_extract: имя {bad!r} должно быть отказом')
    except ValueError:
        ok(True, f'safe_extract: имя {bad!r} — отказ')
try:
    WS.safe_extract(mkzip({'a.bin': b'0' * 5000}), tmpdir('ex3'), limit=1000)
    ok(False, 'safe_extract: «бомба» должна быть отказом')
except ValueError:
    ok(True, 'safe_extract: распакованное больше лимита — отказ')

# ---------------------------------------------------------------- состав входа и команды
ok(WS.missing_inputs('06', list(WS.NEED_06)) == [] and WS.missing_inputs('06', ['model.glb']) != [], 'вход 06: полный набор проходит, неполный — список недостающего')
ok(WS.missing_inputs('07', list(WS.NEED_07)) == [] and '06-visible/visible.glb' in WS.missing_inputs('07', []), 'вход 07: visible.glb и check.json обязательны')
C = {'code': '/opt/scout-root', 'work': '/tmp/w', 'python': '/opt/venv/bin/python', 'procs': 4, 'fill_procs': 2, 'threads': 1, 'timeout': 900, 'allow_baked': True}   # запасной путь включён: старые тесты идут без code.tar
CS40 = 'a' * 40
cmd, out, nm = WS.stage_command(C, '06', '/tmp/w/j', 'sku1', True, False, '/tmp/w/j/peak')
ok(cmd[-5:] == ['/tmp/w/j/in/model.glb', '/tmp/w/j/in/photo.png', '/tmp/w/j/in/pose_run', '/tmp/w/j/out', 'sku1'] and '--body-only' in cmd and cmd[cmd.index('-I') + 1].endswith('tex_visible.py')
   and nm == '06-visible', 'команда 06: tex_visible.py -I, --body-only до позиционных, вход/выход по схеме')
cmd, out, nm = WS.stage_command(C, '07', '/tmp/w/j', 'sku1', False, False, '/tmp/w/j/peak')
ok(cmd[cmd.index('-I') + 1].endswith('tex_fill.py') and 'run_stage' in cmd and '--no-parts-npz' in cmd and '--visible' in cmd and nm == '07-fill', 'команда 07: tex_fill.py run_stage --visible … --no-parts-npz')
cmd, _o, _n = WS.stage_command(C, '07', '/tmp/w/j', 'sku1', False, True, '/tmp/w/j/peak')
ok('--parts-npz' in cmd and '--no-parts-npz' not in cmd, 'команда 07 с parts.npz: --parts-npz')


# ---------------------------------------------------------------- пул заданий с поддельным запуском этапа
class FakeProc:
    live = 0
    max_live = 0
    lock = threading.Lock()

    def __init__(self, cmd, stdout=None, stderr=None, cwd=None, env=None):
        self.cmd, self.n = cmd, 0
        i = cmd.index('-I')
        self.stage = '06' if cmd[i + 1].endswith('tex_visible.py') else '07'
        sku = cmd[-1] if self.stage == '06' else cmd[cmd.index('run_stage') + 2]
        outd = cmd[-2] if self.stage == '06' else cmd[cmd.index('run_stage') + 1]
        sd = os.path.join(outd, sku, '06-visible' if self.stage == '06' else '07-fill')
        os.makedirs(sd, exist_ok=True)
        passed = 'bad' not in sku
        json.dump({'passed': passed, 'reason': '' if passed else 'камера не годится', 'metric': {'name': 'x', 'value': 0.9}, 'seconds': 1.0}, open(os.path.join(sd, 'check.json'), 'w'))
        open(os.path.join(sd, 'out.bin'), 'wb').write(b'x' * 100)
        open(cmd[cmd.index('-c') + 2], 'w').write('2097152')                 # пик 2 ГБ (в КБ)
        self.rc = 1 if (self.stage == '06' and not passed) else (2 if 'crash' in sku else 0)
        with FakeProc.lock:
            FakeProc.live += 1
            FakeProc.max_live = max(FakeProc.max_live, FakeProc.live)

    def poll(self):
        self.n += 1
        if self.n < 4:
            return None
        with FakeProc.lock:
            if not getattr(self, 'done', False):
                FakeProc.live -= 1
                self.done = True
        return self.rc

    def kill(self):
        pass

    def wait(self):
        pass


def inputs_for(stage: str) -> bytes:
    if stage == '06':
        return mkzip({n: b'x' for n in WS.NEED_06})
    return mkzip({n: b'x' for n in WS.NEED_07})


def wait_done(pool: WS.Pool, ids: list[str], secs: float = 10.0) -> bool:
    t = time.time()
    while time.time() - t < secs:
        if all(pool.jobs[i]['status'] in ('done', 'failed') for i in ids):
            return True
        time.sleep(0.05)
    return False


st = KW.State()
cfgp = dict(C, work=tmpdir('work1'), fill_procs=2, procs=4)
pool = WS.Pool(st, cfgp, popen=FakeProc, sleep=lambda s: time.sleep(0.01))
ids = []
for k in range(6):
    jid = f'j07-{k}'
    pool.submit(jid, '07', f'sku{k}', inputs_for('07'), False, CS40)
    ids.append(jid)
ok(wait_done(pool, ids), 'пул: 6 заданий 07 закончились')
ok(FakeProc.max_live <= 2, f'пул: этапа 07 одновременно не больше fill_procs=2 (было {FakeProc.max_live})')
ok(all(pool.jobs[i]['status'] == 'done' for i in ids) and pool.peak.get('07') == 2.0, f'пул: все done, пик памяти 07 записан ({pool.peak})')
j = pool.jobs[ids[0]]
ok(j['sha256'] == hashlib.sha256(open(j['zip'], 'rb').read()).hexdigest() and 'check.json' in zipfile.ZipFile(j['zip']).namelist(), 'пул: sha256 результата сходится, в zip есть check.json')
pool.submit('j06-bad', '06', 'bad1', inputs_for('06'), False, CS40)
pool.submit('j06-ok', '06', 'ok1', inputs_for('06'), False, CS40)
pool.submit('j07-crash', '07', 'crash1', inputs_for('07'), False, CS40)
ok(wait_done(pool, ['j06-bad', 'j06-ok', 'j07-crash']), 'пул: 06 «не прошёл», 06 «прошёл», 07 «сбой» закончились')
ok(pool.jobs['j06-bad']['status'] == 'done' and pool.jobs['j06-bad']['metrics']['passed'] is False, 'пул: 06 с кодом 1 («этап не прошёл») — done с passed=false, не отказ воркера')
ok(pool.jobs['j06-ok']['metrics']['passed'] is True, 'пул: 06 прошёл — passed=true')
ok(pool.jobs['j07-crash']['status'] == 'failed' and 'rc=2' in (pool.jobs['j07-crash']['error'] or ''), 'пул: 07 с кодом 2 — failed с причиной')
ok(pool.submit('j06-ok', '06', 'ok1', inputs_for('06'), False, CS40) is pool.jobs['j06-ok'], 'пул: повтор того же job_id возвращает то же задание (дубля нет)')

# ---------------------------------------------------------------- настоящий HTTP (воркер на сокете)
st2 = KW.State()
st2.phase = 'ready'
pool2 = WS.Pool(st2, dict(C, work=tmpdir('work2')), popen=FakeProc, sleep=lambda s: time.sleep(0.01))
wd = KW.Watchdog(3600, 3600)
stop = threading.Event()
H = WS.make_handler(st2, pool2, wd, stop, {'numpy': 'x'})
srv = KW.make_server(0, H, host='127.0.0.1')
port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()


def http(method, path, body=None):
    req = urllib.request.Request(f'http://127.0.0.1:{port}{path}', data=None if body is None else json.dumps(body).encode(), method=method, headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if r.headers.get('Content-Type', '').startswith('application/json') else raw)
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, raw


def zbody(stage, sku, files, jid):
    return {'job_id': jid, 'stage': stage, 'sku': sku, 'code_sha': CS40, 'input_z': base64.b64encode(zlib.compress(mkzip(files))).decode()}


c, h = http('GET', '/health')
ok(c == 200 and h['procs'] == 4 and h['fill_procs'] == 2 and 'peak_stage_gb' in h and h['version'] == WS.VERSION, f'HTTP /health: процессы, лимит 07 и пик памяти в ответе ({h.get("version")})')
c, r = http('POST', '/jobs', zbody('06', 's1', {'model.glb': b'x'}, 'a-1'))
ok(c == 400 and 'нет файлов' in r['error'], 'HTTP POST: неполный вход 06 — 400 с перечнем недостающего')
c, r = http('POST', '/jobs', zbody('09', 's1', {'x': b'x'}, 'a-2'))
ok(c == 400, 'HTTP POST: неизвестный этап — 400')
c, r = http('POST', '/jobs', {'job_id': 'a-3', 'stage': '06', 'sku': 's', 'code_sha': CS40, 'input_z': 'не-base64!'})
ok(c == 400, 'HTTP POST: input_z не zlib/base64 — 400')
c, r = http('POST', '/jobs', zbody('06', 'sku-http', {n: b'x' for n in WS.NEED_06}, 'http-06'))
ok(c == 202, f'HTTP POST: полный вход 06 принят ({c})')
c2, r2 = http('POST', '/jobs', zbody('06', 'sku-http', {n: b'x' for n in WS.NEED_06}, 'http-06'))
ok(c2 == 202 and r2.get('repeat') is True, 'HTTP POST: повтор job_id — 202 repeat, без дубля')
ok(wait_done(pool2, ['http-06']), 'HTTP: задание закончилось')
c, v = http('GET', '/jobs/http-06')
ok(c == 200 and v['status'] == 'done' and v['peak_gb'] == 2.0 and v['sha256'], f'HTTP GET /jobs/<id>: done, пик памяти {v.get("peak_gb")} ГБ, sha256 есть')
c, data = http('GET', '/jobs/http-06/result')
ok(c == 200 and hashlib.sha256(data).hexdigest() == v['sha256'] and 'check.json' in zipfile.ZipFile(io.BytesIO(data)).namelist(), 'HTTP GET result: zip сходится по sha256')
ok(http('GET', '/jobs/net-takogo')[0] == 404, 'HTTP: чужой id — 404')
st2.phase = 'loading'
ok(http('POST', '/jobs', zbody('06', 's9', {n: b'x' for n in WS.NEED_06}, 'late'))[0] == 503, 'HTTP POST: нода не готова (фаза loading) — 503')
srv.shutdown()

# ---------------------------------------------------------------- драйвер
AUTH = {'x': 'y'}
body = ST.build_body('t-stage', 'ghcr.io/o/n@sha256:' + 'a' * 64, 'low', 'cls-1650', AUTH, 3600, 900, 4, 2, 1, 900, worker_z=None)
res = body['container']['resources']
prof = KD.resource_profile('cpu_stage')
ok(res['cpu'] == prof['cpu'] and res['memory'] == prof['memory_mb'] and body['container']['environment_variables']['STAGE_FILL_PROCS'] == '2', f'драйвер: ресурсы группы — из профиля cpu_stage ({res["cpu"]} ядер, {res["memory"]} МБ)')
for tier in ('batch', 'high'):
    try:
        ST.build_body('t-stage', 'ghcr.io/o/n@sha256:' + 'a' * 64, tier, 'cls', AUTH, 3600, 900, 4, 2, 1, 900)
        ok(False, f'драйвер: тариф {tier} должен быть отказом')
    except KD.ProfileRefused:
        ok(True, f'драйвер: тариф {tier} — отказ (правило владельца 22.11)')
ok(KD.worker_progress_refusal(ST.WORKER) == '', 'драйвер: воркер отдаёт ход задания в /health (begin_job/step)')
a = type('A', (), {'threads': 1})()
j1 = ST.job_id('06', 'a_b', b'123', a)
ok(j1 == ST.job_id('06', 'a_b', b'123', a) and j1 != ST.job_id('06', 'a_b', b'124', a) and j1 != ST.job_id('07', 'a_b', b'123', a) and '_' not in j1, 'драйвер: job_id идемпотентен, зависит от этапа и входа')

# пакет входа 06: все обязательные файлы на месте
pr = tmpdir('pose_run')
for n in WS.NEED_06:
    if n.startswith('pose_run/'):
        p = os.path.join(pr, n[len('pose_run/'):])
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, 'wb').write(b'x')
glb, photo = os.path.join(pr, '..', 'm.glb'), os.path.join(pr, '..', 'p.png')
open(glb, 'wb').write(b'glTF')
open(photo, 'wb').write(b'png')
inp = {'s1': {'glb': glb, 'photo': photo, 'pose_run': pr}}
ok(ST.input_problems(inp) == [], 'драйвер: входы на месте — проблем нет')
ok(WS.missing_inputs('06', zipfile.ZipFile(io.BytesIO(ST.input_zip_06(inp['s1']))).namelist()) == [], 'драйвер: zip входа 06 содержит всё, что требует воркер')
os.remove(os.path.join(pr, 'stage_loss.json'))
ok(any('stage_loss.json' in x for x in ST.input_problems(inp)), 'драйвер: нет stage_loss.json камеры — проблема до создания группы')


class FakeGW:
    def __init__(self, replies):
        self.replies = replies

    def call(self, method, path, timeout=30, raw=False, **kw):
        return self.replies[path]


zres = mkzip({'check.json': json.dumps({'passed': False}).encode(), 'visible.glb': b'g'})
good = {'status': 'done', 'sha256': hashlib.sha256(zres).hexdigest(), 'wall_s': 5, 'peak_gb': 1.0, 'metrics': {'passed': False}}
A = type('A', (), {'out': tmpdir('salad-out')})()
cur = {'key': '06', 'ids': {'s1': 'j1', 's2': 'j2', 's3': 'j3'}, 'skipped': {}, 'got': {}}
gw = FakeGW({'/jobs/j1': (200, good), '/jobs/j1/result': (200, zres), '/jobs/j2': (200, {'status': 'running'}), '/jobs/j3': (200, {'status': 'failed', 'error': 'x'})})
ok(ST.poll_stage(gw, A, cur, 0)[0] == 'running', 'poll: пока одно задание идёт — running')
gw.replies['/jobs/j2'] = (200, dict(good, sha256='0' * 64))
gw.replies['/jobs/j2/result'] = (200, zres)
st_, info = ST.poll_stage(gw, A, cur, 0)
ok(st_ == 'failed' and info['items']['s1']['status'] == 'done' and 'sha256' in info['items']['s2']['error'] and info['items']['s3']['status'] == 'failed', 'poll: sha256 не сошёлся и failed — отказы с причинами, passed=false не отказ')
ok(os.path.isfile(os.path.join(A.out, 's1', '06-visible', 'visible.glb')) and os.path.isfile(os.path.join(A.out, 'items-06.json')), 'poll: выход 06 лежит в <out>/<товар>/06-visible, items-06.json записан')

# ---------------------------------------------------------------- список файлов образа
files = SSC.read_list()
ok(all(os.path.isfile(os.path.join(ROOT, f)) for f in files), 'stage_files.txt: все файлы есть в репозитории')
dest = os.path.join(tmpdir('ctx'), 'code')
SSC.stage(ROOT, dest, files)
ok(all(os.path.isfile(os.path.join(dest, f)) for f in files) and not any('pycache' in f for f in files), 'stager: копия по списку, кэшей нет')
try:
    SSC.stage(ROOT, dest, files)
    ok(False, 'stager: непустая папка назначения — отказ')
except SystemExit:
    ok(True, 'stager: непустая папка назначения — отказ')

DIRS = [os.path.join(SCOUT, 'salad', 'trellis'), os.path.join(SCOUT, 'salad'), SCOUT]


def local_module(name: str) -> str | None:
    for dd in DIRS:
        p = os.path.join(dd, name + '.py')
        if os.path.exists(p):
            return os.path.relpath(p, ROOT)
    return None


def top_imports(path: str, deep: bool) -> set[str]:
    t = ast.parse(open(os.path.join(ROOT, path), encoding='utf-8').read())
    nodes = ast.walk(t) if deep else t.body
    out = set()

    def add(n):
        if isinstance(n, ast.Import):
            out.update(a.name.split('.')[0] for a in n.names)
        elif isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
            out.add(n.module.split('.')[0])

    for n in nodes:
        add(n)
        if not deep and isinstance(n, (ast.Try, ast.If)):
            for m in ast.walk(n):
                add(m)
    return out


DEEP = {'tools/scout/salad/trellis/tex_visible.py', 'tools/scout/salad/trellis/tex_fill.py', 'tools/scout/paint_stage.py', 'tools/scout/salad/trellis/tex_coverage.py', 'tools/scout/salad/recolor_lp.py'}
missing = set()
for f in [x for x in files if x.endswith('.py')]:
    for m in top_imports(f, f in DEEP):
        p = local_module(m)
        if p and p not in files:
            missing.add(f'{f} → {p}')
ok(not missing, f'stage_files.txt полон: каждый наш модуль, который импортируют файлы списка, тоже в списке ({sorted(missing)[:3]})')


# ---------------------------------------------------------------- сверка «локально / Salad»
try:
    import compare_stage as CS
    from PIL import Image
    d1, d2 = tmpdir('cmpL'), tmpdir('cmpS')
    Image.new('RGBA', (20, 10), (200, 100, 50, 255)).save(os.path.join(d1, 'a.png'))
    Image.new('RGBA', (20, 10), (200, 100, 50, 255)).save(os.path.join(d2, 'a.png'))
    Image.new('RGBA', (20, 10), (255, 100, 50, 255)).save(os.path.join(d2, 'b.png'))
    Image.new('RGBA', (20, 10), (200, 100, 50, 255)).save(os.path.join(d1, 'b.png'))
    Image.new('RGBA', (30, 10), (0, 0, 0, 255)).save(os.path.join(d2, 'c.png'))
    Image.new('RGBA', (20, 10), (0, 0, 0, 255)).save(os.path.join(d1, 'c.png'))
    ok(CS.png_diff(os.path.join(d1, 'a.png'), os.path.join(d2, 'a.png'))[0] == 0.0, 'сверка: одинаковые картинки — разница 0')
    v = CS.png_diff(os.path.join(d1, 'b.png'), os.path.join(d2, 'b.png'))[0]
    ok(abs(v - (55 / 255) / 3) < 1e-4, f'сверка: один канал на 55/255 — средняя разница {v:.4f}')
    ok(CS.png_diff(os.path.join(d1, 'c.png'), os.path.join(d2, 'c.png'))[0] is None, 'сверка: разный размер — отказ, не число')
    ok(CS.png_diff(os.path.join(d1, 'нет.png'), os.path.join(d2, 'a.png'))[0] is None, 'сверка: нет файла — отказ')
    ja, jb = os.path.join(d1, 'r.json'), os.path.join(d2, 'r.json')
    json.dump({'unpainted_after': 0, 'fallback_global': 1, 'seconds': 5, 'x': {'n': 3}}, open(ja, 'w'))
    json.dump({'unpainted_after': 0, 'fallback_global': 2, 'seconds': 9, 'x': {'n': 3}}, open(jb, 'w'))
    ok(CS.json_diffs(ja, jb) == ['fallback_global: 1 ≠ 2'], 'сверка: счётчики сравниваются, время счёта — нет')
except ImportError as exc:
    ok(False, f'сверка: не импортируется ({exc})')


# ---------------------------------------------------------------- режим «только 07 по готовому 06»
ok(ST.stages_of(type('A', (), {})()) == ['06', '07'] and ST.stages_of(type('A', (), {'stages': '07'})()) == ['07'], 'драйвер: этапы по умолчанию 06,07; «07» — только заливка')
try:
    ST.stages_of(type('A', (), {'stages': '09'})())
    ok(False, 'драйвер: неизвестный этап — отказ')
except ValueError:
    ok(True, 'драйвер: неизвестный этап в --stages — отказ')
vr = tmpdir('visroot')
for sku, full in (('skuA', True), ('skuB', True), ('skuC', False)):
    vd = os.path.join(vr, sku, '06-visible')
    os.makedirs(vd, exist_ok=True)
    open(os.path.join(vd, 'check.json'), 'w').write('{}')
    if full:
        open(os.path.join(vd, 'visible.glb'), 'wb').write(b'glTF')
open(os.path.join(vr, 'skuA.06.log'), 'w').write('x')
ok(sorted(ST.vis_inputs(vr)) == ['skuA', 'skuB'], 'vis_inputs: берёт только папки с visible.glb и check.json (файлы-логи и неполные — нет)')
ok(sorted(ST.vis_inputs(vr, 'skuB,skuZ')) == ['skuB'], 'vis_inputs: --skus сужает список')
cur07, why07 = ST.submit_stage(FakeGW({}), type('A', (), {'out': tmpdir('o7'), 'vis_root': vr, 'threads': 1})(), {'skuC': {}}, '07', 0.0)
ok(cur07 is None and 'нечего отправлять' in why07['detail'], 'submit 07: у товара нет visible.glb — не отправляется, причина в ответе')

# ================================================================= T-193/1/1: КОД ЭТАПА ЕДЕТ В ЗАДАНИИ
def run(cwd: str, *cmd: str) -> str:
    env = dict(os.environ, GIT_AUTHOR_NAME='t', GIT_AUTHOR_EMAIL='t@t', GIT_COMMITTER_NAME='t', GIT_COMMITTER_EMAIL='t@t', GIT_AUTHOR_DATE='2026-01-01T00:00:00', GIT_COMMITTER_DATE='2026-01-01T00:00:00')
    return subprocess.run(cmd, cwd=cwd, capture_output=True, check=True, env=env).stdout.decode().strip()


def commit_tree(repo: str, fl: dict[str, str], msg: str) -> str:
    for n, t in fl.items():
        p = os.path.join(repo, n)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, 'w', encoding='utf-8').write(t)
    run(repo, 'git', 'add', '-A')
    run(repo, 'git', 'commit', '-q', '-m', msg)
    return run(repo, 'git', 'rev-parse', 'HEAD')


TRE = 'tools/scout/salad/trellis'
repo = tmpdir('mini-repo')
run(repo, 'git', 'init', '-q')
FILES_A = {
    f'{TRE}/tex_visible.py': 'import json\nimport paint_stage\n\ndef frame():\n    import recolor_lp\n    return recolor_lp\n',
    f'{TRE}/tex_fill.py': 'import tex_coverage\nimport paint_stage\n',
    f'{TRE}/tex_coverage.py': 'X = 1\n',
    'tools/scout/paint_stage.py': 'import remlab_tmp\n\ndef late():\n    import mesh_render\n',
    'tools/scout/remlab_tmp.py': 'Y = 1\n',
    'tools/scout/mesh_render.py': 'Z = 1\n',
    'tools/scout/salad/recolor_lp.py': 'def render_unlit(glb, yaw, pitch, size):\n    pass\n',
    'tools/scout/salad/not_used.py': 'W = 1\n',
    'tools/scout/rules/tex-visible.json': '{"gate": 0.15}\n',
    'other/readme.txt': 'не должно попасть в срез\n',
}
sha_a = commit_tree(repo, FILES_A, 'A')
sha_b = commit_tree(repo, {'tools/scout/rules/tex-visible.json': '{"gate": 0.10}\n'}, 'B — другое число в правилах')
ra, ra2, rb = CT.build(repo, sha_a), CT.build(repo, sha_a), CT.build(repo, sha_b)
ok(ra['sha'] == sha_a and len(sha_a) == 40, 'срез: SHA коммита из ref')
ok(ra['tar_sha256'] == ra2['tar_sha256'] and ra['tar'] == ra2['tar'], 'срез: один SHA → побайтно один tar (детерминирован)')
ok(ra['tar_sha256'] != rb['tar_sha256'] and ra['sha'] != rb['sha'], 'срез: другой SHA (другое число в правилах) → другой sha256 tar')
ok(set(ra['files']) >= {f'{TRE}/tex_visible.py', f'{TRE}/tex_fill.py', 'tools/scout/paint_stage.py', 'tools/scout/remlab_tmp.py', 'tools/scout/salad/recolor_lp.py', 'tools/scout/rules/tex-visible.json'},
   f'срез: код этапов, правила и замыкание импортов (в т.ч. отложенный `import recolor_lp` внутри функции этапа) на месте ({ra["outside"]})')
ok('tools/scout/salad/not_used.py' not in ra['files'] and 'other/readme.txt' not in ra['files'], 'срез: неиспользуемое и чужие папки в срез не тянутся')
ok('tools/scout/mesh_render.py' in ra['files'], 'срез: отложенный импорт внутри FULL_EXTRA-модуля (paint_stage) учтён')
dd = tmpdir('mini-untar')
names = WS.safe_untar(ra['tar'], dd)
ok(sorted(names) == ra['files'] and all(n.startswith('tools/') for n in names), 'срез: проходит безопасную распаковку воркера, все пути под tools/')
repo2 = tmpdir('mini-repo2')
run(repo2, 'git', 'init', '-q')
commit_tree(repo2, {f'{TRE}/tex_fill.py': 'X = 1\n', 'tools/scout/rules/a.json': '{}\n'}, 'без tex_visible')
try:
    CT.build(repo2, 'HEAD')
    ok(False, 'срез: нет обязательной точки входа (tex_visible) — отказ')
except CT.CodeTarError as exc:
    ok('tex_visible' in str(exc), 'срез: нет обязательной точки входа (tex_visible) — отказ с причиной')
try:
    CT.build(repo, 'нет-такого-коммита')
    ok(False, 'срез: неизвестный SHA — отказ')
except CT.CodeTarError:
    ok(True, 'срез: неизвестный SHA/ветка — отказ')
ok(CT.selfcheck(ra['tar'], ra['entries']) == '', 'срез: точки входа импортируются из ЧИСТОЙ распаковки (python -I)')
bad_tar = io.BytesIO()
with tarfile.open(fileobj=bad_tar, mode='w') as tf, tarfile.open(fileobj=io.BytesIO(ra['tar'])) as src:
    for m in src.getmembers():
        if m.isreg() and m.name != 'tools/scout/paint_stage.py':
            tf.addfile(m, src.extractfile(m))
        elif m.isdir():
            tf.addfile(m)
ok('paint_stage' in CT.selfcheck(bad_tar.getvalue(), ra['entries']), 'срез: неполный (нет paint_stage) — selfcheck отказывает ДО платной группы')
try:
    real = CT.build(ROOT, 'HEAD')
    ok({f'{TRE}/tex_visible.py', f'{TRE}/tex_fill.py', 'tools/scout/paint_stage.py'} <= set(real['files']) and len(real['tar']) < 20 * 2 ** 20, f'срез HEAD: этапы 06/07 на месте, tar {len(real["tar"]) / 1024:.0f} КБ, файлов {len(real["files"])}')
    miss = {f for f in files if f.endswith('.py') and f not in real['files']}
    ok(not miss, f'срез HEAD: все .py из stage_files.txt (замыкание образа) входят и в срез кода ({sorted(miss)[:3]})')
except CT.CodeTarError as exc:
    ok(False, f'срез HEAD не собран: {exc}')


def mktar(members: list) -> bytes:
    b = io.BytesIO()
    with tarfile.open(fileobj=b, mode='w') as tf:
        for n, data, kind in members:
            ti = tarfile.TarInfo(n)
            if kind == 'file':
                ti.size = len(data)
                tf.addfile(ti, io.BytesIO(data))
            elif kind == 'link':
                ti.type, ti.linkname = tarfile.SYMTYPE, '/etc/passwd'
                tf.addfile(ti)
            elif kind == 'dev':
                ti.type = tarfile.CHRTYPE
                tf.addfile(ti)
    return b.getvalue()


for nm, mem in (('«..»', [('tools/../x.py', b'x', 'file')]), ('абсолютный путь', [('/etc/x.py', b'x', 'file')]), ('путь вне tools', [('other/x.py', b'x', 'file')]),
                ('ссылка', [('tools/l', None, 'link')]), ('устройство', [('tools/dev', None, 'dev')])):
    try:
        WS.safe_untar(mktar(mem), tmpdir('ut'))
        ok(False, f'safe_untar: {nm} — отказ')
    except ValueError:
        ok(True, f'safe_untar: {nm} — отказ')
try:
    WS.safe_untar(mktar([('tools/big.bin', b'0' * 5000, 'file')]), tmpdir('ut2'), limit=1000)
    ok(False, 'safe_untar: «бомба» — отказ')
except ValueError:
    ok(True, 'safe_untar: больше лимита — отказ')
try:
    WS.safe_untar('это не tar'.encode(), tmpdir('ut3'))
    ok(False, 'safe_untar: не tar — отказ')
except ValueError:
    ok(True, 'safe_untar: не tar — отказ')

# ---- whitelist команд и аргументы
ok(set(WS.COMMANDS) == {'06', '07', 'ref_zone', 'render_unlit', 'pose_job'}, f'whitelist: ровно 5 команд ({sorted(WS.COMMANDS)})')
good_args = ['--zones', '@in/zones.npy', '--n', '3', '0.5', '@out']
ok(WS.check_args(good_args) == good_args and WS.check_args(None) == [], 'args: флаги, слова, числа, @in/…, @out — принимаются')
for bad in (['; rm -rf /'], ['$HOME'], ['../x'], ['/etc/passwd'], ['--Bad'], ['@in/../x'], ['a b'], ['`id`'], ['@in//x'], [1], ['x'] * 41, 'строка'):
    try:
        WS.check_args(bad)
        ok(False, f'args: {str(bad)[:30]!r} — отказ')
    except ValueError:
        ok(True, f'args: {str(bad)[:30]!r} — отказ')
cmd_r, out_r, nm_r = WS.stage_command(C, 'render_unlit', '/tmp/w/j', 'sku1', False, False, '/tmp/w/j/peak', code_root='/tmp/w/j/code', args=['--yaw', '12'])
ok(cmd_r[cmd_r.index('-I') + 1] == '-c' and '/tmp/w/j/code' in cmd_r and cmd_r[-2:] == ['--yaw', '12'] and nm_r == '', 'команда render_unlit: встроенная обёртка из кода задания, args в конце')
cmd_z, _o, _n = WS.stage_command(C, 'ref_zone', '/tmp/w/j', 'sku1', False, False, '/tmp/w/j/peak', code_root='/tmp/w/j/code', args=['--zones', '/x'])
ok(cmd_z[cmd_z.index('-I') + 1] == '/tmp/w/j/code/tools/scout/salad/trellis/ref_zone.py' and cmd_z[-2:] == ['--zones', '/x'], 'команда ref_zone: скрипт из code_root задания, args в конце')
cmd_p, out_p, nm_p = WS.stage_command(C, 'pose_job', '/tmp/w/j', 'sku1', False, False, '/tmp/w/j/peak', code_root='/tmp/w/j/code', args=['--glb', '/g.glb', '--device', 'cuda'])
ok(cmd_p[cmd_p.index('-I') + 1] == '/tmp/w/j/code/tools/scout/salad/trellis/pose_job.py' and cmd_p[-4:] == ['--glb', '/g.glb', '--device', 'cuda'] and nm_p == '' and out_p == '/tmp/w/j/out',
   'команда pose_job (этап 04, T-185/1): скрипт из code_root задания, args в конце, выход — вся папка out')
ok(WS.check_args(['--glb', '@in/model.glb', '--photo', '@in/photo.png', '--out-run', '@out', '--device', 'cuda']) and WS.missing_inputs('pose_job', ['code.tar']) == ['model.glb', 'photo.png'],
   'pose_job: args проходят проверку, без model.glb/photo.png вход неполный')
cmd07, _o, _n = WS.stage_command(C, '07', '/tmp/w/j', 'sku1', False, False, '/tmp/w/j/peak', code_root='/tmp/w/j/code')
ok(cmd07[cmd07.index('-I') + 1] == '/tmp/w/j/code/tools/scout/salad/trellis/tex_fill.py', 'команда 07: скрипт берётся из code_root задания, не из образа')

# ---- пул: код только из задания
C2 = dict(C, work=tmpdir('work3'), allow_baked=False)
seen_cmds: list = []


class FakeProc2(FakeProc):
    def __init__(self, cmd, stdout=None, stderr=None, cwd=None, env=None):
        seen_cmds.append(cmd)
        super().__init__(cmd, stdout, stderr, cwd, env)


pool3 = WS.Pool(KW.State(), C2, popen=FakeProc2, sleep=lambda s: time.sleep(0.01))
vis_files = {n: b'x' for n in WS.NEED_07}
with_code = dict(vis_files, **{'code.tar': ra['tar'], 'zones/z1.npy': b'z'})
cases = (('без code.tar (запасной путь выключен)', dict(files=mkzip(vis_files), code_sha=sha_a, tsha='')),
         ('без code_sha', dict(files=mkzip(with_code), code_sha='', tsha=ra['tar_sha256'])),
         ('code_sha не 40 hex', dict(files=mkzip(with_code), code_sha='abc', tsha=ra['tar_sha256'])),
         ('sha256 tar не совпал', dict(files=mkzip(with_code), code_sha=sha_a, tsha='0' * 64)),
         ('sha256 tar не указан', dict(files=mkzip(with_code), code_sha=sha_a, tsha='')),
         ('args с «;»', dict(files=mkzip(with_code), code_sha=sha_a, tsha=ra['tar_sha256'], args=['; id'])),
         ('args на файл, которого нет во входе', dict(files=mkzip(with_code), code_sha=sha_a, tsha=ra['tar_sha256'], args=['--zones', '@in/нет.npy'])))
for k, (nm, kw) in enumerate(cases):
    try:
        pool3.submit(f'bad-{k}', '07', 'sk', kw['files'], False, kw['code_sha'], kw['tsha'], kw.get('args'))
        ok(False, f'пул: {nm} — отказ')
    except ValueError:
        ok(True, f'пул: {nm} — отказ')
try:
    pool3.submit('bad-cmd', 'rm', 'sk', mkzip(with_code), False, sha_a, ra['tar_sha256'])
    ok(False, 'пул: команда вне whitelist — отказ')
except ValueError as exc:
    ok('whitelist' in str(exc), 'пул: команда вне whitelist — отказ')
ok(not any(i.startswith('bad-') for i in pool3.jobs), 'пул: отказанные задания в очередь не попали')
pool3.submit('code-07', '07', 'skuc', mkzip(with_code), False, sha_a, ra['tar_sha256'], ['--zones', '@in/zones/z1.npy', '--k', '3'])
ok(wait_done(pool3, ['code-07']) and pool3.jobs['code-07']['status'] == 'done', f'пул: 07 с code.tar принят и посчитан ({pool3.jobs["code-07"].get("error")})')
cm = seen_cmds[-1]
jd = os.path.join(C2['work'], 'code-07')
ok(cm[cm.index('-I') + 1] == f'{jd}/code/tools/scout/salad/trellis/tex_fill.py' and cm[-4:-2] == ['--zones', f'{jd}/in/zones/z1.npy'] and cm[-2:] == ['--k', '3'],
   'пул: скрипт этапа — из `<задание>/code`, доп. вход `@in/…` раскрыт в путь входа, args в конце команды')
v3 = pool3.view('code-07')
ok(v3['code_sha'] == sha_a and v3['code_tar_sha256'] == ra['tar_sha256'] and v3['cmd'] == 'tex_fill', 'пул: в ответе задания — code_sha, sha256 tar и команда')
zr = zipfile.ZipFile(pool3.jobs['code-07']['zip'])
meta = json.loads(zr.read('_code.json'))
ok(meta['code_sha'] == sha_a and meta['code_tar_sha256'] == ra['tar_sha256'] and meta['cmd'] == 'tex_fill' and 'check.json' in str(zr.namelist()), 'результат: `_code.json` с SHA кода и sha256 tar рядом с файлами этапа')
ok(not any(os.path.exists(os.path.join(jd, x)) for x in ('in', 'code', 'out')) and os.path.isfile(os.path.join(jd, 'stage.log')),
   'чистка: после задания на ноде in/, code/, out/ убраны, остаётся журнал этапа')
pool3.submit('code-07b', '07', 'skuc', mkzip(dict(vis_files, **{'code.tar': rb['tar']})), False, sha_b, rb['tar_sha256'])
ok(wait_done(pool3, ['code-07b']) and pool3.view('code-07b')['code_sha'] == sha_b != v3['code_sha'], 'пул: другой SHA кода — другой code_sha в ответе')
pool_baked = WS.Pool(KW.State(), dict(C, work=tmpdir('work4'), allow_baked=True), popen=FakeProc2, sleep=lambda s: time.sleep(0.01))
pool_baked.submit('baked-07', '07', 'skub', mkzip(vis_files), False, sha_a)
ok(wait_done(pool_baked, ['baked-07']) and pool_baked.view('baked-07')['code_tar_sha256'] == '', 'запасной путь (код образа) — только при STAGE_ALLOW_BAKED=1, sha256 tar в ответе пуст')

# ---- HTTP: тело POST
st4 = KW.State()
st4.phase = 'ready'
pool4 = WS.Pool(st4, dict(C2, work=tmpdir('work5')), popen=FakeProc2, sleep=lambda s: time.sleep(0.01))
H4 = WS.make_handler(st4, pool4, KW.Watchdog(3600, 3600), threading.Event(), {'numpy': 'x'})
srv4 = KW.make_server(0, H4, host='127.0.0.1')
port4 = srv4.server_address[1]
threading.Thread(target=srv4.serve_forever, daemon=True).start()


def http4(body):
    req = urllib.request.Request(f'http://127.0.0.1:{port4}/jobs', data=json.dumps(body).encode(), method='POST', headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def zb(stage, fl, sha=sha_a, tsha=ra['tar_sha256'], jid='h-1', **extra):
    b = {'job_id': jid, 'stage': stage, 'sku': 's', 'input_z': base64.b64encode(zlib.compress(mkzip(fl))).decode(), 'code_tar_sha256': tsha}
    if sha is not None:
        b['code_sha'] = sha
    return dict(b, **extra)


c4, r4 = http4(zb('rm -rf', with_code))
ok(c4 == 400 and 'whitelist' in r4['error'], 'HTTP: команда вне whitelist — 400')
c4, r4 = http4(zb('07', with_code, sha=None, jid='h-2'))
ok(c4 == 400 and 'code_sha' in r4['error'], 'HTTP: нет code_sha — 400')
c4, r4 = http4(zb('07', with_code, tsha='1' * 64, jid='h-3'))
ok(c4 == 400 and 'sha256' in r4['error'], 'HTTP: sha256 tar не совпал — 400')
c4, r4 = http4(zb('07', vis_files, jid='h-4'))
ok(c4 == 400 and 'code.tar' in r4['error'], 'HTTP: нет code.tar при выключенном запасном пути — 400')
c4, r4 = http4(zb('07', with_code, jid='h-5', args=['; id']))
ok(c4 == 400 and 'args' in r4['error'], 'HTTP: недопустимые args — 400')
c4, r4 = http4(zb('render_unlit', {'code.tar': ra['tar']}, jid='h-6'))
ok(c4 == 400 and 'нет файлов' in r4['error'], 'HTTP: render_unlit без model.glb — 400 с перечнем недостающего')
c4, r4 = http4(zb('pose_job', {'code.tar': ra['tar']}, jid='h-6p'))
ok(c4 == 400 and 'нет файлов' in r4['error'], 'HTTP: pose_job без model.glb/photo.png — 400 с перечнем недостающего')
c4, r4 = http4(zb('07', with_code, jid='h-7'))
ok(c4 == 202, f'HTTP: 07 с code.tar и code_sha принят ({c4}, {r4})')
ok(wait_done(pool4, ['h-7']), 'HTTP: задание с кодом из входа закончилось')
srv4.shutdown()

print()
print('ПРОВАЛЕНО: ' + str(len(FAILS)) if FAILS else 'ВСЕ ТЕСТЫ ЗЕЛЁНЫЕ')
sys.exit(1 if FAILS else 0)
