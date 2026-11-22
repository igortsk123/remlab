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
# ШАПКА — В НАЧАЛЕ ЗАПУСКА (T-20261119-115/2): раньше «=== … rc=N ===» писалась после прогона, и упавший или оборванный запуск в журнале
# не оставлял следа; теперь строка старта есть всегда, вывод идёт в журнал по ходу, итог — отдельной строкой в конце
echo "=== $(date '+%F %T') demo_live старт ===" >> "$LOGF"
RAW="$LOGD/.last-run.raw"
# один браузер: --workers=1 дублирует playwright.live.config.ts — не дать параллели вернуться флагом/правкой конфига
pnpm exec playwright test -c playwright.live.config.ts --workers=1 2>&1 | tee "$RAW" | sed -u 's/\x1b\[[0-9;]*[A-Za-z]//g' >> "$LOGF"
rc=${PIPESTATUS[0]}
echo "=== $(date '+%F %T') demo_live rc=$rc ===" >> "$LOGF"
# СТОРОЖ (T-20261119-115/2): красных ≥ порога (`tools/scout/rules/demo-live.json`) — rc 1 (шаг FAIL) и строка DIGEST:! в сводку;
# раньше шаг кончался rc 0 при любых красных, и 7–13 красных каждую ночь 12–19.11 стали «нормой»
[ "$rc" -ne 0 ] && tail -25 "$RAW"
python3 tools/ops/demo-live-gate.py --file "$RAW" --rc "$rc"
grc=$?
[ "$rc" -eq 0 ] && tail -2 "$RAW"
echo "полный вывод: $LOGF"
exit "$grc"
