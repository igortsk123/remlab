---
tier: 1
topic: agent-trial
scope: Проба агента недвижимости (UK) — план, воркер, стадии, тур /try
tier2: "../plans/MASTER-agent-trial.md"
updated: 2026-11-13
importance: high
source: _intake/session-scratch.md
status: working
source_of_truth: canonical
last_verified: 2026-11-12
review_after: 2026-12-10
---

# Проба агента — Tier 1

План (+ объявление) → стены → комнаты → гостиная и спальни → фото; итог — `/demo` под план (ADR-0372).

## По коду
- **Задание:** `app/try/page.tsx` → `POST /api/trial` → `trial_jobs` (`db/init/022-trial-jobs.sql` … 037); лимиты — ADR-0371
  (`lib/trial/upload-limits.ts`, `own-key.ts`), хранение 30 дн (`lib/trial/config.ts:trialFileHours`).
- **Воркер DEV:** `tools/floorplan/worker.py`, юнит `remlab-trial-worker`, аренда `lib/trial/repo-worker.ts`; не берёт при < 3 ГБ,
  ≥ 2 тяжёлых, прод не 200; правка — после перезапуска (урок 608).
- **Стены:** `tools/floorplan/pipeline.py`, лист `tools/floorplan/bench.py:dev_sheet` (ADR-0374), балкон `outdoor` (ADR-0375),
  регресс `tools/floorplan/regress.py`.
- **Стадии:** `tools/floorplan/conveyor.py` → гостиная `tools/scout/trial_demo.py` → спальни `tools/scout/trial_bedroom.py`
  (стиль — ≤ 16 вызовов решателя, `STYLE_SOLVES`, ADR-0414); данные `tools/scout/trial_bundle.py`; нет масштаба — `awaiting_check`
  (`trial_bundle.py:size_check`), «Обустроить» — `conveyor.Rebuild`.
- **Тур:** `app/try/[id]/tour/[[...path]]/route.ts`; витрина закреплена (`lib/trial/tour-bundle.ts:ensureJobRelease`), обновляет
  `tools/floorplan/reissue.py` (мебель подтверждённого тура держит — новое правило дойдёт после переподтверждения). Ссылка покупателя
  закрыта до «Подтвердить планировку» (`lib/trial/buyer-gate.ts`, ADR-0386); проёмы — как у застройщика (ADR-0399); исходник —
  агенту по `?k=` (`lib/trial/tour-source.ts`).
- **Скорость (ADR-0376):** `tools/scout/cams_par.py`, `tools/floorplan/cards.py`. **Товары:** `trial_bundle.py:catalog_goods`, £ —
  `trial_bundle.py:uk_money`.
- **Правка агентом (ADR-0373):** `tools/floorplan/room_edits.py`, `tools/floorplan/opening_edits.py`; черновики
  `lib/trial/repo-draft.ts`, пересчёт `lib/trial/repo-confirm.ts`. **Перечитать (ADR-0377):** `conveyor.py:Reparse`.
- **Фото:** `trial_bundle.py:photo_ok`; ≤ 10 за 24 ч (`lib/trial/repo-photo.ts`), хранятся у тура (034). **Автофото (ADR-0416):**
  подтверждение → партия ≤ 5 комнат × C1/C2 (`lib/trial/auto-photos-queue.ts`, `tools/scout/rules/tour-auto-photos.json`, 036–037),
  съёмщик DEV `tools/ops/tour-auto-photos.mjs`, таймер `remlab-tour-photos`.

Детали — Tier 2 § «Устройство 10–12.11», § «Автофото тура»; уроки — `lessons/floorplan-trial.md`.
