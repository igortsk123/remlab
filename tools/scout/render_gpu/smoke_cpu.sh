#!/usr/bin/env bash
# Проверка правки render_cycles.py на CPU DEV (0 ₽): два ракурса в одном процессе, малое качество.
#   smoke_cpu.sh <сцена-выгрузка> <dump-декора> <папка-вывода> [сэмплы=8] [pct=25]
S="$1"; DG="$2"; O="$3"; N="${4:-8}"; P="${5:-25}"
WT=/home/pakar/igor/remlab/.claude/worktrees/render-gpu
L="$HOME/remlab-logs/t63-1117"
mkdir -p "$O"
"$WT/tools/ops/heavy-slot.sh" "t22-smoke-$S" --cores "${CORES:-4}" -- "$HOME/opt/blender-5.3.0-linux-x64/blender" -b -P "$WT/tools/scout/cycles_probe/render_cycles.py" -- \
  --scene-dir "$L/export2/$S" --cam C1,C2 --out "$O/$S-{cam}.png" --samples "$N" --pct "$P" --threads "${CORES:-4}" \
  --demo-glb "$L/demo_dump/$DG/demo_nodes.glb" --demo-nodes "$L/demo_dump/$DG/demo_nodes_uuids.json" \
  --export "$L/demo_dump/$DG/scene-export.json" --public "$WT/public" \
  --view 2 --exposure -0.15 --sun-angle 4 --fill 40 --lamp-k 3000 --chandelier 0 --lamps 5 --sheer 0.5 --normal-k 3.5 --rug-erode 0.025 \
  --cam-h 1.35 --level 1 --shift-y -0.12 > "$O/$S.log" 2>&1
grep -E "SCENE_BUILD_SEC|RENDER_SEC|DEVICE|Error|Traceback|поза Б" "$O/$S.log" | tail -12
