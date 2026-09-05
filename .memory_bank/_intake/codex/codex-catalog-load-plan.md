## Вывод

План в целом направлен правильно, но начинать П2.3 и П3.4 в текущей формулировке опасно. Есть шесть блокеров:

1. CI в П0 запускает ещё не существующие `--selftest`; для `load3.py` это сейчас означает реальную загрузку в БД.
2. Финальный `refresh-status.json` создаётся только в `trap EXIT`, поэтому обычный шаг `status_publish` не может опубликовать финальный статус.
3. `step()` сейчас всегда возвращает успех, даже когда команда упала.
4. HD-бэкфилл инвалидирует `mesh_ready`, но не очищает материальный `products.mesh_status='ready'`.
5. П3.4 связывает меш и ориентацию недостаточно строго и предлагает блокировать фид целиком через строковый `dims_source='mesh'`.
6. `attrs_hash` не соответствует реальным входам обогащения и при `openai.off` превращает изменение параметра в потерю используемого payload.

## 1. Порядок П0–П5

- **[блокер] П0.4 нельзя выполнять до П2.1.** Сейчас `load3.py` исполняет DDL и весь импорт на уровне модуля; аргумент `--selftest` он не разбирает. `feed_guard.py --selftest` также просканирует живые фиды и может отправить алерт, а `category_map.py --selftest` просто напечатает docstring и ложно завершится с кодом 0. П0-CI получится одновременно опасным и ложно-зелёным. [План:80](/home/pakar/igor/remlab/.memory_bank/plans/catalog-load-hardening.md:80), [load3.py:25](/home/pakar/igor/remlab/tools/scout/load3.py:25), [feed_guard.py:115](/home/pakar/igor/remlab/tools/scout/feed_guard.py:115), [category_map.py:206](/home/pakar/igor/remlab/tools/scout/category_map.py:206). Это прямо повторяет анти-паттерны неизменяемых фикстур и module-level execution: [anti-patterns.md:555](/home/pakar/igor/remlab/.memory_bank/anti-patterns.md:555), [anti-patterns.md:598](/home/pakar/igor/remlab/.memory_bank/anti-patterns.md:598).

- **[блокер] П1.3 неверно расположен в жизненном цикле.** `refresh-status.json` записывается функцией `finish()` только при `EXIT`. Следовательно, шаг `status_publish` внутри основного тела либо отправит вчерашний файл, либо неполный. Публикация должна происходить внутри финализатора после атомарной записи JSON либо во внешней обёртке. [refresh_daily.sh:36](/home/pakar/igor/remlab/tools/scout/refresh_daily.sh:36), [refresh_daily.sh:52](/home/pakar/igor/remlab/tools/scout/refresh_daily.sh:52), [План:100](/home/pakar/igor/remlab/.memory_bank/plans/catalog-load-hardening.md:100).

- **[блокер] П1 не чинит код возврата `step()`.** В ветке ошибки последней выполняется успешный `echo`, поэтому функция возвращает 0. Из-за этого `step mesh_queue && step mesh_bind` продолжает цепочку после падения. Нужно сохранить `rc`, записать статус и `return "$rc"`. [refresh_daily.sh:31](/home/pakar/igor/remlab/tools/scout/refresh_daily.sh:31), [refresh_daily.sh:285](/home/pakar/igor/remlab/tools/scout/refresh_daily.sh:285).

- **[важно] Перед HD-бэкфиллом нужны миграция хеш-контракта и починка mesh binding.** Сейчас П2.2→П2.3 меняет выбранный источник картинки раньше, чем устранена ложная материальная готовность меша. Порядок внутри П2 должен быть: схема → эффективные хеши/baseline → строгая привязка ревизии → только затем HD-бэкфилл. [План:124](/home/pakar/igor/remlab/.memory_bank/plans/catalog-load-hardening.md:124), [mesh_bind.py:92](/home/pakar/igor/remlab/tools/scout/mesh_bind.py:92).

