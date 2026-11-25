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
photo_x = os.path.join(pr, '..', 'px.png')                                            # фото 07 из extra_in — другое, чем фото 06
open(photo_x, 'wb').write(b'other-png')
zdup = zipfile.ZipFile(io.BytesIO(ST.input_zip_06(dict(inp['s1'], extra_in={'photo.png': photo_x, 'card.json': glb}))))
ok(zdup.namelist().count('photo.png') == 1 and zdup.read('photo.png') == b'png' and 'card.json' in zdup.namelist(), 'драйвер: фото 06 не дублируется доп. файлом photo.png (в zip одна запись, своё фото 06), прочие extra_in едут')
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
dups = sorted({f for f in files if files.count(f) > 1})
ok(not dups, f'stage_files.txt: нет повторов строк ({dups[:3]})')
dest = os.path.join(tmpdir('ctx'), 'code')
SSC.stage(ROOT, dest, files)
ok(all(os.path.isfile(os.path.join(dest, f)) for f in files) and not any('pycache' in f for f in files), 'stager: копия по списку, кэшей нет')
try:
    SSC.stage(ROOT, dest, files)
    ok(False, 'stager: непустая папка назначения — отказ')
except SystemExit:
    ok(True, 'stager: непустая папка назначения — отказ')

DIRS = [os.path.join(SCOUT, 'salad', 'trellis'), os.path.join(SCOUT, 'salad'), SCOUT, os.path.join(ROOT, 'tools', 'assets')]   # + tools/assets: части граней (tex_fill импортирует их внутри функции) — T-193/3


def local_module(name: str, importer: str | None = None) -> str | None:
    for dd in ((os.path.join(ROOT, os.path.dirname(importer)),) if importer else ()) + tuple(DIRS):          # как у Python: сперва каталог самого файла (как code_tar.closure)
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


DEEP = {'tools/scout/salad/trellis/tex_visible.py', 'tools/scout/salad/trellis/tex_fill.py', 'tools/scout/paint_stage.py', 'tools/scout/salad/trellis/tex_coverage.py', 'tools/scout/salad/recolor_lp.py',
        'tools/assets/material_parts.py', 'tools/assets/parts_refine.py', 'tools/assets/parts_vote.py'}      # глубокий разбор (импорты внутри функций и try): parts_refine импортирует parts_vote внутри функции
missing = set()
for f in [x for x in files if x.endswith('.py')]:
    for m in top_imports(f, f in DEEP):
        p = local_module(m, f)
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


# T-20261123-04/1: шлюз 503 на POST /jobs при живой ноде — повтор с паузами внутри post_job, затем отказ с причиной gateway_503 (проба не падает целиком)
class Gw503:
    def __init__(self, posts):
        self.posts, self.n_post, self.counters = list(posts), 0, {}

    def call(self, method, path, body=None, timeout=30, raw=False):
        if method == 'POST':
            self.n_post += 1
            return (self.posts.pop(0) if self.posts else 503), {}
        return (200, {}) if path == '/health' else (404, {})


_orig_post_job = ST.KD.post_job
ST.KD.post_job = lambda *a, **k: _orig_post_job(*a, **k, sleep=lambda s: None)              # паузы — без реального ожидания
try:
    A07 = type('A', (), {'out': tmpdir('o7b'), 'vis_root': vr, 'threads': 1})()
    g503 = Gw503([503, 503, 202])
    cur_, info_ = ST.submit_stage(g503, A07, {'skuA': {}}, '07', 0.0)
    ok(cur_ is not None and g503.n_post == 3 and g503.counters.get('retries_post') == 2, 'submit 07: 503→503→202 — задание принято после двух повторов, retries_post=2')
    g503 = Gw503([])
    cur_, info_ = ST.submit_stage(g503, A07, {'skuA': {}}, '07', 0.0)
    ok(cur_ is None and info_.get('http') == 503 and info_.get('reason') == 'gateway_503' and (info_.get('post') or {}).get('worker_saw_job') is False and g503.counters.get('retries_post', 0) >= 1,
       'submit 07: 503 на всех повторах при живом /health → отказ задания с причиной gateway_503 и сведениями post (драйвер ставит повтор в конец очереди)')
finally:
    ST.KD.post_job = _orig_post_job

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

