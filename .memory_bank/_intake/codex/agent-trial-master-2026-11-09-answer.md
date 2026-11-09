Короткий вердикт: направление верное, но сейчас план недооценивает не фото, а три вещи: слепую надёжность геометрии, runtime-загрузку новой квартиры без билда и изоляцию публичных заданий от живого DEV-демо. «Полный результат ≤3 мин» пока нельзя обещать как SLA.

1. Риски и порядок

- `T7 E2E` стоит слишком поздно. Нужен ранний вертикальный срез: `upload → job → серый runtime-тур → статус`, ещё до товаров и фото. Сейчас новая квартира требует билда/реестра — это блокер критического пути ([инвентаризация](/home/pakar/igor/remlab/.memory_bank/_intake/agent-trial-pipeline-inventory-2026-11-09.md:24)).
- `T3` зависит не только от лендинга, но и от runtime-контракта результата T2. Иначе очередь будет принимать задания, которые нечем показать.
- Волну кроватей начать в T0 параллельно, а не после лендинга: спальня заявлена в v1, но кроватей нет вообще ([инвентаризация](/home/pakar/igor/remlab/.memory_bank/_intake/agent-trial-pipeline-inventory-2026-11-09.md:31)).
- D–G неоднородны: ферма с 23 постройками и PDF на 7 листов — хороший stress-test, но плохой единый критерий v1 ([стенд](/home/pakar/igor/remlab/.memory_bank/plans/floorplan-raster-bench-01.md:129)). Сначала зафиксировать supported envelope: например, одна квартира, ≤2 этажей, ≤12 комнат, без пристроек/участка; F/G оставить стресс-набором.
- При отказе VLM нужен продуктовый путь: один повтор на другом crop → размеры из текста объявления → просьба агенту ввести одну известную длину. Если масштаб всё равно не подтверждён — серый тур с `Scale not verified`, но без мебели и цен.
- Упущены: лимиты/429 внешних моделей, повреждённые и огромные PDF, повтор одного задания после таймаута, приватность и срок удаления планов/email, отмена задания, частичный результат, недоступность DEV и устаревший worker.
- Рекомендуемый порядок:  
  `границы v1 + слепой gate` ∥ `кровати` ∥ `job/runtime JSON` → `upload→серый тур` → `гостиная` → `спальня при готовности мешей` → `один hero-photo` → `лендинг publish` → расширение фото/комнат.

2. Очередь

Для текущей архитектуры надёжнее Postgres, не Inngest: БД и Drizzle уже есть, а Inngest не подключён и всё равно не решит дефицит CPU/RAM на DEV ([architecture](/home/pakar/igor/remlab/.memory_bank/core/architecture.md:48)).

Минимальная надёжная схема:

- `jobs`: `status`, `stage`, `attempt`, `next_run_at`, `lease_until`, `worker_id`, `input_hash`, `budget`, `error_code`, `result_version`.
- Захват через `FOR UPDATE SKIP LOCKED`; lease + heartbeat; просроченный lease возвращает задание в очередь.
- Каждый этап идемпотентен, артефакты адресуются `job_id/stage_version`; письмо — отдельный outbox.
- `LISTEN/NOTIFY` только ускоряет пробуждение. Источник истины — polling раз в 1–3 секунды: соединение `LISTEN` через туннель может незаметно отвалиться.
- Лучше не давать DEV широкий доступ к prod-БД: prod хранит таблицу, DEV забирает задания через HTTPS `claim/heartbeat/result` с machine token — паттерн такого моста в проекте уже есть.

Чтобы не уронить демо:

- публичный CPU-тяжёлый этап — concurrency 1;
- запускать через существующий `heavy_slot`, но с отдельным приоритетом;
- systemd/cgroup: `MemoryMax`, `CPUQuota`, высокий `Nice`, `OOMScoreAdjust` хуже, чем у рендера;
- circuit breaker: при плохом `/health`, недостатке RAM или длинной очереди не брать новое задание;
- внешний VLM и ожидание image API не должны удерживать CPU-слот;
- максимум два параллельных фото, для v1 лучше одно.

3. Формат квартиры

Полигоны хранить сразу как канон, прямоугольник оставить совместимой проекцией. Поле `contour` уже есть в контракте, вместе с обязательным bbox `x/y/w/d` ([apartment.ts](/home/pakar/igor/remlab/contracts/apartment.ts:41)); то есть новая миграция формата для самого контура не нужна.

Практически:

