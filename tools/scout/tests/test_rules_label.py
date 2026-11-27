#!/usr/bin/env python3
"""Метка набора правил и разница деревьев списком ключей (T-20261127-175/12, tools/scout/rules_label.py).
Проверяется: метка не зависит от пробелов/порядка ключей/комментариев `_…`, но двигается значением, новым ключом, файлом, переменной окружения; два дерева с одним
содержимым — одна метка; разница печатается ключами и делится на состав/значения; объявленные ключи (флаги пробы) разрешены, прочие — нет; метка пишется в check.json и
run_all.json; реальные правила репо — метка считается и стабильна.
Запуск: python3 tools/scout/tests/test_rules_label.py"""
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'assets'))
import remlab_tmp  # noqa: E402
remlab_tmp.use('test_rules_label')
import tempfile  # noqa: E402
import rules_label as RL  # noqa: E402
import paint_stage as PS  # noqa: E402

FAIL = 0
REPO = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
CFG = {'include': ['tools/scout/rules'], 'exclude': ['auto.json'], 'env': ['RL_TEST_RULES', 'RL_TEST_FLAG'], 'length': 12}


def ok(cond, name):
    global FAIL
    print(('  ✓ ' if cond else '  ✗ ') + name)
    FAIL += 0 if cond else 1


BASE = tempfile.mkdtemp(prefix='rl-')


def tree(name, files):
    root = os.path.join(BASE, name)
    for rel, txt in files.items():
        p = os.path.join(root, 'tools', 'scout', 'rules', rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, 'w', encoding='utf-8') as f:
            f.write(txt if isinstance(txt, str) else json.dumps(txt, ensure_ascii=False))
    os.makedirs(os.path.join(root, 'tools', 'scout', 'rules'), exist_ok=True)
    return root


def lab(root):
    return RL.label(root, CFG)['id']


R = {'gate': {'photo_only': False, 'min_px': 200}, 'order': ['a', 'b'], '_about': 'комментарий'}
A = tree('a', {'part.json': R, 'sub/x.json': {'k': 1}})

print('== метка')
ok(len(lab(A)) == 12 and lab(A) != 'norules', 'метка — 12 знаков')
B = tree('b', {'part.json': json.dumps(R, indent=4, ensure_ascii=False), 'sub/x.json': '{ "k" : 1 }'})
ok(lab(A) == lab(B), 'два дерева с тем же содержимым (другие пробелы и отступы) — ОДНА метка (два прогона с одной меткой — одни правила)')
C = tree('c', {'part.json': {'order': ['a', 'b'], 'gate': {'min_px': 200, 'photo_only': False}, '_about': 'совсем другой комментарий'}, 'sub/x.json': {'k': 1}})
ok(lab(A) == lab(C), 'порядок ключей и правка комментария «_about» метку не двигают')
D = tree('d', {'part.json': {**R, 'gate': {'photo_only': True, 'min_px': 200}}, 'sub/x.json': {'k': 1}})
ok(lab(A) != lab(D), 'значение флага другое — метка другая')
E = tree('e', {'part.json': {**R, 'new_key': 1}, 'sub/x.json': {'k': 1}})
ok(lab(A) != lab(E), 'новый ключ — метка другая')
F = tree('f', {'part.json': R, 'sub/x.json': {'k': 1}, 'sub/y.json': {'z': 0}})
ok(lab(A) != lab(F), 'новый файл правил (в подпапке) — метка другая')
G = tree('g', {'part.json': R, 'sub/x.json': {'k': 1}, 'auto.json': {'мусор': 1}})
ok(lab(A) == lab(G), 'файл из exclude метку не двигает')
H = tree('h', {'part.json': {**R, 'order': ['b', 'a']}, 'sub/x.json': {'k': 1}})
ok(lab(A) != lab(H), 'порядок в СПИСКЕ (order) — значение: метка другая')
ok(RL.label(tree('empty', {}), CFG)['id'] == 'norules', 'нет правил — «norules», не падение')
bad = tree('bad', {'part.json': '{не json'})
ok(RL.label(bad, CFG)['id'] not in ('norules', ''), 'битый JSON — метка считается по байтам, этап не падает')

