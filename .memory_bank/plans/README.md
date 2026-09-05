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
- **Память:** `memory-bank-audit-2026-09`.

## Реестр активных планов

<!-- GENERATED:plans-registry START -->
<!-- Таблицу регенерирует tools/memory-audit.mjs из frontmatter. Не редактируй вручную. -->

| slug | Название | status | created | updated |
|------|----------|--------|---------|---------|
| mesh-owner-audit | Ручная приёмка мешей владельцем — страница по 20, кнопка «переделать», честная очередь | in_progress | 2026-09-05 | 2026-09-05 |
| memory-bank-audit-2026-09 | Аудит Memory Bank 2026-09 — регулярность, дефекты, реструктуризация (ADR-тома, уроки, планы, intake, Tier 0) | draft | 2026-09-05 | 2026-09-05 |
| health-map-apex-redirect | Апекс health-map.online — 302-редирект на 2mnenie.online (домен перестаёт быть мёртвым) | draft | 2026-09-05 | 2026-09-05 |
| mesh-pool-hardening | Работа над ошибками пула мешей — приёмник, стопоры, транспорт, OOM, цена | in_progress | 2026-09-04 | 2026-09-04 |
| stock-check-weekly-unified | Одно правило проверки наличия — раз в неделю для всех; непроверяемым верим Гдеслону | in_progress | 2026-09-01 | 2026-09-01 |
| photo-improve-from-mesh | Кнопка «Улучшить фото» — ремонт от ИИ поверх НАШЕГО кадра с мешами | in_progress | 2026-09-01 | 2026-09-01 |
| demo-collection-flow | Демо — два уровня: быстрый подбор на странице и конструктор на весь экран | in_progress | 2026-09-01 | 2026-09-02 |
| topview-from-mesh | Вид сверху из мешей для планировщика (тест /test/topview-test/) | in_progress | 2026-08-31 | 2026-09-02 |
| stock-truth-page-verdict | Наличие товара — один вычислитель, свидетельство сильнее фида | in_progress | 2026-08-31 | 2026-08-31 |
| orient-v2 | Ориентация мешей v2 — единый контур upright+front, DINO shadow, gold-бенч | in_progress | 2026-08-31 | 2026-08-31 |
| mesh-dynamic-node-pool | Динамический пул нод Salad в прогоне мешей + честный учёт заданий | in_progress | 2026-08-31 | 2026-08-31 |
| viz-mesh-orientation | Система ориентаций и приёмки 3D-мешей — масштабирование «правильных поворотов» на каталог | in_progress | 2026-08-28 | 2026-08-28 |
| mesh-queue-orientation | Конвейер «отбор → меши → ориентация → сеты»: автоочередь, правило мешей в сетах, каскад фронта, страница人-проверки | in_progress | 2026-08-28 | 2026-08-28 |
| mesh-bulk-salad-hunyuan | PBR-меши товаров — свой образ Hunyuan3D 2.1 на SaladCloud, пилот 500 товаров | in_progress | 2026-08-28 | 2026-08-28 |
| viz-regional-masks | Точность мест мебели — дешёвый трек на gpt-image-2, затем спайк масок на fal (2 разбора Codex) | draft | 2026-08-27 | 2026-08-28 |
| demo-planner-structure | Структура демо-планировщика — витрина и конструктор, серверное хранение кадров | partial | 2026-08-26 | 2026-09-05 |
| MASTER-interactive-planner | МЕТАПЛАН — интерактивный планировщик комнаты (предпосчёт вариантов → ручные правки → примерка товара → рендер) | draft | 2026-08-26 | 2026-09-05 |
| exam-hardening-2208 | Фиксы по ночному экзамену 22.08 — heal-ворота, шедулер, перф-профиль, ковёр Г-дивана | partial | 2026-08-22 | 2026-09-05 |
| q12-situational-canon | Q12 — ситуационный канон (функция × якорь × форма) и честное включение приоров практики | partial | 2026-08-19 | 2026-09-05 |
| MASTER-zones-v7 | МЕТАПЛАН — свод №13 (слепая оценка раунд 1 + каталог nook): ключ по глазу владельца, кресла к ТВ, фронтальная зона, банк→солвер, nook/консоль из фида | partial | 2026-08-16 | 2026-09-05 |
| MASTER-cost-first | МАСТЕР-ПЛАН v0.4 «Смета-first» — расчёт ремонта/материалов как ядро продукта | in_progress | 2026-07-11 | 2026-09-05 |
<!-- GENERATED:plans-registry END -->

> Шаблон нового плана — `_template.md`. Реестр регенерирует аудит — руками не правим.
> Audit также ловит зомби: `in_progress` без движения (PLAN-STUCK) и `completed`,
> забытый в этой папке (PLAN-MISPLACED).
