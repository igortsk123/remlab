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

**Зачем:** интерактивный планировщик и сборка 3D-квартир.
**Генератор — только свой Hunyuan3D 2.1 на SaladCloud** (ADR-0131; fal и Trellis выведены —
запекают свет съёмки в текстуру, $0.375/шт против ≈$0.006). Код — `tools/scout/salad/`.

**Отбор (ADR-0131):** роли слотов × ворота подбора → ≈4 900 SKU из 11 631 живых; пилот 481
(`tools/scout/mesh_pilot.py`). **Приёмка:** `geometry_valid` (`tools/scout/mesh_gate.py`) →
`scene_ready` (`tools/scout/mesh_gate_pbr.py`) → `web_ready`. **Ориентация (ADR-0129):** orienter →
`tools/scout/mesh_front.py` → VLM → человек (финален).

**Готовность, резерв, замена (ADR-0134):** готов = принятая ревизия ТЕКУЩЕГО фото + решённая
ориентация той же ревизии (`tools/scout/mesh_ready.py`). Резерв — покрытие занятых слотов по
`alternates` (`tools/scout/reserve.py`, 2/3/1), дефицит → очередь. Замена — по жёсткой причине,
карантин 14д, лимит 1/сет/сутки, журнал (`tools/scout/heal_policy.py`); пересчёт сцен точечный
(`tools/scout/resolve_affected.py`), изменения — `/test/set-changes/`. Пригодность фото —
`tools/scout/photo_fit.py`; ворота общие для сборки и лечения (`tools/scout/slot_contract.py`).
Покрытие резерва 28.08 — 0%, дефицит 803.

**Вырезка = вход генератора (ADR-0133).** Что срезано — того не будет в меше; что прилипло от
фона — станет геометрией. `tools/scout/salad/hybrid_mask.py` держит 95% деталей 1–2 px против 79%
у чистой сети; `tools/scout/salad/components.py` снимает обрывки фона,
`tools/scout/salad/collage.py` отсеивает баннеры. Вход Hunyuan — **RGBA**, не RGB на белом
(апстрим при RGB строит маску из одних 255). Замер — `tools/scout/mask_bench/`, `/test/cutout-bench/`.
⚠️ Фото фида — 450 px; оригиналы только у divan.ru (22% пула).

**Цены Salad, квоты, грабли сборки — ADR-0132** и [[lessons]].

**Tier 2:** `../domain/viz-fidelity-playbook.md` · планы `mesh-bulk-salad-hunyuan`,
`mask-quality-rgba-contract` · ADR-0129…0134.
