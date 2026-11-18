#!/bin/bash
# T-24/3: рычаги 4090 — 4 варианта × 2 запуска (второй на той же группе = проверка кэша образа). Временный, не коммитить.
cd /home/pakar/igor/remlab/.claude/worktrees/render-gpu/tools/scout/render_gpu || exit 1
PY=~/venvs/scout/bin/python
IMG=$(cat ~/remlab-logs/t22-1117/image-bench.digest)
OUT=~/remlab-logs/t24-1117/levers
mkdir -p "$OUT"
run() {   # метка, доп. аргументы...
  local tag=$1; shift
  echo "=== $tag $(date +%H:%M:%S)"
  $PY bench_run.py --card 4090 --image "$IMG" --apply --out "$OUT" --cap 0.25 --total-cap 0.25 --max-min 8 --no-events-s 150 "$@" 2>&1 | tail -n 40
}
# вариант A: база 8 vCPU / 16 ГБ / high — повтор на уже существующей группе (кэш образа: тот же digest, второй старт)
run A-base-run2 --reuse --tier high
# вариант B: 16 vCPU / 32 ГБ / high — новая группа, потом повтор на ней же
run B-16c32g-run1 --suffix c16 --cpu 16 --mem-mb 32768 --tier high
run B-16c32g-run2 --suffix c16 --reuse --tier high
# вариант C: 8 vCPU / 16 ГБ / medium
run C-medium-run1 --suffix med --tier medium
run C-medium-run2 --suffix med --reuse --tier medium
# вариант D: 16 vCPU / 32 ГБ / medium
run D-16c32g-med-run1 --suffix c16med --cpu 16 --mem-mb 32768 --tier medium
run D-16c32g-med-run2 --suffix c16med --reuse --tier medium
echo "=== ВСЁ $(date +%H:%M:%S)"
