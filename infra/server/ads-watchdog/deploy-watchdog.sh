#!/usr/bin/env bash
# Деплой ads-watchdog на прод-сервер: скрипты + systemd-таймеры. Секреты НЕ трогает:
# требует уже существующий /opt/remlab/ads-watchdog/.env (600) — иначе падает с подсказкой.
set -euo pipefail
SERVER="${REMLAB_SERVER:-root@89.167.127.0}"
DIR="$(cd "$(dirname "$0")" && pwd)"
DEST=/opt/remlab/ads-watchdog

echo "==> [1/4] Файлы джобов -> $DEST"
ssh "$SERVER" "mkdir -p $DEST"
scp -q "$DIR"/{common.py,decisions.py,check.py,minus.py,ads_ab.py,report.py} "$SERVER:$DEST/"

echo "==> [2/4] Проверка .env (секреты деплой не пишет)"
ssh "$SERVER" "test -f $DEST/.env || { echo 'FATAL: нет $DEST/.env — создай с YANDEX_DIRECT_TOKEN, TG_BOT_TOKEN, TG_CHAT_ID, GEMINI_API_KEY, DRY_RUN=1 (chmod 600)'; exit 1; }
chmod 600 $DEST/.env"

echo "==> [3/4] systemd units + timers"
scp -q "$DIR"/units/remlab-ads-*.{service,timer} "$SERVER:/etc/systemd/system/"
ssh "$SERVER" "systemctl daemon-reload
for t in check minus ab report; do systemctl enable --now remlab-ads-\$t.timer; done"

echo "==> [4/4] Статус таймеров"
ssh "$SERVER" "systemctl list-timers 'remlab-ads-*' --no-pager | head -8"
echo "DONE. Логи: ssh $SERVER journalctl -u 'remlab-ads-*' -n 50 | Выключить всё: ssh $SERVER touch $DEST/DISABLED"
