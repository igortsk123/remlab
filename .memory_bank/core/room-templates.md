---
tier: 1
topic: room-templates
scope: Шаблоны комнат — порядок, паспорт, листы
tier2: "../domain/room-templates.md"
updated: 2026-11-18
importance: high
source: _intake/session-scratch.md
status: working
source_of_truth: canonical
last_verified: 2026-11-18
review_after: 2026-12-10
---

# Шаблоны комнат — Tier 1

Единственный вариант правил (TG 768). Ведёт common (ADR-0390); шаблон комнаты → товары стиля −20…+10 % → на ТО ЖЕ место (ADR-0391).
**Строго по шаблонам (ADR-0407):** цель: расстановка — перебор всех совместимых шаблонов (сейчас один шаблон по `priority`, `room_templates.py:template_for`; перебор — только в каталоге спальни тенью); подходящего нет — новый шаблон, не правка под квартиру
(в каталоге спальни — `NO_ROOM_TEMPLATE_FITS` → кандидат, `tools/scout/bedroom_catalog_schemes.py`).

## Порядок
1. Состав и каталог шаблонов с Codex; ни одного товара без места в 3D.
2. Паспорт `services/planner-solver/rules/room-templates/<тип>.json` (`room-composition/1`,
   `services/planner-solver/planner/room_templates.py`: `load`, `check`, `compile_level`); числа — `rule_ref` на
   `services/planner-solver/rules/occupancy.json` (ADR-0392).
3. Листы в масштабе на 8+ комнатах — `tools/scout/bedroom_schemes.py`, `tools/scout/living_schemes.py`.
4. «Ок» владельца → код: группы в движке (`services/planner-solver/planner/bedroom.py:_solve_groups`); листы «было | стало».

## Проходы
Принято ADR-0394 (TG 790), в коде — `services/planner-solver/rules/occupancy.json` (`clearances.*`, `_profiles`), тест `services/planner-solver/tests/test_passage_norms.py`.
Норм «по м²» нет: площадь и ширина выбирают состав, проход — одна норма: цель · допуск `compact` · жёсткий минимум.
Сперва уходят предметы, потом допуск. RU-обычная: бок кровати и путь к окну 50, распашной шкаф и ящики 70, купе 50 (диван–столик — `distances_cm.coffee_table_reach_abs_min` 30)
(Пособие к СНиП 2.08.01-89 п. 3.1). M4(2) 75 и M4(3) 100 — только жильё «доступное». Пороги внедрены для спальни и прихожей (ADR-0394).

## Сейчас
Спальня — движок групп ([[bedroom]]), каталог 24 шаблонов `bedroom-catalog.json` — тенью (T-120, назначение 6–7,5 м² — ADR-0408); гостиная — паспорт `living.json` тенью, уровень по набору `room_templates.py:levels_by_set`; прихожая — `hall.json` H1–H10 тенью, проход от входа `hall_checks.py:_entry_step` (детали — Tier 2).

**Tier 2:** `../domain/room-templates.md` · ADR-0369, 0384, 0390–0392 · [[layout]].
