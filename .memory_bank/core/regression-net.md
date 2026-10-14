---
tier: 1
topic: regression-net
scope: Регресс-защита — тесты, CI, гардрейлы
tier2: "../../docs/tech-spec-ts-stack.md"
updated: 2026-10-14
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
- **Unit (Vitest, `tests/unit/`):** 42 файла; БД — `pg-repository.test.ts` (skipIf); мок — `REMLAB_FAKE_AI=1`.
- **e2e:** CI — весь `e2e/` (smoke, estimate, flat3d serial, legal, embed); `flow` и `/calc/remont` — skip.
  Демо на проде — `e2e/live/demo.live.ts`, ночной шаг `demo_live` (b2b-12).
- **Цепочка каталога по бизнес-правилам (13.10, ADR-0242):** `tools/scout/tests_chain.py` —
  `--selftest` (фикстуры, в CI) и `--live` (инварианты по дев-базе, шаг `chain_checks`,
  расхождение → `WARN:` в дайджест). Утверждают ПРАВИЛО, а не поведение кода, и печатают ЧИСЛО;
  чистые правила — `tools/scout/catalog_rules.py`.
- **Конвейер на одноразовой базе (14.10, conv-06):** `tools/scout/tests/pipeline_chain_dbtest.py` — мини-фид → схема →
  `load3` → `lr_roles` → `pipeline_map.collect`; ночной шаг `chain_dbtest`.
- **CI (`ci.yml`):** gate (postgres → typecheck → lint → test → build → e2e + memory-project-audit),
  db-init, planner, draft-image, scout-orient, scout-selftest (30 модулей); `memory-audit.yml`. Режим аудитов —
  `_kit/gate-mode.txt`: с 28.09 `warn` (дисциплину держит Stop-хук `--block`).
- **Observability:** трейс LLM-вызовов (`lib/trace/`; сбои — `traceWriteFailures` в
  health); база в health (`lib/health.ts:dbCheck`) + сторож `health-watch.sh` (ADR-0266).
- **Гарантии памяти (ADR-0055):** два аудита + хуки Claude Code (`.claude/settings.json`): гард Bash
  (ADR-0195) и SessionStart/Stop/PreCompact/PostToolUse (`tools/code-touch-hint.mjs`).
- **Грабля:** меняешь флоу — правь e2e тем же коммитом; шаг CI и его инструмент — одним
  коммитом (урок 414).

## Цель (спека §12) — НЕ реализовано
- Движок ставок работ есть (`lib/pricing/works.ts`), без confidence (§11); нет matching, гардрейлов,
  интеграционных API, e2e error-путей; генерация — синхронный POST. Пейвол — демо, YooKassa —
  только визуализация (`app/viz-actions.ts`).
- Eval-харнесс (§12.5): `/eval` нет.
- v0.4: golden-формулы смет (комнаты → количества) — CI-тест (мастер).

**DoD (цель):** e2e +≥1 путь ошибки; отклонения → ADR.

**Tier 2:** `../../docs/tech-spec-ts-stack.md` §12 (регресс-защита), §8 (самопроверка моделей).
