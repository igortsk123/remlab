---
tier: 1
topic: architecture
scope: Стек, структура, модули, генерация, деплой — по коду
tier2: "../../docs/tech-spec-ts-stack.md"
updated: 2026-07-09
importance: high
source: manual
status: working
source_of_truth: supporting
last_verified: 2026-07-09
review_after: ""
---

# Architecture — Tier 1 (по коду)

## Стек (факт)
TS strict, pnpm, Next.js 15 App Router (full-stack). Drizzle — только schema+query (`db/schema.ts`, `lib/db.ts`); миграции — raw SQL `db/init/*.sql` + `tools/migrate.mjs`, drizzle-kit НЕТ. Zod-границы: `contracts/`. Провайдеры `lib/providers` (`Result<T,E>`): `gemini.ts` — прямой Gemini API (GEMINI_API_KEY), `fake.ts`, `traced.ts`. Аналитика — своя обёртка `lib/analytics.ts` (PostHog по HTTP, no-op без ключа); Sentry НЕТ. Vitest + Playwright. CI: `.github/workflows/ci.yml` + `deploy.yml`.

## Структура (факт)
- `/app`: `page.tsx` (лендинг), `/start`, `/p/[id]/{brief,select,style,preview,paywall}`, `/rooms`, `/soon`, `/api` (health, p, trace); route-групп нет.
- `/modules` — 5: room-analysis, visual-generation, generation-job, ideas, store. Модуль = один `index.ts`, тесты в `/tests/unit/`; у store index.ts НЕТ — импорт через `@/modules/store/repository` (+ `pg-repository.ts`).
- `/db` (schema + init), `/contracts`, `/lib`, `/e2e` (flow + smoke), `/tools`, `/docs`.

## Генерация (факт)
СИНХРОННО: `app/api/p/[id]/generate/route.ts` → `await runGenerate(id)`, `maxDuration = 60`. Клиент (`GenerateOnMount`) ждёт один POST; прогресс на UI фейковый. Ретраев/квот нет. Inngest НЕ установлен.

## Деплой (self-host, ADR-0001)
Dockerfile multi-stage → Next standalone, `CMD ["node","server.js"]` :3000. Compose (сеть remlab-net): caddy :443 (LE) → app; db = pgvector/pgvector:pg17; imagor (сжатие картинок, internal); traces-init. Детали — `deployment.md`.

## Цели спеки (НЕ реализовано)
- Inngest (durable jobs, ретраи, Realtime/polling) — цель (спека §5).
- Модули product-matching, cost-engine, catalog, payments, export — цель (спека §2).
- Провайдеры Vertex/fal/Replicate — цель (спека §8).
- YooKassa — цель; paywall = заглушка (`app/p/[id]/paywall`).
- Sentry; `/eval` (Python-харнесс) — цель (спека §12).
- Cost Engine по rate-таблицам — цель (спека §3); сейчас `estimateBudget()` в `modules/ideas` — детерм. диапазон по budgetBand.
- Route-группы `(marketing)/(flow)/(workspace)` — цель (спека §2), в коде нет.

**Tier 2:** `../../docs/tech-spec-ts-stack.md` — целевая инженерная спека (контракты §3, схема §4, жизненный цикл §5, модели §8).
