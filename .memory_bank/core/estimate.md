---
tier: 1
topic: estimate
scope: Смета-лист (ядро v0.4) — калькуляторы (вход А), стоимость ремонта (вход Б), чек-лист, /go/ реф
tier2: "../domain/pricing-works-ru.md"
updated: 2026-07-31
importance: high
source: manual
status: working
source_of_truth: canonical
last_verified: 2026-07-31
review_after: ""
---

# Смета-лист — Tier 1 (ядро v0.4 «Смета-first», ADR-0016)

## Что это
Расчёт материалов/стоимости → смета с реф-ссылками (мастер-план М0–М7; М1 построен).

## Два входа
- **А — калькуляторы** (`/calc/[kind]`): обои/плитка/краска/ламинат; сопутка `companions.ts`.
  **Без параметров материала количество НЕ считаем** (`qtyUnknown` + «? ед → что сделать»;
  в смету идёт площадь) — ADR-0034.
- **Б — стоимость ремонта** (`/calc/remont`): площадь+глубина+регион → вилка (`lib/pricing/works.ts`).

## Ядро
- **Чек-лист** `/e/[id]`: постоянная ссылка, свои ссылки руками, «Мои сметы» (`/estimates`).
- **`/lab`**: сметы сессии + удаление (`repo.delete(id, sessionId)`; ADR-0030).
- **Late-binding реф** `/go/[eid]/[iid]`: лог `link_clicks` + 302 на реф из `link_routes`
  (пусто → прямая); мультисеть.
- **Данные:** `contracts/estimate.ts`; `estimates`/`link_clicks`/`link_routes`; `modules/estimate/`.
  Метрика: цели 10–13. Реклама — [[marketing-acquisition]].

## Калькулятор v2 (К0–К6; ADR-0018–0028)
Мультикомната + параметры + формулы (golden) → смета; состояние клиентское (`contracts/calc.ts`,
`lib/calc/*`, localStorage). UX: проёмы у стены, вычет фактом ввода (плитка/краска, ADR-0035;
обои — в запас); плитка — размер в СМ, цена за м²/шт/упак; ламинат — за м² (ADR-0030).
Хвосты: итог → сопутка → «найдём дешевле» → виз. Детали — ADR-0019/0028/0030;
роадмап `calc-materials-roadmap.md`.

## Чтение ссылок (ADR-0031/0032)
Только сервер: direct → прокси `PARSE_PROXY_URLS` для всех магазинов; парс
`parse-product.ts`: regex+OG → JSON-LD → ИИ дочитывает пустые поля; неудача → ручной ввод.
⚠️ Ozon/WB блокируют IP пула — нужен анблокер (Bright Data/Zyte); Леруа/Петрович читаются.

## Следующее
pricing Фаза 2 (GeoIP); ИИ-обогащение (М1 v1.1); реф-маршруты (М0); М5 виз.

**Tier 2:** `../domain/pricing-works-ru.md`; код — [[architecture]].
