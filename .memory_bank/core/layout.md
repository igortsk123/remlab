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
`services/planner-solver/rules/occupancy.json` (ОДИН файл на оба движка).
**Прод-ядро** (ADR-0052, `services/planner-solver/`, Python+shapely, БЕЗ ML): кандидаты → hard →
beam → скоринг → уточнение → top-K с объяснениями; детерминизм; полигонные контуры (Э8).
DFS — периферия для A/B (`--engine dfs`). Остатки: backtracking 26–30, косые стены.
Спека `../guides/layout-engine-spec.md`; добытые правила — `../guides/layout-mined-rules.md`.

**Зонный — боевой дефолт (08.08, ADR-0075):** zoned 239/252 vs beam 119/252, 0 сцен хуже;
экземпляры ролей полноправны (`base_role`); W-правки: severity-реестр+тест, фикс-эргономика,
size-bands→приоры, pair_symmetry.
**Арбитраж рефери принят (08.08, ADR-0076/0077, [[referee-hardening]]):** ярусы = приоритет
удержания (дроп dining/storage ярусом; обеденная атомарна — стол+≥2 стульев); S-чеки камин/окно;
FLOOR_OVERFILL/SOFA_SLIVER демотированы; мёртвая зона локализована; wall-back из данных; ТВ
distance-first; zoned — чистый планнер (test_engine_purity). Расходиться с рефери — только с
самостоятельным пруфом (владелец). Приёмка пакета: 243/252.
**Обеденная группа + новые роли (08.08, ADR-0078, [[inventory-additions]]):** group-исключение
в `check_access` (раньше группа со стульями была геометрически невозможна); якоря стульев к
кромке; dining за диваном легальна; SERVICE_SURFACE S1; приставной/картина. Реестр 48 кодов.
**Зоны-first (ADR-0074):** `services/planner-solver/planner/zones.py` — usable-площадь, группа по
`services/planner-solver/rules/zones.json`, `solve_zoned`, ЛЕКСИКОГРАФИЧЕСКИЙ отбор (hard→циркуляция→функция→зоны→
эстетика). Hard — только физика. Тесты: Q-антипаттерны + 3 Э8-контура; приёмка — 252 фикс-сцены
(`acceptance_run.py`, jsonl-resume).
**А3/А5 (06.08):** SOFT-термы, DUMB_T=12; остаток — backtracking 26–30 ([[layout-engine-gaps]]).

**Tier 2:** ../domain/occupancy-rules.md · ../guides/layout-mined-rules.md · ../guides/layout-engine-spec.md
