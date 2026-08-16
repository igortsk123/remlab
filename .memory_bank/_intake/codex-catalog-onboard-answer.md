Сейчас `bash refresh_daily.sh --force` запускать нельзя: второй пробный прогон в 16:44 обнаружил новую регрессию — переменная `_h` с hash фида затёрла функцию `_h()`, поэтому `commercial_hash()` падает с `TypeError` ([load3.py:35](/home/pakar/igor/remlab/tools/scout/load3.py:35), [load3.py:84](/home/pakar/igor/remlab/tools/scout/load3.py:84), [refresh.log:6669](/home/pakar/igor/remlab/tools/scout/refresh.log:6669)).

### (a) Политика исчезнувшего фида

По истории `777e…`: `fresh` 08.08, `degraded` 09.08, `stale` 10.08, `broken` с 11.08 ([refresh.log:4808](/home/pakar/igor/remlab/tools/scout/refresh.log:4808), [refresh.log:5212](/home/pakar/igor/remlab/tools/scout/refresh.log:5212), [refresh.log:5622](/home/pakar/igor/remlab/tools/scout/refresh.log:5622), [refresh.log:6373](/home/pakar/igor/remlab/tools/scout/refresh.log:6373)). Последний `yml_date` был примерно 07.08 21:00; вся цепочка фактически не работала с 11 августа.

Рекомендованная политика:

- Товар исчез из исправного свежего фида: текущая логика правильная — первый пропуск → `missing` и `in_stock=false`, третий → `archived`; при возврате снова `active` ([load3.py:240](/home/pakar/igor/remlab/tools/scout/load3.py:240)).
- Исчез целый источник: не объявлять все SKU `out_of_stock` — 404 фида не доказывает отсутствие товаров. Нужен отдельный source-level `eligible`.
- До 30 ч — normal; 30–54 ч — `degraded`: существующие сеты можно оставить при живой карточке, но новые позиции лучше не брать; после 54 ч либо при `broken/empty` — исключить mid из compose/candidates/heal, заменить существующие позиции, неремонтируемые сеты реально скрыть. После 7 дней — источник переводить в `disabled` до решения владельца, сохраняя товары и enrichment.

Что уже есть:

- `feed_guard` считает `fresh/degraded/stale` и алертит, но всегда выходит 0 и БД не меняет ([feed_guard.py:26](/home/pakar/igor/remlab/tools/scout/feed_guard.py:26), [feed_guard.py:80](/home/pakar/igor/remlab/tools/scout/feed_guard.py:80)).
- `compose2` пытается исключать `stale/broken` mids из новых сетов ([compose2.py:245](/home/pakar/igor/remlab/tools/scout/compose2.py:245)).
- `health.py` проверяет карточки товаров, уже стоящих в sets1/2/3, и гасит мёртвые ([health.py:40](/home/pakar/igor/remlab/tools/scout/health.py:40), [health.py:60](/home/pakar/igor/remlab/tools/scout/health.py:60)).
- `sets_heal` заменяет `status != active` либо `in_stock=false` на ±30% цены с проверкой пропорций ([sets_incremental.py:203](/home/pakar/igor/remlab/tools/scout/sets_incremental.py:203), [sets_incremental.py:218](/home/pakar/igor/remlab/tools/scout/sets_incremental.py:218)).

Что отсутствует/сломано:

- У `broken`-записи теряются прежние `mids`, поэтому `compose2` сейчас не узнаёт, что broken `777e…` — это mid `116933` ([feed_guard.py:68](/home/pakar/igor/remlab/tools/scout/feed_guard.py:68), [feed-freshness.json:22](/home/pakar/igor/remlab/tools/scout/feed-freshness.json:22)).
- `candidates.py` и `sets_heal` вообще не учитывают freshness источника — только `active/in_stock` ([candidates.py:51](/home/pakar/igor/remlab/tools/scout/candidates.py:51), [sets_incremental.py:231](/home/pakar/igor/remlab/tools/scout/sets_incremental.py:231)). Они могут поставить другой непроверенный товар Nonton.
- Фраза «комплект скрывается» — только лог: никакой `hidden/unhealthy` в JSON не записывается ([sets_incremental.py:267](/home/pakar/igor/remlab/tools/scout/sets_incremental.py:267)).
- В текущем `sets3.json` Nonton участвует во всех 126 сетах: 1 076 позиций, поэтому источник надо карантинить через dry-run heal, а не массовым `in_stock=false`.
- `health.py` считает любой HTTP/сетевой exception смертью товара без retry/unknown-state — возможны ложные массовые замены ([health.py:21](/home/pakar/igor/remlab/tools/scout/health.py:21)).

