#!/bin/bash
# Пересадка очереди опытов на том же поде (T-90/6): ждёт в логе драйвера строку-метку «прогон … <вариант> →» первого ЛИШНЕГО опыта, убивает ТОЧНО PID драйвера и его ретранслятора
# (kill -9: finally не срабатывает, под жив), снимает заказ лишнего опыта в слоте и запускает новый драйвер на том же поде с новым списком (он перечитывает код вариантов).
#   sg_requeue.sh <лог драйвера> <метка в логе> <шаблон процессов лишнего опыта для kill> <PID драйвера> <PID ретранслятора> <id пода> <образ> <runs> [потолок $]
set -u
LOG=$1
MARK=$2
KILLPAT=$3
DRV=$4
REL=$5
POD=$6
IMG=$7
RUNS=$8
CAP=${9:-4.5}
HERE=$(cd "$(dirname "$0")" && pwd)
until grep -q -- "$MARK" "$LOG"; do sleep 3; done
echo "$(date -u +%T) метка «$MARK» есть: пересаживаю очередь"
kill -9 "$DRV" "$REL" 2>/dev/null
sleep 1
for p in $(ps -eo pid,cmd | grep -E "$KILLPAT" | grep -v grep | grep -v sg_requeue | grep -v sg_swap | awk '{print $1}'); do kill "$p" 2>/dev/null; done
sleep 2
CREATED=$(date -d '2026-11-19 21:01:19 UTC' +%s)
AGE=$(( $(date +%s) - CREATED ))
SUF=$(date -u +%m%d%H%M)
NEW="$HOME/remlab-logs/t90-1119/sg/runpod/run-rp-$SUF.log"
echo "$(date -u +%T) новый драйвер: suffix=$SUF age=$AGE log=$NEW"
cd "$HERE" || exit 1
python3 -u sg_runpod.py --apply --suffix "$SUF" --reuse-pod "$POD" --reuse-age-s "$AGE" --cap "$CAP" --image "$IMG" --runs "$RUNS" > "$NEW" 2>&1
echo "$(date -u +%T) новый драйвер завершён rc=$?"
