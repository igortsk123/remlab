#!/usr/bin/env bash
# Трассировка в браузере (three-gpu-pathtracer, программный WebGL): C1 обеих сцен подряд. pt_all.sh <папка-вывода> <сэмплы> <ширина> <высота>
D="$1"; N="$2"; W="$3"; H="$4"
WT=/home/pakar/igor/remlab/.claude/worktrees/cycles-1117
for s in living-scandi bed2-japandi; do
  $WT/tools/ops/heavy-slot.sh "t63-pt-$s" --cores 8 -- node $WT/tools/scout/cycles_probe/pt_run.mjs "$HOME/remlab-logs/t63-1117/gltf/$s" C1 "$W" "$H" "$N" "$D/pt/$s-C1.png" timeout_min=30 sun=0 fill=12 env=0.3 exp=1.0 view=10 > "$D/pt/$s-C1.log" 2>&1
done
echo ALLDONE > "$D/pt/done.txt"