- **[блокер] `mesh_dims` должен идти после точной ориентации, а не просто после `mesh_bind`.** В текущем цикле `mesh_bind` выполняется до `orient_worker`; новая модель в тот же день ещё не имеет ориентации. После записи глубины нужен повторный `capabilities --build`, иначе capability-проекция продолжит жить со старой глубиной до следующего дня. [refresh_daily.sh:290](/home/pakar/igor/remlab/tools/scout/refresh_daily.sh:290), [refresh_daily.sh:299](/home/pakar/igor/remlab/tools/scout/refresh_daily.sh:299), [capabilities.py:255](/home/pakar/igor/remlab/tools/scout/capabilities.py:255).

- **[блокер] П3.5 не проводит MIXED-категорию через загрузчик.** `load3` отбрасывает оффер до индивидуальной классификации, если категория отсутствует в `_CATROLE`. Если `112923:334` останется с `role=null`, до `classify(name)` товар вообще не дойдёт. Кроме того, нынешний `category_map --apply` сначала зануляет все роли, а пропуск MIXED оставит их пустыми. [load3.py:100](/home/pakar/igor/remlab/tools/scout/load3.py:100), [category_map.py:182](/home/pakar/igor/remlab/tools/scout/category_map.py:182), [План:179](/home/pakar/igor/remlab/.memory_bank/plans/catalog-load-hardening.md:179).

- **[важно] Не закрыта атомарность загрузки.** Товары коммитятся отдельно от `product_enrichment`; падение между транзакциями оставляет новый `products` со вчерашними статусами и хешами. Сам аудит это уже признаёт, но плана исправления нет. [load3.py:169](/home/pakar/igor/remlab/tools/scout/load3.py:169), [load3.py:220](/home/pakar/igor/remlab/tools/scout/load3.py:220), [dialog:269](/home/pakar/igor/remlab/.memory_bank/_intake/owner/dialog-catalog-load-0309.md:269).

Рекомендуемый порядок:

1. Фикстуры без подключения к БД.
2. Выделение чистого парсера и настоящих selftest.
3. Подключение CI.
4. Починка `step()` и структурированного статуса.
5. Миграции хешей и строгой mesh-привязки.
6. Транзакционный импорт, поля фида и per-mid shrink.
7. Контролируемый HD-бэкфилл.
8. Размеры и категории.
9. API-эксперимент.
10. Документация.

## 2. П2.3 — HD-бэкфилл

- **[важно] Цепочка в плане сформулирована неточно.** Новый URL не обязательно означает новый `source_sha`: хеш считается по байтам. Правильная цепочка:

  `новый выбранный URL → повторное скачивание → SHA изменился? → да: старая ревизия не готова; нет: меш остаётся готов`.

  [cutout_sync.py:215](/home/pakar/igor/remlab/tools/scout/cutout_sync.py:215), [mesh_queue.py:399](/home/pakar/igor/remlab/tools/scout/mesh_queue.py:399), [mesh_ready.py:58](/home/pakar/igor/remlab/tools/scout/mesh_ready.py:58).

- **[блокер] Две волны через временный `HD_BACKFILL_SKIP_MESHED` неустойчивы.** Следующий обычный cron без флага заполнит пропущенные 58 строк сразу. Нужен либо отдельный одноразовый backfill-скрипт/таблица миграции со списком SKU, либо один честный прогон всех 58 после починки invalidation. [План:133](/home/pakar/igor/remlab/.memory_bank/plans/catalog-load-hardening.md:133).

- **[блокер] `products.mesh_status` останется ложно `ready`.** `mesh_ready()` увидит старый SHA и вернёт false, но `mesh_bind.bind_ready()` берёт просто самый свежий `model.glb` на диске и снова ставит `ready`, не проверяя его `source_sha`. Это два противоречащих источника готовности. [mesh_bind.py:95](/home/pakar/igor/remlab/tools/scout/mesh_bind.py:95), [mesh_bind.py:112](/home/pakar/igor/remlab/tools/scout/mesh_bind.py:112), [db/init/008-mesh-binding.sql:33](/home/pakar/igor/remlab/db/init/008-mesh-binding.sql:33).

- **[важно] `mesh_ready --coverage` недостаточно.** Он измеряет только сеты, но не ловит ложные `products.mesh_uri/status`, не гарантирует точный набор затронутых SKU и не показывает очередь cutout. Кроме того, ночью хешируется максимум 1000 новых источников, поэтому массовый HD-бэкфилл растянется примерно на 11–12 дней. [refresh_daily.sh:197](/home/pakar/igor/remlab/tools/scout/refresh_daily.sh:197), [cutout_sync.py:332](/home/pakar/igor/remlab/tools/scout/cutout_sync.py:332).

