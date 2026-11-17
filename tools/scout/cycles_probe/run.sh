#!/usr/bin/env bash
# Рендер одного кадра Cycles под очередью тяжёлых: run.sh <сцена> <камера> <сэмплы> <pct> <папка-вывода> [доп. ключи render_cycles.py]
set -uo pipefail
S="$1"; C="$2"; N="$3"; P="$4"; O="$5"; shift 5
WT=/home/pakar/igor/remlab/.claude/worktrees/cycles-1117
mkdir -p "$O"
$WT/tools/ops/heavy-slot.sh "t63-cycles-$S-$C" --cores 8 -- "$HOME/opt/blender-4.5.9/blender" -b -P "$WT/tools/scout/cycles_probe/render_cycles.py" -- \
  --scene-dir "$HOME/remlab-logs/t63-1117/export/$S" --cam "$C" --out "$O/$S-$C.png" --samples "$N" --pct "$P" --threads 8 "$@" > "$O/$S-$C.log" 2>&1
grep -E "RENDER_SEC|Error|error|Traceback" "$O/$S-$C.log" | tail -5
