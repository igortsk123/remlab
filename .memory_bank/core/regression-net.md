---
tier: 1
topic: regression-net
scope: Регресс-защита — тесты, CI, гардрейлы
tier2: "../../docs/tech-spec-ts-stack.md"
updated: 2026-11-13
importance: high
source: manual
status: working
source_of_truth: supporting
last_verified: 2026-11-12
review_after: 2026-12-05
---

# Regression Net — Tier 1

> Ошибки ловит автоматика. «Цель» = НЕ реализовано.

## Есть в коде
- **Unit (Vitest):** `tests/unit/*.test.ts`; на БД (skipIf без `TEST_DATABASE_URL`) — `pg-repository.test.ts`,
  `trial-claim.test.ts`; мок AI — `REMLAB_FAKE_AI=1`.
- **e2e:** CI — `e2e/*.spec.ts`; пути ошибок — `smoke.spec.ts`, `embed.spec.ts`.
  Живые проверки прода — `e2e/live/*.live.ts`, ночной шаг `demo_live`.
- **Цепочка каталога (ADR-0242):** `tools/scout/tests_chain.py` `--selftest` (CI) / `--live` (шаг `chain_checks` → `WARN:`);
  правила — `tools/scout/catalog_rules.py`.
- **Конвейер на одноразовой базе:** `tools/scout/tests/pipeline_chain_dbtest.py`, шаг `chain_dbtest`.
- **Стенд паритета комнат:** `tools/scout/parity_living.py --room living|bedroom|hall` — до/после правки общего конвейера
  на замороженных данных (`parity_guard.py`, `tools/scout/rules/parity-living.json`); код 3 — эталон старше данных.
- **CI (`ci.yml`):** gate (postgres; memory-project-audit → селфтесты → typecheck → lint → test → build → e2e), db-init, planner, draft-image,
  scout-orient, scout-selftest (python 3.12); `memory-audit.yml`; аудиты — `warn` (`_kit/gate-mode.txt`). Статус main —
  `tools/ops/ci-status.sh` (ночь → DIGEST); перед пушем — хук `tools/ops/prepush-check.sh`; пачка веток — сборщик
  `tools/ops/merge-queue.sh` (ADR-0406); Tier 2 — `domain/deployment-details.md` § CI.
- **Observability:** трейс LLM (`lib/trace/`); health (`lib/health.ts:dbCheck`) + `health-watch.sh` (ADR-0266).
- **Конвейер и надписи (ADR-0407):** реестр `tools/ops/conveyor-manifest.yml` + `tools/ops/conveyor_check.py`, хук
  `tools/hooks/guard_conveyor.py`, разрешение `tools/ops/conveyor_permit.py`, линт ID `tools/ops/conveyor_ids.py` (WARN);
  пары RU/EN /demo — `tools/ops/demo-i18n-scan.mjs --check` (CI).
- **Гарантии памяти (ADR-0055):** два аудита + хуки (`.claude/settings.json`): гард Bash (ADR-0195),
  SessionStart/Stop/PreCompact/PostToolUse (`tools/code-touch-hint.mjs`).
- **Грабля:** флоу — e2e тем же коммитом; шаг CI и инструмент — одним (урок 414); `bank_*` — `test_bank_spec_golden.py --record`.

## Цель (спека §12) — НЕ реализовано
- Ставки работ (`lib/pricing/works.ts`) без confidence; нет product-matching, гардрейлов стоимости генерации;
  YooKassa — только визуализация (`app/viz-actions.ts`); `/eval` нет; golden-формулы смет — цель мастера.
**Tier 2:** `../../docs/tech-spec-ts-stack.md` §12 (регресс), §8 (самопроверка).
