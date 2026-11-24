#!/usr/bin/env python3
"""АВТОПРОВЕРКА «СБОРКА ПРОБНОГО ОБРАЗА ЗАПУСКАЕТСЯ ОТ ПРАВКИ ЛЮБОГО ФАЙЛА ОБРАЗА» (T-20261124-56).

Зачем. 24.11 правка `salad/trellis/junction.py` и `rules/camera-check.json` ушла в `trial/pose-t2418`, а образ не пересобрался:
у `build-pose-trial.yml` в `on.push.paths` была только папка `salad/pose/**`, а код цепочки едет в образ по списку из других папок.
Проба на Salad тихо пошла на СТАРОМ коде. Общее правило (одно, без ID товаров):
  `on.push.paths` каждого `.github/workflows/build-*-trial.yml` покрывает КАЖДЫЙ файл, который попадает в образ:
    • сам workflow;
    • Dockerfile, по которому идёт сборка (`docker build -f "$CTX/Dockerfile.x"` / `cp "$CTX/Dockerfile.x"`);
    • скрипт сборки контекста (`python3 "$CTX/stage_*_code.py"`), его соседи `stage_*.py`, которые он импортирует, и список `*_files.txt`;
    • каждый файл из этого списка (пути от корня репозитория: код, `rules/*.json`, данные);
    • каждый файл, который Dockerfile берёт из контекста командой COPY/ADD (папка — рекурсивно).
Workflow без `push` (только `workflow_dispatch`) не проверяется: он и так запускается руками. `push` без `paths` — запуск от любой правки, покрыто.

    python3 tools/ops/trial_build_paths_check.py              # проверить дерево; находка → код 1 с именем workflow и файла
    python3 tools/ops/trial_build_paths_check.py --verbose    # + по каждому workflow: сколько файлов образа и какие «лишние» шаблоны paths
    python3 tools/ops/trial_build_paths_check.py --selftest   # на поддельных workflow во временной папке (ничего не пишет в репозиторий)
Код: 0 — всё покрыто; 1 — есть непокрытые файлы или файл из списка образа не существует; 2 — не удалось разобрать workflow."""
from __future__ import annotations

import argparse
import os
import re
import sys

try:
    import yaml
except ImportError:                                                    # CI: `pip install pyyaml` в той же строке
    print('нужен pyyaml: pip install pyyaml')
    sys.exit(2)

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
WF_DIR = '.github/workflows'
WF_GLOB = re.compile(r'^build-.+-trial\.yml$')
SKIP_DIRS = {'__pycache__', '.git', 'node_modules'}


# ---------- шаблоны GitHub Actions paths ----------

def glob_to_re(pat: str) -> re.Pattern:
    """Шаблон paths GitHub: `*` — внутри одного сегмента (без `/`), `**` — любые символы включая `/`, `**/` — ноль и более папок, `?` — один символ не `/`."""
    out, i = '', 0
    while i < len(pat):
        c = pat[i]
        if pat.startswith('**/', i):
            out += '(?:.*/)?'
            i += 3
        elif pat.startswith('**', i):
            out += '.*'
            i += 2
        elif c == '*':
            out += '[^/]*'
            i += 1
        elif c == '?':
            out += '[^/]'
            i += 1
        else:
            out += re.escape(c)
            i += 1
    return re.compile('^' + out + '$')


def covered(patterns: list[str], path: str) -> bool:
    """Правила GitHub: шаблоны идут по порядку, `!шаблон` вычёркивает; последнее сработавшее решает. Нет совпадений — не покрыт."""
    hit = False
    for p in patterns:
        neg = p.startswith('!')
        if glob_to_re(p[1:] if neg else p).match(path):
            hit = not neg
    return hit


# ---------- разбор workflow ----------

def load_wf(path: str) -> dict:
    with open(path, encoding='utf-8') as f:
        return yaml.safe_load(f) or {}


def push_paths(wf: dict):
    """None — workflow не запускается от push (проверять нечего); [] — push без paths (любая правка); иначе список шаблонов."""
    on = wf.get('on', wf.get(True))                                    # YAML 1.1: ключ `on` превращается в True
    if isinstance(on, str):
        on = {on: None}
    elif isinstance(on, list):
        on = {k: None for k in on}
    on = on or {}
    if 'push' not in on:
        return None
    push = on['push'] or {}
    return [str(p) for p in (push.get('paths') or [])]


def run_text(wf: dict) -> str:
    return '\n'.join(str(s.get('run', '')) for j in (wf.get('jobs') or {}).values() for s in (j.get('steps') or []))


