"""ПРОВЕРКА ПЕРЕД ПУШЕМ — быстрые самопроверки CI, которые касаются изменённых файлов (T-20261107-41).

07.11 два коммита (потолок досъёмки 50 → 200 ₽ в rules/demo-realistic.json и шаг photo_speed в refresh_daily.sh) сломали
`node tools/ops/demo-realistic.mjs --selftest` — его никто не запускал: правили не сам тест, а файлы, которые он читает.
Гейт был красным ~3 ч и ~37 пушей. Этот скрипт запускает такие проверки до пуша.

    bash tools/ops/prepush-check.sh                    # файлы — git diff origin/main...HEAD
    bash tools/ops/prepush-check.sh --files a b c      # подставной список файлов
    bash tools/ops/prepush-check.sh --dry              # только показать, что запустил бы
    bash tools/ops/prepush-check.sh --budget 120       # потолок времени, с (по умолчанию 120)
    git pre-push хук: `tools/ops/prepush-check.sh` читает stdin протокола (local_ref local_sha remote_ref remote_sha)
    python3 tools/ops/prepush_check.py --selftest

КАРТА «ПУТЬ → КОМАНДА» — ИЗ ci.yml, не руками: каждая `run:` всех job разбирается на команды (`a && b`; цикл
`for m in …; do python tools/scout/$m.py …` — по команде на элемент). Команда касается изменённого файла F, если
  (а) F — файл, который она запускает (путь в командной строке), или
  (б) исходник этого файла упоминает F: путь от корня, путь от своей папки (`../scout/x.sh`), имя файла (если оно в репо
      одно), а для .py — `import F` / `from F import`.
Не локально (медленно или нужна установка): pnpm, docker, playwright, pip, `-m pytest` — их проверяет CI.
ВСЕГДА и первыми — команды `ALWAYS` (реестр конвейера `tools/ops/conveyor_check.py` и линт особых случаев `conveyor_ids.py`,
T-20261112-121): при любой правке;
не успела в потолок — стоп, как упавшая.
Окружение — как у job: его `env:`, CI=true, GITHUB_ACTIONS=true, RUNNER_TEMP; `python` — venv scout, если есть.
Код выхода: 1 — какая-то проверка упала (пуш остановить); 0 — все прошли или не успели в потолок (это не стоп, их проверит CI)."""
import os
import re
import shlex
import signal
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT_DEFAULT = os.path.abspath(os.path.join(HERE, '..', '..'))
SLOW = re.compile(r'^(pnpm|npx|docker|pip|pip3|apt|apt-get|sudo)\b|playwright|-m\s+pytest')
RUNNERS = ('python', 'python3', 'node', 'bash', 'sh', 'diff')
ZERO = '0' * 40
# проверки при ЛЮБОЙ правке, первыми; не успела — стоп, а не «проверит CI» (реестр конвейера, T-20261112-121:
# ручную правку собранного файла или новый писатель в обход генератора ловим до пуша, какой бы файл ни поменялся)
# + линт особых случаев (ID товара/тура в коде, шаг 6): пока предупреждение — печатает WARN, пуш не держит; кривой реестр — стоп
ALWAYS = ('python tools/ops/conveyor_check.py', 'python tools/ops/conveyor_ids.py')


def _strip_installs(cmd: str) -> str:
    return re.sub(r'(^|&&)\s*pip3? install [^&\n]*(?=&&|$)', r'\1', cmd, flags=re.M).strip().lstrip('&').strip()


def _paths(cmd: str, root: str) -> list:
    out = []
    try:
        toks = shlex.split(cmd, comments=True)
    except ValueError:
        toks = cmd.split()
    for t in toks:
        t = t.strip('"\'')
        if '/' in t and not t.startswith('-') and os.path.isfile(os.path.join(root, t)) and t not in out:
            out.append(t)
    return out


def units_of(run: str, root: str) -> list:
    """Команды одной `run:`: цикл — по элементу, `a && b` — по части; многострочный скрипт без цикла — целиком."""
    m = re.search(r'for (\w+) in ([^;\n]+);\s*do(.*?)done', run, re.S)
    if m:
        var, items, body = m.group(1), m.group(2).split(), m.group(3)
        t = re.search(r'\b(python3?|node|bash)\s+(\S*\$' + var + r'\b\S*)([^;|&\n]*)', body)
        if t:
            return [(t.group(1) + ' ' + t.group(2) + t.group(3)).replace('$' + var, it).strip() for it in items]
    run = _strip_installs(run)
    if not run:
        return []
    if '\n' in run.strip():
        return [run.strip()]
    return [p.strip() for p in run.split('&&') if p.strip()]