print('== окружение')
os.environ.pop('RL_TEST_RULES', None)
os.environ.pop('RL_TEST_FLAG', None)
l0 = lab(A)
os.environ['RL_TEST_FLAG'] = '1'
l1 = lab(A)
ok(l1 != l0 and RL.label(A, CFG)['env'] == {'RL_TEST_FLAG': {'value': '1'}}, 'выставленная переменная из env двигает метку и видна в отчёте')
os.environ.pop('RL_TEST_FLAG')
ok(lab(A) == l0, 'переменная снята — метка прежняя')
ov = os.path.join(BASE, 'over-RULES.json')
open(ov, 'w').write('{"x": 1}')
os.environ['RL_TEST_RULES'] = ov
m1 = lab(A)
open(ov, 'w').write('{"x": 2}')
m2 = lab(A)
os.environ.pop('RL_TEST_RULES')
ok(m1 != l0 and m1 != m2, 'подмена файла правил через переменную …RULES: метка зависит и от СОДЕРЖИМОГО того файла')

print('== разница списком ключей')
P = tree('probe', {'part.json': {'gate': {'photo_only': True, 'min_px': 200, 'photo_denominator': {'enabled': True}}, 'order': ['a', 'b']}, 'sub/x.json': {'k': 1}, 'sub/only.json': {'q': 1}})
d = RL.diff_trees(P, A, CFG)
keys = {(e['kind'], e['file'].split('/')[-1], e['key']) for e in d}
ok(('значение', 'part.json', 'gate.photo_only') in keys, 'значение флага — в списке: gate.photo_only')
ok(('только_A', 'part.json', 'gate.photo_denominator.enabled') in keys, 'ключ только у пробы — «состав»: gate.photo_denominator.enabled')
ok(any(e['kind'] == 'файл_только_A' and e['file'].endswith('only.json') for e in d), 'файл только у пробы — «состав»')
ok(not any(e['file'].endswith('x.json') for e in d), 'одинаковый файл в разницу не попадает')
ok(RL.diff_trees(A, B, CFG) == [], 'совпадающие наборы — пустая разница')
text = '\n'.join(RL.render(d, None, 'проба', 'основная'))
ok('СОСТАВ' in text and 'ЗНАЧЕНИЯ' in text and 'gate.photo_only  проба=true  основная=false' in text, 'печать: состав отдельно от значений, ключ и обе стороны')
ok(('значение', 'part.json', 'gate.photo_only') not in {(e['kind'], e['file'].split('/')[-1], e['key']) for e in RL.diff_trees(A, B, CFG)}, 'форматирование не создаёт ложной разницы')

print('== объявленные ключи (флаги пробы)')
okd, bad_, unused = RL.split_declared(d, ['part.json::gate.photo_only', 'gate.photo_denominator', 'only.json::'])
ok(len(bad_) == 0 and len(okd) == len(d), 'объявлены все: ключ, префикс по точке, весь файл — «не объявлено» нет')
okd, bad_, unused = RL.split_declared(d, ['gate.photo_only'])
ok(len(bad_) == len(d) - 1 and okd[0]['key'] == 'gate.photo_only', 'объявлен один — остальные «не объявлено» (молча не накладывается)')
okd, bad_, unused = RL.split_declared(d, ['gate.photo_only', 'нет.такого'])
ok(unused == ['нет.такого'], 'объявлено, но разницы нет — отдельное предупреждение')
ok('❗ не объявлено' in '\n'.join(RL.render(d, ['gate.photo_only'])), 'в печати «не объявлено» помечено')

