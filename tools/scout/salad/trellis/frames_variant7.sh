#!/usr/bin/env bash
# T-20261119-92/1 — кадры вариантов 7 тем же стендом, что у остальных вариантов (render_stand.py; виды az000, az045, az180, top55 × текстура/«глина», 32 прохода Cycles).
# Каждый GLB — отдельным процессом под очередью тяжёлого: `heavy-slot.sh --prio 1 --cores 2` (правило директора 19.11 14:50: кадры показа владельцу — prio 1).
# Запуск:  frames_variant7.sh <метка> <glb> [<метка> <glb> …]   → ~/remlab-logs/t92-1119/frames/<метка>/NN_<вид>_<tex|clay>.png (полный размер, по кадру) + подписанные копии в <метка>/cap/.
# Метка кадра = путь + товар + доля куба (например `B-komod-f50`): по ней видно, как узор зависит от сжатия формы.
set -u
REPO="${REPO:-/home/pakar/igor/remlab/.claude/worktrees/pixtex-1119}"
TR="$REPO/tools/scout/salad/trellis"
BLENDER="${BLENDER:-$HOME/opt/blender-4.5.9/blender}"
PY="${PY:-$HOME/venvs/scout/bin/python}"
ROOT="${ROOT:-$HOME/remlab-logs/t92-1119/frames}"
VIEWS="${VIEWS:-az000,az045,az180,top55}"
[ $(( $# % 2 )) -eq 0 ] && [ $# -gt 0 ] || { echo "нужны пары: <метка> <glb>" >&2; exit 2; }
while [ $# -gt 0 ]; do
  label="$1"; glb="$2"; shift 2
  [ -f "$glb" ] || { echo "нет $glb" >&2; continue; }
  out="$ROOT/$label"
  mkdir -p "$out"
  cd "$REPO" || exit 2
  tools/ops/heavy-slot.sh "t92-fr-$label" --prio 1 --cores 2 --min-gb 3 --timeout 3000 -- "$BLENDER" -b -P "$TR/render_stand.py" -- \
    --glb "$glb" --out "$out" --samples 32 --modes tex,clay --only "$VIEWS" --threads 2 >> "$ROOT/render-$label.log" 2>&1
  echo "$label rc=$?"
  "$PY" -I "$TR/caption_frames.py" "$out" "$label" >> "$ROOT/render-$label.log" 2>&1
done
