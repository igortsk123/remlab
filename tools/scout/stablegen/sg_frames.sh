#!/bin/bash
# Кадры 0°/45° (текстура + «глина», 1600×1200, отдельными файлами) для готового GLB пробы StableGen — на ТОМ ЖЕ стенде, что у UltraTex run5 (render_stand.py, тот же свет и камера).
#   sg_frames.sh <painted.glb> <новая_папка_кадров>        → 01_az000_tex, 02_az000_clay, 03_az045_tex, 04_az045_clay
# Тяжёлое (Cycles на процессоре) — только под общим слотом проекта.
set -u
GLB=$1
OUT=$2
HERE=$(cd "$(dirname "$0")" && pwd)
exec "$HERE/../../ops/heavy-slot.sh" "t90-sg-frames" --min-gb 4 --cores 4 --timeout 3600 -- \
  "${BLENDER:-$HOME/opt/blender-4.5.9/blender}" -b -P "$HERE/render_stand.py" -- --glb "$GLB" --out "$OUT" --only az000,az045 --samples 64 --w 1600 --h 1200 --threads 4
