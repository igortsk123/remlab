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
  # JSON читаем python3 (есть на сервере), а не sed: поля структурированные (overall, fails)
  read -r d fin overall fails < <(python3 - "$STATUS" <<'PY'
import json, sys
try:
    s = json.load(open(sys.argv[1]))
except Exception:
    print('? ? broken -'); sys.exit(0)
print(s.get('date') or '?', (s.get('finished_at') or s.get('finished') or '?').replace(' ', 'T'),
      s.get('overall') or ('ok' if s.get('finished') else '?'), ','.join(s.get('fails') or []) or '-')
PY
)
  if [ "$d" = "$today" ] && [ "$overall" = "FAIL" ]; then
    # локальная тревога с DEV могла не уйти (нет TG, сеть) — сторож дублирует сбой
    msg="remlab каталог: прогон $today завершился С ОШИБКАМИ — FAIL: ${fails} (см. refresh.log на DEV)"
  elif [ "$d" = "$today" ] && [ "$fin" != "?" ]; then
    exit 0
  else
    msg="remlab каталог: утренний прогон $today НЕ СОСТОЯЛСЯ — последний статус: дата ${d:-?}, финиш ${fin:-?}, итог ${overall:-?} (DEV-машина выключена или крон не сработал)"
  fi
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
