#!/usr/bin/env python3
"""Тест гарда конвейера `guard_conveyor.py` (T-20261112-121 шаг 3). Запуск: python3 tools/hooks/guard_conveyor_test.py
Реестр — настоящий (`tools/ops/conveyor-manifest.yml`); случаи — в файле, не в командной строке (иначе гард в сессии
заблокировал бы сам запуск теста). Ссылки worktree → живой банк — настоящие, во временной папке."""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import guard_conveyor as G  # noqa: E402

M = G.load()
MAIN = '/home/x/remlab'                        # основная копия (живые банки DEV)
W = f'{MAIN}/.claude/worktrees/w1'             # worktree
FUR = 'data/flat3d/furniture.json'
BANK = 'tools/scout/sets3.json'
GT = '>'   # символ записи — переменной, чтобы строки случаев читались одинаково
Q3 = "'" * 3

EDIT = [   # (инструмент, путь, ожидание: True — отказ)
    ('Edit', f'{W}/{FUR}', True),                     # собранный файл в git — в любой копии
    ('Write', f'{MAIN}/{BANK}', True),                # живой банк
    ('MultiEdit', f'{W}/data/partners/kitchen-fit/flat215.json', True),
    ('Write', os.path.expanduser('~/scout-scenes/flat215-demo/demo-data.json'), True),
    ('Edit', f'{W}/{BANK}', False),                   # своя копия живого банка в worktree (не ссылка) — не живой
    ('Edit', f'{W}/tools/flat3d/build-catalogue.mjs', False),     # генератор правят — это и есть вход
    ('Edit', f'{W}/tools/scout/flat215.json', False),             # тёзка kitchen-fit/flat215.json — другой файл
    ('Write', f'{W}/tools/scout/rules/bank-candidate.json', False),
    ('Edit', f'{MAIN}/tools/scout/sets3.json.bak', False),
    ('Read', f'{W}/{FUR}', False),
]

BASH = [   # (команда, cwd, ожидание)
    (f'cat x.json {GT} {FUR}', W, True),
    (f'jq . a.json {GT}{GT} {W}/{FUR}', '/tmp', True),
    (f'echo [] | tee {BANK}', MAIN, True),
    (f'cp /tmp/new.json "$HOME/igor/remlab/{BANK}"', W, True) if os.path.expanduser('~') == '/home/pakar' else ('true', W, False),
    (f'cd tools/scout && cp /tmp/n.json sets3.json', MAIN, True),   # путь — от папки после cd
    (f'cd /tmp && cp /tmp/n.json sets3.json', MAIN, False),
    (f'cp /tmp/n.json sets3.json', f'{MAIN}/tools/scout', True),
    (f'cp /tmp/n.json sets3.json', f'{W}/tools/scout', False),     # своя копия в worktree
    (f'mv /tmp/n.json {FUR}', W, True),
    (f"sed -i 's/a/b/' {FUR}", W, True),
    (f'rm -f {BANK}', MAIN, True),
    (f'dd if=/dev/zero of={FUR} bs=1 count=1', W, True),
    (f"python3 -c \"import json; json.dump({{}}, open('{FUR}', 'w'))\"", W, True),
    (f"python3 -c \"import json; p='{FUR}'; d=json.load(open(p)); d['x']=1; json.dump(d, open(p, 'w'))\"", W, True),
    (f"python3 -c \"import json; d=json.load(open('{FUR}')); json.dump(d, open('/tmp/x.json', 'w'))\"", W, False),  # читает собранный, пишет другой
    (f"cat {GT} {FUR} <<'EOF'\n{{}}\nEOF", W, True),
    (f"python3 - <<'EOF'\nimport json\njson.dump({{}}, open('{FUR}', 'w'))\nEOF", W, True),      # код в heredoc
    (f"python3 - <<'EOF'\np='tools/ops/demo-realistic.mjs'; s=open(p).read()\ns=s.replace({Q3}--force all{Q3}, {Q3}--force x{Q3})\n"
     f"open(p,'w').write(s)\nEOF\nnode --check tools/ops/demo-realistic.mjs && echo ok", W, False),  # правка кода — не обход
    (f"python3 - <<'EOF'\np='tools/assets/material_pipeline.py'; s=open(p).read()\n"
     f"s=s.replace({Q3}json.dump(m, open('data/flat3d/materials.json', 'w')){Q3}, {Q3}dump_sealed(m, P){Q3})\nopen(p,'w').write(s)\nEOF", W, False),
    (f"python3 - $B <<'EOF'\nimport json, os, sys\nout = os.path.join(sys.argv[1], 'stage', 'demo-data.json')\n"
     "json.dump({}, open(out, 'w'))\nEOF", W, False),   # копия в папку из аргумента — место неизвестно
    ("python3 - <<'EOF'\nimport json, os\np = os.path.expanduser('~/scout-scenes/flat215-demo/demo-data.json')\n"
     "d = json.load(open(p))\nd['x'] = 1\njson.dump(d, open(p, 'w'))\nEOF", W, True),   # правка живых данных витрины
    (f"cd tools/scout && python3 - <<'EOF'\nfrom pathlib import Path\nPath('sets3.json').write_text('[]')\nEOF", MAIN, True),
    (f'bash -c "cat a {GT} {FUR}"', W, True),
    (f'node tools/flat3d/build-catalogue.mjs --out {FUR}', W, False),   # генератор пишет сам
    (f'node tools/flat3d/build-catalogue.mjs {GT} {FUR}', W, False),    # … и через вывод
    ('rm -f data/flat3d/materials.json && python tools/assets/material_pipeline.py --all', W, False),
    ('python tools/assets/opening_golden.py', W, False),
    (f'cp {BANK} $D/sets3.json', MAIN, False),          # снимок банка в НОВУЮ папку
    (f'cp {BANK} /tmp/snap/', MAIN, False),
    (f'grep -c tintRgb {FUR}', W, False),
    (f'git diff {FUR} {GT} /tmp/d.txt', W, False),
    (f'python3 tools/scout/judge.py 2{GT}&1 | tee /tmp/log.txt', W, False),
    (f"git commit -m 'не править {FUR} руками: cat {GT} {FUR}'", W, False),   # текст в кавычках — не команда
    (f'git commit -q -m "заголовок\n\ncat {GT} {FUR} — так нельзя\n"', W, False),   # многострочный текст коммита
    (f"cat {GT} /tmp/m.txt <<'EOF'\ncp a {FUR}\nEOF", W, False),            # тело heredoc у cat — данные
    # обходы force_guard
    ('python3 tools/scout/bank_promote.py --force', W, True),
    ('cd tools/scout && ~/venvs/scout/bin/python bank_promote.py --room bedroom --no-exam', W, True),
    ('python tools/scout/bank_promote.py --force-ready 1,2', W, True),
    ('bash tools/scout/refresh_daily.sh --force', MAIN, True),
    ('node tools/ops/demo-realistic.mjs --go --force photo', W, True),
    ('for st in a b; do timeout 900 node tools/ops/demo-realistic.mjs --force $st --go; done', W, True),
    ('python3 tools/scout/bank_refresh.py --force', W, True),
    ('cd $R/repo/tools/scout && python3 bank_promote.py --force', W, False),   # песочница по переменной — место неизвестно
    ('python3 tools/scout/bank_promote.py --dry', W, False),
    ('git push --force-with-lease origin x', W, False),
    ('python3 tools/scout/img_alive.py --scan --force', W, False),   # не из force_guard
    ("git commit -m 'bank_promote.py --force — запрещено'", W, False),
    ('python3 tools/scout/bank_promote.py --selftest', W, False),
]


