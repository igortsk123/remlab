#!/usr/bin/env bash
# T-20261119-06/5 — проба `supratex` на ОДНОМ товаре: наша готовая форма (очищенный GLB TRELLIS.2) + одно фото → SUPRA-Tex КАК ЕСТЬ (с Qwen-Image-2.1): Qwen рисует альбедо и карту материала,
# генератор SUPRA красит форму и САМ выпускает GLB (ремеш, до 500 тыс. граней, новая развёртка, текстура 4096²). Оценка ВИДА (владелец: решения с некоммерческими частями — если заменимы за месяц).
# НЕ запускалась: настоящий запуск платный — только после слова директора/менеджера. Потолок CAP $0,35 (по умолчанию).
# Товар — обязательный вход: `SKU=<магазин:товар> probe_supratex.sh` или первым аргументом (в коде и в этом файле товаров нет). Нет — отказ с кодом 2.
# Форма: `~/remlab-logs/mesh-models-1118/trellis/<магазин_товар>-1024-42-0.clean2.glb`, если есть, иначе `.clean.glb` (скрипт печатает, какой взял). Фото: `inputs30/<магазин_товар>.rgba.png` рядом.
#
#   probe_supratex.sh <SKU>              — «сухой» прогон: печатает тело группы без секретов, ничего не создаёт и ничего не стоит (денег 0)
#   APPLY=1 probe_supratex.sh <SKU>      — настоящий запуск (платный, потолок CAP) + бесплатная приёмка (кадры, лист «гибрид р.3 | MV-Adapter | SUPRA-Tex», метрика рисунка)
#   ONLY_SCORE=<папка с .glb> probe_supratex.sh <SKU>   — только приёмка, без Salad
#
# Образ: `Dockerfile.supratex` (Actions, пуш в ветку trial/trellis2*; адрес — IMAGE, лучше digest). Код воркера едет через command. Веса ≈ 43 ГиБ докачиваются на старте (открытые, токен не нужен).
# Память группы 48 ГиБ (пик процессов SUPRA ≈ 32,4 ГиБ), диск 80 ГиБ — выставляет драйвер. Группа своя: `trial-supratex-<SUFFIX>`. Только 4090, тариф high, остановка с проверкой — в драйвере.
# Параметры: SUPRA_REFINE=1 (--refine апстрима, чёткий мелкий рисунок), SUPRA_TEX_SIZE=4096|2048|1024, SUPRA_DECIMATION=500000, DEBUG_CUDA=1, WORKER_ENV="CUDA_LAUNCH_BLOCKING=1".
# Результат: OUT (по умолчанию ~/remlab-logs/t19-06-1119/supra-<ЧЧММ по Лондону>/), НЕ папка `trellis/`; задание называется `<магазин_товар>-1024-42-0-supra`.
# Лист: столбцы «гибрид р.3» (эталон) | «MV-Adapter» (последний прогон `t19-06-1119/run-*` с кадрами этого товара; нет — столбца нет) | «SUPRA-Tex».
set -u
REPO="${REPO:-/home/pakar/igor/remlab/.claude/worktrees/supratex-1119}"
TR="$REPO/tools/scout/salad/trellis"
PY="${PY:-$HOME/venvs/scout/bin/python}"
SKU="${1:-${SKU:-}}"
case "$SKU" in
  *:*) ;;
  *) echo "нужен товар: SKU=<магазин:товар> $0 (или первым аргументом)" >&2; exit 2;;
esac
SKUF="${SKU//:/_}"
LOGS="$HOME/remlab-logs/mesh-models-1118"
BASE="$LOGS/trellis"
if [ -f "$BASE/${SKUF}-1024-42-0.clean2.glb" ]; then
  SHAPE="$BASE/${SKUF}-1024-42-0.clean2.glb"; SHAPE_KIND="clean2 (правило очистки E)"
elif [ -f "$BASE/${SKUF}-1024-42-0.clean.glb" ]; then
  SHAPE="$BASE/${SKUF}-1024-42-0.clean.glb"; SHAPE_KIND="clean (прежнее правило очистки; clean2 нет)"
else
  echo "нет формы: ни $BASE/${SKUF}-1024-42-0.clean2.glb, ни .clean.glb" >&2; exit 2
fi
echo "форма: $SHAPE — $SHAPE_KIND"
PHOTO="$BASE/inputs30/${SKUF}.rgba.png"
[ -f "$PHOTO" ] || { echo "нет фото: $PHOTO" >&2; exit 2; }
REF=""
for c in "$LOGS/frames-clean2/hybrid/noremesh/$SKUF" "$LOGS/frames-clean2/hybrid/$SKUF" "$LOGS/frames-clean/hybrid/noremesh/$SKUF"; do
  [ -d "$c" ] && { REF="$c"; break; }
