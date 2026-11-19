"""Серая крышка — МЯГКИЙ карантин по всем мешам детектора + удержание болванок (T-20261119-101/3, ответ Codex 19.11).
Без базы и сети: чистые функции `mesh_quarantine` (grey_units, plan_grey, hold_keys, grey_sql, restore_sql) и `salad/prune_shapes` (classify, hold_keys).
    python3 tools/scout/tests/test_grey_soft.py"""
import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, '..'), os.path.join(HERE, '..', 'salad')]
import remlab_tmp  # noqa: E402
remlab_tmp.use('test_grey_soft')

import mesh_quarantine as MQ  # noqa: E402
import prune_shapes as PS  # noqa: E402

fails = 0


def check(name, cond, extra=''):
    global fails
    print(('OK   ' if cond else 'FAIL ') + name + (f' — {extra}' if extra and not cond else ''))
    fails += 0 if cond else 1


def sha(c):
    return 'sha256:' + c * 64


def row(owner, c, verdict, via=False, share=0.9):
    return {'asset_id': sha(c), 'owner': owner, 'via_family': via, 'grey_top': {'verdict': verdict, 'grey_share': share}}


# --- свёртка строк сторожа в (owner, sha16) ---
rows = {'a:1': row('a:1', 'a', 'candidate'), 'a:2': row('a:1', 'a', 'reject', via=True),          # вариант семьи берёт меш представителя a:1
        'b:1': row('b:1', 'b', 'candidate'), 'b:2': row('b:2', 'b', 'candidate'),                  # тот же GLB, но другой владелец (разные строки)
        'c:1': {'asset_id': sha('c'), 'owner': 'c:1', 'via_family': False},                        # без grey_top (ok/na/серый товар) — не берём
        'd:1': row('d:1', 'd', 'na'), 'e:1': {'asset_id': None, 'owner': 'e:1', 'grey_top': {'verdict': 'reject'}}}
u = MQ.grey_units(rows)
check('свёртка: 5 строк с признаком → 3 единицы (owner, sha16); без признака, na и без asset_id — нет',
      sorted(u) == [('a:1', 'a' * 16), ('b:1', 'b' * 16), ('b:2', 'b' * 16)], sorted(u))
check('вариант семьи наследует owner представителя, тяжесть — худшая из строк, предложений — обе',
      u[('a:1', 'a' * 16)]['severity'] == 'reject' and u[('a:1', 'a' * 16)]['offers'] == ['a:1', 'a:2'])
check('sha16 — как asset_revisions.glb_sha (первые 16 после «sha256:»)', all(len(h) == 16 for _, h in u))
check('grey_share = None не роняет свёртку', MQ.grey_units({'x:1': row('x:1', 'x', 'candidate', share=None)})[('x:1', 'x' * 16)]['grey_share'] is None)

# --- план по таблице карантина ---
U = MQ.grey_units({k: row(k, c, v) for k, c, v in (('n:1', '1', 'candidate'), ('o:1', '2', 'reject'), ('p:1', '3', 'candidate'),
                                                    ('q:1', '4', 'reject'), ('r:1', '5', 'candidate'), ('s:1', '6', 'candidate'))})
mq = {('o:1', '2' * 16): {'decision': 'auto_release_v2', 'reasons': 'grey_top', 'prev': 'accepted'},
      ('p:1', '3' * 16): {'decision': 'accept', 'reasons': 'grey_top', 'prev': 'accepted'},
      ('q:1', '4' * 16): {'decision': '', 'reasons': 'proportion', 'prev': 'accepted'},
      ('r:1', '5' * 16): {'decision': '', 'reasons': 'grey_top', 'prev': 'generated'},
      ('old:1', '9' * 16): {'decision': '', 'reasons': 'grey_top', 'prev': 'accepted'},                 # детектор больше не держит
      ('old:2', '8' * 16): {'decision': '', 'reasons': 'slab', 'prev': 'accepted'},                     # осевая причина — не трогать
      ('old:3', '7' * 16): {'decision': 'reject', 'reasons': 'grey_top', 'prev': 'accepted'}}
