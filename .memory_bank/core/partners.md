---
tier: 1
topic: partners
scope: Застройщик, ЖК, квартира, цена и сертификат — данные; реестр и карточка квартиры
tier2: "../completed_plans/b2b-06-apartment-as-data.md"
updated: 2026-10-30
importance: high
source: manual
status: working
source_of_truth: canonical
last_verified: 2026-10-30
review_after: 2026-12-13
---

# Застройщики и квартиры — Tier 1 (план b2b-06, ADR-0258)

**Что это:** карточка застройщика — файл `data/partners/<id>.json`, строгая проверка `contracts/partner.ts`.
Внутри: рынок (ru/uk), язык, валюта, доля сертификата, часовой пояс, домены встраивания (`b2b-07`), ЖК со сроком
сдачи, квартиры (тип, площадь, этаж, цена с `priceAsOf`, источники `demoData`/`flat3d`). Менеджеры — в базе ([[manager-links]]).

**Реестр** `lib/partners/registry.ts`: загрузка и проверка (id квартир уникальны, ЖК существует),
`findApartment`, `apartmentCard` — готовая карточка для шапки (тип, ЖК, срок, этаж, цена,
сертификат). **Пакет (ADR-0308):** `incentive {mode pooled|split, limits}` — ближайший уровень целиком (`lib/partners/incentive.ts`);
без политики — прежняя доля цены (вниз до 10 000 ₽ / £100). Демо: РФ 600 000 ₽ одной суммой, UK £4 500 + £8 000 раздельно.

**Кто читает:** `GET /api/apartments/<id>` → шапка демо; `lib/configurator/source.ts` → 3D; `modules/sends/apartments.ts` → менеджер.

**Новая квартира:** запись в файле застройщика; новый застройщик — файл + импорт в `lib/partners/registry.ts`; тест `tests/unit/partners.test.ts`.

**Опции** (ADR-0262/0297/0308): куда деньги — `lib/configurator/settlement.ts:settlementOf` (РФ: пол/стены/санузел — доплата застройщику, встроенное — в пакет; UK — все в пакет).

**Комнаты (ADR-0307):** `rooms[]` — `contracts/partner.ts:apartmentRoom`; остаток пакета — по корзине (`lib/basket/basket.ts`, вариант на комнату).

**Сегодня:** `demo` — РФ, `flat215` (7 комнат, готова гостиная); `demo-uk` — UK, `demo-uk-1` и двойник EN-демо `demo-uk-215` (ADR-0298) с временной британской маской товаров `demoMask` (ADR-0328).
Площади — истина реестр (`data/partners/demo.json`: комнаты + `loggiaM2`, сторож суммы в `contracts/partner.ts`); чертёж плана демо — абстракция
(снят с квартиры №180, владелец 22.10: оставить). Контур комнаты (`contracts/apartment.ts:room.contour`) движки не читают.
- **Встраивание (ADR-0283):** `/embed/<партнёр>/<квартира>` — рамкой с доменов `frameDomains`; `docs/embed.md`.
