---
tier: 1
topic: mesh-owner-audit
scope: Приёмка мешей владельцем — /lab/mesh-audit
tier2: "../completed_plans/mesh-owner-audit.md"
updated: 2026-11-20
importance: high
source: manual
status: working
source_of_truth: canonical
last_verified: 2026-11-18
review_after: 2026-12-05
---

# Ручная приёмка мешей владельцем — Tier 1 сводка

**Что:** `/lab/mesh-audit?page=N` — 20 карточек, одна на МОДЕЛЬ (+N вариантов, ADR-0196), постер → 3D,
«переделать» и «отменить».
Вход — ссылка с ключом (ADR-0197). Переделка — в ОБЩУЮ очередь; **2 ручные переделки на товар**; счётчик
«просмотрено»; «есть 3D» — по sku партии (урок 421).

**Прод** (`db/schema.ts`: `mesh_audit_items`, `mesh_audit_decisions` — отмена удаляет строку; `mesh_audit_cancellations`, `mesh_audit_batches`): клик = транзакция
(`lib/mesh-audit/repo-decisions.ts:decide`); правила
`lib/mesh-audit/rules.ts` — 409 устаревшей вкладке, лимит, `(sku, попытка)` уникален.
Ручки `app/api/lab/mesh-audit/*`, карточка `components/lab/MeshAuditCard.tsx`; тесты `tests/unit/mesh-audit.test.ts`.

**DEV-мост** `tools/scout/mesh_audit_sync.py --tick` (крон, минута, lock): решение → одной транзакцией вердикт поколению,
ревизия `owner_reject`/`replace_needed` при CAS, инбокс `mesh_rework_requests`; ACK `applied → queued → done | blocked`.

**Партии** — `tools/scout/mesh_audit_publish.py` (свой lock): 200 товаров (`rules.ts:BATCH_SIZE`); `releases/<token>.staging` →
`active`; удаление ТОЛЬКО под `releases/`. После заливки свободно ≥ 7 ГБ (`enough_space`). Постеры — `tools/scout/mesh_audit_posters.py`.

**Комментарий к браку (ADR-0324):** `components/lab/MeshAuditVerdict.tsx`, `db/init/021-mesh-audit-comment.sql` → журнал
`mesh_decisions` (`tools/scout/mesh_decisions.py --comments`); брак без модели — снова в спрос (`bank_ready.classify`).

**Приёмка освобождает диск (ADR-0233):** принято = просмотрено и не забраковано
(`rules.ts:isAccepted`; `seen_at` сбрасывает новое поколение) → `?scope=accepted` → прополка
болванок `tools/scout/salad/prune_shapes.py:classify`; старше 14 сут (`tools/scout/rules/dev-disk.json:shape_max_age_d`)
уходит и без приёмки (при `model.glb`, не на приёмнике, ≥48 ч), кроме очереди перегона.

**Проверка мешей `/lab/mesh-check` (13.11, T-118):** «ок»/«брак» + комментарий к модели; журнал навсегда
(`db/init/035-mesh-audit-marks.sql`, `lib/mesh-audit/marks.ts`), снимок 1024 — `mesh_audit_posters.py --hd`.

**Вырезка `/lab/cutout-check` (T-104):** `db/init/039-cutout-check.sql`, заливка `tools/scout/cutout_check_sync.py`; проверка — урок 776.

**Tier 2:** `../completed_plans/mesh-owner-audit.md`.
