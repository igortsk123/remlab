#!/usr/bin/env bash
# T-20261118-91/2: кадры гибрида «форма TRELLIS.2 + покраска Hunyuan» на предметном стенде (0° и 45°, текстура и «глина», полный размер) под heavy-slot.
# Запуск на pakardev: hybrid_frames.sh [вариант …]   (по умолчанию noremesh remesh). Кадры — ~/remlab-logs/mesh-models-1118/frames-clean/hybrid/<вариант>/<товар>/
set -u
W="$HOME/igor/remlab/.claude/worktrees/hy-paint/tools/scout/salad/trellis"
R="$HOME/remlab-logs/mesh-models-1118"
SKU=112923_13224664101879413845
VARS="${*:-noremesh remesh}"
for v in $VARS; do
  out="$R/frames-clean/hybrid/$v/$SKU"
  mkdir -p "$out"
  "$HOME/igor/remlab/tools/ops/heavy-slot.sh" "hybrid-$v" --cores 4 --min-gb 3 --prio 1 -- \
    "$HOME/opt/blender-4.5.9/blender" -b -P "$W/render_stand.py" -- \
    --glb "$R/trellis/$SKU-paint-$v-42.glb" --out "$out" --only az000,az045 \
    > "$R/hunyuan-ctrl/hybrid-frames-$v.log" 2>&1
  echo "hybrid $v: кадров $(ls "$out" | grep -c '\.png$')" >> "$R/hunyuan-ctrl/frames-chain.log"
done
echo "гибрид-кадры кончились: $VARS" >> "$R/hunyuan-ctrl/frames-chain.log"
