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

**Объём:** полный пул — 11 631 товар (`plans/mesh-bulk-salad-hunyuan.md`); ≈4 900 —
подмножество отбора ADR-0131, не путать. Очередь — см. ADR-0153.
**Приёмка:** `mesh_gate.py` → `mesh_gate_pbr.py` → `web_ready`. **Ориентация:** ADR-0129, orient-v2.

**Вход** — RGBA-вырезка (`hybrid_mask.py`, ADR-0133/0136). Готовность/резерв — ADR-0134.
**РЕМОНТ ОТМЕНЁН (ADR-0143):** везде оригинал `model.glb`. **Цвет — [[mesh-color]]** (ADR-0145).
Показ `/test/mesh-pilot10/`; конвейер `batch_show.py`: разбор пачки ФОНОМ (ноды не ждут),
`drain.sh` не тянет скачанное и публикует каталог атомарно, группа гасится до финального drain.
**Выкатка кода на ноды — ADR-0154:** слой поверх боевого образа (`tools/scout/salad/Dockerfile.code`)
+ НОВАЯ группа (PATCH образа молчит); боевая `mesh-gates-a`, откат `mesh-run10`.
**Порядок очереди — ADR-0153:** `tools/scout/rules/mesh-priority.json` + `tools/scout/mesh_priority.py`;
ярусы: закреплённые → демо → сеты → мебель → свет/декор, в сетах — стоимость достройки КОМПЛЕКТА.
Очередь 11 704. **Небелый фон фото — ADR-0155:** не блокирует, метка «на проверку».

**Пул нод — ADR-0142** (`ssh_run.py`): супервизор добирает прогретые ноды на ходу, обрыв
возвращает задание в очередь.

**Здоровье нод — ADR-0146** (`node_health.py`): вина по ТЕКСТУ ошибки (сеть ноды → в очередь +
счётчик; 404/`flat_shape` → терминально; timeout → повтор без обвинения); 3 подряд по вине ноды →
снятие + `reallocate`. Счётчик и бюджет — в файле под flock (пачка = новый процесс).

Цены/квоты Salad и грабли сборки — ADR-0132/0137/0142, [[lessons]].

**Tier 2:** `../domain/viz-fidelity-playbook.md` · планы `mesh-bulk-salad-hunyuan`,
`mask-quality-rgba-contract`, `mesh-node-health-breaker` · ADR-0129…0134, 0146.
