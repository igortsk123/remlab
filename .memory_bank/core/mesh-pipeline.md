---
tier: 1
topic: mesh-pipeline
scope: 3D-меши товаров — генерация, приёмка, ориентация
tier2: "../domain/viz-fidelity-playbook.md"
updated: 2026-08-31
importance: high
source: manual
status: working
source_of_truth: canonical
last_verified: 2026-08-31
---

# Конвейер 3D-мешей — Tier 1 сводка

**Зачем:** планировщик и 3D-квартиры. **Генератор — свой Hunyuan3D 2.1 на SaladCloud**
(ADR-0131; fal/Trellis выведены). Код — `tools/scout/salad/`.

**Отбор — ADR-0131** (≈4 900 SKU из 11 631; `tools/scout/mesh_pilot.py`). **Приёмка:**
`mesh_gate.py` → `mesh_gate_pbr.py` → `web_ready`. **Ориентация:** ADR-0129 → план orient-v2.

**Готовность/резерв/замена — ADR-0134** (`mesh_ready.py`, `reserve.py`, `heal_policy.py`,
`/test/set-changes/`); покрытие резерва 28.08 — 0%, дефицит 803.

**Вырезка = вход генератора (ADR-0133):** гибрид `tools/scout/salad/hybrid_mask.py` (95% деталей 1–2px
против 79% у сети), `components.py`/`collage.py` чистят фон и баннеры; вход Hunyuan — **RGBA**.
Замер — `tools/scout/mask_bench/`.
Фото: HD у 12 649 из ~19 700 (`products.image_url_hd`, XML API Гдеслона); у остальных потолок — 450 px фида.

**Пилот 30–31.08 (560 заданий, HD):** вход — `coalesce(image_url_hd, image_url)` (ADR-0136,
эксперименты 2/2: хвосты/плиты — от бедного 450px). Ремонт-конвейер брака — ADR-0138:
идентификация (`slab_excess` ×1.15, `color_mismatch`) → reseed → срез-кандидат → человек
(`/test/mesh-repairs/`); нож плиты v9 + закраска кромки + цвет к фото — `tools/scout/salad/
pipeline.py`, `texture_fix.py`, `apply_repairs.py` (REPAIR_VERSION, чанки ≤6, кэш приёмки).
Показ: `/test/mesh-pilot10/` (страницы по 10, lazy GLB, вырезка в карточке, кандидат замещает
оригинал). Образы — только digest, боевой `cu124-baked` (веса внутри, ADR-0137); конвейер
`batch_show.py`: мультигруппы SALAD_GROUP через запятую, WAVE_FIRST=1 (волна лечения до
основной очереди), детект «кончился баланс». Провенанс: source.jpg+input.png+cutout.png в
комплекте каждой версии. Вид сверху из мешей для планировщика — план `topview-from-mesh`
(`orient_run.py` → orientation_state, `topview_render.py`, тест `/test/topview-test/`).

**Цены Salad, квоты, грабли сборки — ADR-0132/0137** и [[lessons]].

**Tier 2:** `../domain/viz-fidelity-playbook.md` · планы `mesh-bulk-salad-hunyuan`,
`mask-quality-rgba-contract` · ADR-0129…0134.
