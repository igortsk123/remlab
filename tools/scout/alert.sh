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
# ПОВТОР (05.11, урок 551, план ops-alert-retry): связь DEV → api.telegram.org рвётся на части запросов (таймаут/сброс),
# сводка 05.11 не дошла с одной попытки. До ALERT_TRIES (3) попыток, паузы ALERT_PAUSES («15 45» с), `--max-time 20` на
# попытку — худшее время ~2 мин. HTTP 4xx (кроме 429) — ошибка запроса, не повторяем; 429 — пауза retry_after (≤ 60 с).
# Текст длиннее 4 000 знаков — частями «(1/2) …» по строкам, у каждой свои попытки; часть не ушла — остальные не шлём.
# В журналы — только код curl и HTTP, адрес с токеном не пишется никогда.
set -u
cd "$(dirname "$0")"
MSG="${1:-}"
[ -z "${MSG//[[:space:]]/}" ] && MSG="remlab: ПУСТОЙ АЛЕРТ — вызывающий скрипт не собрал текст (ночная сводка? проверь tools/scout/refresh.log на DEV)"
STAMP="$(date '+%F %T')"
if [ "${ALERT_DRY:-0}" = "1" ]; then echo "[сухо] $MSG"; exit 0; fi
TRIES="${ALERT_TRIES:-3}"
read -r -a PAUSES <<< "${ALERT_PAUSES:-15 45}"
MAX_CHARS=4000

split_msg() {                  # MSG → PARTS[] по строкам, не длиннее MAX_CHARS знаков (в C-локали крона ${#} — байты)
  local LC_ALL=C.UTF-8 cur="" line
  PARTS=()
  while IFS= read -r line || [ -n "$line" ]; do
    while [ "${#line}" -gt "$MAX_CHARS" ]; do                 # одна строка длиннее предела — режем по знакам
      [ -n "$cur" ] && { PARTS+=("$cur"); cur=""; }
      PARTS+=("${line:0:$MAX_CHARS}"); line="${line:$MAX_CHARS}"
    done
    if [ -z "$cur" ]; then cur="$line"
    elif [ $(( ${#cur} + 1 + ${#line} )) -le "$MAX_CHARS" ]; then cur="$cur"$'\n'"$line"
    else PARTS+=("$cur"); cur="$line"; fi
  done <<< "$MSG"
  [ -n "$cur" ] && PARTS+=("$cur")
  [ "${#PARTS[@]}" -gt 0 ] || PARTS=("$MSG")
}

send_part() {                  # send_part <текст> → 0 доставлено; ATTEMPT, LAST_RC (curl), LAST_HTTP — для журнала
  local text="$1" resp pause ra
  ATTEMPT=0
  while [ "$ATTEMPT" -lt "$TRIES" ]; do
    ATTEMPT=$((ATTEMPT + 1))
    resp="$(curl -s --max-time 20 -w '\n%{http_code}' "https://api.telegram.org/bot${TG_BOT_TOKEN}/sendMessage" \
              -d chat_id="${TG_CHAT_ID}" --data-urlencode text="[$STAMP] $text")"
    LAST_RC=$?; LAST_HTTP="${resp##*$'\n'}"; LAST_HTTP="${LAST_HTTP:-000}"
    [ "$LAST_RC" = 0 ] && [[ "$LAST_HTTP" == 2?? ]] && return 0
    [[ "$LAST_HTTP" == 4?? ]] && [ "$LAST_HTTP" != 429 ] && return 1       # запрос неверный — повтор не поможет
    [ "$ATTEMPT" -lt "$TRIES" ] || break
    pause=0; [ "${#PAUSES[@]}" -gt 0 ] && pause="${PAUSES[$((ATTEMPT - 1))]:-${PAUSES[$((${#PAUSES[@]} - 1))]}}"
    if [ "$LAST_HTTP" = 429 ]; then
      ra="$(grep -o '"retry_after":[0-9]*' <<< "$resp" | grep -o '[0-9]*$')"
      [ -n "$ra" ] && pause=$(( ra > 60 ? 60 : ra ))
    fi
    sleep "$pause"
  done
  return 1
}

if [ -f .env.alert ]; then
  # shellcheck disable=SC1091
  . ./.env.alert
  if [ -n "${TG_BOT_TOKEN:-}" ] && [ -n "${TG_CHAT_ID:-}" ]; then
    split_msg
    n="${#PARTS[@]}"
    for i in "${!PARTS[@]}"; do
      tag=""; [ "$n" -gt 1 ] && tag="($((i + 1))/$n) "
      if send_part "$tag${PARTS[$i]}"; then
        try=""; [ "$ATTEMPT" -gt 1 ] && try=" (попытка $ATTEMPT)"
        echo "[$STAMP] TG ok$try: $tag${PARTS[$i]}" >> alert-sent.log
      else
        rest=""; [ "$n" -gt 1 ] && rest=", часть $((i + 1))/$n, остальные не отправлялись"
        echo "[$STAMP] TG FAIL (попыток $ATTEMPT, curl $LAST_RC, HTTP $LAST_HTTP$rest): $MSG" >> refresh-alert.log
        exit 1
      fi
    done
    exit 0
  fi
fi
echo "[$STAMP] (TG не настроен) $MSG" >> refresh-alert.log
exit 2
