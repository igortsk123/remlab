#!/usr/bin/env bash
# САМОПРОВЕРКА `db-migrate-safe.sh` (onb-12 ч.2): заглушки psql/pg_dump и временный замок обслуживания — дев-базу и паузу
# машины не трогает. Запуск: `tools/ops/db-migrate-safe.sh selftest` (его же гоняет `tests/unit/db-migrate-safe.test.ts`).
# Временная папка остаётся в $TMPDIR (несколько КБ) — путь в конце вывода.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCRIPT="$ROOT/tools/ops/db-migrate-safe.sh"
T=$(mktemp -d "${TMPDIR:-/tmp}/db-migrate-selftest.XXXXXX")
fails=0
ok() { if [ "$2" = 0 ]; then echo "  [ ok ] $1"; else echo "  [FAIL] $1"; fails=$((fails + 1)); fi; }
yes_if() { if eval "$1"; then echo 0; else echo 1; fi; }

export REMLAB_MAINT_DIR="$T/maint" MIGRATE_DIR="$T/backups" MIGRATE_PSQL="$T/bin/psql" MIGRATE_PG_DUMP="$T/bin/pg_dump"
mkdir -p "$T/bin" "$T/sql"

# psql-заглушка: чтения отвечают по STUB_EXISTING/STUB_DEPS, применение пишет SQL в applied.sql и отмечает, стояла ли пауза
cat > "$T/bin/psql" <<'EOF'
#!/usr/bin/env bash
T="$(cd "$(dirname "$0")/.." && pwd)"
echo "psql $*" >> "$T/calls.log"
q="${*: -1}"
case "$*" in
  *to_regclass*) for n in ${STUB_EXISTING:-}; do grep -q "'$n'" <<<"$q" && echo "$n"; done; exit 0 ;;
  *pg_depend*) echo "${STUB_DEPS:-}"; exit 0 ;;
  *'\d '*) echo "Table ${q#\\d }"; exit 0 ;;
esac
sql=$(cat); printf '%s\n' "$sql" >> "$T/applied.sql"
[ -f "$REMLAB_MAINT_DIR/maintenance.pause" ] && echo paused >> "$T/apply-state" || echo NOT-paused >> "$T/apply-state"
[ "${STUB_FAIL:-}" = sql ] && { echo "ERROR:  syntax error at or near \"oops\"" >&2; exit 3; }
if [ "${STUB_FAIL:-}" = check ] && grep -q 'проверка после миграции' <<<"$sql"; then
  echo "ERROR:  db-migrate-safe: проверка после миграции не прошла" >&2; exit 3
fi
exit 0
EOF
cat > "$T/bin/pg_dump" <<'EOF'
#!/usr/bin/env bash
T="$(cd "$(dirname "$0")/.." && pwd)"
echo "pg_dump $*" >> "$T/calls.log"
[ -n "${STUB_DUMP_FAIL:-}" ] && { echo "pg_dump: error: connection refused" >&2; exit 1; }
printf -- '-- dump %s\n-- PostgreSQL database dump complete\n' "$*"
EOF
chmod +x "$T/bin/psql" "$T/bin/pg_dump"

printf 'alter table products add column if not exists fabric text;\ncreate table if not exists upholstery (id int);\n' > "$T/sql/010-mixed.sql"
printf 'create table if not exists upholstery (id int);\ncreate index if not exists up_i on upholstery (id);\n' > "$T/sql/011-new.sql"
printf 'do $$ begin perform 1; end $$;\n' > "$T/sql/012-do.sql"
printf 'begin;\ncreate table x (id int);\ncommit;\n' > "$T/sql/013-tx.sql"
printf 'create index concurrently i on products (id);\n' > "$T/sql/014-conc.sql"

run() { bash "$SCRIPT" "$@" > "$T/out.txt" 2>&1; echo $?; }
reset() { : > "$T/calls.log"; : > "$T/apply-state"; : > "$T/applied.sql"; }
journal_last() { tail -1 "$MIGRATE_DIR/journal.log" 2>/dev/null; }
paused() { [ -f "$REMLAB_MAINT_DIR/maintenance.pause" ]; }

# 1. сухой прогон: план, без паузы, дампа и применения
reset; rc=$(STUB_EXISTING=products run "$T/sql/010-mixed.sql" --dry-run)
ok "dry-run: код 0 ($rc), план с дампом таблицы products" "$(yes_if "[ $rc = 0 ] && grep -q 'таблицы: products' '$T/out.txt'")"
ok "dry-run: ни паузы, ни дампа, ни SQL, ни журнала" "$(yes_if "! paused && ! grep -q pg_dump '$T/calls.log' && [ ! -s '$T/applied.sql' ] && [ ! -e '$MIGRATE_DIR' ]")"

