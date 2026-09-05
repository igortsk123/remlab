---
tier: 1
topic: mesh-owner-audit
scope: Ручная приёмка мешей владельцем — страница /lab/mesh-audit, переделки, партии моделей
tier2: "../plans/mesh-owner-audit.md"
updated: 2026-09-05
importance: high
source: manual
status: working
source_of_truth: canonical
last_verified: 2026-09-05
review_after: 2026-12-05
---

# Ручная приёмка мешей владельцем — Tier 1 сводка

**Что:** `/lab/mesh-audit?page=N` — 20 карточек на страницу, одна на товар (текущий меш),
постер → 3D по клику, одна кнопка «переделать». Вход — кука `/lab/mesh-review`
(`lib/mesh-review/auth.ts`). Владелец 05.09: 3D, не картинки; переделка — в ОБЩУЮ очередь;
**2 ручные переделки на товар за всё время** (авто-перегон не считается); прогресс
«просмотрено» считать; исходники на DEV не удалять.

**Прод** (`db/schema.ts`: `mesh_audit_items` read-model, `mesh_audit_decisions` append-only,
`mesh_audit_batches`): клик = транзакция с `for update` (`lib/mesh-audit/repo-decisions.ts`);
правила `lib/mesh-audit/rules.ts` — 409 устаревшей вкладке, лимит, `(sku, попытка)` уникален.
Ручки `app/api/lab/mesh-audit/*`, страница `app/lab/mesh-audit/page.tsx`, карточка
`components/lab/MeshAuditCard.tsx` (GLB — только по клику), model-viewer —
`public/vendor/model-viewer.min.js`. Тесты — `tests/unit/mesh-audit.test.ts`.

**DEV-мост** `tools/scout/mesh_audit_sync.py --tick` (крон, минута, свой lock): решение →
одной транзакцией вердикт поколению, ревизия `owner_reject`/`replace_needed` при CAS «текущее =
отвергнутое», отвязка товара (`rejected`), sidecar `owner_reject.json`, инбокс
`mesh_rework_requests`; курсор — после успеха; ACK обратно (`applied → queued → done | blocked`).

**Партии** — `tools/scout/mesh_audit_publish.py` (свой lock): 200 товаров ≈ 1,5 ГБ ≈ 12 мин;
состав — с прода; жёсткие ссылки в `~/.cache` → `releases/<token>.staging` → манифест → `mv` →
`active` → прежняя `retiring` → удаление через 10 мин ТОЛЬКО под
`/opt/remlab/test/mesh-audit/releases/`. Порог диска `свободно − партия − 0,5 ≥ 7 ГБ`. Кэш
`/test/mesh-audit/*` — `caddy/Caddyfile`. Постеры — `tools/scout/mesh_audit_posters.py`.

**Очередь:** «принято, ждёт сборки очереди» до `--build-queue` ([[mesh-pipeline]] § старт волны).

**Tier 2:** `../plans/mesh-owner-audit.md` (там же — итоги двух аудитов Codex).
