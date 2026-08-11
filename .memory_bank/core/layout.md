---
tier: 1
topic: layout
scope: Расстановка — свод правил, зона-билдер, прод-ядро
tier2: ../domain/occupancy-rules.md
updated: 2026-08-11
importance: high
source: manual
status: working
---

# Расстановка — Tier 1

**Правила**: свод `../domain/occupancy-rules.md` → `services/planner-solver/rules/occupancy.json`.
**Прод-ядро** (ADR-0052, `services/planner-solver/`, Python+shapely, БЕЗ ML): кандидаты → hard →
beam → скоринг → уточнение → top-K; детерминизм; полигонные контуры. Остатки: backtracking
26–30 ([[layout-engine-gaps]]), косые стены.

**Зонный — боевой дефолт (ADR-0074/0075):** `services/planner-solver/planner/zones.py` usable
+ группы из `services/planner-solver/rules/zones.json`, лексикографический отбор; `base_role`.
Рефери — ADR-0076/0077 (расходиться — со своим пруфом); обеденная — ADR-0078; T6 —
ADR-0080 (`services/planner-solver/planner/tv.py`, constraint-CI).
**MASTER-layout-v5 (ADR-0082/0083):** подложка вне free_space, кламп дериватив-якорей,
joint-пары ВЫКЛ, `tools/scout/topo_sig.py`; 62 кода. Приёмка:
`tools/scout/acceptance_run.py` (ACC_WORKERS=6, timeout 600; рядом тяжёлое не гонять —
аварийные записи).
**KB-merge (10.08, план kb-rules-merge):** книжные числа в occupancy только через класс-гейт
LAYER_STRENGTHS (`services/knowledge-db/kdb/export_rules.py`): hard слушает REQUIRED/MAXIMUM,
рекомендации — preferred (ADR-0086). Парность диванов — `tools/scout/compose2.py`
(same_model→collection→palette→2 кресла); Г-стык + SOFA_BLOCKS_SOFA S1
(`services/planner-solver/planner/validate.py`). Бисект — `tools/scout/acceptance_bisect.py`.
Гейт: 252/252, 0 хуже, 245 чистых, band50+ 32/36; `_tv`-аннотация — `tools/scout/solver_run.py`.
**Петля судьи (10.08, ADR-0085):** СУДЬЯ один — GPT terra-vision (`tools/scout/judge_layout.py`;
judge.py по коллажам — «контроль коллажей», не судья). Применимые правила из [[knowledge-db]],
ходы принимаются по lex_score; реестры в git; кандидаты правок — `tools/scout/judge_learn.py`
(решает владелец); прозрачность — /test/rules/ (`tools/scout/rules_page.py`); ~$0.043/сцена;
замечания — `tools/scout/owner-comments.jsonl`.
**Шаблоны зон (11.08, [[solver-speed]] T3.5):** библиотека блоков —
`services/planner-solver/planner/template.py` (посадка/медиа/столовая/хранение/чтение/камин);
цепочка зон в `planner/zones.py` (теги `+tpl+tv+fp+din+st+rd`), фолбэк beam жив
(`LAYOUT_TEMPLATES=0`). Витрина с табами по площади — `tools/scout/templates_page.py`
(/test/templates/). Датасет-опора и правило декора — ADR-0087; очередь новых схем —
[[template-library-v2]] (draft). Экзамен 252 ждёт команды владельца.

**Tier 2:** ../domain/occupancy-rules.md · ../guides/layout-mined-rules.md · ../guides/layout-engine-spec.md
