#!/usr/bin/env bash
# T-20261119-06/2 — проба `mvadapter-i2tex` на ОДНОМ товаре: готовая форма TRELLIS.2 (очищенный GLB) + одно фото → краска MV-Adapter (6 видов SDXL → проекция на готовую развёртку).
# Сравнивается с лучшим гибридом (форма TRELLIS.2 + краска Hunyuan). НЕ запускалась: настоящий запуск платный — только после слова директора/менеджера.
# Товар — обязательный вход: `SKU=<магазин:товар> probe_mvadapter.sh` или первым аргументом (в коде и в этом файле товаров нет). Нет — отказ с кодом 2.
# Форма: `~/remlab-logs/mesh-models-1118/trellis/<магазин_товар>-1024-42-0.clean2.glb`, если есть, иначе `.clean.glb` (скрипт печатает, какой взял). Фото: `inputs30/<магазин_товар>.rgba.png` рядом.
#
#   probe_mvadapter.sh <SKU>              — «сухой» прогон: печатает тело группы без секретов, ничего не создаёт и ничего не стоит (денег 0)
#   APPLY=1 probe_mvadapter.sh <SKU>      — настоящий запуск (платный, потолок CAP, по умолчанию $0,35) + бесплатная приёмка после него (кадры, лист «эталон | наше»)
#   ONLY_SCORE=<папка с .glb> probe_mvadapter.sh <SKU>   — только приёмка, без Salad
#
# Образ: `Dockerfile.mvadapter` (собирается на GitHub Actions пушем в ветку trial/trellis2*; адрес — IMAGE, лучше digest). Код воркера едет через command. Веса ≈ 10 ГиБ докачиваются на старте.
# Группа своя: `trial-mvadapter-i2tex-<SUFFIX>` (группа рабочего 1 `r30` не трогается). Только 4090, тариф high, остановка с проверкой — в драйвере.
# Параметры: MV_YAW=auto|0|90|180|270 (поворот формы лицом к виду 0; auto — по силуэту фото), MV_UV_SIZE=4096|2048|1024, MV_STEPS=50, MV_REF_SCALE=1.0,
# DEBUG_CUDA=1 (CUDA_LAUNCH_BLOCKING + стеки C++), WORKER_ENV="MVTEX_OFFLOAD=0 MVTEX_ALLOC_CONF=…".
# Результат: OUT (по умолчанию ~/remlab-logs/t19-06-1119/run-<ЧЧММ по Лондону>/), НЕ папка `trellis/` (чужие результаты не затираются); задание называется `<магазин_товар>-1024-42-0-mvtex`.
set -u
REPO="${REPO:-/home/pakar/igor/remlab/.claude/worktrees/mvadapter-1119}"
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
if [ -n "$REF" ]; then echo "эталон (гибрид, кадры 0°/45°): $REF"; else echo "эталона-гибрида для этого товара нет в frames-clean2/hybrid и frames-clean/hybrid/noremesh — лист «эталон | наше» не соберётся" >&2; fi
IMAGE="${IMAGE:-ghcr.io/igortsk123/mesh-mvadapter-trial:mvadapter-trial}"       # лучше digest (ghcr.io/…@sha256:…), на котором прошёл прогрев
CAP="${CAP:-0.35}"
SUFFIX="${SUFFIX:-$(TZ=UTC date +%m%d%H%M)}"
STAMP="$(TZ=Europe/London date +%H%M)"
OUT="${OUT:-$HOME/remlab-logs/t19-06-1119/run-$STAMP}"
mkdir -p "$OUT"

if [ -z "${ONLY_SCORE:-}" ]; then
  cd "$TR" || exit 2
  FLAG=""
  [ "${APPLY:-0}" = "1" ] && FLAG="--apply"
  EXTRA=()
  [ "${DEBUG_CUDA:-0}" = "1" ] && EXTRA+=(--debug-cuda)
  for kv in ${WORKER_ENV:-}; do EXTRA+=(--worker-env "$kv"); done
  "$PY" trellis_trial.py --model mvadapter-i2tex --image "$IMAGE" --inputs "$BASE/inputs30" --skus "$SKU" \
    --texture-mesh "$SHAPE" --plan 1024:1 --seed 42 --tier high --cap "$CAP" --suffix "$SUFFIX" --out "$OUT" \
    --mv-yaw "${MV_YAW:-auto}" --mv-uv-size "${MV_UV_SIZE:-4096}" --mv-steps "${MV_STEPS:-50}" --mv-ref-scale "${MV_REF_SCALE:-1.0}" \
    ${EXTRA[@]+"${EXTRA[@]}"} $FLAG || exit $?
  [ -z "$FLAG" ] && { echo "сухой прогон окончен: денег 0"; exit 0; }
  GLBS_DIR="$OUT"
else
  GLBS_DIR="$ONLY_SCORE"
fi

# ---- бесплатная приёмка: кадры 0°/45° (Blender под heavy-slot; имена 01_az000_tex, 02_az000_clay, 03_az045_tex, 04_az045_clay), лист «эталон | наше», метрика рисунка ----
BLENDER="$HOME/opt/blender-4.5.9/blender"
cd "$REPO" || exit 2
OURS="$GLBS_DIR/${SKUF}-1024-42-0-mvtex.glb"
[ -f "$OURS" ] || { echo "результата нет: $OURS (задание упало? смотри summary-*.json в $OUT)" >&2; exit 1; }
n="$(basename "$OURS" .glb)"
tools/ops/heavy-slot.sh "p06-$n" --cores 4 --min-gb 3 --timeout 3000 -- "$BLENDER" -b -P "$TR/render_stand.py" -- \
  --glb "$OURS" --out "$OUT/frames/$n" --samples 32 --modes tex,clay --only az000,az045 >> "$OUT/render.log" 2>&1
if [ -n "$REF" ]; then
  "$PY" "$TR/mv_sheet.py" "$REF" "$OUT/frames/$n" "$OUT/side-by-side.png" 2>&1 | tee -a "$OUT/render.log"
fi
"$PY" "$TR/score_pixal_tex.py" "$PHOTO" "$OUT/score" "$SHAPE" "$OURS" 2>&1 | tee "$OUT/score.log" || echo "метрика рисунка не посчиталась (кадры и лист — выше)"
echo "готово: кадры $OUT/frames/$n/ (отдельные файлы полного размера), лист $OUT/side-by-side.png, метрика $OUT/score/score.json"
echo "метрики воркера (форма не изменилась: shape.hausdorff_rel <= 1e-4, uv_max_dev; стадии: stage_s; пик памяти: peak_vram_gb, mem; при падении — diag): $OUT/summary-trial-mvadapter-i2tex-$SUFFIX.json; шесть видов SDXL — $OUT/$n.views.jpg"
