#!/usr/bin/env bash
# T-20261117-21: кадры живой сцены /demo из ракурсов данных «до» и «после» правила декора — для глаз.
#   cams_shots.sh <папка бандла> <папка-вывода> <данные-до.json> <данные-после.json> [индексы вариантов] [размер WxH]
BUNDLE="$1"; O="$2"; BEFORE="$3"; AFTER="$4"; IDX="${5:-0 1 2 3 5}"; SZ="${6:-1440x900}"
cd "$(dirname "$0")" || exit 1
mkdir -p "$O"
for I in $IDX; do
  for T in before after; do
    DATA="$BEFORE"; [ "$T" = after ] && DATA="$AFTER"
    D="$O/v$I-$T-raw"
    ../../ops/heavy-slot.sh "camshots-$I-$T" --cores 2 --short -- node demo_scene_dump.mjs "$DATA" "$I" "$BUNDLE" "$D" shots=$SZ maxcams=2 2>&1 | grep -v "THREE\|Failed to load"
    for J in 0 1; do cp "$D/shot-after-$J.jpg" "$O/v$I-C$((J+1))-$T-$SZ.jpg" 2>/dev/null; done
  done
done
echo DONE > "$O/done.txt"
