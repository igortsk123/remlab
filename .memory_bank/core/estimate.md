---
tier: 1
topic: estimate
scope: Смета-лист (ядро v0.4) — калькуляторы (вход А), стоимость ремонта (вход Б), чек-лист, /go/ реф
tier2: "../domain/pricing-works-ru.md"
updated: 2026-07-12
importance: high
source: manual
status: working
source_of_truth: canonical
last_verified: 2026-07-12
review_after: ""
---

# Смета-лист — Tier 1 (ядро v0.4 «Смета-first», ADR-0016)

## Что это
Ядро продукта: расчёт материалов/стоимости → сохранённая смета-список с реф-ссылками. Мастер —
`../plans/MASTER-cost-first.md`; построено М1 (`../completed_plans/m1-estimate-core.md`).

## Два входа
- **А — калькуляторы** (`/calc`, `/calc/[kind]`): обои/плитка/краска/ламинат. Формулы
  `lib/estimate/calc.ts` (golden-тест). Число сразу → сопутка (`lib/estimate/companions.ts`).
- **Б — стоимость ремонта** (`/calc/remont`): площадь + глубина + регион → вилка 3 бюджетов,
  работы/материалы отдельно. Нормативы `lib/pricing/works.ts` (медианы Москвы + коэф. 0.55–0.95).

## Ядро
- **Чек-лист** `/e/[id]`: постоянная ссылка (шаринг), добавление своих ссылок (название/цена руками),
  сохранение в «Мои сметы» (`/estimates`).
- **Late-binding реф** `/go/[eid]/[iid]`: ВСЕ внешние переходы через редирект → лог (`link_clicks`) +
  302 на реф-версию из `link_routes` (пусто → прямая). Мультисеть (Гдеслон/прямые/Admitad/ePN).
- **Данные:** `contracts/estimate.ts`; таблицы `estimates`/`link_clicks`/`link_routes`; repository
  (memory/pg) `modules/estimate/`. Метрика: цели 10–13 (`campaign_state.md`).

## Реклама ведёт сюда
Директ Этап 1 (калькуляторы → /calc/[kind]), Этап 2 (ремонт → /calc/remont) — `marketing-acquisition.md`.

## Калькулятор v2 (детальный, серия К0–К6; ADR-0018)
Мультикомната + проёмы/зоны + полные параметры + автозаполнение по ссылке + платные хвосты.
Состояние клиентское (`contracts/calc.ts`+`lib/calc/*`+`components/calc/*`, localStorage), флаг
`CALC_V2` до К3 (там → материализация в смету). Роадмап `../plans/calc-materials-roadmap.md`.

## Следующее
pricing Фаза 2 (GeoIP); ИИ-обогащение (М1 v1.1); реф-маршруты по логу (М0); М5 виз.

**Tier 2:** `../domain/pricing-works-ru.md`. Код — `architecture.md`.
