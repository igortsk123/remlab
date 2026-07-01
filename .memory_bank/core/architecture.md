---
tier: 1
topic: architecture
scope: Стек, структура репозитория, границы модулей, архитектура деплоя
tier2: "../../docs/tech-spec-ts-stack.md"
updated: 2026-07-01
importance: high
source: manual
status: working
source_of_truth: supporting
last_verified: 2026-07-01
review_after: ""
---

# Architecture — Tier 1 сводка

## Стек
TypeScript (strict) end-to-end. pnpm. Next.js (App Router, full-stack: UI+API). Drizzle (миграции, pgvector, raw SQL). Zod на каждой границе API (single source of truth I/O, `z.infer`). Inngest (durable jobs, ретраи, concurrency). Внешний инференс за провайдер-интерфейсом (Vertex/fal/Replicate). YooKassa. Sentry + PostHog. Vitest + Playwright. GitHub Actions (блокирующий гейт).

## Структура репозитория (§2 спеки)
- `/app` — Next.js: `(marketing)` лендинг, `(flow)` 7-экранный flow, `(workspace)`, `/api` (тонкие роуты).
- `/modules` — ЯДРО: `room-analysis`, `visual-generation`, `product-matching`, `cost-engine`, `catalog`, `payments`, `export`, `generation-job`. Каждый = папка + `index.ts` (контракт) + impl + тесты. Модули общаются ТОЛЬКО через `index.ts`.
- `/db` (Drizzle schema/migrations/seed), `/contracts` (Zod), `/lib` (провайдеры, db client, sentry, posthog), `/inngest`, `/e2e`, `/eval` (Python, не деплоится), `/docs`.

## Ключевые паттерны
- Длинный инференс (30–45с) НЕ в Next.js route → job-строка + Inngest + Realtime/polling статуса.
- Внешние вызовы → типизированный `Result<T,E>`, ретраи через Inngest step, заданный UX ошибки.
- Cost Engine детерминированный: сумму считает движок по rate-таблицам, НЕ LLM.

## Архитектура деплоя (наш self-host — ADR-0001)
Сборка локально → образ на сервер. На exit-fi изолированный `docker-compose` (`remlab-net`):
`Caddy :443 (LE) → remlab-app :3000 (next start) → postgres:17+pgvector`. Подробности — `deployment.md`.

**Tier 2:** `../../docs/tech-spec-ts-stack.md` — полная инженерная спека (контракты §3, схема §4, жизненный цикл §5, модели §8).
