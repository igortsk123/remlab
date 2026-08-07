---
tier: 1
topic: layout
scope: Расстановка — свод правил, зона-билдер, прод-ядро
tier2: ../domain/occupancy-rules.md
updated: 2026-08-08
importance: high
source: manual
status: working
---

# Расстановка — Tier 1

**Правила**: свод `../domain/occupancy-rules.md` → машиночитаемо
`services/planner-solver/rules/occupancy.json` (ОДИН файл на оба движка); шкалы от площади;
ковёр — к дивану.
**Legacy (scout)**: DFS — периферия, для A/B (`solver_run.py --engine dfs`).
**Прод-ядро** (ADR-0052, `services/planner-solver/`, Python+shapely, БЕЗ ML): кандидаты → hard →
beam (20×8) → скоринг → уточнение → top-K с объяснениями. Э1–Э5 в коде, 61 тест,
1.5–2.2 с/комнату, детерминизм. Комнаты пока прямоугольные, геометрия полигонная.
**Требование владельца 07.08: обязательна работа в нестандартных планировках** (Г-контуры,
open-plan кухня-гостиная, эркеры) — план [[layout-polygon-rooms]] (Э8); правила и priors
([[layout-priors-from-datasets]]) строить сразу в терминах контура. Осталось также:
backtracking 26–30 м². Спека `../guides/layout-engine-spec.md`; добытые правила —
`../guides/layout-mined-rules.md` (при конфликте канон наш).

**Зоны-first (08.08, ADR-0074, [[MASTER-zones-first]]):** `services/planner-solver/planner/zones.py` — usable-площадь
(контур − swing − радиаторы − входной резерв), выбор посадочной группы по `services/planner-solver/rules/zones.json`
(10 групп, reference-футпринты), `solve_zoned`; финальный отбор ЛЕКСИКОГРАФИЧЕСКИ
(hard→циркуляция→функция→зоны→эстетика — эстетика не компенсирует проход). Hard — только физика,
числа soft. 73 теста: антипаттерны Q2/Q3/Q6 + 3 Э8-контура (эркер/пилоны/трапеция).
Приёмка — 252 фикс-сцены (`acceptance_run.py`, A/B beam/zoned, jsonl-resume, ENGINE=zoned).
**А3/А5 (06.08, [[MASTER-pipeline-hardening]]):** beam — дефолт; SOFT-термы и порог «глупости»
DUMB_T=12; пуф-пороги в ядре; 117/126. Остаток: backtracking 26–30 ([[layout-engine-gaps]]).

**Tier 2:** ../domain/occupancy-rules.md · ../guides/layout-mined-rules.md · ../guides/layout-engine-spec.md
