---
workstream: product
slug: m1-estimate-core
title: М1 — Ядро «Смета-лист» + /go/ редирект + фронт под сценарии (v0.4)
status: completed
created: 2026-07-11
updated: 2026-07-11
completed: 2026-07-11
---

## Completion summary (2026-07-11)
Сквозной срез v0.4 построен и в проде (`remont-lab.online`, версия 20260711-15xx). Вход А
(калькуляторы обои/плитка/краска/ламинат + golden-тест), вход Б (вилка 3 бюджетов на
плейсхолдер-нормативах), смета-чек-лист `/e/[id]` по постоянной ссылке (добавить свою ссылку,
шаринг, сохранить), `/go/` редирект-слой (late-binding реф + лог кликов), лендинг v0.4, «Мои
сметы». Схема estimates/link_clicks/link_routes (+ deploy.sh накатывает 004). Метрика: 4 цели
воронки. Гейт зелёный (typecheck/lint/unit/e2e 7/7). Прод-verify: смета читается из PG, /go/
302 на внешний + клик залогирован; пойман+исправлен fallback-баг /go/ (внутренний req.url за
прокси). Следующее: pricing-db-ru (реальные нормативы работ, в очереди), ИИ-обогащение сметы
(М1 v1.1), реф-маршруты по логу кликов (М0 late-binding).

## Ход исполнения (2026-07-11)
Построено: контракты `estimate`; формулы `lib/estimate/calc` (обои/плитка/краска/ламинат) +
golden-тест (7); `links` (домен, resolve /go/) + тест; `companions` (сопутка); плейсхолдер
`lib/pricing/works`; `modules/estimate/repository` (memory/pg); схема (estimates/link_clicks/
link_routes) + migrate + init 004; `/go/[eid]/[iid]` редирект-слой (лог+302); actions
(createFromCalc/createFromRemont/addLink/removeItem/markSaved). Экраны: `/calc` хаб, `/calc/[kind]`,
`/calc/remont` (вилка), `/e/[id]` чек-лист (добавить свою ссылку, /go/, шаринг, сохранить),
`/estimates`, лендинг v0.4 (2 входа). Метрика: цели 10_calc_started, 11_estimate_opened,
12_estimate_saved, 13_ref_click (JS через client-компоненты GoLink/SaveButton/CalcForm).
typecheck/lint/unit(golden) зелёные. Остаётся: e2e-прогон, деплой, verify прода.

## Цель
Построить рабочий сквозной срез v0.4: калькуляторы материалов (вход А) + «сколько стоит
ремонт» (вход Б) → смета-чек-лист по постоянной ссылке с сохранением → все внешние переходы
через `/go/<id>` (late-binding реф). Фронт переделан под сценарии мастера. Владелец: «строй
план и делай». Мастер — `MASTER-cost-first.md` (М1–М3).

## Скоуп (MVP, сквозной)
- Схема: `estimates` (jsonb-агрегат как projects) + `link_clicks` (лог /go/) + `link_routes`
  (маршруты домен→реф-программа; пока пустая → прямая ссылка). Миграция идемпотентна.
- Contracts: `contracts/estimate.ts` (Estimate, EstimateItem: source user_link|our_pick|calc).
- Формулы `lib/estimate/calc.ts` (обои/плитка/краска/ламинат) + golden-тест (механика sub-e6).
- `lib/estimate/links.ts` — домен из URL, resolve /go/ (маршрут или прямая).
- `modules/estimate/repository.ts` (memory + pg, как projects).
- Экраны: `/calc` хаб (вход А) · `/calc/[kind]` калькулятор → смета · `/calc/remont` вход Б
  (площадь+глубина → вилка 3 бюджетов → смета) · `/e/[id]` смета-чек-лист (список, добавить
  свою ссылку с ценой/названием руками — деградация из барьеров, сохранить, шаринг) ·
  `/go/[id]` route handler (лог+302). Лендинг: два входа впереди, AI-дизайн — вторичный.
- Метрика-цели: calc_started, estimate_created, estimate_saved, ref_click.

## НЕ входит (по плану — позже)
Парс OG-меты магазинов (барьер: деградация «руками»); ИИ-обогащение/«дешевле» (М1 v1.1);
реальные реф-URL (М0 late-binding, маршруты пусты); Cost Engine точный (вилка — по нормативам);
«сфоткай — посчитаем» (М2 v1.5); мебель/визуализация (М5, существующий флоу не трогаем).

## Файлы
- [ ] `contracts/estimate.ts`, `lib/estimate/{calc,links}.ts`, `modules/estimate/repository.ts`
- [ ] `db/schema.ts` (+estimates/link_clicks/link_routes), `tools/migrate.mjs`, `db/init/004-estimates.sql`
- [ ] `app/estimate-actions.ts` (server actions), `app/go/[id]/route.ts`
- [ ] `app/calc/page.tsx`, `app/calc/[kind]/page.tsx`, `app/calc/remont/page.tsx`, `app/e/[id]/page.tsx`
- [ ] `components/Calc*.tsx`, `app/page.tsx` (лендинг), `app/globals.css` (мелочи)
- [ ] `tests/unit/estimate-calc.test.ts` (golden), `e2e/estimate.spec.ts`

## Критерии приёмки
- [ ] Калькулятор обоев: 4×3 м, h 2.7 → корректные рулоны; golden зелёный.
- [ ] Смета создаётся, сохраняется в сессию, открывается по постоянной ссылке, шаринг работает.
- [ ] Внешняя ссылка идёт через `/go/<id>` → клик логируется → 302 (прямая, маршрутов нет).
- [ ] Лендинг ведёт в оба входа; цели Метрики шлются.
- [ ] typecheck/lint/test/e2e/build зелёные; деплой; smoke прод. `/memory-check` чисто.
