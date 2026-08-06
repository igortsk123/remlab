#!/bin/bash
# Пакет аппликаций: расстановка → сцена → вклейка → лист двух видов с полосой.
# Аппликация делается ДЛЯ ВЛАДЕЛЬЦА на проверку (в ИИ уходит схема с глубиной), поэтому здесь
# нет ни одного платного вызова генерации — только наши рендеры и уже кэшированные вырезки.
#   bash batch_collage.sh 2 5 8 11 14 17 20 23 26 29
set -u -o pipefail   # без pipefail exit-код viz_build глотался бы tail'ом
cd "$(dirname "$0")"
PY="$HOME/venvs/scout/bin/python"
OUT="$HOME/scout-scenes"
FAILED=""
for n in "$@"; do
  echo "=== сет $n ==="
  $PY solver_run.py "$n" --v3 >/dev/null 2>&1 || { echo "  расстановка не собралась"; FAILED="$FAILED $n"; continue; }
  $PY scene_build.py "$n" >/dev/null 2>&1 || { echo "  сцена не собралась"; FAILED="$FAILED $n"; continue; }
  # приёмка блокирующая (А4): раньше exit-код глотался, и сцены с браком шли как чистые
  if ! $PY viz_build.py "$n" --cams C1,C2 2>&1 | tail -2; then
    echo "  ПРИЁМКА НЕ ПРОШЛА — сет $n в список брака"
    FAILED="$FAILED $n"
  fi
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
if [ -n "$FAILED" ]; then
  echo "ИТОГ: приёмку не прошли сеты:$FAILED"
  exit 1
fi
