"""Ночной путь сборки и публикации демо не пишет в жёсткий /tmp (T-20261107-02).
/tmp на DEV — tmpfs с квотой на пользователя (~788 МБ), забитый чужим; ночью 07.11 `demo_rt.sh` писал вывод выкладки
в `/tmp/demo_rt_pub.$$`, упал на EDQUOT, и демо не опубликовалось. Теперь временное — в REMLAB_TMP на диске
(`tools/ops/remlab-tmp.sh`), а `refresh_daily.sh` экспортирует TMPDIR=REMLAB_TMP для python/node/Chromium внутри.
Проверяем:
- в скриптах ночного пути демо нет жёсткого `/tmp/…` и `…:-/tmp}` вне комментариев (исключение — PUB_RTMP: это /tmp
  СЕРВЕРА, куда scp кладёт архив, не DEV), и нет `mktemp` без папки (`-p` или шаблон с путём);
- `refresh_daily.sh` подключает remlab-tmp.sh и экспортирует TMPDIR ДО первого шага; `demo_rt.sh` пишет через mktemp
  в REMLAB_TMP и убирает свой файл (trap);
- сама проверка ловит подложенный жёсткий /tmp и mktemp без папки (иначе тест мог бы молча ничего не находить).
    python3 tools/scout/tests/test_no_hard_tmp.py"""
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..'))
# refresh_daily.sh и то, что он вызывает для демо (шаги flat215_demo … demo_live), плюс общий помощник
FILES = [
    'tools/scout/refresh_daily.sh',
    'tools/scout/flat215_demo.py',
    'tools/flat3d/demo-cams.mjs',
    'tools/assets/demo_rt.sh',
    'tools/assets/runtime_mesh.py',
    'tools/assets/publish_rt.sh',
    'tools/scout/publish_demo.sh',
    'tools/scout/scene_artifacts.py',
    'tools/ops/demo-warm.sh',
    'tools/ops/demo-warm.mjs',
    'tools/ops/demo-real.sh',
    'tools/ops/demo-realistic.mjs',
    'tools/ops/demo-live.sh',
    'tools/ops/node-env.sh',
    'tools/ops/remlab-tmp.sh',
    # ночь вне демо (T-20261107-02/2): шаг dev_checks в refresh_daily и отдельный крон ночного экзамена
    'tools/ops/dev-checks.sh',
    'tools/scout/nightly_exam.sh',
]
# разрешённое: /tmp СЕРВЕРА для архивов (scp на прод) — не DEV; замер занятости /tmp в dev-checks (только чтение)
ALLOW = ['${PUB_RTMP:-/tmp}', '${GAL_RTMP:-/tmp}', 'du -sk /tmp/* /tmp/.[!.]*']
HARD = re.compile(r'(?<![\w.~$}-])/tmp/|:-/tmp\}|["\']/tmp["\']')
MKTEMP = re.compile(r'\bmktemp\b(?P<rest>[^\n)]*)')
BAD = []


def ok(cond, msg):
    print(('  ok  ' if cond else '  FAIL ') + msg)
    if not cond:
        BAD.append(msg)


def code_part(line, ext):
    """Строка без комментария: целиком-комментарий → пусто; хвостовой — по « # » / « // »."""
    s = line.strip()
    if ext == '.mjs':
        if s.startswith('//') or s.startswith('*') or s.startswith('/*'):
            return ''
        return line.split(' // ')[0]
    if s.startswith('#'):
        return ''
    return line.split(' # ')[0]


def scan(text, ext):
    """Нарушения: [(номер строки, строка)]."""
    out = []
    for i, line in enumerate(text.splitlines(), 1):
        c = code_part(line, ext)
        for a in ALLOW:
            c = c.replace(a, '')
        if HARD.search(c):
            out.append((i, line.strip()))
            continue
        if ext == '.sh':
            for m in MKTEMP.finditer(c):
                rest = m.group('rest')
                if not re.search(r'(^|\s)-p\s|/|"\$|\$\{?\w', rest):
                    out.append((i, line.strip()))
    return out


