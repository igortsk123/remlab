---
tier: 1
topic: layout
scope: Расстановка — свод правил, зона-билдер, прод-ядро
tier2: ../domain/occupancy-rules.md
updated: 2026-08-13
importance: high
source: manual
status: working
---

# Расстановка — Tier 1

**Правила**: свод `../domain/occupancy-rules.md` → `services/planner-solver/rules/occupancy.json`.
**Прод-ядро** (ADR-0052, `services/planner-solver/`, Python+shapely, БЕЗ ML): кандидаты → hard →
beam → скоринг → уточнение → top-K; детерминизм; полигонные контуры. Остатки: backtracking
26–30 ([[layout-engine-gaps]]), косые стены.

**Зонный — боевой дефолт (ADR-0074/0075):** `services/planner-solver/planner/zones.py` + группы `services/planner-solver/rules/zones.json`,
лексикографический отбор. Рефери — ADR-0076/0077; обеденная — ADR-0078; T6 — ADR-0080
(`services/planner-solver/planner/tv.py`).
**Целостность шаблонов (12.08, ADR-0088/0089/0090/0091):** шаблон = паспорт с инвариантами —
`services/planner-solver/rules/templates.json` (состав, приоритет схем, инварианты, ГЕОМЕТРИЯ схем,
пруфы); машинная проверка на сборке — `services/planner-solver/planner/invariants.py`; габарит ==
SKU (иначе прогон падает), конверт слота применяется только при подборе товара
(`tools/scout/compose2.py`); `tpl_id` у каждого размещения; гейт качества (маршрут, «щели»,
смещение фокуса) — `services/planner-solver/planner/quality.py`; fill — диагностика, не цель.
Порядок: фокус-стена → диван → циркуляция → носитель → ковёр/столик → доп. посадка → хранение →
свет → декор. Сторожа — `services/planner-solver/tests/test_template_integrity.py` (8),
пруфы чисел — `tools/scout/rules_audit.py`. Замер 12.08: 252/252 чисто, медиа 223 сцены,
смещение носителя медиана 27 см, маршрут ≥70 везде. Режимная триада small/transitional/large (13.08, ADR-0092): пары ТВ↔диван
(`services/planner-solver/planner/tv_sofa.py`), карта ограничений
(`services/planner-solver/planner/room_map.py`), машина остатка R, уровни деградации A/B/C/D;
12 сторожей. Очередь — [[slots-everywhere]].

**Tier 2:** ../domain/occupancy-rules.md · ../guides/layout-mined-rules.md · ../guides/layout-engine-spec.md
