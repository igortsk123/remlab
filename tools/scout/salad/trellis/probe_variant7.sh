#!/usr/bin/env bash
# T-20261119-92/1 — Вариант 7 пробы покраски: форма TRELLIS.2 (очищенная clean2 (clean3 режет обивку — директор 19.11 14:55)) + краска Pixal3D, ОДИН товар за запуск (драйвер: одна форма на группу).
# Путь А — карта 5090 32 ГБ, образ Blackwell (Dockerfile.pixal3d-bw), форма как есть:  PATHID=A SKU=... probe_variant7.sh
# Путь Б — карта 4090 24 ГБ, прежний образ, форма вписана в долю куба (+f<процент>):    PATHID=B SKU=... probe_variant7.sh
#   probe_variant7.sh           — сухой прогон: тело группы без секретов, живая цена, ничего не создаёт и не стоит
#   APPLY=1 probe_variant7.sh   — платный запуск (потолок CAP на группу); группа гасится драйвером сразу после заданий, стоп проверяется
# Все выходы — ~/remlab-logs/t92-1119/<путь>-<товар>-<метка>/ (новая папка с меткой, старое не трогаем).
set -u
REPO="${REPO:-/home/pakar/igor/remlab/.claude/worktrees/pixtex-1119}"
TR="$REPO/tools/scout/salad/trellis"
PY="${PY:-$HOME/venvs/scout/bin/python}"
PATHID="${PATHID:-}"
SKU="${SKU:-${1:-}}"
case "$SKU" in *:*) ;; *) echo "нужен товар: SKU=<магазин:товар> PATHID=A|B $0" >&2; exit 2;; esac
SKUF="${SKU//:/_}"
BASE="$HOME/remlab-logs/mesh-models-1118"
SHAPE="${SHAPE:-$BASE/trellis2/${SKUF}-1024-42-0.clean2.glb}"
[ -f "$SHAPE" ] || { echo "нет формы $SHAPE" >&2; exit 2; }
case "$PATHID" in
  A) CARD_NAME="RTX 5090 (32 GB)"; IMAGE="${IMAGE:-ghcr.io/igortsk123/mesh-pixal3d-trial:pixal3d-bw}"; VARIANTS="${VARIANTS:-fit,official}"; CAP="${CAP:-0.45}";;
  B) CARD_NAME="RTX 4090 (24 GB)"; IMAGE="${IMAGE:-ghcr.io/igortsk123/mesh-pixal3d-trial:pixal3d-trial}"; VARIANTS="${VARIANTS:-fit+f50,fit+f70,fit+f85}"; CAP="${CAP:-0.35}";;
  *) echo "PATHID=A (5090) или B (4090)" >&2; exit 2;;
esac
SUFFIX="${SUFFIX:-$(TZ=UTC date +%m%d%H%M)}"
SHORT="${SKUF#*_}"; SHORT="${SHORT: -4}"
OUT="${OUT:-$HOME/remlab-logs/t92-1119/${PATHID}-${SKUF%%_*}-${SHORT}-$SUFFIX}"
mkdir -p "$OUT"
FLAG=""
[ "${APPLY:-0}" = "1" ] && FLAG="--apply"
EXTRA=()
for kv in ${WORKER_ENV:-}; do EXTRA+=(--worker-env "$kv"); done
cd "$TR" || exit 2
"$PY" trellis_trial.py --model pixal3d-tex --image "$IMAGE" --inputs "$BASE/trellis/inputs30" --skus "$SKU" --texture-mesh "$SHAPE" \
  --tex-align "$VARIANTS" --plan 1024:1 --seed 42 --tier high --cap "$CAP" --card "$CARD_NAME" --suffix "v7${PATHID,,}-$SUFFIX" --out "$OUT" \
  ${EXTRA[@]+"${EXTRA[@]}"} $FLAG 2>&1 | tee "$OUT/driver.log"
exit "${PIPESTATUS[0]}"
