#!/bin/bash
# Витрина-6 v2: по сету на стиль, ПАРАЛЛЕЛЬНО (замер скорости)
PY=~/venvs/scout/bin/python
T0=$(date +%s)
for i in 39 24 81 64 87 36; do
  $PY solver_run.py $i --v3 > v3solve$i.log 2>&1 &
done
wait
echo "солверы: $(( $(date +%s) - T0 )) c"
for i in 39 24 81 64 87 36; do
  $PY pipeline2.py $i --v3 --layout A > v3render$i.log 2>&1 &
done
wait
echo "ИТОГО: $(( $(date +%s) - T0 )) c"
for i in 39 24 81 64 87 36; do grep -H "final:" v3render$i.log || echo "v3render$i: НЕТ ФИНАЛА"; done
echo "=== ВИТРИНА-6 ГОТОВА ==="
