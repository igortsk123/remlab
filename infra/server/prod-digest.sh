#!/usr/bin/env bash
# Дайджест прода раз в сутки (план b2b-09, ADR-0266; remlab-prod-digest.timer 06:00 UTC): одно сообщение в Telegram
# — сайт и база, диск, возраст витрины демо и последнего дампа, ссылки менеджеров и сигналы за сутки, ошибки 5xx
# по журналу Caddy. Проверка без отправки: DRY=1 prod-digest.sh
set -uo pipefail
ENVF=/opt/remlab/catalog-watchdog/.env
SITE=${SITE:-https://remont-lab.online}
psqlq() { docker exec -i remlab-db psql -U remlab -d remlab -qtA -c "$1" 2>/dev/null; }

h=$(curl -s --max-time 15 "$SITE/api/health" || true)
ok=$(printf '%s' "$h" | grep -q '"ok":true' && echo "работает" || echo "НЕ ОТВЕЧАЕТ")
checks=$(printf '%s' "$h" | sed -n 's/.*"checks":{\([^}]*\)}.*/\1/p' | tr -d '"')
ver=$(printf '%s' "$h" | sed -n 's/.*"version":"\([0-9a-f]\{7\}\).*/\1/p')
disk=$(df --output=pcent / | tail -1 | tr -dc '0-9')
demo_age=$(( ( $(date +%s) - $(stat -c %Y /opt/remlab/demo/demo-data.json 2>/dev/null || echo 0) ) / 3600 ))
dump=$(ls -t /opt/remlab/backups/db-*.sql.gz 2>/dev/null | head -1)
dump_age=$([ -n "$dump" ] && echo $(( ( $(date +%s) - $(stat -c %Y "$dump") ) / 3600 )) || echo "нет")
sends=$(psqlq "select count(*) from sends where created_at > now() - interval '1 day'")
opened=$(psqlq "select count(*) from sends where opened_at > now() - interval '1 day'")
sig=$(psqlq "select coalesce(string_agg(status || ' ' || n, ', '), 'нет') from (select status, count(*) n from signal_outbox where created_at > now() - interval '1 day' group by 1) x")
cols=$(psqlq "select count(*) from collections where created_at > now() - interval '1 day'")
e5=$(docker logs --since 24h remlab-caddy 2>&1 | grep -c '"status":5[0-9][0-9]' || true)
top5=$(docker logs --since 24h remlab-caddy 2>&1 | grep '"status":5[0-9][0-9]' | sed -n 's/.*"uri":"\([^"?]*\).*/\1/p' | sort | uniq -c | sort -rn | head -3 | awk '{printf "%s%s ×%s", (NR>1?", ":""), $2, $1}')

warn=""
[ "$ok" = "работает" ] || warn+="⚠ сайт не отвечает. "
[ "${disk:-0}" -ge 80 ] && warn+="⚠ диск ${disk}%. "
[ "$demo_age" -gt 48 ] && warn+="⚠ витрина демо не обновлялась ${demo_age} ч. "
[ "$dump_age" = "нет" ] || [ "$dump_age" -gt 30 ] && warn+="⚠ ночного дампа нет или он старый. "
[ "${e5:-0}" -gt 20 ] && warn+="⚠ много ошибок 5xx. "

msg="📋 remont-lab за сутки
${warn:+$warn
}Сайт: $ok${ver:+ (версия $ver)}${checks:+; $checks}
Диск сервера: ${disk}% · витрина демо: ${demo_age} ч назад · дамп базы: ${dump_age} ч назад
Ссылки менеджеров: отправлено ${sends:-?}, открыто ${opened:-?}; сигналы: ${sig:-?}; коллекций сохранено: ${cols:-?}
Ошибки 5xx: ${e5:-0}${top5:+ ($top5)}"

if [ -n "${DRY:-}" ]; then echo "$msg"; exit 0; fi
logger -t remlab-digest "digest sent"
[ -f "$ENVF" ] || exit 0
# shellcheck disable=SC1091
. "$ENVF"
[ -n "${TG_BOT_TOKEN:-}" ] && [ -n "${TG_CHAT_ID:-}" ] || exit 0
curl -sf --max-time 20 "https://api.telegram.org/bot${TG_BOT_TOKEN}/sendMessage" -d chat_id="${TG_CHAT_ID}" --data-urlencode text="$msg" >/dev/null \
  || logger -t remlab-digest "TG FAIL"
