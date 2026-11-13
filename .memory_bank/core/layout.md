---
tier: 1
topic: layout
scope: Расстановка: правила, зоны, прод-ядро
tier2: ../domain/occupancy-rules.md
updated: 2026-11-13
last_verified: 2026-11-12
importance: high
source: manual
status: working
source_of_truth: canonical
review_after: 2026-12-05
---

# Расстановка — Tier 1

**Правила**: `../domain/occupancy-rules.md` → `services/planner-solver/rules/occupancy.json`.
**Прод-ядро** (ADR-0052): Python+shapely, БЕЗ ML; детерминизм (`archive/plans/layout-engine-gaps.md`).
Дефолт `LAYOUT_ENGINE=zoned` (`tools/scout/solver_run.py:ENGINE`); опция `LAYOUT_ENGINE=llm` — `services/planner-solver/planner/llm_planner.py`.

**Зонный — боевой дефолт (ADR-0074…0078):** `services/planner-solver/planner/zones.py`.
**Шаблоны/модификаторы (ADR-0088…0094):** паспорт+инварианты
(`services/planner-solver/rules/templates.json`), конверт слота (`tools/scout/compose2.py`).
**Своды №10–13 (ADR-0104…0108):** BEAM по гипотезам, ТВ-канон, «только каноны»;
пакеты Q6b–Q10 (нук, capability, back_gap, приоры, сертификат возможностей) — детали в Tier 2.

**Q11–Q12 (ADR-0109…0114):** каноны `/test/canons/`; схема — под ЯКОРЬ комнаты (окно/эркер/угол/камин/стена), приоры — тайбрейк.

**26.08:** ось «диван → носитель» — от главной секции (`geometry.seat_axis_origin`, ADR-0122); главный маршрут (`zones.main_route_tier`)
выше богатства состава, < 70 см — `CIRCULATION_MISSING`; контракты подбора — и при лечении данных (ADR-0121).

**Типы комнат (T-37):** проверки — по `room.room_type` через реестр `services/planner-solver/planner/room_registry.py:PLAGINY`
(гостиная `validate.py:validate_living`, спальня `bedroom_checks.py:validate_bedroom`, кухня `kitchen_checks.py`, прихожая
`hall_checks.py:validate_hall`); детская — роли спальни (`purpose == "child"`). Фронт распашного шкафа 90 см
(`occupancy.json:wardrobe_hinged_front_min`, ADR-0330); гостиная вдвое быстрее (`services/planner-solver/planner/geometry.py`).

**Выбор набора — по обязательному ядру (ADR-0411, 13.11):** без награды за число предметов; необязательный атом (комод+лампа) не
ухудшает ядро; тур при провале ядра пробует следующий набор (`tools/scout/trial_demo.py`, `tools/scout/flat215_demo.py`, тест
`tools/scout/tests/test_dresser_atom.py`). Строго по шаблонам — ADR-0407, [[room-templates]].

**Tier 2:** `../domain/occupancy-rules.md` · `../guides/layout-engine-spec.md`
