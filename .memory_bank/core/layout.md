---
tier: 1
topic: layout
scope: Расстановка — свод правил, зона-билдер, прод-ядро
tier2: ../domain/occupancy-rules.md
updated: 2026-08-03
importance: high
source: manual
status: working
---

# Расстановка — Tier 1

**Правила**: свод `../domain/occupancy-rules.md` (2 раунда мульти-джоб ресёрча, ~40 источников,
верификация фетчем) → машиночитаемо `tools/scout/occupancy.json`; решения владельца: кап пола /
диван↔столик / диван↔ТВ — ДИНАМИЧЕСКИЕ шкалы от площади; ковёр — привязка к дивану.
**Сейчас (scout)**: ЗОНА-БИЛДЕР (ADR-0050) — разговорная зона атомарным блоком (диван∥ТВ,
столик по шкале, кресло у столика 90°, пуф вне оси, буфер 65 см, бронь полосы за диваном;
Г-диван полигоном в угол, float к ТВ), DFS Holodeck — только периферия; hard-проверки по шкалам.
**Прод-ядро**: план [[prod-layout-engine]] — кандидаты → hard → beam search → скоринг →
top-K с объяснениями; спека `../guides/layout-engine-spec.md`; Э0 — добыча правил из
ProcTHOR/Infinigen (лицензии чистые) + clean-room NC. Clean-room обязателен: NC-код не копируем.

**Tier 2:** ../domain/occupancy-rules.md · ../guides/layout-engine-spec.md
