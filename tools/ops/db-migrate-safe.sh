#!/usr/bin/env bash
# БЕЗОПАСНАЯ МИГРАЦИЯ ДЕВ-БД ОДНОЙ КОМАНДОЙ (onb-12 ч.2, ADR-0330 п.6). Каталожные миграции `tools/scout/NNN-*.sql` раньше
# катились `db_migrate.py` прямо под работающими кронами и без копии. Здесь порядок такой:
#   1. пауза тяжёлых кронов `cron-pause.sh on` (ждёт конца работающих задач; не дождались — выходим, ничего не тронув);
#   2. `pg_dump --clean` затронутых таблиц (или всей БД, если по SQL их не определить) в новую папку с меткой времени —
#      ПОСЛЕ паузы: иначе крон успел бы записать между копией и миграцией, и откат по копии это потерял бы;
#   3. SQL в одной транзакции (`--single-transaction`, ON_ERROR_STOP); проверка «после» (`--check`) — в ТОЙ ЖЕ транзакции:
#      не прошла — откатывается вся миграция;
#   4. `\d` новых объектов — в папку дампа;
#   5. `cron-pause.sh off` — всегда, даже при ошибке (trap), но только если паузу ставили мы;
#   6. строка в журнал `<папка>/journal.log`: что, когда, итог, путь дампа, команда отката (`rollback.sh` рядом с дампом).
#
#   tools/ops/db-migrate-safe.sh <файл.sql> [--db dev] [--check '<SQL-выражение boolean>'] [--hours 2] [--wait 900] [--dry-run]
#   tools/ops/db-migrate-safe.sh selftest     # на заглушках psql/pg_dump и временном замке — дев-базу не трогает
#
# Только дев-БД `remlab-devdb` (прод-схема `db/init/` катится деплоем через `tools/apply-db-init.sh`).
# Коды: 0 применена · 2 ошибка ввода · 3 кроны не закончили, миграцию не трогали · 4 пауза или другая миграция уже идёт ·
#       5 дамп не получился · 6 SQL упал (откачен) · 7 проверка «после» не прошла (откачено).
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
MIGRATE_DIR="${MIGRATE_DIR:-$HOME/backups/migrate}"
CRON_PAUSE="$ROOT/tools/ops/cron-pause.sh"

usage() { sed -n '2,19p' "$0"; exit 2; }
say() { echo "$*"; }

# ---------------------------------------------------------------- разбор SQL
# sql_scan <файл> — печатает «t <таблица>» на каждую таблицу, которую SQL трогает, и «full <причина>», если таблиц не определить
sql_scan() {
  local body
  body=$(sed 's/--.*$//' "$1" | tr '[:upper:]' '[:lower:]' | tr '\n' ' ')
  local unknown='\bdo[[:space:]]+\$|create[[:space:]]+(or[[:space:]]+replace[[:space:]]+)?(function|procedure|trigger|view|materialized|type|schema|extension|rule)|drop[[:space:]]+(view|function|procedure|schema|type|extension|index|trigger|materialized)|alter[[:space:]]+(view|type|function|schema|materialized|index)|drop[[:space:]]+table[^;]*,'
  if grep -qE "$unknown" <<<"$body"; then echo "full в SQL есть функции/вью/DO-блоки/DROP INDEX — затронутое не определить"; return; fi
  local name='("?[a-z_][a-z0-9_$]*"?\.)?"?[a-z_][a-z0-9_$]*"?'
  grep -oE "(create[[:space:]]+(unlogged[[:space:]]+)?table|alter[[:space:]]+table|drop[[:space:]]+table|insert[[:space:]]+into|delete[[:space:]]+from|truncate([[:space:]]+table)?|comment[[:space:]]+on[[:space:]]+table)[[:space:]]+((if[[:space:]]+(not[[:space:]]+)?exists|only)[[:space:]]+)*${name}|update[[:space:]]+(only[[:space:]]+)?${name}[[:space:]]+set|index[^;]*[[:space:]]on[[:space:]]+(only[[:space:]]+)?${name}" <<<"$body" \
    | sed -E 's/[[:space:]]+set$//' | awk '{print $NF}' | tr -d '"' | sort -u | sed 's/^/t /'
}