Более дешёвый и честный гейт:

1. Для 58 SKU заранее скачать обычное и HD-фото.
2. Сравнить точный SHA байтов.
3. Не затрагивать идентичные байты.
4. Для остальных атомарно обновить `product_photo_current`, очистить рабочий mesh-pointer и поставить новое задание.
5. Проверить инвариант: `products.mesh_status='ready'` допустим только при совпадении текущего SHA с выбранной ревизией.
6. Приоритетом поднять SKU из опубликованных сетов.

## 3. П2.5 — `attrs_hash`

- **[блокер] Список ключей не соответствует реальным входам обогащения.** Промпт использует `Назначение`, `Форма`, `Обивка`, `Материал каркаса`, которых в плане нет; напротив, часть перечисленного в плане в промпт не входит. Правила `rules0.extract()` вообще склеивают все параметры, поэтому изменение любого параметра способно поменять цвет, материал, форму или features. [golden_label.py:195](/home/pakar/igor/remlab/tools/scout/golden_label.py:195), [golden_label.py:205](/home/pakar/igor/remlab/tools/scout/golden_label.py:205), [rules0.py:73](/home/pakar/igor/remlab/tools/scout/rules0.py:73), [План:141](/home/pakar/igor/remlab/.memory_bank/plans/catalog-load-hardening.md:141).

  Контракт должен быть одним из двух:

  - хеш всего канонизированного `params`; либо
  - хеш точного union ключей, который экспортируется самими потребителями.

  Ручной третий список снова разойдётся.

- **[важно] Нужны нормализация и версия алгоритма:** trim/casefold имени ключа, нормализация `ё`, пробелов и `×/x/х`, `null` против пустой строки, сортировка ключей, алиасы `Коллекция` и `Серия`. Нужен `attrs_hash_version`; иначе расширение списка позже вызовет лавину повторного обогащения. [load3.py:107](/home/pakar/igor/remlab/tools/scout/load3.py:107).

- **[блокер] `enrichment_version=null` — плохая модель stale-состояния при `openai.off`.** `capabilities.py` перестаёт читать старый payload целиком, хотя большая его часть остаётся полезной. Изменение одного параметра превращается в потерю всех vision-признаков на неопределённое время. [load3.py:230](/home/pakar/igor/remlab/tools/scout/load3.py:230), [capabilities.py:255](/home/pakar/igor/remlab/tools/scout/capabilities.py:255), [refresh_daily.sh:18](/home/pakar/igor/remlab/tools/scout/refresh_daily.sh:18).

  Лучше хранить отдельно:

  - `enrichment_input_hash`;
  - `enrichment_status=current|stale|pending`;
  - последнюю успешную версию payload.

  `todo()` выбирает stale/pending, а capabilities продолжает использовать последний payload с provenance `stale`.

- **[важно] `text_hash` должен считаться по эффективному значению.** Если пустое описание фида не затирает старое описание, нельзя продолжать хешировать `name + feed_desc=null`: значение в `products` и его отпечаток разойдутся. Та же проблема уже существует для размеров, защищённых `scrape/manual`. [load3.py:44](/home/pakar/igor/remlab/tools/scout/load3.py:44), [load3.py:126](/home/pakar/igor/remlab/tools/scout/load3.py:126), [load3.py:179](/home/pakar/igor/remlab/tools/scout/load3.py:179), [План:136](/home/pakar/igor/remlab/.memory_bank/plans/catalog-load-hardening.md:136).

- **[важно] Нужны два разных image-контракта.** Для GPT сейчас используется обычный `image_url`, а cutout/mesh выбирает `coalesce(image_url_hd,image_url)`. Один `image_hash` не должен обозначать обе сущности. [rules0.py:145](/home/pakar/igor/remlab/tools/scout/rules0.py:145), [cutout_sync.py:221](/home/pakar/igor/remlab/tools/scout/cutout_sync.py:221).

## 4. П2.6 — shrink-гейт

