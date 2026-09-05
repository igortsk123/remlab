#!/usr/bin/env bash
# СТАРТ ВОЛНЫ МЕШЕЙ — единственная законная процедура пересборки снимка очереди
# (план mesh-owner-audit, 05.09; регламент rules/mesh-priority.json §identity).
#
# ЗАЧЕМ ПРОЦЕДУРА, А НЕ «перезаписать файл и обнулить курсор». Курсор конвейера позиционный:
# он верен только для того снимка, по которому шёл. Снимок, собранный поверх НЕразобранных
# результатов, снова поставит уже сделанные меши (кэш приёмника к тому моменту вычищен) — деньги
# на ветер. Поэтому порядок жёсткий: конвейер остановлен на границе пачки → сироты доработали →
# сделанное стащено, учтено и привязано → решения владельца забраны → новый снимок собран
# АТОМАРНО (tmp → fsync → rename), переделки получили свободный seed → курсор нового снимка
# начинается с нуля в СВОЁМ файле (`<снимок>.progress.json`) → запуск с явным MESH_SAMPLE.
#
#   tools/scout/mesh_wave_start.sh            # собрать снимок и напечатать команду запуска
#   tools/scout/mesh_wave_start.sh --launch   # …и запустить конвейер (nohup, один уровень фона)
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${MESH_PY:-$HOME/venvs/scout/bin/python}"
LOCK="$HOME/scout-scenes/.batch_show.lock"
DRAINING="$HOME/scout-scenes/mesh-draining"
LOG="${MESH_BATCH_LOG:-$HOME/igor/remlab/.memory_bank/_intake/batch-hardened.log}"
SNAP="$HERE/mesh-queue-$(date -u +%Y%m%dT%H%M%S).json"
BATCH="${MESH_BATCH:-200}"

say() { echo "$(date '+%d.%m %H:%M') $*"; }

# 1. Конвейер не должен бежать: замок держит живой процесс.
if ! flock -n "$LOCK" true 2>/dev/null; then
  say "конвейер работает (замок $LOCK). Останови на границе пачки: touch $DRAINING — и запусти меня снова"
  exit 75
fi

# 2. Сироты прошлого прогона обязаны доработать — их результаты ещё не учтены.
pat='[s]sh_run\.py|[d]rain\.sh|[t]opview_render|[a]pply_repairs|[o]rient_worker|[r]eceiver_purge|[i]ngest_registry|[m]esh_bind'
for _ in $(seq 1 60); do
  if pgrep -f "$pat" >/dev/null; then say "жду сирот прошлого прогона…"; sleep 30; else break; fi
done
if pgrep -f "$pat" >/dev/null; then say "сироты не завершились за 30 мин — разбери руками"; exit 1; fi

# 3. Сделанное — стащить, учесть, привязать: снимок собирается по ПРИВЯЗАННОМУ состоянию.
say "стаскиваю с приёмника"; bash "$HERE/salad/drain.sh" --keep || say "drain: код $? (нет новых — нормально)"
say "реестр поколений";      "$PY" "$HERE/salad/ingest_registry.py"
say "привязка к товарам";    "$PY" "$HERE/mesh_bind.py" | head -3

# 4. Решения владельца — забрать до сборки (тик моста; если модуля ещё нет — пропуск).
if [ -f "$HERE/mesh_audit_sync.py" ]; then
  say "решения владельца"; "$PY" "$HERE/mesh_audit_sync.py" --tick || say "sync: код $? — продолжаю, решения подберёт следующий тик"
fi

# 5. Снимок — атомарно; переделки получают seed и статус queued только после записи.
say "собираю снимок $SNAP"
MESH_MAX_JOBS="${MESH_MAX_JOBS:-14000}" "$PY" "$HERE/mesh_priority.py" --build-queue "$SNAP"
N=$("$PY" -c "import json,sys; print(len(json.load(open(sys.argv[1]))['jobs']))" "$SNAP")

# 6. Запуск — с ЯВНЫМ снимком; курсор нового снимка начинается с нуля в своём файле.
CMD="set -a; . $HOME/scout-scenes/salad.env; set +a; MESH_SAMPLE=$SNAP MESH_MAX_JOBS=${MESH_MAX_JOBS:-14000} MESH_POST_EVERY_S=900 nohup $PY -u $HERE/salad/batch_show.py --batch $BATCH >> $LOG 2>&1 &"
say "снимок готов: $N заданий. Команда запуска:"
echo "  $CMD"
if [ "${1:-}" = "--launch" ]; then
  say "запускаю конвейер"
  bash -c "$CMD"
  sleep 3
  pgrep -f "[b]atch_show.py --batch" >/dev/null && say "конвейер запущен, лог: $LOG" || { say "конвейер НЕ поднялся — смотри $LOG"; exit 1; }
fi
