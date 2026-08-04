#!/bin/bash
# 7 витрин: лучший стиль-фит на каждую площадь (владелец 2026-08-02)
PY=~/venvs/scout/bin/python
for i in 11 29 47 64 81 107 114; do
  echo "=== сет $i: солвер ==="
  $PY solver_run.py $i --v3 2>&1 | grep -E "^комната|^seed|FAIL|НЕ разм"
  $PY - <<PYEOF
import json; json.load(open('v3set${i}-layout.json'))  # целостность (гонка с solver_check)
PYEOF
  echo "=== сет $i: рендер ==="
  $PY pipeline2.py $i --v3 --layout A 2>&1 | grep -E "стиль сета|вне кадра|draft ok|QA#|rollback|стабилизатор|final:|TIMING|Error|Traceback"
done
echo "=== ВСЕ 7 ГОТОВЫ ==="
