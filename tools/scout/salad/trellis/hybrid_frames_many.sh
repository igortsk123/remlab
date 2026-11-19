#!/usr/bin/env bash
# T-20261118-91/2: кадры гибрида «форма TRELLIS.2 + покраска Hunyuan» для нескольких товаров (0° и 45°, текстура и «глина», полный размер) под heavy-slot.
# Запуск на pakardev: hybrid_frames_many.sh <папка-с-GLB> <вариант[,вариант]> <sku> [<sku> …]   (sku вида 112923:123…)
#   GLB гибрида — <папка>/<sku_>-paint-<вариант>-42.glb;  кадры — ~/remlab-logs/mesh-models-1118/frames-clean/hybrid/<вариант>/<sku_>/;  журнал — hunyuan-ctrl/hybrid-many.log
set -u
DIR="$1"; VARS="${2//,/ }"; shift 2
W="$HOME/igor/remlab/.claude/worktrees/hy-paint/tools/scout/salad/trellis"
R="$HOME/remlab-logs/mesh-models-1118"
LOG="$R/hunyuan-ctrl/hybrid-many.log"
for sku in "$@"; do
  s=${sku//:/_}
  for v in $VARS; do
    glb="$DIR/$s-paint-$v-42.glb"
    [ -f "$glb" ] || { echo "$sku $v: нет GLB $glb" >> "$LOG"; continue; }
    out="$R/frames-clean/hybrid/$v/$s"
    mkdir -p "$out"
    "$HOME/igor/remlab/tools/ops/heavy-slot.sh" "hybrid2-$v-$s" --cores 4 --min-gb 3 --prio 1 -- \
      "$HOME/opt/blender-4.5.9/blender" -b -P "$W/render_stand.py" -- \
      --glb "$glb" --out "$out" --only az000,az045 \
      > "$R/hunyuan-ctrl/hybrid-many-$v-$s.log" 2>&1
    echo "$sku $v: кадров $(ls "$out" | grep -c '\.png$')" >> "$LOG"
  done
done
echo "hybrid_frames_many кончились" >> "$LOG"