print('== CLI')
PY = sys.executable
env = dict(os.environ)
r = subprocess.run([PY, '-I', os.path.join(REPO, 'tools/scout/rules_label.py'), '--diff', A, B], capture_output=True, text=True, env=env)
ok(r.returncode == 0 and 'совпадают' in r.stdout, 'CLI --diff одинаковых: код 0')
r = subprocess.run([PY, '-I', os.path.join(REPO, 'tools/scout/rules_label.py'), '--diff', P, A], capture_output=True, text=True, env=env)
ok(r.returncode == 1 and 'gate.photo_only' in r.stdout, 'CLI --diff разных: код 1, ключи в выводе')
r = subprocess.run([PY, '-I', os.path.join(REPO, 'tools/scout/rules_label.py'), '--diff', P, A, '--declared', 'gate.photo_only,gate.photo_denominator,only.json::'], capture_output=True, text=True, env=env)
ok(r.returncode == 0, 'CLI --diff с объявленными ключами: все объявлены — код 0')
r = subprocess.run([PY, '-I', os.path.join(REPO, 'tools/scout/rules_label.py'), '--diff', P, A, '--declared', 'gate.photo_only'], capture_output=True, text=True, env=env)
ok(r.returncode == 1 and '❗ не объявлено' in r.stdout, 'CLI --diff: есть необъявленное — код 1')
real = subprocess.run([PY, '-I', os.path.join(REPO, 'tools/scout/rules_label.py'), '--root', REPO, '--json'], capture_output=True, text=True, env=env)
rl = json.loads(real.stdout)
ok(real.returncode == 0 and len(rl['id']) == 12 and rl['n'] >= 50, f"реальные правила репо: метка {rl['id']}, файлов {rl['n']}")
again = subprocess.run([PY, '-I', os.path.join(REPO, 'tools/scout/rules_label.py'), '--root', REPO, '--json'], capture_output=True, text=True, env=env)
ok(json.loads(again.stdout)['id'] == rl['id'], 'повтор — та же метка (стабильна)')
exp = subprocess.run([PY, '-I', os.path.join(REPO, 'tools/scout/rules_label.py'), '--root', REPO, '--expect', rl['id']], capture_output=True, text=True, env=env)
ok(exp.returncode == 0, '--expect с верной меткой — код 0')
exp = subprocess.run([PY, '-I', os.path.join(REPO, 'tools/scout/rules_label.py'), '--root', REPO, '--expect', 'deadbeef0000'], capture_output=True, text=True, env=env)
ok(exp.returncode == 1 and '≠' in exp.stderr, '--expect с чужой меткой — код 1')

print('== отчёты этапов')
d1 = os.path.join(BASE, 'run1', 'sku1', '07-fill')
doc = PS.write_check(d1, '07-fill', 'sku1', None, {'name': 'empty_share', 'value': 0.0, 'threshold': 0.0, 'op': '<='})
disk = json.load(open(os.path.join(d1, 'check.json'), encoding='utf-8'))
ok(disk['rules_label']['id'] == RL.field(REPO)['id'] and len(disk['rules_label']['id']) == 12, f"check.json несёт rules_label.id = метка этого дерева ({disk['rules_label']['id']})")
ok(doc['rules_label'] == disk['rules_label'] and disk['passed'] is True, 'возврат write_check = то, что на диске; прежние поля на месте')
ok({'version', 'stage', 'sku', 'passed', 'metric', 'metrics', 'extra', 'reason', 'seconds', 'outputs', 'frame'} <= set(disk), 'прежние ключи схемы check.json не потеряны')
ok(PS.read_check(d1)['rules_label'] == disk['rules_label'], 'read_check отдаёт метку читателю (circle_origin и др.)')
import paint_run_all as RA  # noqa: E402
ok(RA.PS._rules_label()['id'] == disk['rules_label']['id'], 'paint_run_all берёт ту же запись (run_all.json.rules_label)')
src = open(os.path.join(REPO, 'tools/scout/paint_run_all.py'), encoding='utf-8').read()
ok("'rules_label': PS._rules_label()" in src, 'журнал run_all.json получает rules_label при старте прогона')

print('== проба = ветка = основная копия по составу (реальные правила репо)')
cp = os.path.join(BASE, 'copy')
os.makedirs(os.path.join(cp, 'tools'))
shutil.copytree(os.path.join(REPO, 'tools', 'scout', 'rules'), os.path.join(cp, 'tools', 'scout', 'rules'))
ok(RL.diff_trees(cp, REPO) == [] and RL.label(cp)['id'] == RL.label(REPO)['id'], 'копия правил репо = репо: пустая разница, одна метка')
pm = os.path.join(cp, 'tools', 'scout', 'rules', 'part-material.json')
dj = json.load(open(pm, encoding='utf-8'))
dj['флаг_пробы'] = {'enabled': True}
json.dump(dj, open(pm, 'w', encoding='utf-8'), ensure_ascii=False)
dd = RL.diff_trees(cp, REPO)
ok(len(dd) == 1 and dd[0]['kind'] == 'только_A' and dd[0]['key'] == 'флаг_пробы.enabled', 'лишний ключ пробы — ровно он в списке')
ok(RL.label(cp)['id'] != RL.label(REPO)['id'], 'и метка пробы другая — в отчёте этапа видно, что это не основной набор')

shutil.rmtree(BASE, ignore_errors=True)
print(f'rules_label: ошибок {FAIL}')
sys.exit(1 if FAIL else 0)
