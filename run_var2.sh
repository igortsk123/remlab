#!/bin/bash
# Ш6: мерка Б far/side на заморозке v2 для вар.1 (borrow_texture) и вар.2 (trellis_relief + донор-калибровка); ФЛАГИ — ДО позиционных аргументов (раньше были после и молча игнорировались)
B=$HOME/remlab-logs/t182-1121
export OMP_NUM_THREADS=2
rm -f $B/var2.done
cd $B/tools/scout/salad/trellis || exit 1
PY="$HOME/venvs/scout/bin/python -I"
O=$B/blind-v2
DR=$HOME/remlab-logs/mesh-models-1118/trellis2
$PY tex_fill_blind.py run --tag v2relief --modes far,side --source trellis_relief --draft-dir $DR --cfg '{"relief_calib_donor": true}' $O $O/frozen > $O/run-v2relief.log 2>&1
$PY tex_fill_blind.py run --tag v1borrow --modes far,side --cfg '{"borrow_texture": true}' $O $O/frozen > $O/run-v1borrow.log 2>&1
for t in v2relief v1borrow; do n=$(grep -c "\"tag\": \"$t\"" $O/blind-$t.jsonl 2>/dev/null); echo "ПРОВЕРКА ТЕГА $t: записей ${n:-0}" >> $O/run-var2.check; [ "${n:-0}" -gt 0 ] || echo "FAIL: тега $t нет в jsonl (флаги проигнорированы?)" >> $O/run-var2.check; done
echo ok > $B/var2.done
