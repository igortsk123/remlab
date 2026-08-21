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

**Зонный — боевой дефолт (ADR-0074…0078):** `services/planner-solver/planner/zones.py`.
**Шаблоны/модификаторы (ADR-0088…0094):** паспорт+инварианты
(`services/planner-solver/rules/templates.json`), конверт слота (`tools/scout/compose2.py`).
**Своды №10–13 (ADR-0104…0108):** BEAM по гипотезам, ТВ-канон, «только каноны». **Q6b–Q10
(ADR-0110):** способности каталога, приоры/сертификат — в тень. **Экспорт ИИ:** `tools/scout/export_plans_ai.py`.

**Q11 — библиотека канонов (ADR-0109/0111):** `/test/canons/` рисуется кодом рабочих планов
(`tools/scout/canon_gallery.py`) и проходит боевой `validate()`; отрисовка стала источником боевых
правок — `completed_plans/q11-canon-reference-contract.md`.

**Q12 — ситуационный канон (19–20.08, ADR-0112/0113/0114):** схема выбирается под ЯКОРЬ комнаты
(`room_map → opportunity → схемы → trace → сертификат`); единица учёта — пара (группа, форма),
исполняемая схема без паспорта запрещена. Паспорт — 12 зон / 60 схем, галерея — 65 карточек,
покрытие полное; спящих 3. Гейт — `services/planner-solver/tests/test_passport_situational.py`.
Остаток — Q12-3, Q12-5…7 (`plans/q12-situational-canon.md`). **Заморозка (владелец 19.08):**
планы/экзамен/экспорт не пересобираем, пока каноны не отработаны.

**Аудит Юли 21.08 (ADR-0115):** 13/15 принято, №13/№35 отклонены с пруфом. Камин+ТВ — каскад
side_by_side → смежные стены → ТВ над камином (разбужена); «между окон» — честная реализация
(ось простенка); свет чтения за плечом всегда; консоль ≥⅔ дивана; sectional только угловой.
ТВ-референс на носителях. Якоря кода и детали — ADR-0115, `../domain/occupancy-rules.md`
(раунд 4); гейт — `services/planner-solver/tests/test_audit_julia_2108.py`.

**Tier 2:** `../domain/occupancy-rules.md` · `../guides/layout-engine-spec.md`
