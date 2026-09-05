## 1. Вывод

Базовые принципы архитектуры верны:

- исходный GLB неизменяем;
- ориентация хранится отдельным версионированным преобразованием;
- автоматические методы могут воздерживаться;
- VLM не должен молча разворачивать объект;
- человек — последний арбитр.

Но в текущем виде я не рекомендую включать hard-правило для сетов. Shadow-режим можно начинать после исправления контракта очереди, однако hard-mode сейчас создаст риск массового выпадения товаров и при этом не гарантирует, что оставшиеся меши действительно пригодны.

Главные блокеры:

1. Существующий шаг `MESH_QUEUE` технически неисправен и не является очередью в смысле durable state machine.
2. Один статус SKU смешивает независимые сущности: потребность, попытку генерации, asset revision, приёмку, ориентацию и human review.
3. `_slot_ok` не покрывает первоначальную сборку сетов и работает fail-open.
4. Текущие `scene_ready/web_ready` ещё не являются достаточно строгим доказательством «годного меша».
5. Очередь «недирекционные только из сетов» создаёт циклическое голодание при hard-gate.
6. Обещание «человек кликает десятки, не сотни» пока не подтверждается результатами 35 мешей.

Рекомендуемая граница владения:

- DEV Postgres — control plane очередей, lease/retry и текущего состояния.
- Salad Job Queue — execution plane генерации.
- R2 — immutable artifacts и evidence.
- Prod Postgres — только inbox human-review и append-only решения.
- `queue.json` — лишь версионированный экспорт батча, не источник истины.

## 2. Доказательства в репозитории

| Наблюдение | Доказательство |
|---|---|
| Текущий mesh-step падает при включении | В [refresh_daily.sh](/home/pakar/igor/remlab/tools/scout/refresh_daily.sh:211) stamp записывается до mesh-step; далее используется неопределённый `$VENV` при `set -u`, а путь строится относительно уже выполненного `cd tools/scout`. |
| Текущий файл очереди недолговечен | Там же, строки 220–234: `queue.json` перезаписывается целиком, без atomic rename, lease, попыток, retry и superseded-state. Идентификатор — усечённый MD5 URL, SKU в контракт не входит. |
| Искажённые роли | [refresh_daily.sh](/home/pakar/igor/remlab/tools/scout/refresh_daily.sh:225) делает `role.split(' ')[0]`: например, `стол обеденный` превращается в `стол`. Это уже видно в pilot-данных. |
| «Живое фото» фактически fail-open | [candidates.py](/home/pakar/igor/remlab/tools/scout/candidates.py:51) использует `unknown=True`; [img_alive.py](/home/pakar/igor/remlab/tools/scout/img_alive.py:80) считает непробитые и протухшие проверки допустимыми. |
| Возможна генерация по устаревшему enrichment | [load3.py](/home/pakar/igor/remlab/tools/scout/load3.py:225) сбрасывает `enrichment_version`, но сохраняет старые payload/quality. [candidates.py](/home/pakar/igor/remlab/tools/scout/candidates.py:59) требует quality, но не актуальность enrichment version. |
| Простые gates не эквивалентны реальной пригодности слоту | [compose2.py](/home/pakar/igor/remlab/tools/scout/compose2.py:359) дополнительно проверяет footprint, envelope, цену, subtype, пропорции и другие условия. SQL только по role/stock/photo/quality создаст много никогда не используемых demand. |
| `_slot_ok` не покрывает полный rebuild | Первичная сборка идёт через [compose2.py](/home/pakar/igor/remlab/tools/scout/compose2.py:230). `_slot_ok` применяется в incremental refresh/heal/enforce в [sets_incremental.py](/home/pakar/igor/remlab/tools/scout/sets_incremental.py:112). |
| Текущая mesh-проверка не является readiness gate | [sets_incremental.py](/home/pakar/igor/remlab/tools/scout/sets_incremental.py:138) запрещает только SKU из `replace_product`; отсутствие записи пропускается. Исключения вокруг контрактов также обрабатываются fail-open. |
| `scene_ready` пока слабее заявленного контракта | [mesh_gate_pbr.py](/home/pakar/igor/remlab/tools/scout/mesh_gate_pbr.py:195) допускает `geometry_ok=None`; CLI не передаёт результат геометрии. Это позволяет повысить статус без доказанной геометрической приёмки. |
| План и код расходятся по смыслу readiness | [mesh-bulk-salad-hunyuan.md](/home/pakar/igor/remlab/.memory_bank/plans/mesh-bulk-salad-hunyuan.md:133) описывает четыре стадии и более сильный `web_ready`; draft очереди в [mesh-queue-orientation.md](/home/pakar/igor/remlab/.memory_bank/plans/mesh-queue-orientation.md:45) предлагает gate уже по `scene_ready`. |
| Job identity недостаточно фиксирует генератор | [manifest.py](/home/pakar/igor/remlab/tools/scout/salad/manifest.py:51) включает input hash, commit, params и seed, но не полный digest контейнера, весов и preprocessing. |
| Queue заранее не знает настоящий input hash | Точный SHA исходных байтов вычисляется уже worker’ом в [preprocess.py](/home/pakar/igor/remlab/tools/scout/salad/preprocess.py:89). URL hash и pHash не заменяют этот digest. |
| R2-ошибка может вызвать повторную дорогую генерацию | [storage.py](/home/pakar/igor/remlab/tools/scout/salad/storage.py:50) трактует общую ошибку чтения как «не готово», а не как unknown. |
| Ошибки worker могут не ретраиться Salad | [worker.py](/home/pakar/igor/remlab/tools/scout/salad/worker.py:117) возвращает HTTP 200 с JSON `status=failed`. Если retry Salad основан на HTTP status, ретрай не произойдёт. |
| Контракт поворота ещё не защищён CI | В [scene_mesh.py](/home/pakar/igor/remlab/tools/scout/scene_mesh.py:65) применяется `ry(-front_yaw)`, тогда как комментарий файла говорит обратное. `orient_selftest.py` существует, но [CI](/home/pakar/igor/remlab/.github/workflows/ci.yml:42) его не запускает. |
| Role policy уже содержит спорную классификацию | [mesh_front.py](/home/pakar/igor/remlab/tools/scout/mesh_front.py:21) относит банкетку к NONDIRECTIONAL без проверки наличия спинки. Это противоречит правилу «без спинки — nondirectional». |
| `/test/` не подходит для приватной проверки | [Caddyfile](/home/pakar/igor/remlab/caddy/Caddyfile:13) отдаёт `/test/*` как публичную статику; `noindex` не является авторизацией. |
| Существующий admin guard нельзя копировать | [lib/trace/admin.ts](/home/pakar/igor/remlab/lib/trace/admin.ts:6) fail-open при отсутствии секрета и принимает token в query string. |
| Новая таблица требует изменения обоих deploy-путей | CI прогоняет glob миграций в [deploy.yml](/home/pakar/igor/remlab/.github/workflows/deploy.yml:84), но ручной [deploy.sh](/home/pakar/igor/remlab/deploy.sh:31) перечисляет миграции явно и новую миграцию пропустит. |

