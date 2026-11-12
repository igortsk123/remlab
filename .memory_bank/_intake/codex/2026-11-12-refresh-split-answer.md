1. Граница

- Цепочка `mesh_family_early → mesh_bind_early → bank_prepare → bank_pending → bank_promote` разделена логично; этот порядок уже защищён тестом: `tools/scout/refresh_daily.sh:479`, `tools/scout/refresh_daily.sh:495`, `tools/scout/tests_refresh_order.py:170`.
- Но фактическая утренняя часть уже меняет живой банк: при текущем `write_enabled=false` выполняются `bank_media --apply`, `sets_heal`, `sets_contracts`, затем `set_ids --apply` и публикация страниц: `tools/scout/rules/bank-candidate.json:26`, `tools/scout/refresh_daily.sh:410`, `tools/scout/refresh_daily.sh:419`, `tools/scout/refresh_daily.sh:439`, `tools/scout/refresh_daily.sh:445`. Демо публикуется лишь вечером: `tools/scout/refresh_daily.sh:602`, `tools/scout/refresh_daily.sh:622`. Значит, несогласованное окно действительно растягивается на ~3,5 ч.
- Перенести в вечер минимум `sets_index/sets_check`, `bank_media/bank_photos`, heal/contracts и весь `bank_index_steps`; общие `health/metrics/stock_audit` можно оставить утром: `tools/scout/refresh_daily.sh:380`, `tools/scout/refresh_daily.sh:398`, `tools/scout/refresh_daily.sh:433`.
- Ранний `demo_band` не является полностью свежим спросом: он намеренно читает вчерашнее опубликованное демо, а кандидат — сохранённый прошлый `bank-pending`: `tools/scout/demo_band.py:19`, `tools/scout/bank_pending.py:330`. Это допустимая оценка, но не `mesh-demand-ready`.

2. Два запуска

- Проверки меток/`auto` должны происходить после взятия общего lock: сейчас дневная метка проверяется до `flock`, то есть гонка cron–`@reboot` уже возможна: `tools/scout/refresh_daily.sh:25`, `tools/scout/refresh_daily.sh:33`.
- После `flock -w 7200` надо повторно проверить maintenance pause. Сейчас `maint_gate` выполняется раньше refresh-lock и держит shared-lock; пауза, поставленная во время ожидания, иначе не остановит вечер: `tools/scout/refresh_daily.sh:28`, `tools/ops/maintenance.sh:44`, `tools/ops/maintenance.sh:47`.
- Таймаут lock требует явного статуса/алерта: нынешний ранний выход происходит до установки `trap finish`: `tools/scout/refresh_daily.sh:34`, `tools/scout/refresh_daily.sh:146`.
- `@reboot auto` должен учитывать время: до 10:40 нельзя помечать утро сегодняшним числом, иначе штатный cron пропустится. Кроме того, в репозиторном crontab `@reboot` сейчас вообще отсутствует: `infra/dev/crontab:3`.
- Утверждение «вечер ≤21:30» слабое: уже есть незавершённый замер ≥130 мин, а разрешённое ожидание lock ещё 120 мин — 22:30 может быть штатным ложным алертом: `.memory_bank/plans/refresh-split-01.md:40`, `.memory_bank/plans/refresh-split-01.md:86`.
- `nightly_exam` не разделяет refresh-lock: у него только `exam.flock`; refresh проверяет `exam.lock` лишь вокруг банков. При очень позднем вечере возможен параллельный экзамен после этого блока: `tools/scout/run.sh:27`, `tools/scout/refresh_daily.sh:405`.
- `wave_guard` общего lock не видит — только свои два lock-файла, поэтому вечерний `mesh_queue/mesh_schedule` эту гонку не решает: `tools/scout/salad/wave_guard.py:52`, `tools/scout/salad/wave_guard.py:207`.
- `tests_chain.live_guards_scheduled` два refresh-запуска не проверяет — ищет только четыре имени сторожей. Нужен отдельный тест расписания: `tools/scout/tests_chain.py:204`, `tools/scout/tests_chain.py:210`.
- Для двух watchdog-таймеров нужен явный аргумент `morning|evening`/template-service. Одна service сейчас запускает скрипт без аргументов; определять режим по часам нельзя при `Persistent=true`: `infra/server/systemd/remlab-catalog-watchdog.service:4`, `infra/server/systemd/remlab-catalog-watchdog.timer:6`.

3. Если утра не было

- По умолчанию — пропускать мутирующие банки и публикацию демо, оставляя вчерашний прод. Отсутствие метки неоднозначно: утро могло частично записать БД или живой банк, а не просто «не запускаться»: `tools/scout/refresh_daily.sh:250`, `tools/scout/refresh_daily.sh:410`.
- `BANK_RUN_ID` защищает от чужого кандидата, но не доказывает свежесть/целостность каталога: `tools/scout/bank_run.py:4`, `tools/scout/bank_run.py:85`.
- Маркер утра должен быть атомарным и содержать дату, SHA кода, начало/конец и результаты обязательных шагов. Гейтовать по `overall=ok` нельзя: план фиксирует почти ежедневные некритические FAIL; нужен список обязательных зависимостей: `.memory_bank/plans/refresh-split-01.md:56`.
- Stale-run допустим только отдельным явным флагом после доказательства, что сегодняшнее утро вообще не начиналось.

4. Спрос и `wave_guard`

- С жёстким ожиданием нынешней поздней метки не согласовывать: окно batch действительно заканчивается в 15:00: `infra/dev/crontab:7`, `tools/scout/rules/salad-groups.json:151`.
- Лучше назвать раннюю метку `catalog-ready`, писать поколения входов и считать `demo_band` утренней оценкой на вчерашнем демо. Канонический `demo-band.json` утром лучше не перезаписывать либо использовать отдельный файл: `tools/scout/demo_band.py:423`.
- Сам ранний `demo_band --report` волну не фиксирует: `wave_guard` затем снова запускает `mesh_priority`, который пересчитывает `demo_band.queue()` и читает текущий `bank_pending`: `tools/scout/salad/wave_guard.py:80`, `tools/scout/mesh_priority.py:158`, `tools/scout/mesh_priority.py:166`.
- `bank_pending` отдельно утром не переносить: он требует `bank_prepare` того же `run_id` и паспорта кандидата. Расщепление этой цепочки — отдельная, существенно более сложная задача: `tools/scout/bank_pending.py:384`, `tools/scout/bank_pending.py:393`.

5. До переноса

- Дождаться двух дней `STEPTIME --cpu`: вывод «процессор почти не нужен» пока не доказан — план сам говорит, что CPU/память восстановить нельзя: `.memory_bank/plans/refresh-split-01.md:43`, `.memory_bank/plans/refresh-split-01.md:48`.
- Сделать атомарный версионированный handoff утра и отдельный лог/диапазон строк каждой части. Сейчас дайджест читает общий журнал от первой строки сегодняшнего дня и смешает повторные запуски: `tools/scout/refresh_digest.py:58`.
- В приёмку добавить гонки cron–`@reboot`, pause во время ожидания lock, timeout, смену git SHA между частями и пересечение с `nightly_exam`.
- Лишнее в первом релизе: изменение `tests_chain.live_guards_scheduled`, двойная запись канонического `demo_band` и сложный `auto` без временной модели.

**Вердикт: годен с правками — перенести все писатели банка в вечер; без валидного утреннего handoff вечер по умолчанию пропускать; закрыть гонки lock/pause/auto/watchdog/nightly и считать ранний спрос оценкой, а не готовностью.**