#!/usr/bin/env bash
# Сцены всех вариантов /demo (гостиные и спальни) движком /demo, без экспорта GLB: audit_all.sh <папка-вывода>
# Для каждого варианта — scene_info.json и shell_info.json в <папка>/vNN/. Каждый прогон — под heavy-slot (1 ядро; сборка сцены ≈3 с).
O="$1"
WT=/home/pakar/igor/remlab/.claude/worktrees/cycles-1117
DD="$HOME/scout-scenes/flat215-demo/demo-data.json"
BUNDLE="$HOME/remlab-logs/t63-1117/demo_bundle"
N=$(python3 -c "import json,sys; print(len(json.load(open('$DD'))['variants']))")
mkdir -p "$O"
for i in $(seq 0 $((N - 1))); do
  V=$(printf 'v%02d' "$i")
  $WT/tools/ops/heavy-slot.sh "t63-audit-$V" --cores 2 -- node "$WT/tools/scout/cycles_probe/demo_scene_dump.mjs" "$DD" "$i" "$BUNDLE" "$O/$V" > "$O/$V.log" 2>&1
  grep -E "сцена собрана|pageerror" "$O/$V.log" | tail -2 | sed "s/^/$V: /"
done
echo ALLDONE > "$O/done.txt"
