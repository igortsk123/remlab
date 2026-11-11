---
tier: 1
topic: agent-trial
scope: Проба для агента недвижимости (UK) — лендинг, загрузка плана, задание, воркер DEV, конвейер стадий, тур /try под план
tier2: "../plans/MASTER-agent-trial.md"
updated: 2026-11-11
importance: high
source: _intake/session-scratch.md
status: working
source_of_truth: canonical
last_verified: 2026-11-10
review_after: 2026-12-10
---

# Проба агента — Tier 1

Лендинг → план (+ объявление) → ссылка сразу; по готовности стены → комнаты → гостиная и спальни → AI-фото. Итог — `/demo` под план.

## По коду
- **Задание:** `app/try/page.tsx` → `POST /api/trial` → `trial_jobs` (`db/init/022-trial-jobs.sql`, колонки — 023, 024; `trial_rebuilds` — 025, `trial_photos` — 026);
  ≤ 300/сутки (`trialDailyCap`).
- **Воркер DEV:** `tools/floorplan/worker.py`, юнит `tools/floorplan/systemd/remlab-trial-worker.service` (MemoryMax 2G);
  аренда — `lib/trial/repo-worker.ts` (скалярный `skip locked`). Не берёт при < 3 ГБ (`TRIAL_MEM_MIN_GB`), ≥ 2 в heavy-очереди,
  прод `/api/health` не 200.
- **Стены:** `tools/floorplan/pipeline.py`; неуверенное — флаги (`_room_flags`); масштаб без подписей — по стене или площади
  со статусом `not_verified`. Проёмы «Этажей» — только у листа застройщика (`tools/floorplan/bench.py:dev_sheet`);
  регресс разбора — `tools/floorplan/regress.py`.
- **Стадии:** `tools/floorplan/conveyor.py` — v1 без мебели → гостиная `trial_demo.py` → спальни `trial_bedroom.py`; `done` — после последней версии
  (`_finish`), сбой — отказ по комнате. Данные страницы — `tools/scout/trial_bundle.py`.
- **Размеры:** «не сошлось» или масштаб не подтверждён — `awaiting_check`, без мебели (`trial_bundle.py:SCALE_UNVERIFIED_AWAITS_CHECK`);
  «Обустроить» — `conveyor.Rebuild`.
- **Тур:** `app/try/[id]/tour/[[...path]]/route.ts` (страница `/demo` под `TRIAL()`); версия — `lib/trial/tour-bundle.ts:ensureJobRelease`.
- **Товары:** как в /demo (`trial_bundle.py:catalog_goods`); EN — £ ×1,5 без магазина (`uk_money`); фото — плитка /demo (`demo_img`).
- **Фото:** при `trial_bundle.py:photo_ok`, ≤ 10 на задание за 24 ч (`trialPhotoDaily`).

- **Правка агентом (ссылка с `k`):** комната — `tools/floorplan/room_edits.py`, проёмы — `opening_edits.py`; черновиком
  (`lib/trial/repo-draft.ts`, 032), одна пересборка по «Подтвердить планировку» (`lib/trial/repo-confirm.ts`); детали — Tier 2 § черновики.
- **Ленты /demo:** `tools/scout/demo_feeds.py`; перевыпуск — `publish_demo.sh` → `tools/floorplan/reissue.py --days 14`.

## Хранение
30 дн (`lib/trial/config.ts:trialFileHours`); лимиты — `lib/trial/upload-limits.ts`; наши машины — `lib/trial/own-key.ts`; email и ip_hash не храним.

Уроки — `lessons/floorplan-trial.md`.
