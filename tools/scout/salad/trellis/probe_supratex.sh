#!/usr/bin/env bash
# T-20261119-06/5 — проба `supratex` на ОДНОМ ИЛИ НЕСКОЛЬКИХ товарах в одной группе (T-20261119-06/5/2: один прогрев весов, у каждого товара своя форма): наша готовая форма (очищенный GLB TRELLIS.2) + одно фото → SUPRA-Tex КАК ЕСТЬ (с Qwen-Image-2.1): Qwen рисует альбедо и карту материала,
# генератор SUPRA красит форму и САМ выпускает GLB (ремеш, до 500 тыс. граней, новая развёртка, текстура 4096²). Оценка ВИДА (владелец: решения с некоммерческими частями — если заменимы за месяц).
# НЕ запускалась: настоящий запуск платный — только после слова директора/менеджера. Потолок CAP $0,35 (по умолчанию).
# Товары — обязательный вход: `probe_supratex.sh <магазин:товар> [<магазин:товар> …]` или `SKU="a:1 b:2"` (в коде и в этом файле товаров нет). Нет — отказ с кодом 2.
# Форма КАЖДОГО товара: `~/remlab-logs/mesh-models-1118/trellis/<магазин_товар>-1024-42-0.clean2.glb`, если есть, иначе `.clean.glb` (скрипт печатает, какой взял). Фото: `inputs30/<магазин_товар>.rgba.png` рядом.
#
#   probe_supratex.sh <SKU> […]              — «сухой» прогон: печатает тело группы без секретов, ничего не создаёт и ничего не стоит (денег 0)
#   APPLY=1 probe_supratex.sh <SKU> […]      — настоящий запуск (платный, потолок CAP) + бесплатная приёмка (кадры, лист «гибрид р.3 | MV-Adapter | SUPRA-Tex», метрика рисунка)
#   ONLY_SCORE=<папка с .glb> probe_supratex.sh <SKU> […]   — только приёмка, без Salad
#
# Образ: `Dockerfile.supratex` (Actions, пуш в ветку trial/trellis2*; адрес — IMAGE, лучше digest). Код воркера едет через command. Веса ≈ 43 ГиБ докачиваются на старте (открытые, токен не нужен).
# Память группы 48 ГиБ (пик процессов SUPRA ≈ 32,4 ГиБ), диск 80 ГиБ — выставляет драйвер. Группа своя: `trial-supratex-<SUFFIX>`. Только 4090, тариф high, остановка с проверкой — в драйвере.
# Параметры: SUPRA_REFINE=1 (--refine апстрима, чёткий мелкий рисунок), SUPRA_TEX_SIZE=4096|2048|1024, SUPRA_DECIMATION=500000, DEBUG_CUDA=1, WORKER_ENV="CUDA_LAUNCH_BLOCKING=1".
# Результат: OUT (по умолчанию ~/remlab-logs/t19-06-1119/supra-<ЧЧММ по Лондону>/), НЕ папка `trellis/`; задание — `<магазин_товар>-1024-42-0-supra` (GLB лежат в OUT);
# кадры, лист «гибрид р.3 | MV-Adapter (если есть) | SUPRA-Tex» и метрика — по товару, в подпапке `OUT/<магазин_товар>/`. Потолок CAP — на ВСЮ группу (все товары).
# Лист: столбцы «гибрид р.3» (эталон) | «MV-Adapter» (последний прогон `t19-06-1119/run-*` с кадрами этого товара; нет — столбца нет) | «SUPRA-Tex».
set -u
. "$(cd "$(dirname "$0")" && pwd)/probe_lib.sh"
probe_init "$@"                                   # товары, формы, фото, эталоны — по каждому; нет формы или фото у одного — отказ здесь, до группы
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
  "$PY" trellis_trial.py --model supratex --image "$IMAGE" --inputs "$BASE/inputs30" --skus "${SKUS[@]}" \
    --shape-dir "$SHAPE_DIR" --plan 1024:1 --seed 42 --tier high --cap "$CAP" --suffix "$SUFFIX" --out "$OUT" \
    --job-timeout "${JOB_MIN:-40}" \
    --supra-texture-size "${SUPRA_TEX_SIZE:-4096}" --supra-decimation "${SUPRA_DECIMATION:-500000}" \
    ${EXTRA[@]+"${EXTRA[@]}"} $FLAG || exit $?
  [ -z "$FLAG" ] && { echo "сухой прогон окончен: денег 0"; exit 0; }
  GLBS_DIR="$OUT"
else
  GLBS_DIR="$ONLY_SCORE"
fi

# ---- бесплатная приёмка по каждому товару (кадры, лист, метрика — в $OUT/<магазин_товар>/; общая функция probe_accept из probe_lib.sh) ----
probe_accept supra "SUPRA-Tex" || exit 1
echo "метрики воркера по товарам: $OUT/summary-trial-supratex-$SUFFIX.json (раздел by_sku — итог по товару; ФОРМА МЕНЯЕТСЯ: shape.faces_in/faces_out, hausdorff_rel/mean_rel/p99_rel, out_frame; стадии: stage_s; пики: peak_vram_mib, peak_cgroup_gb, child_maxrss_gb; при падении — diag)"
