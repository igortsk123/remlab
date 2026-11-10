---
tier: 1
topic: regression-net
scope: Регресс-защита — тесты, CI, гардрейлы
tier2: "../../docs/tech-spec-ts-stack.md"
updated: 2026-11-10
importance: high
source: manual
status: working
source_of_truth: supporting
last_verified: 2026-11-06
review_after: 2026-12-05
---

# Regression Net — Tier 1

> Сетка для соло-не-кодера: ошибки ловит автоматика. «Цель» = НЕ реализовано.

## Есть в коде
- **Unit (Vitest, `tests/unit/`):** 80 файлов; БД — `pg-repository.test.ts` (skipIf); мок — `REMLAB_FAKE_AI=1`.
- **e2e:** CI — весь `e2e/` (`flow`, `/calc/remont` — skip). Живые проверки прода — `e2e/live/*.live.ts`, ночной шаг `demo_live`.
- **Цепочка каталога (ADR-0242):** `tools/scout/tests_chain.py` `--selftest` (CI) / `--live` (шаг `chain_checks` → `WARN:`);
  правила — `tools/scout/catalog_rules.py`.
- **Конвейер на одноразовой базе (conv-06):** `tools/scout/tests/pipeline_chain_dbtest.py` (мини-фид → `load3` → `lr_roles`), шаг `chain_dbtest`.
- **Стенд паритета комнат (05.11):** `tools/scout/parity_living.py --room living|bedroom|hall` — до/после правки общего конвейера
  на замороженных данных и копии базы (`parity_guard.py`, `tools/scout/rules/parity-living.json`); код 3 — эталон старше данных.
- **CI (`ci.yml`):** gate (postgres; memory-project-audit → typecheck → lint → test → build → e2e), db-init, planner, draft-image,
  scout-orient, scout-selftest (python 3.12); `memory-audit.yml`; аудиты — `warn` (`_kit/gate-mode.txt`). Статус main —
  `tools/ops/ci-status.sh` (публичный API, ночь → DIGEST); перед пушем — хук `tools/ops/prepush-check.sh`; Tier 2 —
  `domain/deployment-details.md` § CI.
- **Observability:** трейс LLM (`lib/trace/`, `traceWriteFailures`); база в health (`lib/health.ts:dbCheck`) + `health-watch.sh` (ADR-0266).
- **Гарантии памяти (ADR-0055):** два аудита + хуки (`.claude/settings.json`): гард Bash (ADR-0195),
  SessionStart/Stop/PreCompact/PostToolUse (`tools/code-touch-hint.mjs`).
- **Грабля:** флоу — e2e тем же коммитом; шаг CI и инструмент — одним коммитом (урок 414); `bank_*`/`rules/bank-*` —
  `test_bank_spec_golden.py --record` тем же коммитом.

## Цель (спека §12) — НЕ реализовано
- Ставки работ (`lib/pricing/works.ts`) без confidence (§11); нет matching, гардрейлов, интеграционных API, e2e error-путей;
  генерация — синхронный POST; YooKassa — только визуализация (`app/viz-actions.ts`).
- `/eval` (§12.5) нет; v0.4: golden-формулы смет (комнаты → количества) — CI-тест (мастер).

**DoD (цель):** e2e +≥1 путь ошибки; отклонения → ADR.

**Tier 2:** `../../docs/tech-spec-ts-stack.md` §12 (регресс-защита), §8 (самопроверка моделей).
