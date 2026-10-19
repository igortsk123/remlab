---
tier: 1
topic: observability-tracing
scope: Трейсинг AI-пайплайна — лог, разбор
tier2: ../domain/observability.md
updated: 2026-10-19
importance: high
source: manual
status: working
source_of_truth: canonical
last_verified: 2026-10-18
review_after: 2026-12-05
---

# Observability — Tracing AI-пайплайна (ADR-0013)

> По «номеру генерации» восстановить весь путь: промпты, вход/выход, картинки, время, стоимость,
> ошибки. Правило: `.claude/rules/pipeline-tracing.md`.

## Сущности (БД, `db/schema.ts`)
`generation_runs` (прогон; `seq` = номер генерации) → `generation_steps` (вызов LLM: промпт
id+version+текст, I/O, latency, cost) → `generation_assets` (байты на диске, в БД ссылка;
base64 НЕ пишем).

## Захват (инвариант)
Единая точка — слой провайдеров: `getImageProvider()/getVisionProvider()` (`lib/providers/`)
возвращают обёртку `traced.ts` — каждый вызов LLM логирует себя сам (исключение-долг: `lib/calc/link-parse-ai.ts`
зовёт OpenAI мимо трейса — `.claude/rules/pipeline-tracing.md`). Прогон открывает
`modules/generation-job` через `runWithTrace`; контекст — AsyncLocalStorage; нет прогона →
passthrough. Смена модели/промпта/шага НЕ требует правки лога.

## Реестры
- `lib/prompts/registry.ts` — промпты id+version; меняешь текст → бампни version.
- `lib/pipelines/registry.ts` — дефолт **`preview-v2`**: «генерация» = restyle по выбору
  пользователя + ideas; analyze — ПРЕД-шаг (`runAnalyze`, вне трейса, без номера).
  `preview-v1` — история.

Аналитика без ключей и проверок — Tier 2 § Аналитика.

## Сжатие
`lib/images/compress.ts` → imagor (fit-in 1536, webp q80) перед LLM; что ушло в LLM — то и input-ассет; без `IMAGOR_BASE_URL` — исходник.

## Разбор («генерация N»)
Скилл `/trace`; CLI `pnpm trace <N>`; `GET /api/trace/<N>`, `/api/trace/asset/<id>` за `TRACE_ADMIN_TOKEN` (заголовок
`x-trace-token`; без токена в проде закрыто, ADR-0256). Ссылки на картинки — подписанные (HMAC, TTL 7д).

## Хранение/приватность
Named-том `remlab-traces` (bind-mount нет): в app `/app/data/traces` = `TRACE_DIR` (локально `./.data/traces`). Ретеншн
`TRACE_RETENTION_DAYS` (90) — ежедневно 04:10 UTC таймер `remlab-retention` → `POST /api/internal/retention` →
`modules/retention/run.ts`; `pnpm trace:prune` — ручной дубль. Ошибка записи не валит пайплайн, считается
`traceWriteFailures` в `/api/health` (`lib/trace/failures.ts`); секреты не пишем. Права тома, `traces-init` — Tier 2. Фото — ПДн (TODO legal).

**Tier 2:** `../domain/observability.md` — env, подписанные URL, imagor, роуты, гочи.