# ---- T-193/3 (22.11): на Salad 07 считался БЕЗ частей — модулей tools/assets (материал/ножки) не было в срезе, а «частей нет (ModuleNotFoundError)» глоталось заметкой
PARTS_PY = {'tools/assets/material_parts.py', 'tools/assets/parts_refine.py', 'tools/assets/parts_vote.py', 'tools/assets/part_shapes.py'}
try:
    real2 = CT.build(ROOT, 'HEAD')
    ok(PARTS_PY <= set(real2['files']) and {CT.packed_name(d) for d in CT.DATA_FILES} <= set(real2['files']),
       f'срез HEAD: модули частей (material_parts, parts_refine, parts_vote, part_shapes) и их правила (data/flat3d/*.json → tools/assets/_data/flat3d/*.json: воркер распаковывает только tools/…) в срезе кода ({sorted(PARTS_PY - set(real2["files"]))})')
    real3 = CT.build(ROOT, 'HEAD')
    ok(real2['tar'] == real3['tar'] and real2['tar_sha256'] == real3['tar_sha256'], 'срез HEAD с перенесёнными правилами — всё ещё побайтно детерминирован')
    with tarfile.open(fileobj=io.BytesIO(real2['tar'])) as _tf:
        _b = _tf.extractfile('tools/assets/_data/flat3d/material-part-rules.json').read()
    ok(_b == open(os.path.join(ROOT, 'data/flat3d/material-part-rules.json'), 'rb').read(), 'правила в срезе — те же байты, что data/flat3d/material-part-rules.json (один источник)')
    ok(PARTS_PY <= {f for f in files} and set(CT.DATA_FILES) <= set(files), 'stage_files.txt: те же модули частей и правила в списке образа')
    ok(CT.selfcheck(real2['tar'], real2['entries']) == '', 'срез HEAD: из ЧИСТОЙ распаковки (python -I) tex_fill находит и загружает модули частей и правила (`load_part_modules`)')
    # T-43/3: на ноде front_check был «n/a» у ВСЕХ товаров — правил свидетеля «перёда» (sides-eval.json, front-axis.json) не было в срезе (воркер распаковывает только tools/…)
    ok({CT.packed_name(d) for d in CT.DATA_ALWAYS} <= set(real2['files']) and set(CT.DATA_ALWAYS) <= set(files), 'срез HEAD: правила свидетеля перёда (sides-eval.json, front-axis.json) едут в срезе кода и есть в образе')
    import tempfile as _tf2
    import subprocess as _sp2
    with _tf2.TemporaryDirectory() as _d2:
        WS.safe_untar(real2['tar'], _d2)
        _code = ("import sys,os\nr=sys.argv[1]\nfor x in reversed(%r): sys.path.insert(0, os.path.join(r,x))\nimport front_axis as FA\n"
                 "g=FA.load_guard(); import json; json.load(open(FA.AXIS_RULES)); print('ok', sorted(g)[:2])\n") % (tuple(CT.DIRS),)
        _r2 = _sp2.run([sys.executable, '-I', '-c', _code, _d2], capture_output=True, text=True)
        ok(_r2.returncode == 0 and _r2.stdout.startswith('ok'), f'срез HEAD, чистая распаковка: front_axis читает оба файла правил (на ноде 06 не «n/a: нет файла») {_r2.stderr[-200:]}')
except CT.CodeTarError as exc:
    ok(False, f'срез HEAD с частями не собран: {exc}')
# срез без правил частей, но с модулями — отказ ДО платной группы
repo3 = tmpdir('mini-repo3')
run(repo3, 'git', 'init', '-q')
commit_tree(repo3, {f'{TRE}/tex_visible.py': 'X = 1\n', f'{TRE}/tex_fill.py': 'import material_parts\n', 'tools/assets/material_parts.py': 'Y = 1\n', 'tools/scout/rules/a.json': '{}\n'}, 'модуль частей без правил')
try:
    CT.build(repo3, 'HEAD')
    ok(False, 'срез: модули частей есть, правил data/flat3d нет — отказ')
except CT.CodeTarError as exc:
    ok('правил' in str(exc), 'срез: модули частей есть, правил data/flat3d нет — отказ с причиной')
# tex_fill: нет модуля частей — ИСКЛЮЧЕНИЕ, а не «частей нет» (этап падает, check.json «сбой этапа 7»)
try:
    sys.path.insert(0, os.path.join(SALAD, 'trellis'))
    import tex_fill as TF  # noqa: E402
    saved = {k: sys.modules.get(k) for k in ('material_parts', 'parts_refine', 'parts_vote')}
    for k in saved:
        sys.modules[k] = None                                   # import → ImportError (как «нет файла в срезе»)
    try:
        raised = ''
        try:
            TF.parts_from_geometry([])
        except ImportError as exc:
            raised = type(exc).__name__
        ok(raised in ('ImportError', 'ModuleNotFoundError'), f'tex_fill.parts_from_geometry: нет модуля частей → исключение, не тихое «частей нет» ({raised or "вернул заметку"})')
        raised = ''
        try:
            TF.merge_orphan_parts(None, None)
        except ImportError as exc:
            raised = type(exc).__name__
        ok(raised in ('ImportError', 'ModuleNotFoundError'), f'tex_fill.merge_orphan_parts: нет модуля этапа 3 → исключение, не «сирот не ищем» ({raised or "вернул заметку"})')
    finally:
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v
    out_g, note_g = TF.parts_from_geometry([])
    ok(out_g == [] and 'частей нет' not in note_g, 'tex_fill.parts_from_geometry: при наличии модулей загружается (пустой список геометрий → пусто)')
except Exception as exc:  # noqa: BLE001
    ok(False, f'tex_fill (части): тест не выполнен: {type(exc).__name__}: {exc}')


def swallowed_imports(path: str) -> list[str]:
    """Места, где `try:` с import внутри ловит Exception/BaseException/голый except и НЕ перебрасывает — тихий откат вместо отказа этапа."""
    t = ast.parse(open(path, encoding='utf-8').read())
    bad = []
    for n in ast.walk(t):
        if not isinstance(n, ast.Try):
            continue
        if not any(isinstance(m, (ast.Import, ast.ImportFrom)) for b in n.body for m in ast.walk(b)):
            continue
        for h in n.handlers:
            broad = h.type is None or (isinstance(h.type, ast.Name) and h.type.id in ('Exception', 'BaseException'))
            if broad and not any(isinstance(m, ast.Raise) for m in ast.walk(h)):
                bad.append(f'{os.path.basename(path)}:{h.lineno}')
    return bad


