#!/usr/bin/env bash
# Публикация лёгких runtime-моделей конфигуратора на прод (план apartment-3d-configurator).
#
# Почему отдельным скриптом, а не деплоем: модели — не код, они весят десятки мегабайт и
# меняются реже; деплой их не возит (как и Caddyfile, `.memory_bank/deployment.md`).
# Маршрут `/rt/*` отдаёт Caddy из /opt/remlab/test/rt с `immutable`-кэшем.
set -Eeuo pipefail
# НЕ МОЛЧАТЬ (T-20261112-50): 12.11 12:55 скрипт умер после rsync без единой строки — `demo_rt.sh` увидел только «выкладка не
# прошла». Любой сбой под `set -e` печатает строку, команду и код (ловушка ERR; `set -E` — и внутри подстановок/функций)
trap 'echo "publish_rt.sh: сбой в строке $LINENO (код $?): $BASH_COMMAND" >&2' ERR
SRC="${1:-${RT_OUT:-$HOME/scout-scenes/flat3d-rt}}"
# RT_ADD_ONLY=1 — только добавить новые файлы, уже лежащие на /rt/ не переписывать (сборка рядом, T-20261106-77: копии
# гостиной на проде не меняются); ночь — без него: пересобранная из нового исходника копия должна уехать.
ADD_ONLY=(); [ "${RT_ADD_ONLY:-}" = 1 ] && ADD_ONLY=(--ignore-existing)
[ -d "$SRC" ] || { echo "нет каталога $SRC — сперва tools/assets/runtime_mesh.py"; exit 1; }
COUNT=$(find "$SRC" -name '*.glb' | wc -l)
[ "$COUNT" -gt 0 ] || { echo "в $SRC нет моделей"; exit 1; }
echo "выкладываю $COUNT моделей ($(du -sh "$SRC" | cut -f1))"
# БЕЗ --delete: на проде могут лежать модели прошлых партий, которые ещё открыты по ссылкам
rsync -a "${ADD_ONLY[@]}" --info=stats1 --exclude runtime-meshes.json -e "ssh -p 22222 -o StrictHostKeyChecking=no" "$SRC/" root@89.167.127.0:/opt/remlab/test/rt/
# проба — первая полная модель БЕЗ пайпа: `find | head -1` под pipefail ронял скрипт молча — head закрывал канал, find получал
# SIGPIPE (код 141), подстановка падала под `set -e` (замер T-50: 12 из 100 запусков на ~400 моделях)
PROBE=$(find "$SRC" -name '*.glb' ! -name '*-lite.glb' -print -quit)
[ -n "$PROBE" ] || { echo "в $SRC нет полной модели (только -lite) — проверять /rt/ нечем"; exit 1; }
PROBE=${PROBE##*/}
# curl с ошибкой (таймаут -m 25 — код 28, нет сети — 6/7) не роняет скрипт до сообщения: код HTTP 000 и код curl — в строку отказа
code=$(curl -s -o /dev/null -m 25 -w '%{http_code}' "https://remont-lab.online/rt/$PROBE") || code="000 (curl код $?)"
[ "$code" = 200 ] || { echo "проверка не прошла: HTTP $code на /rt/$PROBE"; exit 1; }
echo "готово: https://remont-lab.online/rt/$PROBE отдаётся (HTTP 200)"
# ТАБЛИЦА КОПИЙ ДЛЯ ДЕМО (план demo-01 п.5): движок сцены демо подставляет её сам (`/demo/rt-meshes.json`, без долгого
# кэша — уедет со следующей публикацией демо); приложение `/flat` берёт свою из сборки. Свежесть копии в браузере держит
# `?v=<отпечаток>` в ссылке (`lib/configurator/mesh-url.ts`): маршрут `/rt/` — immutable на неделю.
# таблица ночной сборки (вне репо, `tools/assets/demo_rt.sh`), а если её нет — та, что в репо
M="${RT_MANIFEST:-$HOME/scout-scenes/flat3d-rt/runtime-meshes.json}"
[ -f "$M" ] || M="$(dirname "$0")/../../data/flat3d/runtime-meshes.json"
# куда — папка сборки (RT_TABLE_OUT; ночь — витрина ~/scout-scenes/flat215-demo, сборка рядом — своя папка, T-20261106-77)
T="${RT_TABLE_OUT:-$HOME/scout-scenes/flat215-demo/rt-meshes.json}"
cp "$M" "$T"
echo "таблица копий → $T"
