#!/usr/bin/env python3
"""ЧТО ЕДЕТ В ОБРАЗ ПРОДА — сторож импортов против `.dockerignore` (T-20261112-121/3; 13.11 выкладка прода упала на `pnpm build`
в образе: `lib/trial/auto-photos-pick.ts` импортирует `@/tools/scout/rules/tour-auto-photos.json`, а `.dockerignore` выкидывает
`tools/` — локально и в CI сборка зелёная, ловилось только в Deploy, прод ~1,5 ч позади main).

Правило: файл, который попадает в сборку образа, не может опираться на файл, которого в образе нет. Сборка образа — `COPY . .` +
`pnpm build` (`Dockerfile`): `next build` проверяет типы во ВСЕХ `*.ts`/`*.tsx` контекста (`tsconfig.json: include **/*.ts`) и
собирает то, что импортирует `app/`. Поэтому:
  • корни — все `.ts/.tsx` контекста образа (не выкинутые `.dockerignore`) и `.js/.mjs/.cjs` в `app/ lib/ components/`;
  • от них — по импортам (`import … from`, `export … from`, `import()`, `require()`, `/// <reference path>`; `@/` = корень репо,
    `./` — от файла) транзитивно; импортирован выкинутый файл → красный: вернуть его строкой `!путь` в `.dockerignore`
    (только этот файл, не папку) или не импортировать из tools/docs/infra;
  • чтение с диска в коде приложения (`app/ lib/ components/`): `path.join/resolve(…)` из одних строк (можно после
    `process.cwd()`/`__dirname`) или строка-путь, которые указывают на выкинутый файл репо, — тоже красный.
Разбор `.dockerignore` — как у Docker (moby patternmatcher): `#` — комментарий, путь чистится, ведущий `/` снимается, `*` и `?` —
в пределах одного имени, `**` — любые папки, шаблон без `/` — только верхний уровень (`*.md` — файлы в корне, не `docs/a.md`);
файл выкинут, если шаблон совпал с ним или с его папкой-родителем; ПОСЛЕДНЕЕ совпадение решает, `!шаблон` возвращает файл —
и внутри выкинутой папки (BuildKit, проверено директором 13.11).

  python tools/ops/docker_context.py             # проверка дерева (CI и prepush — через conveyor_check.py)
  python tools/ops/docker_context.py --ignored <путь>…   # выкинут ли путь
  python tools/ops/docker_context.py --selftest
"""
from __future__ import annotations

import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT_DEFAULT = os.path.abspath(os.path.join(HERE, '..', '..'))
APP_DIRS = ('app/', 'lib/', 'components/')
TS_EXT = ('.ts', '.tsx', '.mts', '.cts')
JS_EXT = ('.js', '.mjs', '.cjs', '.jsx')
RESOLVE_EXT = ('', '.ts', '.tsx', '.d.ts', '.js', '.mjs', '.cjs', '.jsx', '.json')
# `next build` не считает ошибки типов в тестах (node_modules/next/dist/lib/typescript/runTypeCheck.js: ignoreRegex — `__tests__/`,
# `*.test.*`, `*.spec.*`): tests/unit/demo-url.test.ts импортирует выкинутый e2e/live/browser.ts с 05.11, и прод собирался.
NEXT_TEST = re.compile(r'[\\/]__(?:tests|mocks)__[\\/]|(?<=[\\/.])(?:spec|test)\.[^\\/]+$')


# --------------------------------------------------------------------------------------------- .dockerignore как у Docker
def _regex(pat: str) -> re.Pattern:
    out, i = '', 0
    while i < len(pat):
        c = pat[i]
        if c == '*':
            if pat[i + 1:i + 2] == '*':
                i += 1
                if pat[i + 1:i + 2] == '/':
                    i += 1
                out += '.*' if i + 1 >= len(pat) else '(.*/)?'
            else:
                out += '[^/]*'
        elif c == '?':
            out += '[^/]'
        elif c == '\\' and i + 1 < len(pat):
            i += 1
            out += re.escape(pat[i])
        elif c == '[':
            j = pat.find(']', i + 1)
            if j < 0:
                out += re.escape(c)
            else:
                body = pat[i + 1:j]
                out += '[' + ('^' + body[1:] if body.startswith('!') else body) + ']'
                i = j
        else:
            out += re.escape(c)
        i += 1
    return re.compile('^' + out + '$')


