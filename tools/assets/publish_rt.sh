#!/usr/bin/env bash
# Публикация лёгких runtime-моделей конфигуратора на прод (план apartment-3d-configurator).
#
# Почему отдельным скриптом, а не деплоем: модели — не код, они весят десятки мегабайт и
# меняются реже; деплой их не возит (как и Caddyfile, `.memory_bank/deployment.md`).
# Маршрут `/rt/*` отдаёт Caddy из /opt/remlab/test/rt с `immutable`-кэшем.
set -euo pipefail
SRC="${1:-$HOME/scout-scenes/flat3d-rt}"
[ -d "$SRC" ] || { echo "нет каталога $SRC — сперва tools/assets/runtime_mesh.py"; exit 1; }
COUNT=$(find "$SRC" -name '*.glb' | wc -l)
[ "$COUNT" -gt 0 ] || { echo "в $SRC нет моделей"; exit 1; }
echo "выкладываю $COUNT моделей ($(du -sh "$SRC" | cut -f1))"
# БЕЗ --delete: на проде могут лежать модели прошлых партий, которые ещё открыты по ссылкам
rsync -a --info=stats1 -e "ssh -p 22222 -o StrictHostKeyChecking=no" "$SRC/" root@89.167.127.0:/opt/remlab/test/rt/
PROBE=$(find "$SRC" -name '*.glb' ! -name '*-lite.glb' | head -1 | xargs basename)
code=$(curl -s -o /dev/null -m 25 -w '%{http_code}' "https://remont-lab.online/rt/$PROBE")
[ "$code" = 200 ] || { echo "проверка не прошла: HTTP $code на /rt/$PROBE"; exit 1; }
echo "готово: https://remont-lab.online/rt/$PROBE отдаётся (HTTP 200)"
