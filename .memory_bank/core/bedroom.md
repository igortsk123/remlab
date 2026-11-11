---
tier: 1
topic: bedroom
scope: Спальня — каталог, банк наборов, показ на /demo (с 06.11), детская; что дальше
tier2: "../domain/pipeline-order-details.md"
updated: 2026-11-11
importance: med
source: manual
status: working
source_of_truth: canonical
review_after: 2026-12-05
last_verified: 2026-11-06
---

# Спальня — Tier 1 сводка

## Каталог (v1, ADR-0279)
- Отдельно от гостиной: `room_catalog` (`tools/scout/013-room-catalog.sql`, `017` — `photo_alive`), загрузчик
  `tools/scout/room_catalog.py`, роли — `tools/scout/rules/bedroom-roles.json`. `products` и подбор гостиной спальню не видят.
- **Кровать:** габарит ≠ спальное место (`tools/scout/bed_dims.py`); без габарита/спального места, «матрас», общий размер линейки —
  в расстановку нельзя (`room_catalog.line_dims`).
- Оценка стиля — файл `style-scores-bedroom.json`, не `product_style_scores`.

## Показ на /demo (с 06.11, T-20261106-77)
- Спальни 1 и 2 (чертёж №180) — варианты по стилям, 3D и фото.
- **Набор:** сборщик `tools/scout/compose_bedroom.py` (правила `tools/scout/rules/bedroom-composition.json`) → кандидат
  `sets-bedroom.next.json`; ячейка `room_id|purpose|band|style|tier` (`tools/scout/room_identity.py:cell`); стиль без товаров ядра
  ночью не собирается (`compose_bedroom.py:core_skip`).
- **Банк:** ночью prepare → pending → promote → писатель `sets-bedroom.json` (флаги
  `tools/scout/rules/bank-candidate.json:rooms.bedroom`, откат — флаги false + `bank_refresh.py --room bedroom rollback last`).
- **Витрина** (`tools/scout/demo_bedroom.py` поверх общего `tools/scout/demo_room.py`): ведущие роли — поле `lead` профиля
  `tools/scout/rules/profiles/bedroom.json`; пустую роль добирает запас из других записей банка (`demo_room.py:role_spares`);
  лампы декора без моделей — `list_only` (в списке, не в 3D).
- **Модель предмета** — одно правило с банком: `tools/scout/room_bindings.py:usable` (режим orient: ready или blocked только по
  развороту), сцена грузит модель привязки (`room_bindings.py:scene_msid`).
  Изголовье — сторож `tools/scout/bed_headboard.py`.

## Стили и назначения
- Шесть стилей в правилах; владелец 07.11: неоклассика — только в гостиной, нет стиля — молча похожий вариант
  (план `style-fallback-01`, в коде спальни ещё нет).
- Спальня 2 — назначения couple/single/guest/office/child:* (`bedroom-composition.json:bedroom-2`); детская 7–12 решается солвером
  (план `kids-room-01`), наборов в банке пока нет.

**Tier 2:** `../domain/pipeline-order-details.md` § «Банки других комнат» · [[b2b-10-rooms-beyond-living]] · ADR-0330.
