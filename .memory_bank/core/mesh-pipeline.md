---
tier: 1
topic: mesh-pipeline
scope: 3D-меши товаров — генерация, учёт поколений, приёмка, ориентация
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
код `tools/scout/salad/`. Пул, тарифы, приёмник, деньги — [[mesh-pool]]. Ручная приёмка
владельцем и переделки — [[mesh-owner-audit]].
**05.09:** 1490 моделей на 1291 товар; очередь 11 704 (`tools/scout/mesh-queue-v1.json`).

**Путь меша:** вырезка (`tools/scout/salad/hybrid_mask.py`, ADR-0133/0182) → генерация →
приёмка `tools/scout/salad/apply_repairs.py` (ремонт ОТМЕНЁН, ADR-0143; авто-перегон seed+1
один раз) → реестр → привязка → ориентация orient-v2 (ADR-0129). Цвет — [[mesh-color]];
небелый фон — метка (ADR-0155). Показ — `/test/mesh-pilot10/`; модели с ДИСКА образа
(ADR-0168/0173).

**Учёт поколений (05.09).** Физический меш = строка `mesh_generations`
(`tools/scout/008-mesh-owner-audit.sql`); ревизия `asset_revisions` держит
`current_generation_key` — «текущее» по времени файла, не по алфавиту
(`tools/scout/salad/ingest_registry.py`). Человеческий статус ревизии живёт, пока текущее
поколение то же; перегон → `generated`. `tools/scout/mesh_bind.py` привязывает только
текущее; отвергнутое → товар без меша (`rejected`), старые попытки не воскрешаются.
`tools/scout/mesh_ready.py` — ориентация того же файла (`glb_sha`). Тест —
`tools/scout/tests/mesh_owner_audit_dbtest.py` (одноразовая база в `remlab-devdb`).

**Очередь и старт волны.** Живой снимок не редактируется
(`tools/scout/rules/mesh-priority.json` §identity). `tools/scout/mesh_priority.py
--build-queue` пишет снимок атомарно, переделки — с первым свободным seed; курсор конвейера —
`<снимок>.progress.json` (`tools/scout/salad/batch_show.py`). Пересборка — только
`tools/scout/mesh_wave_start.sh`; бегущий конвейер при этом не трогают.

**Tier 2:** `../domain/viz-fidelity-playbook.md` · планы `mesh-owner-audit`,
`mesh-bulk-salad-hunyuan`, `mesh-pool-hardening` · ADR-0129…0134, 0146, 0168–0178, 0182.
