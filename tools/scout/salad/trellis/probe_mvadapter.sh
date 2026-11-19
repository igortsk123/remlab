#!/usr/bin/env bash
# T-20261119-06/2 — проба `mvadapter-i2tex` на ОДНОМ ИЛИ НЕСКОЛЬКИХ товарах в одной группе (T-20261119-06/5/2: один прогрев весов, у каждого товара своя форма): готовая форма TRELLIS.2 (очищенный GLB) + одно фото → краска MV-Adapter (6 видов SDXL → проекция на готовую развёртку).
# Сравнивается с лучшим гибридом (форма TRELLIS.2 + краска Hunyuan). НЕ запускалась: настоящий запуск платный — только после слова директора/менеджера.
# Товары — обязательный вход: `probe_mvadapter.sh <магазин:товар> [<магазин:товар> …]` или `SKU="a:1 b:2"` (в коде и в этом файле товаров нет). Нет — отказ с кодом 2.
# Форма КАЖДОГО товара: `~/remlab-logs/mesh-models-1118/trellis/<магазин_товар>-1024-42-0.clean2.glb`, если есть, иначе `.clean.glb` (скрипт печатает, какой взял). Фото: `inputs30/<магазин_товар>.rgba.png` рядом.
#
#   probe_mvadapter.sh <SKU> […]              — «сухой» прогон: печатает тело группы без секретов, ничего не создаёт и ничего не стоит (денег 0)
#   APPLY=1 probe_mvadapter.sh <SKU> […]      — настоящий запуск (платный, потолок CAP, по умолчанию $0,35) + бесплатная приёмка после него (кадры, лист «эталон | наше»)
#   ONLY_SCORE=<папка с .glb> probe_mvadapter.sh <SKU> […]   — только приёмка, без Salad
#
# Образ: `Dockerfile.mvadapter` (собирается на GitHub Actions пушем в ветку trial/trellis2*; адрес — IMAGE, лучше digest). Код воркера едет через command. Веса ≈ 10 ГиБ докачиваются на старте.
# Группа своя: `trial-mvadapter-i2tex-<SUFFIX>` (группа рабочего 1 `r30` не трогается). Только 4090, тариф high, остановка с проверкой — в драйвере.
# Параметры: MV_YAW=auto|0|90|180|270 (поворот формы лицом к виду 0; auto — по силуэту фото), MV_UV_SIZE=4096|2048|1024, MV_STEPS=50, MV_REF_SCALE=1.0,
# DEBUG_CUDA=1 (CUDA_LAUNCH_BLOCKING + стеки C++), WORKER_ENV="MVTEX_OFFLOAD=0 MVTEX_ALLOC_CONF=…".
# Результат: OUT (по умолчанию ~/remlab-logs/t19-06-1119/run-<ЧЧММ по Лондону>/), НЕ папка `trellis/` (чужие результаты не затираются); задание — `<магазин_товар>-1024-42-0-mvtex` (GLB лежат в OUT);
# кадры, лист «гибрид р.3 | MV-Adapter» и метрика — по товару, в подпапке `OUT/<магазин_товар>/`.
set -u
. "$(cd "$(dirname "$0")" && pwd)/probe_lib.sh"
probe_init "$@"                                   # товары, формы, фото, эталоны — по каждому; нет формы или фото у одного — отказ здесь, до группы
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
  "$PY" trellis_trial.py --model mvadapter-i2tex --image "$IMAGE" --inputs "$BASE/inputs30" --skus "${SKUS[@]}" \
    --shape-dir "$BASE" --plan 1024:1 --seed 42 --tier high --cap "$CAP" --suffix "$SUFFIX" --out "$OUT" \
    --mv-yaw "${MV_YAW:-auto}" --mv-uv-size "${MV_UV_SIZE:-4096}" --mv-steps "${MV_STEPS:-50}" --mv-ref-scale "${MV_REF_SCALE:-1.0}" \
    ${EXTRA[@]+"${EXTRA[@]}"} $FLAG || exit $?
  [ -z "$FLAG" ] && { echo "сухой прогон окончен: денег 0"; exit 0; }
  GLBS_DIR="$OUT"
else
  GLBS_DIR="$ONLY_SCORE"
fi

# ---- бесплатная приёмка по каждому товару (кадры, лист, метрика — в $OUT/<магазин_товар>/; общая функция probe_accept из probe_lib.sh) ----
probe_accept mvtex "MV-Adapter" nomva || exit 1
echo "метрики воркера по товарам: $OUT/summary-trial-mvadapter-i2tex-$SUFFIX.json (раздел by_sku — итог по товару; форма не изменилась: shape.hausdorff_rel <= 1e-4, uv_max_dev; стадии: stage_s; пик памяти: peak_vram_gb, mem; при падении — diag); шесть видов SDXL — $OUT/<магазин_товар>-1024-42-0-mvtex.views.jpg"
