"""Образ запасного рендера (`infra/draft/Dockerfile`) несёт все файлы правил, которые читает его код (T-20261107-03).
07.11 фото спальни ушло на запасной рендер прода (DEV-рендер снял earlyoom) и упало «No such file /app/rules/improve-rooms.json»:
файл добавили в код (T-32/3, `improve_mode.room_rules`), а в COPY образа — нет. Сборка этого не ловила: файл читается лениво,
при первом фото не-гостиной, а проверка образа — только импорты.
Проверяем по тексту, без docker:
- каждый модуль, который Dockerfile кладёт в /app (scout поштучно, планировщик папкой), — чтения `rules/<файл>` (`'rules', '<файл>'` в коде, не в комментарии):
  файл должен быть в COPY → /app/rules/ (из tools/scout/rules или целиком services/planner-solver/rules) И в белом списке
  `Dockerfile.dockerignore` (иначе его нет в контексте сборки); исключение — OPTIONAL с причиной (чтение в try/except с запасом);
- всё, что Dockerfile копирует, есть в git-дереве и в белом списке (рассинхрон COPY ↔ белый список роняет сборку);
- проверка ловит подложенное: Dockerfile без improve-rooms.json даёт отказ;
- ОБРАЗ КАК ЕСТЬ (T-20261107-07): файл в образе есть, но код мог искать его не там (приоры практики искались в
  /tools/scout/rules/ и молча были пустыми). Раскладываем COPY во временную папку и из неё, без репо в sys.path, читаем приоры;
- модули планировщика не ходят за файлами наружу пакета (`'tools', 'scout'`), кроме белого списка с причиной.
Нужны зависимости планировщика (shapely, pydantic) — запускается в CI-джобе `planner`.
    python3 tools/scout/tests/test_draft_image_rules.py"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))  # tools/scout — помощник временного
import remlab_tmp  # noqa: E402
remlab_tmp.use('test_draft_image_rules')  # временное теста — на диске, не в /tmp; папка убирается при выходе (T-20261107-13)

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


PLANNER = os.path.join(ROOT, 'services', 'planner-solver', 'planner')
# модули планировщика, которым можно искать файл вне пакета: причина — почему образ от этого не страдает
OUTSIDE_OK = {
    'llm_planner.py': 'tools/scout/.env с ключом; модуля нет среди импортов образа, ключ — env OPENAI_ENV/OPENAI_API_KEY',
    'opportunities.py': 'tools/scout/rules — третий, запасной путь (DEV/репо); первым ищет env и rules/ рядом с пакетом = /app/rules',
}
OUTSIDE = re.compile(r"""['"]tools['"]\s*,\s*['"]scout['"]|['"][^'"\n]*\btools/scout/""")


def outside_paths():
    """[(модуль:строка)] — пути наружу пакета планировщика в коде (не в комментариях)."""
    out = []
    for f in sorted(os.listdir(PLANNER)):
        if not f.endswith('.py'):
            continue
        with open(os.path.join(PLANNER, f), encoding='utf-8') as fh:
            for n, line in enumerate(fh, 1):
                if line.strip().startswith('#'):
                    continue
                if OUTSIDE.search(line.split('  # ')[0]):
                    out.append((f, n))
    return out


def lay_out_image(docker_text, dst_root):
    """COPY Dockerfile → папка как в образе (`/app/...` → `<dst_root>/app/...`)."""
    for srcs, dst in copies(docker_text):
        base = os.path.join(dst_root, dst.lstrip('/'))
        for s in srcs:
            p = os.path.join(ROOT, s)
            if os.path.isdir(p):
                shutil.copytree(p, base, dirs_exist_ok=True)
            else:
                os.makedirs(base if dst.endswith('/') else os.path.dirname(base), exist_ok=True)
                shutil.copy2(p, os.path.join(base, os.path.basename(s)) if dst.endswith('/') else base)


PROBE = r"""
import json, sys
sys.path.insert(0, sys.argv[1])
from planner import opportunities as o
p = o.priors()
print(json.dumps({'file': o.__file__, 'path': o.priors_path(),
                  'window': len(((p.get('opportunities') or {}).get('window') or {}).get('outcomes') or [])}))
"""


def image_priors(docker_text):
    """Приоры, как их видит код в раскладке образа: {file, path, window, err}."""
    tmp = tempfile.mkdtemp(prefix='draft-image-')
    try:
        root = os.path.join(tmp, 'a', 'b')          # глубже, чтобы ../../../tools/scout из /app/planner остался внутри tmp
        lay_out_image(docker_text, root)
        app = os.path.join(root, 'app')
        env = {k: v for k, v in os.environ.items() if k not in ('PRACTICE_PRIORS_PATH', 'PYTHONPATH')}
        r = subprocess.run([sys.executable, '-I', '-c', PROBE, app], cwd=app, env=env,
                           capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            return {'error': r.stderr[-400:]}
        out = json.loads(r.stdout.strip().splitlines()[-1])
        out['err'] = r.stderr
        out['app'] = app
        return out
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


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

    print('образ как есть — код находит приоры практики (T-20261107-07):')
    im = image_priors(docker_text)
    ok('error' not in im, 'проба в раскладке образа отработала' + (f": {im.get('error')}" if 'error' in im else ''))
    if 'error' not in im:
        ok(im['file'].startswith(im['app']), f"planner взят из раскладки образа, не из репо ({im['file']})")
        ok((im['path'] or '') == os.path.join(im['app'], 'rules', 'practice_priors.json'), f"файл найден в /app/rules ({im['path']})")
        ok(im['window'] > 0, f"исходов окна: {im['window']}")
        ok('не найдены' not in im['err'], 'без предупреждения «не найдены»')
    planted = docker_text.replace(' tools/scout/rules/practice_priors.json', '')
    ok(planted != docker_text, 'подложенный Dockerfile без practice_priors.json собран')
    ip = image_priors(planted)
    ok('error' not in ip and ip['window'] == 0 and 'приоры практики не найдены' in ip['err'],
       'без practice_priors.json — пусто И громко в stderr (не молча)')

    print('планировщик не ищет файлы вне пакета (кроме белого списка):')
    outs = outside_paths()
    bad = [f'{f}:{n}' for f, n in outs if f not in OUTSIDE_OK]
    ok(not bad, 'путей наружу вне белого списка нет' + ('' if not bad else ': ' + ', '.join(bad)))
    stale = sorted(set(OUTSIDE_OK) - {f for f, _ in outs})
    ok(not stale, 'белый список не устарел' + ('' if not stale else ': ' + ', '.join(stale)))
    for f, why in OUTSIDE_OK.items():
        print(f'       {f}: {why}')
    ok(bool(OUTSIDE.search("os.path.join(HERE, '..', 'tools', 'scout', 'rules', 'x.json')")), 'шаблон ловит подложенный путь наружу')

    print('итог:', 'OK' if not BAD else f'FAIL ({len(BAD)})')
    return 1 if BAD else 0


if __name__ == '__main__':
    sys.exit(main())
