#!/bin/bash
# Пересадка очереди опытов на том же поде (T-90/6, решение директора 22:2x): ждёт, когда драйвер прошлого запуска закончит Б и возьмётся за В,
# убивает ТОЧНО его PID (под не трогает — SIGKILL, finally не выполняется), ретранслятор и новый заказ В, и запускает драйвер с новым списком на том же поде.
#   sg_swap.sh <лог старого драйвера> <маркер строки «прогон … →» первого лишнего опыта> <PID драйвера> <PID его ретранслятора> <id пода> <образ> <runs> [потолок $]
set -u
LOG=$1
MARK=$2
DRV=$3
REL=$4
POD=$5
IMG=$6
RUNS=$7
CAP=${8:-4.5}
HERE=$(cd "$(dirname "$0")" && pwd)
until grep -q -- "$MARK" "$LOG"; do sleep 3; done
echo "$(date -u +%T) метка «$MARK» есть: пересаживаю очередь"
kill -9 "$DRV" "$REL" 2>/dev/null
sleep 1
for p in $(ps -eo pid,cmd | grep -E "t90-sg-q2509mp|q2509mp-rp-" | grep -v grep | grep -v sg_swap | awk '{print $1}'); do kill "$p" 2>/dev/null; done
sleep 2
CREATED=$(date -d '2026-11-19 21:01:19 UTC' +%s)
AGE=$(( $(date +%s) - CREATED ))
SUF=$(date -u +%m%d%H%M)
NEW="$HOME/remlab-logs/t90-1119/sg/runpod/run-rp-$SUF.log"
echo "$(date -u +%T) новый драйвер: suffix=$SUF age=$AGE log=$NEW"
cd "$HERE" || exit 1
python3 -u sg_runpod.py --apply --suffix "$SUF" --reuse-pod "$POD" --reuse-age-s "$AGE" --cap "$CAP" --image "$IMG" --runs "$RUNS" > "$NEW" 2>&1
echo "$(date -u +%T) новый драйвер завершён rc=$?"