done
if [ -n "$REF" ]; then echo "эталон (гибрид р.3, кадры 0°/45°): $REF"; else echo "эталона-гибрида для этого товара нет в frames-clean2/hybrid и frames-clean/hybrid/noremesh — в листе его столбца не будет" >&2; fi
MVF=""
for d in $(ls -d "$HOME"/remlab-logs/t19-06-1119/run-*/frames/"${SKUF}-1024-42-0-mvtex" 2>/dev/null | sort -r); do
  [ -d "$d" ] && { MVF="$d"; break; }
done
if [ -n "$MVF" ]; then echo "MV-Adapter (кадры последнего прогона): $MVF"; else echo "кадров MV-Adapter для этого товара нет (t19-06-1119/run-*/frames/${SKUF}-1024-42-0-mvtex) — в листе его столбца не будет" >&2; fi
IMAGE="${IMAGE:-ghcr.io/igortsk123/mesh-supratex-trial:supratex-trial}"       # лучше digest (ghcr.io/…@sha256:…), на котором прошёл прогрев
CAP="${CAP:-0.35}"
SUFFIX="${SUFFIX:-$(TZ=UTC date +%m%d%H%M)}"
STAMP="$(TZ=Europe/London date +%H%M)"
OUT="${OUT:-$HOME/remlab-logs/t19-06-1119/supra-$STAMP}"
mkdir -p "$OUT"

if [ -z "${ONLY_SCORE:-}" ]; then
  cd "$TR" || exit 2
  FLAG=""
  [ "${APPLY:-0}" = "1" ] && FLAG="--apply"
  EXTRA=()
  [ "${DEBUG_CUDA:-0}" = "1" ] && EXTRA+=(--debug-cuda)
  [ "${SUPRA_REFINE:-0}" = "1" ] && EXTRA+=(--supra-refine)
  for kv in ${WORKER_ENV:-}; do EXTRA+=(--worker-env "$kv"); done
  "$PY" trellis_trial.py --model supratex --image "$IMAGE" --inputs "$BASE/inputs30" --skus "$SKU" \
    --texture-mesh "$SHAPE" --plan 1024:1 --seed 42 --tier high --cap "$CAP" --suffix "$SUFFIX" --out "$OUT" --job-timeout 40 \
    --supra-texture-size "${SUPRA_TEX_SIZE:-4096}" --supra-decimation "${SUPRA_DECIMATION:-500000}" \
    ${EXTRA[@]+"${EXTRA[@]}"} $FLAG || exit $?
  [ -z "$FLAG" ] && { echo "сухой прогон окончен: денег 0"; exit 0; }
  GLBS_DIR="$OUT"
else
  GLBS_DIR="$ONLY_SCORE"
fi

# ---- бесплатная приёмка: кадры 0°/45° (Blender под heavy-slot; имена 01_az000_tex, 02_az000_clay, 03_az045_tex, 04_az045_clay), лист, метрика рисунка ----
BLENDER="$HOME/opt/blender-4.5.9/blender"
cd "$REPO" || exit 2
OURS="$GLBS_DIR/${SKUF}-1024-42-0-supra.glb"
[ -f "$OURS" ] || { echo "результата нет: $OURS (задание упало? смотри summary-*.json в $OUT)" >&2; exit 1; }
n="$(basename "$OURS" .glb)"
tools/ops/heavy-slot.sh "p06-$n" --cores 4 --min-gb 3 --timeout 3000 -- "$BLENDER" -b -P "$TR/render_stand.py" -- \
  --glb "$OURS" --out "$OUT/frames/$n" --samples 32 --modes tex,clay --only az000,az045 >> "$OUT/render.log" 2>&1
COLS=()
[ -n "$REF" ] && COLS+=("гибрид р.3=$REF")
[ -n "$MVF" ] && COLS+=("MV-Adapter=$MVF")
COLS+=("SUPRA-Tex=$OUT/frames/$n")
"$PY" "$TR/mv_sheet.py" --cols "${COLS[@]}" --out "$OUT/side-by-side.png" 2>&1 | tee -a "$OUT/render.log"
"$PY" "$TR/score_pixal_tex.py" "$PHOTO" "$OUT/score" "$SHAPE" "$OURS" 2>&1 | tee "$OUT/score.log" || echo "метрика рисунка не посчиталась (кадры и лист — выше)"
echo "готово: кадры $OUT/frames/$n/ (отдельные файлы полного размера), лист $OUT/side-by-side.png, метрика $OUT/score/score.json"
echo "метрики воркера (ФОРМА МЕНЯЕТСЯ: shape.faces_in/faces_out, hausdorff_rel/mean_rel/p99_rel, out_frame; стадии: stage_s; пики: peak_vram_mib, peak_cgroup_gb, child_maxrss_gb; при падении — diag): $OUT/summary-trial-supratex-$SUFFIX.json"
