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
import json
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

# 6) СМЕНА РОЛИ ТОВАРА — в любую сторону (T-20261105-56/5): роль решения ≠ текущей → устарело
POL = W.role_policy()
for old, cur, want, what in (
        ('пуф', 'шкаф', True, 'симметричная → направленная (при свежем отпечатке политики)'),
        ('диван', 'пуф', True, 'направленная → симметричная (пуф «как диван» до T-53)'),
        ('диван', 'кресло', True, 'направленная → другая направленная'),
        ('ваза', 'столик', True, 'симметричная → другая симметричная'),
        ('диван', 'диван', False, 'роль та же — не трогаем'),
        ('диван', '?', False, 'текущая роль неизвестна — не судим'),
        ('', 'пуф', False, 'роль решения неизвестна — это забота политики ролей'),
        ('диван', '', False, 'текущая роль пустая — не судим')):
    src = SYM if not W.directed_role(old or '?') else 'orienter+vlm_agree'
    check(f'6) {what}: устарело={want}',
          W.role_changed('auto_resolved', {'source': src, 'role': old, 'role_policy': POL}, cur) == want)
    check(f'6) общее правило stale_by_role то же: {what}',
          W.stale_by_role('auto_resolved', {'source': src, 'role': old, 'role_policy': POL}, cur) == want)
for st in ('human_resolved', 'human', 'unusable'):
    check(f'6) {st} не перерешается при смене роли',
          not W.role_changed(st, {'source': 'human:front_0', 'role': 'диван'}, 'пуф')
          and not W.stale_by_role(st, {'source': 'human:front_0', 'role': 'диван'}, 'пуф'))
check('6) review/vlm_pending со сменой роли — тоже устарело (решения нет — пересчёт по текущей роли)',
      W.role_changed('vlm_pending', {'source': 'awaiting_vlm', 'role': 'диван'}, 'пуф'))

# 7) role_index = role_of массово (тот же порядок: mesh_demand, затем products; «?» — нет роли каталога)
DEM = {'1:1': 'пуф'}
PROD = {'1:1': 'диван', '1:2': 'пуф', '1:3': None}


def fake_db(sql, quiet=True):
    """Массовый запрос (`role_index`) отдаёт sku первым столбцом, поштучный (`role_of`) — роль первой."""
    bulk = 'select sku' in sql or "select shop_mid||':'||external_id" in ' '.join(sql.split())
    if 'from mesh_demand' in sql:
        return [([s] if bulk else []) + [r, 'Имя ' + s] + ([] if bulk else ['']) for s, r in DEM.items() if q_in(s, sql)]
    if 'from products' in sql:
        return [([s] if bulk else []) + [r if r is not None else '?', 'Имя ' + s] + ([] if bulk else [''])
                for s, r in PROD.items() if q_in(s, sql)]
    return STATE


def q_in(s, sql):
    return f"'{s}'" in sql


STATE: list = []
W.db = fake_db
idx = W.role_index(['1:1', '1:2', '1:3', '1:9', '?'])
check('7) role_index: mesh_demand сильнее products', idx.get('1:1', ('',))[0] == 'пуф', f'{idx}')
check('7) role_index: нет в mesh_demand — products; NULL — «?»; нет нигде — нет ключа',
      idx.get('1:2', ('',))[0] == 'пуф' and idx.get('1:3', ('',))[0] == '?' and '1:9' not in idx, f'{idx}')
import orient_worker as W2  # noqa: E402 — role_of настоящий (выше его подменили для decide)
import importlib  # noqa: E402

W2 = importlib.reload(W2)
W2.db = fake_db
for s in ('1:1', '1:2', '1:3'):
    check(f'7) role_of({s}) == role_index[{s}]', W2.role_of(s)[0] == W2.role_index([s])[s][0])

