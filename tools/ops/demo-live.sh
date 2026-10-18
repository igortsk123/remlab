#!/usr/bin/env bash
# Живая проверка демо на проде (план b2b-12): шаг `demo_live` ночного прогона после публикации демо.
# Крон не видит node из nvm — путь добавляем сами; браузер Playwright — общий кэш DEV (ubuntu24 override).
set -uo pipefail
cd "$(dirname "$0")/../.." || exit 1
. tools/ops/node-env.sh

# РЕНДЕР СВОБОДЕН? (b2b-09, 18.10): браузер проверки рядом с рендером кадра на 7,6 ГБ вызывал earlyoom — он убивал
# рендер и ssh-туннели. Ждём до 10 минут, пока у DEV-рендера нет идущих заданий и пустая очередь (/stats);
# не дождались — проверяем всё равно (пропуск проверки хуже), но пишем предупреждение. Рендер молчит — ждать нечего.
busy() {
  local s
  s=$(curl -s -m 4 http://127.0.0.1:8600/stats) || return 1
  python3 -c 'import json,sys; d=json.loads(sys.argv[1]); sys.exit(0 if d.get("queue",0) or sum((d.get("running") or {}).values()) else 1)' "$s"
}
waited=0
while busy && [ "$waited" -lt 600 ]; do sleep 15; waited=$((waited + 15)); done
if busy; then echo "WARN:demo_live: рендер занят дольше 10 минут — проверяю рядом с ним"
elif [ "$waited" -gt 0 ]; then echo "demo_live: ждал свободного рендера ${waited} с"; fi

# один браузер: --workers=1 дублирует playwright.live.config.ts — не дать параллели вернуться флагом/правкой конфига
if ! out=$(pnpm exec playwright test -c playwright.live.config.ts --workers=1 2>&1); then
  echo "$out" | tail -25
  echo "WARN:demo_live: живая проверка демо на проде не прошла — см. лог шага"
  exit 0
fi
echo "$out" | tail -2
