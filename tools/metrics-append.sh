#!/usr/bin/env bash
# Пассивный сбор эмпирики: дописать строку метрик прогона аудита в
# <проект>/.memory_bank/changelog/metrics.log (committed — накапливается во времени).
# Строка: footprint (Tier0/корпус — структурная экономия токенов) + счётчик находок по категориям
# (частота дрейфа — эффект гейта в фазе warn). Так warn становится фазой сбора данных, а не вечным
# предупреждением. Запускать периодически (раз в неделю/после апгрейда) или из планировщика — НЕ
# на каждую сессию (иначе лог зашумится).
#
# Использование: tools/metrics-append.sh [путь-к-проекту]   (по умолчанию — текущая папка)
set -euo pipefail
root="${1:-.}"
here="$(cd "$(dirname "$0")" && pwd)"

line="$(node "$here/memory-audit.mjs" --check --metrics "$root" 2>/dev/null | grep '^METRICS ' || true)"
[ -n "$line" ] || { echo "metrics-append: строка METRICS не получена (нет node или .memory_bank?)"; exit 1; }

log="$root/.memory_bank/changelog/metrics.log"
mkdir -p "$(dirname "$log")"
[ -f "$log" ] || printf '# Метрики прогонов аудита (пассивный сбор). Строка = один прогон.\n# footprint_pct = Tier0/корпус (структурная экономия); *=N — находки по категориям (частота дрейфа).\n' > "$log"
printf '%s\n' "$line" >> "$log"
echo "metrics-append: дописано в $log"
echo "  $line"
