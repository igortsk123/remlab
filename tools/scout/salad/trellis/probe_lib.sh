# T-20261119-06/5/2 — общее для probe_mvadapter.sh / probe_supratex.sh / probe_mvpainter.sh (подключается `. probe_lib.sh`; сам не запускается).
# Несколько товаров в одной группе: на каждый товар СВОЯ форма (каталог форм: clean2, иначе clean), СВОЁ фото, СВОИ кадры и лист — в подпапке `$OUT/<магазин_товар>/`.
# Всё проверяется ДО группы: нет формы или фото хотя бы у одного товара — отказ с кодом 2, группа не создаётся и ничего не стоит.

# probe_init <товар>…  — товары аргументами (или SKU="a:1 b:2" в окружении). Готовит REPO TR PY LOGS BASE SKUS и по товару: SHAPE[<товар>] PHOTO[<товар>] REF[<товар>] MVA[<товар>].
probe_init() {
  REPO="${REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)}"     # копия репозитория, в которой лежит сам скрипт (не жёсткий путь к чужому worktree)
  TR="$REPO/tools/scout/salad/trellis"
  PY="${PY:-$HOME/venvs/scout/bin/python}"
  LOGS="$HOME/remlab-logs/mesh-models-1118"
  BASE="$LOGS/trellis"
  SHAPE_DIR="${SHAPE_DIR:-$BASE}"                  # каталог форм (по умолчанию тот же, что фото: $BASE); можно задать другой, например $LOGS/trellis2 (формы clean2), фото остаются в $BASE/inputs30
  local list=() s seen=" " bad=0
  if [ "$#" -gt 0 ]; then list=("$@"); else list=(${SKU:-}); fi
  SKUS=()
  for s in ${list[@]+"${list[@]}"}; do
    case "$s" in
      *:*) ;;
      *) echo "товар «$s» не похож на <магазин:товар>" >&2; exit 2;;
    esac
    case "$seen" in *" $s "*) continue;; esac
    seen="$seen$s "
    SKUS+=("$s")
  done
  if [ "${#SKUS[@]}" -eq 0 ]; then
    echo "нужен хотя бы один товар: $0 <магазин:товар> [<магазин:товар> …] (или SKU=\"a:1 b:2\")" >&2
    exit 2
  fi
  declare -gA SHAPE=() PHOTO=() REF=() MVA=()
  local skuf c
  for s in "${SKUS[@]}"; do
    skuf="${s//:/_}"
    if [ -n "${SHAPE_TAG:-}" ]; then                 # SHAPE_TAG=clean3 — форма ТОЛЬКО этого вида (без запасных: подмена формы незаметно портит сравнение); по умолчанию прежний порядок clean2 → clean
      case "$SHAPE_TAG" in *[!a-z0-9]*) echo "SHAPE_TAG: латиница/цифры (например clean3), получено «$SHAPE_TAG»" >&2; exit 2;; esac
      if [ -f "$SHAPE_DIR/${skuf}-1024-42-0.${SHAPE_TAG}.glb" ]; then
        SHAPE[$s]="$SHAPE_DIR/${skuf}-1024-42-0.${SHAPE_TAG}.glb"; echo "[$s] форма: ${SHAPE[$s]} — ${SHAPE_TAG} (задана SHAPE_TAG)"
      else
        echo "[$s] нет формы: $SHAPE_DIR/${skuf}-1024-42-0.${SHAPE_TAG}.glb (задана SHAPE_TAG=$SHAPE_TAG; запасных форм нет)" >&2; bad=1
      fi
    elif [ -f "$SHAPE_DIR/${skuf}-1024-42-0.clean2.glb" ]; then
      SHAPE[$s]="$SHAPE_DIR/${skuf}-1024-42-0.clean2.glb"; echo "[$s] форма: ${SHAPE[$s]} — clean2 (правило очистки E)"
    elif [ -f "$SHAPE_DIR/${skuf}-1024-42-0.clean.glb" ]; then
      SHAPE[$s]="$SHAPE_DIR/${skuf}-1024-42-0.clean.glb"; echo "[$s] форма: ${SHAPE[$s]} — clean (прежнее правило очистки; clean2 нет)"
    else
      echo "[$s] нет формы: ни $SHAPE_DIR/${skuf}-1024-42-0.clean2.glb, ни .clean.glb" >&2; bad=1
    fi
    PHOTO[$s]="$BASE/inputs30/${skuf}.rgba.png"
    [ -f "${PHOTO[$s]}" ] || { echo "[$s] нет фото: ${PHOTO[$s]}" >&2; bad=1; }
    REF[$s]=""
    for c in "$LOGS/frames-clean2/hybrid/noremesh/$skuf" "$LOGS/frames-clean2/hybrid/$skuf" "$LOGS/frames-clean/hybrid/noremesh/$skuf"; do
      [ -d "$c" ] && { REF[$s]="$c"; break; }
    done
    if [ -n "${REF[$s]}" ]; then echo "[$s] эталон (гибрид р.3, кадры 0°/45°): ${REF[$s]}"; else echo "[$s] эталона-гибрида нет в frames-clean2/hybrid и frames-clean/hybrid/noremesh — его столбца в листе не будет" >&2; fi
    MVA[$s]=""      # MV-Adapter: самый свежий прогон пробы 06/2 по этому товару (кадры render_stand); нет — столбца нет
    for c in $(ls -d "$HOME"/remlab-logs/t19-06-1119/run-*/frames/"${skuf}-1024-42-0-mvtex" 2>/dev/null | sort -r); do
      [ -d "$c" ] && { MVA[$s]="$c"; break; }
    done
    if [ -n "${MVA[$s]}" ]; then echo "[$s] MV-Adapter (кадры последнего прогона): ${MVA[$s]}"; else echo "[$s] кадров MV-Adapter нет (t19-06-1119/run-*/frames/${skuf}-1024-42-0-mvtex) — его столбца в листе не будет" >&2; fi
  done
  [ "$bad" = 0 ] || { echo "отказ: у части товаров нет формы или фото — группа не создаётся, денег 0" >&2; exit 2; }
}

