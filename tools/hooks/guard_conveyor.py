#!/usr/bin/env python3
"""PreToolUse-гард конвейера: агент не правит собранный файл руками и не зовёт обход `--force` (T-20261112-121 шаг 3;
план conveyor-guards-01, владелец TG 1366/1370/1381: «всё по конвейеру… чтобы пресекались любые ручные правки»).

Читает тот же реестр, что CI, — `tools/ops/conveyor-manifest.yml` (один список на всех), и то же правило «этот код пишет
в файл», что сканер CI (`conveyor_check.code_writes`):
  Edit / Write / MultiEdit / NotebookEdit — путь = собранный файл реестра → отказ;
  Bash — запись в собранный файл: `>`/`>>`, tee, cp/mv/install/rsync (цель — последний аргумент), `ln -f`, sed -i/perl -i,
         rm/truncate, dd of=; код `python -c`/`node -e` и тело heredoc у `python3 -`/`node` (`bash -c`, `bash <<EOF` — как Bash);
       — обход из `force_guard` реестра (`bank_promote.py --force` и т. п.) → отказ, если нет разового разрешения директора
         (`tools/ops/conveyor_permit.py`, шаг 4): есть — тратим (один запуск) и пускаем, всё — в журнал разрешений.
  Хранилище и журнал разрешений (`~/.local/state/remlab/conveyor-permits.*`) — руками не пишут, как собранные.
Что пропускаем (живые проверки на журналах сессий, T-121):
  • команда, в которой запущен генератор/писатель этого файла (`rm -f materials.json && python material_pipeline.py`,
    `node gen.mjs > out.json`) — пишет конвейер;
  • живой файл (live — вне git) в worktree, если это своя копия, а не ссылка на живой (`cp живой_банк sets3.json` для тестов,
    `ln -s живой sets3.json`, `rm` ссылки); собранный файл в git (tracked) — в любой копии отказ: его закоммитят;
  • копию собранного файла В другое место (`cp sets3.json $D/`); путь через неизвестную переменную (`$R/repo/…` — песочница);
  • текст в кавычках и тела heredoc у `cat >` — данные, не команды.
Разбор по словам (shlex), не по подстроке: `git push --force-with-lease`, текст коммита, `grep sets3.json` — не отказ.
НАМЕРЕННО fail-open: своя ошибка (нет yaml, битый реестр, непонятный ввод) → выход 0. Отказ — выход 2, причина в stderr.

Тест: python3 tools/hooks/guard_conveyor_test.py
"""
import json
import os
import re
import shlex
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
MANIFEST = os.path.join(ROOT, 'tools', 'ops', 'conveyor-manifest.yml')
sys.path.insert(0, os.path.join(ROOT, 'tools', 'ops'))

SEP_CH = set(';&|()')
REDIR = {'>', '>>', '>|', '&>', '&>>'}
LAST_IS_TARGET = {'cp', 'mv', 'install', 'rsync', 'scp'}
ALL_TARGETS = {'tee', 'rm', 'truncate', 'shred', 'unlink'}
INPLACE = {'sed', 'perl', 'ruby'}
SKIP = {'sudo', 'env', 'nice', 'ionice', 'nohup', 'time', 'command', 'exec', 'setsid', 'stdbuf', 'xargs',
        'do', 'then', 'else', 'elif', 'if', 'while', 'until', '!', '{', '}'}
HEREDOC = re.compile(r'<<-?\s*([\'"]?)([A-Za-z_][A-Za-z0-9_]*)\1([^\n]*)\n([\s\S]*?)^\s*\2\s*$', re.M)
WORKTREE = '/.claude/worktrees/'


def load(path=MANIFEST):
    import yaml
    with open(path, encoding='utf-8') as f:
        return yaml.safe_load(f) or {}


def guarded(m):
    out = []
    for kind in ('tracked', 'live'):
        for e in m.get(kind) or []:
            if e.get('path'):
                allowed = [e.get('generator')] + [w.get('path') for w in e.get('writers') or [] if isinstance(w, dict)]
                out.append({'path': e['path'], 'gen': e.get('generator', '?'), 'match': e.get('match') or '', 'kind': kind,
                            'allowed': [a for a in allowed if a]})
    return out


