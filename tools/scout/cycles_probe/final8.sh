#!/usr/bin/env bash
# Позы /demo (C1, C2) — три варианта вертикали (владелец TG 1390; Codex 17.11 п.1): камера на уровне глаз, больше пола.
#   final8.sh <сцена> <имя выгрузки> <папка dump> <папка-вывода> <режим: preview|full> [камеры] [shift для (б)] [высота глаза, м]
#   (б) shift — горизонтальный взгляд (`--level 1`), пол добирает сдвиг объектива вниз (вертикали прямые);
#   (в) pitch — наклон вниз 6°, сдвига нет (вертикали сходятся). (а) — поза /demo как есть (наклон −8°, сдвиг −0,1) — final7.sh.
#   preview — 12 сэмплов 25 % (подбор сдвига: 0,08 / 0,12 / 0,15), full — 64 сэмпла 75 %.
S="$1"; DGN="$2"; DUMP="$3"; O="$4"; MODE="${5:-full}"; CAMS="${6:-C1 C2}"; SHIFT="${7:-0.12}"; EYE="${8:-1.35}"
cd "$(dirname "$0")/.." || exit 1
export EXPD=export2 BL=blender-5.3.0-linux-x64
F=(--view 2 --exposure -0.15 --sun-angle 4 --fill 40 --lamp-k 3000 --chandelier 0 --lamps 5 --sheer 0.5 --normal-k 3.5 --rug-erode 0.025 --cam-h "$EYE" --level 1)
mkdir -p "$O"
go() { local c="$1" tag="$2" n="$3" p="$4"; shift 4; TAG="-$tag" DG="$DGN" EXPJ="$DUMP/scene-export.json" cycles_probe/run.sh "$S" "$c" "$n" "$p" "$O" "${F[@]}" "$@"; }
for C in $CAMS; do
  if [ "$MODE" = "preview" ]; then
    for SH in 0.08 0.12 0.15; do go "$C" "prev-b-shift$SH" 12 25 --shift-y "-$SH"; done
    go "$C" "prev-c-pitch6" 12 25 --pitch 6 --shift-y 0 --pose-mode demo
  else
    go "$C" "b-shift$SHIFT" 64 75 --shift-y "-$SHIFT"
    go "$C" "c-pitch6" 64 75 --pitch 6 --shift-y 0 --pose-mode demo
  fi
done
echo ALLDONE > "$O/done-$S-$MODE.txt"
