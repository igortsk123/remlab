---
tier: 1
topic: access-and-integrations
scope: Интеграции/доступы — ключи, эндпоинты, клиенты
tier2: "../domain/integrations.md"
updated: 2026-08-05
importance: high
source: manual
status: working
source_of_truth: canonical
last_verified: 2026-08-02
review_after: ""
---

# Access & Integrations — Tier 1 сводка

> Секретов тут НЕТ — только где они. Детали — Tier 2.

## fal.ai (2026-08-05) — картинки и image-to-3D
`FAL_KEY` (значение — `_secrets/ACCESS.md`); баланс $9.03 на 2026-08-04. Цены и применение —
`../domain/integrations.md`. Используется в `services/room-measure/run_viz.py`.
Фото → 3D: `fal-ai/trellis` (GLB, ~56 с, ≈$0.02) и `fal-ai/hunyuan3d/v2` (~30 с). Рендера меша
на fal НЕТ — крутим сами (`tools/scout/mesh_render.py`, ADR-0060).

## Чужие ключи на машине
Соседние проекты (sib, sing, sup2) держат свои ключи в своих `.env` — НЕ наши, не трогать.
Инвентаризация: `node tools/access-inventory.mjs`. Прежде чем сказать «у нас нет доступа» —
прогнать её (урок 57).

## Ключевые факты
- **Gemini:** один ключ на обе задачи; модели `gemini-3.1-flash-image` и `gemini-flash-latest`.
- **OpenAI (ADR-0026):** ИИ-фолбэк парсинга ссылок; `OPENAI_EXTRACT_MODEL` (деф. `gpt-4o-mini`).
- **Яндекс:** Метрика `110599064`; чужую кампанию `708745261` не трогать. [[marketing-acquisition]].

**Tier 2:** `../domain/integrations.md` (эндпоинты, форматы, env, фиды/наличие). Решения — ADR-0007/0011/0012/0013/0045.


**Детали разделов: Реестр → `../domain/integrations.md`**