def read_list(path: str) -> list[str]:
    return [ln.strip() for ln in open(path, encoding='utf-8') if ln.strip() and not ln.lstrip().startswith('#')]


def walk(root: str, rel: str) -> list[str]:
    ab = os.path.join(root, rel)
    if os.path.isfile(ab):
        return [rel]
    out = []
    for d, ds, fs in os.walk(ab):
        ds[:] = sorted(x for x in ds if x not in SKIP_DIRS)
        out += [os.path.relpath(os.path.join(d, f), root).replace(os.sep, '/') for f in sorted(fs) if not f.endswith('.pyc')]
    return out


def copy_sources(dockerfile_text: str) -> list[str]:
    """Источники COPY/ADD из контекста (не `--from=`, не URL); продолжения строк через `\\` склеиваются."""
    src = []
    for ln in re.sub(r'\\\n', ' ', dockerfile_text).splitlines():
        m = re.match(r'^\s*(?:COPY|ADD)\s+(.*)$', ln, re.I)
        if not m:
            continue
        toks = m.group(1).split()
        flags = [t for t in toks if t.startswith('--')]
        toks = [t for t in toks if not t.startswith('--')]
        if any(f.startswith('--from') for f in flags) or len(toks) < 2:
            continue
        src += [t for t in toks[:-1] if not re.match(r'^[a-z]+://', t)]
    return src


def image_files(root: str, wf_rel: str, wf: dict) -> tuple[list[tuple[str, str]], list[str]]:
    """→ ([(файл, почему он в образе)], [ошибки разбора/пропавшие файлы]). Пути — от корня репозитория."""
    files: list[tuple[str, str]] = [(wf_rel, 'сам workflow')]
    errs: list[str] = []
    ctx = str((wf.get('env') or {}).get('CTX') or '').strip('/')
    txt = run_text(wf)
    if not ctx:
        errs.append('нет env.CTX — не вижу папку контекста сборки')
        return files, errs

    def c(p: str) -> str:
        return f'{ctx}/{p}'.replace('//', '/')

    dockerfiles = sorted(set(re.findall(r'(?:-f|\bcp)\s+"?\$\{?CTX\}?/(Dockerfile[\w.\-]*)', txt)))
    if not dockerfiles:
        errs.append('не нашла Dockerfile в шагах сборки (`-f "$CTX/Dockerfile.x"` или `cp "$CTX/Dockerfile.x"`)')
    stagers = sorted(set(re.findall(r'python3?\s+"?\$\{?CTX\}?/(stage_\w+\.py)', txt)))
    staged_ctx = bool(stagers)
    for s in stagers:                                                 # скрипт сборки контекста, соседи stage_*.py, список
        sp = os.path.join(root, c(s))
        files.append((c(s), 'скрипт сборки контекста образа'))
        if not os.path.isfile(sp):
            errs.append(f'нет скрипта сборки контекста {c(s)}')
            continue
        src = open(sp, encoding='utf-8').read()
        dirs = [os.path.dirname(c(s))]                                # где искать импортируемый stage_*.py: рядом и в папках, добавленных в sys.path через os.path.join(HERE, '..', 'x')
        for m in re.finditer(r"sys\.path\.insert\(\s*0\s*,\s*os\.path\.join\(\s*HERE((?:\s*,\s*'[^']*')+)\s*\)", src):
            dirs.append(os.path.normpath(os.path.join(os.path.dirname(c(s)), *re.findall(r"'([^']*)'", m.group(1)))).replace(os.sep, '/'))
        for imp in sorted(set(re.findall(r'^\s*import\s+(stage_\w+)\b', src, re.M))):
            home = next((d for d in dirs if os.path.isfile(os.path.join(root, d, imp + '.py'))), None)
            if home is None:
                errs.append(f'{c(s)}: import {imp} — не нашла {imp}.py ни рядом, ни в папках sys.path скрипта')
                continue
            files.append((f'{home}/{imp}.py', f'импортируется скриптом {s}'))
        for lst in sorted(set(re.findall(r"['\"](\w+_files\.txt)['\"]", src))):
            files.append((c(lst), f'список файлов образа ({s})'))
            lp = os.path.join(root, c(lst))
            if not os.path.isfile(lp):
                errs.append(f'нет списка {c(lst)}')
                continue
            for f in read_list(lp):
                if os.path.isfile(os.path.join(root, f)):
                    files.append((f, f'из списка {lst}'))
                else:
                    errs.append(f'файл из списка {c(lst)} не существует: {f}')
    for d in dockerfiles:
        dp = os.path.join(root, c(d))
        files.append((c(d), 'Dockerfile образа'))
        if not os.path.isfile(dp):
            errs.append(f'нет Dockerfile {c(d)}')
            continue
        for s in copy_sources(open(dp, encoding='utf-8').read()):
            s = s.rstrip('/')
            if staged_ctx and (s == 'code' or s.startswith('code/')):
                continue                                              # `COPY code/` — это контекст из списка, он уже учтён
            if any(ch in s for ch in '*?['):
                import glob
                hits = sorted(os.path.relpath(h, root).replace(os.sep, '/') for h in glob.glob(os.path.join(root, c(s))))
            else:
                hits = [c(s)]
            for h in hits:
                got = walk(root, h)
                if not got:
                    errs.append(f'{c(d)}: COPY {s} — нет такого файла в контексте {ctx}')
                files += [(g, f'COPY из {d}') for g in got]
    seen, uniq = set(), []
    for f, why in files:
        if f not in seen:
            seen.add(f)
            uniq.append((f, why))
    return uniq, errs


