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
# РУБИЛЬНИК платных OpenAI-шагов (владелец 17.08: продукт не запущен, занимаемся расстановкой —
# обогащение/эскалация/судьи отключены). Файл-флаг: `touch openai.off` — выключено; `rm openai.off` — включено.
# Бесплатные шаги (фиды, load3, capabilities, индексы, heal, страницы) идут как прежде.
OPENAI_OFF=0; [ -f openai.off ] && OPENAI_OFF=1
paid_step() { if [ "$OPENAI_OFF" = "1" ]; then echo "openai.off: платный шаг «$1» пропущен" >> "$LOG"; else step "$@"; fi; }
# Дневной лимит $ на все модели — rules/openai_prices.json daily_cap_usd (5.0, владелец 17.08); гейт внутри
# enrich/judge (openai_budget.allow) перед каждой отправкой; отчёт: `openai_budget.py --report 7`
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
  printf '{"date":"%s","finished":"%s","feeds_ok":%s,"feeds_downloaded":%s,"feeds_total":%s,"feeds_dead":"%s",%s"products":%s}\n' \
    "$today" "$(date '+%F %T')" "${ok:-0}" "${dl_ok:-0}" "${dl_total:-0}" "${dead# }" "$parts" "$(products_count)" > "$STATUS"
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
ok=1; dl_ok=0; dl_total=0; dead=""
for h in $FEEDS; do
  dl_total=$((dl_total+1)); got=0
  for try in 1 2; do
    # ответ обязан быть zip (magic PK): 16.08 Гдеслон отдал 404-HTML по 777e580d, curl сохранил его как
    # .xml.zip поверх прежнего архива → load3 упал на BadZipFile и ВЕСЬ конвейер остановился (урок).
    curl -sfL --max-time 300 -o "feeds2/$h.xml.zip.new" "https://export.gdeslon.ru/uploads/exports/$h.xml.zip" \
      && [ -s "feeds2/$h.xml.zip.new" ] && "$PY" -c "import zipfile,sys;sys.exit(0 if zipfile.is_zipfile('feeds2/$h.xml.zip.new') and zipfile.ZipFile('feeds2/$h.xml.zip.new').testzip() is None else 1)" \
      && mv "feeds2/$h.xml.zip.new" "feeds2/$h.xml.zip" && got=1 && break
    rm -f "feeds2/$h.xml.zip.new"
    [ "$try" = 2 ] && { echo "фид $h НЕ скачался — оставлен прежний" >> "$LOG"; ok=0; } || sleep 20
  done
  # ССЫЛКА ВЫГРУЗКИ МОЖЕТ ПРОСТО УМЕРЕТЬ (26.08: nonton 404 с 11.08 — 11 595 товаров, треть
  # каталога, замерли на две недели и никто не заметил). Ведём журнал по каждой ссылке и
  # поднимаем тревогу, если она не отдаётся 2 дня подряд.
  if [ "$got" = 1 ]; then dl_ok=$((dl_ok+1)); "$PY" - "$h" <<'PYEOF' || true
import json,os,sys,datetime
p='feed-links.json'; d=json.load(open(p)) if os.path.exists(p) else {}
d.setdefault(sys.argv[1],{})['last_ok']=datetime.date.today().isoformat()
d[sys.argv[1]]['fails']=0
json.dump(d,open(p,'w'),ensure_ascii=False,indent=1)
PYEOF
  else
    dead="$dead $h"
    "$PY" - "$h" <<'PYEOF' || true
import json,os,sys,datetime
p='feed-links.json'; d=json.load(open(p)) if os.path.exists(p) else {}
r=d.setdefault(sys.argv[1],{}); r['fails']=int(r.get('fails') or 0)+1
r['last_fail']=datetime.date.today().isoformat()
json.dump(d,open(p,'w'),ensure_ascii=False,indent=1)
print(f"ССЫЛКА ВЫГРУЗКИ МЕРТВА {sys.argv[1][:12]}: неудач подряд {r['fails']}, последний успех {r.get('last_ok','неизвестно')}")
PYEOF
  fi
