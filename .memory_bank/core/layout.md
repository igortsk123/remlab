---
tier: 1
topic: layout
scope: Расстановка — свод правил, зона-билдер, прод-ядро
tier2: ../domain/occupancy-rules.md
updated: 2026-08-02
importance: high
source: manual
status: working
---

# Расстановка — Tier 1

**Правила**: свод `../domain/occupancy-rules.md` (2 раунда мульти-джоб ресёрча, ~40 источников,
верификация фетчем) → машиночитаемо `tools/scout/occupancy.json`; решения владельца: кап пола /
диван↔столик / диван↔ТВ — ДИНАМИЧЕСКИЕ шкалы от площади; ковёр — привязка к дивану.
**Сейчас (scout)**: ЗОНА-БИЛДЕР (ADR-0050) — разговорная зона атомарным блоком (диван∥ТВ,
столик по шкале, кресло ПОЛУКРУГОМ к ТВ 135–225°±35° (ADR-0051, было 90° к столику),
пуф вне оси, буфер 65 см, бронь полосы за диваном;
Г-диван полигоном в угол, float к ТВ), DFS Holodeck — только периферия; hard-проверки по шкалам.
**Правило владельца (2026-08-02):** диван «по центру» допустим, но тогда стена ЗА ним не должна
пустовать — либо диван к стене, либо за спинкой хранение/консоль (в движке — штраф
`empty_wall_behind_sofa`); промежуточная щель 20–70 см запрещена (или вплотную, или проход ≥76).
**Прод-ядро** (ADR-0052, `services/planner-solver/`, Python+shapely, БЕЗ ML): кандидаты → hard-фильтр
→ beam search (20×8) → скоринг (`services/planner-solver/rules/weights.json`) → уточнение → top-K с объяснениями.
**Э1–Э5 в коде**, 60 тестов, 1.5–2.2 с/комнату, детерминизм; канон правил переехал в
`services/planner-solver/rules/occupancy.json` (был вне git). Осталось: Э6 LLM-слой, Э7 интеграция
со scout (`--engine beam`). Спека `../guides/layout-engine-spec.md`. **Э0 ГОТОВ** (2026-08-02):
118 правил из ProcTHOR/Infinigen/Holodeck + clean-room из NC-статей → `../guides/layout-mined-rules.md`
(там же 15 модулей к легальному vendor/adapt и 15 конфликтов с нашими правилами — при конфликте
канон наш: `occupancy.json` + решения владельца). Clean-room обязателен: NC-код не копируем.

**Tier 2:** ../domain/occupancy-rules.md · ../guides/layout-mined-rules.md · ../guides/layout-engine-spec.md
