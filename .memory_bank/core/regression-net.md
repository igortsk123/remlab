---
tier: 1
topic: regression-net
scope: Регресс-защита — тесты, CI, eval, гардрейлы, DoD
tier2: "../../docs/tech-spec-ts-stack.md"
updated: 2026-08-08
importance: high
source: manual
status: working
source_of_truth: supporting
last_verified: 2026-08-06
review_after: ""
---

# Regression Net — Tier 1 (сверено 2026-07-11)

> Сетка для соло-не-кодера: ошибки ловит автоматика. «Цель» = НЕ реализовано.

## Есть в коде
- **Unit (Vitest, `tests/unit/`):** 24 файла; БД — `pg-repository.test.ts` (skipIf);
  мок — `REMLAB_FAKE_AI=1`.
- **e2e:** happy path `flow.spec.ts` (через /select) + 5 smoke + `estimate.spec.ts`; error-путей НЕТ.
- **CI-гейт (`ci.yml`):** джоб gate (postgres → typecheck → lint → test → build → e2e) +
  джоб planner (pytest солвера, T6). Красный = merge запрещён.
- **Observability:** трейс LLM-вызовов (`lib/trace/`; сбои записи видны — traceWriteFailures
  в /api/health, T0); PostHog. Sentry НЕ заводим.
- **Грабля:** меняешь флоу — правь e2e тем же коммитом; после push смотри gate.
- **Гарантии памяти (ADR-0055):** аудит + 4 хука в git.

## Цель (спека §12) — НЕ реализовано
- Тесты: Cost Engine/matching/work_types/гардрейлы (модулей нет); интеграционные API/миграции;
  RLS (в БД нет); e2e error-пути (плохое фото, инференс, таймаут). Статусов
  done/failed/needs_better_photo НЕТ; генерация — синхронный POST без Realtime/Inngest.
  Платежи демо.
- Гардрейлы стоимости: maxCostUsd; квота free-генераций юзер/IP; потолок + kill-switch;
  nCandidates=1 на free. Сейчас generate без лимитов.
- Eval-харнесс (§12.5): `/eval` (Python) нет; план — 30–50 золотых фото, LPIPS/SSIM + CLIP;
  интерим — ручная рубрика (§8).
- Дашборд стоимости инференса.
- v0.4: golden-формулы смет (комнаты→количества) — CI-тест (мастер).

**DoD (цель-чеклист):** typecheck/lint/тесты ✓; e2e +≥1 путь ошибки; UX всех ошибок; события
эмитятся; env задокументированы; отклонения → DECISIONS.

**Бенчи мебельного трека (08.08):** 252 синтетики + real-бенч `tools/scout/acceptance_real.py`
+ фаззинг + constraint-CI + SKU-бенч (CLIP AUC 0.547 — ворот нет). Числа подписывать
commit'ом. Детали — ADR-0079/0080.

**Tier 2:** `../../docs/tech-spec-ts-stack.md` §12 (регресс-защита), §8 (самопроверка моделей).
