#!/usr/bin/env bash
# T-20261119-06/4 — проба `mvpainter` на ОДНОМ ИЛИ НЕСКОЛЬКИХ товарах в одной группе (T-20261119-06/5/2: один прогрев весов, у каждого товара своя форма): готовая форма TRELLIS.2 (очищенный GLB) + одно фото → краска MVPainter КАК У АВТОРОВ (6 видов диффузией, PBR через IDArb,
# штатное упрощение формы до 30 тыс. вершин, развёртка xatlas, запекание). Сравнивается с лучшим гибридом (форма TRELLIS.2 + краска Hunyuan) и с MV-Adapter (если его проба уже была).
# Критерий пробы — только ВИД: кадры 0°/45° против гибрида (форма здесь меняется законно — владелец 19.11, TG 2149/2150; сколько сжали — в метриках `simplify`).
# НЕ запускалась: настоящий запуск платный — только после слова менеджера. Потолок денег по умолчанию $1,0 (владелец TG 2147).
# Товары — обязательный вход: `probe_mvpainter.sh <магазин:товар> [<магазин:товар> …]` или `SKU="a:1 b:2"` (в коде и в этом файле товаров нет). Нет — отказ с кодом 2.
# Форма КАЖДОГО товара: `~/remlab-logs/mesh-models-1118/trellis/<магазин_товар>-1024-42-0.clean2.glb`, если есть, иначе `.clean.glb` (скрипт печатает, какой взял). Фото: `inputs30/<магазин_товар>.rgba.png` рядом.
#
#   probe_mvpainter.sh <SKU> [<SKU> …]  — «сухой» прогон: печатает тело группы без секретов, таблицу классов GPU от 40 ГБ с ценами, ничего не создаёт и ничего не стоит (денег 0)
#   APPLY=1 probe_mvpainter.sh <SKU> […] — настоящий запуск (платный, потолок CAP, по умолчанию $1,0) + бесплатная приёмка после него (кадры, лист «гибрид | MV-Adapter | MVPainter»)
#   ONLY_SCORE=<папка с .glb> probe_mvpainter.sh <SKU> […]   — только приёмка, без Salad
#
# Образ: `Dockerfile.mvpainter` (собирается на GitHub Actions пушем в ветку trial/trellis2*; адрес — IMAGE, лучше digest). Код воркера едет через command. Веса ≈ 28 ГиБ докачиваются на старте.
# Карта: по умолчанию RTX 5090 (32 ГБ, живая цена ≈ $0,60/ч; решение директора 19.11 — на 24 ГБ MVPainter может не поместиться); 4090 — только явно: GPU="RTX 4090 (24 GB)" (чекпойнт тогда грузится на процессор, issue #13).
# Другой класс — GPU="<полное имя>"; GPU=cheapest + GPU_MIN_GB=N — самый дешёвый от N ГБ (в организации классов от 40 ГБ нет: замер API 19.11, самый большой — 5090). Цена и потолок — по живому прайсу API.
# Параметры: MVP_YAW=auto|0|90|180|270, MVP_STEPS=75, MVP_REDUCE=1|0 (1 — штатное упрощение), MVP_PBR=1|0, READY_MIN=90, JOB_MIN=45, DEBUG_CUDA=1, WORKER_ENV="MVP_CKPT=ckpt MVP_LOAD_CPU=0" (проверка issue #13 «как у авторов»).
# Результат: OUT (по умолчанию ~/remlab-logs/t19-06-1119/mvp-<ЧЧММ по Лондону>/), НЕ папка `trellis/` и не `run-*` пробы MV-Adapter; задание — `<магазин_товар>-1024-42-0-mvp` (GLB лежат в OUT);
# кадры, лист «гибрид р.3 | MV-Adapter (если есть) | MVPainter» и метрика — по товару, в подпапке `OUT/<магазин_товар>/`.
set -u
. "$(cd "$(dirname "$0")" && pwd)/probe_lib.sh"
probe_init "$@"                                   # товары, формы, фото, эталоны — по каждому; нет формы или фото у одного — отказ здесь, до группы
IMAGE="${IMAGE:-ghcr.io/igortsk123/mesh-mvpainter-trial:mvpainter-trial}"       # лучше digest (ghcr.io/…@sha256:…), на котором прошёл прогрев
CAP="${CAP:-1.0}"
SUFFIX="${SUFFIX:-$(TZ=UTC date +%m%d%H%M)}"
STAMP="$(TZ=Europe/London date +%H%M)"
OUT="${OUT:-$HOME/remlab-logs/t19-06-1119/mvp-$STAMP}"
mkdir -p "$OUT"

if [ -z "${ONLY_SCORE:-}" ]; then
  cd "$TR" || exit 2
  FLAG=""
  [ "${APPLY:-0}" = "1" ] && FLAG="--apply"
  EXTRA=()
  [ "${DEBUG_CUDA:-0}" = "1" ] && EXTRA+=(--debug-cuda)
  EXTRA+=(--gpu "${GPU:-RTX 5090 (32 GB)}")       # по умолчанию 5090 (директор 19.11); 4090 — только GPU="RTX 4090 (24 GB)"
  [ -n "${GPU_MIN_GB:-}" ] && EXTRA+=(--gpu-min-gb "$GPU_MIN_GB")
  for kv in ${WORKER_ENV:-}; do EXTRA+=(--worker-env "$kv"); done
  "$PY" trellis_trial.py --model mvpainter --image "$IMAGE" --inputs "$BASE/inputs30" --skus "${SKUS[@]}" \
    --shape-dir "$BASE" --plan 1024:1 --seed 42 --tier high --cap "$CAP" --suffix "$SUFFIX" --out "$OUT" \
    --ready-min "${READY_MIN:-90}" --job-timeout "${JOB_MIN:-45}" \
    --mvp-yaw "${MVP_YAW:-auto}" --mvp-steps "${MVP_STEPS:-75}" --mvp-reduce "${MVP_REDUCE:-1}" --mvp-pbr "${MVP_PBR:-1}" \
    ${EXTRA[@]+"${EXTRA[@]}"} $FLAG || exit $?
  [ -z "$FLAG" ] && { echo "сухой прогон окончен: денег 0"; exit 0; }
  GLBS_DIR="$OUT"
else
  GLBS_DIR="$ONLY_SCORE"
fi

# ---- бесплатная приёмка по каждому товару (кадры, лист, метрика — в $OUT/<магазин_товар>/; общая функция probe_accept из probe_lib.sh) ----
probe_accept mvp "MVPainter" || exit 1
echo "метрики воркера по товарам: $OUT/summary-trial-mvpainter-$SUFFIX.json (в разделе by_sku — итог по товару; упрощение: simplify.faces_in/out, hausdorff_rel/mean_rel/p99_rel; кадр итога: frame.ok; стадии: upstream_stages, stage_s; пик памяти: peak_vram_gb; при падении — diag); шесть видов — $OUT/<магазин_товар>-1024-42-0-mvp.views.jpg"
