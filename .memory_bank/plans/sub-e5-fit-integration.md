---
workstream: ml
slug: sub-e5-fit-integration
title: "Э5 (=Ф8): ml-service в проде — fit, вставка в масштабе, правка человеком"
status: draft
created: 2026-07-11
updated: 2026-07-11
completed:
---

# Э5 (=Ф8): ml-service в проде

## Цель
Замер, fit-проверка и вставка товара в масштабе — в прод отдельным Python-контейнером с жёсткими контрактами: пользователь видит «влезет/нет» и товар в комнате.

## Источник задачи
Э5 [[commercial-master-plan]] (= Ф8 [[MASTER-roadmap]]). Зависимости: gate `sub-ml-sizes`, каталог Э2.

## Прочитай сначала
- `.memory_bank/plans/`: `MASTER-roadmap.md` (Ф8: fit=Shapely, вставка=композитинг, НЕ генерация), `commercial-master-plan.md` (Э5: gate/kill), `unified-measurement-pipeline.md`.
- Код: `docker-compose.yml` (healthcheck `db`, internal-only `imagor`); трейс — `lib/trace/recorder.ts`, `lib/providers/traced.ts`; фейк — `lib/providers/index.ts` + `fake.ts` (`REMLAB_FAKE_AI=1`); Zod — `contracts/project.ts`.
- `/home/pakar/mltest/`: `geometry_solver.py`, `fit_check.py`, `run_viz.py`, `product_match.py` (ВНЕ git!); `.memory_bank/deployment.md` + `deploy.sh` (сервер ARM 2vCPU/3.7GB; remnanode НЕ трогать).

## Скоуп — что входит
1. Бэкенд: `ml/service` (FastAPI, 4 эндпоинта; Python из mltest как есть); контракты Zod↔pydantic (JSON Schema, contract-тесты в CI); трейсинг; фейк для e2e.
2. Продукт: A4-шаг (опц.), fit-фильтр, бейджи, вставка, правка Ш×Г×В; аналитика бизнес-gate.

## Скоуп — что НЕ входит
- Видео-тир; идеальный перелайт («не режет глаз» достаточно).
- Переписывание Python в TS — ЗАПРЕЩЕНО (ре-валидация точности).
- Cost Engine (9900₽ руками); юр. логика (TODO).
- Эмбеддинг-подбор, vector-колонки — Э2/Ф5.

## Файлы к изменению
- [ ] Новые: `ml/service/` (+`Dockerfile`, `tests/`); `contracts/ml.ts` + `contracts/fixtures/ml/`; `lib/ml/client.ts` + `lib/ml/fake.ts`; `e2e/fit.spec.ts`.
- [ ] Правки: `lib/trace/types.ts` (`StepKind` += `"ml"`); `docker-compose.yml`; `deploy.sh`; `.github/workflows/ci.yml`; `app/p/[id]/{brief,preview}/page.tsx` (+ `components/`); `app/api/p/[id]/` (handlers fit/insert рядом с `analyze/`, `generate/`); `modules/ideas/index.ts` ЛИБО каталог Э2; `lib/analytics.ts`; `playwright.config.ts`.

## Задачи

### A — каркас ml-service
- [ ] `GET /health` → `{status:"ok"}`; Dockerfile `python:3.12-slim` (fastapi, uvicorn, opencv-python-headless, shapely, numpy, httpx, pydantic). БЕЗ весов: SAM2/LaMa — fal.ai per-request (как в `run_viz.py`); ключ env `FAL_KEY` (только `.env` сервера).
- [ ] Compose: без ports (образец `imagor`), healthcheck (образец `db`), `mem_limit: 512m`, `remlab-net`.
- [ ] Перенос как есть: `geometry_solver.py`, `fit_check.py`, вставка из `run_viz.py`; алгоритмы не переписывать, прототипы не трогать.

### B — контракты
- [ ] `/scene/analyze` `{imageUrl,a4Hint?}` → `{scalePxPerCm,floorPolygonCm,freeFloorPolygonCm,objects[{name,bboxPx,footprintCm,confidence}]}`; `/fit-check` `{zoneWcm,zoneDcm,prodWcm,prodDcm}` → `{fits,overflowCm,note}`; `/insert` `{imageUrl,targetMask|bboxPx,productImageUrl,placement}` → `{resultImageUrl}`.
- [ ] Истина — JSON Schema (`zod-to-json-schema` из `contracts/ml.ts`).
- [ ] Фикстуры: валид + невалид на эндпоинт; vitest=Zod, pytest=pydantic; расхождение = красный у обеих; в `ci.yml`.

