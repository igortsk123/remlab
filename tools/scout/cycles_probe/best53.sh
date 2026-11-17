#!/usr/bin/env bash
# Лучший набор (декор /demo + собственные карты материалов мебели + реализм комнаты) на Blender 5.3, 1536×1116, 64 сэмпла, обе сцены, C1 и C2.
#   best53.sh <папка-вывода>
O="$1"
cd /home/pakar/igor/remlab/.claude/worktrees/cycles-1117/tools/scout
export EXPD=export2 BL=blender-5.3.0-linux-x64
for p in "living-scandi living" "bed2-japandi bed2"; do
  set -- $p
  for c in C1 C2; do
    DG=$2 TAG=-best53-1536-s64 cycles_probe/run.sh $1 $c 64 75 "$O" --real 1 --view 3
  done
done
echo ALLDONE > "$O/done.txt"
