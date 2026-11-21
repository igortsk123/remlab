#!/bin/bash
# T-182 диагноз v3: GLB читается из записи ЭТОГО прогона (не старый production-файл)
B=$HOME/remlab-logs/t182-1121
export OMP_NUM_THREADS=2
rm -rf $B/diag3-out $B/diag3.done; mkdir -p $B/diag3-out
cd $B/tools/scout/salad/trellis || exit 1
~/venvs/scout/bin/python -I $B/diag182.py $B/diag3-out \
  e2eHD-1121:99272_607007941975253599 e2eHD-1121:114082_10587794773481498560 e2eHD-1121:112923_16411672175141188566 \
  e2eHD-batch-1121:112923_1040167435642588653 e2eHD-batch-1121:112923_10551627698909366429 > $B/diag3.log 2>&1
echo ok > $B/diag3.done
