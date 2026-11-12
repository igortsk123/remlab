---
tier: 1
topic: mesh-pipeline
scope: 3D-меши — генерация, учёт, приёмка
tier2: "../domain/viz-fidelity-playbook.md"
updated: 2026-11-12
importance: high
source: manual
status: working
source_of_truth: canonical
last_verified: 2026-11-06
review_after: 2026-12-05
---

# Конвейер 3D-мешей — Tier 1 сводка

**Генератор — Hunyuan3D 2.1 на SaladCloud** (ADR-0131), код `tools/scout/salad/`.
Пул — [[mesh-pool]]; приёмка — [[mesh-owner-audit]]; прогон — [[mesh-run]].
**Путь меша:** вырезка (`tools/scout/salad/hybrid_mask.py`, ADR-0133/0182) → генерация →
пост-шаги пачки (`batch_show.py:post_steps`): слив приёмника → реестр → приёмка `apply_repairs.py`
(ремонт ОТМЕНЁН, ADR-0143) → привязка → чистка приёмника → прополка болванок `prune_shapes.py`
(ADR-0233) → ориентация (ADR-0129), топ-вью; семейства — при старте волны. Цвет — [[mesh-color]].

**`shape.glb`** (продукт — `model.glb`) полется у принятых (ADR-0233) и старше 14 сут (`tools/scout/rules/dev-disk.json`). Образ — GHCR.
**Ориентация:** на прод — только решённые (`tools/scout/orient_policy.py`; Tier 2 § «Ориентация мешей»).

**Учёт поколений (ADR-0188…0191).** Физический меш = строка `mesh_generations`; ревизия держит
`current_generation_key` (`tools/scout/salad/ingest_registry.py`), статус владельца живёт, пока
поколение то же (тест `tools/scout/tests/mesh_owner_audit_dbtest.py`).

**Один меш на модель (ADR-0196).** Цвет/ткань — варианты семейства
(`tools/scout/mesh_family.py`, `mesh_family_rep` липкий); в очередь встаёт представитель,
варианты получают его меш и готовность (`tools/scout/mesh_bind.py`). `products.mesh_uri` =
`file://`-путь поколения — ссылка у каждого товара; отказ владельца → товар без меша (ADR-0190).

**Очередь и старт волны.** Снимок пишет `mesh_priority.py --build-queue` атомарно, курсор —
`<снимок>.progress.json`; пересборка — только `tools/scout/mesh_wave_start.sh`;
профиль демо — `MESH_QUEUE_PROFILE=demo` (ADR-0241). Подробно — [[mesh-run]].

**Публикация на прод (ADR-0243):** `mesh_publish.py` перед сборкой витрины; индекс
`/test/mesh-pilot10/mesh-index.json` пересобирается по серверу. Весь склад (26 ГБ) не выкладываем.

**Автобрак:** `generated` = годный (`tools/scout/mesh_ready.py`); обрезка чужих кусков на ноде выключена
(`tools/scout/salad/pipeline.py` `ALIEN_CUT=0` — только метка).

**Tier 2:** `../domain/viz-fidelity-playbook.md` · планы `mesh-owner-audit`, `mesh-bulk-salad-hunyuan`,
`mesh-pool-hardening` · ADR-0129…0134, 0146, 0168–0178, 0182, 0188–0197.
