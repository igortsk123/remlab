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
**Прод-ядро** (ADR-0052, `services/planner-solver/`, Python+shapely, БЕЗ ML): кандидаты →
hard → beam → скоринг → top-K; детерминизм; полигонные контуры ([[layout-engine-gaps]]).

**Зонный — боевой дефолт (ADR-0074/0075):** `services/planner-solver/planner/zones.py` +
`services/planner-solver/rules/zones.json`; рефери ADR-0076/0077, обеденная ADR-0078.
**Целостность шаблонов (12.08, ADR-0088…0091):** паспорт+инварианты
(`services/planner-solver/rules/templates.json`, `services/planner-solver/planner/invariants.py`), конверт слота только при
подборе (`tools/scout/compose2.py`), гейт качества (`services/planner-solver/planner/quality.py`), fill — диагностика.
Детали/история: `../guides/layout-engine-spec.md` (пары ТВ↔диван, машина остатка R,
уровни деградации).

**Tier 2:** ../domain/occupancy-rules.md · ../guides/layout-mined-rules.md · ../guides/layout-engine-spec.md

**Модификаторы (ADR-0094):** mode × shape × контур скорингом — `services/planner-solver/planner/room_map.py`
(contour_features); порядок зон — `rules/zones.json → zone_priority` (резервы читают её).
Отложено: swivel, open-plan, потолок.
**Свод №6 (ADR-0095):** entry-зона за диваном (пустота легальна; SEATING_ACCESS_PINCHED),
ось Г-дивана по главной секции (`seat_axis_origin`); спящие: консоль/раннер/divider.
**Свод №9 (14.08, ADR-0102/0103):** P0-кардинальность носителя (3 уровня, MEDIA_DOUBLE_CARRIER);
trace dining (`_dining.search`, failed_axes); mode по топологии (55/90); cohesion-оси;
таксономия gap; зеркала Г-дивана: корень-баг знака исправлен (`geometry.corner_active_lat`),
выбор сравнением, сцены-пруф №270-272.
**Свод №8 v2 (14.08, ADR-0098…0101):** dining-паспорт в коде (envelope 90); каскад
full_island→compact→edge с объяснимостью (тихий edge=0); экран — часть media
(SCREEN_OVER_WINDOW + вейвер `+tvw`); статусы зон данными; оси `_axes`
(`services/planner-solver/planner/quality.py`). Планка dining 196 (ADR-0099).
Сцены №253+ со своими проёмами (`tools/scout/acceptance_run.py`).
**Экспорт для ИИ:** `tools/scout/export_plans_ai.py` (JSON/семантика+ASCII/PNG + index) → хаб `/test/plans-export.zip`.
