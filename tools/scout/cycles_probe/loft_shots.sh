#!/usr/bin/env bash
# T-20261117-16: снимки /demo лофтов с акцентной кирпичной стеной и без неё (`?finish=0` — «до»): 2 спальни и гостиная, телефон 375×667 и компьютер 1440×900.
#   loft_shots.sh <папка бандла> <папка-вывода> [индексы вариантов]
BUNDLE="$1"; O="$2"; IDX="${3:-9 14 3}"
cd "$(dirname "$0")" || exit 1
mkdir -p "$O"
for I in $IDX; do
  for SZ in 375x667 1440x900; do
    for FIN in 1 0; do
      T=$([ "$FIN" = 0 ] && echo before || echo after)
      D="$O/v$I-$SZ-$T"
      ../../ops/heavy-slot.sh "loft-$I-$SZ-$FIN" --cores 2 -- node demo_scene_dump.mjs "$HOME/scout-scenes/flat215-demo/demo-data.json" "$I" "$BUNDLE" "$D" shots=$SZ maxcams=2 finish=$FIN 2>&1 | grep -v "THREE\|Failed to load"
      for J in 0 1; do cp "$D/shot-$T-$J.jpg" "$O/v$I-cam$J-$SZ-$([ "$FIN" = 0 ] && echo before || echo after).jpg" 2>/dev/null; done
    done
  done
done
echo DONE > "$O/done.txt"
