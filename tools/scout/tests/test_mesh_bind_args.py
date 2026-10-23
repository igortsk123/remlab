"""`mesh_bind.py` с неизвестным ключом — отказ rc≠0 БЕЗ обращения к базе (T-20261023-10). Без сети и базы.

23.10 `mesh_bind.py --selftest` (самопроверки у скрипта нет) прошёл полной пометкой и привязкой по рабочей базе — как
запуск без ключей. Проверяем настоящим запуском: в PATH подложен `docker`, который только отмечает вызов (база — `docker exec
… psql`), и `psql` на случай прямого вызова.
  1) `--selftest`, `--dry`, `--reprot` → rc 2, в stderr «неизвестный ключ», к базе ни одного вызова;
  2) смесь `--report --dry` — тоже отказ (известный ключ рядом с опечаткой не спасает);
  3) `--report` и запуск без ключей до базы доходят (заглушка вызвана) — отказ не задел штатные пути.
    python3 tools/scout/tests/test_mesh_bind_args.py"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, '..', 'mesh_bind.py')
fails = 0


def check(name, cond, extra=''):
    global fails
    print(('OK   ' if cond else 'FAIL ') + name + (f' — {extra}' if extra and not cond else ''))
    fails += 0 if cond else 1


def run(args):
    with tempfile.TemporaryDirectory(prefix='mesh-bind-args-') as td:
        mark = os.path.join(td, 'calls')
        for tool in ('docker', 'psql'):
            p = os.path.join(td, tool)
            # заглушка базы: отмечает вызов и падает — штатный путь дальше первого запроса не пойдёт
            open(p, 'w').write(f'#!/bin/sh\necho "{tool} $*" >> "{mark}"\necho "заглушка: базы нет" >&2\nexit 1\n')
            os.chmod(p, 0o755)
        r = subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True, timeout=120,
                           env={**os.environ, 'PATH': td + os.pathsep + os.environ.get('PATH', '')})
        calls = open(mark).read().splitlines() if os.path.exists(mark) else []
        return r.returncode, r.stderr, calls


for args in (['--selftest'], ['--dry'], ['--reprot'], ['--report', '--dry']):
    rc, err, calls = run(args)
    check(f'{" ".join(args)}: отказ rc=2, «неизвестный ключ», к базе не обращался',
          rc == 2 and 'неизвестный ключ' in err and not calls, f'rc={rc} вызовов={len(calls)} {err[-160:]}')

for args in (['--report'], []):
    rc, err, calls = run(args)
    check(f'{" ".join(args) or "без ключей"}: штатный путь — до базы дошёл (заглушка вызвана)',
          bool(calls) and 'неизвестный ключ' not in err, f'rc={rc} вызовов={len(calls)}')

print('test_mesh_bind_args:', 'FAIL' if fails else 'OK')
sys.exit(1 if fails else 0)
