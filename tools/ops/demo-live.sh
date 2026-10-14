#!/usr/bin/env bash
# Живая проверка демо на проде (план b2b-12): шаг `demo_live` ночного прогона после публикации демо.
# Крон не видит node из nvm — путь добавляем сами; браузер Playwright — общий кэш DEV (ubuntu24 override).
set -uo pipefail
cd "$(dirname "$0")/../.." || exit 1
# та же версия node, что в обычной оболочке (nvm default), а не последняя по алфавиту (verify b2b-12)
DEF=$(cat "$HOME/.nvm/alias/default" 2>/dev/null)
NB=$(ls -d "$HOME"/.nvm/versions/node/v${DEF#v}*/bin 2>/dev/null | sort -V | tail -1)
[ -n "$NB" ] || NB=$(ls -d "$HOME"/.nvm/versions/node/*/bin 2>/dev/null | sort -V | tail -1)
export PATH="${NB:+$NB:}/usr/local/bin:$PATH"
export PLAYWRIGHT_HOST_PLATFORM_OVERRIDE=ubuntu24.04-x64 PLAYWRIGHT_BROWSERS_PATH="$HOME/.cache/ms-playwright"
if ! out=$(pnpm exec playwright test -c playwright.live.config.ts 2>&1); then
  echo "$out" | tail -25
  echo "WARN:demo_live: живая проверка демо на проде не прошла — см. лог шага"
  exit 0
fi
echo "$out" | tail -2
