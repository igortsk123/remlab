#!/bin/bash
# DEV-РЕНДЕР ДЛЯ ДЕМО (временный костыль, владелец 31.08): полный кадр 3D-сцены собирает
# DEV-машина, прод проксирует к ней через ssh-туннель и падает обратно на локальный рендер,
# если DEV молчит. Кадры доставляются scp прямо в раздаваемую папку прода.
# Автозапуск: cron @reboot. Логи: ~/scout-scenes/dev-render.log, dev-tunnel.log
cd "$(dirname "$0")" || exit 1
PY=$HOME/venvs/scout/bin/python
LOG=$HOME/scout-scenes/dev-render.log
TLOG=$HOME/scout-scenes/dev-tunnel.log

# сервис рендера (если не отвечает). РЕШАЕТ ТОЛЬКО ЗДОРОВЬЕ (demo-03, verify 14.10): прежний поиск процесса по
# шаблону «DEVBACKEND» не совпадал с командой запуска, и зависший процесс, держащий порт, никто не убирал — крон раз
# в 10 минут запускал копию, которая не могла занять порт, но писала «сервис запущен».
if ! curl -s -m 4 http://127.0.0.1:8600/health >/dev/null; then
  held=$(ss -ltnp 2>/dev/null | grep '127.0.0.1:8600 ' | grep -o 'pid=[0-9]*' | head -1 | cut -d= -f2)
  if [ -n "$held" ]; then
    echo "$(date '+%F %T') порт 8600 занят процессом $held, но он не отвечает — останавливаю" >>"$LOG"
    kill "$held" 2>/dev/null; sleep 3; kill -9 "$held" 2>/dev/null
  fi
  # SCENE3D_QUALITY=full БОЛЬШЕ НЕ СТАВИМ: он выключал отбраковку задних граней (её выключили
  # 31.08 из-за дырок в спинке дивана). Дырки лечены в упрощении (ADR-0165), отбраковка вернулась
  # порогом 0.5 — кадр быстрее на 20 %. Платный путь ставит quality=full сам, в своём процессе.
  # МОДЕЛЬ «РЕАЛИСТИЧНО» (demo-11, бенч 17.10, ADR-0302): gpt-image-2.5-sunburst, quality medium — решение владельца
  # ПРОМПТ improve-v4 (demo-14, ADR-0305): + список товаров с измеренным тоном — включён d8 после A/B 17.10
  REALISTIC_MODEL=openai/gpt-image-2.5-sunburst GPT_IMAGE_QUALITY=medium IMPROVE_PROMPT=v4 \
  SCENE3D=1 SCENE3D_PROCS=1 DRAFT_HOST=127.0.0.1 DRAFT_PORT=8600 \
  FRAME_INLINE=1 \
  SRC_PUSH='root@89.167.127.0:/opt/remlab/test/share/src/' \
  PUBLIC_BASE='https://remont-lab.online' \
  nohup "$PY" -u draft_service.py >>"$LOG" 2>&1 &
  ok=0; for _ in $(seq 1 15); do sleep 2; curl -s -m 2 http://127.0.0.1:8600/health >/dev/null && { ok=1; break; }; done
  if [ "$ok" = 1 ]; then echo "$(date '+%F %T') сервис запущен" >>"$LOG"
  else echo "$(date '+%F %T') сервис НЕ поднялся за 30 с" >>"$LOG"; fi
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
