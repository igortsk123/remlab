---
tier: 1
topic: mesh-pipeline
scope: 3D-меши товаров — генерация, приёмка, ориентация
tier2: "../domain/viz-fidelity-playbook.md"
updated: 2026-08-28
importance: high
source: manual
status: working
source_of_truth: canonical
last_verified: 2026-08-28
---

# Конвейер 3D-мешей — Tier 1 сводка

**Зачем:** интерактивный планировщик (юзер крутит товар) и сборка 3D-квартир.
**Генератор — только свой Hunyuan3D 2.1 на SaladCloud** (ADR-0131; fal и Trellis выведены —
запекают свет съёмки в текстуру, и $0.375/шт против ≈$0.006). Код — `tools/scout/salad/`.

**Отбор (ADR-0131):** роли слотов × ворота подбора → ≈4 900 направленных SKU из 11 631 живых.
Пилот — по сетам, 481 товар / 126 сетов (`tools/scout/mesh_pilot.py`).

**Приёмка:** `generated` → `geometry_valid` (`tools/scout/mesh_gate.py`) → `scene_ready`
(`tools/scout/mesh_gate_pbr.py`) → `web_ready`. **Ориентация (ADR-0129/0131):** orienter+flipper →
`tools/scout/mesh_front.py` → VLM qwen3-vl → человек (финален); кэш за (SKU, glb_hash).

**Готовность и спрос:** `tools/scout/mesh_ready.py` — предикат «есть годный меш» + гейт
`MESH_GATE_PHASE`; спрос — `tools/scout/mesh_queue.py` (1 в сетах / 2 кандидат / 3 резерв).
⚠️ Предикат НЕ сверяется с текущим `source_sha` — меш от старого фото считается готовым
(план `mesh-sets-substitution-pipeline`).

**Вырезка фона = вход генератора (ADR-0133).** Что срезано — того не будет в меше; что прилипло
от фона — станет геометрией. `tools/scout/salad/hybrid_mask.py` держит 95% деталей 1–2 px против
79% у чистой сети; `tools/scout/salad/components.py` снимает обрывки фона,
`tools/scout/salad/collage.py` отсеивает баннеры. Замер — `tools/scout/mask_bench/`, `/test/cutout-bench/`.
⚠️ **Открыто:** `tools/scout/salad/preprocess.py` отдаёт Hunyuan RGB на белом, а апстрим при RGB
строит маску из одних 255 — альфа гибнет перед моделью (план `mask-quality-rgba-contract`).
⚠️ Фото фида — 450 px; оригиналы только у divan.ru (22% пула).

**Стоимость и грабли сборки — ADR-0132** (цены Salad, квоты, лимит образа) и [[lessons]].

**Tier 2:** `../domain/viz-fidelity-playbook.md` · планы `mesh-bulk-salad-hunyuan`,
`mesh-queue-orientation`, `mask-quality-rgba-contract`, `mesh-sets-substitution-pipeline` ·
ADR-0129…0133.