def ci_units(ci_path: str, root: str) -> list:
    import yaml
    with open(ci_path, encoding='utf-8') as f:
        d = yaml.safe_load(f)
    out, seen = [], set()
    for job, J in (d.get('jobs') or {}).items():
        env = {k: str(v) for k, v in ((J or {}).get('env') or {}).items()}
        for st in (J or {}).get('steps') or []:
            run = st.get('run')
            if not run:
                continue
            for cmd in units_of(run, root):
                if cmd in seen:
                    continue
                seen.add(cmd)
                first = cmd.split()[0] if cmd.split() else ''
                slow = bool(SLOW.search(cmd)) or first not in RUNNERS
                out.append({'job': job, 'cmd': cmd, 'env': env, 'paths': _paths(cmd, root), 'slow': slow})
    return out


def _repo_files(root: str) -> list:
    try:
        r = subprocess.run(['git', '-C', root, 'ls-files'], capture_output=True, text=True, timeout=30)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.split()
    except (OSError, subprocess.SubprocessError):
        pass
    out = []
    for dp, dn, fn in os.walk(root):
        dn[:] = [x for x in dn if x not in ('.git', 'node_modules', '.next')]
        out += [os.path.relpath(os.path.join(dp, f), root) for f in fn]
    return out


def mentions(src_path: str, src: str, f: str, unique_base: bool) -> bool:
    """Исходник `src_path` (путь от корня) ссылается на файл `f` (путь от корня)?"""
    if f in src:
        return True
    rel = os.path.relpath(f, os.path.dirname(src_path) or '.')
    if rel in src:
        return True
    base, parent = os.path.basename(f), os.path.basename(os.path.dirname(f))
    # «папка/файл» строкой или по частям (`os.path.join(HERE, '..', 'flat215-demo', 'index.html')` — test_img_fallback, 07.11)
    if parent and (f'{parent}/{base}' in src
                   or re.search(r'[\'"]' + re.escape(parent) + r'[\'"]\s*,\s*[\'"]' + re.escape(base) + r'[\'"]', src)):
        return True
    if unique_base and re.search(r'(?<![\w.-])' + re.escape(base) + r'(?![\w-])', src):
        return True
    if f.endswith('.py'):
        stem = re.escape(base[:-3])
        if re.search(r'^\s*(from\s+(\S+\.)?' + stem + r'\s+import\b|import\s+([\w., ]+,\s*)?' + stem + r'\b)', src, re.M):
            return True
    return False


def select(units: list, changed: list, root: str) -> list:
    """Команды, которые касаются изменённых файлов: сперва запускающие их прямо, потом читающие."""
    files = _repo_files(root)
    cnt = {}
    for x in files:
        b = os.path.basename(x)
        cnt[b] = cnt.get(b, 0) + 1
    cache = {}

    def src(p):
        if p not in cache:
            try:
                with open(os.path.join(root, p), encoding='utf-8', errors='replace') as fh:
                    cache[p] = fh.read(2_000_000)
            except OSError:
                cache[p] = ''
        return cache[p]

    always, direct, indirect = [], [], []
    for u in units:
        if u['slow']:
            continue
        if u['cmd'] in ALWAYS:
            always.append(dict(u, why=['всегда'], always=True))
            continue
        why = [f for f in changed if f in u['paths']]
        if why:
            direct.append(dict(u, why=why))
            continue
        why = [f for f in changed for p in u['paths']
               if p != f and mentions(p, src(p), f, cnt.get(os.path.basename(f), 0) == 1)]
        if why:
            indirect.append(dict(u, why=sorted(set(why))))
    return always + direct + indirect


def _python() -> str:
    v = os.path.expanduser('~/venvs/scout/bin/python')
    return v if os.path.exists(v) else sys.executable


def _localize(cmd: str, py: str) -> str:
    return re.sub(r'(^|&&\s*|;\s*|\n\s*)python3?(?=\s)', lambda m: m.group(1) + shlex.quote(py), cmd)


