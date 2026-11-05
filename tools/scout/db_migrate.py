#!/usr/bin/env python3
"""Применение SQL-миграций каталога к дев-БД `remlab-devdb`.

Каталог живёт только на дев-машине, а `db/init/*.sql` в репозитории применяется `deploy.sh` к
ПРОДОВОЙ базе, где таблицы `products` нет вовсе. Поэтому миграции каталога лежат рядом со
скриптами каталога и применяются отсюда (обоснование — план [[catalog-delta-lifecycle]]).

Применяются ТОЛЬКО пронумерованные файлы `NNN-*.sql` — `bootstrap.sql` (первичная схема и view
`lr_roles`) миграцией не является и запускается руками: попытка прогнать его поверх живой базы
падает на переименовании колонок view.

Все миграции обязаны быть идемпотентными (`if not exists`): гоняются столько раз, сколько нужно.

БЕЗ ПАУЗЫ КРОНОВ — ОТКАЗ (onb-12, ADR-0330 п.6): миграция под работающим ночным циклом и без копии базы — то, от чего
защищает `tools/ops/db-migrate-safe.sh` (пауза → дамп → SQL одной транзакцией → журнал). Здесь миграция идёт, только если
пауза обслуживания действует (`tools/ops/cron-pause.sh on`, метка — как читает `tools/ops/maintenance.sh:maint_active`), или
запуск — из `db-migrate-safe.sh` (переменная `REMLAB_MIGRATE_SAFE=1`), или явно `--unsafe-no-pause` (строка WARN в лог).

  tools/ops/db-migrate-safe.sh tools/scout/NNN-x.sql    # обычный путь: пауза, копия, откат
  ~/venvs/scout/bin/python db_migrate.py              # применить все NNN-*.sql (под паузой)
  ~/venvs/scout/bin/python db_migrate.py enrichment   # только один файл
  ~/venvs/scout/bin/python db_migrate.py --unsafe-no-pause [файл]   # без паузы — сознательно, с WARN
  python tools/scout/db_migrate.py --selftest         # проверка допуска на временной папке — базу не трогает
"""
import glob
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PSQL = ['docker', 'exec', '-i', 'remlab-devdb', 'psql', '-U', 'remlab', '-d', 'remlab',
        '-q', '-v', 'ON_ERROR_STOP=1']
SAFE_ENV = 'REMLAB_MIGRATE_SAFE'
UNSAFE_FLAG = '--unsafe-no-pause'


def maint_dir(env: dict) -> str:
    return env.get('REMLAB_MAINT_DIR') or os.path.join(os.path.expanduser('~'), '.cache', 'remlab')


def pause_active(mdir: str, now: float | None = None) -> str:
    """Пауза обслуживания действует? Как `maintenance.sh:maint_active`: метка `maintenance.pause`, срок — первая строка
    `until=<epoch>`; срока нет (правлена руками) — 6 ч от записи метки. Действует — «до …; причина …», нет или истекла — ''."""
    path = os.path.join(mdir, 'maintenance.pause')
    if not os.path.isfile(path):
        return ''
    kv: dict = {}
    for line in open(path, encoding='utf-8', errors='replace'):
        k, _, v = line.rstrip('\n').partition('=')
        kv.setdefault(k, v)
    until_s = kv.get('until', '')
    until = int(until_s) if until_s.isdigit() else int(os.stat(path).st_mtime) + 6 * 3600
    if (time.time() if now is None else now) >= until:
        return ''
    return f"до {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(until))}; причина: {kv.get('reason') or 'не указана'}"