def parse(text: str) -> list[tuple[re.Pattern, bool, str]]:
    """→ [(шаблон, это_исключение «!», исходная строка)] по порядку."""
    out = []
    for raw in text.splitlines():
        s = raw.strip()
        if not s or s.startswith('#'):
            continue
        neg = s.startswith('!')
        if neg:
            s = s[1:].strip()
        s = os.path.normpath(s).replace(os.sep, '/')
        if len(s) > 1 and s.startswith('/'):
            s = s[1:]
        if s in ('', '.'):
            continue
        out.append((_regex(s), neg, raw.strip()))
    return out


def ignored(path: str, pats) -> bool:
    """Выкинут ли `path` (от корня контекста): последнее совпадение с файлом или его папкой-родителем решает."""
    path = path.strip('/')
    parts = path.split('/')
    parents = ['/'.join(parts[:i + 1]) for i in range(len(parts) - 1)]
    hit = False
    for rx, neg, _ in pats:
        if neg != hit:          # возвращать нечего / выкидывать уже выкинутое — шаблон ничего не меняет
            continue
        if rx.match(path) or any(rx.match(p) for p in parents):
            hit = not neg
    return hit


# --------------------------------------------------------------------------------------------------------- импорты
JS_TOK = re.compile(r'//[^\n]*|/\*.*?\*/|"(?:[^"\\\n]|\\.)*"|\'(?:[^\'\\\n]|\\.)*\'|`(?:[^`\\]|\\.)*`', re.S)
SPEC = r'''(['"])([^'"\n]+)\1'''
IMPORTS = (
    re.compile(r'''\b(?:import|export)\s[^;'"`]*?\bfrom\s*''' + SPEC),
    re.compile(r'''\bimport\s*''' + SPEC),
    re.compile(r'''\b(?:import|require)\s*\(\s*''' + SPEC),
)
REFERENCE = re.compile(r'''///\s*<reference\s+path\s*=\s*''' + SPEC)
JOIN = re.compile(r'''\b(?:path\.)?(?:join|resolve)\(\s*((?:(?:process\.cwd\(\)|__dirname|['"][^'"\n]*['"])\s*,?\s*)+)\)''')
LIT = re.compile(r'''['"]([^'"\n]*)['"]''')


def _no_comments(src: str) -> str:
    """Комментарии — пробелами (строки целы: в них пути импорта)."""
    return JS_TOK.sub(lambda m: re.sub(r'[^\n]', ' ', m.group(0)) if m.group(0).startswith('/') else m.group(0), src)


def specs(src: str) -> list[tuple[int, str]]:
    """→ [(строка, путь импорта)]; ссылки `/// <reference path>` — тоже (это комментарий, но TS их читает)."""
    out = []
    for m in REFERENCE.finditer(src):
        out.append((src.count('\n', 0, m.start()) + 1, m.group(2) if m.group(2).startswith('.') else './' + m.group(2)))
    code = _no_comments(src)
    for rx in IMPORTS:
        for m in rx.finditer(code):
            out.append((code.count('\n', 0, m.start()) + 1, m.group(2)))
    return out


def disk_paths(src: str) -> list[tuple[int, str]]:
    """→ [(строка, путь от корня)] чтения с диска: path.join/resolve из строк, строки вида «tools/…/x.json»."""
    code, out = _no_comments(src), []
    for m in JOIN.finditer(code):
        segs = LIT.findall(m.group(1))
        if segs:
            out.append((code.count('\n', 0, m.start()) + 1, '/'.join(s.strip('/') for s in segs if s.strip('/'))))
    return out


def resolve(root: str, frm: str, spec: str) -> str | None:
    if spec.startswith('@/'):
        base = spec[2:]
    elif spec.startswith('.'):
        base = os.path.normpath(os.path.join(os.path.dirname(frm), spec)).replace(os.sep, '/')
    else:
        return None                      # пакет из node_modules
    if base.startswith('..'):
        return None
    for ext in RESOLVE_EXT:
        if os.path.isfile(os.path.join(root, base + ext)):
            return base + ext
    for ext in RESOLVE_EXT[1:]:
        if os.path.isfile(os.path.join(root, base, 'index' + ext)):
            return f'{base}/index{ext}'
    if base.endswith('.js'):            # TS: импорт «./x.js» — файл «./x.ts»
        for ext in TS_EXT:
            if os.path.isfile(os.path.join(root, base[:-3] + ext)):
                return base[:-3] + ext
    return None


