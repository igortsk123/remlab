T‑A можно начинать, но в плане я бы поменял следующее.

1. Lease fencing

`lease_token + attempt` достаточно, если смена и проверки атомарны. Зафиксировать:

- каждый claim делает `attempt = attempt + 1` и выдаёт новый случайный `lease_token`;
- heartbeat/result/fail — одним `UPDATE … WHERE status='running' AND attempt=? AND lease_token=? AND lease_until>now()`;
- просроченный heartbeat аренду не возобновляет;
- claim берёт только `attempt < max_attempts`; исчерпанные задания отдельно переводятся в `failed`;
- повтор того же result после потерянного HTTP-ответа идемпотентен, другой результат — `409`.

Иначе между чтением строки и обновлением останется гонка. Сейчас план обещает проверять только token ([подплан](/home/pakar/igor/remlab/.memory_bank/plans/agent-trial-01-upload-grey-tour.md:53)); `attempt` должен означать номер поколения аренды, а `max_attempts=2` — ровно два claim.

2. Загрузка

Заменить `request.formData()` на потоковую запись через busboy в файл `.part`:

- rate-limit и проверка заполненности очереди — до чтения body;
- жёсткий лимит считать по реально прочитанным байтам, не только `Content-Length`;
- одновременно считать SHA-256 и проверять magic bytes;
- после успеха — atomic rename; при abort, ошибке БД или превышении лимита удалять `.part`;
- retention чистит также осиротевшие `.part`.

Для app с `mem_limit: 1g` это оправдано ([compose](/home/pakar/igor/remlab/docker-compose.yml:103)). Настройка `bodySizeLimit` репозитория относится только к Server Actions, не к Route Handler ([next.config.mjs](/home/pakar/igor/remlab/next.config.mjs:8)). Caddy 16 MiB оставить внешним заслоном, а 15 MiB явно определить как лимит именно файла.

3. `trial_workers` и очередь

- `queuePos` не хранить: вычислять `queueAhead` по тому же predicate/order, что claim, либо показывать просто `Queued`.
- `breaker` из БД убрать.
- Из `trial_workers` оставить только `id,last_seen,version`, поскольку тесты требуют отличать мёртвый воркер. Обновлять `last_seen` на каждом poll, даже когда воркер временно unavailable; причину breaker оставить в DEV-логах.

Если текст про мёртвый воркер убрать из приёмки, таблицу можно удалить целиком. Текущее сочетание breaker-before-claim и записи breaker в prod требует лишнего status API ([подплан](/home/pakar/igor/remlab/.memory_bank/plans/agent-trial-01-upload-grey-tour.md:84)).

4. Хранение и ПДн

14/90 дней не запрещены сами по себе: UK GDPR не задаёт фиксированных сроков, но требует обосновать их целью и удалять данные, когда цель закончилась ([ICO: storage limitation](https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/data-protection-principles/a-guide-to-the-data-protection-principles/storage-limitation/)).

Для v1 поменять на:

- исходник — 24 часа после terminal status, максимум 7 дней для диагностики;
- результат — 30 дней; 90 только если это явно заявленный срок жизни share-link;
- email до T9 вообще не собирать: сейчас он не используется, что противоречит минимизации ([ICO: data minimisation](https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/data-protection-principles/a-guide-to-the-data-protection-principles/data-minimisation/));
- `ip_hash` не хранить в job; лимитер уже ведёт краткоживущие счётчики ([ratelimit](/home/pakar/igor/remlab/lib/ratelimit/index.ts:19));
- после удаления ставить `input_path=null/input_deleted_at`; при ошибке удаления сохранять ссылку для следующего запуска — тот же инвариант уже есть у retention ([run.ts](/home/pakar/igor/remlab/modules/retention/run.ts:31)).

5. Тесты T‑A

Добавить обязательно:

- reclaim одновременно со старым heartbeat/result/fail; ABA с тем же `worker_id`; граница expiry; исчерпание попыток; повтор result после потерянного ответа;
- конкурентный admission: очередь не перескакивает лимит 5;
- chunked upload, ложный `Content-Length`, `limit±1`, disconnect и ошибка БД — без `.part` и сирот;
- публичные DTO не содержат `input_path`, email, listing text, IP, lease/token, worker/error detail;
- traversal/symlink через `input_path`, неверный Bearer и отсутствие env;
- retention: файл удалён, результат жив; затем результат даёт `410`; ошибка `unlink` оставляет запись для повтора.

Отдельно закрыть утечку ключа ссылки: `/try/<id>` сейчас не маскируется в `metrikaSafeUrl` ([metrika.ts](/home/pakar/igor/remlab/lib/metrika.ts:20)), а полный URL явно передаётся Метрике ([layout.tsx](/home/pakar/igor/remlab/app/layout.tsx:71)). Для `/try` лучше полностью отключить Метрику/Webvisor, поставить `Referrer-Policy: no-referrer`, `Cache-Control: private, no-store`, а `result_version` использовать как `ETag`.

И ещё одна арифметическая правка: `50 × $0.10 = $5`, а не заявленные $3. Для v1 поставить глобальный cap 30 заданий либо делать атомарное резервирование денежного бюджета.