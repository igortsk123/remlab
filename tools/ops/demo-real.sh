#!/usr/bin/env bash
# Ночная досъёмка фото нейросети (план demo-29): шаг `demo_real` ночного прогона — после публикации и прогрева кадров. Только стили
# без фото своей расстановки, потолок трат — tools/scout/rules/demo-realistic.json. Логика — `tools/ops/demo-realistic.mjs --night`.
set -uo pipefail
cd "$(dirname "$0")/../.." || exit 1
. tools/ops/node-env.sh
# обработанные исходы (потолок, ошибка задания, улучшение недоступно) — код 0 и строки DIGEST/WARN; иной код — сбой самого шага
timeout 3600 node tools/ops/demo-realistic.mjs --night; rc=$?
[ "$rc" -ne 0 ] && echo "ERROR:demo_real: досъёмка фото нейросети — код $rc, см. лог шага"
exit "$rc"