def run_units(sel: list, root: str, budget: float, runner_temp: str, py: str | None = None, out=sys.stdout) -> int:
    py = py or _python()
    t0, fails, late = time.time(), [], []
    for i, u in enumerate(sel):
        left = budget - (time.time() - t0)
        if left <= 1:
            late = sel[i:]
            break
        env = dict(os.environ, **u['env'], CI='true', GITHUB_ACTIONS='true', RUNNER_TEMP=runner_temp)
        if not os.environ.get('REMLAB_TMP') and os.path.isdir(os.path.expanduser('~/remlab-scratch')):
            env['REMLAB_TMP'] = os.path.expanduser('~/remlab-scratch/tmp')   # CI=true иначе увело бы временное в /tmp (квота)
        t = time.time()
        p = subprocess.Popen(['bash', '-c', _localize(u['cmd'], py)], cwd=root, env=env, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, text=True, start_new_session=True)
        try:
            text, _ = p.communicate(timeout=left)
        except subprocess.TimeoutExpired:
            os.killpg(p.pid, signal.SIGKILL)
            p.communicate()
            late = sel[i:]
            break
        ok = p.returncode == 0
        print(f"{'ok  ' if ok else 'FAIL'} {time.time() - t:5.1f} с  {u['cmd'].splitlines()[0][:110]}  ← {', '.join(u['why'])[:80]}", file=out, flush=True)
        if not ok:
            fails.append(u)
            print('     ' + '\n     '.join((text or '').strip().splitlines()[-15:]), file=out)
    for u in late:
        if u.get('always'):
            fails.append(u)
            print(f"FAIL не успел в {budget:.0f} с — проверка обязательная: {u['cmd'].splitlines()[0][:110]}", file=out)
            continue
        print(f"не успел в {budget:.0f} с (проверит CI): {u['cmd'].splitlines()[0][:110]}", file=out)
    late = [u for u in late if not u.get('always')]
    print(f'prepush: проверок {len(sel)}, упало {len(fails)}, не успел {len(late)}' +
          (' — ПУШ ОСТАНОВЛЕН, почини и повтори (обойти: git push --no-verify)' if fails else ''), file=out)
    return 1 if fails else 0


def changed_files(root: str, argv: list, stdin) -> list:
    if '--files' in argv:
        i = argv.index('--files') + 1
        out = []
        while i < len(argv) and not argv[i].startswith('--'):
            out.append(argv[i])
            i += 1
        return out
    git = lambda *a: subprocess.run(['git', '-C', root, *a], capture_output=True, text=True).stdout.split()
    out = []
    lines = [] if stdin is None or stdin.isatty() else stdin.read().splitlines()
    for ln in lines:   # протокол pre-push: <local ref> <local sha> <remote ref> <remote sha>
        p = ln.split()
        if len(p) != 4 or p[1] == ZERO:
            continue
        base = p[3] if p[3] != ZERO else (git('merge-base', p[1], 'origin/main') or [''])[0]
        out += git('diff', '--name-only', f'{base}..{p[1]}') if base else git('show', '--name-only', '--format=', p[1])
    if not lines:
        out = git('diff', '--name-only', 'origin/main...HEAD')
    return sorted(set(out))


def here_root() -> str:
    """Корень копии, из которой пуш (хук зовут в её корне; worktree — своя копия), иначе — копия скрипта."""
    try:
        r = subprocess.run(['git', 'rev-parse', '--show-toplevel'], capture_output=True, text=True, timeout=10)
        top = r.stdout.strip()
        if r.returncode == 0 and os.path.isfile(os.path.join(top, '.github', 'workflows', 'ci.yml')):
            return top
    except (OSError, subprocess.SubprocessError):
        pass
    return ROOT_DEFAULT


def main(argv: list) -> int:
    if '--selftest' in argv:
        return _selftest()
    root = argv[argv.index('--root') + 1] if '--root' in argv else here_root()
    budget = float(argv[argv.index('--budget') + 1]) if '--budget' in argv else 120.0
    changed = changed_files(root, argv, sys.stdin)
    if not changed:
        print('prepush: изменённых файлов нет — проверять нечего')
        return 0
    sel = select(ci_units(os.path.join(root, '.github', 'workflows', 'ci.yml'), root), changed, root)
    print(f'prepush: файлов {len(changed)}, проверок CI по ним {len(sel)}')
    if '--dry' in argv:
        for u in sel:
            print(f"  {u['job']}: {u['cmd'].splitlines()[0][:120]}  ← {', '.join(u['why'])[:80]}")
        return 0
    sys.path.insert(0, os.path.join(HERE, '..', 'scout'))
    import remlab_tmp
    with remlab_tmp.tmpdir('prepush-') as rt:
        return run_units(sel, root, budget, rt)


