---
tier: 1
topic: layout
scope: Расстановка: правила, зоны, прод-ядро
tier2: ../domain/occupancy-rules.md
updated: 2026-08-19
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
(`services/planner-solver/rules/templates.json`), конверт слота — при подборе (`tools/scout/compose2.py`).
**Модификаторы (ADR-0094):** mode × shape × контур — `services/planner-solver/planner/room_map.py`.
**Своды №10–13 и 17.08 (ADR-0104…0108):** BEAM по гипотезам (plan_key), MEDIA_MISSING, ТВ-канон,
LEVEL-A guard, паспорта=runtime, второй pod как комплект, «только каноны» (допуски сняты).
**Q6b–Q10 (18–19.08, ADR-0110):** уголок столовой, способности каталога, круглые формы, консоль за
диваном, полоса за спинкой (`services/planner-solver/planner/back_gap.py`), приоры практики и
сертификат возможности (`services/planner-solver/planner/opportunities.py`) — В ТЕНЬ; фактическая
вместимость (`realized_capacity`, ключ в тени).
**Экспорт для ИИ:** `tools/scout/export_plans_ai.py` → хаб `/test/plans-export.zip`.

**Q11 (19.08, ADR-0109):** визуальная библиотека канонов `/test/canons/` — схемы паспорта рисуются
кодом рабочих планов (`tools/scout/canon_gallery.py`) и проходят боевой `validate()`; контекст на
референсе — только если схема определена относительно него (ТВ по оси ГЛАВНОГО дивана,
`geometry.seat_axis_origin`). Отрисовка вскрыла дефекты боевого кода (стороны кресел `media_bridge`,
отступ `_corner_candidates`, единственный кандидат в эркере, столик Г-композиции в 75 см от второго
дивана) — разбор и порядок работ: `plans/q11-canon-reference-contract.md`.

**Tier 2 (детали, история, рабочие заметки пакетов):** `../domain/occupancy-rules.md` ·
`../guides/layout-engine-spec.md`
