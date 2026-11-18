---
tier: 1
topic: bedroom
scope: Спальня — каталог, банк наборов, показ на /demo, группы, детская
tier2: "../domain/pipeline-order-details.md"
updated: 2026-11-18
importance: med
source: manual
status: working
source_of_truth: canonical
review_after: 2026-12-05
last_verified: 2026-11-18
---

# Спальня — Tier 1 сводка

## Каталог (v1, ADR-0279)
- `tools/scout/room_catalog.py`, роли `tools/scout/rules/bedroom-roles.json`, стиль `style-scores-bedroom.json`.
- **Кровать:** габарит ≠ спальное место (`tools/scout/bed_dims.py`, `room_catalog.line_dims`).

## /demo и банк
- **Набор:** `tools/scout/compose_bedroom.py` (`tools/scout/rules/bedroom-composition.json`) → `sets-bedroom.next.json`; ячейка
  `room_id|purpose|band|style|tier` (`tools/scout/room_identity.py:cell`); стиль без ядра ночью не собирается (`core_skip`).
- **Банк:** prepare → pending → promote (≤ 25 %) → `sets-bedroom.json`; флаги `tools/scout/rules/bank-candidate.json:rooms.bedroom`.
- **Витрина:** `tools/scout/demo_bedroom.py` поверх `tools/scout/demo_room.py`; пустую роль добирает `demo_room.py:role_spares`.
- **Модель:** `tools/scout/room_bindings.py:usable`. **3D (ADR-0417/0422/0425):** лампа от 33 см, иначе соседний стиль
  (`tools/scout/dependent_decor.py`); лампа с моделью раньше лампы без модели (ADR-0431, `tools/scout/compose_bedroom.py:decor_pick`); плед — ярлык с фото и ценой (`data/flat3d/textile.json:label`), шторы — `tools/scout/textile_abstract.py`; сторож `tools/scout/priced_vs_3d.py`.

## Расстановка
- Угловая кровать — в угол; ковёр по выступу 45–70 см (`tools/scout/compose_bedroom.py:rug_norm`).
- **Группы (ADR-0392, [[room-templates]]):** паспорт `services/planner-solver/rules/room-templates/bedroom.json`; движок —
  `services/planner-solver/planner/bedroom_checks.py:engine` (`groups`, откат `BEDROOM_ENGINE=items`); P1–P10 (ADR-0384): пара в тесной —
  140, в малой квадратной — без шкафа, без кровати — «кабинет»; гостевой — тумба через compact (ADR-0404).
  Бок без тумбы — к стене или проход 60 (compact 50) (`services/planner-solver/planner/bedroom.py:_free_side_ok`).
- **Каталог шаблонов (тень, T-120):** 24 шаблона `services/planner-solver/rules/room-templates/bedroom-catalog.json` (движок пока —
  `bedroom.json`); комната 6–7,5 м² — по числу комнат (ADR-0408); условие движка — лампа на каждую тумбу.
- **Туры:** у окна — низкие рамы (`tools/scout/trial_bedroom.py:window_low_beds`); стиль — ≤ 16 вызовов решателя (ADR-0414).

## Стили и назначения
- 6 стилей (неоклассика — `core_skip`); назначения couple/single/guest/office/child:*.

**Tier 2:** `../domain/pipeline-order-details.md` § «Банки других комнат», «Спальня 10–12.11» · [[b2b-10-rooms-beyond-living]] · ADR-0330.
