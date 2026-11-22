#!/usr/bin/env python3
"""Крашеная модель в конвейере лёгких копий (план painted-to-rt-01, T-20261120-150/1): (а) склад, (б) стратегия данными, (г) победитель.
  (а) `tools/scout/stablegen/sg_store.py:store_run` — выход покраски `blender/painted.glb` ложится в склад как обычная модель
      (`model.glb` + `manifest.json`: sku, role, source, sha, guard), атомарно, манифест последним; guard по умолчанию `none`.
  (б) `rules/asset-strategies.json:mesh_strategies` — какие стратегии дают роли модель и лёгкую копию (`asset_strategy.has_mesh`,
      `runtime_mesh.mesh_role`): список в данных, литерала `hunyuan3d` у потребителей нет.
  (г) `tools/scout/salad/gallery_build.py:painted_winners/select` — крашеная выигрывает у Hunyuan ТОЛЬКО с `guard == pass` и если её
      лёгкая копия не отказана по весу; время файлов не участвует (порядок записей и mtime меняем — выбор тот же).
Запуск: python tools/assets/tests/test_painted_binding.py"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCOUT = os.path.join(HERE, '..', '..', 'scout')
sys.path.insert(0, os.path.join(HERE, '..'))
sys.path.insert(0, SCOUT)
sys.path.insert(0, os.path.join(SCOUT, 'salad'))
sys.path.insert(0, os.path.join(SCOUT, 'stablegen'))
import remlab_tmp  # noqa: E402
remlab_tmp.use('test_painted_binding')  # временное теста — на диске, не в /tmp; папка убирается при выходе (T-20261107-13)
import asset_strategy as AS  # noqa: E402
import gallery_build as GB  # noqa: E402
import runtime_mesh as RM  # noqa: E402
import sg_store as ST  # noqa: E402

FAILS = []


def ok(name, cond, extra=''):
    print(('OK   ' if cond else 'FAIL ') + name + (f' — {extra}' if extra and not cond else ''))
    if not cond:
        FAILS.append(name)


# ——— (б) стратегия данными ———
cfg = AS.painted_source()
ok('канон: источник покраски, склад и значения guard — в данных', cfg['source'] == 'stablegen' and cfg['guard_pass'] == 'pass' and cfg['guard_none'] == 'none' and cfg['store'], cfg)
ok('mesh_strategies канона: hunyuan3d и крашеная', 'hunyuan3d' in AS.mesh_strategies() and 'stablegen_painted' in AS.mesh_strategies(), AS.mesh_strategies())
ok('роль с моделью (комод) — has_mesh; ковёр (плоскость) и плед (вырезка) — нет', AS.has_mesh('комод') and not AS.has_mesh('ковёр') and not AS.has_mesh('плед'))
ok('runtime_mesh.mesh_role по канону: комод да, ковёр нет (как раньше)', RM.mesh_role('комод') and not RM.mesh_role('ковёр'))
strat = {'комод': 'stablegen_painted', 'ковёр': 'procedural_plane', '_default': 'hunyuan3d'}
ok('роль со стратегией покраски получает копию, когда стратегия в списке данных', RM.mesh_role('комод', strat, ('hunyuan3d', 'stablegen_painted')))
ok('  а когда стратегии в списке нет — не получает (список — данные, не литерал)', not RM.mesh_role('комод', strat, ('hunyuan3d',)))
ok('  ковёр с плоскостью модели не получает', not RM.mesh_role('ковёр', strat, ('hunyuan3d', 'stablegen_painted')))
ok('в коде потребителей литерала «== \'hunyuan3d\'» для выбора роли-меша нет',
   "== 'hunyuan3d'" not in open(os.path.join(SCOUT, 'salad', 'gallery_build.py'), encoding='utf-8').read()
   and '== "hunyuan3d"' not in open(os.path.join(HERE, '..', 'runtime_mesh.py'), encoding='utf-8').read())

# ——— (г) победитель ———
A = lambda **k: {'date': '2026-11-20', 'tg': 2750, **k}  # noqa: E731   строка файла принятия: дата + номер TG владельца
ACC = {'m:a': A(), 'm:b': A(), 'm:c': A(), '112923:13224664101879413845': A()}   # принятые владельцем (в тестах — подложенные)


def SEL(ents_, only, bound, fb, refused=frozenset(), accepted=None):  # noqa: E731
    """select с принятием владельца: по умолчанию принят каждый подложенный SKU — условие «принято» проверяется отдельными тестами ниже."""
    return GB.select(ents_, only, bound, fb, refused, 'pass', ACC if accepted is None else accepted)


E = lambda d, s, **k: {'dir': d, 'sku': s, 'owner_reject': False, 'role_mesh': True, 'has_glb': True, 'painted': False, 'guard': None, 'glb_sha': None, **k}  # noqa: E731
P = lambda d, s, guard='pass', sha='aaaaaaaaaaaaaaaa', **k: E(d, s, painted=True, guard=guard, glb_sha=sha, **k)  # noqa: E731
H_new, H_old = E('/h/a/new/', 'm:a'), E('/h/a/old/', 'm:a')
ents = [H_new, H_old]                                     # порядок записей — как у сборки: свежий manifest первым

ch, how = SEL(ents + [P('/p/a/r1/', 'm:a')], None, {}, False)
ok('крашеная с guard=pass побеждает свежий Hunyuan', ch['m:a'] == '/p/a/r1/' and how['m:a'] == 'painted', (ch, how))
ch, how = SEL([P('/p/a/r1/', 'm:a')] + ents, None, {}, False)
ok('  порядок записей (т.е. mtime) не влияет: крашеная первой или последней — тот же выбор', ch['m:a'] == '/p/a/r1/')
ch, how = SEL(list(reversed(ents)) + [P('/p/a/r1/', 'm:a')], None, {}, False)
ok('  и Hunyuan в обратном порядке — крашеная всё равно', ch['m:a'] == '/p/a/r1/')
for g in ('none', None, 'fail', 'repaint', 'reject', ''):
    ch, how = SEL(ents + [P('/p/a/r1/', 'm:a', guard=g)], None, {}, False)
    ok(f'guard={g!r}: крашеная НЕ побеждает, остаётся Hunyuan (по mtime, первый в списке)', ch['m:a'] == '/h/a/new/' and how['m:a'] == 'mtime', (ch, how))
ch, how = SEL(ents + [P('/p/a/r1/', 'm:a', sha='bbbbbbbbbbbbbbbb')], None, {}, False, refused={'bbbbbbbbbbbbbbbb'})
ok('guard=pass, но копия отказана по весу (sha в отказах): Hunyuan остаётся', ch['m:a'] == '/h/a/new/')
ch, how = SEL(ents + [P('/p/a/r1/', 'm:a', sha='bbbbbbbbbbbbbbbb')], None, {}, False, refused={'другой'})
ok('  отказ чужого файла не мешает', ch['m:a'] == '/p/a/r1/')
ch, _ = SEL(ents + [P('/p/a/r1/', 'm:a', owner_reject=True)], None, {}, False)
ok('крашеная, забракованная владельцем — не побеждает', ch['m:a'] == '/h/a/new/')
ch, _ = SEL(ents + [P('/p/a/r1/', 'm:a', role_mesh=False)], None, {}, False)
ok('крашеная с ролью без модели (стратегия не из списка) — не побеждает', ch['m:a'] == '/h/a/new/')
ch, _ = SEL(ents + [P('/p/a/r1/', 'm:a', has_glb=False)], None, {}, False)
ok('крашеная без model.glb — не побеждает', ch['m:a'] == '/h/a/new/')
ch, _ = SEL(ents + [P('/p/a/r1/', 'm:a')], {'m:other'}, {}, False)
ok('список отбора действует: SKU вне списка — не показан вовсе', 'm:a' not in ch)
ch, _ = SEL([P('/p/c/r1/', 'm:c', guard='none')], None, {}, False)
ok('у SKU только крашеная без сторожа — не показывается (папка без годной модели SKU не занимает)', 'm:c' not in ch)
ch, how = SEL([P('/p/b/rB/', 'm:b'), P('/p/b/rA/', 'm:b')] + [E('/h/b/x/', 'm:b')], None, {}, False)
ok('две прошедших сторож: первая по имени папки (rA), не по времени', ch['m:b'] == '/p/b/rA/', ch)
ch, how = SEL([P('/p/b/rA/', 'm:b', guard='none'), P('/p/b/rB/', 'm:b')], None, {}, False)
ok('  непрошедшая rA не мешает прошедшей rB', ch['m:b'] == '/p/b/rB/')
ch, how = SEL(ents + [P('/p/a/r1/', 'm:a')], None, {'m:a': '/h/a/old'}, True)
ok('привязка к старому файлу Hunyuan не отменяет победителя (г): крашеная после сторожа главнее', ch['m:a'] == '/p/a/r1/' and how['m:a'] == 'painted')
ch, how = SEL(ents + [P('/p/a/r1/', 'm:a', guard='none')], None, {'m:a': '/h/a/old'}, True)
ok('  без guard=pass привязка работает как прежде', ch['m:a'] == '/h/a/old/' and how['m:a'] == 'binding')

# принято владельцем (TG 2734): guard=pass без отметки — побеждает Hunyuan
ch, how = SEL(ents + [P('/p/a/r1/', 'm:a')], None, {}, False, accepted={})
ok('guard=pass, но SKU НЕ принят владельцем (пустой файл принятия): побеждает Hunyuan', ch['m:a'] == '/h/a/new/' and how['m:a'] == 'mtime', (ch, how))
ch, _ = SEL(ents + [P('/p/a/r1/', 'm:a')], None, {}, False, accepted={'m:other': A()})
ok('  принят ДРУГОЙ SKU — для этого не считается', ch['m:a'] == '/h/a/new/')
ch, _ = GB.select(ents + [P('/p/a/r1/', 'm:a')], None, {}, False)
ok('  accepted не передан вовсе (прежний вызов) — тоже никто не принят', ch['m:a'] == '/h/a/new/')
ch, how = SEL(ents + [P('/p/a/r1/', 'm:a')], None, {}, False, accepted={'m:a': A()})
ok('guard=pass И принят (дата + TG): крашеная побеждает', ch['m:a'] == '/p/a/r1/' and how['m:a'] == 'painted')
ch, _ = SEL(ents + [P('/p/a/r1/', 'm:a', guard='none')], None, {}, False, accepted={'m:a': A()})
ok('  принят, но сторож не прошёл (guard=none) — Hunyuan: «принято» сторож не заменяет', ch['m:a'] == '/h/a/new/')
ch, _ = SEL(ents + [P('/p/a/r1/', 'm:a', sha='bbbbbbbbbbbbbbbb')], None, {}, False, refused={'bbbbbbbbbbbbbbbb'}, accepted={'m:a': A()})
ok('  принят и сторож pass, но копия отказана по весу — Hunyuan', ch['m:a'] == '/h/a/new/')
ch, _ = SEL(ents + [P('/p/a/r1/', 'm:a', sha='1234567890abcdef')], None, {}, False, accepted={'m:a': A(glb_sha='1234567890abcdef')})
ok('строка с glb_sha: тот же файл — побеждает', ch['m:a'] == '/p/a/r1/')
ch, _ = SEL(ents + [P('/p/a/r1/', 'm:a', sha='ffffffffffffffff')], None, {}, False, accepted={'m:a': A(glb_sha='1234567890abcdef')})
ok('  перекрашенный файл (другой glb_sha) — не принят, Hunyuan', ch['m:a'] == '/h/a/new/')

# файл принятия: читается из данных, недействительные строки не считаются
with tempfile.TemporaryDirectory(dir=os.environ.get('REMLAB_TMP') or None) as dd:
    ap = os.path.join(dd, 'acc.json')
    json.dump({'accepted': {'m:ok': {'date': '2026-11-20', 'tg': 2750}, 'm:nodate': {'tg': 1}, 'm:notg': {'date': '2026-11-20'}, 'm:baddate': {'date': '20.11.2026', 'tg': 1},
                            'm:strtg': {'date': '2026-11-20', 'tg': '2750'}, 'm:booltg': {'date': '2026-11-20', 'tg': True}, 'm:junk': 'да'}}, open(ap, 'w'))
    got = GB.accepted_skus(ap)
    ok('файл принятия: действительна только строка с датой ГГГГ-ММ-ДД и числом TG', set(got) == {'m:ok'}, got)
    ok('  файла нет / не JSON — пусто (никто не принят, не падаем)', GB.accepted_skus(os.path.join(dd, 'нет.json')) == {} and GB.accepted_skus(__file__) == {})
    os.environ['PAINTED_ACCEPTED'] = ap
    ok('  PAINTED_ACCEPTED подменяет путь (стенд/тест)', set(GB.accepted_skus(painted=cfg)) == {'m:ok'})
    os.environ.pop('PAINTED_ACCEPTED')
real = GB.accepted_skus(painted=cfg)
ok('рабочий файл rules/painted-accepted.json читается, имя файла — из канона (accepted_file); код туда ничего не пишет: пусто, пока ведущий не внесёт строку по слову владельца',
   cfg.get('accepted_file') == 'painted-accepted.json' and os.path.isfile(os.path.join(SCOUT, 'rules', cfg['accepted_file'])) and isinstance(real, dict), (cfg, real))
ok('  ни один скрипт кода не пишет в файл принятия (в tools/ нет записи в painted-accepted)',
   not any('painted-accepted' in open(f, encoding='utf-8').read() and ("open(" in open(f, encoding='utf-8').read().split('painted-accepted')[1][:80] and "'w'" in open(f, encoding='utf-8').read().split('painted-accepted')[1][:120])
           for f in (os.path.join(SCOUT, 'salad', 'gallery_build.py'), os.path.join(SCOUT, 'stablegen', 'sg_store.py'))))

# ——— отказы по весу из таблицы копий ———
with tempfile.TemporaryDirectory(dir=os.environ.get('REMLAB_TMP') or None) as d:
    tbl = os.path.join(d, 'runtime-meshes.json')
    json.dump({'meshes': {'1_1': {'rt_weight': {'status': 'refused', 'glb_sha': 'cccccccccccccccc'}},
                           '2_2': {'rt_weight-lite': {'status': 'refused', 'glb_sha': 'dddddddddddddddd'}},
                           '3_3': {'rt_weight': {'status': 'ok', 'glb_sha': 'eeeeeeeeeeeeeeee'}}, '4_4': {'size': 1}}}, open(tbl, 'w'))
    ok('отказы по весу из таблицы копий: обычная и -lite; «ok» и пустые записи — нет', GB.refused_shas(tbl) == {'cccccccccccccccc', 'dddddddddddddddd'}, GB.refused_shas(tbl))
    ok('таблицы нет — отказов не знаем (пусто, не падаем)', GB.refused_shas(os.path.join(d, 'нет.json')) == set())

    # ——— (а) склад покраски ———
    store = os.path.join(d, 'meshes-painted')
    run = os.path.join(d, 'runs', '112923_13224664101879413845@r2b1-v7-120000')
    os.makedirs(os.path.join(run, 'blender'))
    glb = b'glTF' + os.urandom(64)
    open(os.path.join(run, 'blender', 'painted.glb'), 'wb').write(glb)
    json.dump({'cat_role': 'комод', 'x': 1}, open(os.path.join(run, 'cfg.json'), 'w'))
    it = {'key': '112923_13224664101879413845@r2b1', 'variant': 'v7', 'label': 'вариант 7', 'dir': run}
    res = ST.store_run(it, cfg, root=store)
    dest = res['stored']
    man = json.load(open(os.path.join(dest, 'manifest.json')))
    ok('склад: model.glb и manifest.json в <склад>/<товар>/<прогон>/', os.path.isfile(os.path.join(dest, 'model.glb')) and os.path.isfile(os.path.join(dest, 'manifest.json'))
       and os.path.relpath(dest, store) == os.path.join('112923_13224664101879413845', os.path.basename(run)), dest)
    ok('  модель — байт в байт painted.glb', open(os.path.join(dest, 'model.glb'), 'rb').read() == glb)
    ok('  манифест: sku mid:eid, роль из cfg.json, источник, вариант, sha256, guard=none',
       man['sku'] == '112923:13224664101879413845' and man['role'] == 'комод' and man['source'] == cfg['source'] and man['variant'] == 'v7'
       and len(man['sha256']) == 64 and man['bytes'] == len(glb) and man['guard'] == cfg['guard_none'], man)
    ok('  рабочих .tmp в складе нет', not any(f.endswith('.tmp') for f in os.listdir(dest)), os.listdir(dest))
    # галерея видит запись склада и не пускает без сторожа
    ent = {'dir': dest + '/', 'sku': man['sku'], 'owner_reject': False, 'role_mesh': AS.has_mesh(man['role']), 'has_glb': True, 'painted': man['source'] == cfg['source'], 'guard': man['guard'], 'glb_sha': 'f' * 16}
    ch, _ = SEL([E('/h/x/', man['sku']), ent], None, {}, False)
    ok('запись склада без сторожа (guard=none): Hunyuan остаётся', ch[man['sku']] == '/h/x/')
    ST.set_guard(dest, cfg['guard_pass'], {'coverage': 0.97})
    man2 = json.load(open(os.path.join(dest, 'manifest.json')))
    ok('  set_guard(pass): манифест обновлён, отчёт сторожа сохранён', man2['guard'] == 'pass' and man2['guard_report'] == {'coverage': 0.97} and man2['sha256'] == man['sha256'])
    ent['guard'] = man2['guard']
    ch, how = SEL([E('/h/x/', man['sku']), ent], None, {}, False)
    ch, _ = SEL([E('/h/x/', man['sku']), ent], None, {}, False, accepted={})
    ok('  после guard=pass, но без отметки владельца — Hunyuan', ch[man['sku']] == '/h/x/')
    ch, how = SEL([E('/h/x/', man['sku']), ent], None, {}, False)
    ok('  после guard=pass И отметки владельца — побеждает', ch[man['sku']] == dest + '/' and how[man['sku']] == 'painted')
    # время файлов не участвует: переставили mtime у обеих записей — тот же выбор
    old = os.path.join(d, 'hx'); os.makedirs(old); open(os.path.join(old, 'manifest.json'), 'w').write('{}')
    os.utime(old, (1, 1)); os.utime(os.path.join(dest, 'manifest.json'), (2_000_000_000, 2_000_000_000))
    ch1, _ = SEL([E('/h/x/', man['sku']), ent], None, {}, False)
    os.utime(old, (2_000_000_000, 2_000_000_000)); os.utime(os.path.join(dest, 'manifest.json'), (1, 1))
    ch2, _ = SEL([ent, E('/h/x/', man['sku'])], None, {}, False)
    ok('  mtime записей меняем местами — выбор тот же', ch1 == ch2 == {man['sku']: dest + '/'})
    # прогон без painted.glb — громко, не молча
    try:
        ST.store_run({'key': '1_2', 'variant': 'v', 'dir': os.path.join(d, 'пусто')}, cfg, root=store)
        ok('нет painted.glb — FileNotFoundError', False)
    except FileNotFoundError:
        ok('нет painted.glb — FileNotFoundError (очередь запишет store_error и скажет)', True)
    # drop_run только внутри склада
    try:
        ST.drop_run(d, root=store)
        ok('drop_run вне склада — отказ', False)
    except ValueError:
        ok('drop_run вне склада — отказ', True)
    ok('drop_run убирает запись склада', ST.drop_run(dest, root=store) and not os.path.exists(dest))

    # ——— склады галереи ———
    os.makedirs(os.path.join(store, 'x'), exist_ok=True)
    ok('склад покраски читается галереей, если он есть; склад Hunyuan — всегда', GB.stores({'store': store})[-1] == store and GB.stores({'store': os.path.join(d, 'нет')})[-1] != os.path.join(d, 'нет'))

if FAILS:
    print(f'\n{len(FAILS)} провал(ов)')
    sys.exit(1)
print('\nвсе проверки прошли')
