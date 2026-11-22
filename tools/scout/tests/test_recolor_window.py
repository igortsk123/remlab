"""ПУТЬ ПЕРЕКРАСКИ НА ЖИВОЕ (`salad/recolor_window.py`, `salad/recolor_rollback.sh`, T-20261119-03/2): без базы, сети и мешей — подменены `ps`, запуск шагов,
гейт вариантов и перенос ориентации; поколения v2 — временные папки с пустышками GLB. Случаи:
① `pre`: нет поколения / несколько без `gen` / `gen` выбирает / нет файла перекраски / уже перекрашен / гейт отказал / перенос не «copy» — пропуск с причиной, остальные OK;
② `window`: занято до начала — код 4 и ни одной записи; сухо (по умолчанию) — ничего не пишется; `--apply` — порядок записи v2 → ingest → carry → bindings, отказавшие гейтом
   не пишутся и не переносятся, волна посреди окна — код 5 (запись v2 осталась, дальше не идём), шаг упал — код 6;
③ `backup`: непустая папка — отказ, копии лежат под `<sid>/v2-model.glb`; ④ `publish`: сухо — только план, занято — код 4;
⑤ `recolor_rollback.sh`: сухой прогон печатает все шаги (включая лёгкие копии), нет model.orig.glb — код 3, нет прод-доступа в тесте (`ROLLBACK_SKIP_PROD`).
    python tools/scout/tests/test_recolor_window.py   (нужны numpy и bash)"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'salad'))
sys.path.insert(0, os.path.join(HERE, '..'))
import recolor_put_v2 as PUT  # noqa: E402
import recolor_window as W  # noqa: E402
import remlab_tmp  # noqa: E402
TMP = remlab_tmp.use('test_recolor_window')   # временное — на диске, убирается при выходе (T-20261107-13)

fails = []


def check(name, cond, extra=''):
    print(('OK   ' if cond else 'FAIL ') + name + (f'  [{extra}]' if extra else ''))
    if not cond:
        fails.append(name)


ROOT = os.path.join(TMP, 'v2')
PUT.V2 = ROOT
W.V2 = ROOT


def make_gen(sku, gens, orig=False):
    for g, body in gens.items():
        d = f'{ROOT}/{sku.replace(":", "_")}/{g}'
        os.makedirs(d, exist_ok=True)
        open(f'{d}/model.glb', 'wb').write(body)
        json.dump({'seed': 1}, open(f'{d}/manifest.json', 'w'))
        if orig:
            open(f'{d}/model.orig.glb', 'wb').write(b'ORIG')


def newfile(name, body=b'NEW'):
    p = os.path.join(TMP, name)
    open(p, 'wb').write(body)
    return p


OK_GATE = lambda fam, n, o, tp: {'ok': True, 'reasons': [], 'n_variants': 2}   # noqa: E731
BAD_GATE = lambda fam, n, o, tp: {'ok': False, 'reasons': [f'{fam}:v1: новый упор: потолок']}   # noqa: E731
COPY = lambda sku, o, n: {'action': 'copy', 'why': 'геометрия совпала', 'geometry_sha': 'x'}   # noqa: E731

# ── ① pre ──
make_gen('a:one', {'g1': b'OLD1'})
make_gen('a:two', {'g1': b'A', 'g2': b'B'})
make_gen('a:two2', {'g1': b'A', 'g2': b'B'})
make_gen('a:done', {'g1': b'OLD'}, orig=True)
make_gen('a:nocopy', {'g1': b'OLD'})
make_gen('a:bad', {'g1': b'OLD'})
jobs = [
    {'sku': 'a:one', 'k': 1, 'new': newfile('n1.glb')},
    {'sku': 'a:none', 'k': 2, 'new': newfile('n2.glb')},
    {'sku': 'a:two', 'k': 3, 'new': newfile('n3.glb')},
    {'sku': 'a:two2', 'k': 4, 'new': newfile('n4.glb'), 'gen': 'g2'},
    {'sku': 'a:one', 'k': 5, 'new': os.path.join(TMP, 'нет.glb')},
    {'sku': 'a:done', 'k': 6, 'new': newfile('n6.glb')},
    {'sku': 'a:nocopy', 'k': 7, 'new': newfile('n7.glb')},
    {'sku': 'a:bad', 'k': 8, 'new': newfile('n8.glb')},
]
gate_by = lambda fam, n, o, tp: BAD_GATE(fam, n, o, tp) if fam == 'a:bad' else OK_GATE(fam, n, o, tp)   # noqa: E731
carry_by = lambda sku, o, n: ({'action': 'skip', 'why': 'геометрия изменилась'} if sku == 'a:nocopy' else COPY(sku, o, n))   # noqa: E731
res = {i['k']: i for i in W.pre(jobs, os.path.join(TMP, 'w1'), gate_fn=gate_by, carry_fn=carry_by)}
check('pre: обычное задание — OK', res[1]['skip'] is None and res[1]['carry']['action'] == 'copy')
check('pre: нет поколения — пропуск', 'поколение' in (res[2]['skip'] or ''))
check('pre: несколько поколений без gen — пропуск «укажи живое»', 'укажи живое' in (res[3]['skip'] or ''))
check('pre: gen выбирает поколение — OK', res[4]['skip'] is None and res[4]['gen_dir'].endswith('/a_two2/g2'))
check('pre: нет файла перекраски — пропуск', 'нет файла' in (res[5]['skip'] or ''))
check('pre: уже перекрашен (model.orig.glb) — пропуск', 'уже есть model.orig.glb' in (res[6]['skip'] or ''))
check('pre: перенос ориентации не «copy» — пропуск', 'перенос ориентации: skip' in (res[7]['skip'] or ''))
check('pre: гейт вариантов отказал — пропуск с причиной', 'гейт вариантов' in (res[8]['skip'] or '') and 'потолок' in res[8]['skip'])
check('pre: ничего не записано', open(f'{ROOT}/a_one/g1/model.glb', 'rb').read() == b'OLD1' and not os.path.exists(f'{ROOT}/a_one/g1/model.orig.glb'))
check('pre: итог в pre.json', os.path.exists(os.path.join(TMP, 'w1', 'pre.json')))

# ── ② window ──
make_gen('b:ok', {'g1': b'OLD-OK'})
make_gen('b:bad', {'g1': b'OLD-BAD'})
wjobs = [{'sku': 'b:ok', 'k': 1, 'new': newfile('wn1.glb', b'NEW-OK')}, {'sku': 'b:bad', 'k': 2, 'new': newfile('wn2.glb', b'NEW-BAD')}]
gate_w = lambda fam, n, o, tp: BAD_GATE(fam, n, o, tp) if fam == 'b:bad' else OK_GATE(fam, n, o, tp)   # noqa: E731
calls = []
runner = lambda cmd: (calls.append(os.path.basename(cmd[1])) or (0, '{\n "action": "copy", "written": true, "why": "x"\n}\n' if 'carry' in cmd[1] else 'снимок: x'))   # noqa: E731
code = W.window(wjobs, os.path.join(TMP, 'w2'), '/нет', True, ps=lambda: 'python mesh_wave_start.py --launch', runner=runner, gate_fn=gate_w)
check('window: занято до начала — код 4, ни одной записи и шага', code == 4 and not calls and not os.path.exists(f'{ROOT}/b_ok/g1/model.orig.glb'))
code = W.window(wjobs, os.path.join(TMP, 'w2'), '/нет', False, ps=lambda: '', runner=runner, gate_fn=gate_w)
check('window: сухо — код 0, файлы не тронуты, шагов нет', code == 0 and not calls and open(f'{ROOT}/b_ok/g1/model.glb', 'rb').read() == b'OLD-OK'
      and json.load(open(os.path.join(TMP, 'w2', 'window-done.json'))) == ['b:ok'])
bk = os.path.join(TMP, 'bk2')
os.makedirs(f'{bk}/b_ok')
open(f'{bk}/b_ok/v2-model.glb', 'wb').write(b'OLD-OK')
code = W.window(wjobs, os.path.join(TMP, 'w2'), bk, True, ps=lambda: '', runner=runner, gate_fn=gate_w)
check('window --apply: записан только прошедший гейт, отказавший цел', code == 0 and open(f'{ROOT}/b_ok/g1/model.glb', 'rb').read() == b'NEW-OK'
      and open(f'{ROOT}/b_bad/g1/model.glb', 'rb').read() == b'OLD-BAD' and not os.path.exists(f'{ROOT}/b_bad/g1/model.orig.glb'))
check('window --apply: порядок ingest → carry (одна) → bindings', calls == ['ingest_registry.py', 'recolor_carry_orientation.py', 'room_bindings.py'], str(calls))

make_gen('c:one', {'g1': b'OLD-C'})
cj = [{'sku': 'c:one', 'k': 1, 'new': newfile('wc.glb', b'NEW-C')}]
seq = iter(['', '', 'идёт ingest_registry'])   # свободно в начале и перед ingest, волна встала перед carry
calls.clear()
code = W.window(cj, os.path.join(TMP, 'w3'), bk, True, ps=lambda: next(seq, ''), runner=runner, gate_fn=OK_GATE)
check('window: волна встала посреди окна — код 5, запись v2 осталась, carry и bindings не идут', code == 5 and calls == ['ingest_registry.py']
      and open(f'{ROOT}/c_one/g1/model.glb', 'rb').read() == b'NEW-C', str(calls))
make_gen('d:one', {'g1': b'OLD-D'})
dj = [{'sku': 'd:one', 'k': 1, 'new': newfile('wd.glb', b'NEW-D')}]
code = W.window(dj, os.path.join(TMP, 'w4'), bk, True, ps=lambda: '', runner=lambda cmd: (3, 'упал'), gate_fn=OK_GATE)
check('window: ingest упал — код 6', code == 6)
check('busy: свои процессы не считаются занятостью', W.busy(W.WINDOW_BUSY, ps=lambda: 'python recolor_window.py window x\nbash recolor_rollback.sh a:b') == ''
      and 'batch_show' in W.busy(W.WINDOW_BUSY, ps=lambda: 'python -u batch_show.py --batch 2000'))

# ── ③ backup ──
make_gen('e:one', {'g1': b'OLD-E'})
bj = [{'sku': 'e:one', 'k': 1, 'new': newfile('we.glb')}]
dst = os.path.join(TMP, 'bk-new')
W.backup(bj, dst)
check('backup: v2-model.glb и манифест скопированы под <sid>/', open(f'{dst}/e_one/v2-model.glb', 'rb').read() == b'OLD-E' and os.path.exists(f'{dst}/e_one/v2-manifest.json'))
try:
    W.backup(bj, dst)
    check('backup: непустая папка — отказ', False)
except AssertionError as e:
    check('backup: непустая папка — отказ', 'не пуста' in str(e))

# ── ④ publish ──
os.makedirs(os.path.join(TMP, 'w5'), exist_ok=True)
json.dump(['e:one'], open(os.path.join(TMP, 'w5', 'window-done.json'), 'w'))
check('publish: сухо — код 0, ничего не запускает', W.publish(bj, os.path.join(TMP, 'w5'), None, False, ps=lambda: '', sh=lambda c: (_ for _ in ()).throw(RuntimeError('не должно'))) == 0)
check('publish --apply: занято — код 4', W.publish(bj, os.path.join(TMP, 'w5'), None, True, ps=lambda: 'bash refresh_daily.sh', sh=lambda c: (_ for _ in ()).throw(RuntimeError('не должно'))) == 4)

# ── ⑤ recolor_rollback.sh ──
SH = os.path.join(HERE, '..', 'salad', 'recolor_rollback.sh')
home = os.path.join(TMP, 'home')
gd = f'{home}/scout-scenes/meshes-hunyuan/meshes/hunyuan21/v2/f_x/gen1'
os.makedirs(gd)
open(f'{gd}/model.glb', 'wb').write(b'NEW')
env = {**os.environ, 'HOME': home, 'ROLLBACK_SKIP_PROD': '1'}
r = subprocess.run(['bash', SH, 'f:x'], capture_output=True, text=True, env=env)
check('rollback: нет model.orig.glb — код 3', r.returncode == 3 and 'откатывать нечего' in r.stdout, r.stdout[-120:])
open(f'{gd}/model.orig.glb', 'wb').write(b'ORIG')
r = subprocess.run(['bash', SH, 'f:x'], capture_output=True, text=True, env=env)
check('rollback: сухой прогон — код 0, все шаги напечатаны, файлы не тронуты',
      r.returncode == 0 and r.stdout.count('(сухо)') >= 8 and open(f'{gd}/model.glb', 'rb').read() == b'NEW' and not os.path.exists(f'{gd}/model.recolor.glb'), r.stdout[-300:])
check('rollback: в плане лёгкие копии (1024 и -lite) и порядок ingest → bindings → gallery → rsync',
      '-lite' in r.stdout and r.stdout.index('ingest_registry') < r.stdout.index('room_bindings') < r.stdout.index('gallery_build') < r.stdout.index('rsync'))
r = subprocess.run(['bash', SH, 'f:x', '--dry-run'], capture_output=True, text=True, env=env)
check('rollback: --dry-run — то же, что по умолчанию', r.returncode == 0 and '(сухо)' in r.stdout and 'ВЫПОЛНЯЮ' not in r.stdout)

print('\nПРОВАЛЕНО: ' + ', '.join(fails) if fails else '\nвсё прошло')
sys.exit(1 if fails else 0)
