#!/usr/bin/env bash
# Рендер одного кадра Cycles под очередью тяжёлых: run.sh <сцена> <камера> <сэмплы> <pct> <папка-вывода> [доп. ключи render_cycles.py]
# Переменные: BL — папка Blender в ~/opt (по умолчанию blender-4.5.9), EXPD — папка выгрузки в ~/remlab-logs/t63-1117 (по умолчанию export),
#   DG — папка выгрузки декора /demo (demo_dump/<имя>: берутся demo_nodes.glb и demo_nodes_uuids.json), TAG — приписка к имени файла,
#   CORES — ядер под heavy-slot (по умолчанию 8), THR — потоков Blender (по умолчанию = CORES).
set -uo pipefail
S="$1"; C="$2"; N="$3"; P="$4"; O="$5"; shift 5
WT="${WT:-/home/pakar/igor/remlab/.claude/worktrees/render-3d}"
# EXPJ — scene-export.json сцены (render-3d-01 шаг 0): стены и пол по нему (карты, тайл, тонировка); без него — ровный цвет паспорта
EXPA=()
if [ -n "${EXPJ:-}" ]; then EXPA=(--export "$EXPJ" --public "$WT/public"); fi
BL="${BL:-blender-4.5.9}"; EXPD="${EXPD:-export}"; CORES="${CORES:-8}"; THR="${THR:-$CORES}"; TAG="${TAG:-}"
L="$HOME/remlab-logs/t63-1117"
DGA=()
if [ -n "${DG:-}" ]; then DGA=(--demo-glb "$L/demo_dump/$DG/demo_nodes.glb" --demo-nodes "$L/demo_dump/$DG/demo_nodes_uuids.json"); fi
mkdir -p "$O"
$WT/tools/ops/heavy-slot.sh "t63-cycles-$S-$C$TAG" --cores "$CORES" -- "$HOME/opt/$BL/blender" -b -P "$WT/tools/scout/cycles_probe/render_cycles.py" -- \
  --scene-dir "$L/$EXPD/$S" --cam "$C" --out "$O/$S-$C$TAG.png" --samples "$N" --pct "$P" --threads "$THR" "${DGA[@]}" "${EXPA[@]}" "$@" > "$O/$S-$C$TAG.log" 2>&1
grep -E "RENDER_SEC|Error|error|Traceback|HDRI|DoF|портал" "$O/$S-$C$TAG.log" | tail -6
