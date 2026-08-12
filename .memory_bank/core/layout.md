---
tier: 1
topic: layout
scope: Расстановка — свод правил, зона-билдер, прод-ядро
tier2: ../domain/occupancy-rules.md
updated: 2026-08-12
importance: high
source: manual
status: working
---

# Расстановка — Tier 1

**Правила**: свод `../domain/occupancy-rules.md` → `services/planner-solver/rules/occupancy.json`.
**Прод-ядро** (ADR-0052, `services/planner-solver/`, Python+shapely, БЕЗ ML): кандидаты → hard →
beam → скоринг → уточнение → top-K; детерминизм; полигонные контуры. Остатки: backtracking
26–30 ([[layout-engine-gaps]]), косые стены.

**Зонный — боевой дефолт (ADR-0074/0075):** `services/planner-solver/planner/zones.py` + группы `services/planner-solver/rules/zones.json`,
лексикографический отбор. Рефери — ADR-0076/0077; обеденная — ADR-0078; T6 — ADR-0080
(`services/planner-solver/planner/tv.py`).
**Целостность шаблонов (12.08, ADR-0088/0089/0090):** паспорта зон —
`services/planner-solver/rules/templates.json` (состав, приоритет схем, инварианты, пруфы);
машинная проверка на СБОРКЕ — `services/planner-solver/planner/invariants.py` (вызов
`template._valid`); габарит == SKU (иначе прогон падает), конверт −20/+10 только при подборе
(`tools/scout/compose2.py`); `tpl_id` у каждого размещения; сторож —
`services/planner-solver/tests/test_template_integrity.py`, пруфы чисел —
`tools/scout/rules_audit.py`. Зоны: медиа приоритетнее хранения (стена напротив посадки
резервируется), за спинкой отодвинутого дивана — столовая, хранение ≤2 предметов и ≤2 зон.
Медиа-стенка — паспорт `media_wall`; дверь — сектор у петли + проход 76 см. Зона одного пуфа
удалена. Замер 12.08: 252/252 чисто, медиа 191 сцена, хранение 246, посадочные на ковре 100%.
Дизайнерский порядок (12.08, ADR-0091): фокус-стена → диван → циркуляция → носитель →
ковёр/столик → доп. посадка → хранение → свет → декор; три круга фокуса в `place_template`,
гейт деградации на вторичных зонах — `services/planner-solver/planner/quality.py`
(маршрут ≥75, «щели» 45 см, смещение носителя ≤40); fill — диагностика, не цель.

**Tier 2:** ../domain/occupancy-rules.md · ../guides/layout-mined-rules.md · ../guides/layout-engine-spec.md