STAGE_SCRIPTS = [os.path.join(ROOT, 'tools/scout/salad/trellis/tex_fill.py'), os.path.join(ROOT, 'tools/scout/salad/trellis/tex_visible.py')]
# известные ОСОЗНАННЫЕ откаты (необязательные библиотеки/диагностика) — с причиной; всё новое — отказ этапа, не откат
ALLOWED_SWALLOW: set[str] = set()
sw = [x for p in STAGE_SCRIPTS for x in swallowed_imports(p) if x not in ALLOWED_SWALLOW]
ok(not sw, f'этапы 06/07: ни один `import` внутри try не прячется за `except Exception` без raise (ImportError = отказ этапа): {sw}')
_syn = os.path.join(tmpdir('swallow'), 'syn.py')
open(_syn, 'w', encoding='utf-8').write('def a():\n    try:\n        import zzz\n    except Exception:\n        return 1\n\n\ndef b():\n    try:\n        import yyy\n    except ImportError:\n        raise\n\n\ndef c():\n    try:\n        import xxx\n    except Exception:\n        raise\n')
ok(swallowed_imports(_syn) == ['syn.py:4'], 'самопроверка разборщика: ловит только проглоченный import (a), не перебрасываемый (b, c)')


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
ok(set(WS.COMMANDS) == {'06', '07', 'seam', '08', 'ref_zone', 'render_unlit'}, f'whitelist: ровно 6 команд ({sorted(WS.COMMANDS)})')
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
cmd07, _o, _n = WS.stage_command(C, '07', '/tmp/w/j', 'sku1', False, False, '/tmp/w/j/peak', code_root='/tmp/w/j/code')
ok(cmd07[cmd07.index('-I') + 1] == '/tmp/w/j/code/tools/scout/salad/trellis/tex_fill.py', 'команда 07: скрипт берётся из code_root задания, не из образа')
cmds, outs, nms = WS.stage_command(C, 'seam', '/tmp/w/j', 'sku1', False, False, '/tmp/w/j/peak', code_root='/tmp/w/j/code')
ok(cmds[cmds.index('-I') + 1] == '/tmp/w/j/code/tools/scout/salad/trellis/seam_stage.py' and nms == '07-seam' and '--fill' in cmds and '/tmp/w/j/in/07-fill' in cmds and '/tmp/w/j/in/06-visible' in cmds,
   'команда шва: seam_stage.py из code_root, вход 07-fill + 06-visible, выход 07-seam')
ok(WS.missing_inputs('seam', list(WS.NEED_SEAM)) == [] and '07-fill/filled.glb' in WS.missing_inputs('seam', ['06-visible/known.png']), 'вход шва: known.png и filled.glb обязательны')
ok('seam' in WS.DRIVER_STAGES and 'seam' not in WS.STAGES, 'шов в списке драйвера, но не в образе-запасе')
import argparse as _ap
ok(ST.stages_of(_ap.Namespace(stages='07,seam')) == ['07', 'seam'] and ST.stages_of(_ap.Namespace(stages='seam')) == ['seam'], 'драйвер: --stages 07,seam и seam разбираются')

# ---- этап 08 (T-220/1): команда, входы, whitelist, имя выхода
d08 = tmpdir('s08')
os.makedirs(os.path.join(d08, 'j', 'in', '03-parts'), exist_ok=True)
os.makedirs(os.path.join(d08, 'j', 'in', '07-seam'), exist_ok=True)
for rel in ('03-parts/parts.npz', '03-parts/parts.json', '07-seam/seam.glb', 'photo.png'):
    open(os.path.join(d08, 'j', 'in', rel), 'wb').write(b'x')
c8, o8, n8 = WS.stage_command(C, '08', os.path.join(d08, 'j'), 'sku1', False, False, '/tmp/w/j/peak', code_root='/tmp/w/j/code')
ok(c8[c8.index('-I') + 1] == '/tmp/w/j/code/tools/assets/material_stage.py' and n8 == '08-material' and c8[c8.index('-I') + 2] == 'stage', 'команда 08: material_stage.py stage из code_root, выход 08-material')
ok(c8[c8.index('--glb') + 1].endswith('07-seam/seam.glb') and '--no-frame' in c8 and '--parts-dir' in c8 and '--photo' in c8 and c8[c8.index('--stages-dir') + 1].endswith('/j/in'),
   'команда 08: модель — шов, есть --no-frame, части, фото, stages-dir = вход')
os.remove(os.path.join(d08, 'j', 'in', '07-seam', 'seam.glb'))
os.remove(os.path.join(d08, 'j', 'in', '03-parts', 'parts.json'))
os.remove(os.path.join(d08, 'j', 'in', 'photo.png'))
c8b, _o, _n = WS.stage_command(C, '08', os.path.join(d08, 'j'), 'sku1', False, False, '/tmp/w/j/peak', code_root='/tmp/w/j/code')
ok(c8b[c8b.index('--glb') + 1].endswith('07-fill/filled.glb') and '--parts-dir' not in c8b and '--photo' not in c8b, 'команда 08: нет шва — filled.glb; нет parts.json/фото — без --parts-dir/--photo')
# вход шва: prov*.png едет на ноду (T-20261124-23/в3) — без него шов считает synth известным, а локально (с prov) — нет
vs, fs = os.path.join(d08, 'vis_seam'), os.path.join(d08, 'fill_seam')
os.makedirs(vs, exist_ok=True)
os.makedirs(fs, exist_ok=True)
open(os.path.join(fs, 'filled.glb'), 'wb').write(b'x')
open(os.path.join(fs, 'report.json'), 'wb').write(b'{}')
for n in ('known.png', 'conf.png', 'prov.png', 'prov1.png', 'known1.png', 'frame.png', 'visible.glb', 'check.json'):
    open(os.path.join(vs, n), 'wb').write(b'x')
zs = sorted(zipfile.ZipFile(io.BytesIO(ST.input_zip_seam(vs, fs, b'TAR', None))).namelist())
ok(all(f'06-visible/{n}' in zs for n in ('known.png', 'conf.png', 'prov.png', 'prov1.png', 'known1.png')) and '07-fill/filled.glb' in zs and '07-fill/report.json' in zs and '06-visible/visible.glb' not in zs and '06-visible/frame.png' not in zs,
   f'input_zip_seam: known*/conf*/prov*.png + filled.glb + report.json (решение 07 о synth), без visible.glb и кадра ({zs})')
