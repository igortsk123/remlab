---
tier: intake
topic: codex-book-verify
scope: Ответ Codex 13.10 — полная сверка книги о продукте с кодом (79 блоков, 28 расхождений, 5 не найдено)
updated: 2026-10-13
source: external:codex-exec (сессия 01a00a62, read-only)
status: raw
---

Проверено состояние `main` на `f806f2c`. Числа из БД и рыночные тезисы не перепроверял, как задано. Живой `crontab -l` прочитать не удалось: `Permission denied`, поэтому расписание DEV помечено «НЕ НАЙДЕНО».

| Гл. | Короткая цитата | Код | Вердикт |
|---|---|---|---|
| 1.1 | «Сегодня демо только на русском, один сертификат, рынки не различаются» | `flat215-demo/index.html:1,677-688`; `flat215_demo.py:642-650` | **OK** |
| 1.2 | «Квартира, ЖК и цена зашиты; карточки застройщика нет» | `flat215-demo/index.html:677-688,1525-1534`; `flat215_demo.py:642` | **OK** |
| 1.3 | «Нет страницы менеджера, персональных отправок и их номеров» | `app/`; `lib/leads/` содержит только лиды калькуляторов | **OK** |
| 1.4 | «Снятые товары выбрасываются; видно четыре стиля» | `flat215_demo.py:378-408`; `flat215-demo/index.html:900,954` | **OK** для механизма; бедность вариантов и ковры — данные, не проверялись |
| 1.5 | «Правки теряются; ссылка хранит исходный вариант; скачать кадр нельзя» | `flat215-demo/index.html:947-954,1017-1042,1129`; есть только печать списка `:868` | **OK** |
| 1.6 | «Кадр без очереди и прогресса» | `draft_service.py:77-84,146-153,219-246`; `index.html:2265-2305` | **MISMATCH** — есть фоновое задание, polling и прошедшее время; нет только места в очереди/ETA |
| 1.7 | «В 3D другая квартира» | `app/flat/page.tsx:20-44`; `fromDemo.ts:58-153` | **MISMATCH** — `?demo=` уже открывает ту же гостиную и мебель; вся квартира действительно не передаётся, цена нулевая |
| 1.8 | «Кухня/спальни серые; кухня в 3D — прямая линия четырёх уровней» | `index.html:704-708`; `catalogue-base.json:833-917`; `viewer.ts:360-371` | **OK** |
| 1.9 | «Кнопки застройщика — заглушки; аналитики и менеджерского бота нет» | `index.html:1547-1552`; отсутствие B2B-событий в `app/` | **OK** |
| 2.1 | «Один refresh_daily, три исхода шага» | `refresh_daily.sh:37-65,148-444` | **MISMATCH** — конвейер один, но исходов четыре: `ok`, `WARN`, `FAIL`, `SKIP` |
| 2.2 | «Ежедневно 10:40 UTC и при перезагрузке» | живой `crontab -l` недоступен; репо-unit запуска refresh не найден | **НЕ НАЙДЕНО** |
| 2.3 | «БД, десять zip-фидов, проверка архива, тревога после двух сбоев» | `refresh_daily.sh:148-213` | **OK** |
| 2.4 | «feed_guard карантинит пустой и похудевший фид» | `feed_guard.py:27-29,121-141`; `load3.py:373-407` | **MISMATCH** — guard ловит empty/stale/broken; усадку до 70% блокирует `load3`, не `feed_guard` |
| 2.5 | `gdeslon_api.py --retire` | `gdeslon_api.py:11,124`; вызов `refresh_daily.sh:224` | **OK** |
| 2.6 | «load3: поля, четыре смысловых хеша, 70%, архив через три дня, fail-stop» | `load3.py:93-129,373-407,420-509`; `refresh_daily.sh:228-229` | **OK** |
| 2.7 | «category_map превращает категорию и слова названия в роль» | `load3.py:203-223`; `tests_chain.py:56-82` | **MISMATCH** — канон намеренно не угадывает неизвестную категорию по названию; роль прежде всего из `mid:categoryId` |
| 2.8 | «catalog_api: сплошной обход+поиск, комиссия/HD/описание, только дополнение» | `catalog_api_sync.py:49-51,102-147,181-212`; вызов после load3 `refresh_daily.sh:230-244` | **OK**, но связи различаются по полям, а не единообразно «картинка+название» |
| 2.9 | «dim_prior калибрует единицы и оси по магазин×роль» | `dim_prior.py:1-42,107-141,173-199` | **MISMATCH** — это достройка глубины по `роль×форма`; единицы и оси разбирает `dim_resolver` |
| 2.10 | «У вазы/кашпо/торшера/пуфа глубина равна ширине» | `dim_resolver.py`; `footprint.py:42-74`; `mesh_bind.py:95-109` | **MISMATCH** — `d=w` допустимо только при честном диаметре/канонической square-role; в каталог глубина не придумывается |
| 2.11 | `dim_audit.py --warn` по магазин×роль | `dim_audit.py:23,48,112,204-219`; вызов `refresh_daily.sh:260-264` | **OK** |
| 2.12 | `stock_check → page_alive → stock_truth.reconcile` | `stock_check.py:25-36,44-50`; `stock_truth.py:223+`; вызов `refresh_daily.sh:266-270` | **OK** — запускается ежедневно, отдельная карточка перепроверяется по TTL |
| 2.13 | `phash.py` после наличия | `refresh_daily.sh:272-273` | **OK** |
| 2.14 | `enrich --pool --vision`, бюджет, `enrich_wait` и пересборка индекса | `refresh_daily.sh:275-303`; `enrich_wait.sh:20-61` | **OK** |
| 2.15 | `style_score`, `pack_qty`; будущие оси | `refresh_daily.sh:284-296`; планы `conv-01*:4,15+`, `conv-02*:4,15+` | **OK** как текущее имя и подтверждённый будущий план |
| 2.16 | «capabilities сводит доступные роли, размеры и стили» | `capabilities.py:1-20,107-251` | **MISMATCH** — это SKU-capabilities: посадочность, неглубокое хранение, механизмы и planning roles |
| 2.17 | `img_alive → linkcheck → candidates` | `refresh_daily.sh:309-317`; `candidates.py:51-90` | **OK** |
| 2.18 | `cutout_sync`, `hybrid_mask`, `collage`, `photo_fit`; ночью лимит 0 | `refresh_daily.sh:318-323`; названные файлы существуют | **OK** |
| 2.19 | Индекс/check, live-инварианты, health/metrics/audit | `refresh_daily.sh:324-338`; `tests_chain.py:118-202`; `health.py:91-98` | **OK** |
| 2.20 | Heal/contracts/reindex/служебные страницы; publish до demo; понедельник | `refresh_daily.sh:343-411`; все названные скрипты существуют | **OK** |
| 2.21 | «Ночью review pull, затем push» | `refresh_daily.sh:424-441` | **MISMATCH** — фактически `--push`, затем `--pull` |
| 2.22 | Экзамен 03:00, audit-sync 1 мин, guards 5/10/15 мин, окно 09/15, render при boot | живой crontab недоступен; файлы существуют | **НЕ НАЙДЕНО** для фактического расписания |
| 3.1 | `enrich.todo`: повтор только при смене текста/размеров | `load3.py:489-497`; `enrich.py:124-145` | **MISMATCH** — stale также дают картинка и значимые attrs |
| 3.2 | Фото 448 px, анкета, Luna, quality 0.65 | `enrich.py:36,67-91,232-294`; `golden_label.py:91,195+` | **OK** |
| 3.3 | «Сегодня enrich выключен openai.off» | `tools/scout/openai.off`; `refresh_daily.sh:18,284` | **OK** для текущего состояния; историческая дата не проверялась |
| 3.4 | «Два источника стиля и третья ступень у демо» | `enrich_bridge.py:160-201`; `style_score.py:40-58`; `demo_swap_pool.py:44-66` | **OK** |
| 3.5 | «Живое фото читают двое из шести» | `candidates.py:51-54`; `compose2.py:400-409`; `flat215_demo.py:505-508` | **MISMATCH** — уже минимум трое; `style_score`, `mesh_bind`, `demo_swap_pool` всё ещё смотрят лишь URL |
| 4.1 | Названные `mesh_*`, `orient_worker`, `salad/*` существуют | соответствующие файлы в `tools/scout/`, `tools/scout/salad/` | **OK** |
| 4.2 | `mesh_bind`: только роли гостиной и живое фото | `mesh_bind.py:48-110` | **MISMATCH** — все роли стратегии `hunyuan3d`; гейт проверяет непустой URL, не `img_alive` |
| 4.3 | Семейства и атомарный приоритетный снимок | `mesh_family.py`; `mesh_priority.py:393-453,560-590` | **OK** |
| 4.4 | «Планировщик+export формируют рабочую волну» | `mesh_scheduler.py:35-36,62-130`; `mesh_wave_start.sh:72-84` | **MISMATCH** — полная волна строится `mesh_priority --build-queue`; scheduler/export — отдельная дневная очередь |
| 4.5 | Законный старт и три группы/окно | `mesh_wave_start.sh:1-14`; `salad-groups.json:10-23` | **OK** |
| 4.6 | Staged pipeline, receiver, draining/finale | `salad/pipeline.py`; `batch_show.py:131,739,845-876`; compose service `mesh-receiver` | **OK** |
| 4.7 | «При пустом балансе ничего не происходит, пока владелец не заметит» | `batch_show.py:197-200,255-260` | **MISMATCH** — `no_credits_available` распознаётся и посылает throttled alert; автостарт действительно отсутствует |
| 4.8 | Точный порядок `post_steps` | `batch_show.py:566-600` | **OK** |
| 4.9 | Приёмка понижает до generated, а readiness принимает generated; резаки включены | `apply_repairs.py:195-244`; `mesh_ready.py:49-65`; `pipeline.py:497-501` | **OK** |
| 4.10 | Партии 200, 20 карточек, ledger/redo/sync | `mesh_audit_publish.py`; `lib/mesh-audit/rules.ts:4-7`; `mesh_audit_sync.py:90-102,214+` | **OK** |
| 4.11 | Модели demo-вариантов идут full GLB без cache | `fromDemo.ts:138-148`; `data.ts:13-32`; `Caddyfile:100-107` | **OK** — runtime-копия используется только если mesh есть в manifest |
| 5.1 | `CORE`, локальный свет и universal «без штрафа» | `compose2.py:1095-1105,1173-1180` | **MISMATCH** — свет добавляется вне `CORE`; universal получает 5.5/+0.3, а не нейтральное отсутствие штрафа |
| 5.2 | `proportions.json`, `item_function`, slot envelope, `_SLOT_MISS` | `compose2.py:344-365,385-434`; `tools/scout/proportions.json` | **OK** |
| 5.3 | «Пороги dining 22/40 против правил 18/30» | `compose2.py:352-354`; `zones.json:1105-1112` | **MISMATCH** — 22/40 действительно в коде; правила задают площадь региона 3/6/8 м², не пороги 18/30 |
| 5.4 | «Heal и demo по-разному понимают снятие» | `sets_incremental.py:545-561`; `flat215_demo.py:369-398`; `catalog_media.py` | **MISMATCH** — оба уже опираются на производное состояние каталога; demo лишь имеет дополнительный fail-safe |
| 5.5 | `LAYOUT_ENGINE=zoned`, zones/templates, hard/soft validation | `solver_run.py:851`; `planner/zones.py`; `validate.py`; `score.py` | **OK** |
| 5.6 | «Всего 60 раскладок» | `templates.json`, `zones.json` не содержат устойчивого агрегата 60 | **НЕ НАЙДЕНО** |
| 5.7 | Нормы occupancy и те же числа в подсказчике | `occupancy.json:345-453,469-500`; `zones.json:1416-1422` | **MISMATCH** — TV 1.2–2.5 диагонали, preferred 1.6; floor occupancy — cap/диагностика, не цель 40–50% |
| 5.8 | 272 acceptance-сцены; demo не помечено | `tools/scout/acceptance-scenes.json`; поиск `flat215/demo` пуст | **OK** для проверяемой части |
| 5.9 | `drop_unavailable → pick_banks → solve_layouts → _dims_of → demo-data` | `flat215_demo.py:34-69,322-409,642-650` | **OK** |
| 5.10 | «Сегодня 4 стиля, нет ≥6, slot ranges hardcoded» | `index.html:900,954`; `demo_swap_pool.py:44-66`; `flat215_demo.py:469-478` | **OK** |
| 6.1 | «Сегодня /demo только RU» | `index.html:1`; i18n-переключателя нет | **OK** |
| 6.2 | «Коллекция не сохраняет расстановку; share не доставляет» | `index.html:947-954,2594-2606`; `draft_service.py:328-387` | **OK** — сервер сохраняет статическую подборку кадров, но не пользовательскую расстановку |
| 6.3 | «Рендер без очереди/прогресса, 25 секунд молча» | `draft_service.py:77-84,181-190,219-246`; `index.html:2265-2305` | **MISMATCH** |
| 6.4 | «Нет продуктовых счётчиков» | в `index.html` нет аналитических событий/идентификатора отправки | **OK** |
| 7.1 | «В /flat другая 58 м² квартира» | `page.tsx:20-44`; `fromDemo.ts:58-153`; `apartment.json:5` | **MISMATCH** — базовый `/flat` 58 м², но переход из demo уже использует ту же гостиную и набор |
| 7.2 | «Нет drag, зелёного/красного гейта и загрузки с процентами» | `Scene3D.tsx:64,211-306,323-335,340-410`; `FlatConfigurator.tsx:145-166` | **MISMATCH** — всё перечисленное уже есть; нет удаления и кнопок, привязанных проекцией к объекту |
| 7.3 | «Demo-save падает, сохранённая ссылка открывает base» | `api/flat/config/route.ts:21-25`; `FlatConfigurator.tsx:169-180` | **MISMATCH** — demo-save действительно получает 400, поэтому «сохранённой ссылки» вообще нет; URL также теряет `demo/lang` |
| 7.4 | «В EN русские товары/материалы, магазины и одна неверная кнопка» | `fromDemo.ts:79-80,131-149`; `materials.json:56-355`; `Scene3D.tsx:319,350-404` | **MISMATCH** — проблема шире: много русских материалов, ролей, aria/title и move-controls |
| 8.1 | «Нет B2B manager/funnel; есть только бот лидов калькуляторов» | `lib/leads/`, `app/api/leads/`; B2B-страниц/таблиц нет | **OK** |
| 9.1 | «На сервере контейнеры app,caddy,db,imagor,mesh-receiver,draft» | `docker-compose.yml:4-153`; `Caddyfile:110-127` | **MISMATCH** — `draft` отсутствует в compose, хотя Caddy на него проксирует |
| 9.2 | GitHub deploy и rollback через `deploy-remote.sh` | `infra/server/deploy-remote.sh`; `.github/workflows/deploy.yml` | **OK** |
| 9.3 | «remlab-watchdog каждый час сторожит сайт» | `remlab-watchdog.service:1-6`; timer `:5` | **MISMATCH** — это сторож диска; внешний availability-check отсутствует |
| 9.4 | DEV cron из главы 9 | `crontab -l` → permission denied | **НЕ НАЙДЕНО** |
| 9.5 | «DEV через туннель, ручные публикации, draft расходится с repo» | `draft_service.py:247-260`; отсутствие draft в compose | **OK** |
| 9.6 | «Health всегда good, внешнего monitor нет» | `lib/health.ts:13-20`; systemd units | **OK** |
| 9.7 | «Backup только локально, restore drill нет» | `infra/server/db-backup.sh:2-11`; поиск restore/offsite пуст | **OK** |
| 9.8 | «Контакты закрыты, policy href пустой, rate limits нет» | `Caddyfile:93-98`; `LeadModal.tsx:130`; `draft_service.py:69-74,281-286` | **MISMATCH** — первые два верны, но рендер ограничен semaphore=2 и 60/час |
| 10.1 | «Форм и CRM не делаем» | `LeadModal.tsx`; `app/lead-actions.ts`; `lib/leads/` | **MISMATCH** как общее утверждение; верно только для нового B2B-потока |
| 10.2 | «Не чиним меши автоматически» | `salad/pipeline.py:497-501`; `apply_repairs.py:44-49` | **MISMATCH** — `cut_base_slab` и `crop_beyond_passport` включены |
| 10.3 | «Страницы товара — недельный TTL; embed/cloud/legal пока нет» | `stock_check.py:25-36`; текущие `app/`, `docker-compose.yml` | **OK** |
| 10.4 | «Прототип замера комнаты по фото уже есть и спит» | найден только потребитель готового плана `room_bridge.py:1-25` | **НЕ НАЙДЕНО** — самого измерителя фото в репозитории нет |
| 10.5 | Все ссылки «после правок» на `conv-*`/`b2b-*` | `.memory_bank/plans/conv-01…11*.md:4,15+`; `b2b-00…13*.md:4,15+` | **OK** — все 25 планов существуют, прямые обещания книги входят в их scope |

