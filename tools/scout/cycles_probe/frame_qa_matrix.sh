#!/usr/bin/env bash
# Матрица проверки сторожа кадров (render-qa-gate-01, T-20261118-03/1): на комнату — без инъекций, «пачка» инъекций на разных предметах, камера.
# CPU DEV под heavy-slot (через run.sh), 0 ₽, машину рендера не включает. Запуск на pakardev из worktree:
#   WT=<worktree> tools/scout/cycles_probe/frame_qa_matrix.sh <сцена> <камера> <метка> [ключи render_cycles.py, напр. --qa-inject "art_nomap:картина#0,hide_item:столик#0"]
# Сцена — имя папки в demo_dump/ и export2/ (s-set1, s-set4, s-bed-scandi). Итог — `<папка>/<сцена>-<камера>-<метка>.png` + `.png.qa.json`; таблица — frame_qa_table.py.
set -uo pipefail
S="$1"; C="$2"; T="$3"; shift 3
WT="${WT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)}"
L="$HOME/remlab-logs/t63-1117"
export WT DG="$S" EXPJ="$L/demo_dump/$S/scene-export.json" EXPD=export2 BL="${BL:-blender-5.3.0-linux-x64}" CORES="${CORES:-2}" THR="${CORES:-2}" TAG="-$T"
O="${OUT:-$HOME/remlab-logs/t18-1118/qa}/$S"
exec bash "$WT/tools/scout/cycles_probe/run.sh" "$S" "$C" 16 35 "$O" --view 2 --exposure -0.15 --sun-angle 4 --fill 40 --lamp-k 3000 --chandelier 0 --lamps 1 --sheer 0.5 \
  --normal-k 3.5 --rug-erode 0.025 --transform "Khronos PBR Neutral" --sky-sat 0.4 --fill-k 6500 "$@"