need08 = ['product.json', '04-camera/check.json', '06-visible/check.json']
ok(WS.missing_inputs('08', need08 + ['07-fill/filled.glb']) == [] and WS.missing_inputs('08', need08 + ['07-seam/seam.glb']) == [], 'вход 08: хватает шва ИЛИ filled.glb')
ok(len(WS.missing_inputs('08', need08)) == 1 and 'product.json' in WS.missing_inputs('08', ['07-fill/filled.glb', '04-camera/check.json', '06-visible/check.json']), 'вход 08: без модели и без product.json — отказ с именами')
ok('08' in WS.DRIVER_STAGES and '08' not in WS.STAGES and '08' in WS.FILL_STAGES, '08 в списке драйвера и в «местах под тяжёлое», но не в образе-запасе')
ok(ST.stage_dirname('08') == '08-material' and ST.stages_of(_ap.Namespace(stages='07,seam,08')) == ['07', 'seam', '08'], 'драйвер: --stages 07,seam,08, папка выхода 08-material')
# вход 08: zip драйвера → то, что просит воркер
vd, fd, sd = (os.path.join(d08, x) for x in ('vis', 'fill', 'sea'))
for p in (vd, fd, sd, os.path.join(d08, 'pose', 'sku1', '04-camera'), os.path.join(d08, 'pose', 'g1', 'sku2', '04-camera')):
    os.makedirs(p, exist_ok=True)
for rel in ('vis/check.json', 'vis/known.png', 'vis/visible.glb', 'fill/filled.glb', 'fill/check.json', 'sea/seam.glb', 'pose/sku1/04-camera/check.json', 'pose/g1/sku2/04-camera/check.json', 'prod.json', 'p.npz'):
    open(os.path.join(d08, rel), 'wb').write(b'{}' if rel.endswith('.json') else b'x')
z08 = zipfile.ZipFile(io.BytesIO(ST.input_zip_08(vd, fd, sd, os.path.join(d08, 'pose', 'sku1', '04-camera', 'check.json'), b'TAR', {'extra_in_08': {'product.json': os.path.join(d08, 'prod.json'), '03-parts/parts.npz': os.path.join(d08, 'p.npz')}}))).namelist()
ok(WS.missing_inputs('08', z08) == [] and '07-seam/seam.glb' in z08 and '07-fill/filled.glb' not in z08 and 'code.tar' in z08 and '03-parts/parts.npz' in z08 and '06-visible/known.png' in z08,
   f'input_zip_08: шов вместо filled.glb, product.json, части, code.tar ({sorted(z08)})')
ok('07-fill/check.json' in z08, 'input_zip_08: check.json этапа 07 едет во вход (заслон 08 «только после зелёного 07», T-20261124-10)')
os.remove(os.path.join(sd, 'seam.glb'))
z08b = zipfile.ZipFile(io.BytesIO(ST.input_zip_08(vd, fd, sd, os.path.join(d08, 'pose', 'sku1', '04-camera', 'check.json'), None, {'extra_in_08': {'product.json': os.path.join(d08, 'prod.json')}}))).namelist()
ok('07-fill/filled.glb' in z08b and '07-seam/seam.glb' not in z08b and WS.missing_inputs('08', z08b) == [], 'input_zip_08: шва нет — filled.glb')
a08 = _ap.Namespace(out=d08, vis_root='', fill_root='', pose_root=os.path.join(d08, 'pose'))
ok(ST.seam_model_08(a08, 'sku1', {})[3].endswith('pose/sku1/04-camera/check.json') and ST.seam_model_08(a08, 'sku2', {})[3].endswith('pose/g1/sku2/04-camera/check.json'),
   'камера 08: --pose-root находит и <корень>/<товар>, и <корень>/g1/<товар>')
