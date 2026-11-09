---
workstream: product
slug: agent-trial-01-upload-grey-tour
title: Проба агента — загрузка плана → задание на проде → воркер DEV → серый 3D-тур по ссылке /try/<id>
status: in_progress
created: 2026-11-09
updated: 2026-11-09
completed:
plan_kind: sub
parent_plan: MASTER-agent-trial
review_after: 2026-11-23
---

## Цель
Вертикальный срез T3+T4 мастера: агент грузит картинку/PDF плана (+ текст объявления, + почта по желанию) → задание в Postgres
прода → воркер на DEV забирает его по HTTPS (claim/heartbeat/result, токен машины) → стенд `tools/floorplan` строит стены и
комнаты → JSON результата в базе → `/try/<id>` показывает шаги с таймером, затем серый 3D-тур (полигоны `contour`), читая JSON
во время работы, без сборки сайта и без реестра квартир. Мебели, товаров, фото, письма нет.

## Источник задачи
Мастер `MASTER-agent-trial` (T3 `job-runtime` + T4 `upload-grey-tour` — сведены в один срез по заданию ведущего 09.11);
Codex `_intake/codex/agent-trial-master-2026-11-09-answer.md` §1–3; инвентаризация `_intake/agent-trial-pipeline-inventory-2026-11-09.md`
(шаги 1, 2, 2а, 3, 4, 10); решения владельца TG 294 (миграции — без вопросов, pg_dump перед).

## Скоуп — что входит
- Таблица заданий + машинный мост прод ↔ DEV по образцу `lib/mesh-review/auth.ts:machineOk` (Bearer) и
  `tools/scout/mesh_audit_sync.py:api` (DEV сам ходит на прод; туннель кадров ADR-0139/0280 — обратный путь, его не трогаем).
- Модуль стенда «слепой план → результат» без `gold/*.json` и `CFG[plan]`; PDF → картинка; воркер DEV с изоляцией от демо.
- Страница загрузки `/try` (простая форма EN, не лендинг T8) и страница задания `/try/<id>` (шаги, таймер, серый тур).
- Лимиты пробы, суточные потолки денег, срок хранения файлов (⚑ владелец — сроки), поле email без отправки.

## Скоуп — что НЕ входит
Мебель/расстановка (T5), спальня (T6), фото (T7), лендинг (T8), письмо и outbox (T9: таблица — по образцу `db/schema.ts:signalOutbox`,
сейчас только поле `email`), «введите одну длину» (T1-цепочка отказа, след. план), прогулка по полигонам (боевой
`lib/viewer3d/walk.ts:walkArea` — только прямоугольники), капча (в проекте её нет; лендинг не публичный — лимиты достаточно),
мост в `contracts/apartment.ts:apartment` (T5), PDF-вектор/DXF (`b2b-13`).

## Решения внутри плана (кандидаты в ADR)
- **Имена:** страница `/try/<id>`, API `/api/trial/*`. НЕ `/api/job*` и НЕ `/api/jobs*`: в `caddy/Caddyfile` `handle /api/job*` уходит
  в сервис кадров `draft:8099` — совпадёт и `/api/jobs`. Таблица `trial_jobs` (не `jobs`: у кадров уже есть «job» в другом смысле —
  `tools/scout/draft_service.py`, `/api/job`); поле `kind` оставляет её общей на будущее.
- **id задания = публичный ключ ссылки** — `lib/token.ts:randomToken` (22 символа, `TOKEN_RE`), перебор невозможен.
- **Координаты результата:** сантиметры, x вправо, y вниз по листу = «вглубь» канона: то же отображение план y → сцена Z, что у
  `lib/viewer3d/rooms.ts` (шапка) и `tools/floorplan/render/scene.js` (шапка); переворота нет. `contour` — канон, `bbox` — проекция
  (как требует `contracts/apartment.ts:room` refine) — T5 возьмёт комнату без пересчёта.
- **Очередь — только Postgres** (Codex §2): `FOR UPDATE SKIP LOCKED`, lease + heartbeat, опрос воркера раз в 2 с; LISTEN/NOTIFY нет.
- **PDF → PNG на DEV, не на проде:** `pdftoppm` (poppler 26.01 уже стоит на pakardev; GPL — вызываем отдельным процессом, наш код не
  заражает), `-r 150 -png -f 1 -l 2`, `timeout 30`, `prlimit --as`. PyMuPDF — AGPL, нельзя; `pypdfium2` (Apache/BSD) — запасной, не стоит.

