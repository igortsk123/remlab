#!/usr/bin/env bash
# Тройное сравнение зада «stat | trellis | trellis_relief» этапа 7 на ОДНОМ входе — выходе этапа 6 (<корень>/<sku>/06-visible). Бесплатно (процессор), только под heavy-slot (P-038):
#   tools/ops/heavy-slot.sh t164-cmp --prio 1 --short --cores 2 --timeout 21600 -- nice -n 19 timeout -k 20 7200 bash tools/scout/salad/trellis/tex_fill_compare_visible.sh <выход> <корень этапа 6> <папка черновиков TRELLIS> <sku> [<sku> …]
# Черновики — родные TRELLIS.2: <папка>/<sku>-1024-42-0.glb (например ~/remlab-logs/mesh-models-1118/trellis2). Нет файла — товар для trellis/trellis_relief пропущен (в <выход>/<источник>/skipped.txt), в кадрах — только stat.
# Источники: stat = вариант А (по умолчанию этапа 7); trellis = вариант Б «как есть» (--draft-fallback off: без отката на А; --draft-texture off: БЕЗ фото-квилта — иначе это «Б+квилт», Codex 21.11), цвет черновика сдвигается к тону фото;
#           trellis_relief = вариант C: цвет как stat, фактура — рельеф яркости черновика с ограничением силы, выбросы → лоскут stat (пороги — rules/paint-fill.json: trellis_relief).
# Кадры: <выход>/frames/<метка>-zad-stat_trellis_relief.png — зад az180, слева направо stat | trellis | trellis_relief (подписи в углу), плюс <метка>-zad-stat_trellis_relief-mery.txt — мерки трёх.
set -u
OUT="$1"; ROOT="$2"; DRAFTS="$3"; shift 3
HERE="$(cd "$(dirname "$0")" && pwd)"
THR="${STAGE_THREADS:-1}"                                   # как в проде (worker_stage.py: STAGE_THREADS=1); cpu_s при других потоках завышен и с боевым не сравнивается (T-157)
export OMP_NUM_THREADS="$THR" OPENBLAS_NUM_THREADS="$THR" MKL_NUM_THREADS="$THR"
PY="$HOME/venvs/scout/bin/python"
CFG_C="${CFG_C:-}"; [ -n "$CFG_C" ] || CFG_C='{}'        # JSON-добавка к настройкам C, например роли частей этапа 3: CFG_C='{"part_class": {"0": "body", "1": "legs"}}' (нет — ворота C только по однородности известного)
mkdir -p "$OUT/stat" "$OUT/trellis" "$OUT/trellis_relief" "$OUT/frames"
"$PY" "$HERE/tex_fill_probe.py" --visible-root "$ROOT" --source stat "$OUT/stat" "$@" > "$OUT/stat/probe.log" 2>&1
SKUB=""
for s in "$@"; do
  if [ -f "$DRAFTS/$s-1024-42-0.glb" ]; then SKUB="$SKUB $s"; else echo "нет черновика: $s" >> "$OUT/trellis/skipped.txt"; echo "нет черновика: $s" >> "$OUT/trellis_relief/skipped.txt"; fi
done
if [ -n "$SKUB" ]; then
  # shellcheck disable=SC2086
  "$PY" "$HERE/tex_fill_probe.py" --visible-root "$ROOT" --source trellis --draft-dir "$DRAFTS" --draft-fallback off --draft-texture off "$OUT/trellis" $SKUB > "$OUT/trellis/probe.log" 2>&1
  # shellcheck disable=SC2086
  "$PY" "$HERE/tex_fill_probe.py" --visible-root "$ROOT" --source trellis_relief --draft-dir "$DRAFTS" --cfg "$CFG_C" "$OUT/trellis_relief" $SKUB > "$OUT/trellis_relief/probe.log" 2>&1
fi
"$PY" -I "$HERE/tex_fill_compare_frames.py" "$OUT"
echo "готово: $OUT"
