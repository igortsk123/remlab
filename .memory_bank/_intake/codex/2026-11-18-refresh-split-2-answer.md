**Вердикт:** полный split я бы сейчас не делал. Выбрал бы вариант **(а)**: отдельно вынести понедельничный `solver_full`, затем отдельно решить судьбу `resolve_affected`; параллель (б) — после проверки на копии БД. Цена (в) непропорциональна фактической нагрузке.

### 1. Разрез и зависимости

- Числа в целом верны, но медиана полного прогона — **338**, не 332 мин; `stock_check` иногда идёт 174,6 мин, а не строго 150. `.memory_bank/plans/refresh-split-01.md:29-38`, `.memory_bank/plans/refresh-split-01.md:53`
- Формулировка границы противоречива: `sets_index/sets_check` находятся до `stock_audit`, но план относит их к вечеру. Выберите одно; я оставил бы их утром как подготовленный артефакт для вечернего лечения. `tools/scout/refresh_daily.sh:394-408`, `.memory_bank/plans/refresh-split-01.md:153-158`
- Пропущен настоящий утренний писатель живого банка: `sync_metrics.py` безусловно перезаписывает `sets3.json`. Значит, для утра «без изменений банка» шаг `metrics` тоже надо переносить в вечер. `tools/scout/refresh_daily.sh:405`, `tools/scout/sync_metrics.py:27-63`
- `mesh_family_early` утром на вчерашнем `sets3.json` не полностью безопасен: членство в банке участвует в выборе представителя новой семьи, а выбранный представитель затем становится липким. `tools/scout/mesh_family.py:67-71`, `tools/scout/mesh_family.py:268-286`
- Поздний блок выполняет только `mesh_bind`, но не пересчитывает семейства; ошибочный утренний выбор вечером не исправится. `tools/scout/refresh_daily.sh:710-719`
- Поэтому `mesh_family_early/mesh_bind_early` лучше оставить в исходном месте — вечером после писателей банка. Для волн утреннее выполнение всё равно не нужно: старт волны сам запускает `mesh_family --fill` и `mesh_bind`. `tools/scout/refresh_daily.sh:473-494`, `tools/scout/mesh_wave_start.sh:91-95`
- Ещё один пропущенный писатель: по понедельникам `sets_refresh/sets_pairs_w --apply` меняют банк уже **после публикации демо**. Это существующее рассогласование банк↔демо, которое split сохранит. `tools/scout/refresh_daily.sh:651-678`, `tools/scout/refresh_daily.sh:682-693`

### 2. Что выбрать

- Перенос 58 CPU-мин звучит крупно, но это медианно 0,24 ядра из 15; память и heavy-slot не были ограничением. Полный split покупает главным образом другое время публикации, а не ёмкость DEV. `.memory_bank/plans/refresh-split-01.md:40-45`
- Сначала вынес бы `solver_full` отдельным понедельничным заданием: это изолированные 64 CPU-мин и почти весь недельный всплеск. `tools/scout/refresh_daily.sh:680-696`, `.memory_bank/plans/refresh-split-01.md:62`
- `resolve_affected` нельзя переносить один: за ним связаны страницы и `layout_page`; переносить надо весь хвост `bank_index_steps` либо ограничить ему CPU/nice. `tools/scout/refresh_daily.sh:447-470`
- Параллель `catalog_api ‖ stock_check` правдоподобна: они обновляют разные поля, а финальные записи происходят в разные моменты. Но нужен тест блокировок PostgreSQL и отдельный parallel-helper — текущий `step()`/`RES` не поддерживает фоновые дочерние shell. `tools/scout/catalog_api_sync.py:181-212`, `tools/scout/stock_truth.py:223-236`, `tools/scout/refresh_daily.sh:66-89`

### 3. Метки, падения, `force`

- Утренний handoff нельзя гейтовать условием `stock_check=ok`: он дал `rc=1` все шесть дней. Используйте `stock_audit=ok` плюс явные показатели полноты/карантина самого обхода. `.memory_bank/plans/refresh-split-01.md:53`, `tools/scout/stock_check.py:712-750`, `tools/scout/refresh_daily.sh:406-408`
- `refresh-morning.json` должен иметь `schema_version`, дату, attempt-id, start/end, `complete`, exit code, SHA **и хеш самого скрипта**, все `RES/WARN*`, поколения/идентификаторы `load3` и каталога, а также вычисленные `ready_for_bank` и `ready_for_demo` с причинами. `tools/scout/refresh_daily.sh:121-131`
- Отдельно нужен атомарный статус «morning started». Иначе отсутствие финального JSON не отличает «не запускалось» от «упало после частичных записей». `tools/scout/refresh_daily.sh:161-176`
- Вечер при отсутствующем/битом/неполном handoff должен завершаться fail-closed до писателей и публикаций. Автоматически считать вчерашний каталог допустимым нельзя. `tools/scout/refresh_daily.sh:417-469`, `tools/scout/refresh_daily.sh:602-659`
- `--force` должен игнорировать только метку выбранной части; валидность handoff он обходить не должен. Для аварийного stale-run нужен другой, громкий ключ. `tools/scout/refresh_daily.sh:25`
- Если вечер держит lock до следующих 10:40, утро обязано записать статус `blocked_by_previous_evening` и немедленно алертить; тихий `flock -n` здесь означает потерянный день. `tools/scout/refresh_daily.sh:33-34`

