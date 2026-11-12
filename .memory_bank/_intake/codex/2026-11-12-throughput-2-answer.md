### А — единый интегратор

**Да — как централизованный gate; нет — как один Claude, вручную выполняющий всё подряд.** Выигрыш: полные наборы запускаются один раз на совместном результате, директор перестаёт cherry-pick’ать, а `main` всегда соответствует проверенному SHA. Риски ручного интегратора: очередь встаёт вместе с ним, теряется контекст автора, чужой или flaky-тест ошибочно обвиняет последнюю ветку.

Порядок внедрения:

1. Ввести очередь веток и обязательный пакет от автора: SHA, затронутые области, лёгкие проверки, риск/миграции.
2. Интегратор пока только формирует synthetic merge и запускает проверки; вливание остаётся ручным.
3. Автоматизировать: батч 2–4 ветки либо окно 10–15 минут → один полный прогон. При падении: сначала проверить чистый `main`, затем делить батч пополам. Автору возвращать ветку и полный лог.
4. После недели статистики разрешить автоматическое вливание **ровно проверенного merge-SHA**.

На 16 ядрах/29 ГБ реалистична одна локальная тяжёлая полоса: Playwright/WebGL либо экзамен банка, не параллельно. Остальные проверки — GitHub jobs. Интегратор управляет очередью и разбирает неоднозначности; скрипт выполняет merge/bisect/report.

### Б — refresh и Salad

Перенос всего refresh на 20:00 **нельзя**. Фид действительно ожидается к 10:40 ([ADR:587](/home/pakar/igor/remlab/.memory_bank/decisions/adr-0151-0200.md:587)), окно Salad — 09:00–15:00 ([crontab:3](/home/pakar/igor/remlab/infra/dev/crontab:3)).

Сам `refresh_daily` волну не запускает: блок только строит БД/экспорт и прямо говорит «генераций здесь нет» ([refresh_daily.sh:638](/home/pakar/igor/remlab/tools/scout/refresh_daily.sh:638)). Запускает независимый `wave_guard` каждые 15 минут ([wave_guard.py:21](/home/pakar/igor/remlab/tools/scout/salad/wave_guard.py:21), [wave_guard.py:245](/home/pakar/igor/remlab/tools/scout/salad/wave_guard.py:245)). Но он читает текущий demo-спрос, поэтому вечерний refresh оставит свежий каталог без волн до следующего дня. Более того, нынешний цикл 11 ноября завершился лишь в 16:36 ([refresh.log:175911](/home/pakar/igor/remlab/tools/scout/refresh.log:175911)).

Разделить:

- **10:40:** фиды/load/catalog, проверки наличия и фото, capabilities/candidates; затем `mesh_family`/`mesh_bind` ([450–451](/home/pakar/igor/remlab/tools/scout/refresh_daily.sh:450)) и ранний `demo_band` ([552](/home/pakar/igor/remlab/tools/scout/refresh_daily.sh:552)) по последним годным банкам. После успешного checkpoint разрешать `wave_guard`.
- **18:30, не 20:00:** сборка/экзамены банков ([464–552](/home/pakar/igor/remlab/tools/scout/refresh_daily.sh:464)), demo/PageCheck/runtime-меши/demo-real/pубликация ([569–614](/home/pakar/igor/remlab/tools/scout/refresh_daily.sh:569)), weekly solver/backup ([616–632](/home/pakar/igor/remlab/tools/scout/refresh_daily.sh:616)).

Днём CPU грузят прежде всего DB-индексы, candidates/reindex, сборщики и солверы; `stock_check`, 25+10 минут фото и API в основном сетевые.

### Сделать сегодня

- Не менять cron 10:40.
- Включить shadow merge-queue без автослияния.
- Ограничить локальные тяжёлые прогоны одной полосой.
- Добавить длительности шагов refresh и дневной `mesh-demand-ready` marker.
- Спроектировать два отдельных статуса/stamp, не разрезая текущий скрипт вслепую.