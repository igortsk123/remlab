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

print('== «_»-ключи: комментарии-строки не в счёте, данные (число/флаг/объект) — в счёте (T-175/12-дыра)')
U0 = tree('u0', {'p.json': {'a': 1, '_about': 'комментарий', '_default': 0}})
ok(lab(U0) == lab(tree('u1', {'p.json': {'a': 1, '_about': 'другой текст комментария', '_default': 0}})), 'правка текстового «_about» метку не двигает')
ok(lab(U0) == lab(tree('u1b', {'p.json': {'a': 1, '_default': 0}})), 'и удаление текстового «_»-ключа метку не двигает')
ok(lab(U0) != lab(tree('u2', {'p.json': {'a': 1, '_about': 'комментарий', '_default': 1}})), '«_default»: 0 → 1 (число) метку ДВИГАЕТ — раньше был слепым пятном')
ok(lab(tree('u3', {'p.json': {'_flag': True}})) != lab(tree('u4', {'p.json': {'_flag': False}})), '«_»-ключ с флагом: True → False двигает метку')
ok(lab(tree('u5', {'p.json': {'_any': {'x': 1}}})) != lab(tree('u6', {'p.json': {'_any': {'x': 2}}})), '«_»-ключ с объектом: значение внутри двигает метку')
ok(lab(tree('u7', {'p.json': {'_any': {'x': 1, '_why': 'a'}}})) == lab(tree('u8', {'p.json': {'_any': {'x': 1, '_why': 'b'}}})), 'а текстовый комментарий ВНУТРИ такого объекта — по-прежнему не в счёте')
ok(lab(tree('u9', {'p.json': {'_list': [1, 2]}})) != lab(tree('u10', {'p.json': {'_list': [1, 3]}})), '«_»-ключ со списком — данные, двигает метку')
dd = RL.diff_trees(tree('v1', {'p.json': {'_default': 0, '_about': 'x'}}), tree('v2', {'p.json': {'_default': 1, '_about': 'y'}}), CFG)
ok(len(dd) == 1 and dd[0]['key'] == '_default', '--diff показывает ключ «_default» и не показывает комментарий «_about»')

print('== переменные окружения конвейера: реальный набор (T-175/12-дыра)')
real_cfg = RL.load_cfg(os.path.join(REPO, 'tools', 'scout', 'rules', 'rules-label.json'))
ok(RL.env_gaps(REPO) == [], 'сторож на реальном дереве: каждое чтение окружения в скриптах конвейера учтено: ' + '; '.join(RL.env_gaps(REPO)[:3]))
ok({'POSE_JUNCTION', 'TEX_VISIBLE_DEPTH_TILT', 'SIGMA', 'EDGE_BG_PX', 'TONE_SRC_COS', 'FILL_RULES', 'KNOWN_SYNTH_TRUSTED'} <= set(real_cfg['env']), 'в env — переменные, которые двигают результат (POSE_*, TEX_VISIBLE_*, SIGMA, EDGE_BG_*, FILL_RULES…)')
ok(len(real_cfg['env']) >= 40, f"в env не 4, а {len(real_cfg['env'])} переменных")
ok(all(isinstance(v, str) and v.strip() for v in real_cfg['env_ignore'].values()) and not (set(real_cfg['env']) & set(real_cfg['env_ignore'])), 'у каждой записи «не влияет» есть причина; в обоих списках не стоит ни одна')
base_id = RL.label(REPO)['id']
for var, val in (('POSE_JUNCTION', 'probe'), ('TEX_VISIBLE_DEPTH_TILT', '1'), ('SIGMA', '0.7')):
    old = os.environ.get(var)
    os.environ[var] = val
    try:
        RL._CACHE.clear()
        lb, fl = RL.label(REPO), RL.field(REPO)
        ok(lb['id'] != base_id and lb['env'].get(var, {}).get('value') == val, f'{var}={val}: метка сдвинулась ({base_id} → {lb["id"]})')
        ok(fl['id'] == lb['id'] and fl['env'].get(var, {}).get('value') == val, f'{var} видна в поле rules_label.env отчёта этапа')
    finally:
        os.environ.pop(var, None) if old is None else os.environ.__setitem__(var, old)
        RL._CACHE.clear()
ok(RL.label(REPO)['id'] == base_id, 'переменные сняты — метка вернулась')
os.environ['THREADS'] = '7'
ok(RL.label(REPO)['id'] == base_id and 'THREADS' not in RL.label(REPO)['env'], 'THREADS (число потоков, «не влияет») метку НЕ двигает')
os.environ.pop('THREADS', None)
fv = os.path.join(BASE, 'fill-rules.json')
shutil.copy(os.path.join(REPO, 'tools', 'scout', 'rules', 'paint-fill.json'), fv)
os.environ['FILL_RULES'] = fv
e1 = RL.label(REPO)['env']['FILL_RULES']
ok(len(e1.get('sha', '')) == 12, 'FILL_RULES (путь к файлу правил) входит в метку вместе с sha файла, на который указывает')
os.environ.pop('FILL_RULES', None)

print('== сторож окружения: выдуманная переменная в скрипте конвейера (отрицательные контроли)')


