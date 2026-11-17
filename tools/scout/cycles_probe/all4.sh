#!/usr/bin/env bash
# все 4 кадра Cycles подряд (две сцены × две камеры): all4.sh <папка-вывода> <сэмплы>
D="$1"; N="$2"
cd /home/pakar/igor/remlab/.claude/worktrees/cycles-1117/tools/scout
for s in living-scandi bed2-japandi; do for c in C1 C2; do
  cycles_probe/run.sh $s $c $N 100 "$D/cycles"
done; done
echo ALLDONE > "$D/cycles/done.txt"
