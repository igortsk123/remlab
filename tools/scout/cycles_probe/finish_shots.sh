#!/usr/bin/env bash
# Снимки /demo с отделкой CC0 и без неё (`?finish=0`): set1 (гостиная) и bedroom-1-scandi, телефон 375×667 и компьютер 1440×900, оба ракурса витрины.
#   finish_shots.sh <папка бандла> <папка-вывода>
# Движок тот же, что у /demo (`FlatViewer.capturePhoto`), WebGL программный; отделка вкл — по умолчанию, выкл — finish=0.
BUNDLE="$1"; O="$2"
cd "$(dirname "$0")" || exit 1
mkdir -p "$O"
for I in 0 6; do
  for SZ in 375x667 1440x900; do
    for FIN in 1 0; do
      T=$([ "$FIN" = 0 ] && echo before || echo after)
      D="$O/v$I-$SZ-$T"
      ../../ops/heavy-slot.sh "fin-$I-$SZ-$FIN" --cores 2 -- node demo_scene_dump.mjs "$HOME/scout-scenes/flat215-demo/demo-data.json" "$I" "$BUNDLE" "$D" shots=$SZ maxcams=2 finish=$FIN 2>&1 | grep -v "THREE\|Failed to load"
      for J in 0 1; do cp "$D/shot-$T-$J.jpg" "$O/v$I-cam$J-$SZ-finish$([ "$FIN" = 0 ] && echo off || echo on).jpg" 2>/dev/null; done
    done
  done
done
echo DONE > "$O/done.txt"
