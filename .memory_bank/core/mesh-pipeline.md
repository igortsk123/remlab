---
tier: 1
topic: mesh-pipeline
scope: 3D-меши товаров — генерация, приёмка, ориентация
tier2: "../domain/viz-fidelity-playbook.md"
updated: 2026-09-03
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
`draft_render.FIXTURE_MESH`. Приёмник, добор нод и здоровье — ADR-0159/0142/0146.

**Модели в образе — ADR-0168/0173:** DINOv2 и веса покраски читаются С ДИСКА, в интернет нода
не ходит совсем. **Тариф — ADR-0173:** только `low`; `batch` при равном образе дал 0 мешей.
**Деньги — ADR-0174:** `money_guard.py` гасит группы по двойному условию и пишет стоп-файл,
который сильнее автостарта. **Пересадка — ADR-0170:** зомби снимает супервизор каждые 45 с.
«Running» ≠ работает — судить по `gpu_seconds`/`done`.

**Цифры 03.09:** 100 мешей/час на 20 нодах, занятость GPU 87–92%, **1.35 ₽ за меш** по
оплаченному времени. Пороги, цены тарифов и правила пересадки — в Tier 2.

**Tier 2:** `../domain/viz-fidelity-playbook.md` · планы `mesh-bulk-salad-hunyuan`,
`mesh-dino-baked` · ADR-0129…0134, 0146, 0168–0170, 0173–0174.
