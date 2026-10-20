#!/bin/bash
# DEV-РЕНДЕР ДЛЯ ДЕМО (временный костыль, владелец 31.08): полный кадр 3D-сцены собирает
# DEV-машина, прод проксирует к ней через ssh-туннель и падает обратно на локальный рендер,
# если DEV молчит. Кадры доставляются scp прямо в раздаваемую папку прода.
# СЕРВИС И ТУННЕЛЬ — пользовательские юниты systemd (b2b-09, T-20261018-04): tools/scout/systemd/*.service,
# Restart=always. Этот скрипт — только СТОРОЖ (крон @reboot и каждые 10 мин): ставит юниты, если их файлы
# изменились, и перезапускает сервис, если /health молчит. Сам ничего через nohup не держит.
# Логи: ~/scout-scenes/dev-render.log (кадры), dev-tunnel.log (туннель); пишут сами юниты.
cd "$(dirname "$0")" || exit 1
LOG=$HOME/scout-scenes/dev-render.log
TLOG=$HOME/scout-scenes/dev-tunnel.log
UNITS=(remlab-render remlab-render-tunnel)
UDIR=$HOME/.config/systemd/user
# крон не даёт шины пользователя — без неё systemctl --user не достучится до менеджера (linger держит его живым)
export XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}
export DBUS_SESSION_BUS_ADDRESS=${DBUS_SESSION_BUS_ADDRESS:-unix:path=$XDG_RUNTIME_DIR/bus}
say() { echo "$(date '+%F %T') $*" >>"$LOG"; }
if ! systemctl --user show-environment >/dev/null 2>&1; then
  say "СТОРОЖ: менеджер systemd пользователя недоступен — рендер и туннель не проверить"; exit 1
fi

# 1. юниты: файл в репо изменился (или его нет) → поставить и включить
changed=0
mkdir -p "$UDIR"
for u in "${UNITS[@]}"; do
  if ! cmp -s "systemd/$u.service" "$UDIR/$u.service"; then
    install -m 644 "systemd/$u.service" "$UDIR/$u.service" && changed=1 && say "СТОРОЖ: юнит $u поставлен/обновлён"
  fi
done
[ "$changed" = 1 ] && systemctl --user daemon-reload
for u in "${UNITS[@]}"; do systemctl --user is-enabled -q "$u" || systemctl --user enable -q "$u"; done

# 2. остатки прежнего запуска через nohup (до 18.10): процесс НЕ из юнита, который держит порт 8600 или туннель 8601,
#    мешает юниту (порт занят / ExitOnForwardFailure) — убрать. Поиск — по ps и cgroup, не по pgrep -f (урок 399).
in_unit() { grep -q "/$2.service" "/proc/$1/cgroup" 2>/dev/null; }
held=$(ss -ltnp 2>/dev/null | grep '127.0.0.1:8600 ' | grep -o 'pid=[0-9]*' | head -1 | cut -d= -f2)
if [ -n "$held" ] && ! in_unit "$held" remlab-render; then
  say "СТОРОЖ: порт 8600 держит процесс $held вне юнита — останавливаю"
  kill "$held" 2>/dev/null; sleep 3; kill -9 "$held" 2>/dev/null
fi
ps -eo pid=,args= | grep '172\.18\.0\.1:8601' | grep -v grep | while read -r pid _; do
  in_unit "$pid" remlab-render-tunnel && continue
  echo "$(date '+%F %T') СТОРОЖ: прежний туннель $pid вне юнита — останавливаю" >>"$TLOG"
  kill "$pid" 2>/dev/null
done

# 3. туннель: юнит перезапускает ssh сам; сторож поднимает его, если юнит остановлен целиком
if ! systemctl --user is-active -q remlab-render-tunnel; then
  echo "$(date '+%F %T') СТОРОЖ: юнит туннеля не активен — запускаю" >>"$TLOG"
  systemctl --user restart remlab-render-tunnel
fi
# 3б. туннель активен, но порт на проде занят (зависшая сессия после перезагрузки DEV) — тревога, раз в час (T-20261020-20)
bash ./tunnel_watch.sh || true

# 4. сервис: РЕШАЕТ ТОЛЬКО ЗДОРОВЬЕ (demo-03, verify 14.10). Только что запущенный прогревает меши (~15 с) —
#    его не трогаем первые 90 с, иначе сторож перезапускал бы его по кругу.
curl -s -m 4 http://127.0.0.1:8600/health >/dev/null && exit 0
if systemctl --user is-active -q remlab-render; then
  since=$(systemctl --user show -p ActiveEnterTimestampMonotonic --value remlab-render)
  now=$(awk '{printf "%d", $1 * 1000000}' /proc/uptime)
  if [ -n "$since" ] && [ "$since" -gt 0 ] && [ $(( (now - since) / 1000000 )) -lt 90 ]; then exit 0; fi
  say "СТОРОЖ: сервис активен, но /health молчит — перезапускаю"
else
  say "СТОРОЖ: сервис не активен — запускаю"
fi
systemctl --user restart remlab-render
ok=0; for _ in $(seq 1 15); do sleep 2; curl -s -m 2 http://127.0.0.1:8600/health >/dev/null && { ok=1; break; }; done
if [ "$ok" = 1 ]; then say "сервис запущен"; else say "сервис НЕ поднялся за 30 с"; fi
