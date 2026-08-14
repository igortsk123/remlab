---
tier: 1
topic: layout
scope: Расстановка — свод правил, зона-билдер, прод-ядро
tier2: ../domain/occupancy-rules.md
updated: 2026-08-14
importance: high
source: manual
status: working
---

# Расстановка — Tier 1

**Правила**: свод `../domain/occupancy-rules.md` → `services/planner-solver/rules/occupancy.json`.
**Прод-ядро** (ADR-0052, `services/planner-solver/`, Python+shapely, БЕЗ ML): кандидаты → hard →
beam → скоринг → уточнение → top-K; детерминизм; полигонные контуры. Остатки: backtracking
26–30 ([[layout-engine-gaps]]), косые стены.

**Зонный — боевой дефолт (ADR-0074/0075):** `services/planner-solver/planner/zones.py` +
`services/planner-solver/rules/zones.json`; рефери ADR-0076/0077, обеденная ADR-0078, T6 ADR-0080.
**Целостность шаблонов (12.08, ADR-0088…0091):** паспорт+инварианты
(`services/planner-solver/rules/templates.json`, `services/planner-solver/planner/invariants.py`), конверт слота только при
подборе (`tools/scout/compose2.py`), гейт качества (`services/planner-solver/planner/quality.py`), fill — диагностика.
Детали и историю см. `../guides/layout-engine-spec.md`.
(`services/planner-solver/planner/tv_sofa.py`), карта ограничений
(`services/planner-solver/planner/room_map.py`), машина остатка R, уровни деградации A/B/C/D;
12 сторожей. Очередь — slots-everywhere (completed).

**Tier 2:** ../domain/occupancy-rules.md · ../guides/layout-mined-rules.md · ../guides/layout-engine-spec.md

**Модификаторы (14.08, ADR-0094, свод №5):** mode × shape × контур — ортогональные признаки,
комбинируются скорингом: `contour_features` (эркер/колонна/квадрат) —
`services/planner-solver/planner/room_map.py`, пороги в `services/planner-solver/rules/templates.json`;
clearance-классы и dead_side-маска — `services/planner-solver/planner/quality.py`; подбор
(масса/ножки/посадка/круглое/концентрация) — `tools/scout/compose2.py`. Приоритет зон —
ЕДИНАЯ таблица `services/planner-solver/rules/zones.json → zone_priority`; резервы места читают
её — `services/planner-solver/planner/zones.py`. R5: 17 hard — «сторожевые» (0 за 252,
`services/planner-solver/rules/registry.json`), замер — LAYOUT_RULE_STATS; маршрут сцены — `_route_cm`
в артефакте (`tools/scout/solver_run.py`). Замер 14.08: 252/252, медиа 252/252, маршрут min 75,
«глупых» 226. Отложено: swivel (нет данных), open-plan (нет сцен), потолок (спит до ceiling_cm).
**Свод №6 (ADR-0095):** entry-зона за диваном (пустота легальна, вход вокруг торца —
SEATING_ACCESS_PINCHED), Г-диван: ось по ГЛАВНОЙ секции (`seat_axis_origin`), зазор от угла —
функциональная проверка, не порог; спящие: консоль/раннер/divider.
