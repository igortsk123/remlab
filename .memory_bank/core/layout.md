---
tier: 1
topic: layout
scope: Расстановка: правила, зоны, прод-ядро
tier2: ../domain/occupancy-rules.md
updated: 2026-08-26
importance: high
source: manual
status: working
---

# Расстановка — Tier 1

**Правила**: `../domain/occupancy-rules.md` → `services/planner-solver/rules/occupancy.json`.
**Прод-ядро** (ADR-0052): Python+shapely, БЕЗ ML; детерминизм ([[layout-engine-gaps]]).

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
покрытие полное; спящих 4 (в т.ч. консоль — ADR-0116). Гейт — `services/planner-solver/tests/test_passport_situational.py`.
Остаток — Q12-3, Q12-5…7 (`plans/q12-situational-canon.md`). **Заморозка (владелец 19.08):**
планы/экзамен/экспорт не пересобираем, пока каноны не отработаны.

**Аудит Юли 21.08 (ADR-0115/0116):** 13/15 принято, №13/№35 отклонены с пруфом; консоль —
только стол-консоль (в фиде нет → схема спит). **Доктрина чтения канонов — ADR-0117**
(не-центр = обязательный якорь), внедрение — ADR-0118: `_media_min` (совместный камин+ТВ в
лестнице) + гейт `ANCHOR_SEMANTICS` (Q12-3). Детали — `../domain/occupancy-rules.md` (раунд 4);
гейты — `services/planner-solver/tests/test_audit_julia_2108.py` и `services/planner-solver/tests/test_anchor_semantics.py`.

**26.08 (корневые правки по разбору владельца):** ось «диван → носитель» считается ОТ ГЛАВНОЙ
СЕКЦИИ (`geometry.seat_axis_origin`) во всех местах, включая фильтр центрированных позиций
(ADR-0122; медиана смещения 17 → 0 см); ярус ГЛАВНОГО МАРШРУТА (`zones.main_route_tier` по
`quality.route_width_cm`) стоит ВЫШЕ богатства состава, ниже пола 70 см — терминальный
`CIRCULATION_MISSING` с сертификатом; контракты подбора банка (конверт слота, ковёр↔диван,
экземпляры пары) применяются и при лечении данных, а не только при сборке (ADR-0121).

**Tier 2:** `../domain/occupancy-rules.md` · `../guides/layout-engine-spec.md`
