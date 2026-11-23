"""Тесты сбора входа этапа 09 (plan09.py) на заглушках: происхождение пакета выигрывает у «самого свежего», приоритетные корни, запасной поиск с пометкой, пропуск своей папки, «нет этапа»; пометка в paint_check."""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import plan09 as P  # noqa: E402

bad = 0


def ok(c, m):
    global bad
    print(('  ✓ ' if c else '  ✗ ') + m)
    bad += 0 if c else 1


def mk(root, sku, st, passed=True, mtime=None):
    d = os.path.join(root, sku, st)
    os.makedirs(d, exist_ok=True)
    f = os.path.join(d, 'check.json')
    json.dump({'passed': passed}, open(f, 'w'))
    if mtime:
        os.utime(f, (mtime, mtime))
    return d


def touch(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, 'w').write('x')
    return path


with tempfile.TemporaryDirectory() as t:
    logs = os.path.realpath(os.path.join(t, 'logs'))
    prio = os.path.join(logs, 'prio')
    old = {'03-parts': [prio], '01-trellis': [prio]}
    out = os.path.join(logs, 'out09')
    # два прогона одного товара с РАЗНЫМИ формами: в пакет пошла форма из formA; formB свежее и тоже прошла — берём formA (происхождение), не свежее
    a03 = mk(os.path.join(logs, 'formA'), 'sA', '03-parts', True, 1000)
    mk(os.path.join(logs, 'formB'), 'sA', '03-parts', True, 9000)
    glb = touch(os.path.join(logs, 'formA', 'forms-out', 'sA-hd.glb'))
    inputs = {'sA': {'glb': glb}}
    rows = {s: (f, h) for s, f, h in P.collect(inputs, [], logs, old, skip=(out,))}
    ok(rows['sA'][0].get('03-parts') == a03 and rows['sA'][1]['03-parts'] == 'origin', 'два прогона с разными формами: берётся тот, что в пакете (origin), а не самый свежий')
    # явный stage_src главнее
    ex = mk(os.path.join(logs, 'formC'), 'sA', '03-parts', True, 5)
    r = {s: (f, h) for s, f, h in P.collect({'sA': {'glb': glb, 'stage_src': {'03-parts': ex}}}, [], logs, old)}
    ok(r['sA'][0]['03-parts'] == ex and r['sA'][1]['03-parts'] == 'origin', 'явный stage_src главнее')
    # приоритетный корень (список) — когда происхождения нет
    p1 = mk(prio, 's1', '03-parts')
    r = {s: (f, h) for s, f, h in P.collect({'s1': {}}, [], logs, old)}
    ok(r['s1'][0]['03-parts'] == p1 and r['s1'][1]['03-parts'] == 'list', 'приоритетный корень, если происхождения нет')
    # запасной поиск — помечен search; прошедший самый свежий; глубина 2
    mk(os.path.join(logs, 'runA'), 's2', '03-parts', True, 1000)
    b_new = mk(os.path.join(logs, 'runB'), 's2', '03-parts', True, 2000)
    mk(os.path.join(logs, 'runC'), 's2', '03-parts', False, 3000)
    deep = mk(os.path.join(logs, 'grp', 'runD'), 's3', '01-trellis')
    r = {s: (f, h) for s, f, h in P.collect({'s2': {}, 's3': {}}, [], logs, old)}
    ok(r['s2'][0]['03-parts'] == b_new and r['s2'][1]['03-parts'] == 'search', 'запасной поиск: прошедший самый свежий, помечен search')
    ok(r['s3'][0]['01-trellis'] == deep and r['s3'][1]['01-trellis'] == 'search', 'запасной поиск на глубине 2')
    # выходная папка — не источник; нигде нет — «нет этапа»
    mk(out, 's4', '03-parts')
    r = {s: (f, h) for s, f, h in P.collect({'s4': {}, 's5': {}}, [], logs, old, skip=(out,))}
    ok('03-parts' not in r['s4'][0], 'выходная папка пропускается')
    ok(r['s5'][0] == {}, 'нигде нет — «нет этапа», без выдумывания')
    # сборка: симлинк один раз + sources.json с how; paint_check видит search
    rows3 = P.collect({'s2': {}}, [], logs, old)
    n = P.link(rows3, out)
    src = json.load(open(os.path.join(out, 's2', P.SOURCES)))['sources']
    ok(n == 1 and os.path.islink(os.path.join(out, 's2', '03-parts')) and src['03-parts']['how'] == 'search' and P.link(rows3, out) == 0, 'симлинк один раз; sources.json несёт how')
    sys.path.insert(0, os.path.join(HERE, 'salad', 'trellis'))
    try:
        import paint_check as PC
        ok(PC._sources_by_search(out, 's2') == ['03-parts'] and PC._sources_by_search(out, 'sX') == [], 'paint_check: этапы «по поиску» читаются из sources.json, файла нет — пусто')
    except ImportError as e:  # нет numpy/PIL в окружении — проверка пометки пропущена явно
        print('  ~ paint_check не импортируется:', e)
print(f'tests_plan09: ошибок {bad}')
sys.exit(1 if bad else 0)