## Поправки после Codex 09.11 — ПРИОРИТЕТ над текстом ниже
Ответ — `_intake/codex/agent-trial-01-plan-2026-11-09-answer.md`; ведущий сверил по коду (`lib/metrika.ts:metrikaSafeUrl` не маскирует
`/try/`, `docker-compose.yml:103` app `mem_limit: 1g`) — принято целиком:
- **Ограждение:** claim → `attempt = attempt + 1` + новый случайный `lease_token`; heartbeat/result/fail — одним `UPDATE … WHERE
  status='running' AND attempt=? AND lease_token=? AND lease_until>now()`; просроченный heartbeat аренду не продлевает; claim берёт только
  `attempt < max_attempts` (2 = ровно два claim), исчерпанные — отдельным `UPDATE` в `failed/lease_lost`; повтор того же result после
  потерянного ответа — идемпотентен (тот же хэш тела → 200), другой — 409.
- **Загрузка потоком** (busboy → `<id>.part`), не `request.formData()`: лимит частоты и заполненность очереди — ДО чтения тела; лимит
  15 МБ — по реально прочитанным байтам; sha256 и сигнатура — на лету; успех → атомарный rename; обрыв/ошибка БД/превышение → `.part`
  удаляется; retention чистит сироты `.part`. Caddy 16 МБ — внешний заслон. (`next.config.mjs` `bodySizeLimit` — только Server Actions.)
- **Без `breaker` и `queuePos` в БД:** `queueAhead` считать тем же условием и порядком, что claim; `trial_workers` = `id, last_seen,
  version` (last_seen — на каждом опросе, даже когда воркер сам себя притормозил); причина торможения — в логах DEV.
- **ПДн и сроки (ICO: storage limitation / minimisation):** исходный файл — 24 ч после финального статуса (максимум 7 дней для
  диагностики), результат — 30 дней; email до T9 НЕ собирать (поля в форме нет; колонка — в T9); `ip_hash` в задании не хранить (лимитер
  ведёт свои счётчики); после удаления файла — `input_path=null`, `input_deleted_at`; ошибка unlink оставляет запись для повтора
  (инвариант `modules/retention/run.ts`). Сроки — env, по умолчанию эти.
- **Утечка ключа ссылки:** на `/try/*` Метрику и Вебвизор не грузить вовсе (или маска `/try/*` в `metrikaSafeUrl` + clean=false);
  заголовки `Referrer-Policy: no-referrer`, `Cache-Control: private, no-store`; `result_version` → `ETag`.
- **Деньги:** суточный потолок заданий 30 (30 × $0,10 = $3), не 50.
- **Тесты T-A дополнительно:** reclaim одновременно со старым heartbeat/result/fail; ABA с тем же `worker_id`; граница истечения
  lease; исчерпание попыток; повтор result; конкурентная постановка не пробивает лимит очереди 5; chunked-загрузка, ложный
  `Content-Length`, лимит ±1 байт, обрыв, ошибка БД — без `.part` и сирот; публичные ответы без `input_path`, текста объявления,
  lease/token, worker, деталей ошибок; traversal/symlink через `input_path`; неверный Bearer и пустой env; retention: файл удалён —
  результат жив, потом результат → 410; ошибка unlink → повтор.

## Таблица `trial_jobs` (`db/init/022-trial-jobs.sql` + `db/schema.ts`)
`id text pk` · `kind text 'floorplan'` · `status text` (`queued|running|done|failed|cancelled|expired`) · `stage text`
(`queued|raster|labels|walls|repair|export|done`) · `stages jsonb` ([{stage, at}] — времена ставит прод по heartbeat) ·
`attempt int 0` · `max_attempts int 2` · `next_run_at timestamptz` · `lease_until timestamptz` · `lease_token text` (ограждение:
result/heartbeat принимаются только с текущим) · `worker_id text` · `heartbeat_at` · `input_hash text` (sha256 файла + текста; кэш VLM/
растра на DEV) · `input_path text` · `input_mime text` · `input_bytes int` · `listing_text text` (≤ 5000) · `email text null` (ПДн) ·
`consent_version text` · `ip_hash text` · `budget_usd numeric 0.10` · `spent_usd numeric 0` · `error_code text` · `error_detail text` ·
`result jsonb` (≤ 2 МБ) · `result_version int 0` · `created_at` · `started_at` · `finished_at` · `expires_at` (файл) ·
`result_expires_at`. Индексы: `(status, next_run_at)`, `(lease_until) where status='running'`, `(input_hash)`, `(expires_at)`.
Плюс `trial_workers(id pk, last_seen, version, breaker text)` — «жив ли воркер» для честного статуса страницы.
Захват — один `update … where id = (select id … where (status='queued' and next_run_at<=now()) or (status='running' and
lease_until<now()) order by created_at for update skip locked limit 1) returning *`; `attempt>max_attempts` → `failed/lease_lost`.

