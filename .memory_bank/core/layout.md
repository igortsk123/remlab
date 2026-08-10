---
tier: 1
topic: layout
scope: Расстановка — свод правил, зона-билдер, прод-ядро
tier2: ../domain/occupancy-rules.md
updated: 2026-08-10
importance: high
source: manual
status: working
---

# Расстановка — Tier 1

**Правила**: свод `../domain/occupancy-rules.md` → `services/planner-solver/rules/occupancy.json`.
**Прод-ядро** (ADR-0052, `services/planner-solver/`, Python+shapely, БЕЗ ML): кандидаты → hard →
beam → скоринг → уточнение → top-K; детерминизм; полигонные контуры (Э8). Остатки: backtracking
26–30 ([[layout-engine-gaps]]), косые стены. Спека `../guides/layout-engine-spec.md`.

**Зонный — боевой дефолт (08.08, ADR-0075):** zoned 239/252 vs beam 119/252, 0 сцен хуже;
экземпляры ролей полноправны (`base_role`).
**Арбитраж рефери принят (ADR-0076/0077, [[referee-hardening]]):** ярусы = приоритет удержания;
обеденная атомарна; zoned — чистый планнер (test_engine_purity). Расходиться с рефери — только
со своим пруфом (владелец).
**Обеденная + новые роли (08.08, ADR-0078, [[inventory-additions]]):** group-исключение в
`check_access`, якоря стульев к кромке, dining за диваном легальна, SERVICE_SURFACE S1.
**Зоны-first (ADR-0074):** `services/planner-solver/planner/zones.py` — usable, группа из
`services/planner-solver/rules/zones.json`, лексикографический отбор (hard→…→эстетика).
Приёмка — 252 фикс-сцены (`acceptance_run.py`).
**T6 (08.08, ADR-0080):** band в beam.solve (детерминизм); ТВ-геометрия
`services/planner-solver/planner/tv.py`; sofa_table_cm фикс 36–46; constraint-CI.
**MASTER-layout-v5 (09.08, ADR-0082/0083):** приёмка **245/252 (97.2%)**, медиана soft 8.8.
Ковёр-подложка исключён из free_space + кламп кандидатов ковра (ADR-0083 — вернул ковры/столики,
убрал SOFA_SLIVER/UNREACHABLE). Joint-пары кресел — под флагом `LAYOUT_PAIR_JOINT`, дефолт ВЫКЛ
(A/B: нетто 0, ADR-0082); AI-гипотезы отклонены (гейт L5). Камин-канон — в данных zones.json.
`Candidate.topology` + TOPO-сигнатуры `tools/scout/topo_sig.py`. Реестр 62 кодов, 99+ тестов.
Приёмка: `tools/scout/acceptance_run.py` (ACC_WORKERS=6 + timeout 600; во время экзамена НЕ
запускать рядом тяжёлое — солверов душит, записи выходят аварийными) + analyze/ab_compare.
**KB-merge (10.08, kb-rules-merge):** книжные числа в `occupancy.json` только через класс-гейт
`LAYER_STRENGTHS` (`services/knowledge-db/kdb/export_rules.py`): hard слушает REQUIRED/MAXIMUM,
рекомендации — в preferred (урок: [30,46]-регресс). Парность диванов — `tools/scout/compose2.py`
(same_model→same_collection→palette→2 кресла); Г-стык торец-к-торцу + SOFA_BLOCKS_SOFA (S1,
`planner/validate.py:check_sofa_pair_geometry`). Регресс ищет бисект `acceptance_bisect.py`.
Гейт финала: 252/252, 0 хуже, 245 чистых, band50+ 32/36.
**Петля судьи (10.08, ADR-0085):** только GPT terra-vision (`tools/scout/judge_layout.py`),
применимые правила из [[knowledge-db]], ходы принимаются по lex_score; реестры в git;
кандидаты правок — `judge_learn.py` (решает владелец); прозрачность — `/test/rules/`
(`rules_page.py`). Пилот: ~$0.043/сцена. Замечания владельца — `owner-comments.jsonl`.
**Дальше:** [[solver-speed]] (draft) — зонные ШАБЛОНЫ по band'ам со слот-конвертами
(−20/+10%), перебор по шаблонам вместо предметов; ковёр/стулья жёстко в шаблоне.

**Tier 2:** ../domain/occupancy-rules.md · ../guides/layout-mined-rules.md · ../guides/layout-engine-spec.md