rev = {('n:1', '1' * 16): 'accepted', ('s:1', '6' * 16): 'quarantine'}
pl = MQ.plan_grey(U, mq, rev)
check('нет строки → новая мягкая; статус ревизии из таблицы, «quarantine» в prev не пишем (→ generated)',
      pl['insert'] == [('n:1', '1' * 16, 'accepted'), ('s:1', '6' * 16, 'generated')], pl['insert'])
check('auto_release_v2 на тот же GLB решением не считается: строка открывается снова', pl['reopen'] == [('o:1', '2' * 16)])
check('accept владельца блокирует тот же GLB (терминально для файла)', pl['blocked'] == [('p:1', '3' * 16, 'accept')])
check('строка с осевой причиной остаётся жёсткой, grey_top ей не добавляем', pl['hard'] == [('q:1', '4' * 16, 'proportion')])
check('уже мягкая — только обновление тяжести', pl['soft'] == [('r:1', '5' * 16)])
check('мягкая, которую детектор не держит (новая модель / фото совпало), — снимается; осевая и решённая — нет', pl['clear'] == [('old:1', '9' * 16)], pl['clear'])
check('новый GLB того же товара — новая строка (ключ (owner, sha))',
      MQ.plan_grey(MQ.grey_units({'p:1': row('p:1', 'f', 'candidate')}), mq, {})['insert'] == [('p:1', 'f' * 16, 'generated')])
pl2 = MQ.plan_grey(U, mq, rev, seen={('old:1', '9' * 16)})
check('снимаем только оценённые детектором: меш, которого нет в таблице сторожа (не в привязке), остаётся нетронутым',
      pl2['clear'] == [('old:1', '9' * 16)] and MQ.plan_grey(U, mq, rev, seen=set())['clear'] == [])
check('seen_units: все оценённые (owner, sha), в том числе без признака', MQ.seen_units(rows) == {('a:1', 'a' * 16), ('b:1', 'b' * 16), ('b:2', 'b' * 16), ('c:1', 'c' * 16), ('d:1', 'd' * 16)}, MQ.seen_units(rows))
check('детектор не считал (нет счётчиков) — ничего не снимаем', MQ.plan_grey({}, mq, {}, detector_ran=False)['clear'] == [])

# --- SQL: мягкая строка не трогает статус ревизии, возврат из quarantine — общее правило ---
sqls = MQ.grey_sql(pl, U, 9.0)
body = '\n'.join(sqls[1:])
check('мягкая запись не меняет asset_revisions и не пишет решения (mesh_decisions/redo)', 'asset_revisions' not in body and 'redo' not in body and 'mesh_decisions' not in body)
check('первый блок — общий возврат ревизий из quarantine по строкам только с мягкой причиной (soft_sql), в prev_status',
      sqls[0].startswith('update asset_revisions') and "r.status = 'quarantine'" in sqls[0] and 'mq.prev_status' in sqls[0] and 'grey_top' in sqls[0] and "'accepted','generated'" in sqls[0])
check('возврат — по правилу soft_sql (decision null и причины целиком из soft_reasons), а не по списку SKU', MQ.soft_cond() in sqls[0] and "sku in (" not in sqls[0].lower())
check('вставка мягкой строки: причина ровно grey_top, тяжесть — в axis', "'grey_top'" in body and "'grey:reject'" not in body.split('insert into')[1].split('values')[0])
check('автоснятие пишет auto_release_grey (не owner-решение) и только мягкой строке без решения',
      "decision = 'auto_release_grey'" in body and "decision is null and reasons = 'grey_top'" in body)
check('автоснятие замера не блокирует (DECIDED_SQL исключает auto_release_*), accept/reject/cut — блокируют',
      all(n in MQ.DECIDED_SQL for n in MQ.NON_DECISIONS) and 'is not null' in MQ.DECIDED_SQL)

# --- удержание болванок ---
td = tempfile.mkdtemp(prefix='greyhold-')


def mk(sku, job, shape=True):
    d = os.path.join(td, sku.replace(':', '_'), job)
    os.makedirs(d, exist_ok=True)
    open(os.path.join(d, 'model.glb'), 'wb').write(b'm')
    if shape:
        open(os.path.join(d, 'shape.glb'), 'wb').write(b's')
    return os.path.join(d, 'model.glb')


