#!/usr/bin/env bash
# T-20261119-80 — проба `triposg-mv` (вариант 6, владелец TG 2250–2256): форма TripoSG («набросок геометрии») → развёртка CuMesh (как у TRELLIS.2) → чистка общим правилом E → краска MV-Adapter (тот же код, что у mvadapter-i2tex).
# Вопрос пробы: чище ли краска на форме TripoSG, чем на формах TRELLIS.2 (меньше «невидимых» и незакрашенных текселей, глаже поверхности). Главная мера — узор и цвет как на фото (ADR-0451).
# Товары — обязательный вход: `probe_triposg.sh <магазин:товар> [<магазин:товар> …]` (в коде и в этом файле товаров нет). Фото — `inputs30/<магазин_товар>.rgba.png`; формы НЕ нужны: их рисует TripoSG на ноде.
#
#   probe_triposg.sh <SKU> […]                  — «сухой» прогон: тело группы без секретов, проверка «карта ↔ образ», живая цена; денег 0
#   APPLY=1 probe_triposg.sh <SKU> […]          — настоящий запуск (платный, потолок CAP, по умолчанию $0,30 на ВЕСЬ вариант; одна группа, один холодный старт, товары по очереди: форма → краска) + бесплатная приёмка
#   ONLY_SCORE=1 OUT=<папка> probe_triposg.sh <SKU> […]   — только приёмка по готовым GLB в OUT, без Salad
#
# Образ: `Dockerfile.triposg` (GitHub Actions, ветка trial/triposg*; адрес — IMAGE, лучше digest). Только 4090 (образ собран под архитектуру 8.9: драйвер сверяет карту ДО группы, урок 742).
# Результат: OUT (по умолчанию ~/remlab-logs/mesh-models-1118/triposg-mv/), задания `<магазин_товар>-1024-42-0-tpshape` (форма без краски; рядом `.clean2.glb`, `.metrics2.json`, `.audit2.glb`) и `-tpmv` (итог).
# Приёмка (бесплатно, процессор): кадры 0° и 45° с текстурой и глиняные (форма) — ОТДЕЛЬНЫМИ файлами полного размера в `OUT/<магазин_товар>/frames/<id>/` тем же `render_stand.py` и теми же настройками, что `frames-clean2`;
# товары снимаются ДВУМЯ процессами одновременно под heavy-slot (по --cores 2 каждый, указание директора); метрика покрытия `tex_coverage.py` (unseen / grazing / unpainted + шов) — `OUT/coverage/`.
# Для сравнения: `~/remlab-logs/mesh-models-1118/frames-clean2/mvadapter/<магазин_товар>/` (краска MV-Adapter на форме TRELLIS.2).
set -u
REPO="${REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)}"
TR="$REPO/tools/scout/salad/trellis"
PY="${PY:-$HOME/venvs/scout/bin/python}"
LOGS="$HOME/remlab-logs/mesh-models-1118"
BASE="$LOGS/trellis"
SKUS=("$@")
if [ "${#SKUS[@]}" -eq 0 ]; then
  echo "нужен хотя бы один товар: $0 <магазин:товар> [<магазин:товар> …]" >&2
  exit 2
fi
for s in "${SKUS[@]}"; do
  case "$s" in *:*) ;; *) echo "товар «$s» не похож на <магазин:товар>" >&2; exit 2;; esac
  [ -f "$BASE/inputs30/${s//:/_}.rgba.png" ] || { echo "[$s] нет фото: $BASE/inputs30/${s//:/_}.rgba.png" >&2; exit 2; }
done
IMAGE="${IMAGE:-ghcr.io/igortsk123/mesh-triposg-trial:triposg-trial}"
CAP="${CAP:-0.30}"
SUFFIX="${SUFFIX:-$(TZ=UTC date +%m%d%H%M)}"
OUT="${OUT:-$LOGS/triposg-mv}"
mkdir -p "$OUT"

if [ -z "${ONLY_SCORE:-}" ]; then
  cd "$TR" || exit 2
  FLAG=""
  [ "${APPLY:-0}" = "1" ] && FLAG="--apply"
  EXTRA=()
  [ "${DEBUG_CUDA:-0}" = "1" ] && EXTRA+=(--debug-cuda)
  [ -n "${TP_STEPS:-}" ] && EXTRA+=(--tp-steps "$TP_STEPS")
  [ -n "${TP_GUIDANCE:-}" ] && EXTRA+=(--tp-guidance "$TP_GUIDANCE")
  for kv in ${WORKER_ENV:-}; do EXTRA+=(--worker-env "$kv"); done
  "$PY" trellis_trial.py --model triposg-mv --image "$IMAGE" --inputs "$BASE/inputs30" --skus "${SKUS[@]}" \
    --plan 1024:1 --seed 42 --tier high --cap "$CAP" --suffix "$SUFFIX" --out "$OUT" \
    --mv-yaw "${MV_YAW:-auto}" --mv-uv-size "${MV_UV_SIZE:-4096}" --mv-steps "${MV_STEPS:-50}" --mv-ref-scale "${MV_REF_SCALE:-1.0}" \
    ${EXTRA[@]+"${EXTRA[@]}"} $FLAG || exit $?
  [ -z "$FLAG" ] && { echo "сухой прогон окончен: денег 0"; exit 0; }
fi

# ---- бесплатная приёмка: кадры по товарам ДВУМЯ процессами одновременно (heavy-slot, по 2 ядра), затем метрика покрытия ----
blender="$HOME/opt/blender-4.5.9/blender"
cd "$REPO" || exit 2
frames_one() {      # frames_one <товар> — кадры 0°/45° с текстурой и глиняные итоговой формы (краска + форма) в OUT/<магазин_товар>/frames/<id>/
  local s="$1" skuf n glb d
  skuf="${s//:/_}"
  n="${skuf}-1024-42-0-tpmv"
  glb="$OUT/$n.glb"
  d="$OUT/$skuf"
  mkdir -p "$d"
  if [ ! -f "$glb" ]; then echo "[$s] результата нет: $glb (задание упало? смотри summary-*.json в $OUT)" >&2; return 1; fi
  tools/ops/heavy-slot.sh "p80-$n" --cores 2 --prio 1 --min-gb 3 --timeout 3000 -- "$blender" -b -P "$TR/render_stand.py" -- \
    --glb "$glb" --out "$d/frames/$n" --samples 32 --modes tex,clay --only az000,az045 >> "$d/render.log" 2>&1
  echo "[$s] кадры: $d/frames/$n/ (отдельные файлы полного размера; сравнить с $LOGS/frames-clean2/mvadapter/$skuf/)"
}
pids=()
for s in "${SKUS[@]}"; do
  frames_one "$s" &
  pids+=($!)
done
fails=0
for p in "${pids[@]}"; do wait "$p" || fails=$((fails + 1)); done

mkdir -p "$OUT/coverage"
SUMMARY="$(ls -t "$OUT"/summary-trial-triposg-mv-*.json 2>/dev/null | head -1)"
"$PY" "$TR/tex_coverage.py" --out "$OUT/coverage" --pattern '*-tpmv.glb' "$OUT" 2>&1 | tee "$OUT/coverage/coverage.log" || echo "метрика покрытия не посчиталась (кадры — выше)"
echo "метрики воркера и счётчик отказов по классам: $SUMMARY (by_sku: форма и краска каждого товара, очистка; fail_classes; cost_usd_est)"
[ "$fails" = 0 ]