cat08 = os.path.join(d08, 'cat.json')
json.dump([{'sid': 'sku1', 'name': 'Стол', 'role': 'dining_table', 'params': {'color': 'белый'}}], open(cat08, 'w', encoding='utf-8'), ensure_ascii=False)
inp08 = {'sku1': {'extra_in': {'parts.npz': os.path.join(d08, 'p.npz'), 'photo.png': os.path.join(d08, 'p.npz')}}, 'sku2': {}}      # фото — из extra_in['photo.png'] (так у входов 07)
pj08 = os.path.join(d08, 'parts.json')
open(pj08, 'w', encoding='utf-8').write(json.dumps({'parts': [{'id': 0, 'role': 'legs'}, {'id': 1, 'name': 'Frame'}]}))
ok('нет роли' in ST.parts_roles_problem(pj08) and 'у 1 из 2' in ST.parts_roles_problem(pj08), 'parts_roles_problem: часть без роли (PartLLM до моста) — причина строкой, 08 без частей')
open(os.path.join(d08, 'roles.json'), 'w', encoding='utf-8').write(json.dumps({'1': {'role': 'frame'}}))
ok(ST.parts_roles_problem(pj08) == '', 'parts_roles_problem: роль части есть в roles.json рядом — частей хватает')
open(pj08, 'w', encoding='utf-8').write(json.dumps({'parts': [{'id': 0, 'role': 'legs'}, {'id': 1, 'role': 'body'}]}))
rep08 = ST.attach_08(inp08, cat08, d08)
ok(inp08['sku1']['extra_in_08'].get('03-parts/roles.json', '').endswith('roles.json') and rep08['sku1']['parts_why'] == '', 'attach_08: роли есть → части и roles.json едут в 08')
ok(rep08['sku1']['product'] and rep08['sku1']['photo'] and rep08['sku1']['parts'] and not rep08['sku2']['product'] and not rep08['sku2']['parts'], 'attach_08: product.json из каталога, чего нет в каталоге — не выдумывается; части — парой npz+json')
ok(json.load(open(inp08['sku1']['extra_in_08']['product.json'], encoding='utf-8'))['params'] == {'color': 'белый'}, 'attach_08: params — как в каталоге')
open(pj08, 'w', encoding='utf-8').write(json.dumps({'parts': [{'id': 0, 'name': 'Leg'}]}))
os.remove(os.path.join(d08, 'roles.json'))
inp08b = {'sku1': {'extra_in': {'parts.npz': os.path.join(d08, 'p.npz')}}}
rep08b = ST.attach_08(inp08b, cat08, d08)
ok(not rep08b['sku1']['parts'] and 'нет роли' in rep08b['sku1']['parts_why'] and '03-parts/parts.npz' not in inp08b['sku1']['extra_in_08'], 'attach_08: части без ролей (PartLLM до моста) не отправляются — 08 по форме, причина в отчёте')
pool08 = WS.Pool(KW.State(), dict(C, work=tmpdir('work08')))
ok(pool08.sem_08._value == 1,'08: по умолчанию одно задание за раз (пик памяти 4,5 ГБ, проба 23.11)')
va = {'args': ['--card-json', '@in/card.json']}
ok(ST.job_args('07', va) == va['args'] and ST.job_args('06', va) == [] and ST.job_args('seam', va) == [] and ST.job_args('08', va) == [], 'job_args: args из inputs — только 07; 06, шов и 08 — пусто (иначе падают на «unrecognized arguments --card-json»)')
# --- T-43/❓2: роль во вход 06 → «зад корпусной» после переноса (product.json, --product-json)
d06 = tmpdir('s06role')
cat06 = os.path.join(d06, 'cat.json')
json.dump([{'sid': 'a1', 'name': 'x', 'role': 'комод', 'params': {'k': 1}}, {'sid': 'a2', 'name': 'y', 'role': ''}], open(cat06, 'w', encoding='utf-8'), ensure_ascii=False)
inp06 = {'a1': dict(inp['s1']), 'a2': dict(inp['s1']), 'a3': dict(inp['s1'])}
rep06 = ST.attach_06(inp06, cat06, d06)
ok(rep06['a1'] == {'product': True, 'role': 'комод'} and not rep06['a2']['product'] and not rep06['a3']['product'], 'attach_06: product.json только у товара с ролью в каталоге; без записи/роли — файла нет, причина в отчёте')
ok(ST.job_args('06', inp06['a1']) == ['--product-json', '@in/product.json'] and ST.job_args('06', inp06['a2']) == [] and ST.job_args('06', inp06['a3']) == [], 'job_args 06: --product-json только когда product.json во входе (иначе tex_visible не знал бы флаг лишний раз)')
ok(WS.check_args(ST.job_args('06', inp06['a1'])) == ['--product-json', '@in/product.json'], 'job_args 06: аргументы проходят whitelist воркера')
z06 = zipfile.ZipFile(io.BytesIO(ST.input_zip_06(inp06['a1'])))
ok('product.json' in z06.namelist() and json.loads(z06.read('product.json'))['role'] == 'комод', 'input_zip_06: product.json (с ролью) лежит во входе 06')
ok('product.json' not in zipfile.ZipFile(io.BytesIO(ST.input_zip_06(inp06['a3']))).namelist(), 'input_zip_06: без роли product.json нет')
import back_panel_stage as BPS_
vz = os.path.join(d06, 'vis'); os.makedirs(vz)
for n in ('visible.glb', BPS_.KEEP, 'check.json'):
    open(os.path.join(vz, n), 'wb').write(b'x')
zz = io.BytesIO()
with zipfile.ZipFile(zz, 'w') as z_:
    ST.zip_dir_into(z_, vz, '06-visible')
ok(BPS_.KEEP.endswith(ST.KEEP_SUFFIX) and sorted(zipfile.ZipFile(io.BytesIO(zz.getvalue())).namelist()) == ['06-visible/check.json', '06-visible/visible.glb'], 'вход 07/08: исходник до «зад корпусной» (visible.pre-backpanel.glb) в задания не едет')
os.makedirs(os.path.join(d08, 'pr', 'sku1', '07-fill'), exist_ok=True)
open(os.path.join(d08, 'pr', 'sku1', '07-fill', 'report.json'), 'w').write(json.dumps({'report': {'relief_source': None}}))
os.makedirs(os.path.join(d08, 'pr', 'sku2', '07-fill'), exist_ok=True)
open(os.path.join(d08, 'pr', 'sku2', '07-fill', 'report.json'), 'w').write(json.dumps({'report': {'relief_source': 'ultratex'}}))
ok(ST.texture_source(os.path.join(d08, 'pr', 'sku1', '07-fill')) == 'none' and ST.texture_source(os.path.join(d08, 'pr', 'sku2', '07-fill')) == 'ultratex'
   and ST.texture_source(os.path.join(d08, 'нет')) == 'нет отчёта', 'texture_source: none / ultratex / нет отчёта читаются из report.json 07')
ok(ST.text_counts({'a': {'status': 'done', 'texture_source': 'ultratex'}, 'b': {'status': 'done', 'texture_source': 'none'}, 'c': {'status': 'failed'}}) == {'ultratex': 1, 'none': 1}, 'text_counts: только готовые')

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
c4, r4 = http4(zb('07', with_code, jid='h-7'))
ok(c4 == 202, f'HTTP: 07 с code.tar и code_sha принят ({c4}, {r4})')
ok(wait_done(pool4, ['h-7']), 'HTTP: задание с кодом из входа закончилось')
srv4.shutdown()

print()


