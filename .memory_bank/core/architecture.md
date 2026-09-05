---
tier: 1
topic: architecture
scope: Стек, модули, генерация, деплой — по коду
tier2: "../../docs/tech-spec-ts-stack.md"
updated: 2026-08-06
importance: high
source: manual
status: working
source_of_truth: supporting
last_verified: 2026-08-31
review_after: 2026-12-05
---

# Architecture — Tier 1 (по коду)

## Стек (факт)
TS strict, pnpm, Next.js 15 App Router. Drizzle — только schema+query (`db/schema.ts`); миграции — raw SQL `db/init/*.sql` + `tools/migrate.mjs` (drizzle-kit НЕТ). Zod: `contracts/`. Провайдеры `lib/providers` (`Result<T,E>`): gemini/fake/traced. Аналитика `lib/analytics.ts` (PostHog HTTP, no-op без ключа); Sentry НЕТ. Vitest + Playwright. CI: `.github/workflows/{ci,deploy,memory-audit}.yml`.

## UI-слой (ADR-0041)
**Untitled UI React** (Tailwind v4 + React Aria), примитивы в `components/base|application`;
бренд ТОЛЬКО в `styles/brand.css`. Правила и грабли — `.claude/rules/ui-rules.md`.

## Структура (факт)
- `/app`: `page.tsx` (хаб). **Смета-first (M1):** `/calc` хаб, `/calc/[kind]`, `/calc/remont`, `/e/[id]`, `/estimates`→`/lab` (ADR-0036), `/go/[eid]/[iid]`. **Навигация (ADR-0017):** `SiteHeader.tsx`; `/styles` — живой квиз (`modules/style/`); каркасы `/sovety`, `/lab`. **Legacy М5:** `/start`, `/p/[id]/*`, `/rooms`. `/api`: calc, health, lab, leads, p, pay, trace. Actions: `app/{estimate,calc,lead,styles,viz}-actions.ts`.
- `/modules` — store + **estimate** (memory/pg) + **leads** + **style**; visual-generation/generation-job/ideas/room-analysis — М5.
- **Смета (v0.4):** `contracts/estimate.ts`; `lib/estimate/*`; `lib/pricing/works`. Наружу ТОЛЬКО через `/go/`. **Калькулятор v2 (ADR-0018):** `contracts/calc.ts`+`lib/calc/*`+`components/calc/*` (клиентское состояние, localStorage); `CALC_V2` удалён — v2 дефолт.
- `/db` (init 001-006: 005-leads, 006-style-results), `/contracts`, `/lib`, `/e2e`, `/docs`.
- `/tools` — в git, кроме данных scout (ADR-0055); состав — spec §2.1.

## Генерация AI (legacy, М5)
СИНХРОННО: `app/api/p/[id]/generate` → `runGenerate`, `maxDuration=60`. Ретраев/квот/Inngest нет.

## Деплой (self-host, ADR-0001)
Compose (`remlab-net`): caddy :443 (LE) → app (Next standalone :3000); db pgvector:pg17; imagor (internal); traces-init. Детали — `deployment.md`.

## Цели (НЕ реализовано)
Inngest · матчинг/каталог/платежи/export · Vertex/fal · YooKassa (скелет `lib/payments/yookassa.ts` + `api/pay/yookassa` есть, ключей нет) · Sentry · `/eval` · Cost Engine (вход Б = плейсхолдер).

**Tier 2:** `../../docs/tech-spec-ts-stack.md` (контракты §3, схема §4, жизненный цикл §5, модели §8).
