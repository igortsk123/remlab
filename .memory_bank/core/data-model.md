---
tier: 1
topic: data-model
scope: Реальная схема БД (4 таблицы), изоляция сессий, миграции, pgvector
tier2: "../../docs/tech-spec-ts-stack.md"
updated: 2026-07-09
importance: high
source: manual
status: working
source_of_truth: supporting
last_verified: 2026-07-09
review_after: ""
---

# Data Model — Tier 1 сводка

Истина — код: `db/schema.ts` (Drizzle) + `db/init/*.sql`. Форма агрегата — `contracts/project.ts` (Zod).

## Реализовано: 4 таблицы
- **projects** (ADR-0008) — весь проект комнаты одним jsonb `data` (brief, photos как base64 data-url, styleProfile, analysis/objectChoices, previewImage, ideas, items с `locked`, budget, `paid`, status started…paid) + колонка `session_id` (индекс).
- **generation_runs / generation_steps / generation_assets** (ADR-0013) — трейсинг: прогон (seq, pipeline_id/version, status, total_latency_ms/cost_usd) → шаг = один LLM-вызов (provider/model/prompt*/params, latency_ms, cost_usd) → ассеты (role input|intermediate|output, storage_key под TRACE_DIR; байты на диске). Sequence `generation_seq` — «номер генерации».

## Изоляция и доступ
- **RLS НЕТ** (ни ENABLE ROW LEVEL SECURITY, ни policy; одна роль remlab). Изоляция — фильтр `session_id` в приложении (`PgRepository.listBySession`).
- **Известный риск:** `PgRepository.get(id)` (`modules/store/pg-repository.ts`) читает проект по UUID БЕЗ проверки сессии — знание id даёт чужой проект.

## Расширения и миграции
- pgvector **установлен, но не используется** (`001-extensions.sql`: vector + pg_trgm; vector-колонок в схеме нет).
- Миграции = идемпотентный raw SQL: `db/init/*.sql` (initdb свежего тома) + `deploy.sh` шаг 5b (psql в контейнере) + `tools/migrate.mjs` (`pnpm db:migrate`). drizzle-kit нет; **down-миграций нет**.
- БД — контейнер pgvector/pg17 (ADR-0002).

## Цель (спека §4) — НЕ реализовано
Целевая нормализованная модель: `users → properties → rooms → room_projects → result_versions`; `style_profiles`, `uploaded_images`, `detected_objects`; `generation_jobs`/`generated_images`; каталог (`products`, `product_embeddings vector(768)`, `price_snapshots`, `product_previews`); Cost Engine (`work_rates`…); `payments` (provider_payment_id); RLS + hnsw/ivfflat-индексы. Всё это — план: в коде живёт полями jsonb-агрегата или отсутствует.

**Tier 2:** `../../docs/tech-spec-ts-stack.md` §4 — целевые таблицы (только имена, полной схемы полей там нет) + `../../docs/cjm-ux-v0.2.md` §13.
