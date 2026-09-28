---
tier: 1
topic: estimate
scope: Смета — калькуляторы, /go/ реф
tier2: "../domain/pricing-works-ru.md"
updated: 2026-09-28
importance: high
source: manual
status: working
source_of_truth: canonical
last_verified: 2026-09-05
review_after: 2026-12-05
---

# Смета-лист — Tier 1 (ядро «Смета-first», ADR-0016)

## Два входа (А в проде с 11.07; порядок — ADR-0187)
- **А — калькуляторы** (`/calc/[kind]`): обои/плитка/краска/ламинат. Сопутка — галочки на `/e`
  (`CompanionChecklist`), НЕ позиции (ADR-0040). **Без параметров материала количество НЕ
  считаем** (`qtyUnknown`, в смету — площадь) — ADR-0034.
- **Б — стоимость ремонта** (`/calc/remont`, до запуска —
  заглушка `app/calc/remont/page.tsx`): площадь+глубина+регион → вилка (`lib/pricing/works.ts`).

## Ядро
- **Чек-лист** `/e/[id]`: постоянная ссылка, свои ссылки руками; баннер «✓ Сохранено», одна
  «сохранялка» (ADR-0036); имя — «Расчёт …» (`lib/estimate/label.ts`), у ремонта «Ремонт N м² · …»
  (`app/estimate-actions.ts`); «смета» — SEO (ADR-0039) и подводки главной и `/calc`.
- **`/lab`**: вкладки Материалы/Ремонт/Дизайны + «Мой стиль», тизеры WIP (ADR-0038);
  удаление смет (ADR-0030).
- **Реф late-binding** `/go/[eid]/[iid]`: лог `link_clicks` + 302 по `link_routes`
  (пусто → прямая); мультисеть.
- **Данные:** `contracts/estimate.ts`; `estimates`/`link_clicks`/`link_routes`;
  `modules/estimate/`. Метрика: цели 10–13. Реклама — [[marketing-acquisition]].

## Калькулятор v2 (ADR-0018–0028)
Мультикомната + параметры + формулы (golden) → смета; состояние клиентское (`lib/calc/*`,
localStorage). UX: в комнате размеры → ссылка → лид (ADR-0037); проёмы у стены
фактом ввода (плитка/краска ADR-0035, обои — в запас); плитка — размер в СМ, цена за м²/шт/упак;
ламинат — за м² (ADR-0030); Роадмап `calc-materials-roadmap.md`.

## Чтение ссылок (ADR-0031/0032)
Только сервер: direct → прокси `PARSE_PROXY_URLS`; `parse-product.ts`: regex+OG → JSON-LD →
ИИ дочитывает; неудача → ручной ввод. ⚠️ Ozon/WB — нужен анблокер; Леруа/Петрович читаются.

## Дальше (после М5)
М4 реклама; pricing Фаза 2 (GeoIP); ИИ-обогащение (М1 v1.1); реф-маршруты (М0).

**Tier 2:** `../domain/pricing-works-ru.md`; код — [[architecture]].
