---
tier: 1
topic: architecture
scope: Стек, структура, модули, генерация, деплой — по коду
tier2: "../../docs/tech-spec-ts-stack.md"
updated: 2026-07-11
importance: high
source: manual
status: working
source_of_truth: supporting
last_verified: 2026-07-11
review_after: ""
---

# Architecture — Tier 1 (по коду)

## Стек (факт)
TS strict, pnpm, Next.js 15 App Router (full-stack). Drizzle — только schema+query (`db/schema.ts`, `lib/db.ts`); миграции — raw SQL `db/init/*.sql` + `tools/migrate.mjs`, drizzle-kit НЕТ. Zod-границы: `contracts/`. Провайдеры `lib/providers` (`Result<T,E>`): `gemini.ts` — прямой Gemini API (GEMINI_API_KEY), `fake.ts`, `traced.ts`. Аналитика — своя обёртка `lib/analytics.ts` (PostHog по HTTP, no-op без ключа); Sentry НЕТ. Vitest + Playwright. CI: `.github/workflows/ci.yml` + `deploy.yml`.

## Структура (факт)
- `/app`: `page.tsx` (лендинг v0.4 — 2 входа), **смета-first (M1): `/calc` хаб, `/calc/[kind]`
  калькулятор, `/calc/remont` вход Б, `/e/[id]` смета-чек-лист, `/estimates` мои сметы,
  `/go/[eid]/[iid]` редирект-слой**; legacy AI-флоу `/start`, `/p/[id]/{brief,select,style,preview,paywall}`,
  `/rooms` (→ ступень М5). `/api` (health, p, trace).
- `/modules` — store (projects) + **estimate** (`repository.ts`: memory/pg, как projects).
  visual-generation/generation-job/ideas/room-analysis — AI-флоу (М5).
- **Смета (v0.4):** `contracts/estimate.ts`; `lib/estimate/{calc,links,companions}`; `lib/pricing/works`
  (плейсхолдер); `app/estimate-actions.ts`. Ссылки наружу ТОЛЬКО через `/go/` (late-binding реф).
- `/db` (schema + init 001-004), `/contracts`, `/lib`, `/e2e` (flow + smoke + estimate), `/tools`, `/docs`.

## Генерация AI (факт; legacy-флоу, ступень М5)
СИНХРОННО: `app/api/p/[id]/generate` → `await runGenerate(id)`, `maxDuration=60`; `GenerateOnMount` ждёт POST. Ретраев/квот/Inngest нет.

## Деплой (self-host, ADR-0001)
Dockerfile multi-stage → Next standalone, `CMD ["node","server.js"]` :3000. Compose (сеть remlab-net): caddy :443 (LE) → app; db = pgvector/pgvector:pg17; imagor (сжатие картинок, internal); traces-init. Детали — `deployment.md`.

## Цели (НЕ реализовано)
Inngest (durable jobs) · матчинг/каталог/платежи/export · провайдеры Vertex/fal · YooKassa
(paywall-заглушка) · Sentry · `/eval` · точный Cost Engine (сейчас вход Б = плейсхолдер
`lib/pricing/works`, план `pricing-db-ru`).

**Tier 2:** `../../docs/tech-spec-ts-stack.md` — целевая инженерная спека (контракты §3, схема §4, жизненный цикл §5, модели §8).
