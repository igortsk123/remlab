#!/usr/bin/env bash
# Прогрев кадров демо (план b2b-08 п.4): шаг `demo_warm` ночного прогона — после публикации демо и ДО живой проверки,
# чтобы у каждого стиля был кадр свежего набора. Логика — `tools/ops/demo-warm.mjs`.
set -uo pipefail
cd "$(dirname "$0")/../.." || exit 1
. tools/ops/node-env.sh
timeout 1800 node tools/ops/demo-warm.mjs || echo "WARN:demo_warm: прогрев кадров упал (код $?) — см. лог шага"
exit 0
