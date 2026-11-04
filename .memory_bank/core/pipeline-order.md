---
tier: 1
topic: pipeline-order
scope: Порядок конвейера — от фида до расстановки
tier2: "../domain/pipeline-order-details.md"
updated: 2026-11-04
importance: high
source: manual
status: working
source_of_truth: canonical
last_verified: 2026-10-11
review_after: 2026-12-05
---

# Порядок конвейера — Tier 1 сводка

Зафиксирован владельцем 29.08: **каждый этап зависит только от предыдущих** (раньше спрос на
меши считался от сетов, а сеты ждали мешей — петля).

| # | Этап | Чем | На выходе (замер 11.10) |
|---|---|---|---|
| 1 | Фиды → каталог (до него `drawing_dims --cache-only`; кэш негоден → СТОП ночи) | `load3.py` | 22 075 (активных 20 382) |
| 2 | Обогащение GPT: роль, функция, **стиль**, качество | `enrich.py`, `enrich_bridge.py` | — |
| 3 | **Отбор**: наличие, живое фото, цена, обогащение, `quality ≥ 0.65` (`enrich_bridge.py`, `candidates.py`) | `slot_contract.py` | **≈14 360** |
| 4 | **Обрезка фото** | `cutout_sync.py` | вердикт: ok · collage · bad_cutout · tiny_object · unknown |
| 5 | **Очередь мешей** — годное после обрезки, минус мягкий декор | `mesh_queue.demand_from_cut_pool` | **4 669** |
| 6 | Генерация → приёмка → ориентация → «меш есть»; прогон ПОСЛЕ стилей — [[mesh-run]] | `salad/*`, `mesh_ready.py` | — |
| 7 | **Сборка сетов** по стилям; «меш готов» — только при `MESH_GATE_PHASE` `hard_new`/`rolling`/`full` (`slot_contract.py:61`) | `compose2.py` | 126 комплектов |
| 8 | Судья: выбор лучших вариантов | `judge.py` | — |
| 9 | Расстановка под планировку | солвер, `acceptance-scenes.json` | 272 сцены |

**Стыки (ADR-0272):** пороги — `tools/scout/rules/pipeline-map.json`, расчёт — `tools/scout/pipeline_map.py`, страница `/test/pipeline/`;
тревога при смене состояния, напоминание жёлтый/72 ч, красный/24 ч.

**Этап 4 — ворота, а не косметика:** что срезано с фото, того не будет в меше; что прилипло от
фона — станет геометрией. Мягкий декор режется тоже (нужен витрине), но на меши не идёт.

**Очередь ≠ генерация:** генерим только под демо (ADR-0314).

**Банк комплектов (ADR-0318):** ночью кандидат → ожидание по ячейке → `bank_promote` → писатель `bank_refresh.py` (выключен до готовых ячеек) — Tier 2.

**13.10 (ADR-0247):** живость фото (`pool_photos`) — ДО стиля, стиль — ДО отбора и вырезки (`tools/scout/refresh_daily.sh`).

**Tier 2:** `../domain/pipeline-order-details.md` · `tools/scout/refresh_daily.sh` ·
ADR-0131/0133/0134 · [[mesh-pipeline]].