def _norm(p, cwd):
    p = p.strip().strip('"\'')
    home = os.path.expanduser('~')
    p = re.sub(r'^~(?=/|$)', home, p)
    p = re.sub(r'\$\{?HOME\}?(?=/|$)', home, p)
    if '$' in p or '`' in p:   # неизвестная переменная ($D/sets3.json — папка снимков): не знаем, куда — не мешаем
        return None
    if not os.path.isabs(p):
        if not cwd:
            return None
        p = os.path.join(cwd, p)
    return os.path.normpath(p)


def hit(p, cwd, entries, op=''):
    """Запись реестра, которой является путь p (или None). op — чем пишут (для ссылок: rm ссылки — не запись)."""
    n = _norm(p, cwd)
    if not n:
        return None
    for e in entries:
        g = e['path']
        if g.startswith('~'):
            same = n == os.path.normpath(os.path.expanduser(g))
        else:   # любой копии репо (основная, worktree)
            same = n.endswith('/' + g) or n == g or bool(e['match'] and n.endswith('/' + e['match']))
        if not same:
            continue
        if e['kind'] == 'live' and not g.startswith('~') and WORKTREE in n:
            real = os.path.realpath(n)
            if not os.path.islink(n) and WORKTREE in real:
                continue   # своя копия живого файла в worktree — не живой
            if os.path.islink(n) and op in ('rm', 'unlink', 'ln'):
                continue   # убрать/поставить ссылку — живой файл не меняется
        return e
    return None


def _split_heredocs(cmd):
    """Команда без тел heredoc + [(строка-заголовок, тело)]. Строку после заголовка сохраняем — это следующая команда."""
    docs = []

    def cut(m):
        docs.append((cmd[:m.start()], m.group(4)))   # всё до `<<`: интерпретатор — последняя команда, `cd` — по пути
        return m.group(3) + '\n'
    return HEREDOC.sub(cut, cmd), docs


def _tokens(text):
    try:   # перевод строки — разделитель команд, но внутри кавычек (текст коммита) — часть слова
        lx = shlex.shlex(text, posix=True, punctuation_chars=';&|()<>\n')
        lx.whitespace = ' \t\r'
        lx.whitespace_split = True
        lx.commenters = '#'
        return list(lx)
    except ValueError:   # кавычки не закрыты (`$(…'"'…)`) — грубо: строки в кавычках выкинуть, остальное по словам
        rough = re.sub(r'"[^"]*"|\'[^\']*\'', ' ', text)
        return re.findall(r'[;&|()\n]+|[<>]+&?|[^\s;&|()<>]+', rough)


def segments(cmd):
    """Простые команды: [[слово, …], …] — по ; && || | & ( ) и переводу строки вне кавычек."""
    out, seg = [], []
    for t in _tokens(cmd):
        if t and set(t) <= SEP_CH | {'\n'}:
            if seg:
                out.append(seg)
            seg = []
            continue
        seg.append(t)
    if seg:
        out.append(seg)
    return out


def _cmd_index(seg):
    i = 0
    while i < len(seg):
        t = seg[i]
        if re.match(r'^[A-Za-z_]\w*=', t) or os.path.basename(t) in SKIP or t.startswith('-') \
                or (i > 0 and os.path.basename(seg[i - 1]) in ('timeout', 'nice') and re.match(r'^[\d.]+[smh]?$', t)):
            i += 1
            continue
        if os.path.basename(t) == 'timeout':
            i += 1
            continue
        break
    return i


PY_WRITE_LAST = {'replace', 'rename', 'copy', 'copy2', 'copyfile', 'move', 'copytree'}   # os./shutil.: цель — последний


