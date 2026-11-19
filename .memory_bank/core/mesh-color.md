---
tier: 1
topic: mesh-color
scope: Цвет мешей — диагноз, мерка, рычаги
tier2: "../domain/viz-fidelity-playbook.md"
updated: 2026-11-19
importance: high
source: manual
status: working
source_of_truth: canonical
last_verified: 2026-11-19
review_after: 2026-12-05
---

# Цвет мешей — Tier 1 сводка

**Диагноз (191 модель, 01.09).** Врёт СВЕТЛОТА, не оттенок: хрома ±3/255, |ΔL|>40 у 26% моделей; бьёт по однотонным серым.

**Чем НЕЛЬЗЯ** (ADR-0145): промптом; чисткой фото (`tools/scout/salad/photo_color.py`); обратным делением альбедо; перегоном с другим seed.

Свой seed/CFG покраски — только опытные поля `_paint_seed`/`_paint_cfg` (`tools/scout/salad/pipeline.py`; ADR-0145).

**Мерка.** Рендер БЕЗ света (`UNLIT=1`, `tools/scout/mesh_render.py`) против фото, разница в стопах + гейт на коллапс (чёрный: `tools/scout/salad/color_o2.py:COLLAPSE_Y`);
знак совпал с 43 слепыми отметками в 89% (`archive/evidence/owner-marks-mesh-color-0109.txt`).

**CAL (13.11, T-49):** поправка светлоты видов до запекания `tools/scout/salad/mv_color_cal.py` — влита, в боевых группах выключена.

**ADR-0185:** часть промаха — свет на sRGB (`SCENE3D_LIGHT_LINEAR=1`); без карты — `meshes.ts` `fallbackMeshColor`.

**Рычаги.** Перепокраска формы (paint = 42% задания) — **`shape.glb` живёт ≤14 сут, кроме очереди перегона/перекраски
(`tools/scout/rules/dev-disk.json`), у прочих — только перегон**. **К8:** отложен; `tools/scout/mesh_color_check.py` метит, `room_bindings.py`
прячет вариант семьи на чужом меше; дальше (TG 1614) — правка только сильно расходящихся с фото.
Плюс сдвиг экспозиции входа (`photo_color.shift_exposure`, `tools/scout/salad/exposure_plan.py`, `EV_MAX` ±0.45; покраска реагирует ~0.8 ст. на ступень).

**Подкраска `sku.tint` (mcg-v3):** опорная часть `tools/scout/mesh_color_check.py:anchor_part` (урок 710). Перекраска — ADR-0445; у семейств
с tint — только через гейт по всем вариантам `tools/scout/salad/recolor_variants_gate.py` (ADR-0446, урок 727), запись на живое —
`tools/scout/salad/recolor_window.py`, откат `recolor_rollback.sh`.
**«Серая крышка» (ADR-0436, 0447):** детектор `tools/scout/mesh_grey_top.py` (`gt-v4`, 92/92 известных, 7 ложных из 3013) + мягкий карантин;
разметка — `tools/scout/rules/mesh-grey-top-labels.json`; детали — Tier 2 § «серая крышка». Урок 711.

**Tier 2:** `../domain/viz-fidelity-playbook.md` · [[mesh-pipeline]] · ADR-0145 ·
разбор Codex — `archive/evidence/codex-color-answer.md`.
