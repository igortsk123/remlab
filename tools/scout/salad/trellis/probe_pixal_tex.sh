#!/usr/bin/env bash
# T-20261119-05/1, этап 3 — проба `pixal3d-tex` на комоде 112923:13224664101879413845 (форма TRELLIS.2 + краска Pixal3D). НЕ запускалась (этап 3 — после слова директора).
#
#   probe_pixal_tex.sh            — «сухой» прогон: печатает тело группы без секретов, ничего не создаёт и ничего не стоит
#   APPLY=1 probe_pixal_tex.sh    — настоящий запуск (платный, потолок CAP, по умолчанию $0,5) + бесплатная приёмка после него
#   ONLY_SCORE=<папка с .glb> probe_pixal_tex.sh  — только приёмка (кадры и метрика), без Salad
#
# Образ: тот же, что у пробы pixal3d (`Dockerfile.pixal3d`, пересборки НЕ нужно; код едет через command). Адрес — IMAGE (по умолчанию тег пакета pixal3d-trial).
# Группа своя: `trial-pixal3d-tex-<SUFFIX>` (группа рабочего 1 `r30` не трогается). Только 4090, тариф high ($0,33/ч), остановка с проверкой — в драйвере.
# Четыре варианта на одну форму: fit (подгонка фото), official (как в апстриме — контроль), fit+g3 (сильнее слушаться фото), fit+s60 (латент формы по сглаженной копии).
set -u
REPO="${REPO:-/home/pakar/igor/remlab/.claude/worktrees/pixtex-1119}"
TR="$REPO/tools/scout/salad/trellis"
PY="${PY:-$HOME/venvs/scout/bin/python}"
SKU="112923:13224664101879413845"
SKUF="112923_13224664101879413845"
BASE="$HOME/remlab-logs/mesh-models-1118/trellis"
SHAPE="$BASE/${SKUF}-1024-42-0.clean.glb"
IMAGE="${IMAGE:-ghcr.io/igortsk123/mesh-pixal3d-trial:pixal3d-trial}"       # лучше digest (ghcr.io/…@sha256:…) — тот, на котором прошёл прогрев у рабочего 1
CAP="${CAP:-0.5}"
SUFFIX="${SUFFIX:-$(TZ=UTC date +%m%d%H%M)}"
VARIANTS="${VARIANTS:-fit,official,fit+g3,fit+s60}"
OUT="${OUT:-$HOME/remlab-logs/t19-05-1119/probe-$SUFFIX}"
mkdir -p "$OUT"

if [ -z "${ONLY_SCORE:-}" ]; then
  cd "$TR" || exit 2
  FLAG=""
  [ "${APPLY:-0}" = "1" ] && FLAG="--apply"
  "$PY" trellis_trial.py --model pixal3d-tex --image "$IMAGE" --inputs "$BASE/inputs30" --skus "$SKU" \
    --texture-mesh "$SHAPE" --tex-align "$VARIANTS" --plan 1024:1 --seed 42 --tier high --cap "$CAP" \
    --suffix "$SUFFIX" --out "$OUT" $FLAG || exit $?
  [ -z "$FLAG" ] && { echo "сухой прогон окончен: денег 0"; exit 0; }
  GLBS_DIR="$OUT"
else
  GLBS_DIR="$ONLY_SCORE"
fi

# ---- бесплатная приёмка: кадры 0°/45° (Blender под heavy-slot), метрика рисунка, проверка «форма не изменилась» из метрик воркера ----
BLENDER="$HOME/opt/blender-4.5.9/blender"
cd "$REPO" || exit 2
LIST=("$SHAPE")                                                  # контроль: исходная форма с её краской TRELLIS.2 («было»)
for g in "$GLBS_DIR"/${SKUF}-1024-42-0-tex*.glb; do
  case "$g" in *.ai.glb|*.audit.glb|*.clean.glb) continue;; esac
  [ -f "$g" ] && LIST+=("$g")
done
for g in "${LIST[@]}"; do
  n="$(basename "$g" .glb)"
  tools/ops/heavy-slot.sh "p05-$n" --cores 4 --min-gb 3 --timeout 3000 -- "$BLENDER" -b -P "$TR/render_stand.py" -- \
    --glb "$g" --out "$OUT/frames/$n" --samples 32 --modes tex --only az000,az045 >> "$OUT/render.log" 2>&1
done
"$PY" "$TR/score_pixal_tex.py" "$BASE/inputs30/${SKUF}.rgba.png" "$OUT/score" "${LIST[@]}" 2>&1 | tee "$OUT/score.log"
echo "готово: кадры $OUT/frames/*, метрика $OUT/score/score.json, кадры фасада $OUT/score/frames-az000.png и frames-az045.png"
echo "метрики воркера (форма не изменилась: shape.hausdorff_rel <= 1e-4, tris_in == tris_out): $OUT/*.metrics.json"