H = MQ.grey_units({k: row(k, c, v) for k, c, v in (('h:1', '1', 'candidate'), ('h:2', '2', 'reject'), ('h:3', '3', 'candidate'), ('h:4', '4', 'candidate'),
                                                    ('h:5', '5', 'reject'))},
                  {'h:1': mk('h:1', 'j1'), 'h:2': mk('h:2', 'j2'), 'h:3': mk('h:3', 'j3', shape=False), 'h:4': mk('h:4', 'j4'), 'h:5': mk('h:5', 'j5')})
hmq = {('h:4', '4' * 16): {'decision': 'accept', 'reasons': 'grey_top', 'prev': 'accepted'},
       ('h:5', '5' * 16): {'decision': 'auto_release_v2', 'reasons': 'grey_top', 'prev': 'accepted'}}
hk = MQ.hold_keys(H, hmq, lambda g: os.path.isfile(os.path.join(os.path.dirname(g), 'shape.glb')))
check('удержание: candidate И reject без решения, где болванка есть; без болванки (h:3) и с решением владельца (h:4) — нет; auto_release — не решение (h:5)',
      hk == ['h_1/j1', 'h_2/j2', 'h_5/j5'], hk)
check('удержание не идёт через redo: функции записи решений в модуле нет', not hasattr(MQ, 'grey_redo') and 'mesh_decisions' not in open(MQ.__file__, encoding='utf-8').read().split('def sync_grey')[1].split('def pull')[0])

# файл-список → прополка: переживает срок, не мешает новому поколению, снимается решением
hf = os.path.join(td, 'grey-shape-hold.json')
json.dump({'keys': hk}, open(hf, 'w'))
hold = PS.hold_keys(hf)
check('прополка читает список; нет файла — пусто; битый файл — None (ничего не трогать)',
      hold == set(hk) and PS.hold_keys(os.path.join(td, 'нет.json')) == set() and PS.hold_keys(__file__) is None)
now = time.time()
old = now - 40 * 86400


def pack(sku, job, age=old):
    d = os.path.join(td, 'v2', sku, job)
    os.makedirs(d, exist_ok=True)
    for f in ('model.glb', 'shape.glb', 'complete.json', 'manifest.json'):
        p = os.path.join(d, f)
        open(p, 'wb').write(b'x')
        os.utime(p, (age, age))
    return d


d1, d2 = pack('h_1', 'j1'), pack('h_1', 'j1-new')
cl = lambda d, hs: PS.classify(d, set(), now, set(), {}, frozenset(), 14, hs)   # noqa: E731
check('болванка старше срока (40 сут, не принята) под удержанием — остаётся', cl(d1, hold) == 'keep_hold', cl(d1, hold))
check('без удержания та же болванка уходит по сроку (контроль)', cl(d1, set()) == 'del_old')
check('новое поколение (другой job) в списке не значится — удержание снято само', cl(d2, hold) == 'del_old')
check('решение владельца: ключ ушёл из списка при следующем проходе → болванка снова подчиняется сроку', cl(d1, hold - {'h_1/j1'}) == 'del_old')
check('удержание не отменяет «на приёмнике» и «неполный комплект» (они выше)', PS.classify(d1, {PS.key(d1)}, now, set(), {}, frozenset(), 14, hold) == 'keep_sink')

# --- шаг ночи и CI на месте ---
rd = open(os.path.join(HERE, '..', 'refresh_daily.sh'), encoding='utf-8').read()
i = rd.index('step mesh_color_guard')
g, rb = rd.index('step grey_sync'), rd.index('step room_bindings', i)
check('refresh_daily: grey_sync — сразу после mesh_color_guard и до первой привязки (room_bindings после сторожа)', i < g < rb and rd[i:g].count('step ') == 1, (i, g, rb))
check('в ночи нет лишнего ручного шага: --sync-grey вызывается через step', 'mesh_quarantine.py --sync-grey' in rd)

print('самопроверка серой крышки (мягкий карантин): ' + ('ОК' if not fails else f'ПРОВАЛОВ {fails}'))
sys.exit(1 if fails else 0)
