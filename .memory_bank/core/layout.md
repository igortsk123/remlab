---
tier: 1
topic: layout
scope: Расстановка: правила, зоны, прод-ядро
tier2: ../domain/occupancy-rules.md
updated: 2026-08-17
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

**Модификаторы (ADR-0094):** mode × shape × контур — `services/planner-solver/planner/room_map.py`;
порядок зон — `rules/zones.json → zone_priority`.
**Свод №12 (ADR-0106):** BEAM по гипотезам — `services/planner-solver/planner/zones.py` (plan_key,
greedy = гипотеза №0); MEDIA_MISSING; scenario_needs; паспорта=runtime.
**Своды №10–11 (ADR-0104/0105):** ТВ-канон, comfort-first, LEVEL-A guard, band=кап, functional claim.
**Свод №13 (16–17.08, ADR-0107, Codex-советник):** метрики «как видит владелец» —
`services/planner-solver/planner/view_metrics.py` (диагностика); identity-адаптер банка
(`tools/scout/solver_run.py`, `_bank_unused`); media-формы кресел + сертификаты семейств; `plan_key_v2`
SHADOW; второй pod = атомарный комплект пара 3/4 + столик 2 (`compose2.py pod_kit`), `quiet_chat`/
`fireplace_flank` + `check_quiet_contract`; контракт позы в экспорте (`export_plans_ai.py`).
**17.08 (ADR-0108):** «только каноны» — допуски (сдвиг столика, зазоры 32/48) сняты из каскада
`services/planner-solver/planner/template.py`; реестр канонов `/test/templates/` из паспортов; ускорение
цикла `tools/scout/run.sh smoke|render`, снимок банков; 8 XL TIMEOUT — открыто.
**Экспорт для ИИ:** `tools/scout/export_plans_ai.py` (JSON/семантика+ASCII/PNG + index) → хаб `/test/plans-export.zip`.
