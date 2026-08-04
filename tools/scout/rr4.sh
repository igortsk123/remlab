#!/bin/bash
PY=~/venvs/scout/bin/python
for i in 87 81; do
 $PY solver_run.py $i --v3 > v3solve$i.log 2>&1 &
done
wait
for i in 87 81; do
 $PY pipeline2.py $i --v3 --layout A > v3render$i.log 2>&1 &
done
wait
echo "=== 2 ГОТОВЫ ==="