### (b) Перезапуск

После переименования `_h` → `_feed_hash` — да, после окончания layout exam catch-up нужен. До запуска желательно узнать размер платной дельты: успешного `load3` не было с 10.08, поэтому точное число сейчас неизвестно. Текущим безопасным способом после ручного `load3.py` можно выполнить `enrich.py --sample 0`: он напечатает размер todo, но отправит ноль запросов ([enrich.py:562](/home/pakar/igor/remlab/tools/scout/enrich.py:562)).

`--pool --vision --batch`:

- берёт только новых/сброшенных по text/geometry/image товарам ([enrich.py:126](/home/pakar/igor/remlab/tools/scout/enrich.py:126));
- отправляет два запроса на товар — text + vision, то есть `2 × N` ([enrich.py:311](/home/pakar/igor/remlab/tools/scout/enrich.py:311));
- блокирует отправку при незабранном старом batch и при доступности картинок <90% ([enrich.py:276](/home/pakar/igor/remlab/tools/scout/enrich.py:276), [enrich.py:284](/home/pakar/igor/remlab/tools/scout/enrich.py:284));
- денежного/числового лимита у cron-прогона нет. Дополнительно позже идёт синхронная Terra-эскалация до 400 товаров ([refresh_daily.sh:112](/home/pakar/igor/remlab/tools/scout/refresh_daily.sh:112)).

По официальной документации Luna сейчас стоит $0.20/$1.20 за 1M input/output tokens, а Batch даёт 50% скидку и окно до 24 часов: [GPT‑5.6 Luna](https://developers.openai.com/api/docs/models/gpt-5.6-luna), [Batch API](https://developers.openai.com/api/docs/guides/batch). Точный чек без N и token estimate код не рассчитывает.

Проверка после запуска:

```bash
jq . refresh-status.json
rg -n "ДЕЛЬТА|СТАТУСЫ|к обогащению|часть 1:|вылечено ролей|без замены|готово" refresh.log | tail -40
test ! -s enrich-batch-id.txt && tail -1 enrich-batch-log.txt
stat candidates-index.json sets-index.json health-report.json enrich-drift.jsonl sets3.json
```

Ожидание:

- `refresh-status.json` содержит все шаги до `layout_page` со значением `ok`; `feeds_ok:0` из-за Nonton допустим, `load3:FAIL` — нет ([refresh_daily.sh:24](/home/pakar/igor/remlab/tools/scout/refresh_daily.sh:24)).
- Успешный background-fetch удаляет `enrich-batch-id.txt`, дописывает batch-log и пересобирает candidates/index/judge ([enrich_wait.sh:39](/home/pakar/igor/remlab/tools/scout/enrich_wait.sh:39)).
- Важно: background-fetch не повторяет `sets_heal`. Если новые обогащённые кандидаты должны закрыть прежнюю дырку, после исчезновения batch-id отдельно выполнить `sets_incremental.py --heal --apply`, затем `--index`.

### (c) Риски фиксов

- PK-проверка — правильное направление и защищает от текущего HTML, но первые два байта не гарантируют целый ZIP: обрезанный архив тоже начинается с `PK`. Перед `mv` лучше `curl --fail` плюс полная `zipfile.is_zipfile()`/`unzip -tq` проверка ([refresh_daily.sh:64](/home/pakar/igor/remlab/tools/scout/refresh_daily.sh:64)).
- После сохранения старого исправного архива он станет `stale`, но `load3` сейчас пропускает только `broken`, поэтому будет ежедневно загружать старый фид, ставить свежий `last_seen` и возвращать `in_stock=true`. Следует пропускать также `stale/empty`, сохраняя `mids/last_good/first_bad` из реестра источников.
- Блокирующая регрессия `_h` описана выше.
- Новый `bceea2bc…` добавлять не нужно: в `FEEDS` правильно остаётся только существующий `1b9f77d2…` ([refresh_daily.sh:60](/home/pakar/igor/remlab/tools/scout/refresh_daily.sh:60)).

Live Docker SQL из этой read-only sandbox недоступен; числа Nonton беру из переданных FACTS, а схему/поведение сверил по миграциям, коду и журналу.