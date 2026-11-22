---
tier: 1
topic: stablegen-paint
scope: Покраска мешей v3 — этапы, код, статус
tier2: "../plans/paint-photo-fill-01.md"
updated: 2026-11-22
importance: high
source: manual
status: working
source_of_truth: canonical
last_verified: 2026-11-20
review_after: 2026-12-05
---

# Покраска мешей — конвейер v3 (Tier 1)

**Канон — блок «Как сейчас» в начале `plans/paint-photo-fill-01.md` (ADR-0463, владелец TG 1679).** Описывать конвейер
владельцу, в бриф, советнику — только по нему; отменённое не упоминать.

## Этапы (22.11)
1. **Форма** — TRELLIS.2 по одному фото фида (Salad 5060 Ti, тяжёлые → 5090). Краска TRELLIS не используется.
2. **Ш0 приёмка формы** — только автоматическими правилами (`tools/scout/salad/render/form_checks.py`, `tools/scout/rules/form-checks.json`); глаз — проверка правил.
3. **03 части** — PartLLM (мягкая), SegviGen (фасады корпусной, проба); P3-SAM — эталон (ADR-0460).
4. **04 камера** — силуэт формы ↔ маска фото (`tools/scout/salad/trellis/pose_fit.py`, `camera_check.py`); габариты карточки до позы — проба.
5. **06 фото на форму** — проекция камерой 04 на UV (cos ≥0,4); `tex_visible.py` — в ветках, не в main.
6. **Ш8 суть** — UltraTex 1024·20 красит нашу форму (ADR-0464).
7. **07 заливка** (`tools/scout/salad/trellis/tex_fill.py`) — видимое с фото; невидимое — донор по UltraTex, без зеркала (ADR-0464); шов — шаг после 07.
8. **Мерки** — строгая доля прошедших, слепая Б, 30 известных 3D-моделей, check 07.

## Где деньги и узкие места
06+07 — Salad CPU ≈$0,00024/товар; форма ≈$0,007; UltraTex ≈$0,007. Узкое место — наши ядра (очередь heavy-slot) → P-067:
каждая задача — сперва «Salad или ядра?», образ со свежим кодом по SHA (T-193/1).

## Открытое
Тени щелей на фасадах (T-194/1), торцы/верх под острым углом (Ш3б, T-195/1), ножки формы ≠ фото при IoU ✓, швы «фото | достроенное».

## StableGen — архив (до 20.11)
Был основным путём до ADR-0455: `tools/scout/stablegen/`, Qwen-Image-Edit на Salad 5090/RunPod, ≈7,3 мин и $0,07 на товар;
дефекты (малиновое, «лицо» на заду, мрамор велюра) — журнал `plans/mesh-type-rules-01.md`, профилактика `plans/paint-prevent-01.md`.

**Tier 2:** `../plans/paint-photo-fill-01.md` · ADR-0457/0459/0460/0463 · `../domain/viz-fidelity-playbook.md` · [[mesh-pipeline]].
