---
tier: 1
topic: agent-trial
scope: Проба для агента недвижимости (UK) — лендинг, загрузка плана, задание, воркер DEV, конвейер стадий, тур /try под план
tier2: "../plans/MASTER-agent-trial.md"
updated: 2026-11-10
importance: high
source: _intake/session-scratch.md
status: working
source_of_truth: canonical
last_verified: 2026-11-10
review_after: 2026-12-10
---

# Проба агента — Tier 1

Лендинг → фото/PDF плана (+ текст объявления) → ссылка сразу, всё появляется по готовности: стены → пустые комнаты → гостиная
и все спальни по шаблонам → AI-фото. Итог — ровно `/demo` под план. Решения — ADR 09.11; задачи — мастер (tier2) и `agent-trial-08`.

## По коду
- **Задание:** `app/try/page.tsx` → `POST /api/trial` → `trial_jobs` (`db/init/022-trial-jobs.sql`, колонки — 023, 024; `trial_rebuilds` — 025, `trial_photos` — 026); ≤ 30 заданий/сутки на сайт
  (`lib/trial/config.ts:trialDailyCap`); Метрики на /try нет (`lib/metrika.ts:noMetrikaPath`).
- **Воркер DEV:** `tools/floorplan/worker.py`, юнит `tools/floorplan/systemd/remlab-trial-worker.service` (MemoryMax 2G);
  аренда — `lib/trial/repo-worker.ts` (скалярный `skip locked`). Не берёт при < 3 ГБ (`TRIAL_MEM_MIN_GB`), ≥ 2 в heavy-очереди,
  прод `/api/health` не 200; 3 сбоя подряд по нашей вине — пауза 10 мин.
- **Стены:** `tools/floorplan/pipeline.py`; неуверенное — флаги (`_room_flags`); масштаб без подписей — по стене или площади
  со статусом `not_verified`.
- **Стадии:** `tools/floorplan/conveyor.py` — v1 без мебели → гостиная `trial_demo.py` → спальни `trial_bedroom.py`; `done` — всегда после
  последней версии (`_finish`), недоделанное — только в журнал; сбой — отказ по комнате. Данные страницы — `tools/scout/trial_bundle.py`.
- **Размеры:** «не сошлось» или масштаб не подтверждён — `awaiting_check`, без мебели (`trial_bundle.py:SCALE_UNVERIFIED_AWAITS_CHECK`);
  «Обустроить» — `conveyor.Rebuild`.
- **Тур:** `app/try/[id]/tour/[[...path]]/route.ts` (страница `/demo` под `TRIAL()`); версия — `lib/trial/tour-bundle.ts:ensureJobRelease`.
- **Фото:** при `trial_bundle.py:photo_ok`, ≤ 10 на задание за 24 ч (`trialPhotoDaily`); обложка `tools/scout/trial_hero.py`
  в конвейер не подключена (`conveyor.after_done` — заглушка).

## Хранение
План 24 ч после итога, результат 30 дн (`trialFileHours`, `trialResultDays`); email и ip_hash не храним.

## Лендинг
`/test/landing/` (EN) и `/test/landing/ru.html`, noindex — показ человеку; исходник вне репо.

## Дыры 10.11
Решения ночи — ADR-0360…0364, уроки — `lessons/floorplan-trial.md`. Лист C: стены 764 с при пределе 900 с (`worker.py`), второй этаж не виден.
