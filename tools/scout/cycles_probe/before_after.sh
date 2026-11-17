#!/usr/bin/env bash
# Кадры «было | стало» одной сцены (render-3d-01 шаги 0–1): before_after.sh <сцена> <имя выгрузки декора> <папка dump с scene-export.json> <папка-вывода> [камеры]
#   «было»  — стены и пол ровным цветом паспорта (так их видит /demo без фактуры);
#   «стало» — стены и пол по scene-export.json (карты CC0, тайл и тонировка из описания сцены).
# Blender 5.3, 1536×1116, 64 сэмпла, ядер 8 под heavy-slot. Пример: before_after.sh living-scandi living ~/remlab-logs/t66-1117/dump/living ~/remlab-logs/t66-1117/ba C1 C2
S="$1"; DGN="$2"; DUMP="$3"; O="$4"; shift 4
CAMS=("${@:-C1 C2}")
cd "$(dirname "$0")/.." || exit 1
export EXPD=export2 BL=blender-5.3.0-linux-x64
for c in ${CAMS[@]}; do
  DG=$DGN TAG=-before cycles_probe/run.sh "$S" "$c" 64 75 "$O" --view 3
  DG=$DGN TAG=-after EXPJ="$DUMP/scene-export.json" cycles_probe/run.sh "$S" "$c" 64 75 "$O" --view 3
done
echo ALLDONE > "$O/done-$S.txt"
