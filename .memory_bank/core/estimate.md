---
tier: 1
topic: estimate
scope: Смета-лист (ядро v0.4) — калькуляторы (вход А), стоимость ремонта (вход Б), чек-лист, /go/ реф
tier2: "../domain/pricing-works-ru.md"
updated: 2026-07-11
importance: high
source: manual
status: working
source_of_truth: canonical
last_verified: 2026-07-11
review_after: ""
---

# Смета-лист — Tier 1 (ядро v0.4 «Смета-first», ADR-0016)

## Что это
Ядро продукта: расчёт материалов/стоимости → сохранённая смета-список с реф-ссылками.
Мастер-план — `../plans/MASTER-cost-first.md` (в completed после М1); построено М1
(`../completed_plans/m1-estimate-core.md`).

## Два входа
- **А — калькуляторы** (`/calc`, `/calc/[kind]`): обои/плитка/краска/ламинат. Формулы —
  `lib/estimate/calc.ts` (golden-тест). Ищут ЧИСЛО → ответ сразу, сопутка «предвосхищение»
  (`lib/estimate/companions.ts`), визуализация — ненавязчиво.
- **Б — стоимость ремонта** (`/calc/remont`): площадь + глубина + регион → вилка 3 бюджетов
  (эконом/средний/получше), работы/материалы отдельно. Нормативы — `lib/pricing/works.ts`
  (медианы Москвы + региональные коэф. 0.55–0.95; данные — Tier 2 `pricing-works-ru`).

## Ядро
- **Смета-чек-лист** `/e/[id]`: постоянная ссылка (шаринг by design), добавление своих ссылок
  (название/цена руками — парс OG позже), сохранение в «Мои сметы» (`/estimates`).
- **Late-binding реф** (`/go/[eid]/[iid]`): ВСЕ внешние переходы через наш редирект → лог клика
  (`link_clicks`) + 302 на реф-версию из `link_routes` (пусто → прямая). Подмена на партнёрскую =
  правка маршрута, чек-листы не трогаем. Мультисеть (Гдеслон/прямые/Admitad/ePN/AliExpress).
- **Данные:** `contracts/estimate.ts`; таблицы `estimates`/`link_clicks`/`link_routes`;
  repository (memory/pg) `modules/estimate/`. Метрика: цели 10–13 (`campaign_state.md`).

## Реклама ведёт сюда
Директ Этап 1 (калькуляторы → /calc/[kind]), Этап 2 (ремонт → /calc/remont) — `marketing-acquisition.md`.

## Следующее
pricing Фаза 2 (GeoIP, сверка регионов); ИИ-обогащение (М1 v1.1); реф-маршруты по логу (М0); М5 виз.

**Tier 2:** `../domain/pricing-works-ru.md`. Код — `architecture.md`.
