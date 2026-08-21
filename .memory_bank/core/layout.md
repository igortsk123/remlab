---
tier: 1
topic: layout
scope: Расстановка: правила, зоны, прод-ядро
tier2: ../domain/occupancy-rules.md
updated: 2026-08-21
importance: high
source: manual
status: working
---

# Расстановка — Tier 1

**Правила**: `../domain/occupancy-rules.md` → `services/planner-solver/rules/occupancy.json`.
**Прод-ядро** (ADR-0052): Python+shapely, БЕЗ ML; кандидаты → hard → beam → скоринг → top-K;
детерминизм ([[layout-engine-gaps]]).

**Зонный — боевой дефолт (ADR-0074…0078):** `services/planner-solver/planner/zones.py` + правила
зон, рефери, обеденная. **Шаблоны и модификаторы (ADR-0088…0094):** паспорт+инварианты
(`services/planner-solver/rules/templates.json`), конверт слота при подборе
(`tools/scout/compose2.py`), mode × shape × контур. **Своды №10–13 (ADR-0104…0108):** BEAM по
гипотезам, ТВ-канон, паспорта=runtime, «только каноны» без допусков. **Q6b–Q10 (ADR-0110):**
способности каталога, полоса за спинкой, приоры и сертификат возможности
(`services/planner-solver/planner/opportunities.py`) — в тень. **Экспорт для ИИ:**
`tools/scout/export_plans_ai.py`.

**Q11 — библиотека канонов (ADR-0109/0111):** `/test/canons/` рисуется кодом рабочих планов
(`tools/scout/canon_gallery.py`) и проходит боевой `validate()`; отрисовка стала источником боевых
правок — `completed_plans/q11-canon-reference-contract.md`.

**Q12 — ситуационный канон (19–20.08, ADR-0112/0113/0114):** схема выбирается под ЯКОРЬ комнаты
(`room_map → opportunity → схемы → search trace → сертификат`), приор практики — локально и в тени.
Единица учёта — пара (группа, форма): у всех схем `anchor`+`form`, зеркала слиты,
`seating.default` расщеплён на 7, запасные исходы — `situational_fallback` +
`requires_certificate`, исполняемая схема без паспорта запрещена. Паспорт — 12 зон / 59 схем,
галерея — 64 карточки, покрытие полное; спящих 4. Гейт —
`services/planner-solver/tests/test_passport_situational.py`. Нормы 20.08 — ADR-0114.
Остаток — Q12-3, Q12-5…7 (`plans/q12-situational-canon.md`). **Заморозка (владелец 19.08):**
планы/экзамен/экспорт не пересобираем, пока каноны не отработаны.

**Tier 2:** `../domain/occupancy-rules.md` · `../guides/layout-engine-spec.md`