### 4. Сводка и watchdog

- Текущий `finish()` утром использовать нельзя: любой `FAIL` делает общий статус FAIL и почти неизбежно вызывает `alert.sh`. Нужны разные `finish_morning` и `finish_evening`. `tools/scout/refresh_digest.py:76-80`, `tools/scout/refresh_daily.sh:145-152`
- Утро: локальный handoff + отдельный `refresh-morning-status.json`; сообщение только если `ready_for_evening=false`. Вечер: подмешивает утренние результаты и один раз строит обычный digest. `tools/scout/refresh_daily.sh:121-144`
- Watchdog лучше направить на два разных файла, а не перезаписывать один: текущий сторож не знает `part` и считает любой сегодняшний finished достаточным. `infra/server/scripts/catalog-watchdog.sh:22-31`, `infra/server/scripts/catalog-watchdog.sh:69-75`
- Утренний watchdog проверяет `complete/ready_for_evening`; вечерний — финальный `refresh-status.json`. `running` каждой части должен содержать `part` и attempt-id. `tools/scout/refresh_daily.sh:116-120`

### 5. Соседи и замки

- Общий короткий lock семейство→привязка→снимок очереди нужен: иначе очередь может строиться между двумя состояниями таблиц. `tools/scout/mesh_wave_start.sh:91-95`, `tools/scout/mesh_wave_start.sh:114-138`
- Но брать его только в refresh и `mesh_wave_start` недостаточно: `mesh_bind.py` вызывают также `sink_keeper`, `ssh_run` и `batch_show`. Замок должен обеспечиваться общей обёрткой/самим writer-кодом. `tools/scout/salad/sink_keeper.sh:87`, `tools/scout/salad/ssh_run.py:365`, `tools/scout/salad/batch_show.py:634`
- `exam.lock` — TOCTOU-проверка, а не взаимное исключение. Для банков нужен настоящий `exam.flock`: экзамен exclusive, писатели банка — совместимый договорный lock. `tools/scout/run.sh:27-34`, `tools/scout/refresh_daily.sh:419-446`

### 6. Теневой прогон и тесты

- Единого dry-run нет. `mesh_publish` имеет `--dry`, `demo_warm` — `DRY=1`, `tour_reissue` — `--dry-run`; остальные публикации надо явно отключать. `tools/scout/mesh_publish.py:164-217`, `tools/ops/demo-warm.mjs:322-368`, `tools/ops/tour-reissue.sh:37-44`
- Список прод-писателей неполон: ещё пишут `orient_pull/orient_sync`, `tour_reissue`, `demo_warm`, `pipeline_map` и `book_page`. `tools/scout/orient_review.py:249-269`, `tools/scout/orient_review.py:115-136`, `tools/scout/refresh_daily.sh:651-652`, `tools/scout/pipeline_map.py:279-282`, `tools/book-build.py:137-140`
- Нужен оркестраторский `--shadow`: локальные target для статуса, убрать `--publish`, `LAYOUT10_PUBLISH=0`, `mesh_publish --dry`, `DRY=1`, не запускать push/sync/reissue. Просто закрыть сеть — это проверит аварийный, а не успешный путь. `tools/scout/refresh_daily.sh:102-109`, `tools/scout/refresh_daily.sh:459-469`
- `tests_refresh_order.py` сейчас начинает хвост с `sets_index`, заранее подставляет два `RES` и не тестирует CLI, handoff, lock или `finish`. `tools/scout/tests_refresh_order.py:25-34`
- `test_refresh_steptime.py` извлекает только две функции; нужны сценарии: union частей = `all`, crash утра, stale/malformed handoff, `--force`, auto по времени, lock timeout, pause после ожидания, один digest и ноль прод-команд в shadow. `tools/scout/tests/test_refresh_steptime.py:33-47`, `tools/scout/tests/test_refresh_steptime.py:93-96`