# ---- T-187/7: верх по Ш3в — результат этапа 07 одинаков «у нас» (дерево репозитория) и «на Salad» (чистая распаковка code.tar, python -I, тот же воркерный запуск)
def _top_equality():
    import tempfile
    sys.path.insert(0, os.path.join(SALAD, 'trellis'))
    import numpy as np
    import tests_tex_fill as TT
    import tex_coverage as TC
    import tex_fill as TF
    from PIL import Image
    g, tex, kn = TT._top_scene()
    td = tmpdir('topeq')
    v = os.path.join(td, 'in', 's1', '06-visible')
    os.makedirs(v)
    TF.write_glb([g], [tex], os.path.join(v, 'visible.glb'))
    Image.fromarray((kn * 255).astype(np.uint8)).save(os.path.join(v, 'known.png'))
    json.dump({'version': 1, 'stage': '06-visible', 'sku': 's1', 'passed': True, 'reason': '', 'metric': None, 'metrics': {}, 'outputs': [], 'frame': None, 'extra': {}}, open(os.path.join(v, 'check.json'), 'w'))
    ph = np.zeros((200, 300, 4), np.uint8)
    ph[..., :3] = (150, 100, 60)
    ph[::6, :, :3] = (120, 80, 45)
    ph[..., 3] = 255
    Image.fromarray(ph).save(os.path.join(td, 'photo.png'))
    json.dump({'role': 'стол обеденный', 'name': 'Стол обеденный из массива дуба', 'Материал столешницы': 'массив дуба'}, open(os.path.join(td, 'card.json'), 'w'), ensure_ascii=False)
    real = CT.build(ROOT, 'HEAD')
    code = os.path.join(td, 'code')
    WS.safe_untar(real['tar'], code)
    args = ['run_stage', None, 's1', '--visible', v, '--no-parts-npz', '--no-mirror', '--card-json', os.path.join(td, 'card.json'), '--photo', os.path.join(td, 'photo.png')]
    res = {}
    for nm, script in (('local', os.path.join(ROOT, 'tools/scout/salad/trellis/tex_fill.py')), ('code_tar', os.path.join(code, 'tools/scout/salad/trellis/tex_fill.py'))):
        out = os.path.join(td, 'out-' + nm)
        a = list(args)
        a[1] = out
        r = subprocess.run([sys.executable, '-I', script] + a, capture_output=True, cwd=td, timeout=600)
        ok(r.returncode == 0, f'верх Ш3в: этап 07 из «{nm}» отработал ' + ('' if r.returncode == 0 else r.stderr.decode('utf-8', 'replace')[-300:]))
        d = os.path.join(out, 's1', '07-fill')
        rep = json.load(open(os.path.join(d, 'report.json'), encoding='utf-8'))['report']
        res[nm] = (TC.load_geoms(os.path.join(d, 'filled.glb')), rep.get('top_prior', {}))
        _chk = json.load(open(os.path.join(d, 'check.json'), encoding='utf-8'))
        _pp = (_chk.get('extra') or {}).get('paint_policy') or {}
        sys.path.insert(0, os.path.join(ROOT, 'tools/scout'))
        import mesh_type_passports as _MTP
        ok(_pp.get('type') == 'стол обеденный' and _pp.get('hidden_pattern') == 'continue' and _pp.get('digest') == _MTP.digest('стол обеденный') and _pp.get('applied') in ('synth', 'no_synth'),
           f'политика покраски в check.json 07 из «{nm}»: тип, значение, digest паспорта, применено ({ {k: _pp.get(k) for k in ("type", "hidden_pattern", "mode", "applied", "reason")} })')
    (ga, ra), (gb, rb) = res['local'], res['code_tar']
    ok(ra.get('applied') is True and ra.get('pattern') == 'library' and ra.get('top_source') == 'same_part_inference', f'верх Ш3в: применён с узором библиотеки ({ra.get("top_source")}, pattern={ra.get("pattern")}, {ra.get("library")})')
    ok(all(np.array_equal(np.asarray(x['tex']), np.asarray(y['tex'])) for x, y in zip(ga, gb)), 'верх Ш3в: текстуры filled.glb одинаковы у нас и из code.tar (побайтно)')
    ok({k: ra.get(k) for k in ('top_source', 'applied', 'tone_lab', 'library', 'texels_changed', 'pattern_amp')} == {k: rb.get(k) for k in ('top_source', 'applied', 'tone_lab', 'library', 'texels_changed', 'pattern_amp')}, 'верх Ш3в: отчёт top_prior одинаков (источник, тон, бин узора, число текселей)')


try:
    _top_equality()
except Exception as exc:  # noqa: BLE001
    ok(False, f'верх Ш3в: проверка равенства не выполнена: {type(exc).__name__}: {exc}')


# ---- А4 (type-rules-code-01): политика покраски по типу читается ИЗ СРЕЗА code.tar (модуль паспортов и json едут в tar), digest тот же, что у нас
def _paint_policy_from_slice():
    td = tmpdir('paintpol')
    real = CT.build(ROOT, 'HEAD')
    code = os.path.join(td, 'code')
    WS.safe_untar(real['tar'], code)
    ok(os.path.isfile(os.path.join(code, 'tools/scout/mesh_type_passports.py')) and os.path.isfile(os.path.join(code, 'tools/scout/rules/mesh-type-passports.json')), 'политика покраски: модуль паспортов и json — в срезе code.tar')
    prog = ('import sys, json; sys.path.insert(0, "tools/scout/salad/trellis"); sys.path.insert(0, "tools/scout"); import mesh_type_passports as M, tex_fill as T; '
            'print(json.dumps({r: T.paint_policy_for({"top_card": {"role": r}}) for r in ("ваза", "комод", "кресло", "неведомая вещь")}, ensure_ascii=False)); print(M.__file__)')
    r = subprocess.run([sys.executable, '-I', '-c', prog], capture_output=True, cwd=code, timeout=300)
    ok(r.returncode == 0, 'политика покраски: срез читает паспорт типов ' + ('' if r.returncode == 0 else r.stderr.decode('utf-8', 'replace')[-300:]))
    lines = r.stdout.decode('utf-8').strip().splitlines()
    got = json.loads(lines[0]) if lines else {}
    ok(lines[-1].startswith(code), 'политика покраски: модуль паспортов взят из среза, не из рабочей копии')
    sys.path.insert(0, os.path.join(ROOT, 'tools/scout'))
    import mesh_type_passports as MTP
    ok(all(got[k]['digest'] == MTP.digest(k) and got[k]['hidden_pattern'] == MTP.paint_policy(k)['hidden_pattern'] for k in ('ваза', 'комод', 'кресло')), 'политика покраски: digest и значение из среза = у нас (ваза continue, комод body, кресло same_fabric)')
    ok(got['неведомая вещь']['hidden_pattern'] == 'unknown' and got['неведомая вещь']['reason'] == 'no_type', 'политика покраски: неизвестный тип из среза → unknown + no_type (воздержание)')


