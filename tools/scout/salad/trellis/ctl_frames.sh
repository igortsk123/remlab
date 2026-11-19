#!/usr/bin/env bash
# T-20261118-91/2: кадры КОНТРОЛЯ Hunyuan 2.1 — только от настоящих GLB в hunyuan21/ (после путаницы имён в trellis/ 19.11).
# По каждому товару: mesh_clean (то же правило, что у TRELLIS; кладёт <имя>.clean.glb рядом, в hunyuan21/) → кадры стенда (az000, az045, top55; текстура и «глина»; полный размер) под heavy-slot.
# Кадры — ~/remlab-logs/mesh-models-1118/frames-clean/hunyuan21-ctl/<товар>/  (новая папка: старые не трогаем). Запуск на pakardev: ctl_frames.sh [sku …]; без аргументов — все из hunyuan21/_copy-report.json (поле ok).
set -u
W="$HOME/igor/remlab/.claude/worktrees/hy-paint/tools/scout/salad/trellis"
R="$HOME/remlab-logs/mesh-models-1118"
LOG="$R/hunyuan-ctrl/ctl-frames.log"
if [ "$#" -gt 0 ]; then SKUS="$*"; else SKUS=$(python3 -c "import json;print(*json.load(open('$R/hunyuan21/_copy-report.json'))['ok'])"); fi
for sku in $SKUS; do
  s=${sku//:/_}
  glb="$R/hunyuan21/$s-1024-42-0.glb"
  dims=$(python3 -c "import json;S={c['sku']:c for c in json.load(open('$R/trellis/set30.json'))};print(*S['$sku']['dims_cm'])")
  [ -f "$glb" ] || { echo "$sku: нет GLB в hunyuan21/" >> "$LOG"; continue; }
  "$HOME/venvs/scout/bin/python" "$W/mesh_clean.py" "$glb" --dims $dims > "$R/hunyuan-ctrl/ctl-clean-$s.log" 2>&1 || { echo "$sku: mesh_clean упал" >> "$LOG"; continue; }
  out="$R/frames-clean/hunyuan21-ctl/$s"
  mkdir -p "$out"
  "$HOME/igor/remlab/tools/ops/heavy-slot.sh" "hyctl2-$s" --cores 4 --min-gb 3 -- \
    "$HOME/opt/blender-4.5.9/blender" -b -P "$W/render_stand.py" -- \
    --glb "${glb%.glb}.clean.glb" --out "$out" --only az000,az045,top55 \
    > "$R/hunyuan-ctrl/ctl-frames-$s.log" 2>&1
  echo "$sku: кадров $(ls "$out" | grep -c '\.png$')" >> "$LOG"
done
echo "ctl_frames кончились" >> "$LOG"