def conv(name, scripts, extra_rules=None):
    root = os.path.join(BASE, name)
    sc = os.path.join(root, 'tools', 'scout')
    os.makedirs(os.path.join(sc, 'rules'), exist_ok=True)
    json.dump({'stages': {'s1': {'steps': [{'argv': ['py', '{root}/tools/scout/fake_step.py']}]}}}, open(os.path.join(sc, 'rules', 'paint-run-all.json'), 'w'))
    for fn, txt in scripts.items():
        open(os.path.join(sc, fn), 'w', encoding='utf-8').write(txt)
    return root


GC = {'env': ['KNOWN_ONE'], 'env_ignore': {}}
r1 = conv('cv1', {'fake_step.py': "import os\nA = os.environ.get('KNOWN_ONE')\nB = os.environ.get('MY_NEW_KNOB', '1')\n"})
g = RL.env_gaps(r1, GC)
ok(len(g) == 1 and 'MY_NEW_KNOB' in g[0] and 'fake_step.py:3' in g[0], 'выдуманная переменная без записи → сторож КРАСНЫЙ с именем и файлом:строкой: ' + (g[0] if g else '—'))
ok(RL.env_gaps(r1, {'env': ['KNOWN_ONE', 'MY_NEW_KNOB'], 'env_ignore': {}}) == [], 'запись в env → зелёный')
ok(RL.env_gaps(r1, {'env': ['KNOWN_ONE'], 'env_ignore': {'MY_NEW_KNOB': 'число потоков, скорость'}}) == [], 'запись в «не влияет» С причиной → зелёный')
for bad in ('', '   ', None):
    gb = RL.env_gaps(r1, {'env': ['KNOWN_ONE'], 'env_ignore': {'MY_NEW_KNOB': bad}})
    ok(any('без причины' in x and 'MY_NEW_KNOB' in x for x in gb), f'запись «не влияет» БЕЗ причины ({bad!r}) → красный')
gb = RL.env_gaps(r1, {'env': ['KNOWN_ONE', 'MY_NEW_KNOB'], 'env_ignore': {'MY_NEW_KNOB': 'причина'}})
ok(any('одновременно' in x for x in gb), 'переменная в обоих списках → красный')
r2 = conv('cv2', {'fake_step.py': "import os\nimport helper_mod\n", 'helper_mod.py': "import os\nX = os.getenv('HELPER_KNOB')\n"})
g = RL.env_gaps(r2, GC)
ok(len(g) == 1 and 'HELPER_KNOB' in g[0] and 'helper_mod.py:3' in g[0] or (len(g) == 1 and 'HELPER_KNOB' in g[0] and 'helper_mod.py' in g[0]), 'переменная в ИМПОРТИРУЕМОМ модуле конвейера тоже ловится (файл: helper_mod.py)')
ok(RL.env_gaps(r2, dict(GC, env_stop={'tools/scout/helper_mod.py': 'GPU-воркер'})) == [], 'файл из env_stop не открывается (с причиной) → зелёный')
ok(RL.env_gaps(r2, dict(GC, env_leaf={'tools/scout/helper_mod.py': 'сам читаем, импорты не разворачиваем'})) != [], 'файл из env_leaf сам читается: его переменная по-прежнему красная')
r3 = conv('cv3', {'fake_step.py': "import os\nk = 'Z'\nA = os.environ['X_SUB']\nB = 'X_IN' in os.environ\nC = os.getenv('X_GETENV')\nD = (os.environ if k is None else {}).get('X_HIDE')\nE = os.environ.get(k)\n"})
g = RL.env_gaps(r3, GC)
names = ' '.join(g)
ok(all(n in names for n in ('X_SUB', 'X_IN', 'X_GETENV', 'X_HIDE')), 'ловятся все формы чтения: os.environ[..], «in os.environ», os.getenv, (os.environ if … else …).get')
ok(any('динамическое' in x and 'fake_step.py:7' in x for x in g), 'динамическое чтение (имя не литерал) → красный')
ok(not any('динамическое' in x for x in RL.env_gaps(r3, dict(GC, env=GC['env'] + ['X_SUB', 'X_IN', 'X_GETENV', 'X_HIDE'], env_ignore={'<динамическое>:fake_step.py': 'потоки'}))), 'запись «<динамическое>:файл» с причиной → зелёный')
ok(any('не прочитан' in x for x in RL.env_gaps(os.path.join(BASE, 'нет-такого-дерева'), GC)), 'нет рецепта → красный (сторож не слепнет молча)')
r4 = conv('cv4', {'fake_step.py': "def (:\n"})
ok(any('не разобран' in x for x in RL.env_gaps(r4, GC)), 'скрипт конвейера не разобрался → красный')
ok(subprocess.run([sys.executable, '-I', os.path.join(REPO, 'tools', 'scout', 'rules_label.py'), '--env-check', '--root', REPO], capture_output=True).returncode == 0, 'CLI `rules_label.py --env-check` на реальном дереве — код 0')
ok(subprocess.run([sys.executable, '-I', os.path.join(REPO, 'tools', 'scout', 'rules_label.py'), '--env-check', '--root', r1], capture_output=True).returncode in (0, 1), 'CLI на чужом корне не падает исключением')

shutil.rmtree(BASE, ignore_errors=True)
print(f'rules_label: ошибок {FAIL}')
sys.exit(1 if FAIL else 0)
