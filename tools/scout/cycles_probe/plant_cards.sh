#!/usr/bin/env bash
# T-20261117-21: карточки всех пробных растений (кандидаты c-*, нынешние cur-*) — каждое отдельным кадром, полный размер, 2 ракурса.
#   plant_cards.sh <папка с raw/*.glb> <папка кадров> [размер] [отсчёты]
GLB="${1:-$HOME/remlab-logs/t21-1117/glb}"; OUT="${2:-$HOME/remlab-logs/t21-1117/cards}"; SZ="${3:-1400}"; SM="${4:-96}"
HERE="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$OUT"
for F in "$GLB"/raw/*.glb; do
  N="$(basename "$F" .glb)"
  for AZ in 35 -50; do
    [ -f "$OUT/$N-az$AZ.png" ] && continue
    "$HOME/opt/blender-4.5.9/blender" -b -P "$HERE/plant_cards.py" -- --glb "$F" --out "$OUT/$N-az$AZ.png" --size "$SZ" --samples "$SM" --azim "$AZ" 2>&1 | grep -E "^CARD|Error|Traceback"
  done
done
echo DONE > "$OUT/done.txt"
