---
tier: 1
topic: room-templates
scope: Шаблоны комнат — порядок создания, паспорт, листы в масштабе
tier2: "../domain/room-templates.md"
updated: 2026-11-12
importance: high
source: _intake/session-scratch.md
status: working
source_of_truth: canonical
last_verified: 2026-11-12
review_after: 2026-12-10
---

# Шаблоны комнат — Tier 1

Шаблоны всех комнат ведёт менеджер common (ADR-0390); правило одно на все комнаты (ADR-0391): шаблон целой комнаты из доступных
предметов → товары стиля в размере места −20…+10 % → лучший по стилю на ТО ЖЕ место.

## Порядок (подробно — Tier 2)
1. Состав и каталог шаблонов — с Codex (где лежат вопросы — Tier 2); ни одного товара без места в 3D.
2. Паспорт `services/planner-solver/rules/room-templates/<тип>.json`, формат `room-composition/1` —
   `services/planner-solver/planner/room_templates.py` (`load`, `check`, `template_for`, `level_of`); числа — `rule_ref` на
   `services/planner-solver/rules/occupancy.json` (ADR-0392).
3. Листы в масштабе на 8+ реальных комнатах по образцу Т0 — `tools/scout/bedroom_schemes.py`, `tools/scout/living_schemes.py`.
4. Показ владельцу → «ок» → код: геометрия групп в движке (`services/planner-solver/planner/bedroom.py:_solve_groups`), место товара —
   `services/planner-solver/rules/zones.json` → `template_slot_envelopes`.
5. Листы «было | стало» по координатам движка.

## Как ложится
Привязка к ролям стен (дверь / окно / глухая), перебор стен с поворотом и отражением, проверка нормами; не прошёл ни один — следующий
уровень (только целые составы) или честный отказ с причиной.

## Сейчас
Спальня — паспорт есть, движок групп за `BEDROOM_ENGINE` ([[bedroom]]); гостиная — листы T-46, паспорт — `plans/living-full-01.md`.

**Tier 2:** `../domain/room-templates.md` · ADR-0369, ADR-0384, ADR-0390–0392 · [[layout]].