def main():
    print('ночной путь демо — без жёсткого /tmp:')
    for rel in FILES:
        p = os.path.join(ROOT, rel)
        if not os.path.exists(p):
            ok(False, f'{rel}: файла нет (список устарел)')
            continue
        with open(p, encoding='utf-8') as f:
            bad = scan(f.read(), os.path.splitext(p)[1])
        ok(not bad, f'{rel}' + ('' if not bad else ': ' + '; '.join(f'{n}: {s[:120]}' for n, s in bad)))

    print('TMPDIR и REMLAB_TMP:')
    rd = open(os.path.join(ROOT, 'tools/scout/refresh_daily.sh'), encoding='utf-8').read()
    first_step = rd.find('\nstep ')
    i_src, i_exp = rd.find('. ../ops/remlab-tmp.sh'), rd.find('export TMPDIR="$REMLAB_TMP"')
    ok(0 < i_src < i_exp < first_step, 'refresh_daily: remlab-tmp.sh и export TMPDIR — до первого шага')
    ok('свободно в /tmp' in rd and 'в REMLAB_TMP' in rd, 'refresh_daily: строка в лог «свободно в /tmp и в REMLAB_TMP»')
    rt = open(os.path.join(ROOT, 'tools/assets/demo_rt.sh'), encoding='utf-8').read()
    ok('mktemp -p "$REMLAB_TMP"' in rt and re.search(r"trap 'rm -f \"\$PUB_LOG\"' EXIT", rt) is not None,
       'demo_rt: временный файл в REMLAB_TMP, свой убирается (trap)')
    ne = open(os.path.join(ROOT, 'tools/scout/nightly_exam.sh'), encoding='utf-8').read()
    ok('mktemp -p "$REMLAB_TMP" acc-gallery' in ne and "trap 'rm -f \"$GAL_TGZ\"' EXIT" in ne,
       'nightly_exam: архив галереи в REMLAB_TMP, убирается trap и при упавшем scp')
    dc = open(os.path.join(ROOT, 'tools/ops/dev-checks.sh'), encoding='utf-8').read()
    ok('mktemp -p "$REMLAB_TMP" llm-probe' in dc, 'dev-checks: ответ пробы LLM в REMLAB_TMP')

    print('помощник remlab-tmp.sh:')
    with tempfile.TemporaryDirectory() as t:
        want = os.path.join(t, 'a', 'b')
        r = subprocess.run(['bash', '-c', '. tools/ops/remlab-tmp.sh; echo "$REMLAB_TMP"; remlab_tmp_free "$REMLAB_TMP"'],
                           cwd=ROOT, env={**os.environ, 'REMLAB_TMP': want}, capture_output=True, text=True)
        lines = r.stdout.split()
        ok(r.returncode == 0 and lines[:1] == [want] and os.path.isdir(want), 'REMLAB_TMP из окружения, папка создана')
        ok(len(lines) == 2 and lines[1].isdigit(), f'remlab_tmp_free даёт МБ ({r.stdout.strip()!r})')
        home = os.path.join(t, 'home')
        os.makedirs(home)
        env = {k: v for k, v in os.environ.items() if k != 'REMLAB_TMP'}
        r = subprocess.run(['bash', '-c', '. tools/ops/remlab-tmp.sh; echo "$REMLAB_TMP"'],
                           cwd=ROOT, env={**env, 'HOME': home}, capture_output=True, text=True)
        ok(r.stdout.strip() == os.path.join(home, 'remlab-scratch', 'tmp'), 'по умолчанию — ~/remlab-scratch/tmp')

    print('demo_rt.sh на подставном дереве (без сети и выкладки):')
    for rc_pub in (0, 1):
        with tempfile.TemporaryDirectory() as t:
            rem, home = os.path.join(t, 'rtmp'), os.path.join(t, 'home')
            for d in ('tools/assets', 'tools/ops', 'data/flat3d', 'bin'):
                os.makedirs(os.path.join(t, 'tree', d), exist_ok=True)
            os.makedirs(home)
            tree = os.path.join(t, 'tree')
            for rel in ('tools/assets/demo_rt.sh', 'tools/ops/remlab-tmp.sh'):
                with open(os.path.join(ROOT, rel), encoding='utf-8') as f, open(os.path.join(tree, rel), 'w', encoding='utf-8') as g:
                    g.write(f.read())
            with open(os.path.join(tree, 'tools/assets/publish_rt.sh'), 'w') as g:
                g.write(f'echo выкладываю 3 моделей; echo строка-2; echo готово-или-нет; exit {rc_pub}\n')
            py = os.path.join(tree, 'bin', 'py')
            with open(py, 'w') as g:   # подставной python: проверка прода (heredoc) — «не хватает 0», остальное — успех
                g.write('#!/bin/bash\n[ "${1:-}" = "-" ] && { cat >/dev/null; echo "0 "; }\nexit 0\n')
            os.chmod(py, 0o755)
            open(os.path.join(tree, 'data/flat3d/runtime-meshes.json'), 'w').write('{}')
            env = {**os.environ, 'HOME': home, 'REMLAB_TMP': rem, 'PY': py, 'DEMO_DATA': os.path.join(t, 'demo-data.json'),
                   'RT_MANIFEST': os.path.join(t, 'rt.json'), 'RT_OUT': os.path.join(t, 'rt'), 'RT_TABLE_OUT': os.path.join(t, 'tab.json')}
            r = subprocess.run(['bash', os.path.join(tree, 'tools/assets/demo_rt.sh')], env=env, capture_output=True, text=True)
            out = r.stdout + r.stderr
            left = os.listdir(rem) if os.path.isdir(rem) else None
            if rc_pub == 0:
                ok(r.returncode == 0 and 'готово-или-нет' in out, f'выкладка прошла: код 0, хвост вывода в логе ({out.strip()[-120:]!r})')
            else:
                ok(r.returncode == 1 and 'выкладка копий на /rt/ не прошла' in out and 'выкладываю 3' in out,
                   f'выкладка упала: код 1, хвост из 3 строк ({out.strip()[-160:]!r})')
            ok(left == [], f'временный файл убран из REMLAB_TMP (осталось {left})')

    print('проверка ловит подложенное:')
    planted = ['x > /tmp/demo_rt_pub.$$ 2>&1', 'D=${TMPDIR:-/tmp}', 'F=$(mktemp)', 'F=$(mktemp -d)', "cd '/tmp'"]
    for s in planted:
        ok(bool(scan(s, '.sh')), f'поймано: {s}')
    ok(bool(scan("const d = '/tmp/x';", '.mjs')), "поймано (.mjs): '/tmp/x'")
    fine = ['# пишет в /tmp/x — комментарий', 'scp a "$HOST:${PUB_RTMP:-/tmp}/f"', 'F=$(mktemp -p "$REMLAB_TMP" a.XXXXXX)',
            'T=$(mktemp "$PUB_TMP/x.XXXX.tgz")', 'echo "свободно в /tmp $(df -Pm /tmp)"', 'cmd  # в /tmp/x не пишем']
    for s in fine:
        ok(not scan(s, '.sh'), f'не ложная тревога: {s}')

    print('итог:', 'OK' if not BAD else f'FAIL ({len(BAD)})')
    return 1 if BAD else 0


if __name__ == '__main__':
    sys.exit(main())