- 3D читает настоящий полигон; bbox используется старым UI, камерой и индексами.
- В Python-солвер передавать контур в локальных координатах комнаты: TS хранит координаты квартиры, Python — `0..width/depth`.
- Осевые Г/П-контуры солвер уже частично поддерживает; косые рёбра пока пропускает, кухня полигон прямо отвергает ([models.py](/home/pakar/igor/remlab/services/planner-solver/planner/models.py:56), [kitchen.py](/home/pakar/igor/remlab/services/planner-solver/planner/kitchen.py:409)).
- Фолбэк решателя — не bbox: он может поставить диван за пределами комнаты. Использовать максимальный вписанный прямоугольник/ортогональную декомпозицию и ставить `layoutApproximate=true`.
- Следующий контрактный долг — проёмы: `north/south/east/west` недостаточно для произвольного полигона. Добавить совместимое optional `edgeId + offsetCm`, сохранив `wall` для прямоугольников.

4. Товары и AI-фото

Маску «рубли ×1,5 → GBP» лучше вообще не показывать публично: такая цена не является проверяемой indicative price. До UK-каталога:

- карточка: `Demo catalogue item · not currently offered for purchase in the UK`;
- показывать тип, размеры, цвет и роль в интерьере;
- убрать магазин, stock, Buy, сравнение цен и конкретную GBP-цену;
- общий ярлык рядом с карточками, не в футере: `Illustrative demo products. UK retailer availability and prices are not yet connected.`
- AI-кадр: постоянный бейдж `AI-generated visualisation — not a photograph`; экспорт по умолчанию с тем же бейджем.
- Если геометрия/масштаб не подтверждены: `Automatically interpreted floor plan — verify flagged dimensions before marketing use.`

CAP оценивает общий эффект текста и изображения; важное ограничение должно быть заметно рядом с утверждением, а мелкий disclaimer не исправляет противоречащее обещание ([ASA/CAP](https://www.asa.org.uk/advice-online/claims-that-require-qualification.html)). DMCC consumer rules действуют с 6 апреля 2025 года и запрещают misleading actions/omissions; формально агент, действующий в бизнесе, не “consumer”, но его итоговый листинг и товарные предложения уже увидит потребитель ([DMCC Act](https://www.legislation.gov.uk/ukpga/2024/13/2024-05-24?view=extent), [CMA guidance](https://www.gov.uk/government/publications/unfair-commercial-practices-cma207/unfair-commercial-practices)). Это не юридическое заключение, но безопасный продуктовый минимум.

5. Три минуты

Реалистично:

- серый 3D — да, цель p95 60–90 с;
- обставленные поддерживаемые комнаты — возможно p50 до 2 мин;
- все AI-фото за 3 мин — только удачный тёплый прогон, не p95.

Уже измеренный путь даёт 60–90 с до контракта и ещё 80–110 с до фото; оценка самого инвентаря — 2,5–3,5 мин при хорошем железе, не текущем туннеле DEV ([инвентаризация](/home/pakar/igor/remlab/.memory_bank/_intake/agent-trial-pipeline-inventory-2026-11-09.md:41)).

Заранее считать и греть:

- наборы `room kind × style × area/aspect band × opening signature`;
- кровати и top-GLB, но не генерировать меши на запрос;
- Python/OpenCV/Shapely-процесс, PDF renderer, browser/render worker, DB pool;
- VLM-ответ и PDF raster по hash;
- типовые product-role packs; точную посадку всё равно считать по фактическому контуру.

Из v1 вырезать:

- кухни, санузлы, прихожие;
- выбор/замену конкретного товара;
- магазины и GBP-цены;
- фото каждой комнаты — оставить один hero-photo гостиной;
- меблировку косых/неуверенных комнат;
- большие estates/outbuildings.

Публичное обещание лучше разделить: «3D opens as soon as the layout is ready; furnishing and AI images appear progressively». Мерить от upload, включая очередь, отдельно warm/cold и p50/p95.

6. Первый экран

Главное обещание:

> **Turn a floor plan into a furnished 3D viewing link — in minutes.**

Подзаголовок:

> Upload a PDF or photo. Get a walkable layout, furnished supported rooms and an AI visualisation — ready to share, with no app or card.

CTA:

> **Upload a floor plan — free**

Второй CTA:

> Open a live example

Под кнопкой честная beta-строка:

> Living rooms and bedrooms are furnished in this beta. Other rooms appear as labelled 3D spaces.

Справа — настоящий интерактивный тур или короткое `plan → grey 3D → furnished → AI image`, не абстрактный рендер. Основное отличие действительно соответствует конкурентному разбору: самостоятельная загрузка без звонка, ссылка без приложения и минуты вместо ручных 48 часов ([разбор конкурентов](/home/pakar/igor/remlab/.memory_bank/_intake/landing-competitors-2026-11-09.md:171)). Формулу «real products from UK retailers with live prices» до подключения UK-фида на первом экране не ставить.