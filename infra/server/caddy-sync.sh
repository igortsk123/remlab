#!/usr/bin/env bash
# КОНФИГ ВХОДА (Caddyfile) ЕДЕТ ДЕПЛОЕМ (план b2b-01). Зовётся из `deploy-remote.sh` под замком
# деплоя, ДО активации нового приложения: сломанный конфиг роняет деплой, а не сайт.
#
# Раньше Caddyfile возили руками, и сервер трижды оказывался новее репозитория (07.08, 04.09,
# 13.10) — правка на сервере жила неделями, а следующая ручная копия её стирала. Теперь:
#   • CI кладёт репо-версию рядом: /opt/remlab/caddy/Caddyfile.new;
#   • после каждой успешной выкладки рядом остаётся снимок `Caddyfile.deployed`;
#   • если боевой файл ≠ снимку — значит, его правили на сервере руками: СТОП с diff-ом,
#     такую правку надо сперва перенести в репозиторий (иначе деплой её молча снесёт);
#   • новый файл проверяется `caddy validate` ДО подмены; подмена — `cat >` в тот же файл
#     (он примонтирован в контейнер bind-ом по inode: `mv` оставил бы Caddy старый файл);
#   • `caddy reload` не прошёл — возвращаем бэкап и перезагружаем снова.
# VPN-нода `remnanode` делит хост — здесь трогается только контейнер remlab-caddy.
set -euo pipefail

DIR=${CADDY_DIR:-/opt/remlab/caddy}
CUR=$DIR/Caddyfile NEW=$DIR/Caddyfile.new SNAP=$DIR/Caddyfile.deployed
C=${CADDY_CONTAINER:-remlab-caddy}

[ -f "$NEW" ] || { echo "caddy: нового Caddyfile нет — конфиг не трогаю"; exit 0; }

# 1. Ручная правка на сервере? Есть снимок — сравниваем с ним; первого снимка нет — прежний
#    предохранитель: строка есть на сервере и нет в репо → стоп.
if [ -f "$SNAP" ]; then
  if ! cmp -s "$CUR" "$SNAP"; then
    echo "FATAL: Caddyfile на сервере правили руками после прошлого деплоя — перенеси в репо:"
    diff "$SNAP" "$CUR" | head -40 || true
    exit 1
  fi
elif comm -23 <(sort -u "$CUR") <(sort -u "$NEW") | grep -q .; then
  echo "FATAL: в серверном Caddyfile есть строки, которых нет в репо — сперва слей их в caddy/Caddyfile:"
  comm -23 <(sort -u "$CUR") <(sort -u "$NEW") | head -20
  exit 1
fi

if cmp -s "$CUR" "$NEW"; then
  echo "caddy: конфиг не изменился"
  cp "$NEW" "$SNAP"
  exit 0
fi

# 2. Проверка до подмены.
docker exec -i "$C" caddy validate --adapter caddyfile --config /dev/stdin < "$NEW" >/dev/null 2>&1 || {
  echo "FATAL: новый Caddyfile не проходит caddy validate:"
  docker exec -i "$C" caddy validate --adapter caddyfile --config /dev/stdin < "$NEW" 2>&1 | tail -5 || true
  exit 1
}

# 3. Бэкап → подмена в тот же inode → reload; провал — откат.
BAK="$DIR/Caddyfile.bak.$(date +%Y%m%d-%H%M%S)"
cp -p "$CUR" "$BAK"
cat "$NEW" > "$CUR"
if docker exec "$C" caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null 2>&1; then
  cp "$NEW" "$SNAP"
  echo "caddy: конфиг обновлён и перезагружен (бэкап $BAK)"
  diff "$BAK" "$CUR" | head -30 || true
else
  cat "$BAK" > "$CUR"
  docker exec "$C" caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null 2>&1 || true
  echo "FATAL: caddy reload не прошёл — вернул прежний конфиг ($BAK)"
  exit 1
fi

# Держим 10 последних бэкапов, старые — прочь.
ls -1t "$DIR"/Caddyfile.bak.* 2>/dev/null | tail -n +11 | xargs -r rm -f
