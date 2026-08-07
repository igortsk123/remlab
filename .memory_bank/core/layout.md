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

**Зонный — боевой дефолт (08.08, ADR-0075):** приёмка 252 фикс-сцены — zoned 239/252 vs beam
119/252, 0 сцен хуже; экземпляры ролей («кресло 2»/«диван 2»/«стул N») — полноправны
(`base_role`, qty из сета в FLOOR); W-правки: severity-реестр 47 кодов+тест, столик 36–46 фикс,
size-bands→приоры, pair_symmetry (S2).
**Арбитраж рефери принят (08.08, ADR-0076/0077):** ярусы = приоритет удержания — не влезшие
dining/storage дропаются ярусом, обеденная атомарна (стол+≥2 стульев, `beam.solve`); новые S-чеки
камин/окно; FLOOR_OVERFILL и SOFA_SLIVER демотированы; мёртвая зона локализована (диван+100);
wall-back из данных; ТВ distance-first (приор тумбы 70–90); zoned — чистый планнер (DFS-фолбэк
убран, test_engine_purity). Расходиться с рефери — только с самостоятельным пруфом (владелец).
План: [[referee-hardening]].
**Зоны-first (ADR-0074):** `services/planner-solver/planner/zones.py` — usable-площадь, группа по
`services/planner-solver/rules/zones.json`, `solve_zoned`, ЛЕКСИКОГРАФИЧЕСКИЙ отбор (hard→циркуляция→функция→зоны→
эстетика). Hard — только физика. Тесты: Q-антипаттерны + 3 Э8-контура; приёмка — 252 фикс-сцены
(`acceptance_run.py`, jsonl-resume).
**А3/А5 (06.08, [[MASTER-pipeline-hardening]]):** beam — дефолт; SOFT-термы и порог «глупости»
DUMB_T=12; пуф-пороги в ядре; 117/126. Остаток: backtracking 26–30 ([[layout-engine-gaps]]).

**Tier 2:** ../domain/occupancy-rules.md · ../guides/layout-mined-rules.md · ../guides/layout-engine-spec.md
