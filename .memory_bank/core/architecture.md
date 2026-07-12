---
tier: 1
topic: architecture
scope: Стек, структура, модули, генерация, деплой — по коду
tier2: "../../docs/tech-spec-ts-stack.md"
updated: 2026-07-12
importance: high
source: manual
status: working
source_of_truth: supporting
last_verified: 2026-07-12
review_after: ""
---

# Architecture — Tier 1 (по коду)

## Стек (факт)
TS strict, pnpm, Next.js 15 App Router (full-stack). Drizzle — только schema+query (`db/schema.ts`, `lib/db.ts`); миграции — raw SQL `db/init/*.sql` + `tools/migrate.mjs` (drizzle-kit НЕТ). Zod-границы: `contracts/`. Провайдеры `lib/providers` (`Result<T,E>`): `gemini.ts` (прямой Gemini API), `fake.ts`, `traced.ts`. Аналитика `lib/analytics.ts` (PostHog по HTTP, no-op без ключа); Sentry НЕТ. Vitest + Playwright. CI: `.github/workflows/{ci,deploy}.yml`.

## Структура (факт)
- `/app`: `page.tsx` (главная). **Смета-first (M1):** `/calc` хаб, `/calc/[kind]`, `/calc/remont` (вход Б), `/e/[id]` чек-лист, `/estimates`, `/go/[eid]/[iid]` редирект. **Навигация (ADR-0017):** шапка `components/SiteHeader.tsx` (в `layout.tsx`); каркасы `/styles` (`components/StyleQuiz.tsx`+`lib/styles/quiz.ts`+`app/styles-actions.ts`), `/sovety`, `/lab`. **Legacy AI-флоу (М5):** `/start`, `/p/[id]/{brief,select,style,preview,paywall}`, `/rooms`. `/api` (health, p, trace).
- `/modules` — store (projects) + **estimate** (`repository.ts`: memory/pg). visual-generation/generation-job/ideas/room-analysis — AI-флоу (М5).
- **Смета (v0.4):** `contracts/estimate.ts`; `lib/estimate/{calc,links,companions}`; `lib/pricing/works`; `app/estimate-actions.ts`. Наружу ТОЛЬКО через `/go/`. **Калькулятор v2 (ADR-0018):** `contracts/calc.ts`+`lib/calc/*`+`components/calc/*` (клиентское состояние, localStorage), флаг `CALC_V2` до К3.
- `/db` (init 001-004), `/contracts`, `/lib`, `/e2e`, `/tools`, `/docs`.

## Генерация AI (факт; legacy, ступень М5)
СИНХРОННО: `app/api/p/[id]/generate` → `await runGenerate(id)`, `maxDuration=60`; `GenerateOnMount` ждёт POST. Ретраев/квот/Inngest нет.

## Деплой (self-host, ADR-0001)
Dockerfile multi-stage → Next standalone (:3000). Compose (`remlab-net`): caddy :443 (LE) → app; db pgvector:pg17; imagor (internal); traces-init. Детали — `deployment.md`.

## Цели (НЕ реализовано)
Inngest · матчинг/каталог/платежи/export · Vertex/fal · YooKassa (paywall-заглушка) · Sentry · `/eval` · точный Cost Engine (вход Б = плейсхолдер `lib/pricing/works`).

**Tier 2:** `../../docs/tech-spec-ts-stack.md` (контракты §3, схема §4, жизненный цикл §5, модели §8).
