#!/usr/bin/env bash
# Публикация демо планировщика на прод-статик (26.08). Живой путь — /opt/remlab/test:
# /srv/remlab/static/test Caddy не отдаёт (проверено 26.08, публикация «в никуда»).
set -euo pipefail
SRC="$HOME/scout-scenes/flat215-demo"
[ -f "$SRC/index.html" ] || { echo "нет $SRC/index.html — сборка не выполнялась"; exit 1; }
TGZ=$(mktemp /tmp/flat215-demo.XXXX.tgz)
tar czf "$TGZ" -C "$(dirname "$SRC")" flat215-demo
scp -P 22222 -o StrictHostKeyChecking=no "$TGZ" root@89.167.127.0:/tmp/demo.tgz
# ТОП-СПРАЙТЫ ПЕРЕЖИВАЮТ ПУБЛИКАЦИЮ (01.09). `rm -rf flat215-demo` чистил и `topsprites/`,
# а туда виды сверху приезжают ОТДЕЛЬНО, прямым scp из мешевого конвейера
# (`salad/batch_show.py`, шаг «ориент-паблиш»), и в локальной сборке их всегда меньше:
# на замере 01.09 локально лежало 123 спрайта против 271 на проде — публикация стёрла бы 148,
# включая только что отрисованные. Та же болезнь, что у реестров (`salad/publish_merge.py`):
# частичная локальная копия ложится поверх более полной удалённой. Поэтому спрайты уносим в
# сторону, каталог обновляем начисто (чтобы удалённые файлы кода не оставались), и возвращаем
# спрайты объединением — свежая версия побеждает, старые не теряются.
ssh -p 22222 root@89.167.127.0 "set -e; cd /opt/remlab/test
  rm -rf .topsprites-keep
  [ -d buildup/topsprites ] && mv buildup/topsprites .topsprites-keep || mkdir -p .topsprites-keep
  rm -rf buildup && tar xzf /tmp/demo.tgz && mv flat215-demo buildup
  mkdir -p buildup/topsprites
  cp -n .topsprites-keep/*.png buildup/topsprites/ 2>/dev/null || true
  rm -rf .topsprites-keep
  chown -R 1000:1000 buildup && rm -f /tmp/demo.tgz"
rm -f "$TGZ"
code=$(curl -s -o /dev/null -m 25 -w '%{http_code}' "https://remont-lab.online/test/buildup/?v=$(date +%s)")
[ "$code" = 200 ] || { echo "публикация не подтвердилась: HTTP $code"; exit 1; }
echo "демо опубликовано: https://remont-lab.online/test/buildup/"
