"""Образ запасного рендера (`infra/draft/Dockerfile`) несёт все файлы правил, которые читает его код (T-20261107-03).
07.11 фото спальни ушло на запасной рендер прода (DEV-рендер снял earlyoom) и упало «No such file /app/rules/improve-rooms.json»:
файл добавили в код (T-32/3, `improve_mode.room_rules`), а в COPY образа — нет. Сборка этого не ловила: файл читается лениво,
при первом фото не-гостиной, а проверка образа — только импорты.
Проверяем по тексту, без docker:
- каждый модуль, который Dockerfile кладёт в /app (scout поштучно, планировщик папкой), — чтения `rules/<файл>` (`'rules', '<файл>'` в коде, не в комментарии):
  файл должен быть в COPY → /app/rules/ (из tools/scout/rules или целиком services/planner-solver/rules) И в белом списке
  `Dockerfile.dockerignore` (иначе его нет в контексте сборки); исключение — OPTIONAL с причиной (чтение в try/except с запасом);
- всё, что Dockerfile копирует, есть в git-дереве и в белом списке (рассинхрон COPY ↔ белый список роняет сборку);
- проверка ловит подложенное: Dockerfile без improve-rooms.json даёт отказ.
    python3 tools/scout/tests/test_draft_image_rules.py"""
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..'))
DOCKERFILE = os.path.join(ROOT, 'infra', 'draft', 'Dockerfile')
IGNORE = os.path.join(ROOT, 'infra', 'draft', 'Dockerfile.dockerignore')
# чтения, которым файл в образе не нужен: причина — почему без него работает
OPTIONAL = {
    'dev-tmp.json': 'draft_render._cache_dir/_cache_trim: потолки кэша DEV, чтение в try/except, в контейнере — /tmp и 600 МБ',
}
READ = re.compile(r"""['"]rules['"]\s*,\s*['"]([\w.-]+\.json)['"]""")
BAD = []


def ok(cond, msg):
    print(('  ok  ' if cond else '  FAIL ') + msg)
    if not cond:
        BAD.append(msg)


def copies(text):
    """[(источники, назначение)] из COPY Dockerfile (строки с `\\` склеены)."""
    text = re.sub(r'\\\n', ' ', text)
    out = []
    for line in text.splitlines():
        parts = line.split()
        if parts[:1] == ['COPY'] and len(parts) >= 3 and not parts[1].startswith('--'):
            out.append((parts[1:-1], parts[-1]))
    return out


def rules_in_image(cps):
    """Имена файлов, которые окажутся в /app/rules/: поштучно и целыми папками правил."""
    names = set()
    for srcs, dst in cps:
        if dst.rstrip('/') != '/app/rules':
            continue
        for s in srcs:
            p = os.path.join(ROOT, s)
            if s.endswith('/') and os.path.isdir(p):
                names |= {f for f in os.listdir(p) if os.path.isfile(os.path.join(p, f))}
            else:
                names.add(os.path.basename(s))
    return names


def app_modules(cps):
    """Модули scout в /app и модули папок, скопированных целиком (планировщик в /app/planner/)."""
    out = [s for srcs, dst in cps if dst.rstrip('/') == '/app' for s in srcs if s.endswith('.py')]
    for srcs, dst in cps:
        for s in srcs:
            p = os.path.join(ROOT, s)
            if s.endswith('/') and os.path.isdir(p) and dst.rstrip('/') != '/app/rules':
                out += [s + f for f in sorted(os.listdir(p)) if f.endswith('.py')]
    return out


def code_reads(path):
    reads = {}
    with open(path, encoding='utf-8') as f:
        for n, line in enumerate(f, 1):
            if line.strip().startswith('#'):
                continue
            for m in READ.finditer(line.split('  # ')[0]):
                reads.setdefault(m.group(1), n)
    return reads


def whitelisted(rel, allow):
    for a in allow:
        if a.endswith('/**') and rel.startswith(a[:-2]):
            return True
        if rel.rstrip('/') == a or rel.rstrip('/') + '/**' == a:
            return True
    return False


def missing(docker_text, allow):
    """Чтения rules/* модулей образа, которых нет в образе: [(модуль:строка, файл, чего нет)]."""
    cps = copies(docker_text)
    have = rules_in_image(cps)
    out = []
    for mod in app_modules(cps):
        for name, line in code_reads(os.path.join(ROOT, mod)).items():
            if name in OPTIONAL:
                continue
            if name not in have:
                out.append((f'{mod}:{line}', name, 'нет в COPY → /app/rules/'))
            elif os.path.exists(os.path.join(ROOT, 'tools/scout/rules', name)) and \
                    not whitelisted(f'tools/scout/rules/{name}', allow) and \
                    not os.path.exists(os.path.join(ROOT, 'services/planner-solver/rules', name)):
                out.append((f'{mod}:{line}', name, 'нет в Dockerfile.dockerignore'))
    return out


def main():
    docker_text = open(DOCKERFILE, encoding='utf-8').read()
    allow = [l.strip()[1:] for l in open(IGNORE, encoding='utf-8') if l.strip().startswith('!')]
    cps = copies(docker_text)
    mods = app_modules(cps)

    print('модули образа и их чтения rules/*:')
    ok(len(mods) >= 8 and 'tools/scout/improve_mode.py' in mods, f'модулей в /app: {len(mods)}')
    for mod in mods:
        r = code_reads(os.path.join(ROOT, mod))
        if r:
            print(f'       {mod}: ' + ', '.join(f'{k} (стр. {v})' for k, v in sorted(r.items())))
    miss = missing(docker_text, allow)
    ok(not miss, 'все чтения rules/* есть в образе' + ('' if not miss else ': ' + '; '.join(f'{a} {b} — {c}' for a, b, c in miss)))
    ok('improve-rooms.json' in rules_in_image(cps), 'improve-rooms.json в /app/rules/ (07.11)')

    print('COPY ↔ git ↔ белый список:')
    for srcs, dst in cps:
        for s in srcs:
            p = os.path.join(ROOT, s)
            ok(os.path.exists(p), f'{s} есть в дереве')
            ok(whitelisted(s, allow), f'{s} в Dockerfile.dockerignore')

    print('проверка ловит подложенное:')
    old = docker_text.replace(' \\\n     tools/scout/rules/improve-rooms.json /app/rules/', ' /app/rules/')
    ok(old != docker_text, 'подложенный Dockerfile без improve-rooms.json собран')
    ok(any(b == 'improve-rooms.json' for _, b, _ in missing(old, allow)), 'Dockerfile без improve-rooms.json — отказ')
    ok(any(b == 'improve-rooms.json' and 'dockerignore' in c for _, b, c in
           missing(docker_text, [a for a in allow if 'improve-rooms' not in a])), 'белый список без improve-rooms.json — отказ')

    print('итог:', 'OK' if not BAD else f'FAIL ({len(BAD)})')
    return 1 if BAD else 0


if __name__ == '__main__':
    sys.exit(main())
