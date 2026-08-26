## Вывод

Корень дефекта — не `load3.py`, не первичная запись `compose2.py` и не доказанное переиспользование CDN-путей. Непосредственная причина — частичная замена товара в `sets_incremental.py`: меняются `(mid,eid,name,price,dimensions)`, но сохраняются `img`, `url`, `shop`, иногда `fp` предыдущего товара.

Архитектурная причина — банк разрешает хранить такой гибрид без проверки инварианта:

> все поля позиции должны происходить из одной версии товара `(shop_mid, external_id)`.

«Устаревший снимок» тоже присутствует, но как фактор накопления дрейфа, а не как главное объяснение массовой подмены.

## 1. Доказательство корня

`load3.py` читает `eid`, `name`, `picture` и URL из одного XML `<offer>` и складывает их в одну строку ([load3.py](/home/pakar/igor/remlab/tools/scout/load3.py:85)). Upsert обновляет `url` и `image_url` той же `excluded`-строкой по PK `(shop_mid,external_id)` ([load3.py](/home/pakar/igor/remlab/tools/scout/load3.py:163)). Механизма, способного взять картинку соседнего offer, здесь не видно.

`compose2.py` также получает `(mid,eid,name,image_url,url)` одной SQL-строкой ([compose2.py](/home/pakar/igor/remlab/tools/scout/compose2.py:236)), создаёт единый словарь товара ([compose2.py](/home/pakar/igor/remlab/tools/scout/compose2.py:291)) и переносит его в банк ([compose2.py](/home/pakar/igor/remlab/tools/scout/compose2.py:1279)). Старый полностью собранный [sets3-enrich1.json](/home/pakar/igor/remlab/tools/scout/sets3-enrich1.json) имел 809 уникальных ключей и 809 изображений без дублей; все 2337 позиций, найденные в актуальном candidate-index, совпали по картинке.

Дефект появляется при incremental-заменах:

- `alternates` изначально содержат только `mid/eid/name/price/score`, без картинки и URL ([compose2.py](/home/pakar/igor/remlab/tools/scout/compose2.py:749)).
- `heal` делает `cand = dict(it)`, то есть копирует старый товар целиком, а затем обновляет ограниченный список полей без `img/url/shop` ([sets_incremental.py](/home/pakar/igor/remlab/tools/scout/sets_incremental.py:455)).
- `refresh` делает то же самое ([sets_incremental.py](/home/pakar/igor/remlab/tools/scout/sets_incremental.py:258)).
- `enforce_contracts` также сохраняет старую картинку при новой identity ([sets_incremental.py](/home/pakar/igor/remlab/tools/scout/sets_incremental.py:558)).

Текущая незакоммиченная правка добавила `img/url` в `_live_candidates`, но это не исправляет дефект: три перечисленных whitelist-update по-прежнему не копируют эти поля.

Данные подтверждают механизм:

- В исходном [sets3.json.bak-media](/home/pakar/igor/remlab/tools/scout/sets3.json.bak-media): 3086 позиций, 891 товар, 766 ненулевых `img`, 202 картинки принадлежат нескольким ключам.
- Между [sets3.json.bak](/home/pakar/igor/remlab/tools/scout/sets3.json.bak) и [sets3.json.bak-erid](/home/pakar/igor/remlab/tools/scout/sets3.json.bak-erid) 785 слотов сменили `(mid,eid)`, и все 785 сохранили прежние `img` и `url`. Это сигнатура partial merge, а не CDN reuse.
- Резолвинг медиа из текущей БД изменил ровно 1490 изображений без единой смены `(mid,eid)`. После этого 891 ключу соответствуют 891 URL.
- Ориндж в старых полноценных сборках имел правильный `497409186`. Позднее тот же ключ появился с `497426785`, то есть неверная картинка возникла после первичной сборки.

CDN reuse остаётся теоретическим риском, но как объяснение данного инцидента не выдерживает сравнения с переходами банка.

## 2. Считать ли `img/url` производными

Да — для текущей витрины это производные операционные поля. Банк должен хранить identity и причины выбора товара, а экспорт должен join/resolver-ом получать актуальные:

- `image_url`;
- отдельно `affiliate_url` и `direct_url`, а не неоднозначное поле `url`;
- актуальные `name/price/availability`.