## Контракт (`contracts/trial.ts`, Zod)
- `trialStage`, `trialStatus` (enum); `trialJobView` — что видит страница: `{id,status,stage,stages,createdAt,elapsedSec,queuePos,
  workerAlive, errorCode?, resultVersion}`.
- `floorplanResult` (version: 1): `{version, units:"cm", source:{mime,pages,usedPages,imageW,imageH}, scale:{status:
  "verified"|"listing"|"not_verified", ppm, inliers, n}, panels:[{id,title, rooms:[{id,name,kind:"living"|"bedroom"|"kitchen"|
  "bathroom"|"hall"|"other", contour:[[x,y]]≥3, bbox:{x,y,w,d}, areaM2, dims?:{w,d,src:"plan"|"listing"}, flags:string[]}],
  walls:[{z0,z1, polys:[{outer,holes}]}], openings:[{kind:"door"|"window"|"opening", c:[x,y], widthCm, exterior}]}], flags,
  timings:{stage→sec}, costUsd}`. Источник формы — `tools/floorplan/bench.py:export_panel` (`model-*.json`: bands/floors/openings/
  rooms, метры) → перевод в см и сбор по комнатам в адаптере. Один и тот же JSON проверяет прод (`safeParse` в `result`) и тест Python
  (`tests/floorplan/test_pipeline.py` сверяет с выгрузкой `z.toJSONSchema` → `tests/fixtures/trial-result.schema.json`).

## Модуль стенда (`tools/floorplan/pipeline.py`, новый) — отвязка от gold/CFG
Опирается на T-20261109-04 (ветка `worktree-floorplan-bench`, ещё не в `main`): `bench.py:blind_gold(plan, image, vdir, listing_path)`
(подписи VLM `labels2` + текст объявления через `listing.py:parse_listing`/`match`), `bench.py:auto_cfg(img)` вместо `CFG[plan]`,
`run_plan(plan, inputs, outdir, gold=None, cfg=None)`, `vlm.py:ask(plan, kind, out, image=None)`. **Без влития T-04 этот план не
стартует (T-B).** `pipeline.run(image_path, listing_text, workdir) -> dict`: VLM `labels2|panels|unlabeled` параллельно (потоки, сеть
— вне CPU-слота) → `blind_gold` → `run_plan(..., gold=G, cfg=auto_cfg)` под `heavy_slot` → сбор `model-*-<i>.json` в `floorplanResult`.
`scale.status`: подписи плана сошлись (`fit_scale` инлаеры ≥ 2) → `verified`; только из текста → `listing`; иначе `not_verified`
(тур есть, плашка `Scale not verified`). Потолок денег VLM — на задание (`vlm.py:CAP_USD` сейчас 0,50 на папку → параметр, 0,10).
Пути `vlm.py:INPUTS` и `bench.py` `--inputs` по умолчанию — `~/remlab-logs/...`; воркер даёт свою папку `~/remlab-logs/trial/<id>/`.

## Воркер DEV (`tools/floorplan/worker.py`, новый) и изоляция от живого демо
- Цикл: breaker → `POST /api/trial/worker/claim` → `GET …/<id>/input` (файл) → PDF→PNG → `pipeline.run` → `POST …/<id>/result`;
  heartbeat каждые 10 с (`stage`, lease +60 с); concurrency 1. Ошибка → `POST …/<id>/fail {code, retryable}`.
- `heavy_slot('trial-<id>', min_gb=2.5, timeout=60)` (`tools/ops/heavy_slot.py:heavy_slot`) — только OpenCV/починка; приоритета в
  очереди нет (строгий порядок + обгон T-79) — тот, кто ждал > 60 с, возвращает задание (`next_run_at` +30 с, `waiting_capacity`).
- Circuit breaker (не брать новое): `MemAvailable` < 3 ГБ; в очереди тяжёлых ≥ 2 ожидающих (`heavy-slot.sh --status`); 3 сбоя
  подряд → пауза 10 мин; `/health` прода не 200. Состояние — в `trial_workers.breaker` (страница пишет «DEV занят, в очереди»).