def _py_paths(code, cwd):
    """Python-код (`-c`, heredoc): куда он пишет — по синтаксису, не по тексту. Путь вычисляем из констант и переменных
    (`p='data/x.json'`, `os.path.join(HOME, 'x')`, `Path(p)`, `~`); неизвестная часть (sys.argv, $B) — путь неизвестен, не цель.
    Код в строках (правка исходника заменой текста) — строка, не вызов: не запись."""
    import ast
    tree = ast.parse(code)
    env = {}

    def val(n):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            return n.value
        if isinstance(n, ast.Name):
            return env.get(n.id)
        if isinstance(n, ast.JoinedStr):
            parts = [val(v) for v in n.values]
            return ''.join(parts) if all(p is not None for p in parts) else None
        if isinstance(n, ast.BinOp) and isinstance(n.op, (ast.Add, ast.Div)):
            a, b = val(n.left), val(n.right)
            if a is None or b is None:
                return None
            return a + b if isinstance(n.op, ast.Add) else os.path.join(a, b)
        if isinstance(n, ast.Call):
            f = n.func
            name = f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else ''
            if name in ('join', 'Path', 'PurePath', 'PosixPath') and n.args:
                parts = [val(a) for a in n.args]
                return os.path.join(*parts) if all(p is not None for p in parts) else None
            if name in ('expanduser', 'abspath', 'realpath', 'normpath', 'str', 'fspath') and n.args:
                v = val(n.args[0])
                return os.path.expanduser(v) if v is not None else None
            if name in ('resolve', 'expanduser', 'absolute') and isinstance(f, ast.Attribute):
                v = val(f.value)
                return os.path.expanduser(v) if v is not None else None
        return None

    for _ in range(2):   # присвоения (дважды — ссылки вперёд по коду)
        for n in ast.walk(tree):
            if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
                v = val(n.value)
                if v is not None:
                    env[n.targets[0].id] = v
    out = []
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call):
            continue
        f = n.func
        name = f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else ''
        if name == 'open' and n.args:
            mode = n.args[1] if len(n.args) > 1 else next((k.value for k in n.keywords if k.arg == 'mode'), None)
            m = mode.value if isinstance(mode, ast.Constant) and isinstance(mode.value, str) else ''
            tgt = n.args[0] if isinstance(f, ast.Name) else f.value if isinstance(f, ast.Attribute) else None
            if isinstance(f, ast.Attribute) and not isinstance(f.value, ast.Name) and len(n.args) >= 1:   # Path(p).open('w')
                m = n.args[0].value if isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str) else ''
            if set(m) & set('wax+') and tgt is not None:
                out.append(val(tgt))
        elif name in ('write_text', 'write_bytes', 'touch', 'unlink') and isinstance(f, ast.Attribute):
            out.append(val(f.value))
        elif name in PY_WRITE_LAST and isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) \
                and f.value.id in ('os', 'shutil') and len(n.args) >= 2:
            out.append(val(n.args[-1]))
        elif name in ('remove', 'unlink') and isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) \
                and f.value.id == 'os' and n.args:
            out.append(val(n.args[0]))
    return [p for p in out if p]


def _code_hits(code, ext, entries, cwd):
    if ext == '.py':
        import warnings
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('ignore')   # SyntaxWarning «\$» в чужом коде — не наше дело
                return [e for p in _py_paths(code, cwd) for e in [hit(p, cwd, entries, 'py')] if e]
        except (SyntaxError, ValueError, RecursionError):
            return []   # python такой код не запустит — записи не будет
    import conveyor_check as CC
    out = []
    for e in entries:
        lit = e['match'] or os.path.basename(e['path'])
        if CC.code_writes(code, lit, ext):
            out.append(e)
    return out


def _runs(segs, path):
    base = os.path.basename(path)
    return any(os.path.basename(t) == base for s in segs for t in s)


