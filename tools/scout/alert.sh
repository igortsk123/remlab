#!/bin/bash
# Алерт владельцу: TG, если рядом лежит tools/scout/.env.alert (TG_BOT_TOKEN + TG_CHAT_ID, вне git);
# иначе — громкий маркер-файл refresh-alert.log (виден агенту и в git status не попадает).
# Причина (аудит 06.08): сбой крона 05.08 никто не заметил — refresh-status.json никто не читал.
#
# КОД ВОЗВРАТА ЧЕСТНЫЙ (04.09): 0 — доставлено в TG, 1 — TG не ответил, 2 — TG не настроен.
# Раньше скрипт возвращал 0 всегда и успех не логировал: в ночь на 04.09 сторож денег погасил пул
# и «сообщил» — а сообщение ушло в файл при пустом chat_id, и никто не мог отличить доставку от
# недоставки. Вызывающие, которым важен только факт попытки, пишут `bash alert.sh … || true`.
# Каждая отправка — строка в alert-sent.log (успех) или refresh-alert.log (провал/нет конфига).
#   bash alert.sh "текст сообщения"
#   ALERT_DRY=1 bash alert.sh "…"   # сухо: текст — в stdout, без TG и без записи в журналы (тесты)
# ПУСТОЙ ТЕКСТ — ГРОМКО (04.11): с 18.10 ночная сводка приходила как «алерт без текста», и это никого не насторожило
# 18 раз подряд (T-20261104-11). Пустой/пробельный текст = поломка у вызывающего, так и пишем.
set -u
cd "$(dirname "$0")"
MSG="${1:-}"
[ -z "${MSG//[[:space:]]/}" ] && MSG="remlab: ПУСТОЙ АЛЕРТ — вызывающий скрипт не собрал текст (ночная сводка? проверь tools/scout/refresh.log на DEV)"
STAMP="$(date '+%F %T')"
if [ "${ALERT_DRY:-0}" = "1" ]; then echo "[сухо] $MSG"; exit 0; fi
if [ -f .env.alert ]; then
  # shellcheck disable=SC1091
  . ./.env.alert
  if [ -n "${TG_BOT_TOKEN:-}" ] && [ -n "${TG_CHAT_ID:-}" ]; then
    if curl -sf --max-time 20 "https://api.telegram.org/bot${TG_BOT_TOKEN}/sendMessage" \
         -d chat_id="${TG_CHAT_ID}" --data-urlencode text="[$STAMP] $MSG" >/dev/null; then
      echo "[$STAMP] TG ok: $MSG" >> alert-sent.log
      exit 0
    fi
    echo "[$STAMP] TG FAIL: $MSG" >> refresh-alert.log
    exit 1
  fi
fi
echo "[$STAMP] (TG не настроен) $MSG" >> refresh-alert.log
exit 2