# probe_accept <суффикс задания: supra|mvp|mvtex> <подпись столбца> [mva-нет] — бесплатная приёмка по КАЖДОМУ товару: кадры 0°/45° (Blender под heavy-slot; имена 01_az000_tex, 02_az000_clay,
# 03_az045_tex, 04_az045_clay), лист «гибрид р.3 | MV-Adapter (если есть) | <модель>», метрика рисунка. Всё — в `$OUT/<магазин_товар>/`. Нужны GLBS_DIR и OUT. Код 1 — у кого-то нет результата.
probe_accept() {
  local suf="$1" lab="$2" nomva="${3:-}" s skuf ours n d fails=0 cols
  local blender="$HOME/opt/blender-4.5.9/blender"
  cd "$REPO" || exit 2
  for s in "${SKUS[@]}"; do
    skuf="${s//:/_}"
    ours="$GLBS_DIR/${skuf}-1024-42-0-${suf}.glb"
    d="$OUT/$skuf"
    mkdir -p "$d"
    if [ ! -f "$ours" ]; then echo "[$s] результата нет: $ours (задание упало? смотри summary-*.json в $OUT)" >&2; fails=$((fails + 1)); continue; fi
    n="$(basename "$ours" .glb)"
    tools/ops/heavy-slot.sh "p06-$n" --cores 4 --min-gb 3 --timeout 3000 -- "$blender" -b -P "$TR/render_stand.py" -- \
      --glb "$ours" --out "$d/frames/$n" --samples 32 --modes tex,clay --only az000,az045 >> "$d/render.log" 2>&1
    cols=()
    [ -n "${REF[$s]}" ] && cols+=("гибрид р.3=${REF[$s]}")
    [ -z "$nomva" ] && [ -n "${MVA[$s]}" ] && cols+=("MV-Adapter=${MVA[$s]}")
    cols+=("$lab=$d/frames/$n")
    "$PY" "$TR/mv_sheet.py" --cols "${cols[@]}" --out "$d/side-by-side.png" 2>&1 | tee -a "$d/render.log"
    "$PY" "$TR/score_pixal_tex.py" "${PHOTO[$s]}" "$d/score" "${SHAPE[$s]}" "$ours" 2>&1 | tee "$d/score.log" || echo "[$s] метрика рисунка не посчиталась (кадры и лист — выше)"
    echo "[$s] готово: кадры $d/frames/$n/ (отдельные файлы полного размера), лист $d/side-by-side.png, метрика $d/score/score.json"
  done
  [ "$fails" = 0 ]
}
