---
tier: 1
topic: mesh-pipeline
scope: 3D-меши — генерация, учёт, приёмка
tier2: "../domain/viz-fidelity-playbook.md"
updated: 2026-09-05
importance: high
source: manual
status: working
source_of_truth: canonical
last_verified: 2026-09-05
review_after: 2026-12-05
---

# Конвейер 3D-мешей — Tier 1 сводка

**Зачем:** планировщик и 3D-квартиры. **Генератор — Hunyuan3D 2.1 на SaladCloud** (ADR-0131),
код `tools/scout/salad/`. Пул, деньги — [[mesh-pool]]; ручная приёмка — [[mesh-owner-audit]].
**05.09:** ~1 500 моделей; очередь после схлопывания вариантов ≈ 6 300 заданий.

**Путь меша:** вырезка (`tools/scout/salad/hybrid_mask.py`, ADR-0133/0182) → генерация →
приёмка `tools/scout/salad/apply_repairs.py` (ремонт ОТМЕНЁН, ADR-0143; авто-перегон seed+1
один раз) → реестр → семейства → привязка → ориентация orient-v2 (ADR-0129). Цвет —
[[mesh-color]].

**Учёт поколений (ADR-0188…0191).** Физический меш = строка `mesh_generations`
(`tools/scout/008-mesh-owner-audit.sql`); ревизия держит `current_generation_key` — «текущее»
по времени файла (`tools/scout/salad/ingest_registry.py`); человеческий статус живёт, пока
поколение то же. `tools/scout/mesh_ready.py` — ориентация того же файла (`glb_sha`). Тест —
`tools/scout/tests/mesh_owner_audit_dbtest.py`.

**Один меш на модель (ADR-0196).** Цвет/ткань — варианты семейства
(`tools/scout/mesh_family.py`, `mesh_family_rep` липкий); в очередь встаёт представитель,
варианты получают его меш и готовность (`tools/scout/mesh_bind.py`). `products.mesh_uri` =
`file://`-путь поколения — ссылка у каждого товара; отказ владельца → товар без меша (ADR-0190).

**Очередь и старт волны.** Живой снимок не редактируется
(`tools/scout/rules/mesh-priority.json`). `tools/scout/mesh_priority.py --build-queue` пишет
снимок атомарно (без вариантов), переделки — с первым свободным seed; курсор —
`<снимок>.progress.json`. Пересборка — только `tools/scout/mesh_wave_start.sh` (сироты, drain,
реестр, семейства, привязка, зелёный приёмник — до старта; пачка 2000).

**Tier 2:** `../domain/viz-fidelity-playbook.md` · планы `mesh-owner-audit`,
`mesh-bulk-salad-hunyuan`, `mesh-pool-hardening` · ADR-0129…0134, 0146, 0168–0178, 0182, 0188–0197.
