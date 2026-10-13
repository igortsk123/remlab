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

# --- безопасность (план b2b-01, ADR-0248/0256): ежечасно, тем же каналом ---
# 1) Контакты «отправить себе» живут 90 дней — удаляем просроченные, даже если новых заявок нет;
#    там же чистим старые окна счётчиков частоты.
docker exec remlab-db psql -U remlab -d remlab -q -c \
  "delete from share_requests where expires_at < now(); delete from rate_limits where window_start < now() - interval '2 days'; delete from dedup_marks where at < now() - interval '1 day'; delete from tg_updates where created_at < now() - interval '7 days';" \
  >/dev/null 2>&1 || logger -t remlab-watchdog "share_requests: чистка не удалась"
# 2) Данные людей в файлах под веб-корнем (инцидент 13.10) — тревога, если снова появились.
STAMP_PII=$BK/.pii-alert-at
pii=$(find /opt/remlab/test /opt/remlab/demo -path '*/_queue/*' -type f 2>/dev/null | wc -l)
if [ "${pii:-0}" -gt 0 ] && ! throttled "$STAMP_PII" 21600; then
  tg "remlab БЕЗОПАСНОСТЬ: под веб-корнем снова лежат файлы очереди (${pii} шт., папки _queue) — там могут быть контакты людей. Перенести в базу и удалить."
  date +%s > "$STAMP_PII"
fi
# 3) Конфиг входа правили на сервере руками после деплоя — следующий деплой остановится.
STAMP_CADDY=$BK/.caddy-drift-at
CD=/opt/remlab/caddy
if [ -f "$CD/Caddyfile.deployed" ] && ! cmp -s "$CD/Caddyfile" "$CD/Caddyfile.deployed" \
   && ! throttled "$STAMP_CADDY" 21600; then
  tg "remlab: Caddyfile на сервере отличается от выкаченного из репозитория — правку надо перенести в caddy/Caddyfile, иначе следующий деплой остановится."
  date +%s > "$STAMP_CADDY"
fi
