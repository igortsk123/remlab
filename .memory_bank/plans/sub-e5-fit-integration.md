---
workstream: ml
slug: sub-e5-fit-integration
title: Э5 (=Ф8): ml-service в проде — fit-вердикты, вставка в масштабе, правка человеком
status: draft
created: 2026-07-11
updated: 2026-07-11
completed:
---

# Э5 (=Ф8): ml-service в проде — fit-вердикты, вставка в масштабе, правка человеком

## Цель
Вывести измерительный ML-стек (замер сцены, fit-проверка, вставка товара в масштабе) в прод как отдельный
Python-контейнер с жёсткими контрактами к Next.js; пользователь видит «влезет/не влезет» и товар в своей комнате.

## Источник задачи
Этап Э5 коммерческого мастер-плана [[commercial-master-plan]] (= Ф8 [[MASTER-roadmap]]), сессия 2026-07-11.

## Прочитай сначала
- `.memory_bank/plans/MASTER-roadmap.md` — Ф8 и стек-решения (композитинг, не генерация мебели).
- `.memory_bank/plans/commercial-master-plan.md` — строка Э5: gate, kill-критерий, зависимости.
- `.memory_bank/plans/unified-measurement-pipeline.md` — как устроен замер (A4, контур, масштаб).
- `docker-compose.yml` — паттерн сервисов: `remlab-net`, `mem_limit`, healthcheck (см. `db`), internal-only (см. `imagor`).
- `lib/trace/types.ts` + `lib/trace/recorder.ts` (`runWithTrace`, `recordStep`) + `lib/providers/traced.ts` — паттерн инструментирования шагов.
- `lib/providers/index.ts` + `lib/providers/fake.ts` — паттерн фейк-флага (`REMLAB_FAKE_AI=1`), повторить для ML.
- `contracts/project.ts` — стиль Zod-контрактов проекта.
- `/home/pakar/mltest/geometry_solver.py`, `fit_check.py`, `run_viz.py`, `product_match.py` — рабочие Python-прототипы (ВНЕ git!).
- `.memory_bank/deployment.md` + `deploy.sh` — как катим, лимиты сервера (ARM 2vCPU/3.7GB, remnanode не трогать).

## Скоуп — что входит
1. Контейнер `ml/service`: FastAPI+uvicorn, эндпоинты `/health`, `/scene/analyze`, `/fit-check`, `/insert`.
2. Перенос проверенной Python-логики из `/home/pakar/mltest` внутрь `ml/service` (Python→Python, без переписывания).
3. Контракты в двух мирах: `contracts/ml.ts` (Zod) ↔ pydantic; единый источник — JSON Schema; contract-тесты
   на golden-фикстурах с обеих сторон (vitest + pytest) в CI.
4. Трейсинг: вызовы ml-service — шаги прогона `kind="ml"` со сквозным `run_id`; фейк `REMLAB_FAKE_ML=1` для e2e.
5. Продукт: опциональный A4-шаг в brief; fit-фильтр в подборе Э2; бейджи «влезет/велик» в preview;
   кнопка «показать в моей комнате» (вставка); экран минимальной правки (имя/Ш×Г×В → пересчёт fit).
6. Аналитика для бизнес-gate: события adoption A4 и CTR/оплат в когорте с fit.

## Скоуп — что НЕ входит
- Видео-тир; совершенство перелайта (достаточно «не режет глаз»).
- Переписывание Python-логики в TS — ЗАПРЕЩЕНО (потребует ре-валидации точности).
- Cost Engine / смета (тир 9900₽ исполняется руками); юридическая логика (TODO, не блокироваться).
- Эмбеддинг-подбор DINOv3/SigLIP2 (отдельный этап Э2/Ф5); vector-колонки в БД.

