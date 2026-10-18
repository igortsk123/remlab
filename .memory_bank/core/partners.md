---
tier: 1
topic: partners
scope: Застройщик, ЖК, квартира, цена и сертификат — данные; реестр и карточка квартиры
tier2: "../completed_plans/b2b-06-apartment-as-data.md"
updated: 2026-10-18
importance: high
source: manual
status: working
source_of_truth: canonical
last_verified: 2026-10-13
review_after: 2026-12-13
---

# Застройщики и квартиры — Tier 1 (план b2b-06, ADR-0258)

**Что это:** карточка застройщика — файл `data/partners/<id>.json`, строгая проверка `contracts/partner.ts`.
Внутри: рынок (ru/uk), язык, валюта, доля сертификата, часовой пояс, домены встраивания (`b2b-07`), ЖК со сроком
сдачи, квартиры (тип, площадь, этаж, цена с `priceAsOf`, источники `demoData`/`flat3d`). Менеджеры — в базе ([[manager-links]]).

**Реестр** `lib/partners/registry.ts`: загрузка и проверка (id квартир уникальны, ЖК существует),
`findApartment`, `apartmentCard` — готовая карточка для шапки (тип, ЖК, срок, этаж, цена,
сертификат). **Сертификат — одна формула здесь:** доля цены, округлённая ВНИЗ (₽ — до 10 000,
£ — до 100); демо-застройщик: 5 % от 9 578 200 ₽ = 470 000 ₽.

**Кто читает:** `GET /api/apartments/<id>` → шапка демо (`index.html:loadFlatCard`); `lib/configurator/source.ts` → 3D и
сохранение подбора; `modules/sends/apartments.ts` → квартиры менеджера.

**Живые данные витрины** `lib/partners/demo-data.ts`: по адресу из реестра, кэш 5 минут; имена, которым верит сервер.

**Новая квартира:** запись в файле застройщика; новый застройщик — файл + импорт в `lib/partners/registry.ts`; тест `tests/unit/partners.test.ts`.

**Опции** (ADR-0262/0297): кухня, пол, стены (`enabled`); куда деньги — `settlement.ts:settlementOf` (РФ: пол/стены вне сертификата, кухня в нём; UK — в цену квартиры).

**Комнаты (18.10, ADR-0307):** `rooms[]` — `contracts/partner.ts:apartmentRoom` (id, kind, ordinal, areaM2, contentState); refine на
уникальность, порядок, `roomId` опций, состав `enTwin`; `apartmentCard` отдаёт `rooms`, `options[].roomId`. Остаток сертификата на демо —
по корзине покупателя (`lib/basket/basket.ts`, один включённый вариант на комнату); лимит — формула выше.

**Сегодня:** `demo` — РФ, `flat215` (6 комнат, готова гостиная); `demo-uk` — UK, `demo-uk-1` и двойник EN-демо `demo-uk-215` (ADR-0298).
Контур комнаты в контракте (`contracts/apartment.ts:room.contour`) движки не читают.
- **Встраивание (ADR-0283):** `/embed/<партнёр>/<квартира>` — рамкой с доменов `frameDomains`; `docs/embed.md`.
