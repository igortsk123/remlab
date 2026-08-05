#!/bin/bash
# Ждём, пока пакетные задания обогащения досчитаются, и сразу забираем результат в БД.
# Пакет OpenAI выполняется до 24 часов, поэтому ожидание фоновое: опрос раз в 5 минут.
#   bash enrich_wait.sh
set -u
cd "$(dirname "$0")"
PY="$HOME/venvs/scout/bin/python"
for i in $(seq 1 288); do            # 288 × 5 мин = 24 часа, дальше пакет всё равно истекает
  out=$($PY enrich.py --fetch 2>&1)
  echo "[$(date +%H:%M)] $out"
  if ! grep -qE 'validating|in_progress|finalizing' <<<"$out"; then
    echo "все части готовы"
    $PY enrich.py --stats
    exit 0
  fi
  sleep 300
done
echo "истекли сутки ожидания — проверь пакеты вручную"
