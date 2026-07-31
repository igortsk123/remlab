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
Расчёт материалов/стоимости → смета с реф-ссылками. Мастер — `../plans/MASTER-cost-first.md`; построено М1.

## Два входа
- **А — калькуляторы** (`/calc/[kind]`): обои/плитка/краска/ламинат; сопутка `companions.ts`;
  стены добавляются из карточки размеров.
- **Б — стоимость ремонта** (`/calc/remont`): площадь+глубина+регион → вилка (`lib/pricing/works.ts`).

## Ядро
- **Чек-лист** `/e/[id]`: постоянная ссылка, свои ссылки руками, «Мои сметы» (`/estimates`).
- **Лаборатория `/lab`**: сметы сессии + удаление (`repo.delete(id, sessionId)`; ADR-0030).
- **Late-binding реф** `/go/[eid]/[iid]`: лог `link_clicks` + 302 на реф из `link_routes`
  (пусто → прямая); мультисеть.
- **Данные:** `contracts/estimate.ts`; `estimates`/`link_clicks`/`link_routes`; `modules/estimate/`.
  Метрика: цели 10–13. Реклама — `marketing-acquisition.md`.

## Калькулятор v2 (К0–К6; ADR-0018–0028)
Мультикомната + параметры + формулы (golden) → смета; состояние клиентское (`contracts/calc.ts`,
`lib/calc/*`, localStorage). ОСНОВНОЙ на `/calc/[kind]`. UX: проёмы скрыты; плитка — размер в СМ
(хранение мм), цена за м²/шт/упак; ламинат — цена за м² (конвертация упаковка→м²; ADR-0030).
Хвосты: итог → сопутка → «найдём дешевле» → виз. Детали — ADR-0019/0027/0028/0030; роадмап
`calc-materials-roadmap.md`.

## Чтение ссылок (ADR-0031/0032)
Только сервер: direct → прокси `PARSE_PROXY_URLS` для всех магазинов (cap 2 МБ); парс
`parse-product.ts`: regex+OG → JSON-LD → ИИ дочитывает пустые поля; неудача → ручной ввод.
⚠️ Ozon/WB блокируют IP пула — нужен анблокер (Bright Data/Zyte); Леруа/Петрович читаются.

## Следующее
pricing Фаза 2 (GeoIP); ИИ-обогащение (М1 v1.1); реф-маршруты (М0); М5 виз.

**Tier 2:** `../domain/pricing-works-ru.md`. Код — `architecture.md`.