# 8) пачка: смена роли ловится по манифесту, человек — нет; без флага — нет; тень — только устаревшие
with tempfile.TemporaryDirectory(prefix='orient-role-') as td:
    def mesh(sku, man_role):
        d = os.path.join(td, sku.replace(':', '_'), 'h0')
        os.makedirs(d)
        open(os.path.join(d, 'model.glb'), 'wb').write(b'x')
        json.dump({'role': man_role}, open(os.path.join(d, 'manifest.json'), 'w', encoding='utf-8'), ensure_ascii=False)
        return os.path.join(d, 'model.glb')

    G = {'2:1': mesh('2:1', 'диван'),      # пуф, решён «как диван»: каталог — пуф
         '2:2': mesh('2:2', 'диван'),      # то же, но решение человека
         '2:3': mesh('2:3', 'диван'),      # кровать без роли каталога: роль из манифеста «диван» = решению — не устарело
         '2:4': mesh('2:4', 'кресло'),     # диван → кресло (направленная → направленная)
         '2:5': mesh('2:5', 'пуф')}        # новый меш без решения
    SH = {g: f'sha{s[-1]}' for s, g in G.items()}
    W2.all_meshes = lambda: sorted(G.values())
    W2._sha16 = lambda p: SH[p]
    W2._sha_flush = lambda: None
    DEM = {}
    PROD = {'2:1': 'пуф', '2:2': 'пуф', '2:3': None, '2:4': 'кресло'}
    rk = {s: f'{s}|{SH[g]}|orient-v1' for s, g in G.items()}
    STATE = [[rk['2:1'], 'auto_resolved', 'orienter+seat_agree', 'диван', POL],
             [rk['2:2'], 'human_resolved', 'human:front_0', 'диван', POL],
             [rk['2:3'], 'auto_resolved', 'orienter+seat_agree', 'диван', POL],
             [rk['2:4'], 'auto_resolved', 'orienter+vlm_agree', 'диван', POL]]
    with_flag = {r for r, _, _ in W2.pending_meshes(100, recheck_roles=True)}
    no_flag = {r for r, _, _ in W2.pending_meshes(100)}
    only = {r for r, _, _ in W2.pending_meshes(100, stale_only=True)}
    check('8) с --recheck-roles: пуф «как диван» и диван→кресло + новый меш',
          with_flag == {rk['2:1'], rk['2:4'], rk['2:5']}, f'{sorted(with_flag)}')
    check('8) human_resolved не перерешается, роль из манифеста = решению — не устарело',
          rk['2:2'] not in with_flag and rk['2:3'] not in with_flag)
    check('8) без флага — только новый меш', no_flag == {rk['2:5']}, f'{sorted(no_flag)}')
    check('8) тень (stale_only) — только устаревшие, без новых', only == {rk['2:1'], rk['2:4']}, f'{sorted(only)}')
    found = {r: (why, cur) for r, _, _, why, cur in W2.stale_meshes()}
    check('8) причина и текущая роль', found.get(rk['2:1']) == ('role', 'пуф') and found.get(rk['2:4']) == ('role', 'кресло'),
          f'{found}')

    # 9) перерешение пишет текущую роль — по кругу не гоняется; тень не пишет в БД
    W2.canonical_parts = lambda glb, R: {}
    W2.infer_seat_front = lambda parts, role, has_back=True: {'status': 'confident', 'front_yaw': W2.FRONT_CANON_YAW}
    res = W2.decide('2:1', G['2:1'], {'R': [[1, 0, 0], [0, 1, 0], [0, 0, 1]], 'quat_wxyz': [1, 0, 0, 0],
                                        'flip_prob': 0.6, 'pset_size': 1}, use_vlm=False)
    check('9) пуф перерешён «симметрична по роли» с ролью «пуф»', res.get('source') == SYM and res.get('role') == 'пуф',
          f"{res.get('source')} {res.get('role')}")
    check('9) новое решение не устаревшее (нет цикла)', not W2.stale_by_role(res['status'], res, 'пуф'))
    row = W2.overlay_row(res)
    check('9) строка тени в формате индекса вида сверху (статус, источник, yaw, отпечаток, роль)',
          len(row) == 5 and row[0] == 'auto_resolved' and row[4] == 'пуф' and str(row[3]).startswith('shadow-'), f'{row}')
    writes = []
    W2.db = lambda sql, quiet=True: (writes.append(sql) if sql.lstrip().lower().startswith('insert') else fake_db(sql))
    shd = os.path.join(td, 'shadow')
    W2.ORIENTER_PY = sys.executable
    fake_inf = os.path.join(td, 'fake_infer.py')
    open(fake_inf, 'w').write(
        "import json,sys\nl=open(sys.argv[sys.argv.index('--list')+1]).read().split()\n"
        "json.dump({g:{'R':[[1,0,0],[0,1,0],[0,0,1]],'quat_wxyz':[1,0,0,0],'flip_prob':0.6,'pset_size':1} for g in l},"
        "open(sys.argv[sys.argv.index('--out')+1],'w'))\n")
    W2.HERE = td
    os.rename(fake_inf, os.path.join(td, 'orient_infer.py'))
    W2.run(100, False, True, shadow=shd)
    ov = json.load(open(os.path.join(shd, 'index-overlay.json'), encoding='utf-8'))
    check('9) тень: в БД ни одной записи', writes == [], f'{writes[:1]}')
    check('9) тень: оверлей — ровно устаревшие, роли текущие',
          set(ov) == {rk['2:1'], rk['2:4']} and ov[rk['2:1']][4] == 'пуф' and ov[rk['2:4']][4] == 'кресло', f'{ov}')

print('test_orient_role_policy:', 'FAIL' if fails else 'OK')
sys.exit(1 if fails else 0)
