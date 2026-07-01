---
tier: 1
topic: regression-net
scope: Регресс-защита — тесты, CI-гейт, observability, eval, гардрейлы, DoD
tier2: "../../docs/tech-spec-ts-stack.md"
updated: 2026-07-01
importance: high
source: manual
status: working
source_of_truth: supporting
last_verified: 2026-07-01
review_after: ""
---

# Regression Net — Tier 1 сводка

> Главная сетка для соло-не-кодера: ошибки ловит автоматика, не чтение кода. Обязательно с Stage 1.

## Тесты
- **Unit (Vitest)** — чистая логика без сети: математика Cost Engine, ранжирование matching, мапперы scope→work_types, style_profile→prompt, гардрейлы. Самые ценные.
- **Integration (Vitest + тестовая БД)** — API/RLS/миграции/Zod; внешние модели/платежи — мок.
- **e2e (Playwright)** — критические потоки + пути ошибок: happy path; generation lifecycle (Realtime/polling → done/failed/needs_better_photo); paywall; failure (плохое фото, упавший инференс, таймаут, недоступный товар).
- **Правило:** нет e2e на затронутый поток → срез не готов.

## Definition of Done
typecheck ✓, lint ✓, unit+integration ✓, e2e (+≥1 путь ошибки) ✓, все состояния ошибки имеют UX, PostHog/Sentry эмитятся, секретов нет / env задокументированы, миграция обратима, отклонения → DECISIONS.

## CI-гейт (GitHub Actions) — S4
postgres(pgvector) service → install → typecheck → lint → db:migrate → test → build → e2e. Красный = merge запрещён.

## Observability
Sentry (ошибки фронт/бэк/Inngest с job_id/user_id/mode); структурные логи внешних вызовов (провайдер/модель/latency/cost); трейс generation_job; PostHog события всего flow; дашборд стоимости инференса.

## Гардрейлы стоимости (Stage 1)
maxCostUsd на вызов; квота free-генераций на юзера/IP; Inngest concurrency.limit; дневной потолок + kill-switch (PostHog флаг); nCandidates=1 на free.

## Eval-харнесс качества (Python /eval, не в рантайме)
Золотой набор 30–50 фото + брифы; LPIPS/SSIM по «оставленным» зонам + CLIP к стилю; перед сменой модели/промпта. MVP-интерим: ручная рубрика §8.3.

**Tier 2:** `../../docs/tech-spec-ts-stack.md` §12 (полная регресс-защита) + §8.3 (протокол самопроверки моделей).
