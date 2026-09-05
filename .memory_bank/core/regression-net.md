---
tier: 1
topic: regression-net
scope: Регресс-защита — тесты, CI, гардрейлы
tier2: "../../docs/tech-spec-ts-stack.md"
updated: 2026-09-05
importance: high
source: manual
status: working
source_of_truth: supporting
last_verified: 2026-09-05
review_after: 2026-12-05
---

# Regression Net — Tier 1

> Сетка для соло-не-кодера: ошибки ловит автоматика. «Цель» = НЕ реализовано.

## Есть в коде
- **Unit (Vitest, `tests/unit/`):** 25 файлов (в т.ч. `mesh-audit.test.ts`); БД — `pg-repository.test.ts`
  (skipIf); мок — `REMLAB_FAKE_AI=1`. Память: `tests/memory-project-audit.test.mjs` (`node --test`).
- **e2e:** happy path `flow.spec.ts` (через /select) + 5 smoke + `estimate.spec.ts`; error-путей НЕТ.
- **CI (`ci.yml`):** джобы gate (postgres → typecheck → lint → test → build → e2e + шаг
  memory-project-audit), db-init, planner (pytest солвера), scout-orient, scout-selftest;
  `memory-audit.yml` — аудит памяти (режим `_kit/gate-mode.txt`). Красный = merge запрещён.
- **Observability:** трейс LLM-вызовов (`lib/trace/`; сбои записи — `traceWriteFailures` в
  `/api/health`); PostHog. Sentry НЕ заводим.
- **Гарантии памяти (ADR-0055):** два аудита + хуки: PreToolUse-гард Bash — в git
  (`.claude/settings.json`, ADR-0195); SessionStart/Stop/PreCompact/PostToolUse — в
  `.claude/settings.local.json` (вне git; скрипты `tools/*.mjs` — в git).
- **Грабля:** меняешь флоу — правь e2e тем же коммитом; шаг CI и его инструмент — одним
  коммитом (урок 414); после push смотри gate.

## Цель (спека §12) — НЕ реализовано
- Тесты Cost Engine/matching/гардрейлов (модулей нет); интеграционные API; e2e error-пути;
  статусов done/failed нет, генерация — синхронный POST. Платежи демо.
- Гардрейлы стоимости: maxCostUsd; квота free-генераций юзер/IP; потолок + kill-switch.
- Eval-харнесс (§12.5): `/eval` нет; план — золотые фото, LPIPS/SSIM + CLIP.
- v0.4: golden-формулы смет (комнаты → количества) — CI-тест (мастер).

**DoD (цель-чеклист):** typecheck/lint/тесты ✓; e2e +≥1 путь ошибки; UX всех ошибок; события
эмитятся; env задокументированы; отклонения → ADR.

**Бенчи мебельного трека (08.08):** 252 синтетики + real-бенч, фаззинг, constraint-CI (ADR-0079/0080).

**Tier 2:** `../../docs/tech-spec-ts-stack.md` §12 (регресс-защита), §8 (самопроверка моделей).
