---
tier: 1
topic: layout
scope: Расстановка: правила, зоны, прод-ядро
tier2: ../domain/occupancy-rules.md
updated: 2026-08-14
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
**Свод №6 (ADR-0095):** entry-зона за диваном (пустота легальна; SEATING_ACCESS_PINCHED),
ось Г-дивана по главной секции (`seat_axis_origin`); спящие: консоль/раннер/divider.
**Свод №10 (15.08, ADR-0104):** band=КАП лестницы (pouf 149→22); seating_search/
axis_contract/rug-trace; functional claim щелей (dining 209, острова 44+62);
TALL_SOLID_BEHIND_SOFA; контракт угла; аудит контрактов.
**Свод №9 (ADR-0102/0103):** кардинальность носителя (3 уровня); trace dining;
mode по топологии; cohesion-оси; корень-баг знака зеркала исправлен
(`services/planner-solver/planner/geometry.py` corner_active_lat), выбор сравнением.
**Свод №8 v2 (ADR-0098…0101):** dining-паспорт в коде; каскад island→edge; экран —
часть media (вейвер `+tvw`); статусы зон данными; оси `_axes`. Сцены №253+ со
своими проёмами.
**Экспорт для ИИ:** `tools/scout/export_plans_ai.py` (JSON/семантика+ASCII/PNG + index) → хаб `/test/plans-export.zip`.
