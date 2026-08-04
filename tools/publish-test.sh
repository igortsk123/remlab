#!/usr/bin/env bash
# Выкладывает страницы/картинки проверок на https://remont-lab.online/test/ (статик Caddy,
# закрыт от поисковиков). Владелец смотрит их по ссылке — вложения в чате он открыть не может.
#   tools/publish-test.sh probe-f1.html plan.png
set -euo pipefail
SRV=${REMLAB_SRV:-root@89.167.127.0}
DIR=/opt/remlab/test
[ $# -gt 0 ] || { echo "укажи файлы"; exit 1; }
ssh "$SRV" "mkdir -p $DIR"
scp -q "$@" "$SRV:$DIR/"
for f in "$@"; do
  b=$(basename "$f")
  code=$(curl -s -o /dev/null -w '%{http_code}' "https://remont-lab.online/test/$b")
  echo "https://remont-lab.online/test/$b  ($code)"
done
