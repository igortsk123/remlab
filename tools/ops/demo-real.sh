#!/usr/bin/env bash
# Ночная досъёмка фото нейросети (план demo-29): шаг `demo_real` ночного прогона — ДО публикации, на новой сборке (`DEMO_LOCAL`,
# план photo-before-publish-01, T-20261107-34); тот же шаг зовёт ручная выкладка (`publish_demo.sh`). Только варианты без фото своей
# расстановки, потолок трат — tools/scout/rules/demo-realistic.json (200 ₽, WARN выше 100). Логика — `tools/ops/demo-realistic.mjs --night`.
set -uo pipefail
cd "$(dirname "$0")/../.." || exit 1
. tools/ops/node-env.sh
# обработанные исходы (потолок, ошибка задания, улучшение недоступно) — код 0 и строки DIGEST/WARN; иной код — сбой самого шага.
# Аргументы — дальше в скрипт: `--dry` — бесплатная проверка без съёмки (ночь с упавшей публикацией, T-20261106-88)
# 10800 с = ожидание очереди тяжёлых прогонов ночью (2 ч, `demo-realistic.mjs:NIGHT_WAIT_S`, T-20261107-03) + час съёмки
timeout 10800 node tools/ops/demo-realistic.mjs --night "$@"; rc=$?
[ "$rc" -ne 0 ] && echo "ERROR:demo_real: досъёмка фото нейросети — код $rc, см. лог шага"
exit "$rc"
