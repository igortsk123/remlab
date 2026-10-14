---
tier: 1
topic: data-model
scope: Схема БД, миграции, pgvector
tier2: "../../docs/tech-spec-ts-stack.md"
updated: 2026-10-14
importance: high
source: manual
status: working
source_of_truth: supporting
last_verified: 2026-09-05
review_after: 2026-12-05
---

# Data Model — Tier 1 сводка

Истина — код: `db/schema.ts` (Drizzle) + `db/init/*.sql`; агрегаты — `contracts/*` (Zod).

## Реализовано (прод-БД)
- **projects** (ADR-0008) — проект комнаты jsonb `data` + `session_id`.
- **generation_runs / steps / assets** (ADR-0013) — трейсинг: прогон → шаг (LLM-вызов) → ассеты
  (TRACE_DIR); `generation_seq` — номер генерации.
- **estimates / link_clicks / link_routes** (ADR-0016, М1) — смета jsonb + лог кликов `/go/` +
  маршруты реф (домен→шаблон, late-binding, пусто→прямая).
- **leads / lead_messages** (К6, TG-бот) — лиды «найти дешевле» + переписка (in|out,
  `admin_tg_message_id`); согласие с версией (`consent_version`), срок — `LEADS_RETENTION_DAYS` (`modules/retention/run.ts`).
- **style_results** (ADR-0038) — итог квиза: `session_id` PK → `style`, upsert; «Мой стиль» в `/lab`.
- **mesh_review_* / mesh_audit_*** (`007-mesh-review.sql`, `010-mesh-audit.sql`) — ручная проверка мешей
  (`/lab/mesh-review`, `/lab/mesh-audit`, ADR-0188…0194); детали — Tier 2.
- **rate_limits / share_requests** (`013-security.sql`, ADR-0256); **managers / sends / send_events / signal_outbox**
  (`014`, ADR-0257); **flat_configs** (`015`, `020`: hidden, collection_id); **collections** (`016`); **page_counters / partner_keys** (`017`); **retention_runs** (`018`); **owner_reviews** (`019`).

## Изоляция и доступ
- **RLS НЕТ** (одна роль remlab). Изоляция — фильтр `session_id` в приложении (`listBySession`).
- **Риск:** `PgRepository.get(id)` (`modules/store/pg-repository.ts`) читает по UUID без проверки сессии.

## Расширения и миграции
- pgvector установлен, но не используется (`001-extensions.sql`).
- Миграции = идемпотентный raw SQL `db/init/NNN-*.sql`; CI и оба деплоя прогоняют их одним
  `tools/apply-db-init.sh`. Здесь ТОЛЬКО прод-схема; каталожные — `tools/scout/NNN-*.sql`, `bootstrap.sql` и
  DDL в скриптах (`mesh_queue.py`, `load3.py`) → дев-БД (ADR-0179). drizzle-kit и down-миграций НЕТ (`tools/migrate.mjs` — устаревший). БД — контейнер pgvector/pg17 (ADR-0002).

## Дев-БД каталога (`remlab-devdb`, `tools/scout/`)
`products` (+ `availability_state/page_state/basis`, ADR-0186), `asset_revisions`, `orientation_state`,
`product_photo_current`, `image_url_hd` (ADR-0182), `mesh_generations` (ADR-0188), `mesh_quarantine` (012, ADR-0276),
`room_catalog`/`room_catalog_runs` (013, спальня, ADR-0279) — [[catalog]],
[[stock-and-dims]], [[mesh-pipeline]].

**Tier 2:** `../../docs/tech-spec-ts-stack.md` §4.
