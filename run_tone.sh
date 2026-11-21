#!/bin/bash
# Ш6 × р.8: 07 на 06 с тон-слоем (tone-l0): base | tone | tone_b; кадры сверху и метрики по частям
B=$HOME/remlab-logs/t182-1121
export OMP_NUM_THREADS=2
rm -rf $B/tone-out $B/tone.done; mkdir -p $B/tone-out
cd $B/tools/scout/salad/trellis || exit 1
~/venvs/scout/bin/python -I $B/cmp_tone.py $B/tone-out > $B/tone.log 2>&1
echo ok > $B/tone.done
