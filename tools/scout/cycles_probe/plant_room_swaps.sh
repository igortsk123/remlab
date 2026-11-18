#!/usr/bin/env bash
# T-20261117-21: кадры одной живой комнаты — нынешнее растение и кандидаты на том же месте (комната, свет, ракурс те же).
#   plant_room_swaps.sh <папка кадров> <сцена> <камера> <слот заменяемого растения> <id кандидатов через пробел> [высота см]
# Пример: plant_room_swaps.sh ~/remlab-logs/t21-1117/room living-scandi C1 plant:decor:ваза "c-gazania c-heliophila"
O="$1"; SCENE="$2"; CAM="$3"; SLOT="$4"; IDS="$5"; PH="${6:-0}"
HERE="$(cd "$(dirname "$0")" && pwd)"
WT="$(cd "$HERE/../../.." && pwd)"
G="$HOME/remlab-logs/t21-1117/glb/raw"
mkdir -p "$O"
export WT EXPD=export2 BL=blender-5.3.0-linux-x64 DG="${DG:-living-pl}" CORES=4
EXTRA="${EXTRA:-}"
TAGS="$(echo "$SLOT" | tr ':' '_' | tr -d '#')"
if [ ! -f "$O/$SCENE-$CAM-cur-$TAGS.png" ]; then
  TAG="-cur-$TAGS" "$HERE/run.sh" "$SCENE" "$CAM" 32 100 "$O" --real 1 --view 3 $EXTRA
fi
for I in $IDS; do
  [ -f "$O/$SCENE-$CAM-$I-$TAGS.png" ] && continue
  TAG="-$I-$TAGS" "$HERE/run.sh" "$SCENE" "$CAM" 32 100 "$O" --real 1 --view 3 --plant-swap "$G/$I.glb" --plant-slot "$SLOT" --plant-h "$PH" $EXTRA $PLANT_ARGS
done
echo DONE > "$O/done-$TAGS.txt"