# ---------------------------------------------------------------- основной путь
main() {
  local file="" db=dev check="" hours=2 wait=900 dry=0
  while [ $# -gt 0 ]; do
    case "$1" in
      --db) db="${2:-}"; shift 2 ;;
      --check) check="${2:-}"; shift 2 ;;
      --hours) hours="${2:-}"; shift 2 ;;
      --wait) wait="${2:-}"; shift 2 ;;
      --dry-run) dry=1; shift ;;
      -h|--help) usage ;;
      -*) echo "неизвестный ключ: $1"; exit 2 ;;
      *) [ -z "$file" ] || { echo "файл миграции — один, а не «$file» и «$1»"; exit 2; }; file="$1"; shift ;;
    esac
  done
  [ -n "$file" ] || usage
  [ -f "$file" ] || { echo "нет файла: $file"; exit 2; }
  case "$db" in
    dev) local container=remlab-devdb ;;
    *) echo "база «$db» не поддерживается: только dev (remlab-devdb); прод-схема — db/init/ через деплой"; exit 2 ;;
  esac
  case "$wait" in ''|*[!0-9]*) echo "--wait — секунды целым числом"; exit 2;; esac
  if grep -qiE '^[[:space:]]*(begin|commit|rollback|start[[:space:]]+transaction)[[:space:]]*;' "$file"; then
    echo "в файле свои BEGIN/COMMIT — уберите: транзакцию ставит скрипт (иначе проверка «после» не откатит миграцию)"; exit 2
  fi
  if grep -qiE '\bconcurrently\b|^[[:space:]]*vacuum\b' "$file"; then
    echo "CONCURRENTLY/VACUUM не работают в транзакции — такую миграцию катите руками по шагам"; exit 2
  fi
  local -a PSQL DUMP
  read -ra PSQL <<<"${MIGRATE_PSQL:-docker exec -i $container psql -U remlab -d remlab}"
  read -ra DUMP <<<"${MIGRATE_PG_DUMP:-docker exec $container pg_dump -U remlab -d remlab}"

  # что трогает SQL и что из этого уже есть в базе (чтение, не запись)
  local scan full_reason="" t names=() existing=() created=()
  scan=$(sql_scan "$file")
  full_reason=$(sed -n 's/^full //p' <<<"$scan")
  while read -r _ t; do [ -n "$t" ] && names+=("$t"); done < <(grep '^t ' <<<"$scan")
  if [ -z "$full_reason" ] && [ ${#names[@]} -eq 0 ]; then full_reason="таблиц в SQL не нашли"; fi
  if [ ${#names[@]} -gt 0 ]; then
    local list out
    list=$(printf "'%s'," "${names[@]}"); list="${list%,}"
    if ! out=$("${PSQL[@]}" -tAc "select n from unnest(array[$list]) n where to_regclass(n) is not null" 2>&1); then
      echo "база не отвечает: $out"; exit 5
    fi
    for t in "${names[@]}"; do
      if grep -qx "$t" <<<"$out"; then existing+=("$t"); else created+=("$t"); fi
    done
  fi
  # на таблицу опирается вью или чужой внешний ключ (products ← lr_roles, catalog_ready) — её DROP из дампа `--clean` упадёт,
  # и откат по таблицам не сработает; тогда копия всей БД
  if [ -z "$full_reason" ] && [ ${#existing[@]} -gt 0 ]; then
    local arr deps
    arr=$(printf "'%s'," "${existing[@]}"); arr="array[${arr%,}]::regclass[]"
    deps=$("${PSQL[@]}" -tAc "select string_agg(distinct x::regclass::text, ', ') from (
      select r.ev_class x from pg_depend d join pg_rewrite r on r.oid = d.objid
       where d.classid = 'pg_rewrite'::regclass and d.refobjid = any($arr) and r.ev_class <> d.refobjid
      union all
      select conrelid from pg_constraint where contype = 'f' and confrelid = any($arr) and conrelid <> confrelid) s" 2>&1) \
      || { echo "база не отвечает: $deps"; exit 5; }
    [ -n "$deps" ] && full_reason="на таблицы опираются $deps — откат по отдельным таблицам не сработает"
  fi
  local mode
  if [ -n "$full_reason" ]; then mode="вся БД ($full_reason)"
  elif [ ${#existing[@]} -gt 0 ]; then mode="таблицы: ${existing[*]}"
  else mode="только схема всей БД (все таблицы новые: ${created[*]})"; fi

  local stamp name dir
  stamp=$(date +%Y%m%d-%H%M%S); name=$(basename "$file" .sql); dir="$MIGRATE_DIR/$stamp-$name"
  if [ "$dry" = 1 ]; then
    say "СУХОЙ ПРОГОН — ничего не делаем. Миграция $file → $db ($container)"
    say "  1. пауза кронов: $CRON_PAUSE on $hours \"миграция $name\" (ждать до $wait с)"
    say "  2. дамп в $dir/dump.sql.gz — $mode"
    say "  3. SQL одной транзакцией${check:+; проверка в ней же: $check}"
    say "  4. \\d новых объектов: ${created[*]:-нет}"
    say "  5. $CRON_PAUSE off (всегда)"
    say "  6. строка в $MIGRATE_DIR/journal.log, откат — $dir/rollback.sh"
    exit 0
  fi

  # одна миграция за раз и не поверх чужой паузы
  mkdir -p "$MIGRATE_DIR"
  exec 5>>"$MIGRATE_DIR/.migrate.lock"
  flock -n 5 || { echo "другая миграция уже идёт (замок $MIGRATE_DIR/.migrate.lock) — выходим"; exit 4; }
  # shellcheck source=tools/ops/maintenance.sh
  . "$ROOT/tools/ops/maintenance.sh"
  local why
  if why=$(maint_active); then echo "пауза кронов уже стоит не нами ($why) — не трогаем её и выходим"; exit 4; fi

  PAUSED=0; RESULT="не дошли до SQL"; DIR="$dir"; MODE="$mode"; FILE="$file"; DB="$db"
  trap finish EXIT
  trap 'exit 130' INT TERM
  local rc
  MAINT_WAIT="$wait" bash "$CRON_PAUSE" on "$hours" "миграция $name"; rc=$?
  [ "$rc" = 0 ] || [ "$rc" = 3 ] && PAUSED=1
  if [ "$rc" = 3 ]; then RESULT="кроны не закончили за $wait с — миграцию не трогали"; exit 3; fi
  [ "$rc" = 0 ] || { RESULT="cron-pause on: код $rc"; exit 4; }
  # пауза наша, копия будет до SQL: `db_migrate.py`, запущенный отсюда, без паузы не отказывает (его допуск — `db_migrate.py:gate`)
  export REMLAB_MIGRATE_SAFE=1

  mkdir -p "$dir"
  cp "$file" "$dir/migration.sql"
  local -a dargs=(--clean --if-exists)
  if [ -n "$full_reason" ]; then :
  elif [ ${#existing[@]} -gt 0 ]; then for t in "${existing[@]}"; do dargs+=(-t "$t"); done
  else dargs=(--schema-only); fi
  if ! { "${DUMP[@]}" "${dargs[@]}" 2>"$dir/dump.err" | gzip > "$dir/dump.sql.gz"; } \
     || ! gzip -t "$dir/dump.sql.gz" 2>/dev/null \
     || ! gunzip -c "$dir/dump.sql.gz" | tail -5 | grep -q 'PostgreSQL database dump complete'; then
    RESULT="дамп не получился ($(head -c 300 "$dir/dump.err"))"; exit 5
  fi
  write_rollback "$dir" "${#existing[@]}" "${created[@]}"
  say "дамп: $dir/dump.sql.gz ($(du -h "$dir/dump.sql.gz" | cut -f1); $mode)"

  local marker="db-migrate-safe: проверка после миграции не прошла"
  {
    cat "$file"
    echo
    if [ -n "$check" ]; then
      # shellcheck disable=SC2016  # $chk$ — кавычки долларом в SQL, не переменная
      printf 'do $chk$ begin if not coalesce((%s), false) then raise exception %s; end if; end $chk$;\n' "$check" "'$marker'"
    fi
  } | "${PSQL[@]}" -q -v ON_ERROR_STOP=1 --single-transaction > "$dir/apply.log" 2>&1; rc=$?
  if [ "$rc" != 0 ]; then
    if grep -q "$marker" "$dir/apply.log"; then RESULT="проверка «после» не прошла — откачено"; tail -3 "$dir/apply.log"; exit 7; fi
    RESULT="SQL упал — откачено ($(grep -m1 ERROR "$dir/apply.log" | head -c 200))"; tail -5 "$dir/apply.log"; exit 6
  fi
  for t in "${created[@]}"; do "${PSQL[@]}" -c "\\d $t" >> "$dir/after.txt" 2>&1; done
  RESULT="OK"
  say "миграция применена${check:+, проверка «после» прошла}; новые объекты: ${created[*]:-нет} (описание — $dir/after.txt)"
}

# rollback.sh рядом с дампом: сам не запускается, команда отката для журнала и человека
write_rollback() {
  local dir="$1" n_existing="$2"; shift 2
  local psql_str="${MIGRATE_PSQL:-docker exec -i remlab-devdb psql -U remlab -d remlab}" t
  {
    echo "#!/usr/bin/env bash"
    echo "# ОТКАТ миграции $(basename "$FILE") ($(date '+%F %T')). Данные, записанные ПОСЛЕ миграции в затронутые таблицы, пропадут."
    echo "set -euo pipefail"
    for t in "$@"; do echo "$psql_str -v ON_ERROR_STOP=1 -c 'drop table if exists $t cascade'   # новая таблица миграции"; done
    if [ "$n_existing" -gt 0 ] || [[ "$MODE" == "вся БД"* ]]; then
      echo "gunzip -c '$dir/dump.sql.gz' | $psql_str -q -v ON_ERROR_STOP=1 --single-transaction   # таблицы как до миграции"
    else
      echo "# дамп — только схема (справка); существующих таблиц миграция не трогала"
    fi
  } > "$dir/rollback.sh"
}

finish() {
  local rc=$?
  if [ "${PAUSED:-0}" = 1 ]; then bash "$CRON_PAUSE" off >/dev/null 2>&1 && echo "пауза кронов снята" || echo "ВНИМАНИЕ: паузу снять не удалось — $CRON_PAUSE off"; fi
  local sha
  sha=$(sha256sum "$FILE" | cut -c1-12)
  printf '%s | %s | %s sha256:%s | %s | код %s | дамп: %s (%s) | откат: %s\n' "$(date '+%F %T')" "$DB" "$(basename "$FILE")" "$sha" \
    "$RESULT" "$rc" "$DIR" "$MODE" "$([ -f "$DIR/rollback.sh" ] && echo "bash $DIR/rollback.sh" || echo "не нужен — база не менялась")" \
    >> "$MIGRATE_DIR/journal.log"
  echo "журнал: $MIGRATE_DIR/journal.log"
}

[ "${1:-}" = selftest ] && { shift; exec bash "$ROOT/tools/ops/db-migrate-safe-selftest.sh" "$@"; }
main "$@"
