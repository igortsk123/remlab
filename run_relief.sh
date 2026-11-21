#!/bin/bash
B=$HOME/remlab-logs/t182-1121
export OMP_NUM_THREADS=2
rm -f $B/relief.done
cd $B/tools/scout/salad/trellis || exit 1
~/venvs/scout/bin/python -I $B/diag_relief.py > $B/relief.log 2>&1
echo ok > $B/relief.done