## Файлы к изменению
- [ ] `ml/service/` (новый) — FastAPI-приложение: `main.py`, роутеры, pydantic-модели, перенесённые модули замера/fit/вставки, `requirements.txt`, `Dockerfile`, `tests/` (pytest).
- [ ] `contracts/ml.ts` (новый) — Zod-схемы запросов/ответов трёх эндпоинтов.
- [ ] `contracts/fixtures/ml/` (новый) — golden JSON-фикстуры, общие для vitest и pytest.
- [ ] `lib/ml/client.ts` (новый) — типизированный клиент ml-service: fetch → Zod-parse → трейс-шаг; ветка `REMLAB_FAKE_ML`.
- [ ] `lib/ml/fake.ts` (новый) — детерминированные фейк-ответы (по образцу `lib/providers/fake.ts`).
- [ ] `lib/trace/types.ts` — расширить `StepKind` значением `"ml"`.
- [ ] `docker-compose.yml` — сервис `ml`: `remlab-net`, `mem_limit: 512m`, healthcheck `GET /health`, БЕЗ публикации портов.
- [ ] `deploy.sh` — сборка/выкат образа ml-service (arm64) по образцу app; smoke дополнить `/health` ml.
- [ ] `.github/workflows/ci.yml` — джоба pytest + contract-тесты обеих сторон.
- [ ] `app/p/[id]/brief/page.tsx` — опциональный шаг «фото с листом A4».
- [ ] `app/p/[id]/preview/page.tsx` (+ новые компоненты в `components/`) — бейджи fit, кнопка «показать в моей комнате», экран правки размеров.
- [ ] `app/api/p/[id]/` — новые route handlers для fit/insert (точные имена — при реализации, рядом с `analyze`/`generate`).
- [ ] `modules/ideas/index.ts` (или его преемник после Э2) — fit-фильтр в подборе по `w_cm/d_cm` товара vs зона.
- [ ] `lib/analytics.ts` — события `a4_step_offered/accepted`, `fit_verdict_shown`, `insert_clicked`.
- [ ] `e2e/fit.spec.ts` (новый) — сквозной сценарий под `REMLAB_FAKE_ML=1`.

## Задачи

### Блок A — каркас ml-service
- [ ] Создать `ml/service`: FastAPI + uvicorn; `GET /health` → `{status:"ok"}`. Dockerfile на `python:3.12-slim`,
      зависимости: `fastapi`, `uvicorn`, `opencv-python-headless`, `shapely`, `numpy`, `httpx`, `pydantic`.
      БЕЗ тяжёлых весов в образе: нейросетевое (SAM/LaMa) — только через fal.ai per-request; ключ читать из
      env `FAL_KEY` (лежит в `.env` на сервере, в git не попадает).
- [ ] Добавить сервис в `docker-compose.yml`: сеть `remlab-net`, `mem_limit: 512m`, healthcheck на `/health`,
      порт наружу НЕ публиковать (доступ только от `app`, образец — `imagor`).
- [ ] Перенести из `/home/pakar/mltest` модули: `geometry_solver.py` (масштаб/контур), `fit_check.py`
      (Shapely, детерминизм), логику вставки из `run_viz.py` (SAM2+LaMa через fal + композитинг).
      Перенос как есть + мелкая адаптация под пакетную структуру; НЕ переписывать алгоритмы.
      ВАЖНО: mltest вне git — после переноса код живёт в репо, прототипы остаются нетронутыми.

### Блок B — контракты (Zod ↔ pydantic)
- [ ] Зафиксировать контракт трёх эндпоинтов:
      `POST /scene/analyze` `{imageUrl, a4Hint?}` → `{scalePxPerCm, floorPolygonCm, freeFloorPolygonCm, objects[{name,bboxPx,footprintCm,confidence}]}`;
      `POST /fit-check` `{zoneWcm,zoneDcm,prodWcm,prodDcm}` → `{fits,overflowCm,note}`;
      `POST /insert` `{imageUrl, targetMask|bboxPx, productImageUrl, placement}` → `{resultImageUrl}`.
- [ ] Единый источник — JSON Schema (через `zod-to-json-schema` из `contracts/ml.ts` или вручную рядом с фикстурами).
- [ ] Golden-фикстуры в `contracts/fixtures/ml/`: на каждый эндпоинт минимум пара валидный запрос+ответ и
      по одному невалидному. Contract-тесты: vitest парсит фикстуры через Zod, pytest — через pydantic.
      Расхождение схем = красный тест с обеих сторон.