def bash_writes(cmd, cwd, entries, depth=0):
    """[(запись реестра, как пишет)] — записи в собранные файлы."""
    body, docs = _split_heredocs(cmd)
    segs = segments(body)
    found = []
    for head, doc in docs:   # тело heredoc: у интерпретатора — код, у bash — команды, у cat > — данные
        hs = segments(HEREDOC.sub('\n', head))
        hcwd = cwd
        for s in hs[:-1]:   # `cd X && python3 - <<EOF` — код идёт из X
            j = _cmd_index(s)
            if j < len(s) and os.path.basename(s[j]) in ('cd', 'pushd'):
                rest = [a for a in s[j + 1:] if not a.startswith('-')]
                hcwd = _norm(rest[0], hcwd) if rest else os.path.expanduser('~')
        h = hs[-1] if hs else []
        k = _cmd_index(h)
        name = os.path.basename(h[k]) if k < len(h) else ''
        if name.startswith('python'):
            found += [(e, f'{name} <<heredoc с записью в {e["path"]}') for e in _code_hits(doc, '.py', entries, hcwd)]
        elif name == 'node':
            found += [(e, f'node <<heredoc с записью в {e["path"]}') for e in _code_hits(doc, '.mjs', entries, hcwd)]
        elif name in ('bash', 'sh') and depth < 2:
            found += bash_writes(doc, hcwd, entries, depth + 1)
    for seg in segs:
        toks, k = [], 0
        while k < len(seg):   # перенаправления: цель — следующее слово
            t = seg[k]
            if t in REDIR or (t.endswith('>') and t.rstrip('>').isdigit()):
                if k + 1 < len(seg):
                    e = hit(seg[k + 1], cwd, entries)
                    if e:
                        found.append((e, f'перенаправление {t} {seg[k + 1]}'))
                k += 2
                continue
            if t in ('<', '<<', '<<<', '<&', '>&', '<>'):
                k += 2
                continue
            toks.append(t)
            k += 1
        i = _cmd_index(toks)
        if i >= len(toks):
            continue
        name, args = os.path.basename(toks[i]), toks[i + 1:]
        plain = [a for a in args if not a.startswith('-')]
        if name in ('cd', 'pushd'):   # `cd tools/scout && cp n.json sets3.json` — дальше пути от новой папки
            cwd = _norm(plain[0], cwd) if plain else os.path.expanduser('~')
            continue
        targets = []
        if name in LAST_IS_TARGET and len(plain) >= 2:
            targets = [plain[-1]]
        elif name == 'ln' and len(plain) >= 2 and any(re.match(r'^-[a-zA-Z]*f', a) or a == '--force' for a in args):
            targets = [plain[-1]]
        elif name in ALL_TARGETS:
            targets = plain
        elif name in INPLACE and any(re.match(r'^-[a-zA-Z]*i', a) or a.startswith('--in-place') for a in args):
            targets = plain
        elif name == 'dd':
            targets = [a[3:] for a in args if a.startswith('of=')]
        for t in targets:
            e = hit(t, cwd, entries, name)
            if e:
                found.append((e, f'{name} … {t}'))
        if name.startswith('python') and '-c' in args and args.index('-c') + 1 < len(args):
            found += [(e, f'{name} -c с записью в {e["path"]}') for e in _code_hits(args[args.index('-c') + 1], '.py', entries, cwd)]
        if name == 'node' and ('-e' in args or '--eval' in args):
            j = args.index('-e') if '-e' in args else args.index('--eval')
            if j + 1 < len(args):
                found += [(e, f'node -e с записью в {e["path"]}') for e in _code_hits(args[j + 1], '.mjs', entries, cwd)]
        if name in ('bash', 'sh') and '-c' in args and args.index('-c') + 1 < len(args) and depth < 2:
            found += bash_writes(args[args.index('-c') + 1], cwd, entries, depth + 1)
    # генератор/писатель этого файла запущен в той же команде — пишет конвейер (`rm -f out && gen`, `gen > out`)
    return [(e, how) for e, how in found if not any(_runs(segs, a) for a in e['allowed'])]


def bash_force(cmd, cwd, guards):
    """[(инструмент, флаг)] — обходы конвейера из `force_guard` реестра (инструмент в известном месте)."""
    body, _docs = _split_heredocs(cmd)
    found = []
    for seg in segments(body):
        k = _cmd_index(seg)
        if k < len(seg) and os.path.basename(seg[k]) in ('cd', 'pushd'):
            rest = [a for a in seg[k + 1:] if not a.startswith('-')]
            cwd = _norm(rest[0], cwd) if rest else os.path.expanduser('~')
            continue
        for g in guards:
            base = os.path.basename(g.get('path', ''))
            j = next((x for x, t in enumerate(seg) if base and os.path.basename(t) == base), None)
            if j is None or not _norm(seg[j], cwd):
                continue   # не запуск инструмента или он в неизвестном месте (`cd $R/repo` — песочница)
            for f in g.get('flags') or []:
                if any(t == f or t.startswith(f + '=') for t in seg[j + 1:]):
                    found.append((g, f))
    return found


