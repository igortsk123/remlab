#!/bin/bash
cd /home/pakar/igor/remlab/.claude/worktrees/render-gpu/tools/scout/render_gpu || exit 1
PY=~/venvs/scout/bin/python
IMG=$(cat ~/remlab-logs/t22-1117/image-bench-thin.digest)
OUT=~/remlab-logs/t24-1117/thin
mkdir -p "$OUT"
for k in 1 2 3; do
  echo "=== thin-run$k $(date +%H:%M:%S)"
  if [ $k = 1 ]; then X=""; else X="--reuse"; fi
  $PY bench_run.py --card 4090 --image "$IMG" --apply --out "$OUT" --cap 0.2 --total-cap 0.2 --max-min 8 --no-events-s 150 --suffix thin --tier high $X 2>&1 | tail -n 40
done
echo "=== ВСЁ $(date +%H:%M:%S)"