- **[важно] 70% по `merchant_id` — разумный аварийный минимум, но это не статистическая норма.** Сравнивать нужно с последним успешным accepted-count этого mid, а не с текущим числом неархивных строк: после одного принудительного сокращения база сама станет новым пониженным baseline. Сейчас используется именно число строк БД. [load3.py:145](/home/pakar/igor/remlab/tools/scout/load3.py:145).

- **[важно] Нужны два счётчика:** raw offers по mid и accepted offers после карты категорий. Первый ловит урезанный фид, второй — поломку фильтра/таксономии. Иначе изменение `category-roles` неотличимо от сокращения ассортимента.

- **[блокер] После удаления shrunk-mid обязателен guard до любого SQL с `mlist`.** В плане это есть, но его надо поставить до создания staging/формирования всех `IN (...)`, а не только перед строкой 194. [План:144](/home/pakar/igor/remlab/.memory_bank/plans/catalog-load-hardening.md:144), [load3.py:158](/home/pakar/igor/remlab/tools/scout/load3.py:158), [load3.py:194](/home/pakar/igor/remlab/tools/scout/load3.py:194).

- **[важно] Единица карантина — `merchant_id`, не ZIP и не домен.** Несколько mid в одном фиде судятся независимо; несколько фидов одного mid должны сначала дедуплицироваться по `(mid, external_id)`. Иначе staging может содержать две строки одного PK, и PostgreSQL выдаст `ON CONFLICT DO UPDATE command cannot affect row a second time`. [load3.py:75](/home/pakar/igor/remlab/tools/scout/load3.py:75), [load3.py:171](/home/pakar/igor/remlab/tools/scout/load3.py:171).

- **[важно] Карантин freshness нельзя обходить через `FORCE_SHRINK`.** Broken/stale/empty источник уже правильно замораживается до парсинга. Force должен разрешать только известное уменьшение конкретного mid, а не возвращать в работу протухший источник. [load3.py:79](/home/pakar/igor/remlab/tools/scout/load3.py:79).

- **[мелочь] `FORCE_SHRINK=1|<mid,…>` двусмысленен.** Лучше `FORCE_SHRINK=all` либо строгий CSV mid; лог обязан записать пользователя/время/старое и новое число. Без причины override станет постоянной заплаткой.

Минимальные точки правки определены почти верно, но нужен постоянный ledger импорта: `run_id, feed, mid, raw_count, accepted_count, previous_success_count, verdict, forced`.

## 5. П3.4 — глубина из меша

- **[блокер] `mesh_ready()` недостаточен как гейт качества геометрии.** Он принимает `generated`, а ориентацию связывает с ревизией только по SKU. Комментарий ниже утверждает обратное, но SQL делает join через первый сегмент ключа. Старое решение ориентации может подтвердить новый меш. [mesh_ready.py:38](/home/pakar/igor/remlab/tools/scout/mesh_ready.py:38), [mesh_ready.py:50](/home/pakar/igor/remlab/tools/scout/mesh_ready.py:50), [mesh_ready.py:58](/home/pakar/igor/remlab/tools/scout/mesh_ready.py:58), [mesh_ready.py:69](/home/pakar/igor/remlab/tools/scout/mesh_ready.py:69).

  Для размеров нужен отдельный `mesh_geometry_eligible`: точное совпадение `asset_revision.glb_sha == orientation_state.resolution.glb_sha`, пройденный geometry/profile gate, отсутствие `unusable`, slab/flat-shape и неподтверждённых ремонтов.

- **[блокер] `dims_source='mesh'` на весь товар блокирует обновление всех осей фидом.** Текущий upsert защищает `dims_source` целиком. Если только глубина выведена из меша, позднее появившиеся измеренные ширина или глубина уже не доедут. Более того, измеренный фид должен быть сильнее mesh-инференса, а план предлагает обратное. [load3.py:182](/home/pakar/igor/remlab/tools/scout/load3.py:182), [План:173](/home/pakar/igor/remlab/.memory_bank/plans/catalog-load-hardening.md:173).

  Нужен authority по каждой оси в `dims_evidence`, например:

  `manual/scrape/feed_param > mesh_ratio > role_prior > assumed`.

