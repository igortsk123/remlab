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

# ПОЛНЫЙ ВЫВОД — В ФАЙЛ ДНЯ (T-20261023-08): в лог ночи идёт только хвост (имена упавших), а причины падения (ошибка, ожидание,
# строка теста) терялись — ночь 23.10 дала 5 красных, и разобрать их было не по чему. Файл дописывается (несколько прогонов в день),
# коды цвета строчного репортёра срезаны; путь — `DEMO_LIVE_LOGS`, по умолчанию ~/scout-scenes/demo-live/
LOGD=${DEMO_LIVE_LOGS:-$HOME/scout-scenes/demo-live}
mkdir -p "$LOGD"
LOGF="$LOGD/$(date +%F).log"
# один браузер: --workers=1 дублирует playwright.live.config.ts — не дать параллели вернуться флагом/правкой конфига
out=$(pnpm exec playwright test -c playwright.live.config.ts --workers=1 2>&1); rc=$?
{ echo "=== $(date '+%F %T') demo_live rc=$rc ==="; printf '%s\n' "$out" | sed 's/\x1b\[[0-9;]*[A-Za-z]//g'; } >> "$LOGF"
if [ "$rc" -ne 0 ]; then
  echo "$out" | tail -25
  echo "WARN:demo_live: живая проверка демо на проде не прошла — полный вывод: $LOGF"
  exit 0
fi
echo "$out" | tail -2
echo "полный вывод: $LOGF"
