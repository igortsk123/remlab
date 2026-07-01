#!/usr/bin/env bash
# Ночной дамп БД remlab -> /opt/remlab/backups/db-<ts>.sql.gz. Ротацию (7 шт) делает cleanup.sh.
set -euo pipefail
TS=$(date +%Y%m%d-%H%M%S)
OUT=/opt/remlab/backups/db-$TS.sql.gz
mkdir -p /opt/remlab/backups
if docker ps --format '{{.Names}}' | grep -q '^remlab-db$'; then
  docker exec remlab-db pg_dump -U remlab -d remlab | gzip > "$OUT"
  echo "$(date '+%F %T') backup -> $OUT ($(du -h "$OUT" | cut -f1))" >> /opt/remlab/backups/backup.log
else
  echo "$(date '+%F %T') remlab-db не запущен — пропуск" >> /opt/remlab/backups/backup.log
fi
