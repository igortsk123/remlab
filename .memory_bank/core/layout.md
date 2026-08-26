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
**Своды №10–13 (ADR-0104…0108):** BEAM по гипотезам, ТВ-канон, «только каноны»;
пакеты Q6b–Q10 (нук, capability, back_gap, приоры, сертификат возможностей) — детали в Tier 2.

**Q11–Q12 — каноны и ситуационный канон (ADR-0109…0114):** `/test/canons/` рисуется кодом
рабочих планов; схема выбирается под ЯКОРЬ комнаты (окно/эркер/угол/камин/стена), паспорт
объявляет якорь и форму, приоры практики — только локальный тайбрейк. Аудиты владельца
21.08 (ADR-0115…0119) и разбор канонов — в Tier 2.

**26.08 (корневые правки по разбору владельца):** ось «диван → носитель» считается ОТ ГЛАВНОЙ
СЕКЦИИ (`geometry.seat_axis_origin`) во всех местах, включая фильтр центрированных позиций
(ADR-0122; медиана смещения 17 → 0 см); ярус ГЛАВНОГО МАРШРУТА (`zones.main_route_tier` по
`quality.route_width_cm`) стоит ВЫШЕ богатства состава, ниже пола 70 см — терминальный
`CIRCULATION_MISSING` с сертификатом; контракты подбора банка (конверт слота, ковёр↔диван,
экземпляры пары) применяются и при лечении данных, а не только при сборке (ADR-0121).

**Tier 2:** `../domain/occupancy-rules.md` · `../guides/layout-engine-spec.md`
