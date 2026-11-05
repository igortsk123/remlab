# shellcheck shell=bash
# ЗАМОК ОБСЛУЖИВАНИЯ DEV (onb-12, ADR-0330 п.6): пауза тяжёлых кронов на миграцию БД / подмену артефактов.
# Подключается тяжёлыми кронами (`. tools/ops/maintenance.sh; maint_gate <задача> <лог>`); ставит и снимает паузу
# `tools/ops/cron-pause.sh on|off|status`.
#
# Как устроено. Два файла в `$REMLAB_MAINT_DIR` (по умолчанию `~/.cache/remlab`):
#   maintenance.pause — метка паузы (until=<epoch>, since, reason); есть и не истекла — новые запуски выходят строкой в лог;
#   maintenance.lock  — flock: каждая задача держит его ОБЩИМ (shared) всё время работы (fd 8 наследуют дочерние процессы),
#                       `cron-pause.sh on` берёт ИСКЛЮЧИТЕЛЬНЫЙ — так он видит, что работающие задачи закончились.
# Порядок в `maint_gate` (метка → общий замок → метка ещё раз) закрывает гонку «пауза поставлена между проверкой и замком».
# Метка со сроком: забытая пауза не глушит кроны навсегда — истекла → задача идёт и пишет об этом в лог.

MAINT_DIR="${REMLAB_MAINT_DIR:-$HOME/.cache/remlab}"
MAINT_LOCK="$MAINT_DIR/maintenance.lock"
MAINT_PAUSE="$MAINT_DIR/maintenance.pause"
MAINT_ALERT="${MAINT_ALERT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../scout" 2>/dev/null && pwd)/alert.sh}"

# maint_active — 0: пауза действует (печатает «до …; причина …»); 1: паузы нет (истёкшая — печатает «истекла …»)
maint_active() {
  [ -f "$MAINT_PAUSE" ] || return 1
  local until reason now
  until=$(sed -n 's/^until=//p' "$MAINT_PAUSE" | head -1)
  reason=$(sed -n 's/^reason=//p' "$MAINT_PAUSE" | head -1)
  # метка без срока (правлена руками) — срок 6 ч от её записи, а не «навсегда»
  case "$until" in ''|*[!0-9]*) until=$(( $(stat -c %Y "$MAINT_PAUSE") + 6 * 3600 ));; esac
  now=$(date +%s)
  if [ "$now" -lt "$until" ]; then
    echo "до $(date -d "@$until" '+%F %T'); причина: ${reason:-не указана}"
    return 0
  fi
  echo "пауза обслуживания истекла $(date -d "@$until" '+%F %T') (${reason:-без причины}) — работаем; снять метку: tools/ops/cron-pause.sh off"
  return 1
}

# maint_gate <задача> <лог> [alert] — на паузе выходит (exit 0) со строкой в лог; иначе держит общий замок до конца скрипта.
# `alert` — ещё и сообщение владельцу (для ежедневного цикла: пропуск дня не должен пройти молча).
maint_gate() {
  local job="$1" log="${2:-/dev/stderr}" how="${3:-}" why
  _maint_skip() {
    echo "$(date '+%F %T') $job: пауза обслуживания ($1) — выходим, ничего не делали" >> "$log"
    [ "$how" = alert ] && { bash "$MAINT_ALERT" "⏸ remlab: «$job» пропущен — пауза обслуживания ($1)" >> "$log" 2>&1 || true; }
    exit 0
  }
  if why=$(maint_active); then _maint_skip "$why"; fi
  [ -n "$why" ] && echo "$(date '+%F %T') $job: $why" >> "$log"
  mkdir -p "$MAINT_DIR"
  exec 8>>"$MAINT_LOCK"
  flock -s -n 8 || _maint_skip "пауза включается прямо сейчас — замок занят"
  if why=$(maint_active); then _maint_skip "$why"; fi
  return 0
}
