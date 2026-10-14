#!/usr/bin/env bash
# Живая проверка демо на проде (план b2b-12): шаг `demo_live` ночного прогона после публикации демо.
# Крон не видит node из nvm — путь добавляем сами; браузер Playwright — общий кэш DEV (ubuntu24 override).
set -uo pipefail
cd "$(dirname "$0")/../.." || exit 1
. tools/ops/node-env.sh
if ! out=$(pnpm exec playwright test -c playwright.live.config.ts 2>&1); then
  echo "$out" | tail -25
  echo "WARN:demo_live: живая проверка демо на проде не прошла — см. лог шага"
  exit 0
fi
echo "$out" | tail -2
