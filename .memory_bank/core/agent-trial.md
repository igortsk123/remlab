---
tier: 1
topic: agent-trial
scope: Проба агента недвижимости (UK) — план, воркер, стадии, тур /try
tier2: "../plans/MASTER-agent-trial.md"
updated: 2026-11-12
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
- **Задание:** `app/try/page.tsx` → `POST /api/trial` → `trial_jobs` (`db/init/022-trial-jobs.sql` … 033);
  лимиты — ADR-0371 (`lib/trial/upload-limits.ts`, `own-key.ts`), хранение 30 дн (`lib/trial/config.ts:trialFileHours`).
- **Воркер DEV:** `tools/floorplan/worker.py`, юнит `remlab-trial-worker`; аренда — `lib/trial/repo-worker.ts`. Не берёт при < 3 ГБ,
  ≥ 2 ждущих тяжёлых, прод не 200. Правка Python — после перезапуска (урок 608).
- **Стены:** `tools/floorplan/pipeline.py`; неуверенное — флаги; лист — `tools/floorplan/bench.py:dev_sheet` (ADR-0374);
  балкон — `other` + `outdoor` (ADR-0375); регресс — `tools/floorplan/regress.py`.
- **Стадии:** `tools/floorplan/conveyor.py` — v1 → гостиная `tools/scout/trial_demo.py` → спальни `tools/scout/trial_bedroom.py`; данные —
  `tools/scout/trial_bundle.py`. Не подтверждён масштаб или размер комнаты — `awaiting_check` (`trial_bundle.py:size_check`), «Обустроить» — `conveyor.Rebuild`.
- **Тур:** `app/try/[id]/tour/[[...path]]/route.ts`; витрина закреплена (`lib/trial/tour-bundle.ts:ensureJobRelease`) — правки
  страницы — после публикации демо и `tools/floorplan/reissue.py`. Ссылка покупателя (без `k`) закрыта до «Подтвердить планировку» —
  `lib/trial/buyer-gate.ts` (ADR-0386); проёмы — как у застройщика (ADR-0399). Исходник плана — агенту по `?k=` (`lib/trial/tour-source.ts`, П1.14).
- **Скорость (ADR-0376):** ракурсы — `tools/scout/cams_par.py`; карточки — `tools/floorplan/cards.py`.
- **Товары:** `trial_bundle.py:catalog_goods`; EN — £ = ₽ × курс × 1,5 (`trial_bundle.py:uk_money`).
- **Правка агентом (ссылка с `k`, ADR-0373):** комнаты — `tools/floorplan/room_edits.py` (площадь sx·sy, `_scaled`), проёмы —
  `tools/floorplan/opening_edits.py`; черновики — `lib/trial/repo-draft.ts`, один пересчёт — `lib/trial/repo-confirm.ts`.
- **Перечитать (ADR-0377):** `conveyor.py:Reparse`, тот же адрес.
- **Фото:** `trial_bundle.py:photo_ok` — обставленная гостиная/спальня и `user_dims` или масштаб `verified`/`listing` без флага
  размера и не «как есть»; ≤ 10 на задание за 24 ч (`lib/trial/repo-photo.ts`).

Детали — Tier 2 § «Устройство 10–12.11»; уроки — `lessons/floorplan-trial.md`.
