#!/usr/bin/env bash
# Варианты заливки А (stat) на ВЫХОДЕ ЭТАПА 6 — сравнение настроек узора в одном запуске. Только под heavy-slot (P-038):
#   tools/ops/heavy-slot.sh t164-ab7 --prio 1 --short --cores 2 --timeout 21600 -- nice -n 19 timeout -k 20 1800 bash tools/scout/salad/trellis/tex_fill_variants.sh <выход> <корень этапа 6: …/run7> <sku> [<sku> …]
# Варианты (каждый — своя папка <выход>/<имя>): f25/f35/f50 — узор из кадра, блок не меньше 0,25/0,35 (по умолчанию)/0,5 стороны видимого участка части.
set -u
OUT="$1"; ROOT="$2"; shift 2
HERE="$(cd "$(dirname "$0")" && pwd)"
export OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 MKL_NUM_THREADS=2
PY="$HOME/venvs/scout/bin/python"
for v in 'f25|{"pr_block_frac": 0.25}' 'f35|{}' 'f50|{"pr_block_frac": 0.5}'; do
  name="${v%%|*}"; cfg="${v#*|}"
  mkdir -p "$OUT/$name"
  "$PY" "$HERE/tex_fill_probe.py" --visible-root "$ROOT" --source stat --cfg "$cfg" "$OUT/$name" "$@" > "$OUT/$name/probe.log" 2>&1
done
echo "готово: $OUT"
