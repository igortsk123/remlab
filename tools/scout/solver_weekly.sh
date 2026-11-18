#!/bin/bash
# НЕДЕЛЬНАЯ ПРОВЕРКА РАССТАНОВКИ `solver_full` — отдельный крон (T-20261112-56/3, план refresh-split-01, вариант А, директор 18.11).
#
# Раньше по понедельникам шаг `solver_full` (`solver_check.py` — каждый сет из `sets3.json` прогоняется солвером) шёл внутри дневной
# сборки `refresh_daily.sh`: +57,5 мин и 64 процессорных минуты в день (замер STEPTIME 16.11) — почти весь недельный всплеск. Теперь он
# живёт здесь и идёт ночью в понедельник (`infra/dev/crontab`: 30 5 * * 1), когда DEV свободна; дневная сборка в понедельник только
# показывает его итог (шаг `solver_weekly_last` → `solver_weekly_status.py --digest`).
#
#   bash tools/scout/solver_weekly.sh           # боевой запуск (крон)
#   bash tools/scout/solver_weekly.sh --dry     # сухо: замки, срок, журнал, статус и STEPTIME — настоящие, но свои файлы `*.dry.*`,
#                                               #   сам solver_check НЕ запускается; тяжёлая очередь не занимается
#
# ЗАМКИ (настоящие flock, не проверка файла): ① `~/.remlab-refresh.lock` — тот же, что держит `refresh_daily.sh` на весь прогон (fd 9):
# недельная проверка и дневная сборка не идут одновременно (кто пришёл вторым — ждёт SW_LOCK_WAIT, потом пропуск со статусом и тревогой);
# ② `tools/scout/exam.flock` — тот же, что берёт `run.sh exam|smoke` (fd 9 там): не одновременно с экзаменом банков; экзамен, пришедший
# во время недельной проверки, получает свой прежний отказ «экзамен уже идёт (exam.flock)» (код 3) — в расписании 03:00 и 05:30 не пересекаются.
# ③ пауза обслуживания (`tools/ops/maintenance.sh`, `cron-pause.sh on` ждёт конца проверки, как у остальных тяжёлых кронов).
# СРОК: к SW_DEADLINE_HHMM (10:10) проверка обязана кончиться — дневная сборка в 10:40 берёт тот же замок `flock -n` и без него пропустила бы
# день; поэтому solver под `timeout` до этого срока (и не дольше SW_MAX_SEC, 3 ч; обычно ~60 мин). Не успел — статус FAIL и тревога.
# ТЯЖЁЛОЕ — под `tools/ops/heavy-slot.sh` с честной заявкой: 1 ядро (солвер последовательный, замер 64 CPU-мин за 57,5 мин ≈ 1,1 ядра), 2 ГБ, долгая.
# ЖУРНАЛ — `solver-weekly.log` (старт/готово + строка `STEPTIME name=solver_full …` того же вида, что у шагов дневной сборки; таблица минут и
# процессора — `refresh_step_times.py --log solver-weekly.log --cpu`); СТАТУС — `~/.cache/remlab-refresh/solver-weekly-status.json`.
# solver_check пишет те же файлы, что и раньше: `solver-check-report.json` и `v3set*-layout-checkweekly.*` (читателей у них нет).
set -uo pipefail
SELF="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/$(basename "${BASH_SOURCE[0]}")"
cd "$(dirname "$0")"
HERE="$(pwd)"
MODE=run; DRY=0
for a in "$@"; do
  case "$a" in
    --dry) DRY=1 ;;
    --run-solver) MODE=inner ;;   # внутренний вызов: сам solver (под heavy-slot)
    *) echo "solver_weekly.sh: неизвестный ключ «$a» (есть --dry)"; exit 2 ;;
  esac
done
PY="${SW_PY:-$HOME/venvs/scout/bin/python}"

# ---- внутренний режим: ровно одна команда — solver, с остатком времени до срока (heavy-slot мог подержать очередь) ----
if [ "$MODE" = inner ]; then
  left=$(( ${SW_DEADLINE_EPOCH:-0} - $(date +%s) ))
  if [ "$left" -lt "${SW_MIN_SEC:-600}" ]; then echo "до срока осталось $left с — солвер не запускаю"; exit 125; fi
  if [ "$DRY" = 1 ]; then
    sleep "${SW_DRY_SLEEP:-0}"
    echo "Итого: 0/0 влезают; проблемных 0 (сухой прогон, solver_check не запускался)"; exit 0
  fi
  exec env CHECK_TAG=weekly timeout -k 60 "$left" "$PY" solver_check.py
fi