- [ ] Подключить pytest и оба contract-прогона в `.github/workflows/ci.yml`.

### Блок C — интеграция в Next + трейсинг + фейк
- [ ] `lib/trace/types.ts`: `StepKind` += `"ml"`; проверить, что `/api/trace/*` и разбор `/trace N` не падают на новом kind.
- [ ] `lib/ml/client.ts`: базовый URL из env (`ML_SERVICE_URL`, в compose — имя сервиса), каждый вызов записывать
      через `recordStep` внутри активного `runWithTrace` (образец — `lib/providers/traced.ts`): вход/выход/время/ошибка.
- [ ] `REMLAB_FAKE_ML=1` → `lib/ml/fake.ts`: фиксированные детерминированные ответы (тот же вход → бит-в-бит тот же выход),
      переключение по образцу `lib/providers/index.ts`.

### Блок D — продуктовая интеграция
- [ ] Brief: опциональный шаг «Сфотографируйте комнату с листом A4 на полу — так мы измерим её с точностью до сантиметров».
      Пропускаемый; без A4 работаем по эвристикам масштаба (точность ниже — честно пометить в UI).
- [ ] Подбор (Э2): в SQL-запрос подбора добавить fit-фильтр `products.w_cm/d_cm` vs габариты зоны замены
      (из `/scene/analyze`); без замера — фильтр выключен.
- [ ] Preview: бейдж у товара — «влезет (зазор N см)» / «велик на N см» (из `/fit-check`).
- [ ] Кнопка «показать в моей комнате» → route handler → `/insert` → показать результат; ассет записать в трейс.
- [ ] Экран минимальной правки: пользователь исправляет имя объекта и Ш×Г×В → мгновенный пересчёт fit
      (повторный `/fit-check`, без повторного анализа сцены). Это human-fallback из MASTER-roadmap.
- [ ] Аналитика: `a4_step_offered/accepted` (adoption), `fit_verdict_shown`, `insert_clicked` — реально отправлять
      (не повторить судьбу объявленных-но-не-шлющихся событий).

### Блок E — выкат и нагрузка
- [ ] `deploy.sh`: собрать/выкатить образ ml (arm64), smoke `/health`; бэкап compose перед правкой; откат предусмотрен.
- [ ] Замерить RAM всех контейнеров под нагрузкой (`docker stats` при 2–3 параллельных `/scene/analyze` + `/insert`).

## Гейты
- [ ] `pnpm typecheck && pnpm lint && pnpm test && pnpm build` — зелёные.
- [ ] Contract-тесты зелёные с ОБЕИХ сторон: vitest (фикстуры через Zod) и pytest (те же фикстуры через pydantic).
- [ ] Детерминизм: один и тот же вход в `/fit-check` дважды → бит-в-бит одинаковый ответ (pytest-тест).
- [ ] `pnpm e2e` с `REMLAB_FAKE_ML=1` — сценарий brief→preview с бейджами проходит.
- [ ] Полный прогон записан в `generation_runs/steps/assets`: есть шаги `kind="ml"` со сквозным `run_id`; разбор `/trace N` показывает их.
- [ ] На проде: `curl` изнутри сети — `/health` ml отвечает; снаружи порт ml НЕ доступен.
- [ ] RAM всех контейнеров под нагрузкой < 3.4GB (иначе — чекпоинт про апгрейд сервера, см. ниже).
- [ ] Бизнес-gate (после выката, 2–4 недели): uplift CTR/оплат в когорте с fit ≥ +20% (PostHog).

## Чекпоинты владельца
- ⏸ ПОКАЗАТЬ ВЛАДЕЛЬЦУ (до выката): скрины бейджей «влезет/велик» и вставленного товара на 3 разных комнатах.
  Вопрос: «Вердикты выглядят правдоподобно? Вставка не отпугивает качеством?»
- ⏸ ПОКАЗАТЬ ВЛАДЕЛЬЦУ (при спорных вердиктах): overlay замера — фото с наложенным контуром пола и цифрами.
  Вопрос: «Какому из вердиктов верим — глазам или замеру?»
