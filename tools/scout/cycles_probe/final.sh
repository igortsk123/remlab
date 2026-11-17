#!/usr/bin/env bash
# Итоговые кадры T-20261117-06/1 с выбранными настройками (по сетке гостиной): отдельные PNG 1536×1116 (pct 75), 64 сэмпла, Blender 5.3.
#   final.sh <сцена> <имя выгрузки> <папка dump> <папка-вывода> [проба обивки: 1]
# Настройки F: AgX Medium High Contrast, экспозиция −0,3, солнце 4°, заполнение 40 Вт нейтральное (5500 К), лампы 2800 К (люстра 60 Вт, торшер 12 Вт),
# вид за окном 2, шторы-тюль (прозрачность 0,3), нормали отделки ×2 (рельеф штукатурки/досок виден при скользящем свете от окна).
S="$1"; DGN="$2"; DUMP="$3"; O="$4"; PROBE="${5:-0}"
cd "$(dirname "$0")/.." || exit 1
export EXPD=export2 BL=blender-5.3.0-linux-x64
case "$S" in
  living-scandi) CAM=(--eye 3.9,-0.3 --aim 0.5,-2.4 --lens 26) ;;
  bed2-japandi)  CAM=(--eye 3.9,-0.35 --aim 1.0,-2.0 --lens 26) ;;
  *)             CAM=(--cam-auto 1 --lens 30) ;;
esac
F=("${CAM[@]}" --cam-h 1.35 --shift-y -0.05 --view 2 --exposure -0.3 --sun-angle 4 --fill 40 --lamp-k 2800 --chandelier 60 --lamps 12 --sheer 0.3 --normal-k 2.0)
mkdir -p "$O"
go() { local tag="$1"; shift; TAG="-$tag" DG="$DGN" EXPJ="$DUMP/scene-export.json" cycles_probe/run.sh "$S" C1 64 75 "$O" "${F[@]}" "$@"; }
go final
if [ "$PROBE" = "1" ]; then
  ORIG="$HOME/scout-scenes/mesh3d-cache/112923_1000339805231639017.glb"
  FAB="$HOME/remlab-logs/t66-1117/fabric/Fabric036/Fabric036_1K-JPG_NormalGL.jpg"
  go sofa2-original --orig "диван:$ORIG"
  go sofa3-sheen --orig "диван:$ORIG" --sheen 0.4 --sheen-rough 0.5
  go sofa4-weave --orig "диван:$ORIG" --sheen 0.4 --sheen-rough 0.5 --fabric "$FAB" --fabric-k 0.6 --fabric-tile 12
fi
echo ALLDONE > "$O/done-$S.txt"
