#!/usr/bin/env bash
# Проба заливки А (stat) и Б (trellis) на пакете «трудных» ОДНОЙ задачей — запускать только под heavy-slot (P-038):
#   tools/ops/heavy-slot.sh t164-ab --prio 1 --short --timeout 2400 -- nice -n 19 bash tools/scout/salad/trellis/tex_fill_ab.sh <выход> <список.txt> [<папка черновиков TRELLIS>]
# <список.txt> — строки «имя-прогона<TAB>…» (как canary12.txt), прогоны — ~/remlab-logs/t90-1119/sg/salad/<имя>-q2509t5i-*. Внутри — 2 потока, А затем Б по очереди.
set -u
OUT="$1"; LIST="$2"; DRAFTS="${3:-$HOME/remlab-logs/mesh-models-1118/trellis2}"
HERE="$(cd "$(dirname "$0")" && pwd)"
export OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 MKL_NUM_THREADS=2
SALAD="$HOME/remlab-logs/t90-1119/sg/salad"
RUNS=""
for k in $(grep -v '^#' "$LIST" | cut -f1); do RUNS="$RUNS $(ls -d "$SALAD/$k"-q2509t5i-* | tail -1)"; done
mkdir -p "$OUT/A-stat" "$OUT/B-trellis"
# shellcheck disable=SC2086
"$HOME/venvs/scout/bin/python" "$HERE/tex_fill_probe.py" --source stat "$OUT/A-stat" $RUNS > "$OUT/A-stat/probe.log" 2>&1
# shellcheck disable=SC2086
"$HOME/venvs/scout/bin/python" "$HERE/tex_fill_probe.py" --source trellis --draft-dir "$DRAFTS" "$OUT/B-trellis" $RUNS > "$OUT/B-trellis/probe.log" 2>&1
echo "готово: $OUT"
