---
tier: 1
topic: regression-net
scope: Регресс-защита — тесты, CI-гейт, observability, eval, гардрейлы, DoD
tier2: "../../docs/tech-spec-ts-stack.md"
updated: 2026-07-09
importance: high
source: manual
status: working
source_of_truth: supporting
last_verified: 2026-07-09
review_after: ""
---

# Regression Net — Tier 1 (сверено 2026-07-09)

> Сетка для соло-не-кодера: ошибки ловит автоматика. «Цель» = НЕ реализовано.

## Есть в коде
- **Unit (Vitest, `tests/unit/`):** flow-pipeline, health, providers, restyle-prompt, trace-sign,
  trace. Интеграция с БД — только `pg-repository.test.ts` (skipIf без `TEST_DATABASE_URL`).
  Мок моделей — fake-провайдер (`REMLAB_FAKE_AI=1`).
- **e2e (Playwright):** happy path `flow.spec.ts` + 3 smoke (`smoke.spec.ts`); error-путей НЕТ.
- **CI-гейт (`ci.yml`, S4):** postgres (pgvector/pgvector:pg17) → install → typecheck → lint →
  test → build → e2e. Шага db:migrate НЕТ (таблицу тест создаёт сам). Красный = merge запрещён.
- **Observability:** трейс каждого LLM-вызова (`traced.ts`/`lib/trace/`; costUsd/шаг,
  total_cost_usd/прогон); PostHog (`lib/analytics.ts`) — эмитятся 5 из 9 событий
  (project_started, preview_ready, pack_unlocked, problem_reported, app_error). Sentry НЕ заводим.

## Цель (спека §12) — НЕ реализовано
- Тесты: Cost Engine/matching/work_types/гардрейлы (модулей нет); интеграционные API/миграции;
  RLS (в БД нет); e2e error-пути (плохое фото, инференс, таймаут). Статусов
  done/failed/needs_better_photo НЕТ (enum: started…preview_ready|paid); генерация — синхронный
  POST `/api/p/[id]/generate` БЕЗ Realtime/polling и Inngest. Платежи — демо-кнопка.
- Гардрейлы стоимости: maxCostUsd; квота free-генераций юзер/IP; потолок + kill-switch;
  nCandidates=1 на free. Сейчас generate без лимитов.
- Eval-харнесс (§12.5): `/eval` (Python) нет; план — 30–50 золотых фото, LPIPS/SSIM + CLIP;
  интерим — ручная рубрика самопроверки (§8; «§8.3» — условная нумерация).
- Дашборд стоимости инференса.
- Правило «нет e2e на поток → срез не готов» для error-путей нарушено.

**DoD (цель-чеклист):** typecheck/lint/тесты ✓; e2e +≥1 путь ошибки; UX всех ошибок; события
эмитятся; env задокументированы; отклонения → DECISIONS.

**Tier 2:** `../../docs/tech-spec-ts-stack.md` §12 (регресс-защита), §8 (самопроверка моделей).
