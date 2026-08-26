#!/usr/bin/env bash
# Публикация демо планировщика на прод-статик (26.08). Живой путь — /opt/remlab/test:
# /srv/remlab/static/test Caddy не отдаёт (проверено 26.08, публикация «в никуда»).
set -euo pipefail
SRC="$HOME/scout-scenes/flat215-demo"
[ -f "$SRC/index.html" ] || { echo "нет $SRC/index.html — сборка не выполнялась"; exit 1; }
TGZ=$(mktemp /tmp/flat215-demo.XXXX.tgz)
tar czf "$TGZ" -C "$(dirname "$SRC")" flat215-demo
scp -P 22222 -o StrictHostKeyChecking=no "$TGZ" root@89.167.127.0:/tmp/demo.tgz
ssh -p 22222 root@89.167.127.0 "cd /opt/remlab/test && rm -rf flat215-demo && tar xzf /tmp/demo.tgz && chown -R 1000:1000 flat215-demo && rm -f /tmp/demo.tgz"
rm -f "$TGZ"
code=$(curl -s -o /dev/null -m 25 -w '%{http_code}' "https://remont-lab.online/test/flat215-demo/?v=$(date +%s)")
[ "$code" = 200 ] || { echo "публикация не подтвердилась: HTTP $code"; exit 1; }
echo "демо опубликовано: https://remont-lab.online/test/flat215-demo/"