- Юнит `tools/floorplan/systemd/remlab-trial-worker.service` (пользовательский, как `tools/scout/systemd/remlab-render.service`):
  `Nice=15`, `CPUQuota=200%`, `MemoryMax=3G`, `OOMScoreAdjust=500` (хуже рендера 200 — earlyoom снимет воркер первым),
  `Restart=always`; cgroup `cpu memory pids` пользователю делегированы (проверено 09.11). Ставит `tools/floorplan/worker_install.sh`.
- Токен `TRIAL_WORKER_TOKEN`: прод `/opt/remlab/.env` (+ `docker-compose.yml` app env), DEV `~/.config/remlab/env` (как
  `mesh_audit_sync.py`). Секреты в план/банк не пишем.

## Прод: файлы к изменению
- [ ] `db/init/022-trial-jobs.sql` (новый), `db/schema.ts` (`trialJobs`, `trialWorkers`) — перед выкладкой ручной `pg_dump`.
- [ ] `contracts/trial.ts` (новый) — схемы выше.
- [ ] `lib/trial/repo.ts` (создать/чтение/claim/heartbeat/result/fail, SQL `SKIP LOCKED`), `lib/trial/auth.ts` (Bearer по образцу
  `machineOk`, fail-closed 503 без env), `lib/trial/storage.ts` (`TRIAL_DIR=/app/data/trial`, sha256, проверка сигнатур JPEG/PNG/WebP/`%PDF-`).
- [ ] `app/api/trial/route.ts` (POST multipart: файл ≤ 15 МБ, текст, email, согласие) · `app/api/trial/[id]/route.ts` (GET вид) ·
  `app/api/trial/[id]/result/route.ts` (GET JSON, `Cache-Control` по `result_version`) · `app/api/trial/worker/{claim,heartbeat,
  result,fail}/route.ts` + `app/api/trial/worker/[id]/input/route.ts` (только Bearer).
- [ ] `lib/ratelimit/index.ts:PRESETS` — `trialUpload` (3 за 10 мин и 10 в сутки с адреса; `paid:trial` — `TRIAL_DAILY_CAP` 50 в сутки);
  очередь > 5 ожидающих → 503 «busy, leave your email».
- [ ] `modules/retention/run.ts:runRetention` — `trial_files` (файл по `expires_at`), `trial_results`, email; сроки — env ⚑.
- [ ] `docker-compose.yml` — том `remlab-trial:/app/data/trial`, `traces-init` чинит и его владельца; env `TRIAL_*`.
- [ ] `caddy/Caddyfile` — `handle /api/trial` с `request_body max_size 16MB` (formData читает тело целиком; память app — 1 ГБ).
- [ ] `app/try/page.tsx` (форма), `app/try/[id]/page.tsx` (noindex), `components/trial/TrialStatus.tsx` (шаги + таймер от
  `created_at`, опрос 1,5 с; loading/error+retry/empty/success), `components/trial/GreyTour.tsx` (клиент, three 0.186.1 из
  зависимостей), `lib/trial/grey-scene.ts` (порт `tools/floorplan/render/scene.js:build` на TS: стены полосами, полы по `contour`;
  вращение/зум/«сверху»/клик по комнате в списке → камера к ней; комнаты с флагами — штриховка и «?»; плашка Codex §4
  `Automatically interpreted floor plan — verify flagged dimensions before marketing use.`).

## Лимиты пробы и хранение
Файл ≤ 15 МБ, картинка ≤ 40 Мп (PIL `MAX_IMAGE_PIXELS` на DEV), PDF ≤ 2 листа в работу (остальные — флаг `pages_skipped`),
шифрованный/битый PDF → `pdf_unreadable`; текст ≤ 5000 символов. Деньги: VLM ≤ $0,10 на задание, ≤ $3 в сутки (счёт `spent_usd`,
сверх — `budget`); повтор — максимум 2 попытки. Хранение (предложение, ⚑ владелец): исходный файл 14 дней, результат 90 дней, email —
до T9 + 30 дней; файлы не отдаются наружу никогда (только воркеру по токену), ПДн — только в базе (ADR-0256).

## Задачи (исполнителю, по порядку; оценка — рабочие часы исполнителя)
- [ ] **T-A прод-рантайм (6–8 ч):** миграция, схема, контракт, `lib/trial/*`, все `/api/trial/*`, лимиты, хранение, compose/Caddy.
  Тесты unit: два одновременных claim → одно задание (`tests/unit/trial-claim.test.ts`, `TEST_DATABASE_URL` из `.github/workflows/ci.yml`), просроченный lease
  возвращается, чужой `lease_token` → 409, сигнатура файла/размер/лимиты, Zod результата (годный/битый/2 МБ+), токен fail-closed.