def _permit_entries():
    """Хранилище и журнал разрешений (шаг 4) — как собранные: пишет только tools/ops/conveyor_permit.py."""
    import conveyor_permit as P
    return [{'path': p, 'gen': 'tools/ops/conveyor_permit.py', 'match': '', 'kind': 'live',
             'allowed': ['tools/ops/conveyor_permit.py']} for p in P.paths()]


def _force_permitted(fz, cmd):
    """Обходы команды: на КАЖДЫЙ инструмент — разовое разрешение (conveyor_permit). Все есть — тратим и пускаем; нет — (g, флаги)."""
    import conveyor_permit as P
    need = {}
    for g, f in fz:
        need.setdefault(os.path.basename(g['path']), (g, set()))[1].add(f)
    for tool, (g, flags) in need.items():
        if not P.take(tool, flags, cmd, dry=True):
            P.journal('deny', dict(tool=tool, flags=sorted(flags)), cmd=cmd[:500])
            return g, flags
    for tool, (g, flags) in need.items():
        P.take(tool, flags, cmd)
    return None


def decide(inp, m):
    """None — пропустить; иначе текст отказа."""
    tool, ti, cwd = inp.get('tool_name', ''), inp.get('tool_input') or {}, inp.get('cwd') or os.getcwd()
    entries = guarded(m) + _permit_entries()
    if tool in ('Edit', 'Write', 'MultiEdit', 'NotebookEdit'):
        p = ti.get('file_path') or ti.get('notebook_path') or ''
        e = hit(p, cwd, entries) if p else None
        if e:
            return (f'СОБРАННЫЙ ФАЙЛ — руками не правят: {e["path"]} собирает {e["gen"]}.\n'
                    'Правьте вход (правило rules/**, шаблон, словарь, генератор) и пересоберите генератором — '
                    'тогда правка дойдёт до всех комнат, туров и ночи (конвейер, не заплатка; реестр tools/ops/conveyor-manifest.yml).')
        return None
    if tool == 'Bash':
        cmd = ti.get('command') or ''
        if not isinstance(cmd, str) or not cmd:
            return None
        w = bash_writes(cmd, cwd, entries)
        if w:
            e, how = w[0]
            return (f'СОБРАННЫЙ ФАЙЛ — руками не правят ({how}): {e["path"]} собирает {e["gen"]}.\n'
                    'Правьте вход и пересоберите генератором; копию для снимка кладите в НОВУЮ папку (cp файл $D/). '
                    'Реестр — tools/ops/conveyor-manifest.yml.')
        fz = bash_force(cmd, cwd, m.get('force_guard') or [])
        miss = _force_permitted(fz, cmd) if fz else None
        if miss:
            g, flags = miss
            t = f'{os.path.basename(g["path"])} {" ".join(sorted(flags))}'
            return (f'ОБХОД КОНВЕЙЕРА: {t} — {g.get("why", "")}\n'
                    'Только по слову владельца. Попросите директора; он выпускает разовое разрешение (один запуск, срок ≤ 24 ч):\n'
                    f'  python3 tools/ops/conveyor_permit.py issue --tid <T-ID> --tg <номер сообщения владельца> --target "{t}" --hours 2\n'
                    'Реестр обходов — tools/ops/conveyor-manifest.yml § force_guard; журнал — conveyor_permit.py list.')
    return None


def main():
    try:
        inp = json.loads(sys.stdin.read() or '{}')
        msg = decide(inp, load())
    except Exception:   # noqa: BLE001 — fail-open: сломанный гард не должен останавливать работу
        return 0
    if not msg:
        return 0
    sys.stderr.write(msg + '\n')
    return 2


if __name__ == '__main__':
    sys.exit(main())