- ⏸ ПОКАЗАТЬ ВЛАДЕЛЬЦУ (если RAM ≥ 3.4GB): таблица `docker stats` под нагрузкой.
  Вопрос: «Апгрейдим сервер до CAX21 8GB (~+4 евро/мес) или урезаем ml-функции?»
- ⏸ ПОКАЗАТЬ ВЛАДЕЛЬЦУ (бизнес-gate через 2–4 недели): таблица PostHog — adoption A4-шага, CTR/оплаты с fit и без.
  Вопрос: «Gate пройден или (adoption <10% И uplift неразличим) → fit в бэклог?» — kill-решение только за владельцем.

## Если пошло не по плану
- **Контракты разъехались** (vitest зелёный, pytest красный или наоборот) → диагностика: сверить JSON Schema с обеими
  схемами → fallback: JSON Schema — истина, правим отстающую сторону; НЕ ослаблять схему «чтобы прошло».
- **fal.ai недоступен/дорог на `/insert`** → диагностика: коды ошибок/латентность в трейсе → fallback: кнопку вставки
  скрыть фиче-флагом, fit-бейджи оставить (они без fal) → эскалация, если fal лежит > суток.
- **RAM за пределами** → диагностика: `docker stats` по контейнерам, утечки в ml (перезапуск помогает?) → fallback:
  ограничить конкурентность ml до 1 запроса → чекпоинт про CAX21.
- **Замер нестабилен на проде** (вердикты скачут на одном фото) → диагностика: сравнить с golden из sub-ml-sizes,
  overlay-чекпоинт → fallback: показывать вердикт только при `confidence` выше порога → эскалация: порог режет >50% фото.
- **A4-шаг игнорируют** → это не сбой, а kill-метрика: копить adoption в PostHog, решение на бизнес-чекпоинте.
- **Прод собран из `feature/pipeline-tracing` и впереди `main`** → перед стартом свести ветки (прод wins для живых
  фактов), работать от актуального состояния; не начинать Блок E, пока main не догнал прод.

## Критерии приёмки
- [ ] ml-service в проде: internal-only, healthcheck зелёный, mem_limit 512m, remnanode не тронута.
- [ ] Три эндпоинта работают по контракту; contract-тесты в CI с обеих сторон.
- [ ] Пользовательский флоу: brief (A4 опционально) → preview с fit-бейджами → «показать в моей комнате» → правка размеров с пересчётом.
- [ ] Прогоны с ml-шагами видны в `/trace N`; e2e на `REMLAB_FAKE_ML` в CI.
- [ ] Аналитика для бизнес-gate реально шлётся; чекпоинты владельца пройдены.

## Definition of Done — память
- [ ] `core/architecture.md` — появление ml-service (контейнер, контракты, границы); `core/access-and-integrations.md` — fal.ai из ml-service (имя env `FAL_KEY`, без значений).
- [ ] Новая область → `core/ml-service.md` (Tier 1 сводка ≤3 KB) + детали Tier 2.
- [ ] Решения (контракт, kill/gate-исходы) → `decisions.md`; смена этапа → `project-state.md`.
- [ ] `/memory-check` выполнен, audit «чисто»; статус в реестре [[commercial-master-plan]] обновлён.
- [ ] План → `completed_plans/` только после всего перечисленного.

## Лог выполнения
- 2026-07-11 — записан черновик БЕЗ verify-прохода (проверка путей/фактов вдогонку перед «деплой»)
- 2026-07-11 — план создан, draft.

## Completion summary

## Follow-up work
- Э2/Ф5: эмбеддинг-подбор (DINOv3/SigLIP2 + pgvector HNSW) поверх fit-фильтра.
- Перелайт вставки (качество композитинга) — отдельной итерацией после бизнес-gate.
- Автоматический prune трейсов ml-шагов (`tools/trace-prune.mjs` — сейчас вручную).
- UK-локаль: единицы измерения (см/дюймы) в fit-вердиктах — при выходе на UK.
