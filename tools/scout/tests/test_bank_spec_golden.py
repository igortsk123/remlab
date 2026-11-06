#!/usr/bin/env python3
"""Golden-тест цепочки банка гостиной: вывод и файлы всех `bank_*` без `--room` — побайтно как до этапа Б room-bank-01
(`RoomBankSpec`, T-20261106-67).

ЗАЧЕМ. Этап Б перевёл пути, правила и ключ ячейки всех `bank_*` на `room_bank_spec.py`. Гостиная обязана остаться ровно
прежней: та же печать, те же файлы (отчёт prepare, паспорт, состояние ожидания, manifest, смешанный банк, снимки-поколения,
журнал, запрет отката), те же умолчания и env. Тест гоняет сценарии в песочнице и сверяет с эталоном
`tests/fixtures/bank-spec-golden.json`, снятым на коде ДО этапа Б (`--record --rev c09f215f`).

ПЕСОЧНИЦА. `<T>/tools/scout/` — копии `bank_*.py` (и `room_bank_spec.py`, если есть в источнике) + синтетический живой банк
`sets3.json` и правила; остальные модули (`set_identity`, `sets_incremental`, …) — из этого дерева. `HOME=<T>/home`: умолчания
`~/scout-scenes/…` ложатся в песочницу. Время заморожено, pid постоянный, база подменена фактами. Живые банки не трогаются.

  python3 tests/test_bank_spec_golden.py                   # сверка текущего кода с эталоном
  python3 tests/test_bank_spec_golden.py --record [--rev R] # снять эталон (R — git-ревизия модулей; без — текущее дерево)
  python3 tests/test_bank_spec_golden.py --show СЦЕНАРИЙ    # вывод сценария на текущем коде (разбор расхождения)
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

SCOUT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.normpath(os.path.join(SCOUT, '..', '..'))
FIXTURE = os.path.join(SCOUT, 'tests', 'fixtures', 'bank-spec-golden.json')
MODULES = ('bank_prepare', 'bank_pending', 'bank_promote', 'bank_refresh', 'bank_keep', 'bank_ready', 'bank_run',
           'room_bank_spec')
FIXED = 1793450000.0          # заморожённое «сейчас» (2026-10-31, UTC)
CLEAR = ('BANK_CANDIDATE', 'BANK_PREPARE_REPORT', 'BANK_PENDING', 'DEMO_DATA', 'BANK_PROMOTE', 'BANK_PROMOTE_DIR',
         'BANK_GENERATIONS', 'BANK_MAX_PROMOTE_SHARE', 'SETS_BANK', 'SETS_OUTPUT', 'ACC_REPORT_SUFFIX', 'BANK_KEEP_FROM')

# ——— синтетический банк ———
TIERS = ('эконом', 'комфорт', 'премиум')


def _it(eid, role, price, w=200, d=90, h=80):
    return {'mid': 1, 'eid': eid, 'url': f'u/{eid}', 'img': f'i/{eid}', 'price': price, 'w': w, 'd': d, 'h': h,
            'qty': 1, 'role': role}


def live_bank() -> list:
    out = []
    for band in ('S', 'M'):
        for style in ('сканди', 'лофт'):
            for ti, tier in enumerate(TIERS):
                k = f'{band}{style[0]}{ti}'
                p = (ti + 1) * 10000
                out.append({'band': band, 'style': style, 'tier': tier, 'name': f'набор {k}',
                            'items': {'диван': _it(f'd{k}', 'диван', p), 'столик': _it(f't{k}', 'столик', p // 5, 80, 50, 45),
                                      'ковёр': _it(f'r{k}', 'ковёр', p // 4, 200, 140, 1),
                                      'торшер': _it(f'l{k}', 'торшер', p // 10, 30, 30, 160)},
                            'total': p + p // 5 + p // 4 + p // 10})
    out[2]['items']['столик']['_gone'] = True              # живой с ушедшим товаром
    return out


def cand_bank(live: list) -> list:
    out = json.loads(json.dumps(live))
    for s in out:
        s.pop('set_id', None)
    for n in (0, 3, 7):                                     # три ячейки с новым кандидатом
        s = out[n]
        s['items']['столик'] = _it(s['items']['столик']['eid'] + 'n', 'столик', s['items']['столик']['price'] + 100, 80, 50, 45)
    out[2]['items']['столик'] = _it('t-fresh', 'столик', 2500, 80, 50, 45)
    return out


def rules_fixture() -> dict:
    return {'enabled': True, 'prepare_enabled': True, 'promote_enabled': True, 'write_enabled': True, 'max_promote_share': 0.5,
            'promote_exam': False, 'promote_demo_check': False, 'promote_dining_check': True, 'hidden_roles': ['диван'],
            'write_manifest_max_age_h': 12, 'reserve': 30, 'prepare_timeout_min': 1,
            'keep': {'enabled': True, 'wait_catalog_grace_nights': 2}}


# ——— сценарии: код выполняется в песочнице (раннер `_RUN`), печать — эталон ———
PRE = r'''
import json, os, sys, io, contextlib
H = os.environ['GOLD_HERE']
def show(x):
    print(json.dumps(x, ensure_ascii=False, sort_keys=True, default=str))
import bank_ready as BR
SKUS = json.load(open(os.path.join(H, 'skus.json')))
prod = {s: {'role': r, 'status': 'active', 'eligible': True, 'has_h': True, 'rep': s, 'w': 100, 'd': 50, 'h': 40}
        for s, r in SKUS.items()}
MEDIA = {s: {'url': 'u/' + s.split(':')[1], 'img': 'i/' + s.split(':')[1], 'price': 1, 'store': 'x'} for s in SKUS}
F = BR.Facts(prod, failed=set(), strategy=lambda role: 'mesh', media=MEDIA.get, mesh_ok=set(list(SKUS)[::2]), decisions={})
import catalog_media as CM
CM.sync_sets = lambda sets, *a, **k: {'ok': len(sets), 'fixed_url': 0, 'fixed_img': 0, 'fixed_dims': 0, 'gone': 0, 'unknown': 0}
CM.media = lambda mid, eid: {'url': f'u/{eid}', 'img': f'i/{eid}', 'price': 1, 'state': 'ok'}
'''

CONSTS = PRE + r'''
import bank_prepare as PR, bank_pending as PD, bank_promote as PM, bank_refresh as RF, bank_keep as BK
show({'prepare': [PR.RULES_PATH, PR.LIVE, PR.CANDIDATE, PR.REPORT],
      'pending': [PD.RULES_PATH, PD.STATE, PD.CANDIDATE, PD.LIVE, PD.DEMO_DATA, PD.PREPARE_REPORT, PD.NIGHT_MAX_AGE_H],
      'promote': [PM.RULES_PATH, PM.LIVE, PM.CANDIDATE, PM.MANIFEST, PM.WORK, PM.ZONES, PM.SCENES],
      'refresh': RF.paths(), 'refresh_rules': RF.RULES_PATH, 'keep': [BK.RULES_PATH, BK.rules()],
      'defaults': [PR.run.__defaults__[2], PD.night.__defaults__[0]],
      'keys': [PD.key(s) for s in json.load(open(PD.LIVE))][:3] + [BK.key(json.load(open(PD.LIVE))[0])]})
'''

CHAIN = PRE + r'''
import bank_prepare as PR, bank_pending as PD, bank_promote as PM, bank_refresh as RF, bank_run as RUN
PD.load_facts = lambda: F
PD._queued = lambda: set()
PM.strict = lambda *a, **k: []
CAND = json.load(open(os.path.join(H, 'cand.json')))
def compose(out, t):
    json.dump(CAND, open(out, 'w'), ensure_ascii=False, indent=1)
    print('compose', out, t)
    return 0
good = {'sets': 12, 'identity_ok': True, 'identity': [], 'gone': 1}
print('== prepare'); print('rc', PR.run(run_id='N1', compose=compose, invariants=lambda o: good))
print('== pending --night'); print('rc', PD.night(run_id='N1'))
print('== pending dry'); print('rc', PD.run(PD.CANDIDATE, False))
print('== queue_skus'); show(PD.queue_skus())
print('== promote'); print('rc', PM.run(run_id='N1', force_ready={1, 4, 8}))
print('== promote held'); show(PM._held())
print('== refresh enabled'); RF._enabled()
print('== refresh write'); sys.argv = ['bank_refresh.py', '--run-id', 'N1']; print('rc', RF.main())
print('== refresh list'); sys.argv = ['bank_refresh.py', 'list']; print('rc', RF.main())
print('== refresh rollback last'); sys.argv = ['bank_refresh.py', 'rollback', 'last']; print('rc', RF.main())
print('== promote held after rollback'); show(PM._held())
print('== refresh release'); sys.argv = ['bank_refresh.py', 'release']; print('rc', RF.main())
print('== refresh recover'); sys.argv = ['bank_refresh.py', 'recover', '--abandon']; print('rc', RF.main())
print('== refresh rollback no arg'); sys.argv = ['bank_refresh.py', 'rollback']; print('rc', RF.main())
print('== prepare to live'); print('rc', PR.run(run_id='N2', out=PR.LIVE, compose=compose))
print('== pending night foreign run'); print('rc', PD.night(run_id='N9'))
print('== promote foreign run'); print('rc', PM.run(run_id='N9'))
'''

WRITE = PRE + r'''
import bank_refresh as RF, bank_pending as PD, set_identity as SID, hashlib, time
P = RF.paths()
live = json.load(open(P['live']))
hyb = json.loads(json.dumps(live))
hyb[0]['items']['столик'] = dict(hyb[0]['items']['столик'], eid='tz', url='u/tz')
hp = os.path.join(H, 'hyb.json'); SID.write_bank(hyb, hp, P['live'])
rows = [{'n': n, 'cell': PD.key(s), 'candidate_hash': PD.candidate_hash(s)} for n, s in enumerate(json.load(open(hp)), 1)]
man = {'at': time.strftime('%Y-%m-%dT%H:%M:%S'), 'run_id': 'W1', 'live_sha': hashlib.sha256(open(P['live'], 'rb').read()).hexdigest(),
       'hybrid': hp, 'hybrid_sha': hashlib.sha256(open(hp, 'rb').read()).hexdigest(), 'promoted': [1], 'cells': rows}
os.makedirs(os.path.dirname(P['manifest']), exist_ok=True)
json.dump(man, open(P['manifest'], 'w'), ensure_ascii=False)
for argv in (['--run-id', 'W1'], ['--run-id', 'W1'], ['list'], ['rollback', 'last'], ['list'], ['--run-id', 'W1'],
             ['release', PD.key(live[0])], ['--run-id', 'W1'], ['--run-id', 'W2'], [], ['--force']):
    print('== bank_refresh', argv); sys.argv = ['bank_refresh.py'] + argv; print('rc', RF.main())
open(P['lock'], 'w').write('x')
print('== locked'); sys.argv = ['bank_refresh.py', '--run-id', 'W1']; print('rc', RF.main())
print('== locked rollback'); sys.argv = ['bank_refresh.py', 'rollback', 'last']; print('rc', RF.main())
'''

SHIPPED = PRE + r'''
import bank_prepare as PR, bank_pending as PD, bank_promote as PM, bank_refresh as RF, bank_keep as BK
drop = lambda R: {k: v for k, v in R.items() if k != 'rooms' and not k.startswith('_')}
show({'prepare': drop(PR.rules()), 'pending': drop(PD.rules()), 'promote': drop(PM.rules()), 'refresh': drop(RF.rules()),
      'keep': BK.rules(), 'pending_enabled': PD.enabled()})
RF._enabled()
'''


def _cli(script, *args):
    return ('cli', script, list(args))


STORIES = {
    'consts-noenv': ('py', CONSTS, {}),
    'consts-env': ('py', CONSTS, {'BANK_CANDIDATE': 'cand-rel.json', 'BANK_PREPARE_REPORT': '~/alt/prep.json',
                                  'BANK_PENDING': '~/alt/pend.json', 'DEMO_DATA': '~/alt/demo.json',
                                  'BANK_PROMOTE': '~/alt/prom.json', 'BANK_PROMOTE_DIR': '~/alt/prom',
                                  'BANK_GENERATIONS': '~/alt/gens'}),
    'consts-empty-env': ('py', CONSTS, {k: '' for k in CLEAR[:7]}),
    'chain': ('py', CHAIN, {}),
    'chain-env': ('py', CHAIN, {'BANK_PREPARE_REPORT': '~/alt/prep.json', 'BANK_PENDING': '~/alt/pend.json',
                                'BANK_PROMOTE': '~/alt/prom.json', 'BANK_PROMOTE_DIR': '~/alt/prom',
                                'BANK_GENERATIONS': '~/alt/gens', 'BANK_MAX_PROMOTE_SHARE': '0.1'}),
    'write': ('py', WRITE, {}),
    'shipped-rules': ('py', SHIPPED, {}, 'shipped'),
    'cli-off': ('cli-seq', [('bank_prepare.py',), ('bank_pending.py', '--night', '--run-id', 'N1'), ('bank_pending.py',),
                            ('bank_promote.py', '--run-id', 'N1'), ('bank_refresh.py', '--enabled'),
                            ('bank_refresh.py', '--run-id', 'N1'), ('bank_refresh.py', 'list'), ('bank_refresh.py', 'rollback'),
                            ('bank_refresh.py', 'recover')], {}, 'off'),
    **{f'selftest-{m}': ('cli-seq', [(f'{m}.py', '--selftest')], {}) for m in MODULES if m != 'room_bank_spec'},
}

REAL_CLOCK = ('selftest-bank_pending',)   # его проверки возраста отчёта — по mtime файла, на заморожённых часах не сходятся

RUNNER = r'''
import os, sys, time, runpy
if os.environ.get('GOLD_FREEZE') == '1':          # селфтесты — на настоящих часах (их проверки возраста файлов)
    _lt, _sf = time.localtime, time.strftime
    time.time = lambda: %r
    time.localtime = lambda t=None: _lt(time.time() if t is None else t)
    time.strftime = lambda f, t=None: _sf(f, time.localtime() if t is None else t)
    os.getpid = lambda: 4242
H = os.environ['GOLD_HERE']
sys.path[:0] = [H, os.environ['GOLD_DEPS']]
import importlib.abc, importlib.util
OWN = {f[:-3] for f in os.listdir(H) if f.endswith('.py')}


class _Own(importlib.abc.MetaPathFinder):
    # модули песочницы — только из неё: соседи (catalog_media, …) ставят свою папку в начало sys.path
    def find_spec(self, name, path=None, target=None):
        return importlib.util.spec_from_file_location(name, os.path.join(H, name + '.py')) if name in OWN else None


sys.meta_path.insert(0, _Own())
mode, arg = sys.argv[1], sys.argv[2]
if mode == 'py':
    code = open(arg, encoding='utf-8').read()
    exec(compile(code, 'scenario', 'exec'), {'__name__': '__scenario__'})
else:
    sys.argv = [os.path.join(H, arg)] + sys.argv[3:]
    try:
        runpy.run_path(sys.argv[0], run_name='__main__')
    except SystemExit as e:
        print('exit', e.code)
        raise
''' % FIXED


def _src(rev: str | None, name: str) -> bytes | None:
    if rev is None:
        p = os.path.join(SCOUT, name)
        return open(p, 'rb').read() if os.path.exists(p) else None
    r = subprocess.run(['git', '-C', ROOT, 'show', f'{rev}:tools/scout/{name}'], capture_output=True)
    return r.stdout if r.returncode == 0 else None


def sandbox(rev: str | None, rules: str) -> str:
    T = tempfile.mkdtemp(prefix='bankgold-')
    S = os.path.join(T, 'tools', 'scout')
    os.makedirs(os.path.join(S, 'rules'))
    os.makedirs(os.path.join(T, 'home'))
    for m in MODULES:
        b = _src(rev, f'{m}.py')
        if b is not None:
            open(os.path.join(S, f'{m}.py'), 'wb').write(b)
    shutil.copy(os.path.join(SCOUT, 'compose2.py'), S)                       # bank_promote читает константы сборщика текстом
    z = os.path.join(T, 'services', 'planner-solver', 'rules')
    os.makedirs(z)
    shutil.copy(os.path.join(ROOT, 'services', 'planner-solver', 'rules', 'zones.json'), z)
    if rules == 'shipped':
        open(os.path.join(S, 'rules', 'bank-candidate.json'), 'wb').write(_src(rev, 'rules/bank-candidate.json'))
    else:
        R = rules_fixture()
        if rules == 'off':
            R.update({f: False for f in ('enabled', 'prepare_enabled', 'promote_enabled', 'write_enabled')})
        json.dump(R, open(os.path.join(S, 'rules', 'bank-candidate.json'), 'w'), ensure_ascii=False, indent=1)
    sys.path.insert(0, SCOUT)
    import set_identity as SID
    live = live_bank()
    SID.ensure_ids(live)
    json.dump(live, open(os.path.join(S, 'sets3.json'), 'w'), ensure_ascii=False)
    json.dump(cand_bank(live), open(os.path.join(T, 'cand.json'), 'w'), ensure_ascii=False)
    skus = {f"{it['mid']}:{it['eid']}": r for s in cand_bank(live) + live for r, it in s['items'].items()}
    open(os.path.join(S, 'skus.json'), 'w').write(json.dumps(skus, ensure_ascii=False, sort_keys=True))
    os.makedirs(os.path.join(T, 'home', 'scout-scenes', 'flat215-demo'))
    json.dump({'variants': [{'id': 'set1'}, {'id': 'set5'}]},
              open(os.path.join(T, 'home', 'scout-scenes', 'flat215-demo', 'demo-data.json'), 'w'))
    open(os.path.join(T, 'runner.py'), 'w').write(RUNNER)
    return T


def norm(b: bytes, T: str) -> bytes:
    import re
    return re.sub(rb'<T>/tmp/[^/\s\'"]+', b'<T>/tmp/<tmp>', b.replace(T.encode(), b'<T>'))


def run_story(name: str, rev: str | None) -> dict:
    st = STORIES[name]
    kind, body, extra_env = st[0], st[1], st[2]
    T = sandbox(rev, st[3] if len(st) > 3 else 'fixture')
    S = os.path.join(T, 'tools', 'scout')
    env = {k: v for k, v in os.environ.items() if k not in CLEAR}
    os.makedirs(os.path.join(T, 'tmp'))
    env.update(HOME=os.path.join(T, 'home'), TZ='UTC', GOLD_HERE=S, GOLD_DEPS=SCOUT, PYTHONHASHSEED='0', TMPDIR=os.path.join(T, 'tmp'),
               GOLD_FREEZE='0' if name in REAL_CLOCK else '1', **extra_env)
    env['GOLD_HERE'] = S
    if 'cand.json' in str(body):
        shutil.copy(os.path.join(T, 'cand.json'), S)
    out = b''
    try:
        if kind == 'py':
            sp = os.path.join(T, 'scenario.py')
            open(sp, 'w', encoding='utf-8').write(body)
            p = subprocess.run([sys.executable, os.path.join(T, 'runner.py'), 'py', sp], cwd=S, env=env, capture_output=True,
                               timeout=600)
            out = p.stdout + p.stderr + f'\nrc {p.returncode}\n'.encode()
        else:
            for argv in body:
                p = subprocess.run([sys.executable, os.path.join(T, 'runner.py'), 'cli', *argv], cwd=S, env=env,
                                   capture_output=True, timeout=600)
                out += f'$ {" ".join(argv)}\n'.encode() + p.stdout + p.stderr + f'rc {p.returncode}\n'.encode()
        files = {}
        for d, dirs, fs in os.walk(T):
            dirs[:] = [x for x in dirs if x != '__pycache__']
            for f in fs:
                rel = os.path.relpath(os.path.join(d, f), T)
                if f.endswith('.py') or rel in ('cand.json',) or rel.startswith(('services/', 'tools/scout/rules/', 'tmp/')) \
                        or f == 'skus.json':
                    continue
                b = open(os.path.join(d, f), 'rb').read()
                if f.endswith('.gz'):
                    b = gzip.decompress(b)
                files[rel] = hashlib.sha256(norm(b, T)).hexdigest()[:16]
        text = norm(out, T).decode('utf-8', 'replace')
        return {'out_sha': hashlib.sha256(text.encode()).hexdigest()[:16], 'files': dict(sorted(files.items())),
                'out': text}
    finally:
        shutil.rmtree(T, ignore_errors=True)


def main(argv: list) -> int:
    if '--show' in argv:
        r = run_story(argv[argv.index('--show') + 1], None)
        print(r['out'])
        print(json.dumps(r['files'], indent=1))
        return 0
    if '--record' in argv:
        rev = argv[argv.index('--rev') + 1] if '--rev' in argv else None
        res = {n: run_story(n, rev) for n in STORIES}
        os.makedirs(os.path.dirname(FIXTURE), exist_ok=True)
        json.dump({'_': 'эталон tests/test_bank_spec_golden.py: вывод и файлы цепочки банка гостиной до этапа Б room-bank-01',
                   'rev': rev or 'worktree', 'stories': res}, open(FIXTURE, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        for n, r in res.items():
            print(f'  {n}: вывод {r["out_sha"]}, файлов {len(r["files"])}')
        print(f'эталон → {FIXTURE}')
        return 0
    ref = json.load(open(FIXTURE, encoding='utf-8'))['stories']
    bad = 0
    for n in STORIES:
        r = run_story(n, None)
        e = ref.get(n)
        same = e is not None and r['out_sha'] == e['out_sha'] and r['files'] == e['files']
        print(('  ✓ ' if same else '  ✗ ') + f'{n}: вывод и {len(r["files"])} файлов как до этапа Б')
        if not same:
            bad += 1
            if e is None:
                print('    нет в эталоне')
                continue
            if r['files'] != e['files']:
                for k in sorted(set(r['files']) | set(e['files'])):
                    if r['files'].get(k) != e['files'].get(k):
                        print(f'    файл {k}: было {e["files"].get(k)}, стало {r["files"].get(k)}')
            if r['out_sha'] != e['out_sha']:
                import difflib
                for ln in list(difflib.unified_diff(e['out'].splitlines(), r['out'].splitlines(), 'было', 'стало', lineterm=''))[:40]:
                    print('    ' + ln)
    print(f'bank_spec golden: расхождений {bad}')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
