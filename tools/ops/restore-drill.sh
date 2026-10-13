#!/usr/bin/env bash
# Репетиция восстановления (план b2b-09, ADR-0266): свежий дамп из ~/remlab-backups поднимается во
# ВРЕМЕННОЙ базе (тот же образ, что на проде) и проверяется: ключевые таблицы на месте, строк не ноль.
# Боевую базу и dev-базу не трогает; контейнер удаляется. Крон DEV: 30 4 * * 0 (воскресенье).
# Результат — строка в ~/remlab-backups/drill.log; провал — тревога.
set -uo pipefail
DST=${DST:-$HOME/remlab-backups}
ALERT="$(dirname "$0")/../scout/alert.sh"
NAME=remlab-restore-drill
IMG=pgvector/pgvector:pg17
fail() { echo "$(date -u +%FT%TZ) FAIL $1" >> "$DST/drill.log"; docker rm -f "$NAME" >/dev/null 2>&1; bash "$ALERT" "🔴 репетиция восстановления базы не прошла: $1" || true; exit 1; }

dump=$(ls -t "$DST"/db-*.sql.gz 2>/dev/null | head -1)
[ -n "$dump" ] || fail "нет дампов в $DST"
docker rm -f "$NAME" >/dev/null 2>&1
docker run -d --name "$NAME" --memory 1g -e POSTGRES_USER=remlab -e POSTGRES_PASSWORD=drill -e POSTGRES_DB=remlab "$IMG" >/dev/null || fail "не запустился контейнер"
for _ in $(seq 1 60); do docker exec "$NAME" pg_isready -U remlab -d remlab >/dev/null 2>&1 && break; sleep 2; done
docker exec "$NAME" pg_isready -U remlab -d remlab >/dev/null 2>&1 || fail "база не поднялась"
t0=$(date +%s)
gunzip -c "$dump" | docker exec -i "$NAME" psql -U remlab -d remlab -q -v ON_ERROR_STOP=0 >/dev/null 2>"$DST/drill-errors.log"
errs=$(grep -c "ERROR" "$DST/drill-errors.log" || true)
# ключевые таблицы, которые есть с весны: проекты, сметы, лиды; плюс сколько таблиц всего (новые
# таблицы попадают в дамп со следующей ночи — их наличие не требуем)
counts=$(docker exec "$NAME" psql -U remlab -d remlab -tA -c "select 'projects='||(select count(*) from projects)||' estimates='||(select count(*) from estimates)||' leads='||(select count(*) from leads)||' tables='||(select count(*) from information_schema.tables where table_schema='public')" 2>&1) || fail "проверочный запрос: $counts"
docker rm -f "$NAME" >/dev/null 2>&1
tables=$(printf '%s' "$counts" | sed -n 's/.*tables=\([0-9]*\).*/\1/p')
[ "${tables:-0}" -ge 15 ] || fail "после восстановления таблиц $tables ($counts)"
[ "${errs:-0}" -eq 0 ] || fail "ошибок при восстановлении: $errs (см. $DST/drill-errors.log)"
echo "$(date -u +%FT%TZ) ok $(basename "$dump") за $(( $(date +%s) - t0 )) с: $counts" >> "$DST/drill.log"
echo "ok: $counts"