Дополнительно: проверенный `candidates-index.json` от 27.08.2026 содержит около 3223 товаров в перечисленных directed-ролях, а не около 4900. Это не опровергает цифру живой БД, но текущий воспроизводимый артефакт её не подтверждает. Доступа к live catalog Postgres в этой проверке не было.

## 3. Риски и крайние случаи

- **Циклическое голодание.** Если столики, пуфы и декор попадают в mesh queue только из существующих сетов, а hard-gate не разрешает им войти в сет без меша, новые альтернативы никогда не будут сгенерированы.

- **Mass churn.** Включение mesh-gate через общий `enforce_contracts --apply` способно за один daily run заменить или удалить значительную часть сетов.

- **Неправильная инвалидация.** Смена `FRONT_VERSION` не должна делать хороший GLB «негодным для сета». Пригодность asset и готовность к рендеру — разные состояния.

- **TOCTOU фото.** URL может остаться прежним, а байты измениться; URL может измениться при тех же байтах. URL MD5 и pHash нельзя использовать как идентичность входа.

- **Устаревший результат.** Пока Salad генерирует меш, товар может выйти из stock, сменить главное фото или получить новый enrichment. Результат можно сохранить, но нельзя автоматически сделать active.

- **Дубли и гонки.** Две попытки одного job могут одновременно увидеть отсутствие `complete.json` и записать один R2-prefix без conditional claim.

- **Симметрия и equivalence.** Конфликт 180° для симметричного пуфа — не конфликт. Для углового дивана, кресла-качалки или банкетки со спинкой та же логика неверна.

- **Зеркальность.** Equivalence должна содержать только proper rotations. Отражение левого/правого SKU нельзя принимать как эквивалентную ориентацию.

- **Четыре yaw-рендера не исправляют up.** Если сомнение касается pitch/up-axis, выбор 0/90/180/270 принуждает человека выбрать заведомо неправильный вариант.

- **Human-review volume.** На корпусных orienter сейчас часто abstain. Если VLM только предлагает, почти каждый такой объект уйдёт человеку. На масштабе тысяч это несовместимо с «десятками».

