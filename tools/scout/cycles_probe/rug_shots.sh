#!/usr/bin/env bash
# Снимки ковра до/после правки (T-20261117-12/5): телефон 375×667 по обоим ракурсам витрины, 3 гостиные + 2 спальни.
#   rug_shots.sh <метка: before|after> <папка бандла> <папка-вывода>
# Бандл — `node build_entry.mjs <папка>` из дерева с нужной версией `kits/bedroom.ts`. Движок тот же, что у /demo, WebGL программный.
TAG="$1"; BUNDLE="$2"; O="$3"
cd "$(dirname "$0")" || exit 1
mkdir -p "$O"
for I in 0 1 2 6 11; do
  ../../ops/heavy-slot.sh "rug-$TAG-$I" --cores 2 -- node demo_scene_dump.mjs "$HOME/scout-scenes/flat215-demo/demo-data.json" "$I" "$BUNDLE" "$O/v$I-$TAG" shots=375x667 maxcams=2 2>&1 | grep -v "THREE\|Failed to load"
  for J in 0 1; do cp "$O/v$I-$TAG/shot-after-$J.jpg" "$O/rug-v$I-cam$J-$TAG.jpg" 2>/dev/null; done
done
echo DONE > "$O/done-$TAG.txt"
