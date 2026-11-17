#!/usr/bin/env bash
# Матрица быстрого режима Cycles на CPU (п.2 T-20261117-02/2): matrix.sh <папка-вывода>
# декор /demo + собственные карты материалов мебели; «просто» — как было (без пола-досок и штукатурки), «реал» — общие настройки реализма.
# 1024×744 = pct 50, 1536×1116 = pct 75 от 2048×1489. Время кадра — строка RENDER_SEC в логе каждого кадра.
O="$1"
cd /home/pakar/igor/remlab/.claude/worktrees/cycles-1117/tools/scout
export EXPD=export2 DG=living
for c in C1 C2; do
  TAG=-plain-1024-s64 cycles_probe/run.sh living-scandi $c 64 50 "$O" --real 0 --view 1.2
  TAG=-real-1024-s32 cycles_probe/run.sh living-scandi $c 32 50 "$O" --real 1 --view 3
  TAG=-real-1024-s64 cycles_probe/run.sh living-scandi $c 64 50 "$O" --real 1 --view 3
  TAG=-real-1536-s32 cycles_probe/run.sh living-scandi $c 32 75 "$O" --real 1 --view 3
  TAG=-real-1536-s64 cycles_probe/run.sh living-scandi $c 64 75 "$O" --real 1 --view 3
done
TAG=-real-dof-1024-s64 cycles_probe/run.sh living-scandi C1 64 50 "$O" --real 1 --view 3 --dof 8
BL=blender-5.3.0-linux-x64 TAG=-real53-1024-s64 cycles_probe/run.sh living-scandi C1 64 50 "$O" --real 1 --view 3
echo ALLDONE > "$O/done.txt"