- **Недостаточная калибровка.** 10/11 сидячих и VLM 10/10 — хороший smoke test, но не оценка вероятности редкой тихой ошибки.

- **Диск DEV-VM.** На VM около 15 GiB свободного места; хранить локально всю коллекцию GLB рискованно. Нужен streaming/cache с удалением после анализа.

## 4. Альтернативы, которые стоит рассмотреть

1. **Файловая очередь в R2.** Допустима для пилота, если каждый job — отдельный immutable object. Для production orchestration всё равно потребуются lease, retry, reconciliation и индекс состояния; фактически это повторная реализация БД.

2. **Ориентация в том же Salad worker.** Уменьшает передачу данных, но связывает дешёвую CPU-операцию с дорогой генерацией, усложняет retry и затрагивает GPL/образ 3d-orienter. Если DEV не выдержит backlog, лучше отдельный Salad postprocess job.

3. **Весь control plane в prod Postgres.** Даёт одну БД, но смешивает dev catalog и production web, делает daily pipeline зависимым от прод-сервиса и расширяет поверхность доступа. Для данного масштаба это хуже отдельного review inbox.

4. **Немедленный hard-gate в `_slot_ok`.** Минимальный diff, но неполное покрытие и высокий риск обвала. Предпочтительнее отдельные `legacy/published` и `3d_ready` банки сетов с контролируемым продвижением.

5. **Полноценный workflow engine.** Temporal/Prefect могли бы решить orchestration, но для порядка 5–30 тысяч assets Postgres outbox + workers существенно проще и достаточнее.

## 5. Что рекомендую

### а) Mesh queue и state machine

Не делать единую колонку `sku.status`. Разделить состояния:

| Сущность | Пример состояний |
|---|---|
| Demand | `wanted`, `not_required`, `superseded` |
| Generation attempt | `queued`, `submitted`, `running`, `retry_wait`, `failed_terminal`, `completed` |
| Asset revision | `generated`, `acceptance_pending`, `accepted`, `rejected`, `superseded` |
| Orientation | `not_required`, `pending`, `auto_resolved`, `vlm_pending`, `review_pending`, `human_resolved` |

Demand вычислять как:

- directed-товары, прошедшие актуальные stock/photo/enrichment gates;
- текущие члены сетов;
- top-K кандидатов замены каждого слота после всех немешевых проверок;
- небольшой резерв по каждому role/style/price band, чтобы hard-mode не оставлял слот без альтернатив.

Для фото требуется отдельный source-ingest: скачать байты один раз, положить immutable объект в R2, вычислить полный SHA-256. Desired generation key должен включать:

`sku + source_blob_sha256 + container_digest + generator/weights digest + preprocess digest + params + seed + schema_version`.

Готовым считать только asset, у которого:

- exact desired key совпадает;
- манифест и GLB существуют;
- полный GLB checksum сходится;
- завершена требуемая acceptance stage;
- asset не superseded.

R2 timeout должен давать `unknown/retry`, а не «asset отсутствует».

### б) Внедрение правила сетов

Рекомендуемая этапность:

1. **Shadow:** считать `mesh_ready` и прогнозировать потери сетов, ничего не изменяя.
2. **Hard-new:** не публиковать новые 3D-ready сеты без мешей; существующие published сеты не разрушать.
3. **Rolling remediation:** заменять legacy SKU только когда найдено совместимое mesh-ready замещение.
4. **Full hard:** после достижения порога не по общему проценту SKU, а по complete-set coverage и запасу альтернатив.

Нужен один общий predicate, используемый и в initial compose, и в `_slot_ok`. Fail-open в hard-mode недопустим.

Для предотвращения обвала измерять:

- долю полностью покрытых сетов;
- coverage по каждой роли;
- число совместимых альтернатив на слот;
- coverage по style/price band;
- прогнозируемый churn;
- количество сетов, которые останутся без решения.

`replace-registry` следует оставить отрицательным override, но не превращать его в registry готовности.

### в) Ориентация

На первом этапе — отдельный DEV-VM worker/timer:

- 1–2 процесса;
- Postgres lease;
- `flock`, `nice/ionice`;
- загрузка GLB по SHA, локальный bounded cache;
- независимые retry и мониторинг.

При 5 секундах на меш 4900 объектов — примерно 6,8 CPU-часа одним worker, а не сотни часов. Поэтому перенос в Salad преждевременен до реального throughput-теста.

Порядок обработки:

