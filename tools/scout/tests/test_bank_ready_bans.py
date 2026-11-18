#!/usr/bin/env python3
"""Запреты банка ДО «меш готов» (T-20261118-04/22/2, директор 18.11) — `bank_ready.classify`, без базы.

ЗАЧЕМ. Готовность меша («есть годная ревизия текущего фото и решённая ориентация») ничего не знает про решения людей и карантин.
В набор банка такой меш ставить нельзя: владелец велел переделать (`redo`), файл в жёстком карантине (`mesh_quarantine` cut/reject без
мягких — кривая по осям, витрина его вычитает из индекса), либо товар помечен `rejected`/`quarantine`. Правило по признакам, для всех ячеек.
Отдельно от `bank_ready --selftest`: тот печатается побайтно в golden-эталоне цепочки банка (`test_bank_spec_golden`).

  python3 tools/scout/tests/test_bank_ready_bans.py
"""
from __future__ import annotations

import os
import sys
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import remlab_tmp  # noqa: E402
remlab_tmp.use('test_bank_ready_bans')

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bank_ready import Facts, classify  # noqa: E402

bad = 0


def ok(name, cond, extra=''):
    global bad
    print(('  ✓ ' if cond else '  ✗ ') + name + (f' — {extra}' if extra and not cond else ''))
    bad += 0 if cond else 1


P = lambda role, **k: {'role': role, 'status': 'none', 'eligible': True, 'rep': None, 'w': 100, 'd': 50, 'h': 80,  # noqa: E731
                       'dia': None, 'tr': False, 'proven': False, **k}
strat = lambda r: 'mesh'  # noqa: E731
pr = {'s:clean': P('диван'), 's:okredo': P('диван'), 's:okrej': P('диван', status='rejected'), 's:okq': P('диван', status='quarantine'),
      's:okhard': P('диван'), 's:okhardv': P('диван', rep='s:okhard'), 's:okrejv': P('диван', rep='s:okrej'),
      's:okredov': P('диван', rep='s:okredo'), 's:nomesh': P('диван')}
M = {s: {'state': 'available', 'url': f'u/{s}', 'img': f'i/{s}'} for s in pr}
mesh = set(pr) - {'s:nomesh'}
F = Facts(pr, failed=set(), strategy=strat, media=M.get, mesh_ok=mesh, decisions={'s:okredo': {'decision': 'redo'}},
          with_gen={'s:okrej'}, hard_quar={'s:okhard'})
c = lambda s, f=F: classify('диван', s, {'url': f'u/{s}'}, f)  # noqa: E731

print('[1] запреты на готовом меше')
ok('чистый готовый меш — ready (запреты его не трогают)', c('s:clean') == ('ready', None, None))
ok('владелец велел переделать — redo, не ready; цвет-вариант через представителя — тоже',
   c('s:okredo')[::2] == ('redo', None) and c('s:okredov')[::2] == ('redo', None))
ok('жёсткий карантин файла — wait_asset/review; вариант через представителя — тоже',
   c('s:okhard') == ('wait_asset', 'меш в карантине — ждёт решения', 'review') and c('s:okhardv')[::2] == ('wait_asset', 'review'))
ok('товар rejected — не ready (триаж legacy_unknown); вариант — тоже', c('s:okrej')[0] == 'legacy_unknown' and c('s:okrejv')[0] == 'legacy_unknown')
ok('товар в карантине (products.mesh_status) — wait_asset/review', c('s:okq')[::2] == ('wait_asset', 'review'))

print('[2] неготовый меш — прежнее поведение')
F2 = Facts(pr, set(), strat, media=M.get, mesh_ok=mesh, hard_quar={'s:nomesh'})
ok('жёсткий карантин у НЕГОТОВОГО меша ничего не меняет — спрос мешей как был', c('s:nomesh', F2)[::2] == ('wait_asset', 'mesh'))
ok('без hard_quar (старые вызовы Facts) — ready как раньше', c('s:okhard', Facts(pr, set(), strat, media=M.get, mesh_ok=mesh)) == ('ready', None, None))

print('[3] запреты старше готовности, но младше геометрии и каталога')
Fg = Facts({**pr, 's:okhard': P('диван', h=None)}, set(), strat, media=M.get, mesh_ok=mesh, hard_quar={'s:okhard'})
ok('нет высоты — по-прежнему wait_catalog (гейт геометрии раньше)', c('s:okhard', Fg)[0] == 'wait_catalog')

print('ИТОГО: ' + ('всё в норме' if not bad else f'провалов {bad}'))
sys.exit(1 if bad else 0)
