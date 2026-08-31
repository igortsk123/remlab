#!/bin/bash
# DEV-РЕНДЕР ДЛЯ ДЕМО (временный костыль, владелец 31.08): полный кадр 3D-сцены собирает
# DEV-машина, прод проксирует к ней через ssh-туннель и падает обратно на локальный рендер,
# если DEV молчит. Кадры доставляются scp прямо в раздаваемую папку прода.
# Автозапуск: cron @reboot. Логи: ~/scout-scenes/dev-render.log, dev-tunnel.log
cd "$(dirname "$0")" || exit 1
PY=$HOME/venvs/scout/bin/python
LOG=$HOME/scout-scenes/dev-render.log
TLOG=$HOME/scout-scenes/dev-tunnel.log

# сервис рендера (если не бежит)
if ! pgrep -f "draft_service.py.*DEVBACKEND" >/dev/null 2>&1 && ! curl -s -m 2 http://127.0.0.1:8600/health >/dev/null; then
  SCENE3D=1 SCENE3D_QUALITY=full SCENE3D_PROCS=1 DRAFT_HOST=127.0.0.1 DRAFT_PORT=8600 \
  FRAME_INLINE=1 \
  PUBLIC_BASE='https://remont-lab.online' \
  nohup "$PY" -u draft_service.py >>"$LOG" 2>&1 &
  echo "$(date '+%F %T') сервис запущен" >>"$LOG"
fi

# ssh-туннель: прод-шлюз docker-сети 172.18.0.1:8601 → DEV 127.0.0.1:8600 (наружу не торчит)
if ! pgrep -f "ssh .*172.18.0.1:8601" >/dev/null 2>&1; then
  nohup bash -c 'while true; do
    ssh -N -o BatchMode=yes -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 \
        -o ServerAliveCountMax=3 -R 172.18.0.1:8601:127.0.0.1:8600 root@89.167.127.0
    echo "$(date "+%F %T") туннель упал — перезапуск через 15с"
    sleep 15
  done' >>"$TLOG" 2>&1 &
  echo "$(date '+%F %T') туннель запущен" >>"$TLOG"
fi