if [ "$DRY" = 1 ]; then LOG="${SW_LOG:-solver-weekly.dry.log}"; STATUS_F="${SW_STATUS:-$HOME/.cache/remlab-refresh/solver-weekly-status.dry.json}"
else LOG="${SW_LOG:-solver-weekly.log}"; STATUS_F="${SW_STATUS:-$HOME/.cache/remlab-refresh/solver-weekly-status.json}"; fi
# ПАУЗА ОБСЛУЖИВАНИЯ — до всякой работы: на паузе строка в лог и владельцу, выход (пропуск недели не молчит; шаг понедельничной сводки это покажет)
. ../ops/maintenance.sh
maint_gate solver_weekly "$LOG" alert
. ../ops/remlab-tmp.sh
export TMPDIR="$REMLAB_TMP"

REFRESH_LOCK="${SW_REFRESH_LOCK:-$HOME/.remlab-refresh.lock}"
EXAM_LOCK="${SW_EXAM_LOCK:-$HERE/exam.flock}"
WAIT="${SW_LOCK_WAIT:-3600}"
STARTED_UTC="$(date -u '+%FT%TZ')"; STARTED_LOCAL="$(date '+%F %T')"; T0=${EPOCHSECONDS:-$(date +%s)}
# срок: ближайшие SW_DEADLINE_HHMM (в пределах суток) и не позже SW_MAX_SEC от старта
DL_HHMM="${SW_DEADLINE_HHMM:-10:10}"
DL=$(date -d "$DL_HHMM" +%s 2>/dev/null || echo 0)
[ "$DL" -le "$T0" ] && DL=$(date -d "tomorrow $DL_HHMM" +%s 2>/dev/null || echo $(( T0 + 86400 )))
MAXDL=$(( T0 + ${SW_MAX_SEC:-10800} ))
[ "$DL" -gt "$MAXDL" ] && DL=$MAXDL
export SW_DEADLINE_EPOCH="$DL"

mkdir -p "$(dirname "$STATUS_F")"
clean() { local s="${1//\"/}"; s="${s//\\/}"; echo "${s//$'\n'/ }" | cut -c1-200; }
write_status() {   # write_status <state> <rc> <sec> <cpu> <всего> <влезают> <проблемных> <причина>
  local fin=""; [ "$1" != running ] && fin="$(date -u '+%FT%TZ')"
  printf '{"state": "%s", "rc": %s, "date": "%s", "started_at": "%s", "started": "%s", "finished_at": "%s", "finished": "%s", "sec": %s, "cpu": "%s", "total": %s, "fit": %s, "bad": %s, "reason": "%s", "dry": %s, "host": "%s", "pid": %d}\n' \
    "$1" "$2" "${STARTED_LOCAL%% *}" "$STARTED_UTC" "$STARTED_LOCAL" "$fin" "$([ -n "$fin" ] && date '+%F %T')" "$3" "$4" "${5:-0}" "${6:-0}" "${7:-0}" \
    "$(clean "${8:-}")" "$([ "$DRY" = 1 ] && echo true || echo false)" "${HOSTNAME:-?}" "$$" > "$STATUS_F.tmp" && mv -f "$STATUS_F.tmp" "$STATUS_F"
}
steptime() {       # строка STEPTIME — тот же вид, что у step() в refresh_daily.sh (разбирает refresh_step_times.py)
  local a b; printf -v a '%(%FT%T)T' "$T0"; printf -v b '%(%FT%T)T' "$2"
  echo "STEPTIME name=solver_full start=$a end=$b sec=$(( $2 - T0 )) rc=$1 res=$3 cpu=$4" >> "$LOG"
}
cpu_now() {        # user+sys завершённых детей, секунды с десятыми (как в step()); нет /proc — «-»
  local st f tk=${CLK_TCK:-100}; { read -r st < "/proc/$$/stat"; } 2>/dev/null || { echo -; return; }
  st="${st##*) }"; read -r -a f <<< "$st"; echo "$(( ${f[13]:-0} + ${f[14]:-0} ))"
}
alert() { if [ "$DRY" = 1 ]; then ALERT_DRY=1 bash alert.sh "$1" >> "$LOG" 2>&1 || true; else bash alert.sh "$1" >> "$LOG" 2>&1 || true; fi; }
skip() {           # skip <причина>: замок не взяли / не успеть до срока — пропуск недели со статусом и тревогой
  local t1=${EPOCHSECONDS:-$(date +%s)}
  echo "solver_weekly: пропуск — $1" >> "$LOG"
  steptime 0 "$t1" skipped -
  echo "=== $(date '+%F %T') готово (пропуск) ===" >> "$LOG"
  write_status skipped 0 $(( t1 - T0 )) - 0 0 0 "$1"
  alert "remlab: недельная проверка расстановки (solver_full) ПРОПУЩЕНА — $1. Повтор: bash tools/scout/solver_weekly.sh на DEV (или в понедельник днём её итог покажет сводка)."
  exit 0
}