try:
    _paint_policy_from_slice()
except Exception as exc:  # noqa: BLE001
    ok(False, f'политика покраски из среза: проверка не выполнена: {type(exc).__name__}: {exc}')


# ---- T-193/4: «тихие» откаты ленивых импортов этапа 07 — из code.tar части/сироты считаются так же, как у нас (причина прежнего Salad ≠ локально: material_parts/parts_refine не ехали в срезе → молча «одна часть»)
def _lazy_imports_equal():
    td = tmpdir('lazyimp')
    code = os.path.join(td, 'code')
    WS.safe_untar(CT.build(ROOT, 'HEAD')['tar'], code)
    snippet = ('import sys, json; r = sys.argv[1]; sys.path.insert(0, r + "/tools/scout/salad/trellis"); sys.path.insert(0, r + "/tools/scout")\n'
               'import numpy as np, trimesh, tex_fill as TF\n'
               'm = trimesh.creation.box(); g = [{"mesh": m, "F": np.asarray(m.faces)}]\n'
               'p, note = TF.parts_from_geometry(g); q, n2 = TF.merge_orphan_parts(m, np.zeros(len(m.faces), np.int32))\n'
               'print(json.dumps({"note": note, "orphan": n2}))')
    res = {}
    for nm, root in (('дерево', ROOT), ('code.tar', code)):
        r = subprocess.run([sys.executable, '-I', '-c', snippet, root], capture_output=True, cwd=td, timeout=300)
        ok(r.returncode == 0, f'ленивые импорты 07: {nm} — запуск ' + ('' if r.returncode == 0 else r.stderr.decode('utf-8', 'replace')[-300:]))
        res[nm] = json.loads(r.stdout.decode().strip().splitlines()[-1]) if r.returncode == 0 else {}
    ok(res['code.tar'] == res['дерево'] and res['code.tar'] != {}, f'ленивые импорты 07: части и сироты из code.tar = у нас ({res["code.tar"]})')
    ok('частей нет' not in res['code.tar'].get('note', 'частей нет') and 'нет parts_refine' not in res['code.tar'].get('orphan', 'нет parts_refine'), 'ленивые импорты 07: в code.tar есть material_parts и parts_refine/parts_vote (не «одна часть» молча)')


try:
    _lazy_imports_equal()
except Exception as exc:  # noqa: BLE001
    ok(False, f'ленивые импорты 07: проверка не выполнена: {type(exc).__name__}: {exc}')


def _inputs07():
    """T-187/7 (23.11): вход 07 боевого пути несёт card.json + photo.png + args; без карточки — не молча (no_card, top_skip в отчёте, счётчик в итоге, отказ при нуле карточек)."""
    import make_inputs_07 as MI
    td = tmpdir('inputs07')
    ph = os.path.join(td, 'ph')
    os.makedirs(ph)
    rows = [['sku', 'ultratex_glb']]
    vis_of = {}
    for s in ('p1', 'p2', 'p3'):
        for nm in ('ut', 'vis'):
            os.makedirs(os.path.join(td, nm, s), exist_ok=True)
        ut, vd = os.path.join(td, 'ut', s, 'x.glb'), os.path.join(td, 'vis', s)
        open(ut, 'wb').write(b'g')
        open(os.path.join(vd, 'visible.glb'), 'wb').write(b'v')
        rows.append([s, ut])
        vis_of[s] = vd
    for s in ('p1', 'p2'):
        open(os.path.join(ph, f'{s}.hd.rgba.png'), 'wb').write(b'png')
    cards = {'p1': {'role': 'стол обеденный', 'name': 'Стол'}, 'p2': {'role': 'тумба', 'name': 'ТВ-тумба', 'Материал': 'МДФ'}}
    out, miss, top = MI.build(rows, 'ultratex_glb', vis_of, cards, [ph], os.path.join(td, 'cards'))
    ok(not miss and set(out) == {'p1', 'p2', 'p3'}, f'make_inputs_07: все три товара в пакете, пропусков нет ({miss})')
    for s in ('p1', 'p2'):
        v = out[s]
        ok(v['args'] == ['--card-json', '@in/card.json', '--photo', '@in/photo.png', '--ut-glb', '@in/ut.glb'], f'make_inputs_07 {s}: args карточка + фото + UltraTex ({v["args"]})')
        ok(set(v['extra_in']) == {'card.json', 'photo.png', 'ut.glb'} and all(os.path.isfile(p) for p in v['extra_in'].values()), f'make_inputs_07 {s}: card.json, photo.png, ut.glb — файлы на месте')
    ok(json.load(open(out['p2']['extra_in']['card.json'], encoding='utf-8')) == cards['p2'], 'make_inputs_07: card.json = карточка товара (role, name, характеристики)')
    ok(out['p3']['args'] == ['--ut-glb', '@in/ut.glb'] and top['no_card'] == ['p3'] and top['no_photo'] == ['p3'], f'make_inputs_07: товар без карточки/фото — в no_card/no_photo, не молча ({top})')
    nc, nph = ST.top_input_problems(out)
    ok(nc == ['p3'] and nph == ['p3'], f'stage_trial.top_input_problems: без карточки {nc}, без фото {nph}')
    ok(ST.top_input_problems({s: {'args': ['--ut-glb', '@in/ut.glb'], 'extra_in': {'ut.glb': 'x'}} for s in ('a', 'b')})[0] == ['a', 'b'], 'вход как в f1 (только --ut-glb): все без карточки → stage_trial откажет до создания группы')
    for nm, rep, want in (('a', {'top_prior': {'applied': True, 'top_source': 'same_part_inference'}}, 'applied'), ('b', {'top_prior': {'applied': False, 'top_source': 'as_before', 'top_skip': 'no_card'}}, 'no_card'),
                          ('c', {'top_prior': {'applied': False, 'top_source': 'photo_top'}}, 'photo_top')):
        d = os.path.join(td, 'o' + nm)
        os.makedirs(d)
        json.dump({'report': rep}, open(os.path.join(d, 'report.json'), 'w'))
        ok(ST.top_state(d) == want, f'stage_trial.top_state: {rep["top_prior"]} → {want}')
    ok(ST.top_state(os.path.join(td, 'нет')) == 'нет отчёта', 'stage_trial.top_state: нет report.json → «нет отчёта»')
    ok(ST.top_counts({'a': {'status': 'done', 'top': 'no_card'}, 'b': {'status': 'done', 'top': 'no_card'}, 'c': {'status': 'done', 'top': 'applied'}, 'd': {'status': 'failed'}}) == {'no_card': 2, 'applied': 1}, 'stage_trial.top_counts: счётчик причин по готовым товарам')


