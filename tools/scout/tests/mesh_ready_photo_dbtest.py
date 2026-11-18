#!/usr/bin/env python3
"""Смысл условий готовности меша и постановки генерации на НАСТОЯЩЕМ Postgres (pakardev) — T-20261118-04/22. Базу НЕ меняет.

Таблицы подменяются встроенными `WITH t(...) AS (VALUES …)` (CTE с именем таблицы перекрывает её в этом запросе), поэтому проверяется
ровно тот SQL, что идёт в бой (`mesh_ready.ready_sql`, `mesh_ready.revision_current_sql`), на выдуманных строках — без записи и без
чтения боевых данных. В CI не идёт (нужна база); запуск: `r python3 tools/scout/tests/mesh_ready_photo_dbtest.py`.
Плюс живой инвариант: тень «прежний → новый» — пропавших нет.
"""
from __future__ import annotations

import os
import sys
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import remlab_tmp  # noqa: E402
remlab_tmp.use('mesh_ready_photo_dbtest')

SCOUT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SCOUT)

import mesh_ready as MR  # noqa: E402
from mesh_queue import db, q  # noqa: E402

bad = 0


def ok(name, cond, extra=''):
    global bad
    print(('  ✓ ' if cond else '  ✗ ') + name + (f' — {extra}' if extra and not cond else ''))
    bad += 0 if cond else 1


SHA = 'a1b2c3d4e5f60718' + '0' * 48          # полный хеш текущего фото (64)
OTHER = '9999888877776666' + '1' * 48        # хеш ДРУГОГО (нового) фото
GLB = 'ffff000011112222'                      # glb_sha ревизии (16)


def vals(rows):
    return ', '.join('(' + ', '.join('NULL::text' if v is None else q(v) for v in r) + ')' for r in rows)


def run(sql_tail: str, ar, pc=(), ori=(), md=()):
    """Выполнить `sql_tail` (текст, начинающийся с `select …`) поверх выдуманных таблиц; → список строк."""
    pre = ('with asset_revisions(sku, status, origin, revision_key, glb_sha) as (values %s), '
           'product_photo_current(sku, image_url, source_sha) as (values %s), '
           'orientation_state(revision_key, status, resolution) as (select k, s, r::jsonb from (values %s) v(k, s, r)), '
           'mesh_demand(sku, status, source_sha) as (values %s) ' % (
               vals(ar or [('-', '-', '-', '-', '-')]), vals(pc or [('-', '-', '-')]), vals(ori or [('-', '-', '{}')]), vals(md or [('-', '-', '-')])))
    return [r[0] for r in db(pre + sql_tail) if r]


# сценарии: имя → (старый путь готов, новый путь готов)
S = {
    'всё_есть':          dict(old=True,  new=True),
    'строки_спроса_нет': dict(old=False, new=True, demand=False),
    'accepted':          dict(old=True,  new=True, status='accepted'),
    'фото_сменилось':    dict(old=True,  new=False, pc=OTHER),             # копия в спросе отстала от канона — новый строже
    'фото_пустое':       dict(old=True,  new=False, pc=''),
    'нет_строки_фото':   dict(old=True,  new=False, pc=None),
    'legacy':            dict(old=False, new=False, origin='legacy-local'),
    'owner_reject':      dict(old=False, new=False, status='owner_reject'),
    'ориент_ждёт':       dict(old=False, new=False, ori='review_pending'),
    'ориент_unusable':   dict(old=False, new=False, unusable='true'),
    'ориент_другой_glb': dict(old=False, new=False, ori_glb='eeee000011112222'),
    'нет_ориентации':    dict(old=False, new=False, ori=None),
    'human_resolved':    dict(old=True,  new=True, ori='human_resolved'),
}
ar, pc, ori, md = [], [], [], []
for i, (name, o) in enumerate(S.items()):
    sku = f'm:{i}'
    ar.append((sku, o.get('status', 'generated'), o.get('origin', 'salad-pilot'), f'{sku}|{SHA[:16]}|v1', GLB))
    if o.get('pc', SHA) is not None:
        pc.append((sku, 'u', o.get('pc', SHA)))
    if o.get('demand', True):
        md.append((sku, 'wanted', SHA))
    if o.get('ori', 'auto_resolved') is not None:
        ori.append((f'{sku}|{o.get("ori_glb", GLB)}|orient-v1', o.get('ori', 'auto_resolved'),
                    '{"glb_sha": "%s", "unusable": "%s"}' % (o.get('ori_glb', GLB) + '0' * 48, o.get('unusable', ''))))
old_ready = set(run(MR.ready_sql(False), ar, pc, ori, md))
new_ready = set(run(MR.ready_sql(True), ar, pc, ori, md))
print('[1] матрица готовности: прежний путь (mesh_demand) и новый (product_photo_current)')
for i, (name, o) in enumerate(S.items()):
    sku = f'm:{i}'
    ok(f'{name}: прежний={o["old"]}', (sku in old_ready) == o['old'])
    ok(f'{name}: новый={o["new"]}', (sku in new_ready) == o['new'])

print('[2] ревизия текущего фото гасит постановку генерации (revision_current_sql, как в mesh_scheduler._queue)')
T = {
    'generated_текущее':       (True,  dict(status='generated')),
    'accepted_текущее':        (True,  dict(status='accepted')),
    'generated_СТАРОЕ_фото':   (False, dict(key_sha=OTHER[:16])),
    'другая_версия_конвейера': (False, dict(ver='v2')),
    'legacy':                  (False, dict(origin='legacy-local')),
    'owner_reject':            (False, dict(status='owner_reject')),
    'ревизии_нет':             (False, dict(norev=True)),
}
ar2, md2 = [], []
for i, (name, (_exp, o)) in enumerate(T.items()):
    sku = f's:{i}'
    md2.append((sku, 'wanted', SHA))
    if not o.get('norev'):
        ar2.append((sku, o.get('status', 'generated'), o.get('origin', 'salad-pilot'), f'{sku}|{o.get("key_sha", SHA[:16])}|{o.get("ver", "v1")}', GLB))
got = set(run('select d.sku from mesh_demand d where ' + MR.revision_current_sql('d.sku', 'd.source_sha', 'v1'), ar2, md=md2))
for i, (name, (exp, _o)) in enumerate(T.items()):
    ok(f'{name}: гасит постановку={exp}', (f's:{i}' in got) == exp)
# запрос планировщика целиком синтаксически исполним на пустых таблицах
import mesh_scheduler as MS  # noqa: E402
try:
    qs = MS._queue()
    ok('mesh_scheduler._queue() исполняется на боевой базе (только чтение)', isinstance(qs, dict), str(type(qs)))
except Exception as e:  # noqa: BLE001
    ok('mesh_scheduler._queue() исполняется на боевой базе', False, f'{type(e).__name__}: {str(e)[:120]}')

print('[3] живой инвариант: тень — пропавших нет (все старые готовые остаются готовыми)')
MR._CACHE[False] = MR._CACHE[True] = None
old_live, new_live = set(MR._load(False)), set(MR._load(True))
ok(f'прежний {len(old_live)} ⊆ новый {len(new_live)}', old_live <= new_live, f'пропало {len(old_live - new_live)}')

print('ИТОГО: ' + ('всё в норме' if not bad else f'провалов {bad}'))
sys.exit(1 if bad else 0)