Сейчас есть ещё одна несовместимость: `compose2` использует `direct_url`, а новый `candidates.py` сохраняет `p.url`, то есть партнёрский redirect ([candidates.py](/home/pakar/igor/remlab/tools/scout/candidates.py:53)). Копировать одно поле `url` между этими путями нельзя без явного контракта.

Историчность решается не обслуживанием замороженного `img` как истины, а версионированием:

- в банке: `(mid,eid)`, `selected_at`, `catalog_run_id`, snapshot габаритов/цены/стилевых признаков;
- в воспроизводимом экспорте: полная материализованная карточка и хеш/версия изображения;
- для актуальной витрины: текущие поля из последнего успешного свежего каталога.

Риск резолвинга «на сейчас»: фотография может измениться, а стилевой выбор был сделан по старой. Поэтому смена изображения должна инвалидировать позицию сета и запускать пересчёт, а не только подменять URL.

Появившийся во время аудита `catalog_media.py` пока не закрывает архитектуру:

- читает все исторические строки `products`, без `in_stock/status/freshness` ([catalog_media.py](/home/pakar/igor/remlab/tools/scout/catalog_media.py:30));
- `None — ушёл из фида` в его docstring неверно;
- используется как разовая синхронизация банка, но потребители по-прежнему читают сохранённый `img`;
- исправляет медиа, но не пересчитывает сет.

## 3. Исчезнувшие товары и ложный ноль

Да, `0 пропавших` замаскирован механикой хранения.

`load3.py` не удаляет строки: при отсутствии в принятом свежем фиде ставит `in_stock=false` ([load3.py](/home/pakar/igor/remlab/tools/scout/load3.py:163)), а в enrichment наращивает `missing_runs` и переводит `missing → archived` ([load3.py](/home/pakar/igor/remlab/tools/scout/load3.py:234)). Поэтому проверка простого существования ключа в `products` почти гарантированно даст ноль.

Дополнительно broken/stale/empty-фиды полностью пропускаются, а товары остаются «как есть» ([load3.py](/home/pakar/igor/remlab/tools/scout/load3.py:77)). В [feed-freshness.json](/home/pakar/igor/remlab/tools/scout/feed-freshness.json:22) источник `mid=116933` broken и присутствует только как `mids_quarantine_pending`.

Прямая сверка банка с доступными ZIP-фидами дала:

- 891 уникальный ключ банка;
- 495 относятся к источникам со свежим ZIP;
- 493 реально присутствуют в ZIP;
- 2 отсутствуют — три позиции банка;
- 396 ключей `mid=116933` сейчас не проверяемы из-за broken-фида; это 1059 позиций банка.

Надёжная схема:

1. Завести `feed_runs(source, run_id, fetched_at, state, offer_count)` и `product_seen(run_id,mid,eid)`.
2. Считать отсутствие только относительно последнего успешно принятого run конкретного источника.
3. Для broken/stale источника ставить `availability=unknown/quarantined` и исключать из новых/лечимых сетов после SLA, но не утверждать индивидуальное исчезновение.
4. `missing_runs` увеличивать один раз на уникальный успешный run, а не на каждый повторный запуск `load3.py` в тот же день.
5. Любая сверка банка должна требовать `status='active'`, `in_stock`, `last_seen == source.last_successful_run` и свежий источник.

## 4. Порядок `--enforce-contracts`

До исправления media применять небезопасно. Более того, текущий код пока небезопасен и после простого sync, потому что `enforce_contracts` меняет identity, но сохраняет часть старой карточки.

Dry-run `253 заменено / 9 снято` сделан на загрязнённых данных: живая чужая картинка могла ошибочно пропустить товар, а мёртвая чужая — заставить заменить хороший.

Правильный порядок:

1. Приостановить cron-мутации `--heal --apply` и `--refresh --apply` ([refresh_daily.sh](/home/pakar/igor/remlab/tools/scout/refresh_daily.sh:119)).
2. Исправить замену на атомарный `replace_item(new_product, preserved_slot_metadata)`, без whitelist-слияния старого и нового товара.
3. Нормализовать существующий банк из активного свежего каталога.
4. Проверить живость актуальных картинок всего candidate pool.
5. Пересобрать затронутые сеты целиком или dependency-aware: агрегаты `total/fill/style_fit`, пары, pod, alternates, layout.
6. Только затем запускать contracts и acceptance-инварианты.