# 2. обычный путь: пауза → дамп таблицы → SQL в транзакции под паузой → \d нового → пауза снята → журнал и откат
reset; rc=$(STUB_EXISTING=products run "$T/sql/010-mixed.sql" --check "(select true)")
d=$(printf '%s\n' "$MIGRATE_DIR"/*-010-mixed | head -1)
ok "применение: код 0 ($rc)" "$rc"
ok "дамп только products, с --clean" "$(yes_if "grep -q 'pg_dump --clean --if-exists -t products$' '$T/calls.log' && gzip -t '$d/dump.sql.gz'")"
ok "SQL шёл одной транзакцией с ON_ERROR_STOP" "$(yes_if "grep -q 'ON_ERROR_STOP=1 --single-transaction' '$T/calls.log'")"
ok "SQL шёл под паузой кронов" "$(yes_if "[ \"\$(cat '$T/apply-state')\" = paused ]")"
ok "проверка «после» — в той же транзакции" "$(yes_if "grep -q 'if not coalesce(((select true)), false)' '$T/applied.sql'")"
ok "\\d новой таблицы upholstery → after.txt" "$(yes_if "grep -q 'Table upholstery' '$d/after.txt'")"
ok "пауза снята" "$(yes_if "! paused")"
ok "журнал: OK, путь дампа, команда отката" "$(yes_if "journal_last | grep -q '010-mixed.sql sha256:.* | OK | код 0 | дамп: $d (таблицы: products) | откат: bash $d/rollback.sh'")"
ok "rollback.sh: drop новой таблицы + восстановление products" "$(yes_if "grep -q 'drop table if exists upholstery' '$d/rollback.sh' && grep -q 'gunzip -c' '$d/rollback.sh'")"

# 3. SQL упал — код 6, пауза снята, журнал с ошибкой
reset; rc=$(STUB_EXISTING=products STUB_FAIL=sql run "$T/sql/010-mixed.sql")
ok "SQL упал: код 6 ($rc), пауза снята" "$(yes_if "[ $rc = 6 ] && ! paused")"
ok "журнал: «SQL упал — откачено»" "$(yes_if "journal_last | grep -q 'SQL упал — откачено (ERROR:  syntax error.*| код 6'")"

# 4. проверка «после» не прошла — код 7, пауза снята
reset; rc=$(STUB_EXISTING=products STUB_FAIL=check run "$T/sql/010-mixed.sql" --check "false")
ok "проверка не прошла: код 7 ($rc), пауза снята, в журнале" "$(yes_if "[ $rc = 7 ] && ! paused && journal_last | grep -q 'проверка «после» не прошла — откачено'")"

# 5. дамп не получился — SQL не применяли, код 5, пауза снята
reset; rc=$(STUB_EXISTING=products STUB_DUMP_FAIL=1 run "$T/sql/010-mixed.sql")
ok "дамп упал: код 5 ($rc), SQL не применяли, пауза снята" "$(yes_if "[ $rc = 5 ] && [ ! -s '$T/applied.sql' ] && ! paused")"

# 6. работающий тяжёлый крон держит замок — ждём --wait и выходим кодом 3, ничего не применив; пауза снята
reset
( . "$ROOT/tools/ops/maintenance.sh"; maint_gate долгая "$T/long.log"; sleep 4 ) &
bg=$!; sleep 0.5
rc=$(STUB_EXISTING=products run "$T/sql/010-mixed.sql" --wait 1)
ok "кроны не закончили: код 3 ($rc), без дампа и SQL, пауза снята" "$(yes_if "[ $rc = 3 ] && ! grep -q pg_dump '$T/calls.log' && [ ! -s '$T/applied.sql' ] && ! paused")"
ok "журнал: «кроны не закончили», отката не нужно" "$(yes_if "journal_last | grep -q 'кроны не закончили за 1 с.*| откат: не нужен'")"
wait "$bg"

# 7. чужая пауза уже стоит — не трогаем её, код 4
reset; bash "$ROOT/tools/ops/cron-pause.sh" on 1 "чужое обслуживание" >/dev/null 2>&1
rc=$(STUB_EXISTING=products run "$T/sql/010-mixed.sql")
ok "чужая пауза: код 4 ($rc), её метка на месте, SQL не применяли" "$(yes_if "[ $rc = 4 ] && paused && [ ! -s '$T/applied.sql' ]")"
bash "$ROOT/tools/ops/cron-pause.sh" off >/dev/null 2>&1

# 8. выбор дампа: все таблицы новые → только схема; DO-блок → вся БД; вью на таблице → вся БД
reset; rc=$(run "$T/sql/011-new.sql")
ok "все таблицы новые: дамп --schema-only ($rc)" "$(yes_if "[ $rc = 0 ] && grep -q 'pg_dump --schema-only$' '$T/calls.log'")"
reset; rc=$(run "$T/sql/012-do.sql")
ok "DO-блок: дамп всей БД ($rc)" "$(yes_if "[ $rc = 0 ] && grep -q 'pg_dump --clean --if-exists$' '$T/calls.log'")"
reset; rc=$(STUB_EXISTING=products STUB_DEPS=lr_roles run "$T/sql/010-mixed.sql")
ok "на products опирается вью: дамп всей БД ($rc)" "$(yes_if "[ $rc = 0 ] && grep -q 'pg_dump --clean --if-exists$' '$T/calls.log' && journal_last | grep -q 'опираются lr_roles'")"

# 9. отказы ввода — код 2, ничего не тронуто
reset
ok "свой BEGIN/COMMIT в файле — отказ" "$(yes_if "[ \$(run '$T/sql/013-tx.sql') = 2 ]")"
ok "CONCURRENTLY — отказ" "$(yes_if "[ \$(run '$T/sql/014-conc.sql') = 2 ]")"
ok "--db prod — отказ" "$(yes_if "[ \$(run '$T/sql/010-mixed.sql' --db prod) = 2 ]")"
ok "нет файла — отказ" "$(yes_if "[ \$(run '$T/sql/nope.sql') = 2 ]")"
ok "отказы ничего не вызвали" "$(yes_if "[ ! -s '$T/calls.log' ] && ! paused")"

echo "db-migrate-safe selftest: ошибок $fails (папка $T)"
[ "$fails" = 0 ]
