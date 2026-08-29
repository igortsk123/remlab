#!/bin/bash
# Массовая обрезка с предохранителем по балансу fal: ниже резерва не опускаемся.
PY="$HOME/venvs/scout/bin/python"
RESERVE=0.50
while true; do
  BAL=$($PY -c "
import re,urllib.request
k=[m.group(1) for m in (re.match(r'FAL_KEY=(.+)',l.strip()) for l in open('.env')) if m][0]
print(urllib.request.urlopen(urllib.request.Request('https://rest.alpha.fal.ai/billing/user_balance',headers={'Authorization':f'Key {k}'}),timeout=30).read().decode().strip())" 2>/dev/null)
  echo "=== баланс: $BAL ==="
  OK=$($PY -c "print(1 if float('$BAL' or 0) > $RESERVE else 0)")
  [ "$OK" = "1" ] || { echo "баланс у резерва $RESERVE — стоп"; break; }
  CUTOUT_SHA_MAX=0 CUTOUT_DAILY_MAX=300 CUTOUT_WORKERS=2 $PY cutout_sync.py || break
  LEFT=$($PY -c "
import sys; sys.path.insert(0,'.')
import cutout_sync as CS
print(len(CS.todo(100000)))" 2>/dev/null)
  echo "=== осталось в очереди: $LEFT ==="
  [ "${LEFT:-0}" -gt 0 ] || { echo "очередь пуста"; break; }
done