- [ ] **T-B воркер + модуль стенда (6–8 ч, после влития T-04):** `pipeline.py`, `worker.py`, юнит, установщик, PDF. Тесты
  `tests/floorplan/test_pipeline.py` (A/B/C из кэша VLM → JSON проходит схему; без подписей → `not_verified`),
  `tests/floorplan/test_worker.py` (поддельный сервер: claim/heartbeat/fail/потеря lease, breaker по памяти — подмена `/proc/meminfo`).
- [ ] **T-C страницы и серый тур (5–7 ч):** `/try`, `/try/<id>`, `GreyTour`. `e2e/trial.spec.ts`: загрузка → задание в базе
  (поддельный воркер в тесте отдаёт `tests/fixtures/trial-result-A.json`) → шаги → канвас тура не пустой; ошибка/воркер мёртв — тексты.
  ⚑ снимок страниц 375×667 и компьютер — владельцу до выкладки (правило «дизайн сначала»).
- [ ] **T-D живой замер (2–3 ч):** D и E владельца через прод от загрузки, по 3 прогона (холодный/тёплый), таблица шагов; F, G —
  стресс, без гейта. Демо не просело: `remlab-render` не перезапускался, `heavy-slot.log` — без ожиданий демо по вине пробы.

## Критерии приёмки
- [ ] `pnpm typecheck && lint && test && build` зелёные; `pytest tests/floorplan` зелёный; CI после push зелёный.
- [ ] D и E: загрузка → серый тур открыт; время от загрузки до тура (с очередью) p50 ≤ 90 с, max ≤ 150 с на тёплом DEV — по
  `stages` задания (иначе — отчёт с узким местом). Таймер страницы совпадает с `finished_at − created_at` ± 2 с.
- [ ] Неуверенные комнаты — с флагом и «?»; масштаб без подтверждения → `Scale not verified`, не молчаливо.
- [ ] Новая квартира видна без сборки сайта и без `lib/partners/registry.ts`; повторная загрузка того же файла — кэш VLM (0 $).
- [ ] Убитый воркер посреди задания → задание возвращается и доделывается; два воркера не берут одно; чужой результат отвергнут.
- [ ] Ведущий глазами: тур D и E на телефоне 375×667 и компьютере (стены, полы, подписи без наездов) — скриншоты в отчёте.
- [ ] Не задеты файлы вне scope; секретов нет в git.

## Риски
- T-04 не влит или слепой путь слаб (B «хуже на пороге 125») → тур кривой; срез всё равно проверяет рантайм, качество — T1.
- Очередь тяжёлых DEV занята ночными (compose2, меши) → проба ждёт; breaker честно показывает «в очереди», цель 3 мин — p50, не SLA.
- Пик памяти стенда на большом листе неизвестен (нужен замер `peaks.tsv` в T-B) → `MemoryMax` подобрать по факту.
- VLM 429/таймаут → `retryable`, 1 повтор; потолок денег — на задание и на сутки.
- Вредный PDF/картинка-бомба → разбор только на DEV под `timeout`/`prlimit`, лимит мегапикселей.
- `formData` на 15 МБ при нескольких загрузках сразу — память app 1 ГБ; Caddy-лимит + лимит частоты.

## Definition of Done — память
- [ ] ADR: очередь `trial_jobs` и мост claim/heartbeat/result; формат `floorplanResult`; сроки хранения пробы.
- [ ] Новая область → `core/agent-trial.md` (+ строка в INDEX); `core/data-model.md`, `deployment.md` (том, env, юнит DEV).
- [ ] Уроки; `/memory-check`, оба аудита чисты.

## Лог выполнения
- 2026-11-09 — план создан (draft), ждёт «деплой» по очереди мастера (⚑ сроки хранения; ⚑ снимок страниц до выкладки).
- 2026-11-09 13:12 — Codex по плану (поправки выше, приняты); сроки хранения — по Codex (короче прежних 14/90, риск меньше); in_progress; выдано T-20261109-08 = T-A (worktree `trial-runtime`). Владелец TG 327: кухня/санузел/прихожая — серыми с подписью.

## Completion summary

### Уроки

## Follow-up work
- [ ] «Введите одну длину» при `not_verified`; прогулка по полигонам; капча перед публичным лендингом; outbox письма (T9).