# ---------- проверка ----------

def check(root: str, verbose: bool = False) -> int:
    wfs = sorted(f for f in os.listdir(os.path.join(root, WF_DIR)) if WF_GLOB.match(f)) if os.path.isdir(os.path.join(root, WF_DIR)) else []
    bad = 0
    for name in wfs:
        rel = f'{WF_DIR}/{name}'
        try:
            wf = load_wf(os.path.join(root, rel))
        except Exception as exc:                                       # noqa: BLE001 — любой разбор YAML
            print(f'{name}: не удалось разобрать workflow: {exc}')
            return 2
        pp = push_paths(wf)
        if pp is None:
            if verbose:
                print(f'{name}: нет запуска от push — не проверяется')
            continue
        files, errs = image_files(root, rel, wf)
        for e in errs:
            print(f'{name}: {e}')
            bad += 1
        miss = [(f, why) for f, why in files if pp and not covered(pp, f)]
        for f, why in miss:
            print(f'{name}: файл образа не покрыт on.push.paths: {f} ({why})')
            bad += 1
        if verbose:
            extra = [p for p in pp if not any(glob_to_re(p).match(f) for f, _ in files)]
            print(f'{name}: файлов образа {len(files)}, шаблонов paths {len(pp) or "— (любая правка)"}, непокрыто {len(miss)}' + (f'; шаблоны без файлов образа: {extra}' if extra else ''))
    if not wfs:
        print('нет ни одного build-*-trial.yml — проверять нечего')
        return 2
    print(('ОК: paths каждого build-*-trial.yml покрывают все файлы образа' if not bad else f'НАХОДОК: {bad}') + f' (workflow: {len(wfs)})')
    return 1 if bad else 0


# ---------- самопроверка ----------

