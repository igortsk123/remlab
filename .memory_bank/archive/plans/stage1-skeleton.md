---
workstream: stage1
slug: stage1-skeleton
status: cancelled
archived: 2026-07-11
archive_reason: "historical: Stage 1 построен "
created: 2026-07-01
updated: 2026-07-01
completed:
---

## Цель
Каркас продуктового Stage 1 (без реального инференса/платежей): схема БД + миграции + оболочка 7 экранов flow + аналитика/observability обёртки + e2e happy-path на моках. Разблокированный путь (внешние API-ключи не нужны).

## Источник задачи
Пользователь: «S5+ — фичи по тех-спеке, каждая отдельным планом». Это первый feature-план после bootstrap (S1–S4).

## Скоуп — что входит
- **Drizzle + миграции + RLS-заготовки** для ядра схемы (§4 спеки): users, properties, rooms, room_projects, result_versions, style_profiles, uploaded_images, detected_objects, generation_jobs, generated_images. `CREATE EXTENSION vector` уже есть.
- **Zod-контракты** в `/contracts` для этих сущностей (`z.infer` типы) — анти-дрейф.
- **UX-оболочка 7 экранов** (`app/(flow)`): landing → комната/цель/уровень → фото/бриф → style cards → AI-preview(заглушка) → paywall(заглушка) → workspace. Навигация + состояние проекта в БД, БЕЗ реальной генерации/оплаты (моки/stubs).
- **Anonymous session** (интерим Auth): session id в cookie → `users.anonymous_id` (ADR при выборе).
- **Observability-обёртки:** Sentry + PostHog инициализация + типизированный `Result<T,E>` + события flow (§12.4).
- **e2e happy-path (Playwright)** на моках: проход всех 7 экранов; +≥1 путь ошибки (плохое фото/needs_better_photo как stub).
- Обновить CI (`db:migrate` шаг), `deployment.md`, память.

## Скоуп — что НЕ входит
Реальный инференс (Stage 2), каталог/matching (Stage 3), платежи (Stage 4), compose (Stage 5), Cost Engine (Stage 1B). Кухня/ванная/repeat-reference.

## Файлы к изменению (предварительно)
- [ ] `db/schema.ts`, `db/migrations/*`, `drizzle.config.ts`, `lib/db.ts`
- [ ] `contracts/*.ts` (Zod)
- [ ] `app/(flow)/**`, `app/(workspace)/**`, `app/(marketing)/**`
- [ ] `lib/session.ts`, `lib/sentry.ts`, `lib/posthog.ts`, `lib/result.ts`
- [ ] `e2e/*.spec.ts`, `.github/workflows/ci.yml` (+db:migrate)
- [ ] env: DATABASE_URL уже есть; добавить SENTRY_DSN/POSTHOG_KEY (опц. на этом этапе)

## Критерии приёмки
- [ ] typecheck/lint/unit/build зелёные; e2e happy-path + 1 error-path зелёные; CI green
- [ ] миграции применяются на чистой БД и обратимы
- [ ] RLS: юзер не видит чужое (integration-тест)
- [ ] реальных ключей инференса/платежей не требуется (всё за stub)
- [ ] Memory Bank обновлён (core/data-model, project-state), ADR по Auth-интериму

## Открытые вопросы (нужно от владельца перед/во время)
- Дизайн-направление экранов (§16.5) — сейчас берём нейтральный каркас.
- Порядок: сначала этот Stage 1 каркас или Stage 0 спайки (нужны FAL/Replicate/Vertex ключи + источники каталога — §16.4)?

## Лог выполнения
- 2026-07-01 — план создан (draft), ждёт «деплой».
