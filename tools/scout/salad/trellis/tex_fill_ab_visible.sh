#!/usr/bin/env bash
# Проба заливки А (stat) и Б (trellis) на ВЫХОДЕ ЭТАПА 6 (06-visible: visible.glb + known.png) — настоящий вход этапа 7. Запускать только под heavy-slot (P-038):
#   tools/ops/heavy-slot.sh t164-abv --prio 1 --short --cores 2 --timeout 21600 -- nice -n 19 timeout -k 20 3000 bash tools/scout/salad/trellis/tex_fill_ab_visible.sh <выход> <корень этапа 6: …/run7> <папка черновиков out30> <sku> [<sku> …]
# Черновик Б — `<папка черновиков>/<sku>-n1024.glb` (новая выдача out30); нет файла — Б этого товара пропущен (в B-trellis/skipped.txt). Внутри — 2 потока, А затем Б.
set -u
OUT="$1"; ROOT="$2"; DRAFTS="$3"; shift 3
HERE="$(cd "$(dirname "$0")" && pwd)"
export OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 MKL_NUM_THREADS=2
PY="$HOME/venvs/scout/bin/python"
mkdir -p "$OUT/A-stat" "$OUT/B-trellis"
"$PY" "$HERE/tex_fill_probe.py" --visible-root "$ROOT" --source stat "$OUT/A-stat" "$@" > "$OUT/A-stat/probe.log" 2>&1
SKUB=""
for s in "$@"; do
  if [ -f "$DRAFTS/$s-n1024.glb" ]; then SKUB="$SKUB $s"; else echo "нет черновика: $s" >> "$OUT/B-trellis/skipped.txt"; fi
done
if [ -n "$SKUB" ]; then
  # shellcheck disable=SC2086
  "$PY" "$HERE/tex_fill_probe.py" --visible-root "$ROOT" --source trellis --draft-dir "$DRAFTS" --draft-pattern '{base}-n1024.glb' --draft-fallback off --draft-texture on "$OUT/B-trellis" $SKUB > "$OUT/B-trellis/probe.log" 2>&1
fi
echo "готово: $OUT"