def selftest() -> int:
    import tempfile
    fail = 0

    def ok(cond: bool, msg: str) -> None:
        nonlocal fail
        print(('  ✓ ' if cond else '  ✗ ') + msg)
        fail += 0 if cond else 1

    print('шаблоны paths GitHub:')
    ok(covered(['a/**'], 'a/b/c.py') and covered(['a/*'], 'a/c.py') and not covered(['a/*'], 'a/b/c.py'), '`*` не пересекает `/`, `**` — пересекает')
    ok(covered(['a/**/x.py'], 'a/x.py') and covered(['a/**/x.py'], 'a/b/c/x.py'), '`**/` — ноль и более папок')
    ok(not covered(['a/**', '!a/b/**'], 'a/b/c.py') and covered(['a/**', '!a/b/**'], 'a/c.py'), '`!шаблон` вычёркивает')
    ok(covered(['x.py'], 'x.py') and not covered(['x.py'], 'dx.py') and not covered(['x.py'], 'x.pyc'), 'точное имя — только оно')

    def put(base: str, rel: str, text: str = 'x\n') -> None:
        p = os.path.join(base, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, 'w', encoding='utf-8').write(text)

    def wf_text(paths: list[str] | None, ctx: str = 'img', stager: bool = True, df: str = 'Dockerfile.img') -> str:
        on = 'on:\n  push:\n    branches: [\'trial/x\']\n' + ('    paths:\n' + ''.join(f"      - '{p}'\n" for p in paths) if paths is not None else '') + '  workflow_dispatch:\n'
        run = ('python3 "$CTX/stage_img_code.py" . "$RUNNER_TEMP/ctx/code"\n' if stager else '') + f'docker build -f "$CTX/{df}" -t x "$CTX"'
        return on + f'env:\n  CTX: {ctx}\njobs:\n  build:\n    runs-on: ubuntu-24.04\n    steps:\n      - run: |\n' + ''.join(f'          {ln}\n' for ln in run.splitlines())

    stager_src = "import os\nLIST = os.path.join(HERE, 'img_files.txt')\n"
    with tempfile.TemporaryDirectory() as t:
        put(t, 'img/stage_img_code.py', stager_src)
        put(t, 'img/Dockerfile.img', 'FROM x\nCOPY code/ /opt/r/\nCOPY extra /app/extra\n')
        put(t, 'img/img_files.txt', '# список\ntools/lib/a.py\ntools/rules/r.json\n')
        put(t, 'img/extra/e.py')
        put(t, 'tools/lib/a.py')
        put(t, 'tools/rules/r.json')
        wfp = os.path.join('.github/workflows', 'build-img-trial.yml')
        full = ['img/**', 'tools/lib/*', 'tools/rules/*.json', wfp]

        print('поддельный workflow, всё покрыто:')
        put(t, wfp, wf_text(full))
        ok(check(t) == 0, 'код 0')

        print('файл из списка образа (rules/*.json) не покрыт — как 24.11 у pose:')
        put(t, wfp, wf_text(['img/**', 'tools/lib/*', wfp]))
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = check(t)
        out = buf.getvalue()
        ok(rc == 1 and 'build-img-trial.yml' in out and 'tools/rules/r.json' in out, 'код 1, в выводе имя workflow и файл')
        ok('tools/lib/a.py' not in out, 'покрытые файлы не ругаются')

        print('файл из COPY не покрыт, Dockerfile не покрыт, сам workflow не покрыт:')
        put(t, wfp, wf_text(['img/stage_img_code.py', 'img/img_files.txt', 'tools/lib/*', 'tools/rules/*.json']))
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = check(t)
        out = buf.getvalue()
        ok(rc == 1 and 'img/extra/e.py' in out and 'img/Dockerfile.img' in out and wfp in out, 'находки: COPY-файл, Dockerfile и workflow')

        print('список ссылается на несуществующий файл:')
        put(t, wfp, wf_text(full))
        put(t, 'img/img_files.txt', 'tools/lib/a.py\ntools/rules/r.json\ntools/lib/gone.py\n')
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = check(t)
        ok(rc == 1 and 'tools/lib/gone.py' in buf.getvalue(), 'код 1, имя пропавшего файла')

        print('push без paths, только workflow_dispatch, сборка без stager:')
        put(t, 'img/img_files.txt', 'tools/lib/a.py\ntools/rules/r.json\n')
        put(t, wfp, wf_text(None))
        ok(check(t) == 0, 'push без paths — любая правка, код 0')
        put(t, wfp, 'on:\n  workflow_dispatch:\nenv:\n  CTX: img\njobs:\n  b:\n    runs-on: x\n    steps:\n      - run: docker build -f "$CTX/Dockerfile.img" .\n')
        ok(check(t) == 0, 'без push — не проверяется, код 0')
        put(t, 'img/Dockerfile.img', 'FROM x\nCOPY extra /app/extra\nCOPY gone.py /app/\n')
        put(t, wfp, wf_text(['img/**', wfp], stager=False))
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = check(t)
        ok(rc == 1 and 'gone.py' in buf.getvalue(), 'COPY несуществующего файла из контекста — находка')
        print('stager импортирует stage_*.py из ДРУГОЙ папки (как render → pose):')
        put(t, 'img/stage_img_code.py', "import os, sys\nHERE = os.path.dirname(os.path.abspath(__file__))\nsys.path.insert(0, os.path.join(HERE, '..', 'other'))\nimport stage_other_code as SO\nLIST = os.path.join(HERE, 'img_files.txt')\n")
        put(t, 'other/stage_other_code.py')
        put(t, 'img/Dockerfile.img', 'FROM x\nCOPY code/ /opt/r/\n')
        put(t, wfp, wf_text(full))
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = check(t)
        ok(rc == 1 and 'other/stage_other_code.py' in buf.getvalue(), 'чужая папка не покрыта — находка с путём other/stage_other_code.py')
        put(t, wfp, wf_text(full + ['other/*']))
        ok(check(t) == 0, 'добавили other/* — код 0')
    print('ИТОГ:', 'ОК' if not fail else f'ПРОВАЛОВ {fail}')
    return 1 if fail else 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--selftest', action='store_true')
    ap.add_argument('--verbose', action='store_true')
    ap.add_argument('--root', default=ROOT, help='корень репозитория (по умолчанию — этот)')
    a = ap.parse_args(argv)
    return selftest() if a.selftest else check(os.path.abspath(a.root), a.verbose)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
