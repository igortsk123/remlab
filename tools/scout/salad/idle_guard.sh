#!/usr/bin/env bash
# СТОРОЖ ПРОСТОЯ: гасит группы Salad, если конвейера нет, а машины крутятся.
#
# Зачем. Тарифицируется состояние `running`, а не работа (ADR-0135/0142). Штатный финал
# (`finale()`) гасит группы сам, но он не отрабатывает, если процесс убит сигналом или
# машина ушла в перезагрузку — тогда прогретые ноды будут капать в счёт всю ночь.
#
# Ложных срабатываний избегаем двумя проверками подряд: одиночный перезапуск конвейера
# (10–15 секунд между kill и стартом) сторож не заметит, а настоящую пропажу — да.
#
# Ставится в cron: */10 * * * * /home/pakar/igor/remlab/tools/scout/salad/idle_guard.sh
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE="${MESH_GUARD_STATE:-$HOME/scout-scenes/.mesh-idle-guard}"
LOG="${MESH_GUARD_LOG:-$HOME/scout-scenes/idle-guard.log}"
PY="${MESH_PY:-$HOME/venvs/scout/bin/python}"
ENVFILE="${MESH_ENV:-$HOME/scout-scenes/salad.env}"

[ -f "$ENVFILE" ] && { set -a; . "$ENVFILE"; set +a; }
: "${SALAD_GROUP:=mesh-run10}"
: "${SALAD_API_KEY:?нет SALAD_API_KEY (положи в $ENVFILE)}"

log() { echo "$(date '+%F %H:%M') $*" >> "$LOG"; }

if pgrep -f "[b]atch_show.py" > /dev/null; then
  rm -f "$STATE"          # конвейер жив — счётчик подозрений сбрасываем
  exit 0
fi

RUNNING=$("$PY" - <<'EOF'
import json, os, urllib.request
K = os.environ['SALAD_API_KEY']
n = 0
for g in [x.strip() for x in os.environ['SALAD_GROUP'].split(',') if x.strip()]:
    try:
        req = urllib.request.Request(
            f'https://api.salad.com/api/public/organizations/prodstore/projects/dmodel/containers/{g}/instances',
            headers={'Salad-Api-Key': K, 'User-Agent': 'remlab-mesh/1.0'})
        ins = json.loads(urllib.request.urlopen(req, timeout=30).read()).get('instances') or []
        n += sum(1 for i in ins if i.get('state') == 'running')
    except Exception:
        pass                      # сеть недоступна — молчим, решение примет следующий заход
print(n)
EOF
)

[ "${RUNNING:-0}" -eq 0 ] && { rm -f "$STATE"; exit 0; }

if [ ! -f "$STATE" ]; then       # первое подозрение — ждём подтверждения следующим заходом
  date +%s > "$STATE"
  log "конвейера нет, машин в работе: $RUNNING — проверю ещё раз"
  exit 0
fi

log "конвейера нет два захода подряд, машин в работе: $RUNNING — ГАШУ ГРУППЫ"
"$PY" - <<EOF >> "$LOG" 2>&1
import sys
sys.path.insert(0, "$HERE")
import ssh_run
ssh_run.stop_group()
EOF
rm -f "$STATE"
