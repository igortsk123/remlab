#!/bin/bash
# Алерт владельцу: TG, если рядом лежит tools/scout/.env.alert (TG_BOT_TOKEN + TG_CHAT_ID, вне git);
# иначе — громкий маркер-файл refresh-alert.log (виден агенту и в git status не попадает).
# Причина (аудит 06.08): сбой крона 05.08 никто не заметил — refresh-status.json никто не читал.
#   bash alert.sh "текст сообщения"
set -u
cd "$(dirname "$0")"
MSG="${1:-remlab: алерт без текста}"
STAMP="$(date '+%F %T')"
if [ -f .env.alert ]; then
  # shellcheck disable=SC1091
  . ./.env.alert
  if [ -n "${TG_BOT_TOKEN:-}" ] && [ -n "${TG_CHAT_ID:-}" ]; then
    curl -sf --max-time 20 "https://api.telegram.org/bot${TG_BOT_TOKEN}/sendMessage" \
      -d chat_id="${TG_CHAT_ID}" --data-urlencode text="[$STAMP] $MSG" >/dev/null \
      && exit 0
    echo "[$STAMP] TG не отправился, пишу в файл" >> refresh-alert.log
  fi
fi
echo "[$STAMP] $MSG" >> refresh-alert.log
