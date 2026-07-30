---
tier: 1
topic: estimate
scope: Смета-лист (ядро v0.4) — калькуляторы (вход А), стоимость ремонта (вход Б), чек-лист, /go/ реф
tier2: "../domain/pricing-works-ru.md"
updated: 2026-07-30
importance: high
source: manual
status: working
source_of_truth: canonical
last_verified: 2026-07-30
review_after: ""
---

# Смета-лист — Tier 1 (ядро v0.4 «Смета-first», ADR-0016)

## Что это
Расчёт материалов/стоимости → сохранённая смета с реф-ссылками. Мастер —
`../plans/MASTER-cost-first.md`; построено М1.

## Два входа
- **А — калькуляторы** (`/calc`, `/calc/[kind]`): обои/плитка/краска/ламинат; сопутка
  `lib/estimate/companions.ts`.
- **Б — стоимость ремонта** (`/calc/remont`): площадь + глубина + регион → вилка 3 бюджетов
  (`lib/pricing/works.ts`).

## Ядро
- **Чек-лист** `/e/[id]`: постоянная ссылка (шаринг), свои ссылки (название/цена руками), «Мои сметы» (`/estimates`).
- **Лаборатория `/lab`**: список смет сессии + удаление (`repo.delete(id, sessionId)`, confirm; ADR-0030).
- **Late-binding реф** `/go/[eid]/[iid]`: редирект → лог `link_clicks` + 302 на реф из
  `link_routes` (пусто → прямая); мультисеть (Гдеслон/прямые/Admitad/ePN).
- **Данные:** `contracts/estimate.ts`; таблицы `estimates`/`link_clicks`/`link_routes`;
  `modules/estimate/`. Метрика: цели 10–13. Реклама: Директ Этап 1–2 — `marketing-acquisition.md`.

## Калькулятор v2 (К0–К6; ADR-0018–0028)
Мультикомната + параметры + формулы (golden) → смета; состояние клиентское (`contracts/calc.ts`,
`lib/calc/*`, `components/calc/*`, localStorage). ОСНОВНОЙ на `/calc/[kind]`. UX: проёмы скрыты
из UI; плитка — инлайн-результаты стен/пол, «? шт» без размера, размер в СМ (хранение мм), цена за
м²/шт/упак (парсер определяет единицу); ламинат — цена за м² (конвертация упаковка→м², стоимость
через целые упаковки; ADR-0030); «?»-подсказки. Копирайт по kind (`CALC_META`); хвосты: итог →
сопутка → «найдём дешевле» → виз. Детали — ADR-0019/0027/0028/0030; роадмап `calc-materials-roadmap.md`.

## Следующее
pricing Фаза 2 (GeoIP); ИИ-обогащение (М1 v1.1); реф-маршруты по логу (М0); М5 виз.

**Tier 2:** `../domain/pricing-works-ru.md`. Код — `architecture.md`.
