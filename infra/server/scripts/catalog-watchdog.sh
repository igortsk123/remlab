#!/usr/bin/env bash
# remlab catalog watchdog — «утренний прогон каталога состоялся?» (план catalog-load-hardening П1.3).
# Крутится на ПРОД-сервере, независимо от DEV-машины, где живёт сам прогон: DEV выключена или крон
# не сработал — DEV сама об этом не скажет. Читает статус, который refresh_daily.sh публикует в конце
# каждого прогона в /opt/remlab/test/status/refresh-status.json, и шлёт в Telegram, если дата в нём
# не сегодняшняя или прогона нет вовсе. Таймер: remlab-catalog-watchdog.timer (15:30 UTC — прогон
# стартует 10:40 UTC и длится ~3,5 ч). Kill-switch: touch /opt/remlab/catalog-watchdog/DISABLED.
set -euo pipefail
DIR=/opt/remlab/catalog-watchdog
STATUS=/opt/remlab/test/status/refresh-status.json
[ -f "$DIR/DISABLED" ] && exit 0
today=$(date -u +%F)
if [ ! -f "$STATUS" ]; then
  msg="remlab каталог: статуса прогона НЕТ вовсе ($STATUS) — DEV-машина не публикует"
else
  d=$(sed -n 's/.*"date":"\([0-9-]*\)".*/\1/p' "$STATUS" | head -1)
  fin=$(sed -n 's/.*"finished":"\([^"]*\)".*/\1/p' "$STATUS" | head -1)
  if [ "$d" = "$today" ] && [ -n "$fin" ]; then exit 0; fi
  msg="remlab каталог: утренний прогон $today НЕ СОСТОЯЛСЯ — последний статус: дата ${d:-?}, финиш ${fin:-?} (DEV-машина выключена или крон не сработал)"
fi
logger -t remlab-catalog-watchdog "$msg"
echo "$(date -u '+%F %T') $msg" >> "$DIR/watchdog.log"
if [ -f "$DIR/.env" ]; then
  # shellcheck disable=SC1091
  . "$DIR/.env"
  if [ -n "${TG_BOT_TOKEN:-}" ] && [ -n "${TG_CHAT_ID:-}" ]; then
    curl -sf --max-time 20 "https://api.telegram.org/bot${TG_BOT_TOKEN}/sendMessage" \
      -d chat_id="${TG_CHAT_ID}" --data-urlencode text="$msg" >/dev/null || logger -t remlab-catalog-watchdog "TG FAIL"
  fi
fi
