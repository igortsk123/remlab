#!/bin/bash
# Пакет аппликаций: расстановка → сцена → вклейка → лист двух видов с полосой.
# Аппликация делается ДЛЯ ВЛАДЕЛЬЦА на проверку (в ИИ уходит схема с глубиной), поэтому здесь
# нет ни одного платного вызова генерации — только наши рендеры и уже кэшированные вырезки.
#   bash batch_collage.sh 2 5 8 11 14 17 20 23 26 29
set -u
cd "$(dirname "$0")"
PY="$HOME/venvs/scout/bin/python"
OUT="$HOME/scout-scenes"
for n in "$@"; do
  echo "=== сет $n ==="
  $PY solver_run.py "$n" --v3 >/dev/null 2>&1 || { echo "  расстановка не собралась"; continue; }
  $PY scene_build.py "$n" >/dev/null 2>&1 || { echo "  сцена не собралась"; continue; }
  $PY viz_build.py "$n" --cams C1,C2 2>&1 | tail -1
  $PY - "$n" <<'PYEOF'
import sys, os
sys.path.insert(0, '.')
from viz_final import stack_pair
n = sys.argv[1]
S = os.path.expanduser('~/scout-scenes')
try:
    stack_pair([f'{S}/scene{n}-C1-pasted.jpg', f'{S}/scene{n}-C2-pasted.jpg']).save(
        f'{S}/_collage{n}.jpg', quality=93)
    print(f'  аппликация: _collage{n}.jpg')
except Exception as e:
    print(f'  лист не собрался: {str(e)[:60]}')
PYEOF
done
