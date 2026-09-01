---
tier: 1
topic: mesh-pipeline
scope: 3D-меши товаров — генерация, приёмка, ориентация
tier2: "../domain/viz-fidelity-playbook.md"
updated: 2026-09-01
importance: high
source: manual
status: working
source_of_truth: canonical
last_verified: 2026-09-01
---

# Конвейер 3D-мешей — Tier 1 сводка

**Зачем:** планировщик и 3D-квартиры. **Генератор — свой Hunyuan3D 2.1 на SaladCloud**
(ADR-0131; fal/Trellis выведены). Код — `tools/scout/salad/`.

**Объём:** полный пул — 11 631 товар (владелец 01.09, `plans/mesh-bulk-salad-hunyuan.md`);
≈4 900 — подмножество отбора ADR-0131, не путать. Очередь — **1503 задания** (1465 SKU, seeds
развёрнуты; счёт один — `ssh_run.plan_jobs`), первыми демо flat215.
**Приёмка:** `mesh_gate.py` → `mesh_gate_pbr.py` → `web_ready`. **Ориентация:** ADR-0129, orient-v2.

**Готовность/резерв — ADR-0134** (`mesh_ready.py`, `reserve.py`, `heal_policy.py`).
**Вход** — RGBA-вырезка (`hybrid_mask.py`, ADR-0133), фото `coalesce(image_url_hd, image_url)`
(ADR-0136).
**РЕМОНТ ОТМЕНЁН (ADR-0143):** везде оригинал `model.glb`; `apply_repairs.py` — чистая приёмка
(вердикт + очередь перегона). **Цвет — [[mesh-color]]** (ADR-0145): рычаг только на входе.
Показ `/test/mesh-pilot10/`, образ `cu124-baked` (ADR-0137); конвейер `batch_show.py`: разбор
пачки идёт ФОНОМ (ноды не ждут), `drain.sh` не тянет уже скачанное и публикует каталог
атомарно, группа гасится до финального drain.

**Пул нод — ADR-0142** (`ssh_run.py`): супервизор добирает прогретые ноды на ходу, обрыв
возвращает задание в очередь. Ленты замен в `demo-data.json` без `sid` не прогоняются.

**Здоровье нод — ADR-0146** (`node_health.py`): вина по ТЕКСТУ ошибки (сеть ноды → в очередь +
счётчик; 404/`flat_shape` → терминально, счётчик в ноль; timeout → повтор без обвинения);
3 подряд по вине ноды → снятие + `reallocate`. Счётчик и бюджет пересадок — в файле под flock
(пачка = новый процесс). Пропущенное курсором → спул `mesh-retry-queue.jsonl`.

Цены/квоты Salad и грабли сборки — ADR-0132/0137/0142, [[lessons]].

**Tier 2:** `../domain/viz-fidelity-playbook.md` · планы `mesh-bulk-salad-hunyuan`,
`mask-quality-rgba-contract`, `mesh-node-health-breaker` · ADR-0129…0134, 0146.