def gate(argv: list, env: dict, now: float | None = None) -> tuple:
    """Можно ли катить → (да/нет, строка в лог). Порядок: запуск из db-migrate-safe.sh → действующая пауза → явный флаг."""
    if env.get(SAFE_ENV) == '1':
        return True, 'запуск из db-migrate-safe.sh — пауза и копия базы на нём'
    why = pause_active(maint_dir(env), now)
    if why:
        return True, f'пауза обслуживания {why}'
    if UNSAFE_FLAG in argv:
        return True, (f'WARN:db_migrate: {UNSAFE_FLAG} — миграция БЕЗ паузы кронов и без копии базы '
                      '(обычный путь — tools/ops/db-migrate-safe.sh)')
    return False, ('ОТКАЗ: пауза кронов не стоит — миграция под ночным циклом и без копии базы. Обычный путь: '
                   'tools/ops/db-migrate-safe.sh <файл.sql> (пауза, дамп, откат); сознательно без паузы — '
                   f'{UNSAFE_FLAG}')


def apply(path: str) -> None:
    sql = open(path).read()
    r = subprocess.run(PSQL, input=sql, capture_output=True, text=True)
    name = os.path.basename(path)
    if r.returncode != 0:
        print(f'{name}: ОШИБКА\n{r.stderr[:800]}')
        sys.exit(1)
    print(f'{name}: применена')


def main(argv: list, env: dict, run=apply) -> int:
    args = [a for a in argv if not a.startswith('--')]
    only = args[0] if args else None
    files = sorted(glob.glob(os.path.join(HERE, '[0-9][0-9][0-9]-*.sql')))
    if only:
        files = [f for f in files if only in os.path.basename(f)]
    if not files:
        print('нет .sql для применения')
        return 0
    ok, line = gate(argv, env)
    print(line, file=sys.stderr if line.startswith(('WARN', 'ОТКАЗ')) else sys.stdout, flush=True)
    if not ok:
        return 2
    for f in files:
        run(f)
    return 0


def _selftest() -> int:
    bad = 0

    def ok(cond: bool, name: str) -> None:
        nonlocal bad
        print(('OK   ' if cond else 'FAIL ') + name)
        bad += 0 if cond else 1

    tmp = tempfile.mkdtemp(prefix='db-migrate-selftest.')
    env = {'REMLAB_MAINT_DIR': tmp}
    pause = os.path.join(tmp, 'maintenance.pause')
    now = time.time()
    calls: list = []
    run = calls.append

    ok(main(['enrichment'], env, run) == 2 and not calls, 'нет паузы — отказ (код 2), миграции не звали')
    ok(not gate([], env)[0] and 'db-migrate-safe.sh' in gate([], env)[1], 'отказ подсказывает обычный путь db-migrate-safe.sh')
    with open(pause, 'w') as fh:
        fh.write(f'until={int(now) + 3600}\nsince=x\nreason=миграция 015\n')
    ok(main(['enrichment'], env, run) == 0 and len(calls) == 1, 'пауза стоит — миграция идёт')
    ok('миграция 015' in gate([], env)[1], 'в лог — причина паузы')
    with open(pause, 'w') as fh:
        fh.write(f'until={int(now) - 10}\nreason=забыта\n')
    ok(not gate([], env)[0], 'пауза истекла — отказ, как у maint_active')
    with open(pause, 'w') as fh:
        fh.write('reason=руками, без срока\n')
    ok(gate([], env)[0] and not gate([], env, now + 7 * 3600)[0], 'метка без срока — 6 ч от записи, потом отказ')
    os.replace(pause, pause + '.off')
    calls.clear()
    ok(main(['enrichment'], {**env, SAFE_ENV: '1'}, run) == 0 and len(calls) == 1, 'запуск из db-migrate-safe.sh — без паузы пускаем')
    ok(not gate([], {**env, SAFE_ENV: '0'})[0], 'переменная не «1» — отказ')
    calls.clear()
    allowed, line = gate([UNSAFE_FLAG], env)
    ok(allowed and line.startswith('WARN:db_migrate:'), f'{UNSAFE_FLAG} — пускаем со строкой WARN')
    ok(main([UNSAFE_FLAG, 'enrichment'], env, run) == 0 and len(calls) == 1 and 'enrichment' in calls[0],
       'флаг не считается именем файла: катится только выбранная миграция')
    print(f'(временная папка {tmp})')
    return 1 if bad else 0


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        sys.exit(_selftest())
    sys.exit(main(sys.argv[1:], dict(os.environ)))