echo "=== $STARTED_LOCAL старт ===" >> "$LOG"
write_status running 0 0 - 0 0 0 ""
# ЗАМКИ — тот же файл у дневной сборки (`refresh_daily.sh`: exec 9>…; flock -n 9) и тот же exam.flock у `run.sh exam|smoke`; тут — с ожиданием
exec 9>"$REFRESH_LOCK"
flock -w "$WAIT" 9 || skip "дневная сборка держит замок ~/.remlab-refresh.lock дольше $WAIT с"
exec 7>>"$EXAM_LOCK"
flock -w "$WAIT" 7 || skip "экзамен банков держит exam.flock дольше $WAIT с"
echo "$(date '+%F %T') замки взяты (сборка, экзамен); срок $(date -d "@$DL" '+%F %T')" >> "$LOG"

OUT="$(mktemp -p "$REMLAB_TMP" solver-weekly.XXXXXX)"
trap 'rm -f "$OUT"' EXIT
C0=$(cpu_now)
if [ "$DRY" = 1 ]; then
  bash "$SELF" --run-solver --dry > "$OUT" 2>&1; rc=$?
else
  # заявка честная: 1 ядро, 2 ГБ, долгая (nice 10); ждать очередь не дольше 30 мин — иначе пропуск, замки отпускаются
  HEAVY="${SW_HEAVY:-bash ../ops/heavy-slot.sh}"     # SW_HEAVY — подмена очереди только в тестах
  $HEAVY solver-weekly --min-gb 2 --cores 1 --long --timeout 1800 -- bash "$SELF" --run-solver > "$OUT" 2>&1; rc=$?
fi
T1=${EPOCHSECONDS:-$(date +%s)}; C1=$(cpu_now)
CPU=-; if [ "$C0" != - ] && [ "$C1" != - ]; then CPU="$(( (C1 - C0) / ${CLK_TCK:-100} )).$(( (C1 - C0) % ${CLK_TCK:-100} * 10 / ${CLK_TCK:-100} ))"; fi
cat "$OUT" >> "$LOG"
SUM="$(grep -m1 '^Итого:' "$OUT" || true)"
FIT=0; TOTAL=0; BAD=0
if [ -n "$SUM" ]; then
  FIT="$(sed -n 's/^Итого: *\([0-9]*\)\/.*/\1/p' <<< "$SUM")"; TOTAL="$(sed -n 's/^Итого: *[0-9]*\/\([0-9]*\).*/\1/p' <<< "$SUM")"
  BAD="$(sed -n 's/.*проблемных *\([0-9]*\).*/\1/p' <<< "$SUM")"
fi
if grep -q 'не дождался очереди\|не дождался памяти' "$OUT"; then
  steptime "$rc" "$T1" skipped "$CPU"; echo "=== $(date '+%F %T') готово (пропуск) ===" >> "$LOG"
  write_status skipped "$rc" $(( T1 - T0 )) "$CPU" 0 0 0 "не дождался очереди тяжёлых прогонов (heavy-slot, 30 мин)"
  alert "remlab: недельная проверка расстановки (solver_full) ПРОПУЩЕНА — не дождалась очереди тяжёлых прогонов DEV. Повтор: bash tools/scout/solver_weekly.sh"
  exit 0
fi
if [ "$rc" = 125 ]; then skip "до срока (${DL_HHMM}) осталось меньше ${SW_MIN_SEC:-600} с"; fi
if [ "$rc" = 0 ] && [ -n "$SUM" ]; then
  steptime 0 "$T1" ok "$CPU"; echo "=== $(date '+%F %T') готово ===" >> "$LOG"
  write_status ok 0 $(( T1 - T0 )) "$CPU" "$TOTAL" "$FIT" "$BAD" ""
  echo "solver_weekly: ok — влезают $FIT/$TOTAL, проблемных $BAD, $(( (T1 - T0) / 60 )) мин" >> "$LOG"
  exit 0
fi
why="код $rc"; [ "$rc" = 124 ] && why="не уложился в срок (${DL_HHMM}, не дольше ${SW_MAX_SEC:-10800} с)"; [ "$rc" = 0 ] && why="нет итоговой строки «Итого:»"
steptime "$rc" "$T1" FAIL "$CPU"; echo "solver_full FAIL ($why)" >> "$LOG"; echo "=== $(date '+%F %T') готово (FAIL) ===" >> "$LOG"
write_status FAIL "$rc" $(( T1 - T0 )) "$CPU" "$TOTAL" "$FIT" "$BAD" "$why"
alert "remlab: недельная проверка расстановки (solver_full) УПАЛА — $why. Журнал: tools/scout/solver-weekly.log на DEV."
exit 1
