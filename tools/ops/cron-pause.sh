#!/usr/bin/env bash
# ПАУЗА ТЯЖЁЛЫХ КРОНОВ DEV НА ОБСЛУЖИВАНИЕ (onb-12, ADR-0330 п.6): миграция БД, подмена банка наборов `*.next`.
# Кроны хоста не трогает: каждый тяжёлый крон сам смотрит замок (`tools/ops/maintenance.sh:maint_gate`) и на паузе выходит
# строкой в свой лог. Сторожа денег и пула Salad (money_guard, idle_guard, batch_window, heartbeat, wave_guard) паузу НЕ слушают —
# они гасят платные машины, их остановка стоит денег.
#
#   tools/ops/cron-pause.sh on [часов=6] [причина…]   поставить паузу (1–24 ч) и дождаться конца работающих задач (MAINT_WAIT, с)
#   tools/ops/cron-pause.sh off                         снять паузу
#   tools/ops/cron-pause.sh status                      пауза? кто держит замок? все ли тяжёлые кроны подключены к замку?
#   tools/ops/cron-pause.sh selftest                    проверка без кронов: во временной папке, на головах настоящих скриптов
# Коды: on — 0 пауза действует и задач нет, 3 пауза поставлена, но задачи ещё идут (см. список), 2 — ошибка ввода;
#       status — 0 паузы нет, 10 пауза и задач нет, 11 пауза, но задачи ещё идут, 12 крон не подключён к замку.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=maintenance.sh
. "$ROOT/tools/ops/maintenance.sh"
# ТЯЖЁЛЫЕ КРОНЫ, КОТОРЫЕ СЛУШАЮТ ПАУЗУ (строки `infra/dev/crontab`): пишут в БД DEV и/или публикуют демо и галерею
GATED=(tools/scout/refresh_daily.sh tools/scout/nightly_exam.sh tools/scout/salad/sink_keeper.sh)

holders() {   # кто держит замок: pid, время работы, команда
  [ -f "$MAINT_LOCK" ] || return 0
  local p
  command -v fuser >/dev/null || { echo "  (кто именно — не узнать: нет fuser; смотрите ps по cron-задачам)"; return 0; }
  for p in $(fuser "$MAINT_LOCK" 2>/dev/null); do
    [ "$p" = "$$" ] || [ "$p" = "$BASHPID" ] && continue      # сам cron-pause держит файл открытым для проверки
    ps -o pid=,etime=,args= -p "$p" 2>/dev/null | cut -c1-160
  done
}

wired() {     # каждый тяжёлый крон подключён к замку ДО своей работы: печатает неподключённые
  local f n first
  for f in "${GATED[@]}"; do
    n=$(grep -n '^[^#]*maint_gate ' "$ROOT/$f" | head -1 | cut -d: -f1)
    first=$(grep -nE '^[[:space:]]*(exec 9|\./run\.sh|step |paid_step )' "$ROOT/$f" | head -1 | cut -d: -f1)
    if [ -z "$n" ] || { [ -n "$first" ] && [ "$n" -gt "$first" ]; }; then echo "$f"; fi
  done
}

cmd_on() {
  local hours="${1:-6}"; shift || true
  local reason="${*:-обслуживание}"
  case "$hours" in ''|*[!0-9]*) echo "часы — целое 1–24, а не «$hours»"; return 2;; esac
  if [ "$hours" -lt 1 ] || [ "$hours" -gt 24 ]; then echo "часы — 1–24 (забытая пауза не должна глушить кроны сутками)"; return 2; fi
  mkdir -p "$MAINT_DIR"
  printf 'until=%s\nsince=%s\nreason=%s\n' "$(( $(date +%s) + hours * 3600 ))" "$(date '+%F %T')" "${reason//$'\n'/ }" \
    > "$MAINT_PAUSE.tmp" && mv "$MAINT_PAUSE.tmp" "$MAINT_PAUSE"
  echo "пауза поставлена: $(maint_active)"
  exec 7>>"$MAINT_LOCK"
  if flock -x -w "${MAINT_WAIT:-900}" 7; then
    flock -u 7
    echo "пауза действует: работающих тяжёлых задач нет, новые запуски выходят строкой в свой лог"
    return 0
  fi
  echo "пауза поставлена, но задачи ещё идут (ждали ${MAINT_WAIT:-900} с) — дождитесь и повторите status:"
  holders
  return 3
}