### ПРОПУЩЕНО в книге

- Законный старт волны перед снимком сначала делает `drain → registry → family → bind → purge → audit pull`, и только потом очередь: `mesh_wave_start.sh:43-84`.
- Динамический супервизор нод, retry-spool, warmup fault и бюджеты переаллокации: `salad/ssh_run.py:51-84,139-196`; `node_health.py`.
- Render уже имеет async-job registry, ограничение параллелизма и расхода: `draft_service.py:69-84,219-286`.
- `/flat` уже имеет перенос демо-варианта, сохранение координат drag, collision gate и экран загрузки: `fromDemo.ts`, `Scene3D.tsx`.
- Публикация мешей ежедневно пересобирает prod-index по реальным файлам сервера, а не просто копирует индекс: `mesh_publish.py:78-97,130-153`.
- `dim_prior` хранит честный provenance `role_prior` и не заменяет осевые конвенции: `dim_prior.py:173-199`.
- `stock_check` содержит TTL/канарейку/классы отказов и защиту от антибота; книга сводит это к «три карточки открылись».
- `tests_chain --live` читает crontab без проверки return code: при `Permission denied` он сообщает «все guards отсутствуют», не различая сбой чтения и реальное отсутствие: `tests_chain.py:170-180`.

### Итог

Проверено **79 блоков**: **46 OK**, **28 MISMATCH**, **5 НЕ НАЙДЕНО**.

Пять первых исправлений книги:

1. Полностью обновить главу 7: мост demo→3D, drag/collision и progress уже реализованы.
2. Переписать раздел размеров: `dim_prior` не калибрует единицы/оси, а `d=w` не является общим правилом ролей.
3. Исправить текущее описание рендера: async/polling/progress и лимиты уже есть.
4. Развести три мешевые очереди: `mesh_priority` для волны, `mesh_scheduler` для дневных 10, `mesh_queue --export` как отдельный экспорт.
5. Исправить каноны комплектов/солвера: `CORE`, universal, dining thresholds, availability и нормы occupancy описаны неточно.