1. orienter определяет up/full rotation;
2. candidate rotation применяется в памяти;
3. `mesh_front` оценивает yaw уже в нормализованной системе;
4. преобразования компонуются в один `raw_to_canonical` quaternion;
5. запускается pose-contract self-test.

Хранить orientation отдельно от asset manifest:

```text
assets/<asset_id>/
  manifest.json                         # владелец Salad-плана
  analysis/orientation/<contract>/evidence/*.json
  analysis/orientation/<contract>/resolution/<id>.json
```

Resolution должен содержать asset ID, полный GLB SHA, normalized quaternion с фиксированным знаком, coordinate convention, версии orienter/mesh_front/VLM, evidence, equivalence class, автора и timestamp. Asset `manifest.json` не изменять.

### г) Human review

Использовать настоящую приватную Next.js-страницу, например `/lab/mesh-review`, не публичную `/test/`.

Минимальная постоянная модель:

- `mesh_review_tasks`: asset/hash, SKU, версии контракта, evidence, render keys, допустимые варианты, статус;
- `mesh_review_decisions`: append-only ID, task, choice, reviewer, timestamp, idempotency key, optional supersedes.

Write/read path:

1. DEV pipeline идемпотентно POST’ит review tasks в prod API.
2. Браузер владельца записывает append-only decision.
3. DEV получает решения через `GET decisions?after_id=...`.
4. Локальный cursor обновляется транзакционно только после применения решения.
5. Pipeline пишет новую immutable orientation resolution в R2.

Нужны отдельные machine и reviewer secrets. Browser login должен создавать `HttpOnly`, `Secure`, `SameSite=Strict` cookie; POST — с Origin/CSRF-проверкой. Query-string tokens не использовать. R2-рендеры лучше выдавать через короткоживущие signed URLs.

Кроме четырёх yaw-кнопок нужны:

- `NONDIRECTIONAL`;
- `неверный up`;
- `меш непригоден`;
- `пропустить/нужен другой ракурс`.

### д) Что считать спорным

Лексикографику стоит уточнить:

- **Nondirectional:** ориентация yaw не нужна; решение принимается по геометрии/capability, а не только общей роли.
- **Сидячие:** уверенный `mesh_front` — главный источник yaw; orienter — источник up и свидетель. Сильный несовместимый конфликт нельзя молча игнорировать.
- **Корпусные:** orienter + фото-сверка. Согласие двух откалиброванных методов может стать auto после достаточного gold set.
- **VLM:** только формирует кандидат и evidence; само по себе не auto-решение.
- **Человек:** окончательный авторитет, но решение привязано к конкретному GLB hash и contract version.

Конфликт надо считать как минимальное расстояние между equivalence classes, а не простую разницу углов. Для симметричного объекта 0° и 180° могут быть одним решением.

## 6. Неопределённости

Не хватает следующих данных:

- live-выборки, воспроизводящей заявленные ~4900 SKU теми же gates;
- финального R2 manifest schema соседней Salad-сессии;
- точного определения `scene_ready` и `web_ready`;
- подтверждения retry-семантики Salad для HTTP 200 с `status=failed`;
- кода фактического orienter+flipper driver и семантики его `p`;
- стратифицированной оценки по ролям, а не только 35 мешей;
- оценки числа корпусных объектов, которые уйдут в review;
- согласованного критерия «годный меш»: достаточно PBR или обязательны geometry/scale/pivot/floor;
- надёжного признака «банкетка/пуф со спинкой» в enrichment;
- измеренного времени анализа с учётом скачивания, конвертации и четырёх рендеров.

Также найденные локальные legacy-меши почти не имеют новых R2-манифестов. Нужен отдельный bootstrap/reconciliation, иначе diff «уже сделано» будет неполным.

## 7. Что изменило бы мой вывод

Я бы одобрил переход к hard-mode после появления следующего набора доказательств:

- два идентичных refresh run дают ноль новых Salad jobs;
- смена ровно одного фото создаёт ровно одну новую revision;
- R2 timeout не запускает повторную генерацию;
- crash/restart не теряет и не дублирует job;
- manifest fixture фиксирует полные input/output hashes и все версии;
- shadow-отчёт показывает coverage и запас альтернатив по каждой роли/слоту;
- dry-run hard-gate не разрушает текущие 126 сетов и не ухудшает распределение style/price bands сверх согласованного порога;
- stratified gold set подтверждает калиброванные auto-thresholds и ожидаемый объём human review;
- review API проходит idempotency, superseded-asset, auth/CSRF и cursor-resume сценарии;
- pose self-tests для quaternion/yaw/equivalence запускаются в CI;
- подтверждено, что Salad действительно ретраит используемый класс ошибок.

Файлы в ходе проверки не изменялись.