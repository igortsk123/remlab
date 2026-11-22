#!/bin/bash
# Платный прогон TRELLIS.2 (драйвер trellis_trial.py) под heavy-slot — одна точка запуска (T-20261121-172).
# Драйвер почти не ест ни ядер, ни памяти (ходит в сеть, опрашивает Salad), поэтому порог памяти heavy-slot минимальный (0.3 ГБ):
# на pakardev 15–20 ГБ плавающей памяти, держатель с порогом 2 ГБ блокировал этап 05 (9 ГБ) на часы. Класс prio 2 — платная машина не ждёт очереди (ADR-0453).
# Запуск: run_paid_trellis.sh <суффикс> <файл-со-списком-товаров> <папка-входов> <ladder.json> <папка-вывода> <потолок-$> [файл-разрешение]
# Список — по одному mid:eid в строке (ID товаров живут только во входном файле). Без файла-разрешения паузы нет; с ним — после первого задания (пробы) нода ждёт файл ≤25 мин.
set -u
SUF="$1"; SKUS="$2"; INP="$3"; LAD="$4"; OUT="$5"; CAP="$6"; GO="${7:-}"
HERE="$(cd "$(dirname "$0")" && pwd)"
HOLD=()
if [ -n "$GO" ]; then HOLD=(--hold-after 1 --hold-file "$GO" --hold-max-min 25); fi
exec python3 "$HERE/../../../ops/heavy_slot.py" "paid-trellis-$SUF" --prio 2 --cores 1 --min-gb 0.3 --timeout 21600 -- \
  timeout -k 20 21600 "$HOME/venvs/scout/bin/python" -I "$HERE/trellis_trial.py" --model trellis2 \
  --image ghcr.io/igortsk123/mesh-pixal3d-trial:trellis2-bw --inputs "$INP" --skus $(tr '\n' ' ' < "$SKUS") --ladder "$LAD" \
  --card "RTX 5090 (32 GB)" --tier high --cap "$CAP" --max-min 270 "${HOLD[@]}" --out "$OUT" --suffix "$SUF" --apply
