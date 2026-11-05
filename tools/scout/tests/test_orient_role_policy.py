"""Смена политики ролей адресно инвалидирует «симметрична по роли» (T-20261105-36/3, Codex room-bind п.3).

Ключ ревизии `sku|sha16|orient-v1` политику ролей не содержит: в e6a1e01e DIRECTED расширен (кровать, тумба
прикроватная, шкаф), а `pending_meshes()` пропускал тот же ключ — старые «симметрична по роли» у этих ролей не
пересчитались бы никогда. Теперь решение несёт отпечаток `role_policy()`, устаревшие видит `stale_by_role_policy`,
в пачку они идут только с явным `--recheck-roles` (пересчёт платный по VLM).

  1) Отпечаток выводится из DIRECTED: добавили роль — отпечаток другой (забыть поднять версию нельзя).
  2) Смена DIRECTED без инвалидации — провал: старое «симметрична» новой направленной роли устарело и попадает
     в пачку с --recheck-roles; без флага — нет (cron с --vlm сам платить не начнёт).
  3) Старые записи без отпечатка: шкаф/кровать — устарели; ваза — нет; роль «?» — да (её теперь даст manifest).
  4) Человек и unusable — никогда; уже со свежим отпечатком — нет (пересчёт не зацикливается).
  5) decide ставит отпечаток в решение; шкаф теперь направленный.
    ~/venvs/scout/bin/python tools/scout/tests/test_orient_role_policy.py"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
import orient_worker as W  # noqa: E402

fails = 0


def check(name, cond, extra=''):
    global fails
    print(('OK   ' if cond else 'FAIL ') + name + (f' — {extra}' if extra and not cond else ''))
    fails += 0 if cond else 1


SYM = 'symmetric_by_role'
old_pol = W.role_policy()

# 1–2) смена DIRECTED: новая направленная роль
W.DIRECTED = set(W.DIRECTED) | {'роль-тест'}
new_pol = W.role_policy()
check('1) отпечаток выводится из DIRECTED: добавили роль — другой', new_pol != old_pol, f'{old_pol} == {new_pol}')
rec = {'source': SYM, 'role': 'роль-тест', 'role_policy': old_pol}
check('2) «симметрична» новой направленной роли при прежней политике — устарело',
      W.stale_by_role_policy('auto_resolved', rec))

rows = [['7:1|aaaa|orient-v1', 'auto_resolved', SYM, 'роль-тест', old_pol],     # устарело
        ['7:2|bbbb|orient-v1', 'auto_resolved', SYM, 'ваза', old_pol],           # ваза — не направленная
        ['7:3|cccc|orient-v1', 'auto_resolved', 'orienter+vlm_agree', 'комод', ''],  # не «симметрична»
        ['7:4|dddd|orient-v1', 'human_resolved', SYM, 'роль-тест', '']]          # решение человека
SHA = {'/m/7_1/h0/model.glb': 'aaaa', '/m/7_2/h0/model.glb': 'bbbb', '/m/7_3/h0/model.glb': 'cccc',
       '/m/7_4/h0/model.glb': 'dddd', '/m/7_5/h0/model.glb': 'eeee'}             # 7:5 — новый меш без записи
W.db = lambda sql, quiet=True: rows
W.all_meshes = lambda: sorted(SHA)
W._sha16 = lambda p: SHA[p]
W._sha_flush = lambda: None
with_flag = {rk for rk, _, _ in W.pending_meshes(100, recheck_roles=True)}
no_flag = {rk for rk, _, _ in W.pending_meshes(100)}
check('2) с --recheck-roles: устаревшее + новый меш, остальные нет',
      with_flag == {'7:1|aaaa|orient-v1', '7:5|eeee|orient-v1'}, f'{sorted(with_flag)}')
check('2) без флага: только новый меш (платный пересчёт не стартует сам)', no_flag == {'7:5|eeee|orient-v1'},
      f'{sorted(no_flag)}')

# 3–4) записи до отпечатка (как в БД сейчас) и защита
W.DIRECTED = set(W.DIRECTED) - {'роль-тест'}
for role, want in (('шкаф', True), ('кровать', True), ('тумба прикроватная', True), ('ваза', False),
                   ('?', True), ('', True), ('пуф', False)):
    check(f'3) старая запись без отпечатка, роль {role!r}: устарело={want}',
          W.stale_by_role_policy('auto_resolved', {'source': SYM, 'role': role}) == want)
for st in ('human_resolved', 'human', 'unusable'):
    check(f'4) статус {st} — никогда', not W.stale_by_role_policy(st, {'source': SYM, 'role': 'шкаф'}))
check('4) свежий отпечаток — не устарело (роль «?» не пересчитывается по кругу)',
      not W.stale_by_role_policy('auto_resolved', {'source': SYM, 'role': '?', 'role_policy': W.role_policy()}))
check('4) не «симметрична» — не трогаем', not W.stale_by_role_policy('review_pending', {'source': 'vlm_unsure',
                                                                                      'role': 'шкаф'}))

# 5) decide ставит отпечаток; шкаф — направленный
import tempfile  # noqa: E402

W.role_of = lambda sku: ('шкаф', 'Шкаф Тест', '')
W.canonical_parts = lambda glb, R: {}
with tempfile.TemporaryDirectory(prefix='orient-pol-') as td:
    glb = os.path.join(td, 'model.glb')
    open(glb, 'wb').write(b'glTF-fake')
    r = W.decide('x:1', glb, {'R': [[1, 0, 0], [0, 1, 0], [0, 0, 1]], 'quat_wxyz': [1, 0, 0, 0], 'flip_prob': 0.6,
                              'pset_size': 1}, use_vlm=False)
    check('5) отпечаток политики в решении', r.get('role_policy') == W.role_policy(), f"{r.get('role_policy')}")
    check('5) шкаф направленный — ждёт VLM, не «симметрична»', r.get('source') == 'awaiting_vlm', f"{r.get('source')}")
    W.role_of = lambda sku: ('ваза', 'Ваза', '')
    r = W.decide('x:2', glb, {'R': [[1, 0, 0], [0, 1, 0], [0, 0, 1]], 'quat_wxyz': [1, 0, 0, 0], 'flip_prob': 0.6,
                              'pset_size': 1}, use_vlm=False)
    check('5) «симметрична» со свежим отпечатком сразу не устаревшая',
          r.get('source') == SYM and not W.stale_by_role_policy(r['status'], r), f"{r.get('source')}")

print('test_orient_role_policy:', 'FAIL' if fails else 'OK')
sys.exit(1 if fails else 0)