### C — Next + трейсинг + фейк
- [ ] `StepKind` += `"ml"`; `/api/trace/*` и `/trace N` не падают на новом kind.
- [ ] `lib/ml/client.ts`: env `ML_SERVICE_URL`; каждый вызов — `recordStep` в `runWithTrace` (образец `traced.ts`).
- [ ] `lib/ml/fake.ts`: детерминированные ответы (бит-в-бит); включение по образцу `fakeEnabled()`; `REMLAB_FAKE_ML=1` — в `webServer.command` (`playwright.config.ts`).

### D — продукт
- [ ] Brief: опц. шаг «фото с листом A4 на полу»; без A4 — эвристики, точность ниже — пометить в UI.
- [ ] Fit-фильтр: габариты товара vs зона из `/scene/analyze`. Сейчас подбор — заглушка `buildCatalog()` (`modules/ideas/index.ts`) без габаритов и таблицы товаров; фильтр — на схему каталога Э2; без замера выключен.
- [ ] Preview: бейджи «влезет (зазор N см)» / «велик на N см».
- [ ] Вставка: кнопка → handler → `/insert`; ассет в трейс.
- [ ] Правка: имя + Ш×Г×В → повторный `/fit-check` БЕЗ анализа сцены (human-fallback, Ф5).
- [ ] События `a4_step_offered/accepted`, `fit_verdict_shown`, `insert_clicked` — в `EventName` + реальные `track()` (не как brief_completed: объявлено, не шлётся).

### E — выкат и нагрузка
- [ ] Сначала выкатить свежий `main` (`feature/pipeline-tracing` уже влит).
- [ ] `deploy.sh`: образ ml (arm64) по образцу app; smoke `/health`; бэкап compose; откат.
- [ ] RAM: `docker stats` при 2–3 параллельных `/scene/analyze` + `/insert`.

## Гейты
- [ ] `pnpm typecheck && pnpm lint && pnpm test && pnpm build` и `pnpm e2e` (фейк: brief→preview с бейджами) — зелёные.
- [ ] Contract-тесты зелёные у обеих сторон; `/fit-check` дважды → бит-в-бит тот же ответ (pytest).
- [ ] Шаги `kind="ml"` со сквозным run_id в `generation_runs/steps/assets` (видны в `/trace N`).
- [ ] Прод: `/health` ml отвечает изнутри `remlab-net` (`curl`), снаружи порт закрыт; суммарный RAM < 3.4GB под нагрузкой; бизнес-gate (2–4 нед): uplift CTR/оплат с fit ≥ +20% (PostHog).

## Чекпоинты владельца
- ⏸ До выката: скрины бейджей и вставки (3 комнаты). «Правдоподобно? Не отпугивает?»
- ⏸ Спорные вердикты: overlay (контур пола + цифры). «Верим глазам или замеру?»
- ⏸ RAM ≥ 3.4GB: `docker stats`. «CAX21 8GB (~+4 евро/мес) или урезаем ml?»
- ⏸ Бизнес-gate: PostHog (adoption A4, CTR/оплаты с/без fit). «Gate или бэклог (adoption <10% И uplift нет)?» Решает владелец.

## Если пошло не по плану
- Контракты разъехались → JSON Schema истина, правим отстающую; НЕ ослаблять.
- fal.ai недоступен → скрыть вставку флагом (бейджи работают без fal); > суток → эскалация.
- RAM → конкурентность ml до 1; чекпоинт CAX21.
- Замер нестабилен → сверка с golden `sub-ml-sizes`; вердикт при высоком `confidence`; режет >50% → эскалация.
- A4 игнорируют → не сбой, kill-метрика: adoption до чекпоинта.

## Критерии приёмки
- [ ] Прод: internal-only ml-service (512m, healthcheck, remnanode не тронута); 3 эндпоинта по контракту; флоу brief → бейджи → вставка → правка с пересчётом.
- [ ] ml-шаги в `/trace N`; contract- и e2e-тесты в CI; аналитика шлётся; чекпоинты пройдены.

## Definition of Done — память
- [ ] `core/architecture.md`; `core/access-and-integrations.md` (fal.ai: env `FAL_KEY`, без значений); новая область → `core/ml-service.md` (Tier 1 ≤3 KB) + Tier 2.
- [ ] Решения → `decisions.md`; этап → `project-state.md` (убрать устаревшее «прод впереди main»).
- [ ] `/memory-check`, audit «чисто»; реестр [[commercial-master-plan]] обновлён; затем → `completed_plans/`.

## Лог выполнения
- 2026-07-11 — план создан, draft.

## Completion summary

## Follow-up work
- Э2/Ф5: эмбеддинг-подбор; перелайт вставки — после бизнес-gate.
- Автоматизировать `tools/trace-prune.mjs` (пока вручную); UK: см/дюймы в вердиктах.
