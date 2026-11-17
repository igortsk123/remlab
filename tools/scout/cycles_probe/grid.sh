#!/usr/bin/env bash
# Сетка настроек вида на одной сцене, круг 2 (T-20261117-06/1; владелец TG 1315–1319; советы Codex 17.11 `_intake/codex/2026-11-17-render-realism-answer.md`):
#   grid.sh <сцена> <имя выгрузки декора> <папка dump со scene-export.json> <папка-вывода>
# Круг 1 (a–h, ракурс --cam-auto) показал: стены белые от пересвета, вид из окна дымчатый, при лампах 2700 К весь кадр оранжевый (заполняющий свет
# был тёплым — исправлено), ракурс слишком далеко. Круг 2: ракурс ближе к дивану/кровати, вид за окном приглушён (--view 2), тепло — только лампам.
# Каждый кадр — отдельный PNG 1536×1116 (владелец оценивает кадры, не листы), 48 сэмплов, Blender 5.3, под heavy-slot (8 ядер).
S="$1"; DGN="$2"; DUMP="$3"; O="$4"
HD="$HOME/remlab-logs/t63-1117/hdri/kloofendal_48d_partly_cloudy_puresky_2k.hdr"
cd "$(dirname "$0")/.." || exit 1
export EXPD=export2 BL=blender-5.3.0-linux-x64
case "$S" in
  living-scandi) CAM=(--eye 3.9,-0.3 --aim 0.5,-2.4 --lens 26) ;;
  bed2-japandi)  CAM=(--eye 3.9,-0.35 --aim 1.0,-2.0 --lens 26) ;;
  *)             CAM=(--cam-auto 1 --lens 30) ;;
esac
BASE=("${CAM[@]}" --cam-h 1.35 --shift-y -0.05 --view 2)
mkdir -p "$O"
go() { local tag="$1"; shift; TAG="-$tag" DG="$DGN" EXPJ="$DUMP/scene-export.json" cycles_probe/run.sh "$S" C1 48 75 "$O" "${BASE[@]}" "$@"; }
PY="$HOME/venvs/scout/bin/python"
WARM=(--sun-angle 4 --fill 40 --lamp-k 2700 --chandelier 80 --lamps 15)
go r1-agx --exposure -0.3
if [ "$S" = "living-scandi" ]; then   # спальня — сокращённый набор (срок 12:30): AgX без ламп и тёплый вариант; полный разбор вариантов — на гостиной
  go r2-punchy --look "AgX - Punchy" --exposure -0.2
  go r3-filmic --transform Filmic --look "Filmic - High Contrast" --exposure -0.3
fi
go r4-warm --look "AgX - Punchy" --exposure -0.2 "${WARM[@]}"
"$PY" cycles_probe/post_look.py "$O/$S-C1-r4-warm.png" "$O/$S-C1-r5-warm-post.png" --glow 0.25 --vig 0.15 --grain 0.005
if [ "$S" = "living-scandi" ]; then
  go r6-hdri --look "AgX - Punchy" --exposure -0.2 --hdri "$HD" --portal 1 --sun 0 --fill 40 --lamp-k 2700 --chandelier 80 --lamps 15
fi
echo ALLDONE > "$O/done-$S.txt"
