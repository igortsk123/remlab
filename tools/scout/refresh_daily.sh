#!/bin/bash
# Ежедневный цикл каталога: фид → база → статусы → обогащение новинок → индекс → комплекты.
#
# Раньше цикл обрывался на загрузке и молча оставался лежать: 2026-08-05 в 09:40 `load3 FAIL`,
# потому что контейнер БД был погашен, — фиды скачались, в базу не попали, и никто не узнал
# (замечание владельца). Теперь: контейнер поднимаем сами, шаги идут дальше по цепочке, результат
# каждого шага пишется в refresh-status.json — по нему видно, что сломалось и когда.
#
# Guard: не чаще раза в сутки (метка .last-refresh). Принудительно — `bash refresh_daily.sh --force`.
set -u
cd "$(dirname "$0")"
PY="$HOME/venvs/scout/bin/python"
STAMP=.last-refresh
LOG=refresh.log
STATUS=refresh-status.json
today=$(date +%F)
if [ "${1:-}" != "--force" ] && [ -f "$STAMP" ] && [ "$(cat $STAMP)" = "$today" ]; then exit 0; fi

declare -A RES
step() {                       # step <имя> <команда...>
  local name="$1"; shift
  if "$@" >> "$LOG" 2>&1; then RES[$name]=ok; else RES[$name]=FAIL; echo "$name FAIL" >> "$LOG"; fi
}
finish() {                     # статус пишем ВСЕГДА, даже если шаг упал
  local parts=""
  for k in "${!RES[@]}"; do parts="$parts\"$k\":\"${RES[$k]}\","; done
  printf '{"date":"%s","finished":"%s","feeds_ok":%s,%s"products":%s}\n' \
    "$today" "$(date '+%F %T')" "${ok:-0}" "$parts" "$(products_count)" > "$STATUS"
  echo "=== $(date '+%F %T') готово (фиды ok=${ok:-0}) ===" >> "$LOG"
}
products_count() {
  docker exec -i remlab-devdb psql -U remlab -d remlab -tAc \
    "select count(*) from products where in_stock" 2>/dev/null || echo 0
}
trap finish EXIT

echo "=== $(date '+%F %T') старт ===" >> "$LOG"

# 0. База должна быть жива — иначе весь прогон бессмыслен
if ! docker exec remlab-devdb pg_isready -U remlab >/dev/null 2>&1; then
  echo "контейнер remlab-devdb не отвечает — поднимаю" >> "$LOG"
  docker start remlab-devdb >> "$LOG" 2>&1
  for i in 1 2 3 4 5 6 7 8 9 10; do
    docker exec remlab-devdb pg_isready -U remlab >/dev/null 2>&1 && break
    sleep 3
  done
fi
if ! docker exec remlab-devdb pg_isready -U remlab >/dev/null 2>&1; then
  RES[db]=FAIL; echo "БД не поднялась — прогон отменён" >> "$LOG"; exit 1
fi
RES[db]=ok

# 1. Фиды (постоянные ссылки). Не скачался — работаем на прежнем файле, но помечаем.
mkdir -p feeds2
FEEDS="f7633bdd943d41c718c12dc88e7a61f2b88b55c6 c0021e3fe460caf057f3d7823043b14adf6acb0c a5906abd53d7d2efaff63c5021bd1cd4fb337a45 a5bb9dc9178031fc6c3b165c3df9c20bfcc55e18 bb618f0e32cb08ab8d5a247cd15d494516ba3523 777e580d462f92086d4875cf39500375e2a113f6 4255a3608faf6a4bd3b7007f2f0a9977b1f0c89c"
ok=1
for h in $FEEDS; do
  for try in 1 2; do
    curl -sL --max-time 300 -o "feeds2/$h.xml.zip.new" "https://export.gdeslon.ru/uploads/exports/$h.xml.zip" \
      && [ -s "feeds2/$h.xml.zip.new" ] && mv "feeds2/$h.xml.zip.new" "feeds2/$h.xml.zip" && break
    [ "$try" = 2 ] && { echo "фид $h НЕ скачался — оставлен прежний" >> "$LOG"; ok=0; } || sleep 20
  done
done

# 2. База: upsert, хеши дельты, статусы жизненного цикла (ADR-0068)
step load3 "$PY" load3.py
[ "${RES[load3]}" = ok ] || { echo "загрузка упала — дальше по цепочке не идём" >> "$LOG"; exit 1; }

# 3. Отпечатки картинок по кэшу — бесплатно, ловит «URL сменился, картинка та же»
step phash "$PY" phash.py --from-cache

# 4. Обогащение НОВИНОК и тех, у кого сменился смысл. Дельта, обычно единицы процентов пула.
step enrich "$PY" enrich.py --pool --batch

# 5. Индекс кандидатов и здоровье комплектов
step candidates "$PY" candidates.py --build
step sets_index "$PY" sets_incremental.py --index
step sets_check "$PY" sets_incremental.py --check

# 6. Старое поколение проверок (карточки sets2, метрики, стиль-оценки новинок)
step health "$PY" health.py
step metrics "$PY" sync_metrics.py
step style "$PY" style_score.py

echo "$today" > "$STAMP"
