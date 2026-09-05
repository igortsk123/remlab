---
tier: 1
topic: mesh-owner-audit
scope: Приёмка мешей владельцем — /lab/mesh-audit
tier2: "../completed_plans/mesh-owner-audit.md"
updated: 2026-09-05
importance: high
source: manual
status: working
source_of_truth: canonical
last_verified: 2026-09-05
review_after: 2026-12-05
---

# Ручная приёмка мешей владельцем — Tier 1 сводка

**Что:** `/lab/mesh-audit?page=N` — 20 карточек на страницу, одна на МОДЕЛЬ (представитель
семейства, «+N вариантов», ADR-0196), постер → 3D по клику, «переделать» и «отменить».
Вход — ссылка с ключом (ADR-0197, кода не присылать). Владелец 05.09: 3D, не картинки;
переделка — в ОБЩУЮ очередь; **2 ручные переделки на товар за всё время**; прогресс
«просмотрено» считать; исходники не удалять; «есть 3D» — по sku партии (урок 421).

**Прод** (`db/schema.ts`: `mesh_audit_items`, `mesh_audit_decisions` append-only,
`mesh_audit_batches`): клик = транзакция (`lib/mesh-audit/repo-decisions.ts`); правила
`lib/mesh-audit/rules.ts` — 409 устаревшей вкладке, лимит, `(sku, попытка)` уникален.
Ручки `app/api/lab/mesh-audit/*`, страница `app/lab/mesh-audit/page.tsx`, карточка
`components/lab/MeshAuditCard.tsx` (GLB — только по клику), model-viewer —
`public/vendor/model-viewer.min.js`. Тесты — `tests/unit/mesh-audit.test.ts`.

**DEV-мост** `tools/scout/mesh_audit_sync.py --tick` (крон, минута, свой lock): решение →
одной транзакцией вердикт поколению, ревизия `owner_reject`/`replace_needed` при CAS, отвязка
товара, sidecar `owner_reject.json`, инбокс `mesh_rework_requests`; курсор — после успеха; ACK
обратно (`applied → queued → done | blocked`); отмены — своим курсором.

**Партии** — `tools/scout/mesh_audit_publish.py` (свой lock): 200 товаров ≈ 1 ГБ ≈ 6 мин;
состав — с прода, sku партии → прод; жёсткие ссылки в `~/.cache` → `releases/<token>.staging` →
манифест → `mv` → `active` → прежняя `retiring` → удаление через 10 мин ТОЛЬКО под
`/opt/remlab/test/mesh-audit/releases/`. Порог диска ≥ 7 ГБ. Кэш
`/test/mesh-audit/*` — `caddy/Caddyfile`. Постеры — `tools/scout/mesh_audit_posters.py`.

**Очередь:** «принято, ждёт сборки очереди» до `--build-queue` ([[mesh-pipeline]] § старт волны).

**Tier 2:** `../completed_plans/mesh-owner-audit.md`.
