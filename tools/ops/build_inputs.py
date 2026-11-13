#!/usr/bin/env python3
"""ВХОДЫ СБОРКИ ВИТРИНЫ — какие файлы правил читает `flat215_demo.py` (T-20261112-121/2; директор 13.11: публикация /demo
отказала сборке, потому что, пока она шла, влили НОВЫЙ `tools/scout/rules/tour-auto-photos.json` — витрина его не читает, а метка
`build_stamp.py` считалась по всей `rules/**`; ночью сборка и публикация идут подряд, вливают и ночью → выкладка срывалась бы
без причины).

Список входов — ОДИН: `tools/scout/build_stamp.py:DEMO_INPUTS` (файлы правил и папки целиком, `room-templates/`). Метка правил
считается только по нему: новый файл в rules/** вне списка метку не двигает. Этот модуль сторожит обратное — правило, которое
сборка читает, а в список не попало:
  • статически (CI, prepush — через `conveyor_check.py`): от `flat215_demo.py` по настоящим импортам Python (в т.ч. внутри
    функций) и по скриптам, которые код запускает (`subprocess.run(...)` с `*.py`/`*.mjs`, их `import` из Node), — строки, где
    названо правило (`demo-swap.json`, `profiles/`, `room-templates/`); упомянутое правило вне списка → красный, в списке, но
    никем не упомянутое → WARN (лишнее двигает метку зря). Докстринги и самопроверки — не чтение.
  • на ходу (сборка): `build_stamp.watch_rules()` слушает открытия файлов в процессе сборки; прочла правило вне списка —
    строка `WARN:build_inputs:` в журнал ночи (путь, собранный на ходу, статикой не виден).
Скрипты оболочки (`*.sh`) не обходим: сборка их не зовёт (публикация — отдельный шаг ночи).

  python tools/ops/build_inputs.py              # проверка дерева
  python tools/ops/build_inputs.py --list       # кто какое правило называет
  python tools/ops/build_inputs.py --selftest
"""
from __future__ import annotations

import ast
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT_DEFAULT = os.path.abspath(os.path.join(HERE, '..', '..'))
START = 'tools/scout/flat215_demo.py'
SKIP = ('tools/scout/build_stamp.py',)            # сам держит список — его строки не чтение
PY_DIRS = ('tools/scout', 'services/planner-solver', 'tools/assets', 'tools/flat3d', 'tools/ops')
RUNNERS = {'run', 'Popen', 'check_output', 'check_call', 'call'}
SCRIPT = re.compile(r'[\w./-]*?([\w-]+\.(?:py|mjs|cjs|js))(?![\w.])')
JS_IMPORT = re.compile(r'''(?:\bimport\s[^'"`;]*?from\s*|\bimport\s*\(?\s*|\brequire\s*\(\s*)['"]([^'"]+)['"]''')
JS_STR = re.compile(r'//[^\n]*|/\*.*?\*/|"(?:[^"\\\n]|\\.)*"|\'(?:[^\'\\\n]|\\.)*\'|`(?:[^`\\]|\\.)*`', re.S)
TEST = re.compile(r'(^|/)(tests?|__tests__|fixtures)/|(^|/)tests?_[^/]*\.py$|_test\.py$|selftest')
SELFTEST_FN = re.compile(r'^_?(selftest|self_test|test)(_|$)')


