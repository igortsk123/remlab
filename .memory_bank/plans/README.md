# Plans — активные планы

## Lifecycle
```
draft → in_progress → completed → перенос в completed_plans/
                   ↘ partial   → остаётся здесь ТОЛЬКО с полями pause_reason / resume_trigger / review_after
        cancelled / отложенное / поглощённое → archive/plans/ (с archive_reason, superseded_by)
```
Только `completed` переносятся в `completed_plans/`. **Гейт:** план не становится `completed`, пока не
выполнен `/memory-check` и audit не «чисто» (см. `.claude/rules/agent-workflow.md`).

## Статусы и поля
| Статус | Описание |
|--------|----------|
| `draft` | Создан, ждёт команду «деплой». Старше 30 дней без `review_after` → триаж (проектный аудит) |
| `in_progress` | Деплой начат. Без движения >14 дней → `PLAN-STUCK` (аудит кита) |
| `partial` | Прерван. Обязательны `pause_reason`, `resume_trigger`, `review_after` (+ `owner_decision_required`) |
| `completed` | Всё выполнено → перенести в `completed_plans/` |
| `cancelled` | Отменён явно → после записи уроков в `archive/plans/` |

Доп. поля (плоские строки): `plan_kind` — `portfolio_master` (один: `MASTER-cost-first`) ·
`track_master` (мастер трека, `parent_plan: MASTER-cost-first`) · `sub` (по умолчанию).
**Мастер-планы (кит v1.9):** `portfolio_master`/`track_master` с будущей `review_after` не считаются застрявшими
(`PLAN-STUCK`); дата пересмотра прошла или не задана — снова находка с подсказкой.
Отложенное/поглощённое уходит в `archive/plans/` со статусом как есть + `archived`, `archive_reason`,
`superseded_by` — вернуть можно в любой момент (`git mv` обратно, поля убрать).
Триаж 2026-09-05: 53 плана ушли в архив (манифест — `changelog/memory-log.md`), открытых ≤ 25.

## Сейчас в работе (ручная сводка; обновлять при смене фокуса)
- **Портфель:** `MASTER-cost-first` — порядок ступеней временно М5 → М2–М4 (решение владельца 05.09).
- **Трек мебели (М5):** пул мешей (`mesh-pool-hardening`, `mesh-dynamic-node-pool`, `mesh-bulk-salad-hunyuan`,
  `mesh-queue-orientation`, `orient-v2`, `viz-mesh-orientation`, `photo-improve-from-mesh`, `mesh-owner-audit`),
  демо-планировщик (`MASTER-interactive-planner`, `demo-collection-flow`, `topview-from-mesh`,
  `demo-planner-structure` — пауза), каталог (`stock-check-weekly-unified`, `stock-truth-page-verdict`).
- **На паузе (ждёт владельца):** расстановка — `MASTER-zones-v7`, `q12-situational-canon`, `exam-hardening-2208`.

## Реестр активных планов

<!-- GENERATED:plans-registry START -->
<!-- Таблицу регенерирует tools/memory-audit.mjs из frontmatter. Не редактируй вручную. -->

| slug | Название | status | created | updated |
|------|----------|--------|---------|---------|
| flat3d-sims-ux | Конфигуратор как игра — перестановка мебели, кнопки у предмета, вход через план, правая панель | in_progress | 2026-09-30 | 2026-09-30 |
| test-to-work | Внутренние отчёты переезжают с /test на /work; /test без слэша чинится | draft | 2026-09-28 | 2026-09-28 |
| memory-kit-v19-migration | Переход памяти remlab на кит v1.9 (механизмы точности из sup2) + уборка банка | in_progress | 2026-09-28 | 2026-09-28 |
| demo-en-gbp | Демо на английском — переключатель RU/EN, тестовые товары и цены в фунтах | in_progress | 2026-09-28 | 2026-09-29 |
| health-map-apex-redirect | Апекс health-map.online — 302-редирект на 2mnenie.online (домен перестаёт быть мёртвым) | draft | 2026-09-05 | 2026-09-05 |
| mesh-pool-hardening | Работа над ошибками пула мешей — приёмник, стопоры, транспорт, OOM, цена | partial | 2026-09-04 | 2026-09-28 |
| topview-from-mesh | Вид сверху из мешей для планировщика (тест /test/topview-test/) | partial | 2026-08-31 | 2026-09-28 |
| mesh-queue-orientation | Конвейер «отбор → меши → ориентация → сеты»: автоочередь, правило мешей в сетах, каскад фронта, страница人-проверки | partial | 2026-08-28 | 2026-09-28 |
| mesh-bulk-salad-hunyuan | PBR-меши товаров — свой образ Hunyuan3D 2.1 на SaladCloud, пилот 500 товаров | partial | 2026-08-28 | 2026-09-28 |
| viz-regional-masks | Точность мест мебели — дешёвый трек на gpt-image-2, затем спайк масок на fal (2 разбора Codex) | draft | 2026-08-27 | 2026-08-28 |
| demo-planner-structure | Структура демо-планировщика — витрина и конструктор, серверное хранение кадров | partial | 2026-08-26 | 2026-09-05 |
| MASTER-interactive-planner | МЕТАПЛАН — интерактивный планировщик комнаты (предпосчёт вариантов → ручные правки → примерка товара → рендер) | draft | 2026-08-26 | 2026-09-05 |
| exam-hardening-2208 | Фиксы по ночному экзамену 22.08 — heal-ворота, шедулер, перф-профиль, ковёр Г-дивана | partial | 2026-08-22 | 2026-09-05 |
| q12-situational-canon | Q12 — ситуационный канон (функция × якорь × форма) и честное включение приоров практики | partial | 2026-08-19 | 2026-09-05 |
| MASTER-zones-v7 | МЕТАПЛАН — свод №13 (слепая оценка раунд 1 + каталог nook): ключ по глазу владельца, кресла к ТВ, фронтальная зона, банк→солвер, nook/консоль из фида | partial | 2026-08-16 | 2026-09-05 |
| MASTER-cost-first | МАСТЕР-ПЛАН v0.4 «Смета-first» — расчёт ремонта/материалов как ядро продукта | in_progress | 2026-07-11 | 2026-09-28 |
<!-- GENERATED:plans-registry END -->

> Шаблон нового плана — `_template.md`. Реестр регенерирует аудит — руками не правим.
> Audit также ловит зомби: `in_progress` без движения (PLAN-STUCK) и `completed`,
> забытый в этой папке (PLAN-MISPLACED).
