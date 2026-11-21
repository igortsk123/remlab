#!/bin/bash
# Ш6: мерка «часть целиком» (wholepart, Codex 21.11): v3 заморозка (отступ 3, окно спектра 16) и прогон: сейчас (stat) | вар.1 (borrow_texture) | вар.2 (relief + донор-калибровка, УТЕЧКА: черновик TRELLIS видел фото части)
B=$HOME/remlab-logs/t182-1121
export OMP_NUM_THREADS=2
OUT=$B/blind-v3
rm -f $OUT/done.flag
mkdir -p $OUT
cd $B/tools/scout/salad/trellis || exit 1
PY="$HOME/venvs/scout/bin/python -I"
H=$HOME/remlab-logs
if [ ! -f $OUT/frozen/frozen.json ]; then
  $PY tex_fill_blind.py freeze --wholepart --margin 3 --spec-win 16 $OUT $H/e2eHD-1121:99272_607007941975253599 $H/e2eHD-1121:114082_10587794773481498560 $H/e2eHD-1121:112923_16411672175141188566 \
    $H/e2eHD-batch-1121:112923_1040167435642588653 $H/e2eHD-batch-1121:112923_10551627698909366429 > $OUT/freeze.log 2>&1
fi
$PY tex_fill_blind.py run --tag now $OUT $OUT/frozen > $OUT/run-now.log 2>&1
$PY tex_fill_blind.py run --tag borrow --cfg '{"borrow_texture": true}' $OUT $OUT/frozen > $OUT/run-borrow.log 2>&1
$PY tex_fill_blind.py run --tag relief_leaky --source trellis_relief --draft-dir $H/mesh-models-1118/trellis2 --cfg '{"relief_calib_donor": true}' $OUT $OUT/frozen > $OUT/run-relief.log 2>&1
echo ok > $OUT/done.flag
