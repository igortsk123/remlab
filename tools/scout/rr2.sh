#!/bin/bash
PY=~/venvs/scout/bin/python
for i in 47 107; do
 echo "=== сет $i ==="
 $PY pipeline2.py $i --v3 --layout A 2>&1 | grep -E "стиль сета|draft ok|QA|rollback|стабилизатор|final:|retry|Traceback"
done
echo "=== ГОТОВО ==="
