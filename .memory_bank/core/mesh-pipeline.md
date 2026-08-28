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

**Генератор — только свой Hunyuan3D 2.1 на SaladCloud** (ADR-0131). fal и Trellis выведены:
они запекают освещение съёмки в текстуру, в сцене со своим светом объект не пересвечивается;
на fal PBR-эндпоинт $0.375/шт против ≈$0.006 на своей карте. Код — `tools/scout/salad/`.

**Отбор (ADR-0131):** роли слотов сетов × ворота пригодности подбора (in_stock + живое фото +
`enrich_bridge.MIN_QUALITY` 0.65) → направленные роли ≈4 900 SKU. Воронка каталога 28.08:
32 347 → in_stock 19 529 → +обогащение/фото/цена 16 245 → −мёртвое фото 11 631
(`candidates-index.json`); напольных ролей 4 182.

**Пилот** (план `mesh-bulk-salad-hunyuan`): выборка ПО СЕТАМ полными комплектами — 481 товар,
531 генерация, 126 сетов из 126 целиком (`tools/scout/mesh_pilot.py`). Отвечает на «соберётся
ли живая комната», а не на «процент годных по ролям»; доля годных выйдет оптимистичнее пула.

**Приёмка — четыре ступени:** `generated` → `geometry_valid` (`tools/scout/mesh_gate.py`) →
`scene_ready` (`tools/scout/mesh_gate_pbr.py`: карты не пустые и не константные, нет запечённого
света в albedo, transmission у стекла и emissive у светильников по роли) → `web_ready` (бюджет
канваса). Пороги стартовые, калибруются на пилоте.

**Ориентация (ADR-0129/0131):** каскад orienter+flipper → `mesh_front` → VLM qwen3-vl →
человек; вердикт человека финален, кэш за (SKU, glb_hash), GLB не перезаписывается.

**Стоимость** (Salad batch, сверено по API 28.08): 4090 $0.16/ч · 5090 $0.25 · 3090 $0.09 ·
A5000 $0.09. Квота 10 реплик, лимит образа 35 ГБ сжатыми. Пул 11 631 ≈ $31–105, пилот ≈ $2–4.

**Грабли сборки — ADR-0132** и [[lessons]].

**Tier 2:** `../domain/viz-fidelity-playbook.md` · планы `mesh-bulk-salad-hunyuan`,
`mesh-queue-orientation` · ADR-0129…0132.
