---
workstream: viz / 3D-ассеты
slug: mesh-queue-orientation
title: Конвейер «отбор → меши → ориентация → сеты»: автоочередь, правило мешей в сетах, каскад фронта, страница人-проверки
status: in_progress
created: 2026-08-28
updated: 2026-08-28
completed:
---

## Цель
Методика «что отдавать на меши» работает АВТОМАТИЧЕСКИ в ежедневном конвейере; сеты собираются
только из товаров с годным мешом (этапно); фронт каждого меша — каскад
orienter+flipper → mesh_front → VLM → человек (единая приватная страница с кнопками).

## Источник задачи
Владелец 28.08 (ADR-0131): «зафиксируй методику отбора; сеты только из товаров с мешами; меши
всегда через Salad; встроить отбор в конвейер; ориентация orienter+flipper, неуверенное — GPT,
спорное — человек по единой ссылке с кнопками». Критика — Codex q25 (`_intake/codex-prompts/
q25-queue.answer.md`), фактические претензии выборочно подтверждены по коду.

## Границы с соседним планом (mesh-bulk-salad-hunyuan)
Соседний план владеет ГЕНЕРАЦИЕЙ: `tools/scout/salad/*`, `mesh_pilot.py`, `mesh_gate*.py`,
`mesh_make.py`, `mesh_render.py`, R2, PBR-приёмка. Этот план — ДО и ПОСЛЕ. Стык: (1) очередь
задач для Salad — экспорт из control plane; (2) `manifest.json` ассета — их файл, НЕ трогаем:
ориентация живёт рядом в `analysis/orientation/<contract>/` (evidence + resolution, immutable).
Согласовать с соседкой ДО кода: схема манифеста, критерий «годный» (scene_ready vs web_ready),
retry-семантика Salad (HTTP 200 + status=failed может не ретраиться — её находка q25).

## Методика отбора (канон, ADR-0131)
1. Роли — слоты сетов; текстиль/ковры/плоские настенные — нет. Направленные (~4 900 по dev-БД):
   диван/кресло/стул/тв-тумба/стеллаж/комод/стенка/витрина/камин/банкетка-со-спинкой
   (банкетка — по ПРИЗНАКУ спинки из enrichment subtype, не по роли; q25). Таблица —
   `domain/viz-fidelity-playbook.md` §Роли.
2. Ворота: in_stock + живое фото + enrichment quality ≥ 0.65 И актуальная enrichment_version
   (q25: load3 сбрасывает версию, но старый payload остаётся — генерить по нему нельзя).
3. Demand не только «кто в сетах»: члены сетов + top-K кандидатов каждого слота (после ВСЕХ
   немешевых ворот compose2: конверт, пропорции, subtype, цена) + резерв по роли/стилю/ценовой
   полке — иначе hard-гейт голодает (недирекционные вне сетов никогда не получат меш; q25).
4. Пул живой → пересчёт ежедневный; повторный прогон без изменений = 0 новых генераций.

## Блоки

### 1. Control plane — dev-Postgres (не queue.json)
Таблицы в remlab-devdb (queue.json — только версионированный ЭКСПОРТ батча для Salad):
- `mesh_demand` (wanted/not_required/superseded) — вычисляется методикой отбора;
- `mesh_jobs` (queued/submitted/running/retry_wait/failed_terminal/completed) — попытки, lease;
- `asset_revisions` (generated/acceptance_pending/accepted/rejected/superseded);
- `orientation_state` (not_required/pending/auto_resolved/vlm_pending/review_pending/human_resolved).
Идентичность входа: source-ingest фото — байты скачиваются ОДИН раз → immutable объект в R2 →
SHA-256 (URL-md5 и phash идентичностью не являются, TOCTOU; q25). Ключ генерации:
sku + source_blob_sha256 + container/weights digest + preprocess digest + params + seed + schema.
«Готово» = ключ совпал + манифест и GLB есть + checksum сошёлся + приёмка пройдена + не superseded.
Ошибка чтения R2 = unknown/retry, НЕ «нет ассета» (иначе повторная дорогая генерация).
Bootstrap: reconciliation старых локальных мешей → revisions (иначе дифф «сделано» слеп).

### 2. Правило «сеты только с мешами» — 4 фазы (q25)
Единый predicate `mesh_ready(sku)` — и в ПЕРВИЧНОЙ сборке (compose2), и в лечении
(`_slot_ok`); сейчас первичная сборка идёт мимо _slot_ok. В hard-фазах fail-closed.
- A **shadow**: метрики в отчёте сборки (полностью покрытые сеты, coverage по ролям,
  альтернатив на слот, по стилям/полкам, прогноз churn) — ничего не менять.
- B **hard-new**: новые 3D-ready сеты не публикуются без мешей; изживших не рушим.
- C **rolling**: legacy-SKU заменяется только при наличии mesh-ready замены той же пригодности.
- D **full hard**: по complete-set coverage и запасу альтернатив (не «% SKU»); момент — владелец.
Инвалидация раздельная: смена FRONT_VERSION делает stale ОРИЕНТАЦИЮ, но не годность ассета.
replace-registry остаётся отрицательным override, реестром готовности не становится.