def _selftest() -> int:
    import io
    import tempfile
    sys.path.insert(0, os.path.join(HERE, '..', 'scout'))
    import remlab_tmp
    remlab_tmp.use('prepush-check')
    bad = []

    def check(cond, msg, got=None):
        print(('OK   ' if cond else 'FAIL ') + msg + ('' if cond else f': {got!r}'))
        if not cond:
            bad.append(msg)

    # подставной репозиторий: ci.yml и скрипты, которые он запускает
    root = tempfile.mkdtemp(prefix='prepush-repo-')
    files = {
        '.github/workflows/ci.yml': """name: CI gate
on: push
jobs:
  gate:
    steps:
      - uses: actions/checkout@v4
      - run: pnpm install --frozen-lockfile
      - run: node tools/ops/reads_night.mjs --selftest   # комментарий
      - run: python3 tools/ops/fails.py --selftest
      - run: pnpm test
  scout:
    env:
      MY_PRIORS: tools/scout/fx.json
    steps:
      - run: |
          for m in m1 m2; do
            echo "== $m"; python tools/scout/$m.py --selftest || exit 1
          done
      - run: pip install pillow && python tools/scout/tests/test_t.py
      - run: python -m pytest tools/scout/tests -q
      - run: python tools/scout/slow.py
""",
        'tools/ops/reads_night.mjs': 'const sh = readFileSync(new URL("../scout/night.sh", import.meta.url));\nprocess.exit(0);\n',
        'tools/ops/fails.py': 'import sys\nprint("сломано")\nsys.exit(3)\n',
        'tools/scout/night.sh': 'echo night\n',
        'tools/scout/m1.py': 'import os, sys\nsys.exit(0 if os.environ.get("MY_PRIORS") and os.environ.get("CI") == "true" else 4)\n',
        'tools/scout/m2.py': 'print(2)\n',
        'tools/scout/tests/test_t.py': 'import os, sys\nsys.path.insert(0, "tools/scout")\nimport m1  # noqa\nP = os.path.join("..", "web", "page.html")\n',
        'tools/scout/web/page.html': '<p>\n',
        'tools/scout/slow.py': 'import time\ntime.sleep(30)\n',
        'tools/scout/fx.json': '{}\n',
        'tools/scout/rules/only.json': '{}\n',
    }
    for p, body in files.items():
        os.makedirs(os.path.dirname(os.path.join(root, p)), exist_ok=True)
        with open(os.path.join(root, p), 'w', encoding='utf-8') as f:
            f.write(body)
    with open(os.path.join(root, 'tools/ops/reads_night.mjs'), 'a', encoding='utf-8') as f:
        f.write('// правила: rules/only.json\n')
    units = ci_units(os.path.join(root, '.github/workflows/ci.yml'), root)
    cmds = [u['cmd'] for u in units]
    check('python tools/scout/m1.py --selftest' in cmds and 'python tools/scout/m2.py --selftest' in cmds,
          'цикл `for m in …` — по команде на элемент', cmds)
    check('python tools/scout/tests/test_t.py' in cmds and not any(c.startswith('pip') for c in cmds), '`pip install … &&` срезан', cmds)
    check(all(u['slow'] for u in units if u['cmd'].startswith('pnpm') or 'pytest' in u['cmd']), 'pnpm и -m pytest — не локально', units)
    pick = lambda ch: [u['cmd'] for u in select(units, ch, root)]
    s = pick(['tools/scout/night.sh'])
    check(s == ['node tools/ops/reads_night.mjs --selftest'], 'файл, который тест читает (`../scout/night.sh`) — его тест', s)
    s = pick(['tools/scout/rules/only.json'])
    check(s == ['node tools/ops/reads_night.mjs --selftest'], 'имя файла, единственное в репо, упомянуто в тесте — его тест', s)
    s = pick(['tools/scout/web/page.html'])
    check(s == ['python tools/scout/tests/test_t.py'], 'путь по частям (`os.path.join(..., "web", "page.html")`) — его тест', s)
    s = pick(['tools/scout/m1.py'])
    check(s == ['python tools/scout/m1.py --selftest', 'python tools/scout/tests/test_t.py'],
          'модуль: сперва свой селфтест, потом тест, который его импортирует; соседний m2 — нет', s)
    s = pick(['tools/ops/fails.py', 'README.md', 'app/page.tsx'])
    check(s == ['python3 tools/ops/fails.py --selftest'], 'сам скрипт проверки — его команда; чужие файлы — ничего', s)
    check(pick(['package.json']) == [], 'pnpm-шаги не выбираются', pick(['package.json']))
    # запуск: env job, код выхода, потолок времени
    rt = tempfile.mkdtemp(prefix='prepush-rt-')
    buf = io.StringIO()
    rc = run_units(select(units, ['tools/scout/m1.py'], root), root, 60, rt, py=sys.executable, out=buf)
    check(rc == 0 and 'упало 0' in buf.getvalue(), 'env job (MY_PRIORS) и CI=true доходят до проверки — код 0', buf.getvalue())
    buf = io.StringIO()
    rc = run_units(select(units, ['tools/ops/fails.py', 'tools/scout/night.sh'], root), root, 60, rt, py=sys.executable, out=buf)
    check(rc == 1 and 'FAIL' in buf.getvalue() and 'сломано' in buf.getvalue() and 'ПУШ ОСТАНОВЛЕН' in buf.getvalue(),
          'упавшая проверка — код 1, её вывод и «ПУШ ОСТАНОВЛЕН»', buf.getvalue())
    buf = io.StringIO()
    t = time.time()
    rc = run_units(select(units, ['tools/scout/slow.py'], root), root, 3, rt, py=sys.executable, out=buf)
    check(rc == 0 and 'не успел в 3 с' in buf.getvalue() and time.time() - t < 15,
          'потолок времени: долгую проверку обрываем, «не успел» — не стоп (её проверит CI)', (rc, buf.getvalue()))
    # протокол pre-push и --files
    check(changed_files(root, ['--files', 'a.py', 'b/c.sh', '--dry'], None) == ['a.py', 'b/c.sh'], '--files — подставной список')
    # протокол pre-push (stdin) на этом репо: коммит HEAD против его родителя — файлы того коммита
    head = subprocess.run(['git', '-C', ROOT_DEFAULT, 'rev-parse', 'HEAD', 'HEAD~1'], capture_output=True, text=True).stdout.split()
    if len(head) == 2:
        want = sorted(subprocess.run(['git', '-C', ROOT_DEFAULT, 'diff', '--name-only', head[1], head[0]],
                                     capture_output=True, text=True).stdout.split())
        got = changed_files(ROOT_DEFAULT, [], io.StringIO(f'refs/heads/x {head[0]} refs/heads/main {head[1]}\n'))
        check(got == want, 'pre-push stdin: файлы от удалённого sha до локального', (got, want))
        got = changed_files(ROOT_DEFAULT, [], io.StringIO(f'refs/heads/x {ZERO} refs/heads/main {head[1]}\n'))
        check(got == [], 'pre-push stdin: удаление ветки — проверять нечего', got)
    # настоящий ci.yml: регресс 07.11 ловится
    real = ci_units(os.path.join(ROOT_DEFAULT, '.github', 'workflows', 'ci.yml'), ROOT_DEFAULT)
    for f in ('tools/scout/refresh_daily.sh', 'tools/scout/rules/demo-realistic.json'):
        s = [u['cmd'] for u in select(real, [f], ROOT_DEFAULT)]
        check('node tools/ops/demo-realistic.mjs --selftest' in s, f'настоящий ci.yml: правка {f} запускает demo-realistic --selftest (07.11)', s)
    s = [u['cmd'] for u in select(real, ['tools/scout/bank_run.py'], ROOT_DEFAULT)]
    check('python tools/scout/bank_run.py --selftest' in s, 'настоящий ci.yml: модуль из цикла scout-selftest — свой селфтест', s[:5])
    s = [u['cmd'] for u in select(real, ['tools/scout/flat215-demo/index.html'], ROOT_DEFAULT)]
    check('python tools/scout/tests/test_img_fallback.py' in s, 'настоящий ci.yml: правка страницы демо запускает test_img_fallback (07.11, 6f2395bc)', s)
    s = [u['cmd'] for u in select(real, ['README.md'], ROOT_DEFAULT)]
    check(s[:len(ALWAYS)] == list(ALWAYS), 'настоящий ci.yml: реестр конвейера и линт особых случаев — при любой правке и первыми (T-20261112-121)', s[:3])
    # обязательная проверка, не успевшая в потолок, — стоп (а обычная — «проверит CI», см. выше)
    buf = io.StringIO()
    slow = dict(select(units, ['tools/scout/slow.py'], root)[0], always=True)
    rc = run_units([slow], root, 3, rt, py=sys.executable, out=buf)
    check(rc == 1 and 'обязательная' in buf.getvalue(), 'обязательная проверка не успела — код 1', (rc, buf.getvalue()))
    print(f'prepush_check selftest: ошибок {len(bad)}')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
