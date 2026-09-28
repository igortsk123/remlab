---
tier: 1
topic: regression-net
scope: Регресс-защита — тесты, CI, гардрейлы
tier2: "../../docs/tech-spec-ts-stack.md"
updated: 2026-09-28
importance: high
source: manual
status: working
source_of_truth: supporting
last_verified: 2026-09-28
review_after: 2026-12-05
---

# Regression Net — Tier 1

> Сетка для соло-не-кодера: ошибки ловит автоматика. «Цель» = НЕ реализовано.

## Есть в коде
- **Unit (Vitest, `tests/unit/`):** 25 файлов (в т.ч. `mesh-audit.test.ts`); БД — `pg-repository.test.ts`
  (skipIf); мок — `REMLAB_FAKE_AI=1`. Память: `tests/memory-project-audit.test.mjs` (`node --test`).
- **e2e:** в CI — 5 smoke + 2 из 3 тестов `estimate.spec.ts` (`/calc/remont` — skip); happy path `flow.spec.ts`
  — `test.skip` с 28.07 (раздел за заглушкой); error-путей НЕТ.
- **CI (`ci.yml`):** джобы gate (postgres → typecheck → lint → test → build → e2e + шаг
  memory-project-audit), db-init, planner (pytest солвера), scout-orient, scout-selftest;
  `memory-audit.yml` — аудит памяти. Оба аудита памяти — по `_kit/gate-mode.txt`: с 28.09 `warn`
  (прод из-за памяти не стоит; дисциплина — Stop-хук `--block`).
- **Observability:** трейс LLM-вызовов (`lib/trace/`; сбои записи — `traceWriteFailures` в
  `/api/health`); PostHog. Sentry НЕ заводим.
- **Гарантии памяти (ADR-0055):** два аудита + хуки в git (`.claude/settings.json`): гард Bash
  (ADR-0195) и с 28.09 SessionStart/Stop/PreCompact/PostToolUse (Read → read-logger, Edit|Write →
  `tools/code-touch-hint.mjs`); разрешения — `settings.local.json`.
- **Грабля:** меняешь флоу — правь e2e тем же коммитом; шаг CI и его инструмент — одним
  коммитом (урок 414); после push смотри gate.

## Цель (спека §12) — НЕ реализовано
- Движок ставок работ есть (`lib/pricing/works.ts`), без confidence (§11); нет matching, гардрейлов,
  интеграционных API, e2e error-путей, статусов done/failed; генерация — синхронный POST. Пейвол — демо,
  YooKassa — только визуализация (`app/viz-actions.ts`).
- Гардрейлы стоимости: maxCostUsd; квота free-генераций юзер/IP; потолок + kill-switch.
- Eval-харнесс (§12.5): `/eval` нет; план — золотые фото, LPIPS/SSIM + CLIP.
- v0.4: golden-формулы смет (комнаты → количества) — CI-тест (мастер).

**DoD (цель):** typecheck/lint/тесты ✓; e2e +≥1 путь ошибки; UX ошибок; события; env описаны; отклонения → ADR.

**Бенчи мебельного трека (08.08):** 252 синтетики + real-бенч, фаззинг, constraint-CI (ADR-0079/0080).

**Tier 2:** `../../docs/tech-spec-ts-stack.md` §12 (регресс-защита), §8 (самопроверка моделей).
