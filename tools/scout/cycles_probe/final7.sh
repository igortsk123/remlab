#!/usr/bin/env bash
# T-20261117-12/1 ❷❹: гостиная и спальня позами камер /demo (C1 — широкая, C2 — вторая; телефонный кадр — вырез из широкого по `crop` /demo),
# поза Б по умолчанию (render_cycles.py: глаз 1,35, горизонтально, сдвиг вниз 0,15, правила долей; T-20261117-12/2), ковёр без светлой каймы (`--rug-erode`), свет как final6. Без правок под комнату: камера из scene.json, остальное — общие ключи.
#   final7.sh <сцена> <имя выгрузки> <папка dump> <папка-вывода> [камеры: "C1 C2"]
S="$1"; DGN="$2"; DUMP="$3"; O="$4"; CAMS="${5:-C1 C2}"
cd "$(dirname "$0")/.." || exit 1
export EXPD=export2 BL=blender-5.3.0-linux-x64
F=(--view 2 --exposure -0.15 --sun-angle 4 --fill 40 --lamp-k 3000 --chandelier 0 --lamps 5 --sheer 0.5 --normal-k 3.5 --rug-erode 0.025)
mkdir -p "$O"
for C in $CAMS; do
  TAG="-poseB" DG="$DGN" EXPJ="$DUMP/scene-export.json" cycles_probe/run.sh "$S" "$C" 64 75 "$O" "${F[@]}"
done
echo ALLDONE > "$O/done-$S.txt"