- **[важно] Формула корректна только после точного R и на подходящих ролях.** `orientation_state.resolution` действительно содержит `R` и `glb_sha`, но ключ ориентации строится по SHA GLB, не по source SHA фотографии. [orient_worker.py:147](/home/pakar/igor/remlab/tools/scout/orient_worker.py:147), [orient_worker.py:233](/home/pakar/igor/remlab/tools/scout/orient_worker.py:233).

- **[блокер] Калибровка только на 61 диване не разрешает запись для других ролей.** Даже для диванов выборка смещена: это товары с полным паспортом и уже годным мешом, тогда как целевая популяция — магазины без глубины. Угловые/модульные диваны, разложенная мебель и свободные подушки должны быть отдельными стратами либо исключены.

- **[важно] Порог “80% в ±10%” слишком слаб для планировки.** Он допускает примерно 12 из 61 дивана с произвольно большой ошибкой. Нужны как минимум median APE, P90, максимальная недооценка и доля gross error >20%. Недооценка глубины опаснее переоценки, поэтому её надо считать отдельно.

- **[важно] Если известны ширина и высота, используйте обе как проверку, не выбирайте одну молча.** Рассчитать `s_w=w/ext_w`, `s_h=h/ext_h`; если они расходятся сильнее откалиброванного допуска, глубину не выводить. При единственной известной высоте — не включать без отдельной ролевой калибровки.

Провенанс должен содержать `source=mesh_ratio`, reference axis/value, raw extents, `glb_sha`, revision key, orientation key/version, роль, версию формулы и confidence. При смене меша или ориентации значение становится stale и пересчитывается.

## 6. `WARN`, дайджест и сторож

- **[блокер] `tee` без сохранения `PIPESTATUS[0]` превратит падение команды в успех `tee`.** В скрипте нет `set -o pipefail`. Лучше явно сохранить rc команды либо использовать временный файл без pipeline. [refresh_daily.sh:10](/home/pakar/igor/remlab/tools/scout/refresh_daily.sh:10), [План:96](/home/pakar/igor/remlab/.memory_bank/plans/catalog-load-hardening.md:96).

- **[важно] Одного префикса `WARN:` мало.** Нужен формат `WARN:<code>:<однострочный текст>`, массив предупреждений и счётчик на шаг. Иначе несколько строк нельзя надёжно поместить в JSON/Telegram, а длинный вывод превысит лимит сообщения. JSON следует собирать Python/jq, не ручным `printf`. [refresh_daily.sh:38](/home/pakar/igor/remlab/tools/scout/refresh_daily.sh:38).

- **[важно] Сейчас большинство проблем feed_guard не печатают `WARN:`.** Broken/empty/stale вызывают `alert.sh`, но stdout остаётся обычным текстом, поэтому новый `step()` отметит их `ok`. Нужно привести все предупреждающие ветки к одному контракту. [feed_guard.py:74](/home/pakar/igor/remlab/tools/scout/feed_guard.py:74), [feed_guard.py:97](/home/pakar/igor/remlab/tools/scout/feed_guard.py:97), [feed_guard.py:106](/home/pakar/igor/remlab/tools/scout/feed_guard.py:106).

- **[важно] Прод-сторож должен проверять `overall_status`, а не только дату/finished.** Иначе локальный Telegram может не отправиться, удалённый сторож увидит завершённый файл и промолчит о FAIL. В статус добавить `started_at`, `finished_at` с timezone, `overall`, `exit_code`, host и git SHA.

- **[важно] `OnCalendar=15:30` означает timezone сервера, не обязательно UTC.** Нужен явный суффикс `UTC`; существующий шаблон timezone не фиксирует. [remlab-watchdog.timer:4](/home/pakar/igor/remlab/infra/server/systemd/remlab-watchdog.timer:4), [План:103](/home/pakar/igor/remlab/.memory_bank/plans/catalog-load-hardening.md:103).

- **[важно] Публиковать надо атомарно:** локальный `.tmp → rename`, затем SCP во временный remote-файл и remote `mv`. Сам watchdog находится на проде, поэтому пусть читает локальный `/opt/remlab/test/status/refresh-status.json`, а не HTTP с возможным кэшем. Права технически решаемы: существующая публикация уже работает через root SSH. [publish_demo.sh:9](/home/pakar/igor/remlab/tools/scout/publish_demo.sh:9), [publish_demo.sh:18](/home/pakar/igor/remlab/tools/scout/publish_demo.sh:18).

