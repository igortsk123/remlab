#!/bin/bash
# Ш6: кадр «разница видна» (Денди ч.1) + шов на границе заёма
B=$HOME/remlab-logs/t182-1121
export OMP_NUM_THREADS=2
rm -rf $B/seam-out $B/seam.done; mkdir -p $B/seam-out
cd $B/tools/scout/salad/trellis || exit 1
~/venvs/scout/bin/python -I $B/cmp_seam.py $B/seam-out > $B/seam.log 2>&1
echo ok > $B/seam.done
