---
tier: 1
topic: stablegen-paint
scope: Покраска мешей v3 — этапы, код, статус
tier2: "../plans/paint-photo-fill-01.md"
updated: 2026-11-23
importance: high
source: manual
status: working
source_of_truth: canonical
last_verified: 2026-11-20
review_after: 2026-12-05
---

# Покраска мешей — конвейер v3 (Tier 1)

**Канон — блок «Как сейчас» в начале `plans/paint-photo-fill-01.md` (ADR-0463/0464/0465, владелец TG 1679).**
Описывать конвейер владельцу, в бриф, советнику — только по нему; отменённое не упоминать.

## Этапы
1. **Форма** — TRELLIS.2 по одному фото фида (Salad 5060 Ti, тяжёлые → 5090). Краска TRELLIS не используется.
2. **Ш0 приёмка формы** — правила `tools/scout/salad/render/form_checks.py` + `form_gate.py` (сам после `tools/ops/forms_render.py --accept`).
3. **03 части** — PartLLM (мягкая), SegviGen (фасады, проба); P3-SAM — эталон (ADR-0460).
4. **04 камера** — силуэт формы ↔ маска фото (`tools/scout/salad/trellis/pose_fit.py`, `camera_check.py`).
5. **06 фото на форму** — проекция камерой 04 на UV (`tex_visible.py`, Lanczos, подгонка регистрации).
6. **Ш8 UltraTex** — выключен по умолчанию (ADR-0466), только выключатель для узорной обивки.
7. **07 заливка** (`tools/scout/salad/trellis/tex_fill.py`) — видимое с фото; невидимое — тон группы материала + зерно фото,
   вид невидимых сторон — по типу (паспорт `paint_policy`, `plans/type-rules-code-01.md`); затем шов (ADR-0465). Канон этапов — `plans/paint-photo-fill-01.md` § «Как сейчас».
8. **Мерки** — строгая доля прошедших, check 07 по итоговой текстуре, 30 известных 3D-моделей.

## Деньги и узкие места
06+07 — Salad CPU ≈$0,0003/товар; форма ≈$0,007; UltraTex ≈$0,01. Узкое место — наши ядра → P-067: каждая задача сперва
«Salad или ядра?»; срез кода на Salad = локально (ленивые импорты — в срез, ImportError = отказ).

## Открытое
m4 (ветка `t187/pipeline-1122`): полоса стула, пятна шкафа/комода, «мало блоков → ровный тон» (ваза),
UltraTex выкинут при `ut_align` uncertain (4/29), L части с ~2 % известного; торшеры; форма → авто-перегенерация
(TG 1796); z-буфер в 04. Уроки 868–869.

## StableGen — архив (до 20.11)
Был основным до ADR-0455 (`tools/scout/stablegen/`, ≈$0,07/товар); дефекты — `plans/mesh-type-rules-01.md`.

**Tier 2:** `../plans/paint-photo-fill-01.md` · `../domain/viz-fidelity-playbook.md` · [[mesh-pipeline]].
