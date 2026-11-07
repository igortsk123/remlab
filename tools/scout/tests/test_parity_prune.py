"""Уборка стенда паритета (T-20261107-48/2): `parity_living.prune_runs` держит последние `keep_runs` папок run-* и прогоны,
на которые ссылаются свежий эталон каждой комнаты и эталон команды; data-*, эталоны *.json и чужие папки не трогает; сухой
режим ничего не удаляет; жёсткие ссылки на заморозку data-* не считаются освобождённым местом и заморозку не портят.
Без базы и сети.
    python3 tools/scout/tests/test_parity_prune.py"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
import remlab_tmp  # noqa: E402
remlab_tmp.use('test_parity_prune')

import tempfile  # noqa: E402

import parity_living as P  # noqa: E402

fails = 0


def check(name, cond, extra=''):
    global fails
    print(('OK   ' if cond else 'FAIL ') + name + (f' — {extra}' if extra and not cond else ''))
    fails += 0 if cond else 1


h = tempfile.mkdtemp(prefix='parity-')
os.environ['PARITY_HOME'] = h
R = {'home': h, 'keep_runs': 4, 'rooms': {'living': {}, 'bedroom': {}, 'hall': {}}}
data = os.path.join(h, 'data-20261101-000000')
os.makedirs(os.path.join(data, 'files'))
frozen = os.path.join(data, 'files', 'big.json')
open(frozen, 'w').write('z' * 50000)
runs = [f'run-202611{d:02d}-120000-{t}' for d, t in
        ((1, 'ref-hall'), (2, 'ref-living'), (3, 'cmp-living'), (4, 'ref-bedroom'), (5, 'cmp-bedroom'),
         (6, 'ref-living'), (7, 'cmp-living'), (8, 'cmp-bedroom'), (9, 'ref-bedroom'))]
for r in runs:
    d = os.path.join(h, r, 'repo')
    os.makedirs(d)
    open(os.path.join(d, 'own.txt'), 'w').write('o' * 20000)
    os.link(frozen, os.path.join(d, 'big.json'))       # данные — жёсткой ссылкой на заморозку


def ref(name, run, t):
    p = os.path.join(h, name)
    json.dump({'stand': os.path.join(h, run), 'artifacts': {'demo': {'dump': os.path.join(h, run, 'repo', 'demo.json')}}}, open(p, 'w'))
    os.utime(p, (t, t))
    return p


now = time.time()
ref('hall-20261101-120500.json', runs[0], now - 9 * 86400)       # единственный эталон прихожей — держим его прогон
ref('living-20261102-120500.json', runs[1], now - 8 * 86400)     # старый эталон гостиной — не свежий
ref('living-20261106-120500.json', runs[5], now - 3 * 86400)     # свежий эталон гостиной
old_ref = ref('bedroom-20261104-120500.json', runs[3], now - 5 * 86400)
ref('bedroom-20261109-120500.json', runs[8], now - 1 * 86400)
open(os.path.join(h, 'living-20261101-000000.json.bak'), 'w').write('{}')
os.makedirs(os.path.join(h, 't70-2-0940'))

dry = P.prune_runs(R, apply=False)
want = {runs[2], runs[4]}   # последние 4 = 6..9; эталоны: прихожая (1), гостиная свежая (6), спальня свежая (9)
check('сухой прогон: к удалению — не последние 4 и не прогоны свежих эталонов', set(dry['gone']) == want | {runs[1], runs[3]},
      str(sorted(dry['gone'])))
check('сухой прогон ничего не удаляет', all(os.path.isdir(os.path.join(h, r)) for r in runs))
check('держим прогон единственного эталона прихожей (старше 4 последних)', runs[0] in dry['held'], str(dry['held']))
check('освобождаемое — только свои файлы, не жёсткие ссылки на заморозку', 4 * 20000 <= dry['bytes'] < 4 * 50000, str(dry['bytes']))
got = P.prune_runs(R, apply=True, extra_refs=(old_ref,))
check('эталон команды (--ref) держит свой прогон', runs[3] not in got['gone'] and os.path.isdir(os.path.join(h, runs[3])))
check('удалены ровно лишние', sorted(got['gone']) == sorted({runs[1], runs[2], runs[4]}) and not got['fails'], str(got))
check('удалённых нет на диске', not any(os.path.exists(os.path.join(h, r)) for r in got['gone']))
check('оставшиеся на месте', all(os.path.isdir(os.path.join(h, r)) for r in (runs[0], runs[3], *runs[5:])))
check('заморозка data-* цела (жёсткая ссылка не утащила файл)', open(frozen).read() == 'z' * 50000)
check('эталоны *.json и чужие папки целы', len([n for n in os.listdir(h) if n.endswith('.json')]) == 5
      and os.path.isdir(os.path.join(h, 't70-2-0940')) and os.path.exists(os.path.join(h, 'living-20261101-000000.json.bak')))
again = P.prune_runs(R, apply=True, extra_refs=(old_ref,))
check('повтор — ничего', again['gone'] == [], str(again))
check('правила стенда: keep_runs = 4', P.rules().get('keep_runs') == 4)
ref('hall-20261110-120500.json', 'run-20261110-120000-ref-hall', now)   # эталон на прогон, которого нет
lost = P.prune_runs(R, apply=False)
check('эталон на удалённый прогон — назван, в «держим» не числится', lost['lost'] == ['run-20261110-120000-ref-hall']
      and 'run-20261110-120000-ref-hall' not in lost['held'], str(lost))
print(f'\n{"OK" if not fails else "FAIL"}: провалов {fails}')
sys.exit(1 if fails else 0)
