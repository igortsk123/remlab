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

**Вырезка = вход генератора (ADR-0133):** гибрид `tools/scout/salad/hybrid_mask.py` (95% деталей
1–2px против 79% у сети), `components.py`/`collage.py` чистят фон; вход Hunyuan — **RGBA**.
Фото: HD у 12 649 из ~19 700 (`products.image_url_hd`); у остальных потолок — 450 px фида.

**Пилот 30–31.08 (560 заданий, HD):** вход — `coalesce(image_url_hd, image_url)` (ADR-0136).
Ремонт-конвейер брака — ADR-0138: идентификация (`slab_excess`, `color_mismatch`) → reseed →
человек (`/test/mesh-repairs/`); нож плиты + цвет к фото — `tools/scout/salad/pipeline.py`,
`texture_fix.py`, `apply_repairs.py`.
Показ: `/test/mesh-pilot10/`. Образы — digest, боевой `cu124-baked` (ADR-0137); конвейер
`batch_show.py` (мультигруппы, WAVE_FIRST, детект баланса, `cull_slow_pulls`; в цикле —
«ориентация»+«топ-вью»+паблиш). Вид сверху — план `topview-from-mesh` (`topview_render.py`).

**Пул нод и учёт заданий — ADR-0142** (`ssh_run.py`): супервизор добирает прогретые ноды по ходу
прогона (id инстанса, не порт), обрыв возвращает задание в очередь, курсор двигается на подряд
закрытые (`RUN_SUMMARY`), прогресс — `tools/scout/mesh-run-progress.jsonl`, стенд `tests_pool.py`.
31.08 приоритет волны — 34 товара демо flat215 (ленты замен в `demo-data.json` идут БЕЗ `sid`,
поэтому не прогоняются — задача генератору демо).

**Цены Salad, квоты, грабли сборки — ADR-0132/0137/0142** и [[lessons]].

**Tier 2:** `../domain/viz-fidelity-playbook.md` · планы `mesh-bulk-salad-hunyuan`,
`mask-quality-rgba-contract` · ADR-0129…0134.
