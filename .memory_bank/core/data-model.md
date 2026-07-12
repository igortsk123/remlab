---
tier: 1
topic: data-model
scope: Реальная схема БД (таблицы), изоляция сессий, миграции, pgvector
tier2: "../../docs/tech-spec-ts-stack.md"
updated: 2026-07-12
importance: high
source: manual
status: working
source_of_truth: supporting
last_verified: 2026-07-12
review_after: ""
---

# Data Model — Tier 1 сводка

Истина — код: `db/schema.ts` (Drizzle) + `db/init/*.sql`. Форма агрегатов — `contracts/*` (Zod).

## Реализовано (основные таблицы)
- **projects** (ADR-0008) — проект комнаты одним jsonb `data` (brief/photos/styleProfile/analysis/ideas/items/budget/paid/status) + колонка `session_id` (индекс).
- **generation_runs / generation_steps / generation_assets** (ADR-0013) — трейсинг: прогон (seq, pipeline*, status, latency/cost) → шаг = один LLM-вызов (provider/model/prompt*/params, latency/cost) → ассеты (role, storage_key под TRACE_DIR; байты на диске). Sequence `generation_seq` = «номер генерации».
- **estimates / link_clicks / link_routes** (ADR-0016, М1) — смета одним jsonb + лог кликов `/go/` (приоритет реф-регистраций) + маршруты реф (домен→шаблон, late-binding, пусто→прямая).
- **leads** (К6) — лиды «найти дешевле» (email/channel/url/kind/session_id); email пишем только по согласию, ПДн — TODO.

## Изоляция и доступ
- **RLS НЕТ** (одна роль remlab). Изоляция — фильтр `session_id` в приложении (`listBySession`).
- **Известный риск:** `PgRepository.get(id)` (`modules/store/pg-repository.ts`) читает по UUID БЕЗ проверки сессии — знание id даёт чужой проект.

## Расширения и миграции
- pgvector **установлен, но не используется** (`001-extensions.sql`: vector + pg_trgm; vector-колонок в схеме нет).
- Миграции = идемпотентный raw SQL: `db/init/*.sql` (initdb свежего тома) + `deploy.sh` шаг 5b (psql в контейнере) + `tools/migrate.mjs` (`pnpm db:migrate`). drizzle-kit нет; **down-миграций нет**.
- БД — контейнер pgvector/pg17 (ADR-0002).

## Цель (спека §4) — НЕ реализовано
Нормализованная модель (users→properties→rooms→room_projects→result_versions; каталог products/product_embeddings `vector(768)`/price_snapshots; Cost Engine work_rates; payments; RLS + hnsw). Пока — поля jsonb-агрегата или отсутствует.

**Tier 2:** `../../docs/tech-spec-ts-stack.md` §4 (целевые таблицы — имена) + `../../docs/cjm-ux-v0.2.md` §13.
