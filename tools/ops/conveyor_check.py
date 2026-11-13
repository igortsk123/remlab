"""РЕЕСТР КОНВЕЙЕРА — проверка (T-20261112-121, план conveyor-guards-01 шаг 2; владелец TG 1366/1370/1381: «всё по конвейеру…
поставь предохранители, чтобы пресекались любые ручные правки»; Codex `_intake/codex/2026-11-12-conveyor-guards-answer.md`).

Реестр `tools/ops/conveyor-manifest.yml`: каждый собранный файл → генератор → кто ещё вправе писать → ночной шаг → публикатор.
Что ловим (выход 1, строки FAIL):
  • РУЧНАЯ ПРАВКА собранного файла в git: `check: seal` — печать `_seal` сломана (`conveyor_seal.py`); `check: regen` — команда
    пересборки (`regen`) обязана стоять в ci.yml (её там и гоняют: файл = пересборка);
  • НЕИЗВЕСТНЫЙ ПИСАТЕЛЬ: код (tools/, services/, lib/, scripts/, app/), который пишет в собранный файл (открытие на запись,
    замена, копирование, `>` в shell — по имени файла или по переменной с ним), но не назван в `generator`/`writers` записи;
  • писатель файла с печатью, который не ставит печать (не импортирует conveyor_seal);
  • устаревший реестр: генератора/писателя/публикатора нет в репо, ночного шага нет в `refresh_daily.sh`.
Тесты и фикстуры (`tests/`, `test_*.py`, `tests_*.py`) не считаются писателями. Это не граница безопасности (обфускацию не
поймать) — граница будет на шаге 7 (права пользователя конвейера); здесь — чтобы обход не прошёл незамеченным в коммите.

    python3 tools/ops/conveyor_check.py              # проверка (CI scout-selftest; prepush — всегда)
    python3 tools/ops/conveyor_check.py --writers    # кто пишет каждый собранный файл (для заполнения реестра)
    python3 tools/ops/conveyor_check.py --selftest
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT_DEFAULT = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, HERE)
import conveyor_seal as SEAL  # noqa: E402

MANIFEST = 'tools/ops/conveyor-manifest.yml'
CODE_DIRS = ('tools/', 'services/', 'lib/', 'scripts/', 'app/', 'infra/')
CODE_EXT = ('.py', '.sh', '.mjs', '.cjs', '.js', '.ts')
NOT_WRITER = re.compile(r'(^|/)(tests?|fixtures|__tests__)/|(^|/)tests?_[^/]*\.py$|\.test\.ts$|(^|/)node_modules/|selftest[^/]*$')
SELFTEST = re.compile(r'selftest|self_test', re.I)
# операция записи: куда пишут — последний аргумент (замена/копия) или первый (открытие)
W_OPEN = re.compile(r'''open\(\s*([^,()]+(?:\([^()]*\))?[^,()]*)\s*,\s*['"](?:w|wb|a|ab|w\+|x)['"]''')
W_PATH = re.compile(r'''([\w.\[\]'"()/+ -]+?)\.(?:write_text|write_bytes)\(''')
W_LAST = re.compile(r'''(?:os\.replace|os\.rename|shutil\.copy2?|shutil\.copyfile|shutil\.move|renameSync|copyFileSync|rename|copyFile)\(([^;]*)\)''')
W_FIRST = re.compile(r'''(?:writeFileSync|writeFile|appendFileSync|createWriteStream|write_json|atomic_write\w*|dump_sealed|write_atomic\w*)\(\s*([^,;]+)''')
W_SH = re.compile(r'''(?:^|[;&|]\s*|\bthen\s+|\bdo\s+)(?:cp|mv|install|rsync)\s+(?:-\S+\s+)*\S+\s+(\S+)\s*$|>>?\s*("?[^\s;&|>]+"?)''')


def load(root: str) -> dict:
    import yaml
    with open(os.path.join(root, MANIFEST), encoding='utf-8') as f:
        return yaml.safe_load(f) or {}


def code_files(root: str) -> list:
    try:
        r = subprocess.run(['git', '-C', root, 'ls-files'], capture_output=True, text=True, timeout=30)
        files = r.stdout.split('\n') if r.returncode == 0 else []
    except (OSError, subprocess.SubprocessError):
        files = []
    return [f for f in files if f.startswith(CODE_DIRS) and f.endswith(CODE_EXT) and not NOT_WRITER.search(f)]


def _targets(line: str, ext: str) -> list:
    """Выражения-цели записи в строке кода."""
    out = []
    if ext == '.sh':
        for m in W_SH.finditer(line):
            out.append(m.group(1) or m.group(2) or '')
        return out
    out += [m.group(1) for m in W_OPEN.finditer(line)]
    out += [m.group(1) for m in W_PATH.finditer(line)]
    for m in W_LAST.finditer(line):
        args = re.split(r',(?![^()]*\))', m.group(1))
        out.append(args[-1] if args else '')
    out += [m.group(1) for m in W_FIRST.finditer(line)]
    return out


def _names(src: str, lit: str, ext: str) -> dict:
    """Имена переменных, которым присвоен путь, оканчивающийся на `lit`. Производные (`TMP = OUT + '.tmp'`) — не тот файл:
    запись во временный и `os.replace(TMP, OUT)` ловится по самому OUT."""
    pat = (r'^\s*(?:export\s+|local\s+|readonly\s+)?([A-Za-z_]\w*)=(.*)$' if ext == '.sh'
           else r'^\s*(?:export\s+)?(?:const\s+|let\s+|var\s+)?([A-Za-z_][\w.]*)\s*(?::[^=]+)?=(?!=)(.*)$')
    assigns = []
    for i, ln in enumerate(src.split('\n'), 1):
        m = re.match(pat, ln)
        if m:
            assigns.append((i, m.group(1), m.group(2).split('#')[0].rstrip().rstrip(';')))
    names = {n: 0 for _, n, rhs in assigns if _ends_with(rhs, lit)}   # имя → с какой строки оно = файл (0 — везде)
    if ext == '.py':   # путь — умолчание ключа: add_argument('--catalogue', default='data/flat3d/furniture.json') → a.catalogue
        for m in re.finditer(r'''add_argument\(\s*['"]--([\w-]+)['"][^\n]*?default\s*=\s*([^,)\n]+)''', src):
            if _ends_with(m.group(2), lit):
                names['.' + m.group(1).replace('-', '_')] = 0
    for _ in range(3):   # тот же путь под другим именем ниже присвоения: path = os.path.abspath(a.catalogue); P = OUT
        new = {n: i for i, n, rhs in assigns if n not in names and _is_ref(rhs, names, lit)}
        if not new:
            break
        names.update(new)
    return names


def _ends_with(expr: str, lit: str) -> bool:
    """Выражение пути оканчивается на файл `lit` (а не `lit.bak`, `lit + '.tmp'`): `os.path.join(HERE, 'sets3.json')`,
    `"$HOME/x/sets3.json"`, `os.environ.get('SETS_OUTPUT', os.path.join(HERE, 'sets3.json'))`."""
    return bool(re.search(re.escape(lit) + r'''['"}]?[\s)\]}]*$''', expr.strip()))


def _is_ref(expr: str, names: set, lit: str) -> bool:
    """Цель записи — сам файл: оканчивается на `lit` или на имя переменной с ним (`OUT`, `os.path.join(HERE, SETS_FILE)`, `"$SETS"`)."""
    if _ends_with(expr, lit):
        return True
    pre = lambda n: r'\w+' if n.startswith('.') else r'(?<![\w.])\$?\{?'   # «.catalogue» — атрибут разбора ключей (a.catalogue)
    return any(re.search(pre(n) + re.escape(n) + r'''\}?['"]?[\s)\]]*$''', expr.strip()) for n in names)


def writers(root: str, lit: str, files=None) -> dict:
    """{файл: [строки записи]} — код, который пишет в путь с именем `lit`."""
    out = {}
    for f in files if files is not None else code_files(root):
        try:
            src = open(os.path.join(root, f), encoding='utf-8', errors='replace').read()
        except OSError:
            continue
        if lit not in src:
            continue
        ext = os.path.splitext(f)[1]
        names = _names(src, lit, ext)
        hits, top = [], ''
        for i, ln in enumerate(src.split('\n'), 1):
            d = re.match(r'(?:async\s+)?(?:def|function|class)\s+(\w+)', ln)   # функция верхнего уровня (столбец 0)
            if d:
                top = d.group(1)
            if SELFTEST.search(top):
                continue   # самопроверка модуля пишет во временную папку
            code = ln.split('#', 1)[0] if ext in ('.py', '.sh') else re.sub(r'//.*$', '', ln)
            live = {n for n, since in names.items() if since <= i}
            for t in _targets(code, ext):
                if _is_ref(t, live, lit):
                    hits.append(i)
                    break
        if hits:
            out[f] = hits
    return out


def allowed_of(e: dict) -> set:
    """Кто вправе писать файл записи: генератор и писатели с причиной."""
    return {x for x in [e.get('generator')] + [w.get('path') for w in e.get('writers') or [] if isinstance(w, dict)] if x}


def check(root: str, m: dict = None, files=None) -> list:
    m = m if m is not None else load(root)
    fails = []
    ex = lambda p: os.path.isfile(os.path.join(root, p))
    ci = open(os.path.join(root, '.github/workflows/ci.yml'), encoding='utf-8').read() if ex('.github/workflows/ci.yml') else ''
    night = open(os.path.join(root, 'tools/scout/refresh_daily.sh'), encoding='utf-8').read() if ex('tools/scout/refresh_daily.sh') else ''
    files = files if files is not None else code_files(root)
    for kind in ('tracked', 'live'):
        for e in m.get(kind) or []:
            p = e.get('path', '?')
            gen, allowed = e.get('generator'), allowed_of(e)
            for w in e.get('writers') or []:
                if not isinstance(w, dict) or not w.get('path') or not str(w.get('why') or '').strip():
                    fails.append(f'{p}: писатель {w} без причины — нужно {{path, why}}')
            for w in sorted(x for x in allowed if x):
                if not ex(w):
                    fails.append(f'{p}: писателя {w} нет в репо — реестр устарел')
            if e.get('publisher') and not ex(e['publisher'].split()[0]):
                fails.append(f'{p}: публикатора {e["publisher"]} нет в репо')
            if e.get('step') and not re.search(r'(?:^|[\s;&|])step ' + re.escape(e['step']) + r'(?!\w)', night, re.M):
                fails.append(f'{p}: ночного шага «{e["step"]}» нет в refresh_daily.sh')
            if not gen:
                fails.append(f'{p}: у записи нет generator')
            if kind == 'tracked':
                if not ex(p):
                    fails.append(f'{p}: файла нет в репо — реестр устарел')
                elif e.get('check') == 'seal':
                    ok = SEAL.verify_text(open(os.path.join(root, p), encoding='utf-8').read())
                    if ok is not True:
                        fails.append(f'{p}: печать {"сломана — файл правили руками" if ok is False else "отсутствует"}; '
                                     f'пересоберите генератором {gen}')
                elif e.get('check') == 'regen':
                    if not e.get('regen') or e['regen'] not in ci:
                        fails.append(f'{p}: команды пересборки «{e.get("regen")}» нет в ci.yml — ручную правку никто не поймает')
                else:
                    fails.append(f'{p}: check — seal или regen')
            lit = e.get('match') or os.path.basename(p)
            for w, lines in sorted(writers(root, lit, files).items()):
                if w not in allowed:
                    fails.append(f'{p}: неизвестный писатель {w}:{lines[0]} — пишет собранный файл в обход генератора; '
                                 f'правьте вход (правило/шаблон) или впишите писателя в {MANIFEST} с причиной')
            if kind == 'tracked' and e.get('check') == 'seal':
                # устаревший писатель печать не ставит: его запуск сломает печать — красный, пока его не уберут (WARN ниже)
                legacy = {w.get('path') for w in e.get('writers') or [] if isinstance(w, dict) and w.get('legacy')}
                for w in sorted(allowed - legacy):
                    src = open(os.path.join(root, w), encoding='utf-8', errors='replace').read() if ex(w) else ''
                    if src and 'conveyor_seal' not in src and 'conveyor-seal' not in src:
                        fails.append(f'{p}: писатель {w} не ставит печать (нет conveyor_seal)')
    return fails


def warnings(m: dict) -> list:
    """Устаревшие писатели (`legacy: true`) — не стоп, но каждый прогон на виду, пока их не уберут."""
    return [f"{e['path']}: устаревший писатель {w['path']} — {w.get('why', '')}" for k in ('tracked', 'live')
            for e in m.get(k) or [] for w in e.get('writers') or [] if isinstance(w, dict) and w.get('legacy')]


def _selftest() -> int:
    import tempfile
    fails = 0

    def ok(name, cond, info=''):
        nonlocal fails
        print(('OK   ' if cond else 'FAIL ') + name + (f' — {info}' if info and not cond else ''))
        fails += 0 if cond else 1

    with tempfile.TemporaryDirectory() as d:
        put = lambda p, t: (os.makedirs(os.path.dirname(os.path.join(d, p)), exist_ok=True), open(os.path.join(d, p), 'w').write(t))
        put('.github/workflows/ci.yml', 'run: python tools/x/gen_b.py --check\n')
        put('tools/scout/refresh_daily.sh', 'step night_a python3 gen_a.py\n')
        put('tools/x/gen_a.py', "import os\nOUT = os.path.join(HERE, 'sets9.json')\nTMP = OUT + '.tmp'\nopen(TMP, 'w').write('{}')\nos.replace(TMP, OUT)\n")
        put('tools/x/reader.py', "import json\nd = json.load(open('sets9.json'))\nopen('report.json', 'w').write('x')\nos.replace('a.tmp', 'report.json')\n")
        put('tools/x/hack.sh', 'cp /tmp/my.json "$HOME/x/sets9.json"\n')
        put('tools/x/hack2.mjs', 'const P = "x/sets9.json";\nwriteFileSync(P, "{}");\n')
        put('tools/x/tests/test_a.py', "open('sets9.json', 'w')\n")
        put('tools/x/gen_b.py', 'print(1)\n')
        put('tools/x/gen_c.py', "from conveyor_seal import dump_sealed\ndump_sealed(p, 'data/c.json')\n")
        put('tools/x/hack3.py', "json.dump(x, open('data/c.json', 'w'))\n")
        put('data/b.json', '{}\n')
        put('data/c.json', SEAL.seal_text('{\n "_about": "x",\n "_seal": "",\n "a": 1\n}\n'))
        files = ['tools/x/gen_a.py', 'tools/x/reader.py', 'tools/x/hack.sh', 'tools/x/hack2.mjs', 'tools/x/gen_b.py',
                 'tools/x/gen_c.py', 'tools/x/hack3.py']
        w = writers(d, 'sets9.json', files)
        ok('писатель по переменной (OUT → TMP → os.replace) найден', 'tools/x/gen_a.py' in w, w)
        ok('читатель, пишущий другой файл, — не писатель', 'tools/x/reader.py' not in w, w)
        ok('cp в собранный путь (shell) и writeFileSync по переменной (node) — писатели',
           'tools/x/hack.sh' in w and 'tools/x/hack2.mjs' in w, w)
        m = {'live': [{'path': 'tools/scout/sets9.json', 'generator': 'tools/x/gen_a.py', 'step': 'night_a'}],
             'tracked': [{'path': 'data/b.json', 'generator': 'tools/x/gen_b.py', 'check': 'regen', 'regen': 'python tools/x/gen_b.py --check'},
                         {'path': 'data/c.json', 'generator': 'tools/x/gen_c.py', 'check': 'seal',
                          'writers': [{'path': 'tools/x/hack3.py', 'why': 'проба'}, 'tools/x/gen_b.py']}]}
        f = check(d, m, files)
        ok('неизвестные писатели — FAIL с файлом и строкой', any('hack.sh:1' in x for x in f) and any('hack2.mjs:2' in x for x in f), f)
        ok('генератор из реестра — не FAIL', not any('gen_a.py' in x for x in f), f)
        ok('писатель файла с печатью без conveyor_seal — FAIL', any('hack3.py не ставит печать' in x for x in f), f)
        ok('печать цела — без FAIL по печати', not any('печать' in x and 'data/c.json' in x and 'сломана' in x for x in f), f)
        ok('писатель без причины — FAIL', any('без причины' in x and 'gen_b.py' in x for x in f), f)
        ok('названный писатель файла с печатью без conveyor_seal — FAIL', any('hack3.py не ставит печать' in x for x in f), f)
        ok('устаревший писатель — WARN, не FAIL', warnings({'live': [{'path': 'a', 'writers': [{'path': 'b', 'why': 'w', 'legacy': True}]}]})
           == ['a: устаревший писатель b — w'])
        put('tools/x/gen_d.py', "def _selftest():\n    td = '/tmp/x'\n    cp = os.path.join(td, 'sets9.json')\n    open(cp, 'w').write('[]')\n")
        ok('запись внутри _selftest — не писатель', 'tools/x/gen_d.py' not in writers(d, 'sets9.json', files + ['tools/x/gen_d.py']))
        put('tools/x/bak.py', "SETS = os.path.join(HERE, 'sets9.json')\nshutil.copy(SETS, SETS + '.bak')\n")
        ok('копия В .bak — не запись в собранный файл', 'tools/x/bak.py' not in writers(d, 'sets9.json', ['tools/x/bak.py']))
        put('tools/x/argp.py', "ap.add_argument('--catalogue', default='data/sets9.json')\npath = os.path.abspath(a.catalogue)\n"
            "TMP = path + '.tmp'\nwith open(path, 'w') as fh:\n    fh.write('{}')\n")
        ok('путь — умолчание ключа, через обёртку (a.catalogue → path) — писатель',
           writers(d, 'sets9.json', ['tools/x/argp.py']).get('tools/x/argp.py') == [4], writers(d, 'sets9.json', ['tools/x/argp.py']))
        put('tools/x/argp2.py', "ap.add_argument('--catalogue', default='data/sets9.json')\npath = os.path.abspath(a.catalogue)\n"
            "TMP = path + '.tmp'\nopen(TMP, 'w').write('{}')\n")
        ok('производный путь от умолчания ключа (path + .tmp) — не писатель', 'tools/x/argp2.py' not in writers(d, 'sets9.json', ['tools/x/argp2.py']))
        put('tools/x/argp3.py', "def fetch(path):\n    open(path, 'wb').write(b'')\n"
            "ap.add_argument('--catalogue', default='data/sets9.json')\npath = os.path.abspath(a.catalogue)\nopen(path, 'w')\n")
        ok('то же имя ВЫШЕ присвоения (кэш в другой функции) — не та запись',
           writers(d, 'sets9.json', ['tools/x/argp3.py']).get('tools/x/argp3.py') == [5], writers(d, 'sets9.json', ['tools/x/argp3.py']))
        put('data/c.json', open(os.path.join(d, 'data/c.json')).read().replace('"a": 1', '"a": 2'))
        ok('ручная правка файла с печатью — FAIL', any('data/c.json: печать сломана' in x for x in check(d, m, files)))
        m['tracked'][0]['regen'] = 'python tools/x/gen_b.py --other'
        ok('команды пересборки нет в ci.yml — FAIL', any('нет в ci.yml' in x for x in check(d, m, files)))
        m['live'][0]['step'] = 'night_zz'
        ok('ночного шага нет — FAIL', any('night_zz' in x for x in check(d, m, files)))
    print('FAILS', fails)
    return 1 if fails else 0


def main(argv: list) -> int:
    if '--selftest' in argv:
        return _selftest()
    root = argv[argv.index('--root') + 1] if '--root' in argv else ROOT_DEFAULT
    m = load(root)
    if '--writers' in argv:
        files = code_files(root)
        for kind in ('tracked', 'live'):
            for e in m.get(kind) or []:
                lit = e.get('match') or os.path.basename(e['path'])
                print(f"{e['path']} ({lit}):")
                for w, lines in sorted(writers(root, lit, files).items()):
                    print(f"  {'   ' if w in allowed_of(e) else 'NEW'} {w}:{','.join(map(str, lines[:5]))}")
        return 0
    fails = check(root, m)
    for w in warnings(m):
        print('WARN ' + w)
    for f in fails:
        print('FAIL ' + f)
    n = sum(len(m.get(k) or []) for k in ('tracked', 'live'))
    print(f'реестр конвейера: записей {n}, нарушений {len(fails)}')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
