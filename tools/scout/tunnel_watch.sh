#!/bin/bash
# СТОРОЖ ТУННЕЛЯ DEV-РЕНДЕРА (T-20261020-20): после перезагрузки DEV зависшая сессия прежнего туннеля держала
# 172.18.0.1:8601 на проде, юнит туннеля 10+ часов писал «remote port forwarding failed», а платные фото молча шли
# через медленный запасной рендер прода (630 с вместо ~33). Тревога владельцу — если туннель не встаёт 10 мин подряд,
# не чаще раза в час. Признак «не встаёт сейчас»: последние строки dev-tunnel.log — отказ, и журнал пишется
# (юнит перезапускает ssh каждые 3 с, при живом туннеле журнал молчит). Зовёт `dev_render_backend.sh` (крон */10).
# Переопределения — для проверки на стенде: TUNNEL_LOG, TUNNEL_STATE (папка отметок), ALERT_CMD, NOW (секунды).
set -u
TLOG=${TUNNEL_LOG:-$HOME/scout-scenes/dev-tunnel.log}
ST=${TUNNEL_STATE:-$HOME/scout-scenes}
ALERT_CMD=${ALERT_CMD:-"bash $(dirname "$0")/alert.sh"}
NOW=${NOW:-$(date +%s)}
SINCE=$ST/.tunnel-fail-since; SENT=$ST/.tunnel-alert-at
FAIL_MIN=10; REPEAT_MIN=60

failing=0
if [ -f "$TLOG" ] && tail -n 20 "$TLOG" | grep -av 'СТОРОЖ' | tail -n 1 | grep -aq 'remote port forwarding failed' \
   && [ $(( NOW - $(stat -c %Y "$TLOG") )) -lt 120 ]; then failing=1; fi

if [ "$failing" = 0 ]; then rm -f "$SINCE"; exit 0; fi
[ -f "$SINCE" ] || echo "$NOW" >"$SINCE"
since=$(cat "$SINCE" 2>/dev/null || echo "$NOW")
[ $(( NOW - since )) -lt $(( FAIL_MIN * 60 )) ] && exit 0
last=$(cat "$SENT" 2>/dev/null || echo 0)
[ $(( NOW - last )) -lt $(( REPEAT_MIN * 60 )) ] && exit 0
mins=$(( (NOW - since) / 60 ))
$ALERT_CMD "remlab: туннель DEV-рендера не встаёт ${mins} мин — порт 8601 на проде занят («remote port forwarding failed»). Платные фото идут через медленный запасной рендер. Проверить: на проде ss -ltnp | grep 8601 — зависшую сессию sshd остановить по PID (не основной sshd)."
echo "$NOW" >"$SENT"
echo "$(date '+%F %T') СТОРОЖ: туннель не встаёт ${mins} мин — тревога отправлена" >>"$TLOG"
