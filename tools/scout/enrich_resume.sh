#!/bin/bash
# Автовозобновление обогащения после пополнения биллинга (решение владельца 08.08).
# Цепочка по правилу «test before spend»: проба ключа → ПРОБНАЯ партия 40 (vision, батч) →
# успешный забор → полный хвост → забор. Каждый шаг громкий (лог + alert.sh при сбое).
#   nohup bash enrich_resume.sh >> enrich-resume.log 2>&1 &
set -u
cd "$(dirname "$0")"
PY="$HOME/venvs/scout/bin/python"

probe() {
  "$PY" - <<'EOF'
import json, sys, urllib.request
sys.path.insert(0, '.')
from enrich import _key, API
req = urllib.request.Request(f'{API}/chat/completions',
    data=json.dumps({'model': 'gpt-5.6-luna', 'messages': [{'role': 'user', 'content': 'ok'}],
                     'max_completion_tokens': 8}).encode(),
    headers={'Authorization': f'Bearer {_key()}', 'Content-Type': 'application/json'})
try:
    json.load(urllib.request.urlopen(req, timeout=60))
except Exception:
    sys.exit(1)
EOF
}

echo "[$(date '+%F %T')] жду оживления биллинга (проба раз в 10 мин, до 48 ч)"
for i in $(seq 1 288); do
  if probe; then break; fi
  [ "$i" = 288 ] && { bash alert.sh "remlab: биллинг не ожил за 48 ч — enrich_resume сдался"; exit 1; }
  sleep 600
done
echo "[$(date '+%F %T')] БИЛЛИНГ ЖИВ — пробная партия 40 (vision, батч)"
"$PY" enrich.py --pool --vision --batch --limit 40 || { bash alert.sh "remlab: пробный батч не отправился"; exit 1; }
bash enrich_wait.sh || { bash alert.sh "remlab: пробный батч не забрался — полный НЕ отправляю"; exit 1; }
echo "[$(date '+%F %T')] проба забрана — отправляю полный хвост"
"$PY" enrich.py --pool --vision --batch || { bash alert.sh "remlab: полный батч не отправился"; exit 1; }
bash enrich_wait.sh || exit 1
echo "[$(date '+%F %T')] обогащение хвоста завершено"
bash alert.sh "remlab: обогащение возобновлено и завершено (проба 40 + полный хвост)"
