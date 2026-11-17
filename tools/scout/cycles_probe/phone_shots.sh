#!/usr/bin/env bash
# Снимки /demo (телефон 375×667, лёгкий режим) «до» (?finish=0) и «после» по вариантам витрины + байты карт оболочки в лёгком и полном режиме:
#   phone_shots.sh <папка-вывода> <индекс варианта>:<имя> ...      (индексы — `demo-data.json` → variants)
# Пример: phone_shots.sh ~/remlab-logs/t66-1117/phone 0:living-set1 5:living-set16 6:bed1-scandi 15:bed2-japandi
O="$1"; shift
HERE="$(cd "$(dirname "$0")/../.." && pwd)"   # папка tools
DD="$HOME/scout-scenes/flat215-demo/demo-data.json"
BUNDLE="$HOME/remlab-logs/t66-1117/bundle"
mkdir -p "$O"
for p in "$@"; do
  i="${p%%:*}"; n="${p##*:}"
  for f in 0 1; do
    "$HERE/ops/heavy-slot.sh" "t66-phone-$n-$f" --cores 2 -- node "$HERE/scout/cycles_probe/demo_scene_dump.mjs" "$DD" "$i" "$BUNDLE" "$O/$n" lite=1 shots=375x667 assets=1 finish=$f maxcams=2 > "$O/$n-$f.log" 2>&1
  done
  # полный режим (десктоп): только байты карт
  "$HERE/ops/heavy-slot.sh" "t66-full-$n" --cores 2 -- node "$HERE/scout/cycles_probe/demo_scene_dump.mjs" "$DD" "$i" "$BUNDLE" "$O/$n-full" assets=1 > "$O/$n-full.log" 2>&1
  echo "$n: $(grep -h 'карты оболочки' "$O/$n-1.log" | tail -1) | полный: $(grep -h 'карты оболочки' "$O/$n-full.log" | tail -1)"
done
echo ALLDONE > "$O/phone-done.txt"