try:
    _inputs07()
except Exception as exc:  # noqa: BLE001
    ok(False, f'вход 07 (карточка+фото): проверка не выполнена: {type(exc).__name__}: {exc}')


def _camera_body_only():
    """T-20261124-02: 06 идёт с --body-only по флагам check.json камеры (rules/paint-run-all.json dynamic.body_only_args), а не по ручному полю."""
    td = tmpdir('cam_body_only')

    def cam(name, extra, write=True):
        d = os.path.join(td, name, '04-camera')
        os.makedirs(d, exist_ok=True)
        if write:
            json.dump({'passed': False, 'extra': extra}, open(os.path.join(d, 'check.json'), 'w'))
        return os.path.join(td, name)

    ok(ST.camera_body_only(cam('bsm', {'bottom_shape_mismatch': True})) is True, 'camera_body_only: bottom_shape_mismatch → body_only')
    ok(ST.camera_body_only(cam('legs', {'legs_block': True})) is True, 'camera_body_only: legs_block → body_only')
    ok(ST.camera_body_only(cam('clean', {'bottom_shape_mismatch': False, 'legs_block': False})) is False, 'camera_body_only: флаги ложны → обычный 06')
    ok(ST.camera_body_only(cam('nofile', {}, write=False)) is False, 'camera_body_only: нет check.json → False (не падает)')
    ok(ST.camera_body_only('') is False and ST.camera_body_only(None) is False, 'camera_body_only: нет pose_run → False')
    rules = json.load(open(os.path.join(SCOUT, 'rules', 'paint-run-all.json'), encoding='utf-8'))
    ok(['04-camera', 'bottom_shape_mismatch'] in rules['dynamic']['body_only_args']['if_extra_true_any'], 'правило одно: stage_trial читает те же флаги, что paint_run_all')


try:
    _camera_body_only()
except Exception as exc:  # noqa: BLE001
    ok(False, f'camera_body_only: проверка не выполнена: {type(exc).__name__}: {exc}')
# ---------------------------------------------------------------- размер ноды по пакету (T-20261124-09)
ok(ST.resolve_node(None, 0, 0, 1) == ('', 4, 2), 'размер ноды: один товар → low, 4 задания, 2 на этап 07')
ok(ST.resolve_node(None, 0, 0, 2) == ('big', 4, 4) and ST.resolve_node(None, 0, 0, 29) == ('big', 4, 4), 'размер ноды: пакет ≥2 товаров → big, 4 задания, 4 на этап 07')
ok(ST.resolve_node('low', 0, 0, 29) == ('', 4, 2), 'размер ноды: --variant low главнее пакета (пакет на low — по явному слову)')
ok(ST.resolve_node('big', 0, 0, 1) == ('big', 4, 4), 'размер ноды: --variant big для одного товара — как просили')
ok(ST.resolve_node(None, 6, 3, 5) == ('big', 6, 3) and ST.resolve_node('low', 3, 1, 5) == ('', 3, 1), 'размер ноды: явные --procs/--fill-procs главнее умолчаний размера')
try:
    ST.resolve_node('huge', 0, 0, 3)
    ok(False, 'размер ноды: неизвестный размер должен отказывать')
except ValueError:
    ok(True, 'размер ноды: неизвестный размер — отказ')
bigb = ST.build_body('t-stage', 'ghcr.io/o/n@sha256:' + 'a' * 64, 'low', 'cls-1650', AUTH, 3600, 900, 4, 4, 1, 900, worker_z=None, variant='big')
rb = bigb['container']['resources']
ok(rb['cpu'] == 8 and rb['memory'] == 16384 and bigb['container']['environment_variables']['STAGE_FILL_PROCS'] == '4', f'тело группы big: 8 vCPU / 16 ГБ из профиля cpu_stage, STAGE_FILL_PROCS=4 ({rb["cpu"]}, {rb["memory"]})')
ok(4 * 3.4 < rb['memory'] / 1024 * 0.9, 'big: 4 задания 07 по пику ≈3,4 ГБ (замер T-24) влезают в 16 ГБ с запасом 10 %')


print('ПРОВАЛЕНО: ' + str(len(FAILS)) if FAILS else 'ВСЕ ТЕСТЫ ЗЕЛЁНЫЕ')
sys.exit(1 if FAILS else 0)
