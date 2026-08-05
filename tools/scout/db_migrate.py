#!/usr/bin/env python3
"""Применение SQL-миграций каталога к дев-БД `remlab-devdb`.

Каталог живёт только на дев-машине, а `db/init/*.sql` в репозитории применяется `deploy.sh` к
ПРОДОВОЙ базе, где таблицы `products` нет вовсе. Поэтому миграции каталога лежат рядом со
скриптами каталога и применяются отсюда (обоснование — план [[catalog-delta-lifecycle]]).

Применяются ТОЛЬКО пронумерованные файлы `NNN-*.sql` — `bootstrap.sql` (первичная схема и view
`lr_roles`) миграцией не является и запускается руками: попытка прогнать его поверх живой базы
падает на переименовании колонок view.

Все миграции обязаны быть идемпотентными (`if not exists`): гоняются столько раз, сколько нужно.

  ~/venvs/scout/bin/python db_migrate.py              # применить все NNN-*.sql
  ~/venvs/scout/bin/python db_migrate.py enrichment   # только один файл
"""
import glob
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PSQL = ['docker', 'exec', '-i', 'remlab-devdb', 'psql', '-U', 'remlab', '-d', 'remlab',
        '-q', '-v', 'ON_ERROR_STOP=1']


def apply(path: str) -> None:
    sql = open(path).read()
    r = subprocess.run(PSQL, input=sql, capture_output=True, text=True)
    name = os.path.basename(path)
    if r.returncode != 0:
        print(f'{name}: ОШИБКА\n{r.stderr[:800]}')
        sys.exit(1)
    print(f'{name}: применена')


def main() -> None:
    only = sys.argv[1] if len(sys.argv) > 1 else None
    files = sorted(glob.glob(os.path.join(HERE, '[0-9][0-9][0-9]-*.sql')))
    if only:
        files = [f for f in files if only in os.path.basename(f)]
    if not files:
        print('нет .sql для применения')
        return
    for f in files:
        apply(f)


if __name__ == '__main__':
    main()
