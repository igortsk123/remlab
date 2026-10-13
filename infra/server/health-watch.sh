#!/usr/bin/env bash
# Сторож доступности прода (план b2b-09, ADR-0266): раз в 2 минуты (remlab-health-watch.timer) проверяет
# то же, что видит покупатель, — через Caddy и TLS: /api/health (база внутри), /demo/, рендер кадров.
# Две неудачи подряд → тревога в Telegram (тот же бот, что у disk-watchdog); восстановилось → «снова работает».
# Внешний монитор (вне этого сервера) — выбор владельца; этот ловит всё, кроме смерти самого сервера.
set -uo pipefail
BK=/opt/remlab/backups
ENVF=/opt/remlab/catalog-watchdog/.env
STATE=${STATE:-$BK/.health-state}     # «ok» или «fail:N»; проверка без тревоги: DRY=1 STATE=/tmp/x SITE=…
SITE=${SITE:-https://remont-lab.online}

tg() {
  [ -n "${DRY:-}" ] && { echo "DRY TG: $1"; return 0; }
  logger -t remlab-health "$1"
  echo "$(date '+%F %T') $1" >> "$BK/watchdog.log"
  [ -f "$ENVF" ] || return 0
  # shellcheck disable=SC1091
  . "$ENVF"
  [ -n "${TG_BOT_TOKEN:-}" ] && [ -n "${TG_CHAT_ID:-}" ] || return 0
  curl -sf --max-time 20 "https://api.telegram.org/bot${TG_BOT_TOKEN}/sendMessage" \
    -d chat_id="${TG_CHAT_ID}" --data-urlencode text="$1" >/dev/null || logger -t remlab-health "TG FAIL"
}

bad=()
body=$(curl -s --max-time 15 -w '\n%{http_code}' "$SITE/api/health" || true)
code=$(printf '%s' "$body" | tail -n1)
if [ "$code" != 200 ] || ! printf '%s' "$body" | grep -q '"ok":true'; then
  why=$(printf '%s' "$body" | sed -n 's/.*"checks":{\([^}]*\)}.*/\1/p')
  bad+=("сайт: health $code${why:+ ($why)}")
fi
c=$(curl -s -o /dev/null --max-time 15 -w '%{http_code}' "$SITE/demo/" || true)
[ "$c" = 200 ] || bad+=("демо: $c")
c=$(curl -s -o /dev/null --max-time 15 -w '%{http_code}' "$SITE/api/draft/health" || true)
[ "$c" = 200 ] || bad+=("рендер кадров: $c")

prev=$(cat "$STATE" 2>/dev/null || echo ok)
if [ ${#bad[@]} -eq 0 ]; then
  case "$prev" in fail:*) n=${prev#fail:}; [ "$n" -ge 2 ] && tg "✅ remont-lab снова работает";; esac
  echo ok > "$STATE"
  exit 0
fi
n=1; case "$prev" in fail:*) n=$(( ${prev#fail:} + 1 ));; esac
echo "fail:$n" > "$STATE"
# тревога на второй неудаче подряд (одна осечка сети — не повод будить) и затем раз в час (30 проверок)
if [ "$n" -eq 2 ] || [ $(( n % 30 )) -eq 0 ]; then
  msg=$(printf '%s; ' "${bad[@]}")
  tg "🔴 remont-lab: ${msg%; } — подряд $n проверок (раз в 2 мин)"
fi
