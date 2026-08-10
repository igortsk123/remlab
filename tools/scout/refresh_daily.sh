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
  local parts="" fails=""
  for k in "${!RES[@]}"; do
    parts="$parts\"$k\":\"${RES[$k]}\","
    [ "${RES[$k]}" = FAIL ] && fails="$fails $k"
  done
  printf '{"date":"%s","finished":"%s","feeds_ok":%s,%s"products":%s}\n' \
    "$today" "$(date '+%F %T')" "${ok:-0}" "$parts" "$(products_count)" > "$STATUS"
  echo "=== $(date '+%F %T') готово (фиды ok=${ok:-0}) ===" >> "$LOG"
  # сбой не должен ждать, пока его случайно заметят (урок: load3 FAIL 05.08 нашли вечером)
  [ -n "$fails" ] && bash alert.sh "remlab: refresh_daily FAIL:$fails (см. refresh.log)"
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
FEEDS="f7633bdd943d41c718c12dc88e7a61f2b88b55c6 c0021e3fe460caf057f3d7823043b14adf6acb0c a5906abd53d7d2efaff63c5021bd1cd4fb337a45 a5bb9dc9178031fc6c3b165c3df9c20bfcc55e18 bb618f0e32cb08ab8d5a247cd15d494516ba3523 777e580d462f92086d4875cf39500375e2a113f6 4255a3608faf6a4bd3b7007f2f0a9977b1f0c89c ec02cfec770831e51450542cf9e6fc0ee53657e4 1b9f77d20e11b89864c73ac9551ff57be0bff818 e2fccbea464497bf6273f6a714ceada976dd4cfe"
ok=1
for h in $FEEDS; do
  for try in 1 2; do
    curl -sL --max-time 300 -o "feeds2/$h.xml.zip.new" "https://export.gdeslon.ru/uploads/exports/$h.xml.zip" \
      && [ -s "feeds2/$h.xml.zip.new" ] && mv "feeds2/$h.xml.zip.new" "feeds2/$h.xml.zip" && break
    [ "$try" = 2 ] && { echo "фид $h НЕ скачался — оставлен прежний" >> "$LOG"; ok=0; } || sleep 20
  done
done

# 1b. Предохранитель фидов (T0 truth-first): пустой исторически-непустой фид и протухший
# yml_date алертятся ДО загрузки — «скачался успешно» не значит «данные живые» (урок 203)
step feed_guard "$PY" feed_guard.py

# 2. База: upsert, хеши дельты, статусы жизненного цикла (ADR-0068)
step load3 "$PY" load3.py
[ "${RES[load3]}" = ok ] || { echo "загрузка упала — дальше по цепочке не идём" >> "$LOG"; exit 1; }

# 3. Отпечатки картинок по кэшу — бесплатно, ловит «URL сменился, картинка та же»
step phash "$PY" phash.py --from-cache

# 4. Обогащение НОВИНОК и тех, у кого сменился смысл. Дельта, обычно единицы процентов пула.
# --vision: стиль по тексту совпадает с фото лишь в 16% — фото обязательно (картинки дельты
# качаются в кэш перед отправкой, со счётчиком и стоп-предохранителем).
step enrich "$PY" enrich.py --pool --vision --batch

# 4b. Отправили — обязаны забрать (ADR-0073): ожидание фоновое (пакет считается до 24 ч),
# успех = id-файл заархивирован; после забора enrich_wait сам пересоберёт индекс и комплекты.
if [ -s enrich-batch-id.txt ]; then
  nohup bash enrich_wait.sh >> "$LOG" 2>&1 &
  echo "пакет отправлен — enrich_wait.sh ждёт и заберёт в фоне (pid $!)" >> "$LOG"
fi

# 5. Индекс кандидатов и здоровье комплектов (по текущим данным; после забора батча
# enrich_wait обновит индекс ещё раз — уже с новинками)
step candidates "$PY" candidates.py --build
step sets_index "$PY" sets_incremental.py --index
step sets_check "$PY" sets_incremental.py --check
# 6→5b. W5 (аудит 10.08): ЖИВОСТЬ КАРТОЧЕК ДО ЛЕЧЕНИЯ — иначе мёртвое, найденное сегодня,
# лечится только завтра. health теперь проверяет и sets3 (боевое поколение).
step health "$PY" health.py
step metrics "$PY" sync_metrics.py
# 5b. АВТОЗАМЕНА выбывших (владелец 2026-08-07: «товар заменяться должен автоматом, если
# наличия нет»): запасной той же роли, в наличии, ±30% цены, с перепроверкой пропорций;
# без замены — комплект честно помечается. Бэкап sets3.json пишет сам heal.
step sets_heal "$PY" sets_incremental.py --heal --apply
# W5: после замен индекс обязан сойтись с sets3 СЕГОДНЯ, а не завтра
step sets_reindex "$PY" sets_incremental.py --index
# W5: терра-эскалация слабых карточек — в кроне с дневным капом (разовая добивка новичков
# трёх свежих фидов ~3.2k, дальше капли; владелец 10.08 подтвердил)
step escalate "$PY" enrich.py --escalate --limit 400

# 7. Страница расстановок владельцу — пересобирается и публикуется КОНВЕЙЕРОМ ежедневно
# (требование владельца 2026-08-07: никаких ручных сборок). Набор сетов — референсная десятка.
step layout_page env LAYOUT10_PUBLISH=1 "$PY" layout10_page.py 1 14 21 29 55 59 66 84 113 117

# 8. ЕЖЕНЕДЕЛЬНО (понедельник): полный перегон размещаемости всех сетов — решение владельца
# 2026-08-07 («прогон по остаткам раз в неделю достаточно»). Отчёт: solver-check-report.json.
if [ "$(date +%u)" = "1" ]; then
  step solver_full env CHECK_TAG=weekly "$PY" solver_check.py
  # В3 (владелец 07.08): точечное освежение сетов новинками — лучшая ступень стиля, ≤2 замен/сет
  step sets_refresh "$PY" sets_incremental.py --refresh --apply
  # W5: после недельных замен — переиндекс и судья сетов (вернулся в цикл: баланс OpenAI есть,
  # владелец 10.08); судья смотрит коллажи и отмечает выбивающиеся предметы
  step sets_reindex_w "$PY" sets_incremental.py --index
  step sets_judge "$PY" judge.py || true
  # W5: еженедельный бэкап каталога (dev-БД существует в единственном экземпляре)
  step db_backup bash -c 'mkdir -p ~/backups && docker exec remlab-devdb pg_dump -U remlab remlab | gzip > ~/backups/remlab-devdb-$(date +%Y%m%d).sql.gz && ls -t ~/backups/remlab-devdb-*.sql.gz | tail -n +5 | xargs -r rm'
fi

echo "$today" > "$STAMP"
