---
tier: 1
topic: pipeline-order
scope: Порядок конвейера — от фида до расстановки
tier2: "../domain/pipeline-order-details.md"
updated: 2026-11-13
importance: high
source: manual
status: working
source_of_truth: canonical
last_verified: 2026-11-12
review_after: 2026-12-05
---

# Порядок конвейера — Tier 1 сводка

**Этап зависит только от предыдущих** (владелец 29.08).

| # | Этап | Чем | На выходе (замер 11.10) |
|---|---|---|---|
| 1 | Фиды → каталог (до него `drawing_dims --cache-only`; кэш негоден → СТОП ночи) | `load3.py` | 22 075 (активных 20 382) |
| 2 | Обогащение GPT: роль, функция, **стиль**, качество | `enrich.py`, `enrich_bridge.py` | — |
| 3 | **Отбор**: наличие, живое фото, цена, обогащение, `quality ≥ 0.65` (`enrich_bridge.py`, `candidates.py`) | `slot_contract.py` | **≈14 360** |
| 4 | **Обрезка фото** | `cutout_sync.py` | вердикт: ok · collage · bad_cutout · tiny_object · unknown |
| 5 | **Очередь мешей** — годное после обрезки, минус мягкий декор | `mesh_queue.demand_from_cut_pool` | **4 669** |
| 6 | Генерация → приёмка → ориентация → «меш есть»; прогон ПОСЛЕ стилей — [[mesh-run]] | `salad/*`, `mesh_ready.py` | — |
| 7 | **Сборка сетов** по стилям; «меш готов» — только при `MESH_GATE_PHASE` `hard_new`/`rolling`/`full` (`mesh_ready.py:gate_active`) | `compose2.py` | 126 комплектов |
| 8 | Судья (по команде, не в ночи): выбивающиеся предметы → замена из запасных | `judge.py` | — |
| 9 | Расстановка под планировку | солвер | сцены — `tools/scout/acceptance-scenes.json` (12.11: 277) |

**Стыки (ADR-0272):** `tools/scout/rules/pipeline-map.json` → `tools/scout/pipeline_map.py` → `/test/pipeline/` — Tier 2.

**Этап 4 — ворота:** срезанное не войдёт в меш. **Очередь ≠ генерация:** генерим только под демо (ADR-0314).

**Банк (ADR-0318):** `bank_prepare && bank_pending && bank_promote` с одним `BANK_RUN_ID`, писатель
`bank_refresh.py` — только при целой цепочке (`tools/scout/refresh_daily.sh:bank_chain_ok`; `write_enabled` выключен) — Tier 2.
**Демо:** `flat215_demo` → `tools/scout/publish_demo.sh` (копия прежней, `--rollback`); перевыпуск туров — после, мебель
подтверждённого тура держит; придержать — файл-стоп (Tier 2).

**Комнаты:** шаги — `tools/scout/room_profile.py:CAPABILITIES`; до привязки — сторож изголовья (`orient_bed_guard`); банки, квота — Tier 2.

**13.10 (ADR-0247):** живость фото (`pool_photos`) — ДО стиля, стиль — ДО отбора и вырезки (`tools/scout/refresh_daily.sh`).

**Tier 2:** `../domain/pipeline-order-details.md` · ADR-0131/0133/0134 · [[mesh-pipeline]].