done
echo "фиды: скачано $dl_ok из $dl_total; мёртвые ссылки:${dead:- нет}" >> "$LOG"
# 2 дня подряд без выгрузки — это не «моргнуло», это ссылка сменилась в кабинете партнёрки
STALE_LINKS=$("$PY" -c "
import json,os
d=json.load(open('feed-links.json')) if os.path.exists('feed-links.json') else {}
print(' '.join(k[:12] for k,v in d.items() if int(v.get('fails') or 0)>=2))" 2>/dev/null)
[ -n "$STALE_LINKS" ] && bash alert.sh "remlab: ссылки выгрузок не отдаются 2+ дня:$STALE_LINKS — нужна новая ссылка в кабинете Гдеслона"

# 1b. Предохранитель фидов (T0 truth-first): пустой исторически-непустой фид и протухший
# yml_date алертятся ДО загрузки — «скачался успешно» не значит «данные живые» (урок 203)
step feed_guard "$PY" feed_guard.py

# 1b. ДОСТУПНОСТЬ ПАРТНЁРОК (26.08). Ссылка выгрузки может 404-ить не потому, что «моргнуло», а
# потому что программы магазина у нас больше нет: так nonton (11 595 товаров) две недели висел
# в каталоге мёртвым грузом. Список рекламодателей в API — источник правды; товары закрытых
# программ снимаются с продажи, дальше их заменяет контракт слота.
step shops_check "$PY" gdeslon_api.py --retire

# 2. База: upsert, хеши дельты, статусы жизненного цикла (ADR-0068)
step load3 "$PY" load3.py
[ "${RES[load3]}" = ok ] || { echo "загрузка упала — дальше по цепочке не идём" >> "$LOG"; exit 1; }

# 3. Отпечатки картинок по кэшу — бесплатно, ловит «URL сменился, картинка та же»
step phash "$PY" phash.py --from-cache

# 4. Обогащение НОВИНОК и тех, у кого сменился смысл. Дельта, обычно единицы процентов пула.
# --vision: стиль по тексту совпадает с фото лишь в 16% — фото обязательно (картинки дельты
# качаются в кэш перед отправкой, со счётчиком и стоп-предохранителем).
# ОПТИМИЗАЦИЯ 17.08 (владелец принял): дельта новинок — с дневным лимитом (ENRICH_DAILY_LIMIT, по умолчанию
# 200 карточек = ≤400 запросов luna+фото); эскалация — ТОЛЬКО вручную (`enrich.py --escalate --limit N`);
# судья сетов — по команде; дрифт-судья — раз в неделю (enrich_wait). Расход — `enrich.py --spend 7`
paid_step enrich "$PY" enrich.py --pool --vision --batch --limit "${ENRICH_DAILY_LIMIT:-200}"

# 4b. Отправили — обязаны забрать (ADR-0073): ожидание фоновое (пакет считается до 24 ч),
# успех = id-файл заархивирован; после забора enrich_wait сам пересоберёт индекс и комплекты.
if [ -s enrich-batch-id.txt ]; then
  nohup bash enrich_wait.sh >> "$LOG" 2>&1 &
  echo "пакет отправлен — enrich_wait.sh ждёт и заберёт в фоне (pid $!)" >> "$LOG"
fi

# 5. Индекс кандидатов и здоровье комплектов (по текущим данным; после забора батча
# enrich_wait обновит индекс ещё раз — уже с новинками)
# 4c. Q6a свода №13: capability-проекция каталога (product_capabilities) — детерминированно из
# params/габаритов/актуального обогащения; второй пересчёт — в enrich_wait.sh после забора батча
step capabilities "$PY" capabilities.py --build --export
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
# ЗАМОК экзамена (17.08): банки под бегущими воркерами не менять — heal/refresh/сборка отложены до завтра
if [ -f exam.lock ]; then echo "exam.lock: идёт экзамен — sets_heal/sets_refresh пропущены" >> "$LOG"; else
# 5b-0. МЕДИА БАНКА = КАТАЛОГ (26.08). Фото и ссылка — производные данные: держать их в банке
# замороженными означает показывать чужую картинку и мёртвую реф-ссылку (найдено 1490 позиций
# с фото ДРУГОГО товара). Сверяем перед лечением, чтобы лечение решало по актуальным данным.
step bank_media "$PY" catalog_media.py --apply
# ФОТО ПРОВЕРЯЕМ КАЖДЫЙ ДЕНЬ, А НЕ РАЗ В 14 ДНЕЙ (владелец 26.08: «чтоб всегда были актуальные
# ссылки и фотки»): ссылок в банке ~750, это минуты; TTL кэша остаётся для пула замен.
step bank_photos "$PY" img_alive.py --scan --force
step sets_heal "$PY" sets_incremental.py --heal --apply
# 5b-1. КОНТРАКТ СЛОТА И ЖИВОЕ ФОТО (владелец 26.08: «товар без фото не должен участвовать —
# пересчитывать надо на этапе сетов»): позиция вне конверта слота или с мёртвой картинкой
# ЗАМЕНЯЕТСЯ, и только если замены нет — снимается с записью coverage_gap.
step sets_contracts "$PY" sets_incremental.py --enforce-contracts --apply
# после замен индекс и медиа обязаны сойтись с банком СЕГОДНЯ
step bank_media2 "$PY" catalog_media.py --apply
fi
# W5: после замен индекс обязан сойтись с sets3 СЕГОДНЯ, а не завтра
step sets_reindex "$PY" sets_incremental.py --index
# W5: терра-эскалация слабых карточек — в кроне с дневным капом (разовая добивка новичков
# трёх свежих фидов ~3.2k, дальше капли; владелец 10.08 подтвердил)
# paid_step escalate — снято из ежедневного цикла (17.08): эскалация до 400/день была главным постоянным расходом; вручную партиями

# 7. Страница расстановок владельцу — пересобирается и публикуется КОНВЕЙЕРОМ ежедневно
# (требование владельца 2026-08-07: никаких ручных сборок). Набор сетов — референсная десятка.
step layout_page env LAYOUT10_PUBLISH=1 "$PY" layout10_page.py 1 14 21 29 55 59 66 84 113 117

# 7b. ДЕМО ИНТЕРАКТИВНОГО ПЛАНИРОВЩИКА — тоже ежедневно (26.08): банк меняется каждый день,
# и страница с вчерашними товарами показывает мёртвые карточки.
step flat215_demo "$PY" flat215_demo.py
step flat215_publish bash publish_demo.sh

# 8. ЕЖЕНЕДЕЛЬНО (понедельник): полный перегон размещаемости всех сетов — решение владельца
# 2026-08-07 («прогон по остаткам раз в неделю достаточно»). Отчёт: solver-check-report.json.
if [ "$(date +%u)" = "1" ]; then
  step solver_full env CHECK_TAG=weekly "$PY" solver_check.py
  # В3 (владелец 07.08): точечное освежение сетов новинками — лучшая ступень стиля, ≤2 замен/сет
  [ -f exam.lock ] || step sets_refresh "$PY" sets_incremental.py --refresh --apply
  # W5: после недельных замен — переиндекс и судья сетов (вернулся в цикл: баланс OpenAI есть,
  # владелец 10.08); судья смотрит коллажи и отмечает выбивающиеся предметы
  step sets_reindex_w "$PY" sets_incremental.py --index
  # paid_step sets_judge — снято из еженедельного цикла (17.08): судья сетов только по команде владельца
  # W5: еженедельный бэкап каталога (dev-БД существует в единственном экземпляре)
  step db_backup bash -c 'mkdir -p ~/backups && docker exec remlab-devdb pg_dump -U remlab remlab | gzip > ~/backups/remlab-devdb-$(date +%Y%m%d).sql.gz && ls -t ~/backups/remlab-devdb-*.sql.gz | tail -n +5 | xargs -r rm'
fi

echo "$today" > "$STAMP"
