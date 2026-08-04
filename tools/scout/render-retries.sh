#!/bin/bash
# ретраи после основной очереди: сет 47 (502 без кадра) и сет 107 (краш стабилизатора)
while pgrep -f render7.sh >/dev/null; do sleep 30; done
PY=~/venvs/scout/bin/python
for i in 47 107; do
  echo "=== сет $i: ретрай ==="
  $PY pipeline2.py $i --v3 --layout A 2>&1 | grep -E "стиль сета|draft ok|QA#|rollback|стабилизатор|final:|retry|Error|Traceback"
done
echo "=== РЕТРАИ ГОТОВЫ ==="
