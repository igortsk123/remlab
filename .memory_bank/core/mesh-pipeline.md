---
tier: 1
topic: mesh-pipeline
scope: 3D-меши товаров — генерация, приёмка, ориентация
tier2: "../domain/viz-fidelity-playbook.md"
updated: 2026-09-02
importance: high
source: manual
status: working
source_of_truth: canonical
last_verified: 2026-09-02
---

# Конвейер 3D-мешей — Tier 1 сводка

**Зачем:** планировщик и 3D-квартиры. **Генератор — свой Hunyuan3D 2.1 на SaladCloud**
(ADR-0131). Код — `tools/scout/salad/`.

**Объём:** пул 11 631 (`plans/mesh-bulk-salad-hunyuan.md`); ≈4 900 — отбор ADR-0131, не путать.
**Приёмка:** `mesh_gate.py` → `mesh_gate_pbr.py` → `web_ready`. **Ориентация:** ADR-0129,
orient-v2. **Вход** — RGBA-вырезка (`hybrid_mask.py`, ADR-0133/0136). Резерв — ADR-0134.
**РЕМОНТ ОТМЕНЁН (ADR-0143):** везде оригинал `model.glb`. **Цвет — [[mesh-color]]** (ADR-0145).
Показ `/test/mesh-pilot10/`; `batch_show.py`: разбор пачки ФОНОМ, группа гасится до drain.
**Выкатка на ноды — ADR-0154/0157** (слой `Dockerfile.code` + НОВАЯ группа; PATCH образа молчит).
**Порядок очереди — ADR-0153:** `tools/scout/rules/mesh-priority.json`; ярусы:
закреплённые → демо → сеты → мебель → свет/декор, в сетах — стоимость достройки КОМПЛЕКТА.
Очередь 11 704. **Небелый фон — ADR-0155:** не блокирует, метка «на проверку».

**Обстановка комнаты — ADR-0162:** меши Kenney (CC0), `kit_fixtures.py`, роль→id в
`draft_render.FIXTURE_MESH`. **Приёмник — ADR-0159:** чистка только ПОСЛЕ записи в базу;
`drain.sh` сверяет ОБЪЁМ. **Пул — ADR-0142**: добор нод на ходу, обрыв возвращает задание.
**Здоровье нод — ADR-0146**: вина по ТЕКСТУ ошибки, 3 подряд → `reallocate`; бюджет под flock.

**Веса в образе — ADR-0168:** DINOv2 запечена (`Dockerfile.dino`), в интернет нода не ходит;
26.43 ГБ сжатый (лимит 35), `storage_amount` — фильтр машин, не место. **Деньги — ADR-0169:**
`money_guard.py` гасит группу после 120 нодо-минут без мешей. **Пересадка — ADR-0170:** простой
15 мин, ступени 20/40/80; зомби (`running`+`warmup_error`) снимаем, общую беду — нет; пробы
параллельны. «Running» ≠ работает — судить по `gpu_seconds`/`done`.

Цены/квоты Salad — ADR-0132/0137/0142, [[lessons]].

**Tier 2:** `../domain/viz-fidelity-playbook.md` · планы `mesh-bulk-salad-hunyuan`,
`mesh-dino-baked` · ADR-0129…0134, 0146, 0168–0170.