Сам `enforce_contracts` сейчас не пересчитывает set-level агрегаты после замен/удалений, поэтому это не полноценная пересборка.

## 5. Другие источники неверного фото

- `img_alive.py` использует только `HEAD`; возможны ложные 404/403, 200 HTML и placeholders ([img_alive.py](/home/pakar/igor/remlab/tools/scout/img_alive.py:43)).
- Unknown и просроченный cache считаются живыми; исключения проглатываются fail-open ([img_alive.py](/home/pakar/igor/remlab/tools/scout/img_alive.py:55), [sets_incremental.py](/home/pakar/igor/remlab/tools/scout/sets_incremental.py:129)).
- `--scan` проверяет только текущий банк, не весь пул замен. Новый кандидат часто будет unknown.
- Ковры, люстры, картины и банкетки в `compose2` выбираются некоторыми ветками напрямую из `cat`, обходя новый liveness-gate `pick2` ([compose2.py](/home/pakar/igor/remlab/tools/scout/compose2.py:844), [compose2.py](/home/pakar/igor/remlab/tools/scout/compose2.py:926), [compose2.py](/home/pakar/igor/remlab/tools/scout/compose2.py:1247)).
- `flat215_demo.py` сначала обрезает пул до 60, а живость проверяет позже; живые кандидаты за пределами 60 уже потеряны ([flat215_demo.py](/home/pakar/igor/remlab/tools/scout/flat215_demo.py:120)).
- Демо просто удаляет роли без фото, а не заменяет/пересобирает комплект ([flat215_demo.py](/home/pakar/igor/remlab/tools/scout/flat215_demo.py:212)). Это прямо противоречит цели владельца.
- Локальный demo-cache без TTL считает файл вечным, если URL тот же ([flat215_demo.py](/home/pakar/igor/remlab/tools/scout/flat215_demo.py:176)).
- `compose2`-миниатюры и embeddings кэшируются по `(mid,eid)`, а не по image hash; смена фото оставляет старую визуальную оценку.
- `candidates.py` допускает payload с `enrichment_version=NULL`, то есть признаки старого изображения могут использоваться после инвалидации ([candidates.py](/home/pakar/igor/remlab/tools/scout/candidates.py:60)).
- `set_optimize.py` имеет аналогичный дефект: получает новую карточку без `image_url` и merge-ит её поверх старой, сохраняя старый `img` ([set_optimize.py](/home/pakar/igor/remlab/tools/scout/set_optimize.py:35), [set_optimize.py](/home/pakar/igor/remlab/tools/scout/set_optimize.py:103)).
- Upstream остаётся возможен: первый `<picture>` может быть неверным для варианта, external_id может переиспользоваться, CDN URL может сохранить путь при смене bytes. Уникальность URL не доказывает уникальность содержимого.

По текущему HEAD-кэшу после media-sync в банке 891 URL: 498 помечены живыми, 393 мёртвыми; затронуто 1058 позиций и все 126 сетов. С учётом слабости HEAD это не окончательный ground truth, но достаточная причина пересчитать весь банк, а не вычеркнуть несколько карточек.

## Неопределённости

Доступ к Docker socket в моей sandbox-сессии запрещён, поэтому SQL `32343/32343` напрямую повторить не удалось. Я независимо подтвердил заявленные 1490 замен сравнением банка до/после DB-resolver, проверил candidate-index и распарсил ZIP-фиды напрямую.

Вывод мог бы уточниться при наличии:

- логов точных команд между `.bak`-снимками — они покажут долю `heal/refresh/enforce` в 785 partial replacements;
- последнего успешного исторического фида `mid=116933`;
- исторического DB snapshot вокруг момента порчи Ориндж;
- GET+decode/content-hash всех изображений вместо HEAD;
- истории соответствия `(mid,eid,image_url,image_hash)` по catalog run.

Если исторический фид покажет, что сам Гдеслон однажды прислал Ориндж с `497426785`, upstream станет соучастником. Но он не отменит доказанный дефект incremental merge: код и переходы банка самостоятельно способны породить именно наблюдаемую массовую подмену. Файлы я не изменял.