## 7. Лишнее и пропущенное

### Критически пропущено

- **[блокер] Единая транзакция или возобновляемый staging для `products + product_enrichment + reconcile`.**
- **[блокер] Очистка stale `products.mesh_uri/status` при смене source SHA.**
- **[блокер] Точный join ориентации по `glb_sha`, а не по SKU.**
- **[важно] Per-axis authority размеров вместо общего `dims_source`.**
- **[важно] Run-ledger импорта с последним успешным baseline по mid.**
- **[важно] Дедупликация `(shop_mid, external_id)` до upsert.**
- **[важно] Защита `category_map --apply`: транзакция, проверка return code и blast-radius до записи.** Сейчас `subprocess.run` не проверяется, а сначала зануляются все роли. [category_map.py:182](/home/pakar/igor/remlab/tools/scout/category_map.py:182).
- **[важно] Freshness API-данных.** `catalog_api_sync` глотает сетевые ошибки по словам и всё равно успешно завершает магазин; старые `api_offers` не помечаются отсутствующими. Недельный `charge` может оказаться частичным или протухшим при статусе `ok`. [catalog_api_sync.py:103](/home/pakar/igor/remlab/tools/scout/catalog_api_sync.py:103), [catalog_api_sync.py:127](/home/pakar/igor/remlab/tools/scout/catalog_api_sync.py:127).

### Лишнее или преждевременное

- **[мелочь] Ежедневный success-дайджест в Telegram** быстро создаст alert fatigue. Удалённый watchdog должен ловить отсутствие/FAIL; Telegram успеха лучше сделать настраиваемым.
- **[мелочь] Три ADR для одного hardening-пакета** избыточны. Достаточно одного ADR про authority/жизненный цикл плюс таблицы поля→источник в `core/catalog.md`.
- **[мелочь] Публикация плана и списка 155 товаров отдельными публичными страницами** не влияет на безопасность кода; можно выполнить после блокеров.
- **[важно] П4 нельзя документировать как “API — источник наличия”.** Сам план называет это ещё непроверенной гипотезой. Для редкого `available=false` нужна стратифицированная выборка и precision отрицательного сигнала, а не общая accuracy 95%. [План:193](/home/pakar/igor/remlab/.memory_bank/plans/catalog-load-hardening.md:193), [План:203](/home/pakar/igor/remlab/.memory_bank/plans/catalog-load-hardening.md:203).

## Изменить в плане до начала кода

1. Перенести CI после выделения чистых parser/selftest; запретить тестам dev-БД.
2. Починить возврат `step()` и описать `WARN:<code>` как структурированный контракт.
3. Финализировать и атомарно публиковать статус из `EXIT`-финализатора; сторож проверяет `overall`.
4. Объединить запись products/enrichment/status в транзакцию и добавить per-mid run-ledger.
5. Определить effective hashes, `attrs_hash_version` и отдельное stale-состояние enrichment.
6. До HD-бэкфилла исправить materialized mesh binding и строгую привязку к source SHA.
7. Заменить временный двухволновый env-гейт на явную миграционную очередь/allowlist.
8. Сделать shrink per-mid по последнему успешному baseline, с dedupe и строгим FORCE.
9. Для mesh-depth ввести точный join по GLB, geometry gate и per-axis provenance; начать только с прямых диванов.
10. Дописать специальный путь MIXED через `load3` и безопасный транзакционный `category_map --apply`.

## Можно начинать как есть

- Создание `.env.alert` с `chmod 600` и `alert.sh --dry-run`.
- Фиксация неизменяемых XML/JSON-фикстур, пока они не подключаются к живым скриптам.
- Сдвиг cron на 10:40 UTC.
- Исправление timezone и чтения `merchant_id` в `feed_guard`.
- Исправление порядка импортов `asset_strategy`, но с проверкой конечного инварианта `sys.path[0] == HERE`.
- Чистый парсинг `merchant_id`, `article`, `original_picture` и нормализация `//`.
- Fixture-first расширение `dim_resolver` для tvoydom/штор/`Д×Ш×В`.
- П4 как исключительно read-only исследование, без влияния на `in_stock`.