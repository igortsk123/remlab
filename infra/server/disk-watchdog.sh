#!/usr/bin/env bash
# remlab disk watchdog — при заполнении корня САМ запускает cleanup, перемеряет и только тогда
# тревожит владельца в Telegram. Заодно ведёт наблюдение за памятью remlab-app.
#
# ЗАЧЕМ (04.09). Прежняя версия только писала в syslog раз в сутки (07:00). Диск заполнился
# вечером 03.09 в 20:31 — до утреннего опроса оставалось 10 часов, и всё это время приёмник
# мешей отвечал 507, а пул простаивал. Теперь: ежечасно (remlab-watchdog.timer), с действием.
#
# remlab-app (04.09): 11 перезапусков, 6 OOM за неделю при лимите 1 ГБ. Владелец решил: не
# поднимать лимит вслепую, а НАБЛЮДАТЬ — пишем RestartCount/OOMKilled/RSS в app-mem.log и
# тревожим, когда число перезапусков выросло с прошлого замера.
#
# TG — тот же .env, что у catalog-watchdog (/opt/remlab/catalog-watchdog/.env), дроссель 6 ч.
set -euo pipefail
THRESH=${1:-80}
BK=/opt/remlab/backups
ENVF=/opt/remlab/catalog-watchdog/.env
STAMP_DISK=$BK/.disk-alert-at
STAMP_APP=$BK/.app-restarts
mkdir -p "$BK"

tg() {  # сообщение владельцу; недоставка не отменяет действие
  logger -t remlab-watchdog "$1"
  echo "$(date '+%F %T') $1" >> "$BK/watchdog.log"
  [ -f "$ENVF" ] || return 0
  # shellcheck disable=SC1091
  . "$ENVF"
  [ -n "${TG_BOT_TOKEN:-}" ] && [ -n "${TG_CHAT_ID:-}" ] || return 0
  curl -sf --max-time 20 "https://api.telegram.org/bot${TG_BOT_TOKEN}/sendMessage" \
    -d chat_id="${TG_CHAT_ID}" --data-urlencode text="$1" >/dev/null \
    || logger -t remlab-watchdog "TG FAIL"
}
throttled() {  # $1 — файл-штамп, $2 — минимальный интервал в секундах
  [ -f "$1" ] && [ $(( $(date +%s) - $(cat "$1" 2>/dev/null || echo 0) )) -lt "$2" ]
}

# --- диск ---
use=$(df --output=pcent / | tail -1 | tr -dc '0-9')
if [ "${use:-0}" -ge "$THRESH" ]; then
  logger -t remlab-watchdog "root ${use}% >= ${THRESH}% — запускаю cleanup"
  /opt/remlab/scripts/cleanup.sh || true
  use2=$(df --output=pcent / | tail -1 | tr -dc '0-9')
  staging=$(find /opt/remlab/meshes -type d -name .staging 2>/dev/null | wc -l)
  meshes=$(du -sm /opt/remlab/meshes 2>/dev/null | cut -f1)
  if [ "${use2:-0}" -ge "$THRESH" ]; then
    msg="remlab ДИСК: корень ${use}% → после cleanup ${use2}% (порог ${THRESH}%) на $(hostname). Меши ${meshes:-?} МБ, .staging ${staging}. Cleanup не помог — нужен человек."
    if ! throttled "$STAMP_DISK" 21600; then tg "$msg"; date +%s > "$STAMP_DISK"; fi
  else
    tg "remlab диск: было ${use}%, cleanup освободил до ${use2}% (порог ${THRESH}%) — само, без человека."
  fi
fi

# --- remlab-app: память и перезапуски (наблюдение, не лечение) ---
if docker inspect remlab-app >/dev/null 2>&1; then
  rc=$(docker inspect remlab-app --format '{{.RestartCount}}')
  oom=$(docker inspect remlab-app --format '{{.State.OOMKilled}}')
  mem=$(docker stats --no-stream --format '{{.MemUsage}}' remlab-app 2>/dev/null || echo '?')
  host=$(free -m | awk 'NR==2{print $7" МБ свободно из "$2}')
  echo "$(date '+%F %T') restarts=$rc oom=$oom mem=$mem host=$host" >> "$BK/app-mem.log"
  prev=$(cat "$STAMP_APP" 2>/dev/null || echo "$rc")
  if [ "$rc" -gt "$prev" ]; then
    tg "remlab-app: перезапусков стало $rc (было $prev), OOMKilled=$oom, память $mem, хост: $host. Лимит 1 ГБ — смотри app-mem.log."
  fi
  echo "$rc" > "$STAMP_APP"
fi
