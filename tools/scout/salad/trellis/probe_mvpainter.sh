#!/usr/bin/env bash
# T-20261119-06/4 — проба `mvpainter` на ОДНОМ товаре: готовая форма TRELLIS.2 (очищенный GLB) + одно фото → краска MVPainter КАК У АВТОРОВ (6 видов диффузией, PBR через IDArb,
# штатное упрощение формы до 30 тыс. вершин, развёртка xatlas, запекание). Сравнивается с лучшим гибридом (форма TRELLIS.2 + краска Hunyuan) и с MV-Adapter (если его проба уже была).
# Критерий пробы — только ВИД: кадры 0°/45° против гибрида (форма здесь меняется законно — владелец 19.11, TG 2149/2150; сколько сжали — в метриках `simplify`).
# НЕ запускалась: настоящий запуск платный — только после слова менеджера. Потолок денег по умолчанию $1,0 (владелец TG 2147).
# Товар — обязательный вход: `SKU=<магазин:товар> probe_mvpainter.sh` или первым аргументом (в коде и в этом файле товаров нет). Нет — отказ с кодом 2.
# Форма: `~/remlab-logs/mesh-models-1118/trellis/<магазин_товар>-1024-42-0.clean2.glb`, если есть, иначе `.clean.glb` (скрипт печатает, какой взял). Фото: `inputs30/<магазин_товар>.rgba.png` рядом.
#
#   probe_mvpainter.sh <SKU>              — «сухой» прогон: печатает тело группы без секретов, таблицу классов GPU от 40 ГБ с ценами, ничего не создаёт и ничего не стоит (денег 0)
#   APPLY=1 probe_mvpainter.sh <SKU>      — настоящий запуск (платный, потолок CAP, по умолчанию $1,0) + бесплатная приёмка после него (кадры, лист «гибрид | MV-Adapter | MVPainter»)
#   ONLY_SCORE=<папка с .glb> probe_mvpainter.sh <SKU>   — только приёмка, без Salad
#
# Образ: `Dockerfile.mvpainter` (собирается на GitHub Actions пушем в ветку trial/trellis2*; адрес — IMAGE, лучше digest). Код воркера едет через command. Веса ≈ 28 ГиБ докачиваются на старте.
# Карта: по умолчанию RTX 5090 (32 ГБ, живая цена ≈ $0,60/ч; решение директора 19.11 — на 24 ГБ MVPainter может не поместиться); 4090 — только явно: GPU="RTX 4090 (24 GB)" (чекпойнт тогда грузится на процессор, issue #13).
# Другой класс — GPU="<полное имя>"; GPU=cheapest + GPU_MIN_GB=N — самый дешёвый от N ГБ (в организации классов от 40 ГБ нет: замер API 19.11, самый большой — 5090). Цена и потолок — по живому прайсу API.
# Параметры: MVP_YAW=auto|0|90|180|270, MVP_STEPS=75, MVP_REDUCE=1|0 (1 — штатное упрощение), MVP_PBR=1|0, READY_MIN=90, JOB_MIN=45, DEBUG_CUDA=1, WORKER_ENV="MVP_CKPT=ckpt MVP_LOAD_CPU=0" (проверка issue #13 «как у авторов»).
# Результат: OUT (по умолчанию ~/remlab-logs/t19-06-1119/mvp-<ЧЧММ по Лондону>/), НЕ папка `trellis/` и не `run-*` пробы MV-Adapter; задание называется `<магазин_товар>-1024-42-0-mvp`.
set -u
REPO="${REPO:-/home/pakar/igor/remlab/.claude/worktrees/mvpainter-1119}"
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
if [ -n "$REF" ]; then echo "эталон (гибрид, кадры 0°/45°): $REF"; else echo "эталона-гибрида для этого товара нет в frames-clean2/hybrid и frames-clean/hybrid/noremesh — лист не соберётся" >&2; fi
# MV-Adapter: самый свежий прогон пробы 06/2 по этому товару (кадры render_stand) — средний столбец листа; нет — лист из двух столбцов
MVA=""
for c in $(ls -d "$HOME"/remlab-logs/t19-06-1119/run-*/frames/"${SKUF}-1024-42-0-mvtex" 2>/dev/null | sort | tail -1); do MVA="$c"; done
if [ -n "$MVA" ]; then echo "MV-Adapter (кадры пробы 06/2): $MVA"; else echo "прогона MV-Adapter по этому товару в t19-06-1119/run-* нет — лист будет «гибрид | MVPainter»"; fi
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
  "$PY" trellis_trial.py --model mvpainter --image "$IMAGE" --inputs "$BASE/inputs30" --skus "$SKU" \
    --texture-mesh "$SHAPE" --plan 1024:1 --seed 42 --tier high --cap "$CAP" --suffix "$SUFFIX" --out "$OUT" \
    --ready-min "${READY_MIN:-90}" --job-timeout "${JOB_MIN:-45}" \
    --mvp-yaw "${MVP_YAW:-auto}" --mvp-steps "${MVP_STEPS:-75}" --mvp-reduce "${MVP_REDUCE:-1}" --mvp-pbr "${MVP_PBR:-1}" \
    ${EXTRA[@]+"${EXTRA[@]}"} $FLAG || exit $?
  [ -z "$FLAG" ] && { echo "сухой прогон окончен: денег 0"; exit 0; }
  GLBS_DIR="$OUT"
else
  GLBS_DIR="$ONLY_SCORE"
fi

# ---- бесплатная приёмка: кадры 0°/45° (Blender под heavy-slot; имена 01_az000_tex, 02_az000_clay, 03_az045_tex, 04_az045_clay), лист «гибрид | MV-Adapter | MVPainter», метрика рисунка ----
BLENDER="$HOME/opt/blender-4.5.9/blender"
cd "$REPO" || exit 2
OURS="$GLBS_DIR/${SKUF}-1024-42-0-mvp.glb"
[ -f "$OURS" ] || { echo "результата нет: $OURS (задание упало? смотри summary-*.json в $OUT)" >&2; exit 1; }
n="$(basename "$OURS" .glb)"
tools/ops/heavy-slot.sh "p06-$n" --cores 4 --min-gb 3 --timeout 3000 -- "$BLENDER" -b -P "$TR/render_stand.py" -- \
  --glb "$OURS" --out "$OUT/frames/$n" --samples 32 --modes tex,clay --only az000,az045 >> "$OUT/render.log" 2>&1
if [ -n "$REF" ]; then
  COLS=("гибрид=$REF")
  [ -n "$MVA" ] && COLS+=("MV-Adapter=$MVA")
  COLS+=("MVPainter=$OUT/frames/$n")
  "$PY" "$TR/mv_sheet.py" --cols "${COLS[@]}" --out "$OUT/side-by-side.png" 2>&1 | tee -a "$OUT/render.log"
fi
"$PY" "$TR/score_pixal_tex.py" "$PHOTO" "$OUT/score" "$SHAPE" "$OURS" 2>&1 | tee "$OUT/score.log" || echo "метрика рисунка не посчиталась (кадры и лист — выше)"
echo "готово: кадры $OUT/frames/$n/ (отдельные файлы полного размера), лист $OUT/side-by-side.png, метрика $OUT/score/score.json"
echo "метрики воркера (упрощение: simplify.faces_in/out, hausdorff_rel/mean_rel/p99_rel; кадр итога: frame.ok; стадии: upstream_stages, stage_s; пик памяти: peak_vram_gb; при падении — diag): $OUT/summary-trial-mvpainter-$SUFFIX.json; шесть видов — $OUT/$n.views.jpg"
