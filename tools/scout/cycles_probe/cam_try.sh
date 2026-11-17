#!/usr/bin/env bash
# Пробные ракурсы (малый размер, 12 сэмплов): cam_try.sh <сцена> <имя выгрузки> <папка-вывода> <метка:eyeX,eyeY:lookX,lookY:объектив> ...
# Пример: cam_try.sh bed2-japandi bed2 ~/remlab-logs/t66-1117/cam sw:0.5,-0.5:3.5,-2.6:24
S="$1"; DGN="$2"; O="$3"; shift 3
cd "$(dirname "$0")/.." || exit 1
export EXPD=export2 BL=blender-5.3.0-linux-x64 CORES=2
mkdir -p "$O"
for p in "$@"; do
  IFS=: read -r tag eye look lens <<< "$p"
  DG="$DGN" TAG="-$tag" EXPJ="$HOME/remlab-logs/t66-1117/dump/$DGN/scene-export.json" cycles_probe/run.sh "$S" C1 12 25 "$O" \
    --eye "$eye" --aim "$look" --lens "$lens" --cam-h 1.35 --shift-y -0.05 --view 3 | grep RENDER_SEC
done
