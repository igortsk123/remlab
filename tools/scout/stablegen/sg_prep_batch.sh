#!/bin/bash
# T-90/11: шаг конвейера «форма с Salad → форма для покраски»: упрощение ≤150 тыс. граней + развёртка (sg_prep_shape.py) для всех `*-n1024.glb` из <вход>, результат в <выход> (уже готовые пропускает), 3 параллельно под heavy-slot prio 2.
# Запуск: sg_prep_batch.sh <папка-вход> <папка-выход>. Вызывается в конце run_shapes.sh (Salad) — вручную перед покраской форму не готовят.
IN=$1; OUT=$2; mkdir -p "$OUT/logs"
HERE=$(cd "$(dirname "$0")" && pwd); ROOT=$(cd "$HERE/../../.." && pwd)
export OUT HERE ROOT SG_COLOR_FROM_DIR
one() {
  f=$1; b=$(basename "$f" -n1024.glb); o=$OUT/$b-n1024.glb
  [ -f "$o" ] && exit 0
  CF=""          # T-167: родной цвет TRELLIS.2 — только если задана папка (SG_COLOR_FROM_DIR) и в ней есть GLB с тем же именем; нет файла — строка «цвет не пришёл» в журнал
  if [ -n "${SG_COLOR_FROM_DIR:-}" ]; then
    if [ -f "$SG_COLOR_FROM_DIR/$(basename "$f")" ]; then CF="--color-from $SG_COLOR_FROM_DIR/$(basename "$f")"; else echo "ЦВЕТ не пришёл: нет $SG_COLOR_FROM_DIR/$(basename "$f")" >> "$OUT/logs/$b.log"; fi
  fi
  cd "$ROOT" && tools/ops/heavy-slot.sh t90-uv-$b --prio 2 --cores 1 --min-gb 2 --timeout 600 -- "${BLENDER:-$HOME/opt/blender-4.5.9/blender}" -b -P "$HERE/sg_prep_shape.py" -- --glb "$f" --out "$o" --faces 150000 $CF > "$OUT/logs/$b.log" 2>&1
}
export -f one
ls "$IN"/*-n1024.glb 2>/dev/null | grep -v '\.raw\.' | xargs -P 3 -I{} bash -c 'one {}'
