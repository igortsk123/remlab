---
tier: 1
topic: apartment-configurator
scope: 3D-конфигуратор квартиры — что это, из чего собран, где детали
tier2: "../domain/flat3d-configurator.md"
updated: 2026-10-15
importance: high
source: manual
status: working
source_of_truth: canonical
last_verified: 2026-09-29
review_after: 2026-12-28
---

# 3D-конфигуратор квартиры — Tier 1

**Что это:** `/flat` — покупатель новостройки ходит по квартире в 3D и собирает её под себя:
пол, кухня с техникой, плитка санузла, стены, мебель. Видит сумму в валюте застройщика и строку
сертификата, сохраняет подбор ссылкой. Вход — с `/demo/` (`?demo=`), из коллекции (`?coll=`), по ссылке менеджера (`?s=`). Квартира — из реестра застройщиков
[[partners]] через одну точку `lib/configurator/source.ts` (ADR-0258).

**Работа (ADR-0221/0224):** 3D на весь экран; клик по предмету → контур; выбор — полосой внизу (`components/flat3d/BuildBar.tsx`).

**Четыре режима над одним выбором:** бродилка · сверху · фото · план; первые два — одна сцена
(`viewer.ts:setViewMode`), телефон открывается в «Фото» (`/api/render`).

**Мебель двигают и поворачивают** (ADR-0227): поворот шагом 15°, координаты — в подборе (ADR-0258), переживают
перезагрузку и ссылку. Стулья меняются группой (ADR-0230); в комнату камера ведёт по выбору человека (ADR-0229).

**Из чего собрано** (детали — Tier 2): ядро — `contracts/apartment.ts`,
`lib/configurator/resolve.ts`; сцена — `lib/viewer3d/*`; сохранение — `flat_configs`;
вход с витрины — `lib/configurator/fromDemo.ts` (`/flat?demo=<вариант>&flat=<квартира>`; места «роль#N»).

**Общий движок с демо (ADR-0288):** `lib/viewer3d` собирается и бандлом для `/demo` (`demo-scene.ts`); предмет = опора
+ модель (сдвиг без пересоздания), фото-поза = серверная камера (`viewer.ts:photoRay`).

**Решения:** ADR-0210…0230, 0258, 0281, 0288, 0292 (проёмы из `opening-ir.ts`), 0293 (вид из окна).

**С 14.10 (ADR-0281):** `ObjectTools`, `InfoPanel`, «убрать», отмена (`lib/configurator/history.ts`), `Hotspots`.
**С 15.10 (demo-05):** витрина → `/flat` одним мостом с окном — ковёр, ваза (`tabletop`, место — `resolve.placeTabletop`),
ленты замен (`demo-feeds.ts`), упаковки (`resolve.packPrices`); ТВ над тумбой — производный (`build-scene.sceneExtras`).
**Нет:** перекраски по маске, лайтмапов, непрямоугольных комнат.

**Уроки:** `lessons/flat3d-configurator.md`.

**Tier 2:** `../domain/flat3d-configurator.md` · [[demo-planner]]
