#!/usr/bin/env bash
# Очередь рендеров T-20261117-06/1: ждёт конца кадров «было | стало» (done-living-scandi.txt), затем сетка настроек гостиной и спальни.
#   chain.sh <папка t66-1117>
B="$1"
cd "$(dirname "$0")/.." || exit 1
while [ ! -f "$B/ba/done-living-scandi.txt" ]; do sleep 20; done
cycles_probe/grid.sh living-scandi living "$B/dump/living" "$B/grid-living" > "$B/grid-living.log" 2>&1
while [ ! -f "$B/dump/bed2/scene-export.json" ]; do sleep 10; done
cycles_probe/before_after.sh bed2-japandi bed2 "$B/dump/bed2" "$B/ba" C1 C2 > "$B/ba-bed2.log" 2>&1
cycles_probe/grid.sh bed2-japandi bed2 "$B/dump/bed2" "$B/grid-bed2" > "$B/grid-bed2.log" 2>&1
echo ALLDONE > "$B/chain-done.txt"