def git_files(root: str) -> list[str]:
    r = subprocess.run(['git', '-C', root, 'ls-files', '-z'], capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise RuntimeError(f'git ls-files: {r.stderr.strip()[:200]}')
    return [p for p in r.stdout.split('\0') if p]


def roots_of(files: list[str], pats) -> list[str]:
    out = []
    for f in files:
        if f.startswith('node_modules/') or ignored(f, pats) or NEXT_TEST.search('/' + f):
            continue
        if f.endswith(TS_EXT) or (f.startswith(APP_DIRS) and f.endswith(JS_EXT)):
            out.append(f)
    return out


def scan(root: str, files: list[str] | None = None, dockerignore: str | None = None) -> list[str]:
    """→ строки нарушений (пусто — образ соберётся с тем, что импортирует/читает код)."""
    if dockerignore is None:
        with open(os.path.join(root, '.dockerignore'), encoding='utf-8') as f:
            dockerignore = f.read()
    pats = parse(dockerignore)
    files = files if files is not None else git_files(root)
    queue, seen, bad = roots_of(files, pats), set(), []
    while queue:
        f = queue.pop()
        if f in seen:
            continue
        seen.add(f)
        try:
            with open(os.path.join(root, f), encoding='utf-8') as fh:
                src = fh.read()
        except (OSError, UnicodeDecodeError):
            continue
        if f.endswith('.json') or NEXT_TEST.search('/' + f):
            continue
        for ln, sp in specs(src):
            t = resolve(root, f, sp)
            if not t:
                continue
            if ignored(t, pats):
                bad.append(f'{f}:{ln} импортирует {t}, а .dockerignore его выкидывает — образ прода не соберётся '
                           f'(в CI и локально зелено). Вернуть строкой `!{t}` в .dockerignore или не брать из этой папки')
            else:
                queue.append(t)
        if f.startswith(APP_DIRS):
            for ln, p in disk_paths(src):
                if p and os.path.isfile(os.path.join(root, p)) and ignored(p, pats):
                    bad.append(f'{f}:{ln} читает с диска {p}, а .dockerignore его выкидывает — в образе файла нет. '
                               f'Вернуть строкой `!{p}` в .dockerignore или положить данные в образ иначе')
    return sorted(set(bad))


def check(root: str, out=sys.stdout) -> int:
    bad = scan(root)
    for b in bad:
        print(f'FAIL:docker_context: {b}', file=out)
    print(f'образ прода: импорты и чтения из выкинутого .dockerignore — {len(bad)}', file=out)
    return 1 if bad else 0


def _selftest() -> int:
    import io
    import tempfile
    bad = []

    def ok(c, m, info=''):
        print(('OK  ' if c else 'BAD ') + m + ('' if c else f' :: {info}'))
        if not c:
            bad.append(m)

    di = ('# комментарий\nnode_modules\n/infra\ntools\ndocs\n*.md\nplaywright*.config.ts\n.env.*\n!.env.example\n'
          'a/**/secret.json\n!tools/scout/rules/keep.json\n')
    p = parse(di)
    for path, want, why in (('tools/scout/x.py', True, 'папка tools — и всё под ней'),
                            ('tools', True, 'сама папка'),
                            ('tools/scout/rules/keep.json', False, '«!файл» внутри выкинутой папки — возвращает'),
                            ('tools/scout/rules/other.json', True, 'соседний файл — выкинут'),
                            ('README.md', True, '*.md в корне'),
                            ('docs/a.md', True, 'docs/ выкинута'),
                            ('lib/notes.md', False, '*.md без «/» — только верхний уровень (как у Docker)'),
                            ('infra/x.sh', True, 'ведущий «/» снимается'),
                            ('playwright.live.config.ts', True, 'звёздочка в имени'),
                            ('.env.local', True, '.env.*'), ('.env.example', False, '!.env.example'),
                            ('a/b/c/secret.json', True, '** — любые папки'), ('a/secret.json', True, '** — и ноль папок'),
                            ('lib/x.ts', False, 'lib — в образе')):
        ok(ignored(path, p) == want, f'.dockerignore: {path} — {why}', ignored(path, p))
    ok(ignored('tools/scout/rules/keep.json', parse('tools\n!tools/scout/rules/keep.json\ntools\n')),
       'последнее совпадение решает: «tools» после «!» выкидывает снова')
    with tempfile.TemporaryDirectory(prefix='docker-ctx-') as d:
        def put(rel, text):
            q = os.path.join(d, rel)
            os.makedirs(os.path.dirname(q), exist_ok=True)
            with open(q, 'w', encoding='utf-8') as f:
                f.write(text)

        put('tools/scout/rules/r.json', '{}')
        put('tools/scout/rules/keep.json', '{}')
        put('tools/scout/helper.ts', 'export const h = 1;\n')
        put('lib/util.ts', 'export const u = 1;\n')
        put('lib/deep.ts', "export { u } from './util';\n")
        put('services/shared/x.ts', "import R from '@/tools/scout/rules/r.json';\nexport default R;\n")
        put('app/page.tsx', "import { u } from '@/lib/deep';\n// import X from '@/tools/scout/rules/r.json';\nexport default u;\n")
        put('lib/reader.ts', "const p = path.join(process.cwd(), 'tools', 'scout', 'rules', 'r.json');\n")
        files = ['tools/scout/rules/r.json', 'tools/scout/rules/keep.json', 'tools/scout/helper.ts', 'lib/util.ts', 'lib/deep.ts',
                 'services/shared/x.ts', 'app/page.tsx', 'lib/reader.ts']
        base = 'tools\n!tools/scout/rules/keep.json\n'
        ok(scan(d, files[:5] + ['app/page.tsx'], base) == [], 'импорт из lib (и комментарий с tools) — ок')
        put('lib/pick.ts', "import R from '@/tools/scout/rules/r.json';\nexport default R;\n")
        got = scan(d, files + ['lib/pick.ts'], base)
        ok(any(g.startswith('lib/pick.ts:1 импортирует tools/scout/rules/r.json') for g in got),
           'импорт из tools без исключения — красный', got)
        ok(any(g.startswith('services/shared/x.ts:1') for g in got), 'любой .ts контекста образа — тоже корень (next build типы)', got)
        ok(any(g.startswith('lib/reader.ts:1 читает с диска tools/scout/rules/r.json') for g in got), 'чтение path.join из выкинутого — красный', got)
        got2 = scan(d, files + ['lib/pick.ts'], base + '!tools/scout/rules/r.json\n')
        ok(got2 == [], 'с исключением «!путь» — ок', got2)
        put('lib/pick.ts', "import { h } from '../tools/scout/helper';\nexport default h;\n")
        got = scan(d, ['tools/scout/helper.ts', 'lib/pick.ts'], base)
        ok(any('импортирует tools/scout/helper.ts' in g for g in got), 'относительный импорт ../tools — красный', got)
        put('lib/dyn.ts', "export const f = () => import('@/tools/scout/helper');\n")
        ok(any('lib/dyn.ts' in g for g in scan(d, ['tools/scout/helper.ts', 'lib/dyn.ts'], base)), 'import() — красный')
        put('tests/unit/a.test.ts', "import R from '@/tools/scout/rules/r.json';\n")
        ok(scan(d, ['tools/scout/rules/r.json', 'tests/unit/a.test.ts'], base) == [],
           'тест (*.test.ts) — next build не проверяет его типы, импорт из tools не ломает образ')
        put('tests/unit/helper.ts', "import R from '@/tools/scout/rules/r.json';\n")
        ok(any('tests/unit/helper.ts' in g for g in scan(d, ['tools/scout/rules/r.json', 'tests/unit/helper.ts'], base)),
           'помощник тестов без «.test.» — проверяется next build, красный')
        put('tools/ops/script.ts', "import R from '@/tools/scout/rules/r.json';\n")
        ok(scan(d, ['tools/scout/rules/r.json', 'tools/ops/script.ts'], base) == [], 'выкинутый .ts сам в образ не едет — не корень')
    buf = io.StringIO()
    ok(check(ROOT_DEFAULT, out=buf) == 0, 'в репо: образ прода собирается с тем, что импортирует код', buf.getvalue()[-800:])
    print('итог:', 'OK' if not bad else f'FAIL ({len(bad)})')
    return 1 if bad else 0


def main(argv: list[str]) -> int:
    if argv[:1] == ['--selftest']:
        return _selftest()
    if argv[:1] == ['--ignored']:
        with open(os.path.join(ROOT_DEFAULT, '.dockerignore'), encoding='utf-8') as f:
            p = parse(f.read())
        for a in argv[1:]:
            print(f"{a}: {'выкинут' if ignored(a, p) else 'в образе'}")
        return 0
    return check(ROOT_DEFAULT)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