def main():
    bad = 0

    def ok(cond, name):
        nonlocal bad
        print(('OK   ' if cond else 'FAIL ') + name)
        bad += 0 if cond else 1

    for tool, p, want in EDIT:
        got = G.decide({'tool_name': tool, 'tool_input': {'file_path': p}, 'cwd': W}, M) is not None
        ok(got == want, f'{tool} {p.replace(W, "<w>").replace(MAIN, "<main>")} → {"отказ" if want else "пропуск"}')
    for cmd, cwd, want in BASH:
        got = G.decide({'tool_name': 'Bash', 'tool_input': {'command': cmd}, 'cwd': cwd}, M) is not None
        ok(got == want, f'Bash [{cwd.replace(W, "<w>").replace(MAIN, "<main>")}] {cmd.splitlines()[0][:90]} → {"отказ" if want else "пропуск"}')
    # ссылка worktree → живой банк основной копии: запись через неё — живой; убрать/поставить ссылку — нет
    with tempfile.TemporaryDirectory() as d:
        live = os.path.join(d, 'main', 'tools', 'scout', 'sets3.json')
        wt = os.path.join(d, 'main', '.claude', 'worktrees', 'w2', 'tools', 'scout')
        os.makedirs(os.path.dirname(live))
        os.makedirs(wt)
        open(live, 'w').write('[]')
        os.symlink(live, os.path.join(wt, 'sets3.json'))
        dec = lambda c: G.decide({'tool_name': 'Bash', 'tool_input': {'command': c}, 'cwd': wt}, M) is not None
        ok(dec('cp /tmp/n.json sets3.json'), 'ссылка worktree → живой банк: cp в неё — отказ')
        ok(not dec('rm sets3.json'), 'ссылка worktree → живой банк: rm ссылки — пропуск')
        ok(not dec(f'ln -sf {live} sets3.json'), 'ссылка worktree → живой банк: ln -sf ссылки — пропуск')
        ok(G.decide({'tool_name': 'Write', 'tool_input': {'file_path': os.path.join(wt, 'sets3.json')}, 'cwd': wt}, M) is not None,
           'ссылка worktree → живой банк: Write в неё — отказ')
    # процесс: код выхода и причина
    run = lambda d: subprocess.run([sys.executable, os.path.join(HERE, 'guard_conveyor.py')], input=d, capture_output=True, text=True)
    r = run(json.dumps({'tool_name': 'Edit', 'tool_input': {'file_path': f'{ROOT}/{FUR}'}, 'cwd': ROOT}))
    ok(r.returncode == 2 and 'build-catalogue.mjs' in r.stderr, 'процесс: отказ — код 2 и генератор в причине')
    r = run(json.dumps({'tool_name': 'Bash', 'tool_input': {'command': 'ls'}, 'cwd': ROOT}))
    ok(r.returncode == 0 and not r.stderr, 'процесс: обычная команда — код 0')
    r = run('не json')
    ok(r.returncode == 0, 'процесс: непонятный ввод — fail-open, код 0')
    print(f'guard_conveyor: ошибок {bad}')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
