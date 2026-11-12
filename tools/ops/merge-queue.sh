#!/usr/bin/env bash
# СБОРЩИК ВЕТОК «В ТЕНИ» (T-20261112-78): пачка 2–4 веток во временной копии от main → один полный прогон под heavy-slot →
# при падении сам находит виновную (повтор шага, чистый main, деление пополам). Не пушит, не вливает, main не трогает.
#   tools/ops/merge-queue.sh <ветка>[@sha] … [--steps typecheck,lint,test,build,prepush,memory] [--base main] [--keep] [--no-slot]
#   tools/ops/merge-queue.sh --selftest
# Отчёт — ~/remlab-logs/mq/<ЧЧММСС>/report.md (строка на ветку), журнал прогонов — ~/remlab-logs/mq/journal.tsv.
# Реализация и подробности — tools/ops/merge_queue.py.
set -uo pipefail
exec python3 "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/merge_queue.py" "$@"