def _stamp(root: str):
    """build_stamp.py ЭТОЙ копии `root` (по пути файла, не из кэша импорта)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location('_build_stamp_of_root', os.path.join(root, 'tools', 'scout', 'build_stamp.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def rule_index(root: str, dirs) -> tuple[list[str], list[str]]:
    """→ (все файлы правил, подпапки правил) от корня."""
    files, subs = [], set()
    for d in dirs:
        for dp, _dn, fn in os.walk(os.path.join(root, d)):
            for f in fn:
                if f.endswith('.json'):
                    rel = os.path.relpath(os.path.join(dp, f), root).replace(os.sep, '/')
                    files.append(rel)
                    if os.path.dirname(rel) != d:          # папка правил первого уровня (room-templates/, profiles/)
                        subs.add(d + '/' + rel[len(d) + 1:].split('/', 1)[0] + '/')
    return sorted(files), sorted(subs)


def _py(src: str):
    """→ (строки — без докстрингов и функций самопроверки, имена модулей, строки в вызовах subprocess)."""
    tree = ast.parse(src)
    docs = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.body:
            f = n.body[0]
            if isinstance(f, ast.Expr) and isinstance(f.value, ast.Constant) and isinstance(f.value.value, str):
                docs.add(id(f.value))
    strs, mods, runs = [], [], []

    def consts(node):
        return [c.value for c in ast.walk(node) if isinstance(c, ast.Constant) and isinstance(c.value, str)]

    def walk(node):
        for ch in ast.iter_child_nodes(node):
            if isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef)) and SELFTEST_FN.match(ch.name):
                continue
            if isinstance(ch, ast.Constant) and isinstance(ch.value, str) and id(ch) not in docs:
                strs.append(ch.value)
            elif isinstance(ch, ast.Import):
                mods.extend(a.name for a in ch.names)
            elif isinstance(ch, ast.ImportFrom) and ch.module:
                mods.append(ch.module)
                mods.extend(f'{ch.module}.{a.name}' for a in ch.names)
            elif isinstance(ch, ast.Call):
                fn = ch.func
                name = fn.attr if isinstance(fn, ast.Attribute) else fn.id if isinstance(fn, ast.Name) else ''
                if name in RUNNERS:
                    runs.extend(consts(ch))
            walk(ch)
    walk(tree)
    return strs, mods, runs


def _js(src: str):
    strs, mods = [], []
    for m in JS_STR.finditer(src):
        if not m.group(0).startswith('/'):
            strs.append(m.group(0)[1:-1])
    for m in JS_IMPORT.finditer(JS_STR.sub(lambda t: t.group(0) if not t.group(0).startswith('/') else ' ', src)):
        mods.append(m.group(1))
    return strs, mods


def _resolve(root: str, frm: str, rel: str) -> str | None:
    for base in (os.path.dirname(frm), '', 'tools/scout'):
        p = os.path.normpath(os.path.join(base, rel.lstrip('/'))).replace(os.sep, '/')
        if not p.startswith('..') and os.path.isfile(os.path.join(root, p)):
            return p
    return None


def _py_module(root: str, frm: str, name: str) -> str | None:
    parts = name.split('.')
    for base in (os.path.dirname(frm),) + PY_DIRS:
        p = os.path.join(base, *parts)
        for cand in (p + '.py', os.path.join(p, '__init__.py')):
            if os.path.isfile(os.path.join(root, cand)):
                return os.path.normpath(cand).replace(os.sep, '/')
    return None


def scan(root: str, start: str = START, dirs=None) -> dict[str, set[str]]:
    """→ {правило или папка правил/: {файлы кода, которые его называют}} по замыканию сборки от `start`."""
    dirs = dirs or _stamp(root).RULE_DIRS
    files, subs = rule_index(root, dirs)
    by_base: dict[str, list[str]] = {}
    for f in files:
        by_base.setdefault(os.path.basename(f), []).append(f)
    seen, queue, refs = set(), [start], {}
    while queue:
        f = queue.pop()
        if f in seen or f in SKIP or TEST.search(f):
            continue
        seen.add(f)
        try:
            with open(os.path.join(root, f), encoding='utf-8') as fh:
                src = fh.read()
        except (OSError, UnicodeDecodeError):
            continue
        if f.endswith('.py'):
            try:
                strs, mods, runs = _py(src)
            except (SyntaxError, ValueError):
                continue
            nxt = [_py_module(root, f, m) for m in mods]
            for s in runs:
                for m in SCRIPT.finditer(s):
                    nxt.append(_resolve(root, f, m.group(0)))
        else:
            strs, mods = _js(src)
            nxt = [_resolve(root, f, m) for m in mods if m.startswith('.') or m.startswith('/')]
        queue.extend(p for p in nxt if p and p.endswith(('.py', '.mjs', '.cjs', '.js')))
        for s in strs:
            s = s.strip()
            if s.endswith('.json'):
                tail = s.replace('\\', '/')
                for cand in by_base.get(os.path.basename(tail), []):
                    if '/' not in tail or cand.endswith(tail.lstrip('./')) or tail.endswith(cand.split('/rules/', 1)[-1]):
                        refs.setdefault(cand, set()).add(f)
            for sd in subs:
                name = sd.rstrip('/').rsplit('/', 1)[-1]
                if s == name or f'{name}/' in s or s.endswith(f'/{name}'):
                    refs.setdefault(sd, set()).add(f)
    return refs


def covered(path: str, inputs) -> bool:
    return any(path == i or (i.endswith('/') and path.startswith(i)) for i in inputs)


def check(root: str, out=sys.stdout, inputs=None, dirs=None) -> int:
    """Код 1 — сборка называет правило вне `DEMO_INPUTS` или в списке путь, которого нет."""
    if inputs is None or dirs is None:
        bs = _stamp(root)
        inputs = list(bs.DEMO_INPUTS) if inputs is None else inputs
        dirs = bs.RULE_DIRS if dirs is None else dirs
    refs = scan(root, dirs=dirs)
    bad = 0
    for i in inputs:
        if not (os.path.isfile(os.path.join(root, i)) or (i.endswith('/') and os.path.isdir(os.path.join(root, i)))):
            print(f'FAIL:build_inputs: в build_stamp.DEMO_INPUTS {i} — такого правила нет', file=out)
            bad += 1
    for r in sorted(refs):
        if not covered(r, inputs):                   # названа папка — во входах должна быть папка целиком
            print(f'FAIL:build_inputs: сборка витрины называет {r} ({", ".join(sorted(refs[r])[:3])}), а в build_stamp.DEMO_INPUTS '
                  f'его нет — метка не заметит его правку; добавить в список', file=out)
            bad += 1
    for i in inputs:
        if not any(covered(r, [i]) or r == i for r in refs) and not any(r.startswith(i) for r in refs):
            print(f'WARN:build_inputs: {i} в DEMO_INPUTS, но код сборки его не называет — лишний вход двигает метку зря', file=out)
    print(f'входы сборки витрины: в списке {len(inputs)}, код называет {len(refs)}, вне списка {bad}', file=out)
    return 1 if bad else 0


def _selftest() -> int:
    import io
    import tempfile
    bad = []

    def ok(c, m, info=''):
        print(('OK  ' if c else 'BAD ') + m + ('' if c else f' :: {info}'))
        if not c:
            bad.append(m)

    with tempfile.TemporaryDirectory(prefix='build-inputs-') as d:
        def put(rel, text):
            p = os.path.join(d, rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, 'w', encoding='utf-8') as f:
                f.write(text)

        R = 'tools/scout/rules'
        for rel in ('demo-swap.json', 'quiz.json', 'other.json', 'profiles/living.json', 'profiles/hall.json'):
            put(f'{R}/{rel}', '{}')
        put('services/planner-solver/rules/room-templates/living.json', '{}')
        put('services/planner-solver/rules/occupancy.json', '{}')
        put('tools/scout/flat215_demo.py',
            '"""Докстринг: other.json — не чтение."""\n'
            'import os, subprocess\nimport helper\n'
            "SW = os.path.join('rules', 'demo-swap.json')\n"
            'def build(root):\n'
            "    subprocess.run(['bash', '-c', f'node \"{root}/tools/flat3d/cams.mjs\"'])\n"
            "    subprocess.run(['python3', 'solver.py'])\n"
            'def _selftest():\n'
            "    open('rules/quiz.json')\n")
        put('tools/scout/helper.py', "def prof(room):\n    return os.path.join(HERE, 'rules', 'profiles', f'{room}.json')\n")
        put('tools/scout/solver.py', 'import planner.zones\n')
        put('services/planner-solver/planner/__init__.py', '')
        put('services/planner-solver/planner/zones.py',
            "RT = os.path.join(RULES, 'room-templates')\nOCC = 'occupancy.json'\n")
        put('tools/flat3d/cams.mjs', "import { x } from './lib/a.mjs';\n// rules/other.json в комментарии\n")
        put('tools/flat3d/lib/a.mjs', "const q = join(ROOT, 'tools/scout/rules/quiz.json');\n")
        dirs = ('services/planner-solver/rules', R)
        refs = scan(d, dirs=dirs)
        ok('tools/scout/rules/demo-swap.json' in refs, 'своя строка сборки — вход', refs)
        ok('tools/scout/rules/profiles/' in refs, 'папка профилей через импорт и f-строку — вход', refs)
        ok('services/planner-solver/rules/room-templates/' in refs and 'services/planner-solver/rules/occupancy.json' in refs,
           'шаблоны комнат и нормы — через запускаемый solver.py и его импорт', refs)
        ok('tools/scout/rules/quiz.json' in refs and refs['tools/scout/rules/quiz.json'] == {'tools/flat3d/lib/a.mjs'},
           'node-скрипт из subprocess и его import — вход; самопроверка Python — нет', refs)
        ok('tools/scout/rules/other.json' not in refs, 'докстринг и комментарий — не чтение', refs)
        full = ['tools/scout/rules/demo-swap.json', 'tools/scout/rules/quiz.json', 'tools/scout/rules/profiles/',
                'services/planner-solver/rules/room-templates/', 'services/planner-solver/rules/occupancy.json']
        buf = io.StringIO()
        ok(check(d, out=buf, inputs=full, dirs=dirs) == 0, 'все называемые правила в списке — код 0', buf.getvalue())
        buf = io.StringIO()
        rc = check(d, out=buf, inputs=[x for x in full if 'room-templates' not in x], dirs=dirs)
        ok(rc == 1 and 'FAIL:build_inputs' in buf.getvalue() and 'room-templates/' in buf.getvalue(),
           'сборка читает шаблоны комнат, а в списке их нет — код 1', buf.getvalue())
        buf = io.StringIO()
        rc = check(d, out=buf, inputs=full + ['tools/scout/rules/other.json'], dirs=dirs)
        ok(rc == 0 and 'WARN:build_inputs: tools/scout/rules/other.json' in buf.getvalue(), 'лишний вход — WARN, не красный', buf.getvalue())
        buf = io.StringIO()
        ok(check(d, out=buf, inputs=full + ['tools/scout/rules/нет.json'], dirs=dirs) == 1, 'вход без файла — код 1', buf.getvalue())
        ok(covered('services/planner-solver/rules/room-templates/living.json', ['services/planner-solver/rules/room-templates/'])
           and not covered('tools/scout/rules/other.json', ['tools/scout/rules/demo-swap.json']), 'папка в списке покрывает файлы под ней')
    real = scan(ROOT_DEFAULT)
    ok(not any('tour-auto-photos' in r for r in real), 'в репо: правило автофото тура сборка витрины не называет (13.11)', sorted(real))
    ok(any('room-templates' in r for r in real), 'в репо: шаблоны комнат — входы сборки')
    buf = io.StringIO()
    ok(check(ROOT_DEFAULT, out=buf) == 0, 'в репо: все называемые правила — в DEMO_INPUTS', buf.getvalue()[-600:])
    print('итог:', 'OK' if not bad else f'FAIL ({len(bad)})')
    return 1 if bad else 0


def main(argv: list[str]) -> int:
    if argv[:1] == ['--selftest']:
        return _selftest()
    if argv[:1] == ['--list']:
        for r, who in sorted(scan(ROOT_DEFAULT).items()):
            print(r, '←', ', '.join(sorted(who)))
        return 0
    return check(ROOT_DEFAULT)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
