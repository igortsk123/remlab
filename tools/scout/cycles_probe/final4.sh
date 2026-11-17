#!/usr/bin/env bash
# Итоговые кадры, круг 2 (T-20261117-06/1): первый круг (final.sh) вышел розово-оранжевым — лампы 2800 К при 60/12 Вт перебивали дневной свет.
# Настройки F2: те же, но лампы 3000 К, люстра 20 Вт, торшер 6 Вт (днём лампы только намечены), рельеф отделки ×3,5.
#   final2.sh <сцена> <имя выгрузки> <папка dump> <папка-вывода> [проба обивки: 1]
S="$1"; DGN="$2"; DUMP="$3"; O="$4"; PROBE="${5:-0}"
cd "$(dirname "$0")/.." || exit 1
export EXPD=export2 BL=blender-5.3.0-linux-x64
case "$S" in
  living-scandi) CAM=(--eye 3.9,-0.3 --aim 0.5,-2.4 --lens 26) ;;
  bed2-japandi)  CAM=(--eye 3.9,-0.35 --aim 1.0,-2.0 --lens 26) ;;
  *)             CAM=(--cam-auto 1 --lens 30) ;;
esac
F=("${CAM[@]}" --cam-h 1.35 --shift-y -0.05 --view 2 --exposure -0.15 --sun-angle 4 --fill 40 --lamp-k 3000 --chandelier 0 --lamps 5 --sheer 0.3 --normal-k 3.5)
mkdir -p "$O"
go() { local tag="$1"; shift; TAG="-$tag" DG="$DGN" EXPJ="$DUMP/scene-export.json" cycles_probe/run.sh "$S" C1 64 75 "$O" "${F[@]}" "$@"; }
go final4
if [ "$PROBE" = "1" ]; then
  ORIG="$HOME/scout-scenes/mesh3d-cache/112923_1000339805231639017.glb"
  FAB="$HOME/remlab-logs/t66-1117/fabric/Fabric036/Fabric036_1K-JPG_NormalGL.jpg"
  go sofa2-original --orig "диван:$ORIG"
  go sofa3-sheen --orig "диван:$ORIG" --sheen 0.4 --sheen-rough 0.5
  go sofa4-weave --orig "диван:$ORIG" --sheen 0.4 --sheen-rough 0.5 --fabric "$FAB" --fabric-k 0.6 --fabric-tile 12
fi
echo ALLDONE > "$O/done-$S.txt"
