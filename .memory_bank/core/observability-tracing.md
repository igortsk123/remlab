---
tier: 1
topic: observability-tracing
scope: Трейсинг AI-пайплайна — лог каждого вызова LLM, «номер генерации», разбор по номеру, сжатие
tier2: ""
updated: 2026-07-02
importance: high
source: manual
status: working
source_of_truth: canonical
last_verified: 2026-07-02
review_after: ""
---

# Observability — Tracing AI-пайплайна (ADR-0013)

> Цель: по «номеру генерации» за секунды восстановить весь путь прогона (модели, промпты, настройки,
> вход/выход, картинки, время, стоимость, ошибки). Живёт под правилом `.claude/rules/pipeline-tracing.md`.

## Сущности (БД)
- `generation_runs` — прогон = один запуск превью. `seq` = человекочитаемый **номер генерации** (sequence
  `generation_seq`). Хранит pipelineId+version, статус, итоги (время/стоимость), meta.
- `generation_steps` — шаг = один вызов LLM: stepName, kind (vision/image/text), provider, model,
  promptId+version+текст, params, input/output-текст, статус/ошибка, latency, cost.
- `generation_assets` — картинки (input/intermediate/output): **байты на диске** (том), в БД только
  ссылка+метаданные. Base64 в БД НЕ пишем.

## Как захватывается (ключевой инвариант)
Единая точка — **слой провайдеров**. `getImageProvider()/getVisionProvider()` (`lib/providers/index.ts`)
оборачивают провайдера в инструментированную версию (`lib/providers/traced.ts`): каждый вызов LLM
логирует шаг в активный прогон. Прогон открывается в оркестраторе (`modules/generation-job`) через
`runWithTrace` (`lib/trace/recorder.ts`), контекст — AsyncLocalStorage (`lib/trace/context.ts`),
поэтому вложенные вызовы видят прогон без протаскивания ctx. Нет прогона → passthrough (тесты/скрипты).
→ Смена модели/промпта/шага НЕ требует правки системы лога: новый вызов логирует себя сам.

## Реестры (версионирование)
- `lib/prompts/registry.ts` — промпты как версионируемые шаблоны (id+version+build). Модули берут промпт
  отсюда; трейс пишет promptId+version+рендер. Меняешь текст → бампни version.
- `lib/pipelines/registry.ts` — сценарии (упорядоченные шаги + модель + промпт). Дефолт **`preview-v2`**
  (интерактивный флоу): «генерация» = **restyle по выбору пользователя + ideas**; **analyze вынесен в
  отдельный ПРЕД-шаг** (`runAnalyze`, вне `runWithTrace` → не попадает в трейс, у него нет номера).
  `preview-v1` (analyze+restyle+ideas одним прогоном) оставлен для истории старых трейсов.
  Точка расширения под новые модели (Nano→GPT→ControlNet/SD) и разные пути под сценарии.

## Сжатие (экономия токенов/диска)
`lib/images/compress.ts` → сервис **imagor** (Go+libvips, internal-only на remlab-net, как в SUP2/ADR D18).
Фото уменьшается (`fit-in 1536`, webp q80) ПЕРЕД LLM: меньше пикселей → меньше токенов; то, что реально
ушло в LLM, и сохраняется как input-ассет. `IMAGOR_BASE_URL` не задан → отправляем исходник (best-effort).

## Разбор («генерация N»)
- Скилл `/trace` (`.claude/skills/trace/`) — триггер «генерация N» → краткий+подробный вид + фото.
- CLI: `pnpm trace <N>` (`tools/trace-show.mjs`) — из БД, печатает путь + пути к файлам-ассетам.
- Admin-роут `GET /api/trace/<N>` (JSON+asset URLs) и `GET /api/trace/asset/<id>` (байты) —
  за `TRACE_ADMIN_TOKEN` (dev — открыто). Кнопка «Сообщить о проблеме» → `POST /api/trace/report`.
- **Ссылки на картинки — подписанные (signed), не токен-в-URL** (`lib/trace/sign.ts`): `[seq]`-роут
  отдаёт абсолютные `url` вида `<TRACE_PUBLIC_BASE_URL>/api/trace/asset/<id>?exp=..&sig=..` (HMAC-SHA256
  от id+exp на ключе `TRACE_ADMIN_TOKEN`, TTL 7д — `TRACE_ASSET_TTL_MS`). Владелец открывает в браузере,
  админ-токен НЕ раскрывается. Asset-роут пускает по валидной подписи ИЛИ по admin-гарду. Формат вывода
  `/trace`: по каждому шагу — дословный промпт + дословный ответ модели + ссылки input/intermediate/output.

## Хранение/приватность
- Том `remlab-traces` → `/opt/remlab/data/traces` (app rw как `/app/data/traces`, imagor ro как `/mnt/data`).
  `TRACE_DIR` в env. Локально — `./.data/traces` (в .gitignore).
- ⚠️ **Гоча (была причиной «0 ассетов» на проде):** app работает под `nextjs` (uid 1001), а свежий
  named-том принадлежит root → запись картинок падала молча (best-effort глушил EACCES). Фикс: сервис
  `traces-init` в compose (под root `chown -R 1001:65533 /app/data/traces` перед стартом app, идемпотентно).
  `saveAsset` теперь при сбое пишет `console.warn` (без секретов), чтобы такой класс багов не прятался.
  Картинки для прогонов ДО фикса невосстановимы (байты не захватывались).
- Ретеншн: `TRACE_RETENTION_DAYS` (дефолт 90) — `pnpm trace:prune` (`tools/trace-prune.mjs`),
  вешается на серверный таймер `remlab-cleanup` (ops-шаг деплоя). Фото — ПДн (TODO legal, не блокируемся).
- Логирование best-effort: ошибка записи/диска НЕ валит пайплайн. Секреты (API-ключи) в лог не пишем.

**Ключевые файлы:** `lib/trace/*`, `lib/providers/traced.ts`, `lib/prompts/registry.ts`,
`lib/pipelines/registry.ts`, `lib/images/compress.ts`, `db/schema.ts` (+ `tools/migrate.mjs`,
`db/init/003-traces.sql`), `app/api/trace/*`. Правило: `.claude/rules/pipeline-tracing.md`.
