---
tier: 1
topic: bedroom
scope: Спальня — каталог, банк наборов, показ на /demo, группы, детская
tier2: "../domain/pipeline-order-details.md"
updated: 2026-11-12
importance: med
source: manual
status: working
source_of_truth: canonical
review_after: 2026-12-05
last_verified: 2026-11-12
---

# Спальня — Tier 1 сводка

## Каталог (v1, ADR-0279)
- Отдельно от гостиной: `room_catalog` (`tools/scout/013-room-catalog.sql`, `tools/scout/room_catalog.py`), роли —
  `tools/scout/rules/bedroom-roles.json`; стиль — `style-scores-bedroom.json`.
- **Кровать:** габарит ≠ спальное место (`tools/scout/bed_dims.py`); без них или общий размер линейки — в расстановку нельзя
  (`room_catalog.line_dims`). Дыры каталога (данные, не код): ковры 180–190×270–300 и 110–120×150–240.

## Показ на /demo (с 06.11) и банк
- **Набор:** `tools/scout/compose_bedroom.py` (правила `tools/scout/rules/bedroom-composition.json`) → `sets-bedroom.next.json`; ячейка
  `room_id|purpose|band|style|tier` (`tools/scout/room_identity.py:cell`); стиль без ядра ночью не собирается (`core_skip`).
- **Банк:** ночью prepare → pending → promote (≤ 25 %/ночь) → `sets-bedroom.json` (с 12.11 promote выключен до
  новой нормы проходов, ADR-0394); флаги `tools/scout/rules/bank-candidate.json:rooms.bedroom`. Руками не менять (урок 623).
- **Витрина:** `tools/scout/demo_bedroom.py` поверх `tools/scout/demo_room.py`; пустую роль добирает `demo_room.py:role_spares`.
- **Модель:** правило `tools/scout/room_bindings.py:usable`; изголовье — сторож `tools/scout/bed_headboard.py` (ночью до привязки).

## Расстановка
- Угловая кровать — только в угол, не для пары; ковёр по выступу 45–70 см (`tools/scout/compose_bedroom.py:rug_norm`).
- /try: у окна — низкие рамы (`tools/scout/trial_bedroom.py:window_low_beds`).
- **Группы (ADR-0392, [[room-templates]]):** паспорт `services/planner-solver/rules/room-templates/bedroom.json`; движок —
  `services/planner-solver/planner/bedroom_checks.py:engine` (обычно `groups`, откат — `BEDROOM_ENGINE=items`). Только в groups — P1–P10 (ADR-0384): пара в
  тесной — кровать 140, в малой квадратной — без шкафа; без кровати — «кабинет». Бок без тумбы — к стене или проход 75
  (`services/planner-solver/planner/bedroom.py:_free_side_ok`). План — `plans/bedroom-groups-01.md`.

## Стили и назначения
- Шесть стилей; неоклассики в банке нет — нет ядра в каталоге (`core_skip`). Спальня 2 — couple/single/guest/office/child:*;
  детская — `kids-room-01`, наборов в банке нет.

**Tier 2:** `../domain/pipeline-order-details.md` § «Банки других комнат», § «Спальня 10–12.11» · [[b2b-10-rooms-beyond-living]] · ADR-0330.
