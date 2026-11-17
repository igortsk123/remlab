#!/usr/bin/env bash
# Сетка настроек вида на одной сцене (T-20261117-06/1, владелец TG 1315–1317; советы Codex 17.11 `_intake/codex/2026-11-17-render-realism-answer.md`):
#   grid.sh <сцена> <имя выгрузки декора> <папка dump со scene-export.json> <папка-вывода>
# Ракурс с окном (`--cam-auto`), объектив 30 мм, глаз 1,35 м, 1024×744, 48 сэмплов, Blender 5.3, под heavy-slot (8 ядер). Стены и пол — из scene-export.json.
# Пример: grid.sh living-scandi living ~/remlab-logs/t66-1117/dump/living ~/remlab-logs/t66-1117/grid
S="$1"; DGN="$2"; DUMP="$3"; O="$4"
HD="$HOME/remlab-logs/t63-1117/hdri/kloofendal_48d_partly_cloudy_puresky_2k.hdr"
cd "$(dirname "$0")/.." || exit 1
export EXPD=export2 BL=blender-5.3.0-linux-x64
BASE=(--cam-auto 1 --lens 30 --cam-h 1.35 --shift-y -0.05 --view 3)
mkdir -p "$O"
go() { local tag="$1"; shift; TAG="-$tag" DG="$DGN" EXPJ="$DUMP/scene-export.json" cycles_probe/run.sh "$S" C1 48 50 "$O" "${BASE[@]}" "$@"; }
go a-base
go b-punchy --look "AgX - Punchy"
go c-filmic --transform Filmic --look "Filmic - High Contrast"
go d-soft --sun-angle 4 --fill 40 --exposure 0.2
go e-hdri --hdri "$HD" --portal 1 --sun 0 --fill 40
go f-warm --sun-angle 4 --fill 40 --exposure 0.2 --lamp-k 2700 --chandelier 80
# g — тот же кадр f с «камерной» обработкой (свечение окна и ламп, виньетка, зерно)
python3 cycles_probe/post_look.py "$O/$S-C1-f-warm.png" "$O/$S-C1-g-warm-post.png" --glow 0.25 --vig 0.15 --grain 0.005
go h-dof --sun-angle 4 --fill 40 --exposure 0.2 --lamp-k 2700 --chandelier 80 --dof 9
python3 cycles_probe/post_look.py "$O/$S-C1-h-dof.png" "$O/$S-C1-h-dof-post.png" --glow 0.25 --vig 0.15 --grain 0.005
echo ALLDONE > "$O/done-$S.txt"
