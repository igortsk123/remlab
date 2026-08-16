---
tier: 1
topic: layout
scope: Расстановка: правила, зоны, прод-ядро
tier2: ../domain/occupancy-rules.md
updated: 2026-08-16
importance: high
source: manual
status: working
---

# Расстановка — Tier 1

**Правила**: `../domain/occupancy-rules.md` → `services/planner-solver/rules/occupancy.json`.
**Прод-ядро** (ADR-0052): Python+shapely, БЕЗ ML; кандидаты → hard → beam → скоринг →
top-K; детерминизм; контуры ([[layout-engine-gaps]]).

**Зонный — боевой дефолт (ADR-0074/0075):** `services/planner-solver/planner/zones.py` +
`services/planner-solver/rules/zones.json`; рефери ADR-0076/0077, обеденная ADR-0078.
**Целостность шаблонов (ADR-0088…0091):** паспорт+инварианты
(`services/planner-solver/rules/templates.json`), конверт слота только при подборе
(`tools/scout/compose2.py`), fill — диагностика.
Детали/история: `../guides/layout-engine-spec.md` (пары ТВ↔диван, машина остатка R,
уровни деградации).

**Tier 2:** ../domain/occupancy-rules.md · ../guides/layout-mined-rules.md · ../guides/layout-engine-spec.md

**Модификаторы (ADR-0094):** mode × shape × контур скорингом — `services/planner-solver/planner/room_map.py`
(contour_features); порядок зон — `rules/zones.json → zone_priority` (резервы читают её).
Отложено: swivel, open-plan, потолок.
**Свод №12 (16.08, ADR-0106):** BEAM по гипотезам посадки — `services/planner-solver/planner/zones.py`
(solve_zoned_beam/plan_key, greedy = гипотеза №0); медиа required ⇒ ровно один (MEDIA_MISSING);
ось ТВ медиана 0.0; scenario_needs; паспорта=runtime; подача: пилон/фасад словами.
**Свод №11 (15.08, ADR-0105, аудит Кодекса):** единый ТВ-канон и comfort-first лестница
+ LEVEL-A guard — FAR-large 60→40% (`services/planner-solver/planner/tv_sofa.py`, планка 41);
quiet разблокирован (в проде 0 — честный проигрыш dining); порядок цепочки зон = данные;
coverage: alt-кресло в банк ≥17 м² (`tools/scout/compose2.py`) — dining 210.
**Свод №10 (15.08, ADR-0104):** band=КАП лестницы (pouf 149→22); functional claim
щелей (острова 44+62); TALL_SOLID_BEHIND_SOFA; контракт угла.
**Экспорт для ИИ:** `tools/scout/export_plans_ai.py` (JSON/семантика+ASCII/PNG + index) → хаб `/test/plans-export.zip`.
