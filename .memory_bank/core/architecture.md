---
tier: 1
topic: architecture
scope: Стек, модули, генерация, деплой — по коду
tier2: "../../docs/tech-spec-ts-stack.md"
updated: 2026-10-18
importance: high
source: manual
status: working
source_of_truth: supporting
last_verified: 2026-10-18
review_after: 2026-12-05
---

# Architecture — Tier 1 (по коду)

## Стек (факт)
TS strict, pnpm, Next.js 15 App Router. Drizzle — только schema+query (`db/schema.ts`); миграции —
raw SQL `db/init/*.sql` + `tools/apply-db-init.sh` (drizzle-kit НЕТ). Zod: `contracts/`. Провайдеры
`lib/providers` (`Result<T,E>`): gemini/fake/traced. Аналитика `lib/analytics.ts` (PostHog); Sentry НЕТ.
Vitest + Playwright. CI: `.github/workflows/{ci,deploy,memory-audit}.yml`.

## UI-слой (ADR-0041)
**Untitled UI React** (Tailwind v4 + React Aria), примитивы в `components/base|application`;
бренд ТОЛЬКО в `styles/brand.css`. Правила — `.claude/rules/ui-rules.md`.

## Структура (факт)
- `/app`: `page.tsx` (хаб). **Смета:** `/calc` хаб, `/calc/[kind]`, `/calc/remont`, `/e/[id]`,
  `/estimates`→`/lab` (ADR-0036), `/go/[eid]/[iid]`. Навигация `SiteHeader.tsx` (ADR-0017); `/styles`
  — квиз `components/StyleQuiz.tsx` (заглушка); `/lab` (+ `/lab/{mesh-review,mesh-audit}` — приёмка мешей).
  `/flat` — 3D-квартира ([[apartment-configurator]]), ещё `/rooms`, `/soon`, `/sovety`; B2B: `/manager` (страница
  менеджера), `/partner/report`, `/embed/[partner]/[flat]` (route); юр.: `/cookies`, `/privacy`, `/terms`.
  Legacy М5: `/start`, `/p/[id]/*`. `/api`: apartments, calc, collections, events, flat, health, internal, lab, leads,
  manager, manager-bot, p, partner, pay, sends, trace.
- `/modules` — store + estimate (memory/pg) + leads + style + collections + sends + share-requests + partner-report +
  owner-reviews + retention; legacy М5 — ideas, room-analysis, visual-generation, generation-job.
- **Смета (v0.4):** `contracts/estimate.ts`; `lib/estimate/*`; `lib/pricing/works`. Наружу ТОЛЬКО
  через `/go/`. **Калькулятор v2 (ADR-0018):** `contracts/calc.ts` + `lib/calc/*` + `components/calc/*`
  (состояние в localStorage); v2 — дефолт.
- `/db` (init 001–020: 007-mesh-review, 010-mesh-audit, 011-configurator, 012-flat-placements, 013-security, 014-sends,
  015-flat-configs-v3, 016-collections, 017-analytics, 018-legal, 019-owner-reviews, 020-flat-configs-hidden),
  `/contracts`, `/lib` (+ `mesh-review`, `mesh-audit`, `configurator`, `viewer3d`, `basket`, `collections`, `embed`,
  `partners`, `legal`, `telegram`), `/e2e`, `/docs`.
- `/tools` — в git, кроме данных scout (ADR-0055); каталог/меши — `tools/scout/` (Python, дев-БД).

## Генерация AI (legacy, М5)
СИНХРОННО: `app/api/p/[id]/generate` → `runGenerate`, `maxDuration=60`; ретраев/квот нет.

## Деплой (self-host, ADR-0001)
Compose (`remlab-net`): caddy :443 (LE) → app (Next standalone :3000); db pgvector:pg17; imagor;
traces-init; mesh-receiver; **draft** (`tools/scout/draft_service.py`, образ `infra/draft/Dockerfile` из ghcr, в compose с
14.10, ADR-0278; кадр — fal, `draft_render.py`). Caddy проксирует `/api/{draft,warm,render,job,share}*` → `draft:8099`.
Детали — `deployment.md`.

## Цели (НЕ реализовано)
Inngest · платежи/export · Vertex · YooKassa (проводка есть — `lib/payments/yookassa.ts`,
`app/viz-actions.ts`, вебхук; НЕТ только ключей) ·
Sentry · `/eval` · Cost Engine (вход Б = плейсхолдер).

**Tier 2:** `../../docs/tech-spec-ts-stack.md` (§3 контракты, §4 схема, §5 цикл, §8 модели).
