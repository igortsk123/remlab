#!/usr/bin/env bash
# ЕДИНЫЙ прогонщик прод-схемы `db/init/NNN-*.sql`. Один порядок и одни правила для трёх путей:
# CI-гарда (job `db-init`), автодеплой (`infra/server/deploy-remote.sh`) и ручной `deploy.sh`.
#
# ЗАЧЕМ ОДИН ФАЙЛ (05.09, ADR-0179). Пути разошлись и это никто не видел: CI применял ВСЁ по глобу
# и падал на каталожной миграции 4 суток, а ручной `deploy.sh` перечислял файлы руками и с 007
# отставал — `007-mesh-review.sql` на существующей БД он не применял вовсе. Пока прогонщиков было
# три, CI проверял не тот путь, которым катится прод.
#
# Файлы обязаны быть ИДЕМПОТЕНТНЫМИ (`if not exists`): прод применяет их на КАЖДОМ деплое.
# Здесь только прод-схема. Каталожные миграции живут в `tools/scout/NNN-*.sql`
# (`db_migrate.py` → дев-БД `remlab-devdb`) — таблиц каталога на проде нет и не должно быть.
#
#   PSQL_CMD='psql -h localhost -U remlab -d remlab -q -v ON_ERROR_STOP=1' tools/apply-db-init.sh
#   PSQL_CMD='docker compose exec -T db psql -U remlab -d remlab -q -v ON_ERROR_STOP=1' \
#     DB_INIT_DIR=/opt/remlab/db/init /opt/remlab/scripts/apply-db-init.sh
set -euo pipefail

: "${PSQL_CMD:?PSQL_CMD не задан — команда psql, читающая SQL со stdin}"
DB_INIT_DIR="${DB_INIT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/db/init}"

shopt -s nullglob
files=("$DB_INIT_DIR"/[0-9][0-9][0-9]-*.sql)
if [ ${#files[@]} -eq 0 ]; then
  echo "FATAL: в $DB_INIT_DIR нет файлов NNN-*.sql — применять нечего"
  exit 1
fi

for f in "${files[@]}"; do
  echo "-- $(basename "$f")"
  eval "$PSQL_CMD" < "$f"
done
echo "прод-схема применена: ${#files[@]} файл(ов) из $DB_INIT_DIR"
