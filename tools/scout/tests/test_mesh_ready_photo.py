#!/usr/bin/env python3
"""Готовность меша по `product_photo_current` (T-20261118-04/22, Codex 18.11) и планировщик мешей — без базы.

ЗАЧЕМ. Предикат `mesh_ready` требовал строку `mesh_demand`, а меши очереди demo/комнат её не имеют: меш есть, банк его «не видит».
Теперь хеш текущего фото можно брать из `product_photo_current` — по выключателю `rules/mesh-ready.json:photo_current` (по потребителю).
Здесь: прежний SQL не изменился ни байтом (golden), новый несёт ВСЕ прежние проверки, выключатель направляет потребителя в свой путь,
кэш раздельный по режимам, варианты семейства готовы по представителю, планировщик (`mesh_scheduler._queue`) гасит постановку, когда
ревизия текущего фото уже есть (accepted|generated). Смысл самих условий на настоящих таблицах — `mesh_ready_photo_dbtest.py` (pakardev).

  python3 tools/scout/tests/test_mesh_ready_photo.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))  # tools/scout — помощник временного
import remlab_tmp  # noqa: E402
remlab_tmp.use('test_mesh_ready_photo')  # временное теста — на диске, не в /tmp; папка убирается при выходе (T-20261107-13)

SCOUT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SCOUT)

import mesh_ready as MR  # noqa: E402

bad = 0


def ok(name, cond, extra=''):
    global bad
    print(('  ✓ ' if cond else '  ✗ ') + name + (f' — {extra}' if extra and not cond else ''))
    bad += 0 if cond else 1


# SQL прежнего `_load` (git до T-20261118-04/22) — ни байтом иначе: потребители без флага читают ровно его
OLD_SQL = ("select r.sku from asset_revisions r join mesh_demand d on d.sku = r.sku join orientation_state o on split_part(o.revision_key,'|',1) = r.sku   "
           "and left(o.resolution->>'glb_sha',16) = r.glb_sha where r.status in ('accepted','generated') and r.origin <> 'legacy-local'   "
           "and d.source_sha is not null   and d.source_sha like split_part(r.revision_key, '|', 2) || '%'   "
           "and o.status in ('auto_resolved','human_resolved')   and coalesce(o.resolution->>'unusable','') <> 'true' group by r.sku")
OLD_FAMILY = ("select shop_mid||':'||external_id, mesh_family_rep from products "
              "where mesh_family_rep is not null and mesh_family_rep <> shop_mid||':'||external_id")

print('[1] прежний путь — байт-в-байт')
ok('ready_sql(False) == прежний текст', MR.ready_sql(False) == OLD_SQL)
ok('ready_sql() по умолчанию — прежний', MR.ready_sql() == OLD_SQL)
ok('запрос семейств не менялся', MR.FAMILY_SQL == OLD_FAMILY)
ok('cols=(sku, glb_sha): тот же запрос, колонки и группировка шире (для карантина банка)',
   MR.ready_sql(True, cols=('r.sku', 'r.glb_sha')).startswith('select r.sku, r.glb_sha from asset_revisions r ')
   and MR.ready_sql(True, cols=('r.sku', 'r.glb_sha')).endswith('group by r.sku, r.glb_sha'))

print('[2] новый путь: product_photo_current вместо mesh_demand, все прежние проверки на месте')
new = MR.ready_sql(True)
ok('хеш фото — product_photo_current', 'join product_photo_current c on c.sku = r.sku' in new and 'mesh_demand' not in new)
ok('ревизия: accepted|generated, не legacy-local', "r.status in ('accepted','generated') and r.origin <> 'legacy-local'" in new)
ok('текущее фото непустое', "coalesce(c.source_sha,'') <> ''" in new)
ok('префикс: хеш фото в ключе ревизии — начало текущего', "c.source_sha like split_part(r.revision_key, '|', 2) || '%'" in new)
ok('ориентация ТОГО ЖЕ glb (16 знаков)', "left(o.resolution->>'glb_sha',16) = r.glb_sha" in new)
ok('ориентация решена и не unusable', "o.status in ('auto_resolved','human_resolved')" in new and "coalesce(o.resolution->>'unusable','') <> 'true'" in new)
ok('группировка по представителю', new.endswith('group by r.sku'))
# разница путей — ТОЛЬКО источник хеша
strip = lambda s: (s.replace('join product_photo_current c on c.sku', 'join SRC on SRC.sku').replace('join mesh_demand d on d.sku', 'join SRC on SRC.sku')  # noqa: E731
                   .replace('c.source_sha', 'H').replace('d.source_sha', 'H'))
ok('кроме источника хеша тексты совпадают, различается лишь проверка пустого', strip(new).replace("coalesce(H,'') <> ''", 'NN') == strip(OLD_SQL).replace('H is not null', 'NN'))

print('[3] revision_current_sql — одно условие у готовности и у планировщика')
rc = MR.revision_current_sql('d.sku', 'd.source_sha', 'v1')
ok('exists по asset_revisions', rc.startswith('exists (select 1 from asset_revisions r where r.sku = d.sku'))
ok('accepted|generated, не legacy', "r.status in ('accepted','generated') and r.origin <> 'legacy-local'" in rc)
ok('префикс текущего sha и непустой', "coalesce(d.source_sha,'') <> ''" in rc and "d.source_sha like split_part(r.revision_key,'|',2) || '%'" in rc)
ok('версия конвейера в ключе — по запросу', "split_part(r.revision_key,'|',3) = 'v1'" in rc)
ok('без версии — без проверки конвейера', "split_part(r.revision_key,'|',3)" not in MR.revision_current_sql('d.sku', 'd.source_sha'))
ok('версия экранируется', "'v1''x'" in MR.revision_current_sql('d.sku', 'd.source_sha', "v1'x"))

print('[4] выключатель по потребителю')
d = tempfile.mkdtemp(prefix='mrp-')


def put_rules(obj):
    p = os.path.join(d, 'mesh-ready.json')
    with open(p, 'w', encoding='utf-8') as f:
        json.dump(obj, f)
    MR.RULES, MR._RULES = p, None
    MR._CACHE[False] = MR._CACHE[True] = None


MR.RULES, MR._RULES = os.path.join(d, 'нет-такого.json'), None
ok('нет файла — всё выключено', not MR.photo_current_on('bank_ready') and not MR.photo_current_on(None))
put_rules({'photo_current': {'bank_ready': True, 'others': False}})
ok('bank_ready=true: банк — по новому пути', MR.photo_current_on('bank_ready'))
ok('прочие (без имени и с чужим именем) — по прежнему', not MR.photo_current_on(None) and not MR.photo_current_on('render_strategy'))
put_rules({'photo_current': {'others': True}})
ok('others=true, bank_ready нет — банк выключен', not MR.photo_current_on('bank_ready') and MR.photo_current_on(None))
put_rules({'photo_current': {}})
ok('пустой photo_current — выключено', not MR.photo_current_on('bank_ready') and not MR.photo_current_on(None))
with open(os.path.join(d, 'битый.json'), 'w') as f:
    f.write('{')
MR.RULES, MR._RULES = os.path.join(d, 'битый.json'), None
ok('битый файл — выключено, не падает', not MR.photo_current_on('bank_ready'))

print('[5] маршрут и раздельный кэш, варианты семейства (подмена db)')
OLD_SET = {'rep:old', 'rep:both'}
NEW_SET = {'rep:old', 'rep:both', 'rep:new'}
seen = []


def fake_db(sql, *a, **k):
    seen.append(sql)
    if sql == MR.FAMILY_SQL:
        return [['var:1', 'rep:new'], ['var:2', 'rep:none'], ['rep:both', 'rep:old']]
    return [[s] for s in sorted(NEW_SET if 'product_photo_current' in sql else OLD_SET)]


MR.db = fake_db
put_rules({'photo_current': {'bank_ready': True, 'others': False}})
bank = MR.mesh_ready_raw('bank_ready')
rest = MR.mesh_ready_raw()
ok('банк получил множество нового пути', 'rep:new' in bank and 'var:1' in bank)
ok('прочие — прежнего (rep:new нет, вариант его не готов)', 'rep:new' not in rest and 'var:1' not in rest)
ok('вариант готов по представителю (старый путь)', 'rep:both' in rest)
ok('вариант нерешённого представителя не готов', 'var:2' not in bank and 'var:2' not in rest)
n = len(seen)
MR.mesh_ready_raw('bank_ready'), MR.mesh_ready_raw(), MR.mesh_ready('rep:new', 'bank_ready'), MR.mesh_ready('rep:new')
ok('кэш по режимам: повторные вызовы базу не трогают', len(seen) == n)
ok('mesh_ready(sku, consumer) по маршруту', MR.mesh_ready('rep:new', 'bank_ready') and not MR.mesh_ready('rep:new'))
put_rules({'photo_current': {'bank_ready': False, 'others': False}})
ok('выключили — банк вернулся к прежнему', 'rep:new' not in MR.mesh_ready_raw('bank_ready'))

print('[6] тень')
put_rules({})
MR.db = fake_db
rc_ = MR.shadow()
ok('тень: пропавших нет — код 0', rc_ == 0)
OLD_SET.add('rep:lost')
MR._CACHE[False] = MR._CACHE[True] = None
ok('тень: пропал товар — код 1', MR.shadow() == 1)

print('[7] планировщик: _queue гасит постановку при ревизии текущего фото')
import mesh_scheduler as MS  # noqa: E402
cap = []
MS.db = lambda sql, *a, **k: (cap.append(sql), [])[1]
MS._queue()
sql = cap[0]
ok('условие — общее с готовностью (revision_current_sql)', MR.revision_current_sql('d.sku', 'd.source_sha', MS.PIPELINE_VERSION) in sql)
ok('generated тоже гасит: проверки «только accepted» больше нет', "r.status='accepted'" not in sql and "'generated'" in sql)
ok('сверка по префиксу, а не по полному ключу ревизии', 'r.revision_key = d.sku' not in sql and "like split_part(r.revision_key,'|',2)" in sql)
ok('очередь заданий (mesh_jobs) по-прежнему гасит', 'from mesh_jobs j' in sql and "'queued','submitted','running'" in sql)
ok('только спрос wanted с хешом фото', "d.status='wanted' and d.source_sha is not null" in sql)

print('[8] правила: файл читается, каждое поле с `_why`')
MR.RULES, MR._RULES = os.path.join(SCOUT, 'rules', 'mesh-ready.json'), None
R = MR.rules()
pc = R.get('photo_current') or {}
ok('rules/mesh-ready.json: bank_ready и others — булевы', isinstance(pc.get('bank_ready'), bool) and isinstance(pc.get('others'), bool))
ok('у каждого поля есть `_why`', all(isinstance(pc.get(f'_{k}_why'), str) and pc[f'_{k}_why'] for k in ('bank_ready', 'others')))
ok('others выключено по умолчанию', pc.get('others') is False)

print('ИТОГО: ' + ('всё в норме' if not bad else f'провалов {bad}'))
sys.exit(1 if bad else 0)
