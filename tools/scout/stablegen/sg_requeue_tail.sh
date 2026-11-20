#!/bin/bash
# Дозаказ опыта В КОНЕЦ очереди (T-90/6): последний опыт идёт, драйвер по его концу удалит под. Ждём «ГОТОВО» в drive.log САМОГО Blender-а опыта (пишется до выхода Blender),
# сразу kill -9 драйвера и ретранслятора (finally не срабатывает → под жив), запускаем новый драйвер на том же поде с одним новым опытом.
#   sg_requeue_tail.sh <drive.log Blender-а последнего опыта> <PID драйвера> <PID ретранслятора> <id пода> <образ> <runs> [потолок $]
set -u
BLOG=$1
DRV=$2
REL=$3
POD=$4
IMG=$5
RUNS=$6
CAP=${7:-4.5}
HERE=$(cd "$(dirname "$0")" && pwd)
until grep -q "ГОТОВО" "$BLOG" 2>/dev/null; do sleep 0.3; done
kill -9 "$DRV" "$REL" 2>/dev/null
echo "$(date -u +%T) Blender опыта дописал: драйвер $DRV и ретранслятор $REL убиты, под должен быть жив"
CREATED=$(date -d '2026-11-19 21:01:19 UTC' +%s)
AGE=$(( $(date +%s) - CREATED ))
SUF=$(date -u +%m%d%H%M)
NEW="$HOME/remlab-logs/t90-1119/sg/runpod/run-rp-$SUF.log"
echo "$(date -u +%T) новый драйвер: suffix=$SUF age=$AGE log=$NEW"
cd "$HERE" || exit 1
python3 -u sg_runpod.py --apply --suffix "$SUF" --reuse-pod "$POD" --reuse-age-s "$AGE" --cap "$CAP" --image "$IMG" --runs "$RUNS" > "$NEW" 2>&1
echo "$(date -u +%T) новый драйвер завершён rc=$?"
