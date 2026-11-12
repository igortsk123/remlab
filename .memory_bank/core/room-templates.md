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

Единственный вариант правил (TG 768). Ведёт common (ADR-0390); шаблон комнаты → товары стиля −20…+10 % → на ТО ЖЕ место (ADR-0391).

## Порядок
1. Состав и каталог шаблонов с Codex; ни одного товара без места в 3D.
2. Паспорт `services/planner-solver/rules/room-templates/<тип>.json` (`room-composition/1`,
   `services/planner-solver/planner/room_templates.py`: `load`, `check`, `compile_level`); числа — `rule_ref` на
   `services/planner-solver/rules/occupancy.json` (ADR-0392).
3. Листы в масштабе на 8+ комнатах — `tools/scout/bedroom_schemes.py`, `tools/scout/living_schemes.py`.
4. «Ок» владельца → код: группы в движке (`services/planner-solver/planner/bedroom.py:_solve_groups`); листы «было | стало».

## Проходы
**Предложение T-65, в коде пока нет** (сейчас — одиночные числа `occupancy.json:distances_cm`: бок кровати 75, распашной шкаф 90).
Норм «по м²» нет: площадь и ширина выбирают состав, проход — одна норма: цель · допуск `compact` · жёсткий минимум.
Сперва уходят предметы, потом допуск. RU-обычная: бок кровати и путь к окну 50, распашной шкаф и ящики 70, купе 50, диван–столик 30
(Пособие к СНиП 2.08.01-89 п. 3.1). M4(2) 75 и M4(3) 100 — только жильё «доступное». Пороги — до «ок» владельца (T-65).

## Сейчас
Спальня — движок групп ([[bedroom]]); гостиная — паспорт `living.json` тенью, `plans/living-full-01.md`.

**Tier 2:** `../domain/room-templates.md` · ADR-0369, 0384, 0390–0392 · [[layout]].
