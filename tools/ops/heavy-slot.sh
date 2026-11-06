#!/usr/bin/env bash
# ОБЩАЯ ОЧЕРЕДЬ ТЯЖЁЛЫХ ПРОГОНОВ DEV (T-20261105-57): одно тяжёлое за раз на машину + порог свободной памяти.
# Порядок — строго по приходу (билеты); ждущий память держатель через 10 мин уступает задаче с меньшим порогом (≤ 3 раз).
# Реализация одна — `tools/ops/heavy_slot.py` (замок flock и файлы состояния общие с питоновым `with heavy_slot(...)`).
#
#   tools/ops/heavy-slot.sh <метка> [--min-gb N] [--timeout S] [--no-slot] -- <команда…>   rc команды; 124 — не дождался
#   tools/ops/heavy-slot.sh --status                                                       кто держит, кто ждёт, память
#   tools/ops/heavy-slot.sh --stats                                                        замеры: пик памяти и держание по типу задачи
#   tools/ops/heavy-slot-selftest.sh                                                       самопроверка (во временной папке)
# Пример: tools/ops/heavy-slot.sh t36-vlm --min-gb 7 -- ~/venvs/scout/bin/python launch.py keys.txt 8
# Журнал «взял/отпустил/сколько ждал» — ~/remlab-logs/heavy-slot.log.
set -uo pipefail
exec python3 "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/heavy_slot.py" "$@"
