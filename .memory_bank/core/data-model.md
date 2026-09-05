---
tier: 1
topic: data-model
scope: Схема БД, миграции, pgvector
tier2: "../../docs/tech-spec-ts-stack.md"
updated: 2026-09-05
importance: high
source: manual
status: working
source_of_truth: supporting
last_verified: 2026-09-05
review_after: 2026-12-05
---

# Data Model — Tier 1 сводка

Истина — код: `db/schema.ts` (Drizzle) + `db/init/*.sql`. Форма агрегатов — `contracts/*` (Zod).

## Реализовано (прод-БД)
- **projects** (ADR-0008) — проект комнаты jsonb `data` + `session_id`.
- **generation_runs / steps / assets** (ADR-0013) — трейсинг: прогон → шаг (LLM-вызов) → ассеты
  (TRACE_DIR); `generation_seq` = «номер генерации».
- **estimates / link_clicks / link_routes** (ADR-0016, М1) — смета jsonb + лог кликов `/go/` +
  маршруты реф (домен→шаблон, late-binding, пусто→прямая).
- **leads / lead_messages** (К6, TG-бот) — лиды «найти дешевле» + переписка (in|out,
  `admin_tg_message_id`); email только по согласию, ПДн — TODO.
- **style_results** (ADR-0038) — итог квиза: `session_id` PK → `style`, upsert; «Мой стиль» в `/lab`.
- **mesh_review_tasks / mesh_review_decisions** (`007-mesh-review.sql`, `/lab/mesh-review`) — ручная
  проверка ориентации мешей: задачи от DEV-конвейера (`task_key` = `sku|glb_sha|contract`), решения
  append-only по курсору `after_id` (`mesh_review_sync.py`).
- **mesh_audit_items / mesh_audit_decisions / mesh_audit_batches** (`010-mesh-audit.sql`,
  `db/schema.ts`) — ручная приёмка мешей владельцем, `/lab/mesh-audit` (ADR-0188…0194).

## Изоляция и доступ
- **RLS НЕТ** (одна роль remlab). Изоляция — фильтр `session_id` в приложении (`listBySession`).
- **Риск:** `PgRepository.get(id)` (`modules/store/pg-repository.ts`) читает по UUID без проверки сессии.

## Расширения и миграции
- pgvector **установлен, но не используется** (`001-extensions.sql`; vector-колонок нет).
- Миграции = идемпотентный raw SQL `db/init/NNN-*.sql`; CI и оба деплоя прогоняют их одним
  `tools/apply-db-init.sh`. Здесь ТОЛЬКО прод-схема; каталожные — `tools/scout/NNN-*.sql` → дев-БД
  (ADR-0179). drizzle-kit и down-миграций НЕТ. БД — контейнер pgvector/pg17 (ADR-0002).

## Дев-БД каталога (`remlab-devdb`, `tools/scout/`)
`products` (+ `availability_state/page_state/basis`, ADR-0186), `asset_revisions`, `orientation_state`,
`product_photo_current`, `image_url_hd` (ADR-0182), `mesh_generations` (ADR-0188) — [[catalog]],
[[stock-and-dims]], [[mesh-pipeline]].

**Tier 2:** `../../docs/tech-spec-ts-stack.md` §4.
