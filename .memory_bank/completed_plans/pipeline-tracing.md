---
workstream: observability / pipeline-tracing
slug: pipeline-tracing
status: completed
created: 2026-07-02
updated: 2026-07-02
completed: 2026-07-02
---

## Цель
Сквозная система логирования (трейсинга) AI-пайплайна: каждый запрос в LLM записывается
по шагам (что отправили → что получили, включая картинки), у каждого прогона есть служебный
номер (#741), и по этому номеру можно за секунды получить краткий и подробный разбор всего пути.
Архитектура заложена так, что смена модели / промпта / самого пайплайна автоматически остаётся
залогированной, без переписывания системы логов.

## Источник задачи
Владелец: будет много тестов пайплайна распознавания; модели будут меняться
(Nano Banana → ChatGPT → ControlNet/SD), промпты переписываться регулярно, пайплайны — разные
под сценарии. Нужно: (1) подробный лог каждого запроса в разрезе пайплайна (вход/выход/настройки/
модель на каждом шаге, включая промежуточные фото); (2) номер генерации на экране; (3) по номеру —
краткий + подробный разбор (промпт, путь, модели, ссылки на исходное и итоговое фото); (4) команда/
скилл, чтобы «генерация 741» сразу triggered разбор; (5) правило в Memory Bank: меняется пайплайн/
модель/промпт → система логирования обязана оставаться полной; (6) на MVP — кнопка «сообщить о
проблеме», которая шлёт номер прогона со всем логом.

## Ключевые архитектурные решения (черновик, часть — на выбор владельца)
1. **Единая точка захвата — слой провайдеров.** Любой вызов LLM идёт через
   `getImageProvider()/getVisionProvider()`. Оборачиваем провайдеры в «инструментированную»
   версию, которая на каждый вызов автоматически пишет шаг в активный прогон. Это и есть гарантия
   «поменяли пайплайн → всё равно залогировано»: новый вызов модели логирует себя сам.
2. **Ambient-контекст через AsyncLocalStorage** (а не протаскивание ctx через все функции): прогон
   открывается в оркестраторе, дальше все вложенные вызовы видят «текущий прогон» без правок сигнатур.
3. **Три сущности данных:** `generation_runs` (прогон = один запуск пайплайна, есть человекочитаемый
   `seq` #741), `generation_steps` (шаг = один вызов модели), `generation_assets` (картинки:
   вход/промежуточные/выход — байты на диске, в БД только ссылка+метаданные). Base64 в БД НЕ пишем.
4. **Картинки — файлы на диске, не в БД** (дёшево, я могу читать напрямую при разборе). Dev:
   `./.data/traces/<run>/...`; прод: том `/opt/remlab/data/traces` (добавить в compose). Отдаём через
   защищённый роут `/api/trace/asset/[id]`. → **решение владельца: диск (реком.) vs БД vs S3-подобное.**
5. **Реестр промптов (Phase C)** и **реестр пайплайнов/сценариев (Phase D)** — версионируемые, чтобы
   «под каждый сценарий свой промпт/пайплайн» и чистое сравнение тестов. Трейс пишет id+версию.
6. **Разбор по номеру** — через admin-роут `/api/trace/[seq]` (JSON + URL картинок, за admin-токеном)
   и скилл `/trace`, который умеет «генерация 741». Даёт кликабельные ссылки + я показываю фото.

## Скоуп — фазы (подпланы). Phase A+B — минимально ценный срез.

### Phase A — Ядро трейсинга (фундамент)
- Схема БД: `generation_runs`, `generation_steps`, `generation_assets` + sequence `generation_seq`.
- `lib/trace/` — RunContext (AsyncLocalStorage), `openRun()/closeRun()`, `recordStep()`, `saveAsset()`.
- Инструментированные обёртки провайдеров: latency, статус/ошибка, модель, промпт, вход/выход,
  оценка стоимости; картинки входа/выхода сохраняются как assets.
- Экспорт модели из провайдера (`imageModel`/`textModel` в `lib/providers`), чтобы логировать «какая LLM».
- Оркестратор `runPreview` открывает прогон, отдаёт `seq` в Project; номер #741 виден на `/preview`.
- Оценка стоимости: `lib/pricing.ts` (модель → цена за картинку / за 1k токенов).

### Phase B — Инструменты разбора («генерация 741»)
- `tools/trace-show.mjs` — по `seq` печатает КРАТКИЙ + ПОДРОБНЫЙ разбор из БД (+ пути к фото).
- `pnpm trace <n>` (package.json script).
- Admin-роут `/api/trace/[seq]` (JSON + asset URLs, защита admin-токеном из env).
- Скилл `.claude/skills/trace/` — распознаёт «генерация N» / `/trace N`, дёргает разбор,
  показывает исходное и итоговое фото + путь (кратко и подробно).

### Phase C — Реестр промптов (версионирование)
- `lib/prompts/registry.ts` — промпт = `{ id, version, build(vars) }`. Модули берут промпты отсюда
  (перенести хардкод из `visual-generation`, `room-analysis`, `ideas`). Трейс пишет promptId+version.

### Phase D — Реестр пайплайнов/сценариев (сменные модели и пути)
- `lib/pipelines/registry.ts` — сценарий = упорядоченные шаги `{stepName, kind, model, promptId, params}`.
- Исполнитель прогоняет шаги, передавая выход дальше. Оркестратор выбирает сценарий по id
  (дефолт `preview-v1`). Трейс пишет pipelineId+version и модель на каждом шаге. Это даёт
  Nano Banana → GPT → ControlNet/SD и разные пайплайны под сценарии без переписывания оркестратора.

### Phase E — Пользовательский репорт + хранение
- Кнопка «сообщить о проблеме» на `/preview` → шлёт `runId` (+ комментарий) в лог/аналитику.
- Ретеншн ассетов: env `TRACE_RETENTION_DAYS`, чистка через существующий `remlab-cleanup`.
- TODO(legal): фото — ПДн; отметить, не реализовывать юр-логику (CLAUDE.md).

### Phase F — Дисциплина (чтобы логи не отставали от пайплайна)
- Path-scoped правило `.claude/rules/pipeline-tracing.md` (scope: `modules/**`, `lib/providers/**`,
  `lib/prompts/**`, `lib/pipelines/**`): меняешь модель/промпт/шаг → трейсинг обязан остаться полным,
  версии в реестрах бампнуты.
- Memory Bank: `core/observability-tracing.md` (Tier 1) + запись в `INDEX.md` (no-orphan) + ADR в
  `decisions.md`/`docs/DECISIONS.md`. Обновить `project-state.md`, `core/access-and-integrations.md`.

## Скоуп — что НЕ входит
- Полноценный UI-дашборд трейсов (пока разбор через скилл/скрипт/admin-роут).
- Стриминг реального времени статуса шага (пока по факту завершения).
- Юридическая логика ПДн (только TODO).
- Перенос генерации в фон (Inngest) — отдельный план; трейсинг совместим с ним.

## Файлы к изменению (черновик; финализируется на «деплой»)
- [ ] `db/schema.ts` — таблицы runs/steps/assets + sequence; миграция + `db/init/003-traces.sql`.
- [ ] `lib/trace/context.ts`, `lib/trace/recorder.ts`, `lib/trace/assets.ts` — ядро.
- [ ] `lib/providers/index.ts` + `types.ts` + `gemini.ts` + `fake.ts` — инструментированные обёртки,
      экспорт модели.
- [ ] `modules/generation-job/index.ts` — открыть/закрыть прогон, вернуть `seq`.
- [ ] `contracts/project.ts` — поле `generationSeq`/`traceRunId` в Project.
- [ ] `app/**/preview` — показать «Генерация #741».
- [ ] `lib/pricing.ts` — оценка стоимости.
- [ ] `tools/trace-show.mjs`, `package.json` (script), `app/api/trace/[seq]/route.ts`,
      `app/api/trace/asset/[id]/route.ts`.
- [ ] `.claude/skills/trace/SKILL.md` (+ хелпер).
- [ ] `lib/prompts/registry.ts` (Phase C), `lib/pipelines/registry.ts` (Phase D).
- [ ] `.claude/rules/pipeline-tracing.md`, `.memory_bank/core/observability-tracing.md`, `INDEX.md`,
      `decisions.md`, `docs/DECISIONS.md`, `project-state.md`, `core/access-and-integrations.md`.
- [ ] `docker-compose.yml` — том для `/opt/remlab/data/traces` (Phase A/E).

## Критерии приёмки
- [ ] Один запуск превью создаёт ровно один run со всеми шагами (analyze, generate, ideas) и ассетами.
- [ ] На экране виден номер #N; по нему `pnpm trace N` и скилл дают краткий+подробный разбор + 2 фото.
- [ ] Смена модели/промпта отражается в логе без правок системы логирования (проверить подменой модели).
- [ ] Секреты не логируются (ключ API не попадает в шаги). Base64 не в БД.
- [ ] Lint / typecheck / build / тесты зелёные; нет отладочного вывода; scope не превышен.
- [ ] Memory Bank + правило + ADR обновлены.

## Решения владельца (нужны к «деплой»)
1. Хранилище картинок: **диск (реком.)** / БД / внешнее объектное хранилище.
2. Объём первого захода: **Phase A+B** (быстрый ценный срез) или сразу A→D.
3. Ретеншн трейсов на проде (напр. 90 дней) — можно позже.

## Лог выполнения
- 2026-07-02 — план создан (draft).
- 2026-07-02 — деплой: реализованы все фазы A–F. Владелец: диск + все фазы сразу + ретеншн 90.
  typecheck/lint/build зелёные, 9 unit passed (+ новый `trace.test.ts`). Ветка `feature/pipeline-tracing`.

## Completion summary
Реализовано (ветка `feature/pipeline-tracing`, НЕ смёрджено/НЕ задеплоено в прод):
- **Схема:** `db/schema.ts` + `tools/migrate.mjs` + `db/init/003-traces.sql` — `generation_runs`(seq)/`steps`/`assets` + sequence.
- **Ядро:** `lib/trace/{types,context,store,recorder,assets,admin}.ts` (PG + in-memory, AsyncLocalStorage, best-effort).
- **Захват:** `lib/providers/traced.ts` оборачивает провайдеров (модель наружу: `imageModel`/`textModel`, `meta` во входе);
  `lib/providers/index.ts` возвращает инструментированные. `lib/pricing.ts` — оценка стоимости.
- **Реестры:** `lib/prompts/registry.ts` (3 промпта, version), `lib/pipelines/registry.ts` (`preview-v1`).
- **Сжатие:** `lib/images/compress.ts` (imagor) — перед LLM; compose: сервис `imagor` + том `remlab-traces`.
- **Оркестратор:** `modules/generation-job` обёрнут в `runWithTrace`, пишет `generationSeq`/`traceRunId` в Project.
- **Разбор:** `/api/trace/[seq]`, `/api/trace/asset/[id]`, `/api/trace/report`, `tools/trace-show.mjs` (`pnpm trace`),
  скилл `.claude/skills/trace/`. UI: «Генерация #N» + кнопка «Сообщить о проблеме» на `/preview`.
- **Ретеншн:** `tools/trace-prune.mjs` (`pnpm trace:prune`, `TRACE_RETENTION_DAYS=90`).
- **Дисциплина/память:** `.claude/rules/pipeline-tracing.md` (+ в CLAUDE.md), `core/observability-tracing.md`,
  INDEX/README/decisions/DECISIONS/project-state/access-and-integrations/.env.example, ADR-0013.

Упрощено: исполнение шагов остаётся в оркестраторе (реестр пайплайна = версия+точка расширения, не data-driven
executor — для 3 фиксированных шагов это избыточно). Мультипровайдерность (GPT/ControlNet) — это seam: добавить
провайдер за интерфейсами + привязать в сценарии (фиктивных провайдеров не заводил).

## Follow-up work (прод-деплой — отдельно, owner-gated, беречь VPN-ноду)
- [ ] `pnpm db:migrate` на прод-БД (создаёт trace-таблицы+sequence). Бэкап перед этим.
- [ ] Развернуть сервис `imagor` + том `remlab-traces` (проверить образ `shumc/imagor` под **arm64**).
- [ ] Env на сервере: `TRACE_DIR`, `IMAGOR_BASE_URL`, `TRACE_ADMIN_TOKEN`, `TRACE_RETENTION_DAYS`.
- [ ] Повесить `pnpm trace:prune` на таймер `remlab-cleanup` (ops-скрипт с доступом к тому).
- [ ] Мердж ветки в `main` (владелец).
- [ ] Дашборд трейсов (UI) и экспорт «набор тестов → сравнение оптимума» — при росте объёма тестов.
- [ ] TODO(legal): фото — ПДн (ретеншн/согласие) — не блокируемся.
