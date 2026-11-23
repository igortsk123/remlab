"""Тесты сбора входа этапа 09 (plan09.py) на заглушках: происхождение пакета выигрывает у «самого свежего», приоритетные корни, запасной поиск с пометкой, пропуск своей папки, «нет этапа»; пометка в paint_check."""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import plan09 as P  # noqa: E402
import remlab_tmp  # noqa: E402
remlab_tmp.use('tests_plan09')                                                  # временное — на диске и с уборкой (T-20261107-13)

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
    # прежняя сборка plan09 (sources.json рядом) не источник: запасной поиск не читает свои же `run09*` (круг)
    old_out = os.path.join(logs, 'run09old')
    mk(old_out, 's7', '03-parts', True, 99999)
    json.dump({'sources': {}}, open(os.path.join(old_out, 's7', P.SOURCES), 'w'))
    real7 = mk(os.path.join(logs, 'realrun'), 's7', '03-parts', True, 10)
    r = {s: (f, h) for s, f, h in P.collect({'s7': {}}, [], logs, old)}
    ok(r['s7'][0].get('03-parts') == real7, f'запасной поиск берёт настоящий прогон, а не прежнюю сборку plan09 (свежее, но симлинк): {r["s7"][0].get("03-parts")}')
    only = os.path.join(logs, 'onlycol')
    mk(only, 's8', '03-parts', True, 5)
    json.dump({'sources': {}}, open(os.path.join(only, 's8', P.SOURCES), 'w'))
    r = {s: (f, h) for s, f, h in P.collect({'s8': {}}, [], logs, old)}
    ok('03-parts' not in r['s8'][0], 'есть только прежняя сборка → «нет этапа», а не выдача сборки за прогон')
    # этап с исходным фото (05): берётся, только если фото check.json = фото пакета по sha256 (T-20261123-46)
    ph_pkg = touch(os.path.join(logs, 'pk', 'p.png'))
    open(ph_pkg, 'w').write('PHOTO-A')
    ph_old = touch(os.path.join(logs, 'oldin', 'p.png'))
    open(ph_old, 'w').write('PHOTO-B')
    ph_same = touch(os.path.join(logs, 'copy', 'p.png'))
    open(ph_same, 'w').write('PHOTO-A')

    def mk5(root, sku, src, mtime=1000):
        d = os.path.join(root, sku, '05-delight')
        os.makedirs(d, exist_ok=True)
        json.dump({'passed': True, 'extra': ({'source_photo': src} if src else {})}, open(os.path.join(d, 'check.json'), 'w'))
        os.utime(os.path.join(d, 'check.json'), (mtime, mtime))
        return d
    old5 = {'05-delight': [prio]}
    d_bad = mk5(prio, 'q1', ph_old)
    r = {s: (f, h) for s, f, h in P.collect({'q1': {'photo': ph_pkg}}, [], logs, old5)}
    ok('05-delight' not in r['q1'][0], '05 с другим фото (sha256) из приоритетного корня не берётся → «нет этапа»')
    d_ok = mk5(prio, 'q2', ph_same)
    r = {s: (f, h) for s, f, h in P.collect({'q2': {'photo': ph_pkg}}, [], logs, old5)}
    ok(r['q2'][0].get('05-delight') == d_ok, '05 с копией того же фото (другой путь, тот же sha256) берётся')
    r = {s: (f, h) for s, f, h in P.collect({'q1': {}}, [], logs, old5)}
    ok(r['q1'][0].get('05-delight') == d_bad, 'у пакета нет фото — сверять не с чем, этап берётся как раньше')
    mk5(prio, 'q3', None)
    r = {s: (f, h) for s, f, h in P.collect({'q3': {'photo': ph_pkg}}, [], logs, old5)}
    ok('05-delight' not in r['q3'][0], '05 без source_photo в check.json (старый) — сверить нечем, не берётся')
    p3 = mk(prio, 'q3b', '03-parts')
    r = {s: (f, h) for s, f, h in P.collect({'q3b': {'photo': ph_pkg}}, [], logs, old)}
    ok(r['q3b'][0].get('03-parts') == p3, 'этап вне PHOTO_STAGES без source_photo (03) берётся как раньше')
    mk5(prio, 'q4', os.path.join(logs, 'стёрто.png'))
    r = {s: (f, h) for s, f, h in P.collect({'q4': {'photo': ph_pkg}}, [], logs, old5)}
    ok('05-delight' not in r['q4'][0], 'фото check.json стёрто — сверить нечем, этап не берётся')
    # запасной поиск: из двух прогонов берётся тот, что на фото пакета, а не самый свежий
    mk5(os.path.join(logs, 'sa'), 'q5', ph_old, 9000)
    good5 = mk5(os.path.join(logs, 'sb'), 'q5', ph_same, 10)
    r = {s: (f, h) for s, f, h in P.collect({'q5': {'photo': ph_pkg}}, [], logs, {'05-delight': []})}
    ok(r['q5'][0].get('05-delight') == good5 and r['q5'][1]['05-delight'] == 'search', 'запасной поиск: берётся прогон на фото пакета, не самый свежий')
    # сборка старого вида (без sources.json): симлинк этапа рядом с 09-check — тоже не источник
    olds = os.path.join(logs, 'run09older')
    os.makedirs(os.path.join(olds, 's9', '09-check'))
    real9 = mk(os.path.join(logs, 'realrun9'), 's9', '03-parts', True, 10)
    os.symlink(real9, os.path.join(olds, 's9', '03-parts'))
    os.utime(real9 + '/check.json', (10, 10))
    r = {s: (f, h) for s, f, h in P.collect({'s9': {}}, [], logs, old)}
    ok(r['s9'][0].get('03-parts') == real9, f'симлинк старой сборки без sources.json не берётся как «найденный прогон»: {r["s9"][0].get("03-parts")}')
    # сборка: симлинк один раз + sources.json с how; paint_check видит search
    rows3 = P.collect({'s2': {}}, [], logs, old)
    n = P.link(rows3, out)
    src = json.load(open(os.path.join(out, 's2', P.SOURCES)))['sources']
    ok(n == 1 and os.path.islink(os.path.join(out, 's2', '03-parts')) and src['03-parts']['how'] == 'search' and P.link(rows3, out) == 0, 'симлинк один раз; sources.json несёт how')
    sys.path.insert(0, os.path.join(HERE, 'salad', 'trellis'))
    try:
        import paint_check as PC
        ok(PC._sources_by_search(out, 's2') == ['03-parts'] and PC._sources_by_search(out, 'sX') == [], 'paint_check: этапы «по поиску» читаются из sources.json, файла нет — пусто')
        rules = PC.load_rules()
        st = [{'stage': '03-parts', 'status': 'ok', 'reason': '', 'hard_failed': [], 'soft_failed': [], 'metrics': {'a': {}}, 'run': '/x/other'},
              {'stage': '01-trellis', 'status': 'ok', 'reason': '', 'hard_failed': [], 'soft_failed': [], 'metrics': {}, 'run': '/x/own'}]
        done = PC.apply_search_sources(st, ['03-parts'], rules)
        ok(done == ['03-parts'] and st[0]['status'] == 'missing' and '/x/other' in st[0]['reason'] and 'нет данных' in st[0]['reason'] and st[1]['status'] == 'ok',
           'этап «по поиску» → нет данных (missing), причина называет чужой прогон; свой этап не тронут')
        v = PC.judge_product([dict(s, status=s['status']) for s in st], {'status': 'ok', 'stage': 'coverage', 'reason': ''}, rules)
        ok(v['final'] == 'not_ready' and '03-parts' in v['blocking'], 'итог товара «не готов», блокирует этап без своих данных')
        st2 = [{'stage': '03-parts', 'status': 'ok', 'reason': '', 'hard_failed': [], 'soft_failed': [], 'metrics': {}, 'run': '/x/other'}]
        ok(PC.apply_search_sources(st2, ['03-parts'], dict(rules, sources={'search': 'note'})) == [] and st2[0]['status'] == 'ok', 'правило sources.search=note — как раньше (пометка, этап как был)')
    except ImportError as e:  # нет numpy/PIL в окружении — проверка пометки пропущена явно
        print('  ~ paint_check не импортируется:', e)
print(f'tests_plan09: ошибок {bad}')
sys.exit(1 if bad else 0)
