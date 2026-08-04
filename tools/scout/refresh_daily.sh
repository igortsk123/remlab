#!/bin/bash
# Ежедневное обновление каталога и здоровья сетов (catalog-freshness Ф2).
# Качает 7 фидов (постоянные ссылки), перезаливает products, проверяет карточки товаров сетов,
# автозаменяет мёртвых в sets2.json. Лог: refresh.log. Guard: не чаще раза в сутки.
set -u
cd "$(dirname "$0")"
STAMP=.last-refresh
today=$(date +%F)
[ -f "$STAMP" ] && [ "$(cat $STAMP)" = "$today" ] && exit 0
LOG=refresh.log
echo "=== $(date '+%F %T') старт ===" >> "$LOG"
mkdir -p feeds2
FEEDS="f7633bdd943d41c718c12dc88e7a61f2b88b55c6 c0021e3fe460caf057f3d7823043b14adf6acb0c a5906abd53d7d2efaff63c5021bd1cd4fb337a45 a5bb9dc9178031fc6c3b165c3df9c20bfcc55e18 bb618f0e32cb08ab8d5a247cd15d494516ba3523 777e580d462f92086d4875cf39500375e2a113f6 4255a3608faf6a4bd3b7007f2f0a9977b1f0c89c"
ok=1
for h in $FEEDS; do
  curl -sL --max-time 300 -o "feeds2/$h.xml.zip.new" "https://export.gdeslon.ru/uploads/exports/$h.xml.zip" \
    && [ -s "feeds2/$h.xml.zip.new" ] && mv "feeds2/$h.xml.zip.new" "feeds2/$h.xml.zip" \
    || { echo "фид $h НЕ скачался — оставлен прежний" >> "$LOG"; ok=0; }
done
python3 load3.py >> "$LOG" 2>&1 || { echo "load3 FAIL" >> "$LOG"; exit 1; }
python3 health.py >> "$LOG" 2>&1 || echo "health FAIL" >> "$LOG"
python3 sync_metrics.py >> "$LOG" 2>&1 || echo "sync_metrics FAIL" >> "$LOG"
# стиль-оценки НОВИНОК (дельта по кэшу style-scores.json; sets-style-v3)
"$HOME/venvs/scout/bin/python" style_score.py >> "$LOG" 2>&1 || echo "style_score FAIL" >> "$LOG"
echo "$today" > "$STAMP"
echo "=== $(date '+%F %T') готово (фиды ok=$ok) ===" >> "$LOG"