### 3. Каскад ориентации — воркер на DEV-VM
Отдельный worker/timer (1–2 процесса, Postgres lease, flock, nice; GLB по SHA из R2 в
ограниченный локальный кэш с удалением — на VM ~15 GiB диска). 4 900 × 5с ≈ 7 CPU-часов —
Salad для этого НЕ нужен (замер, q25 согласен). Порядок на меш:
1. orienter+flipper → up/full rotation, p, prediction set;
2. кандидат применяется в памяти → mesh_front в нормализованной системе (сидячие — авторитет yaw);
3. композиция в один raw_to_canonical quaternion (det=+1, знак фиксирован) + selftest;
4. NONDIRECTIONAL по геометрии/подтипу → symmetric (не по одной роли);
5. авто-резолв: методы согласны В ТЕРМИНАХ equivalence classes (конфликт = мин. расстояние
   между классами, не разница углов; 0/180 симметричного — одно решение);
6. не уверено → VLM qwen3-vl (признаковый промпт) — ПРЕДЛАГАЕТ кандидат+evidence, не решает;
7. спорное → review_pending (человек).
Resolution в R2 (`analysis/orientation/<contract>/resolution/`): asset id, GLB SHA, quaternion,
конвенция, версии orienter/mesh_front/VLM, evidence, equivalence, автор, ts. GLB и manifest
не изменяются. `orient_selftest` + pose-contract — в CI (сейчас CI его не гоняет; q25).

### 4. Страница проверки — /lab/mesh-review (приватная, НЕ /test/)
/test/* — публичная статика (Caddyfile), для ревью не годится. Next.js страница + API:
- prod-Postgres: `mesh_review_tasks` (asset/hash, SKU, версии, ключи рендеров, варианты,
  статус) и `mesh_review_decisions` (append-only: task, choice, reviewer, ts, idempotency key);
- DEV идемпотентно POST-ит задачи → владелец кликает → DEV забирает `GET decisions?after_id=`,
  курсор двигается транзакционно после применения; решение привязано к (glb_hash, contract).
- Кнопки: 4 ракурса-yaw + «симметричен» + «неверный ВЕРХ» + «меш непригоден» + «пропустить»
  (4 yaw не чинят up — нужен отдельный выход; q25).
- Auth: cookie HttpOnly/Secure/SameSite=Strict + CSRF/Origin; machine-секрет для DEV отдельно;
  токены в query string НЕ использовать (существующий trace/admin.ts — плохой образец, fail-open).
- Новая таблица = миграция в ОБА пути деплоя: drizzle (CI glob) и ручной deploy.sh (явный список).

### 5. Починка сломанного шага MESH_QUEUE (refresh_daily.sh)
Подтверждено: `$VENV` не определён (set -u — упадёт), путь относительный после cd,
`role.split(' ')[0]` режет «стол обеденный» в «стол», stamp пишется ДО шага. Шаг переписать
вызовом `mesh_queue.py` (control plane), исправив всё перечисленное.

## Гейты приёмки (сокращённо из q25 §7)
- Два одинаковых прогона подряд → 0 новых заданий; смена одного фото → ровно 1 ревизия.
- Crash/restart не теряет и не дублирует job; таймаут R2 не вызывает регенерацию.
- silent_wrong_front среди auto = 0 (мера — human-вердикты); стратифицированный gold-set
  по ролям (пилот 481) калибрует пороги и ДОКАЗЫВАЕТ объём review («десятки») до масштаба.
- Dry-run hard-гейта не разрушает текущие 126 сетов сверх согласованного порога.
- Review API: идемпотентность, superseded, auth/CSRF, cursor-resume — тесты.

## Файлы к изменению
- [ ] `tools/scout/mesh_queue.py` (новый) — отбор+demand+дифф+экспорт батча.
- [ ] `tools/scout/orient_worker.py` (новый) — каскад ориентации (драйвер orienter из scratchpad → в репо).
- [ ] `tools/scout/refresh_daily.sh` — шаг MESH_QUEUE переписан.
- [ ] `tools/scout/sets_incremental.py` + `compose2.py` — единый predicate mesh_ready (фазы за флагом).
- [ ] `tools/scout/mesh_front.py` — банкетка по subtype, не роли.
- [ ] dev-БД: 4 таблицы control plane (SQL-миграция в tools/scout).
- [ ] `app/lab/mesh-review/` + `app/api/lab/mesh-review/` + `db/schema.ts` + миграции (оба пути).
- [ ] CI: `orient_selftest` + pose-contract в `ci.yml`.
- [ ] `.memory_bank/domain/viz-fidelity-playbook.md` — методика (записана).

## Порядок
1. Согласование стыка с соседним планом (манифест, критерий годности, retry Salad).
2. Control plane + mesh_queue + починка шага; гейт «0 лишних генераций».
3. Orient-worker + resolution в R2 + CI-тесты.
4. Review-страница + API + пилотная партия спорных.
5. Shadow-метрики сетов → отчёт владельцу → решение о фазе B.
