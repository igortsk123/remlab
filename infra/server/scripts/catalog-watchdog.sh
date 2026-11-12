#!/usr/bin/env bash
# remlab catalog watchdog — «утренний прогон каталога состоялся?» (план catalog-load-hardening П1.3).
# Крутится на ПРОД-сервере, независимо от DEV-машины, где живёт сам прогон: DEV выключена или крон
# не сработал — DEV сама об этом не скажет. Читает статус, который refresh_daily.sh публикует
# в /opt/remlab/test/status/refresh-status.json, и шлёт в Telegram, если дата в нём не сегодняшняя,
# прогона нет вовсе или он кончился с FAIL. Таймер: remlab-catalog-watchdog.timer (15:30 UTC, прогон стартует 10:40 UTC).
# Kill-switch: touch /opt/remlab/catalog-watchdog/DISABLED.
#
# «ИДЁТ» ≠ «НЕ СОСТОЯЛСЯ» (T-20261112-56/2, план refresh-split-01): прогон идёт 5–7 ч и кончается после 15:30, а статус
# раньше публиковался только в конце — сторож 08–12.11 каждый день слал ложное «НЕ СОСТОЯЛСЯ». Теперь refresh_daily.sh сразу
# после старта публикует статус `overall: running` (дата, started_at, без finished_at), конец прогона его перезаписывает.
# Видит сегодняшний running — не кричит, а ждёт (опрос раз в CW_POLL с) окончания: кончился FAIL — тревога как раньше, ok/warn —
# тихо; не кончился к started_at + CW_MAX_SEC (10 ч) — тревога «идёт слишком долго: завис или DEV выключилась посреди прогона».
# Не стартовал вовсе (дата не сегодня) — тревога в 15:30, как раньше. Тип службы oneshot — у systemd без предела времени старта.
# Весь код — в main(), вызов в одной строке с exit: выкладка (scp поверх файла) посреди ожидания не ломает идущий процесс.
set -euo pipefail
DIR=${CW_DIR:-/opt/remlab/catalog-watchdog}
STATUS=${CW_STATUS:-/opt/remlab/test/status/refresh-status.json}
POLL=${CW_POLL:-600}
MAX_SEC=${CW_MAX_SEC:-36000}

read_status() {   # → «дата финиш итог старт fails»; JSON читаем python3 (есть на сервере), а не sed
  python3 - "$STATUS" <<'PY'
import json, sys
try:
    s = json.load(open(sys.argv[1]))
except Exception:
    print('? ? broken ? -'); sys.exit(0)
print(s.get('date') or '?', (s.get('finished_at') or s.get('finished') or '?').replace(' ', 'T'),
      s.get('overall') or ('ok' if s.get('finished') else '?'), (s.get('started_at') or '?').replace(' ', 'T'),
      ','.join(s.get('fails') or []) or '-')
PY
}

alarm() {
  local msg="$1"
  [ "${CW_DRY:-0}" = 1 ] || logger -t remlab-catalog-watchdog "$msg"
  echo "$(date -u '+%F %T') $msg" >> "$DIR/watchdog.log"
  if [ -f "$DIR/.env" ]; then
    # shellcheck disable=SC1091
    . "$DIR/.env"
    if [ -n "${TG_BOT_TOKEN:-}" ] && [ -n "${TG_CHAT_ID:-}" ]; then
      curl -sf --max-time 20 "https://api.telegram.org/bot${TG_BOT_TOKEN}/sendMessage" \
        -d chat_id="${TG_CHAT_ID}" --data-urlencode text="$msg" >/dev/null || logger -t remlab-catalog-watchdog "TG FAIL"
    fi
  fi
}

main() {
  [ -f "$DIR/DISABLED" ] && return 0
  local today d fin overall started fails deadline t0
  today=$(date -u +%F)
  if [ ! -f "$STATUS" ]; then
    alarm "remlab каталог: статуса прогона НЕТ вовсе ($STATUS) — DEV-машина не публикует"; return 0
  fi
  read -r d fin overall started fails < <(read_status)
  if [ "$d" = "$today" ] && [ "$overall" = "running" ]; then
    t0=$(date -u -d "$started" +%s 2>/dev/null || date -u +%s)
    deadline=$(( t0 + MAX_SEC ))
    while [ "$overall" = "running" ] && [ "$(date -u +%s)" -lt "$deadline" ]; do
      sleep "$POLL"
      read -r d fin overall started fails < <(read_status)
    done
    if [ "$overall" = "running" ]; then
      alarm "remlab каталог: прогон $today начался ${started} и идёт дольше $(( MAX_SEC / 3600 )) ч — завис или DEV-машина выключилась посреди прогона (см. refresh.log на DEV)"
      return 0
    fi
  fi
  if [ "$d" = "$today" ] && [ "$overall" = "FAIL" ]; then
    # локальная тревога с DEV могла не уйти (нет TG, сеть) — сторож дублирует сбой
    alarm "remlab каталог: прогон $today завершился С ОШИБКАМИ — FAIL: ${fails} (см. refresh.log на DEV)"
  elif [ "$d" = "$today" ] && [ "$fin" != "?" ]; then
    return 0
  else
    alarm "remlab каталог: утренний прогон $today НЕ СОСТОЯЛСЯ — последний статус: дата ${d:-?}, финиш ${fin:-?}, итог ${overall:-?} (DEV-машина выключена или крон не сработал)"
  fi
}

main "$@"; exit $?
