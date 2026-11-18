#!/bin/bash
cd /home/pakar/igor/remlab/.claude/worktrees/render-gpu/tools/scout/render_gpu || exit 1
while ! grep -q "ВСЁ" ~/remlab-logs/t24-1117/levers.log; do sleep 10; done
PY=~/venvs/scout/bin/python
OLD=$(cat ~/remlab-logs/t22-1117/image-bench.digest)
THIN=$(cat ~/remlab-logs/t22-1117/image-bench-thin.digest)
run() { local tag=$1 out=$2 img=$3; shift 3; echo "=== $tag $(date +%H:%M:%S)"; $PY bench_run.py --card 4090 --image "$img" --apply --out "$out" --cap 0.25 --total-cap 0.25 --max-min 8 --no-events-s 150 "$@" 2>&1 | tail -n 40; }
L=~/remlab-logs/t24-1117/levers; T=~/remlab-logs/t24-1117/thin
run B-run3 $L $OLD --suffix c16 --reuse --tier high --cpu 16 --mem-mb 32768
run C-run3 $L $OLD --suffix med --reuse --tier medium
run thin-run4 $T $THIN --suffix thin --reuse --tier high
run thin-run5 $T $THIN --suffix thin --reuse --tier high
echo "=== ВСЁ $(date +%H:%M:%S)"