cmd_off() {
  if [ -f "$MAINT_PAUSE" ]; then rm -f "$MAINT_PAUSE"; echo "пауза снята — кроны идут по расписанию"
  else echo "паузы не было"; fi
}

cmd_status() {
  local why rc=0 busy=0 bad
  bad=$(wired)
  if [ -f "$MAINT_LOCK" ]; then
    exec 7>>"$MAINT_LOCK"
    if flock -x -n 7; then flock -u 7; else busy=1; fi
  fi
  if why=$(maint_active); then
    echo "пауза: ДА, $why"
    rc=10; [ "$busy" = 1 ] && rc=11
  else
    echo "пауза: нет${why:+ ($why)}"
  fi
  if [ "$busy" = 1 ]; then echo "под замком работают:"; holders; else echo "под замком никто не работает"; fi
  echo "тяжёлые кроны, слушающие паузу: ${GATED[*]}"
  if [ -n "$bad" ]; then echo "НЕ ПОДКЛЮЧЕНЫ к замку (или замок после работы): $bad"; rc=12; fi
  return "$rc"
}

# ---------------------------------------------------------------- самопроверка
cmd_selftest() {
  local T fails=0 f rel n rc out
  T=$(mktemp -d "${TMPDIR:-/tmp}/cron-pause-selftest.XXXXXX")
  # shellcheck disable=SC2064
  trap "rm -rf '$T'" EXIT
  ok() { if [ "$2" = 0 ]; then echo "  [ ok ] $1"; else echo "  [FAIL] $1"; fails=$((fails + 1)); fi; }
  export REMLAB_MAINT_DIR="$T/maint" ALERT_DRY=1 MESH_ENV="$T/none.env" MESH_KEEPER_LOG="$T/sink-keeper.log"
  # пути замка — заново, уже во временной папке; иначе on/off самопроверки тронули бы настоящую паузу машины
  . "$ROOT/tools/ops/maintenance.sh"
  if [ "$MAINT_PAUSE" != "$T/maint/maintenance.pause" ]; then echo "selftest: пути замка не во временной папке — стоп"; return 1; fi
  # копия ГОЛОВ настоящих скриптов (до строки maint_gate включительно) + «работа» — так проверяется сам порядок строк скрипта
  mkdir -p "$T/repo/tools/ops" "$T/repo/tools/scout/salad"
  cp "$ROOT/tools/ops/maintenance.sh" "$T/repo/tools/ops/"
  printf '#!/bin/bash\necho "[сухо] $1"\n' > "$T/repo/tools/scout/alert.sh"
  for rel in "${GATED[@]}"; do
    n=$(grep -n '^[^#]*maint_gate ' "$ROOT/$rel" | head -1 | cut -d: -f1)
    if [ -z "$n" ]; then ok "$rel: подключён к замку (maint_gate)" 1; continue; fi
    { head -n "$n" "$ROOT/$rel"; echo "echo РАБОТА-ПОШЛА > \"$T/ran.\$(basename \"\$0\")\""; } > "$T/repo/$rel"
  done
  ok "тяжёлые кроны подключены к замку до своей работы" "$([ -z "$(wired)" ] && echo 0 || echo 1)"
  run_all() { for rel in "${GATED[@]}"; do [ -f "$T/repo/$rel" ] && bash "$T/repo/$rel" >/dev/null 2>&1; done; }
  ran() { ls "$T"/ran.* 2>/dev/null | wc -l; }
  # 1. паузы нет — работа идёт
  run_all; ok "без паузы: все ${#GATED[@]} задачи работают (пошло $(ran))" "$([ "$(ran)" = "${#GATED[@]}" ] && echo 0 || echo 1)"
  rm -f "$T"/ran.*
  # 2. пауза — никто не работает, у каждого строка в логе; ежедневный цикл ещё и сообщает владельцу
  out=$(cmd_on 2 "проверка" 2>&1); rc=$?
  ok "on: пауза действует сразу, задач нет (код $rc)" "$rc"
  run_all; ok "на паузе: работа не пошла ни у одной (пошло $(ran))" "$([ "$(ran)" = 0 ] && echo 0 || echo 1)"
  ok "на паузе: строка в логе refresh_daily" "$(grep -q 'refresh_daily: пауза обслуживания (до .*причина: проверка)' "$T/repo/tools/scout/refresh.log"; echo $?)"
  ok "на паузе: refresh_daily пишет владельцу" "$(grep -q '\[сухо\] ⏸ remlab: «refresh_daily» пропущен' "$T/repo/tools/scout/refresh.log"; echo $?)"
  ok "на паузе: строка в логе nightly_exam" "$(grep -q 'nightly_exam: пауза обслуживания' "$T/repo/tools/scout/nightly.log"; echo $?)"
  ok "на паузе: строка в логе sink_keeper" "$(grep -q 'sink_keeper: пауза обслуживания' "$MESH_KEEPER_LOG"; echo $?)"
  out=$(cmd_status); rc=$?; ok "status на паузе — код 10 ($rc)" "$([ "$rc" = 10 ] && echo 0 || echo 1)"
  cmd_off >/dev/null
  # 3. задача работает → on ждёт её и честно говорит «ещё идут» (код 3), status — 11.
  # Задача держит замок до «отпусти», а on пускаем после метки «замок взят» — не по «sleep 0.5 / sleep 4»: на загруженном
  # раннере CI задача не успевала взять замок или отпускала его раньше проверки (T-20261105-38)
  ( . "$T/repo/tools/ops/maintenance.sh"; maint_gate долгая "$T/long.log"; : > "$T/held"
    for _ in $(seq 1 1200); do [ -e "$T/release" ] && exit 0; sleep 0.1; done ) &
  local bg=$!
  for _ in $(seq 1 300); do [ -e "$T/held" ] || ! kill -0 "$bg" 2>/dev/null && break; sleep 0.1; done
  ok "задача взяла замок до on" "$([ -e "$T/held" ] && echo 0 || echo 1)"
  out=$(MAINT_WAIT=1 cmd_on 1 "ждём" 2>&1); rc=$?
  ok "on при работающей задаче: код 3 и список держателей" "$([ "$rc" = 3 ] && grep -q 'задачи ещё идут' <<<"$out" && { ! command -v fuser >/dev/null || grep -qw "$bg" <<<"$out"; } && echo 0 || echo 1)"
  out=$(cmd_status); rc=$?; ok "status: пауза, но задача идёт — код 11 ($rc)" "$([ "$rc" = 11 ] && echo 0 || echo 1)"
  : > "$T/release"; wait "$bg"
  out=$(MAINT_WAIT=5 cmd_on 1 "ждём" 2>&1); rc=$?; ok "on после её конца — код 0 ($rc)" "$rc"
  cmd_off >/dev/null
  # 4. задача пришла, пока on держит исключительный замок (между меткой и проверкой) — выходит, а не работает
  exec 6>>"$REMLAB_MAINT_DIR/maintenance.lock"; flock -x 6
  bash "$T/repo/tools/scout/nightly_exam.sh" >/dev/null 2>&1
  flock -u 6; exec 6>&-
  ok "замок занят паузой — задача выходит (пошло $(ran))" "$([ "$(ran)" = 0 ] && echo 0 || echo 1)"
  # 5. истёкшая пауза — работа идёт, в логе «истекла»
  printf 'until=%s\nreason=старая\n' "$(( $(date +%s) - 60 ))" > "$REMLAB_MAINT_DIR/maintenance.pause"
  run_all; ok "истёкшая пауза: работа идёт (пошло $(ran))" "$([ "$(ran)" = "${#GATED[@]}" ] && echo 0 || echo 1)"
  ok "истёкшая пауза: строка «истекла» в логе" "$(grep -q 'истекла' "$T/repo/tools/scout/nightly.log"; echo $?)"
  rm -f "$T"/ran.*
  # 6. off — работа идёт; неверные часы — отказ
  cmd_off >/dev/null; run_all; ok "после off: работа идёт" "$([ "$(ran)" = "${#GATED[@]}" ] && echo 0 || echo 1)"
  out=$(cmd_on 48 x 2>&1); rc=$?; ok "on 48 ч — отказ (код 2)" "$([ "$rc" = 2 ] && [ ! -f "$REMLAB_MAINT_DIR/maintenance.pause" ] && echo 0 || echo 1)"
  echo "cron-pause selftest: ошибок $fails"
  [ "$fails" = 0 ]
}

case "${1:-status}" in
  on) shift; cmd_on "$@" ;;
  off) cmd_off ;;
  status) cmd_status ;;
  selftest) cmd_selftest ;;
  *) sed -n '2,13p' "$0"; exit 2 ;;
esac
