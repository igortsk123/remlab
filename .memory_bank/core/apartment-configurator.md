---
tier: 1
topic: apartment-configurator
scope: 3D-конфигуратор квартиры — что это, из чего собран, где детали
tier2: "../domain/flat3d-configurator.md"
updated: 2026-11-10
importance: high
source: manual
status: working
source_of_truth: canonical
last_verified: 2026-11-09
review_after: 2026-12-28
---

# 3D-конфигуратор квартиры — Tier 1

**05.11:** основной сценарий — `/demo` со шторкой; `/flat` не в ходу, его мост строит 3D `/demo` — [[flat3d-configurator]].

**Что это:** `/flat` — покупатель новостройки ходит по квартире в 3D и собирает её под себя:
пол, кухня с техникой, плитка санузла, стены, мебель. Видит сумму в валюте застройщика и строку
сертификата, сохраняет подбор ссылкой. Вход — `?coll=`, `?s=`, `?c=` (`?demo=` без ссылок с 22.10). Квартира — из реестра застройщиков
[[partners]] через одну точку `lib/configurator/source.ts` (ADR-0258).

**Работа (ADR-0221/0224):** 3D на весь экран; клик по предмету → контур; выбор — полосой внизу (`components/flat3d/BuildBar.tsx`).

**Режимы:** бродилка · сверху (`viewer.ts:setViewMode`) · фото (`setPhotoPose`, `LivePhoto.tsx`) · план (`PlanView.tsx`); телефон — «Фото».

**Мебель:** сдвиг, поворот 15° (ADR-0227), стулья группой (ADR-0230).
**Из чего собрано** (Tier 2): ядро — `contracts/apartment.ts`, `lib/configurator/resolve.ts`; сцена — `lib/viewer3d/*`;
сохранение — `flat_configs`; вход с витрины — `lib/configurator/fromDemo.ts` (`?demo=<вариант>&flat=<квартира>`).

**Общий движок с демо (ADR-0288):** `lib/viewer3d` собирается и бандлом для `/demo` (`demo-scene.ts`); предмет = опора
+ модель (сдвиг без пересоздания), фото-поза = серверная камера (`viewer.ts:photoRay`).

**С 14–15.10 (ADR-0281, demo-05):** отмена (`lib/configurator/history.ts`), «убрать»; мост с окном — ковёр, ваза
(`resolve.placeTabletop`), ленты (`demo-feeds.ts`), упаковки (`resolve.packPrices`), ТВ — `build-scene.sceneExtras`.
**С 16.10 (demo-06/07, ADR-0297/0298):** пол и стены витрины — опции места из группы застройщика (`source.floorChoiceOf`,
`source.finishChoiceOf(hit,"wall")`, `?opt=`), итоги `totals.bySettlement`/`byBudget` (ADR-0308); UK-двойник — курс × маска (ADR-0328, `demo-mask.ts`) — Tier 2.
**Нет:** маски перекраски, лайтмапов, косых комнат. **Телефон:** стрелки и подписи не пересекаются
(`WalkPad.tsx:walkPadRect`, `Hotspots.tsx:labelBox`) — Tier 2. **Открыто:** `furniture.json`; кухня (`lib/viewer3d/kits/kitchen.ts`) на паузе (08.11).

**Уроки:** `lessons/flat3d-configurator.md` · **Tier 2:** `../domain/flat3d-configurator.md` · [[demo-planner]]
