---
tier: 1
topic: access-and-integrations
scope: Интеграции/доступы — ключи, клиенты
tier2: "../domain/integrations.md"
updated: 2026-08-06
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
  Реестр моделей и цен для обогащения каталога (сверять перед прогоном, ADR-0067) —
  `../domain/catalog-enrichment.md`; `gpt-4o-mini` под картинки НЕ брать.
- **Яндекс:** Метрика `110599064`; чужую кампанию `708745261` не трогать. [[marketing-acquisition]].

**Tier 2:** `../domain/integrations.md` (эндпоинты, форматы, env, фиды/наличие). Решения — ADR-0007/0011/0012/0013/0045.


**Детали разделов: Реестр → `../domain/integrations.md`**

## Codex (OpenAI CLI) — постоянная сессия-советник (16.08.2026)
- **Сессия проекта:** `01a00a62-33e2-7051-93c6-37bff5c6937e` (онбординг 16.08: прочитал CLAUDE.md, INDEX, ADR-0099…0106,
  MASTER-zones-v7, свои аудиты, карту кода; конспект — `_intake/codex-onboarding-notes.md`).
- **Как звать:** `codex exec resume 01a00a62-33e2-7051-93c6-37bff5c6937e --sandbox read-only -C /home/pakar/igor/remlab - < prompt.md`
  (промпт короткий: «что изменилось с прошлого раза (коммиты/файлы) + вопрос»). Для НЕЗАВИСИМОГО second opinion
  (когда нельзя показывать нашу гипотезу) — по-прежнему `codex exec --ephemeral`.
- Раз в несколько сводов — новый онбординг (сессия распухает/устаревает), старую архивировать (`codex archive <id>`).
- Песочница: `/etc/apparmor.d/codex-bwrap-userns` (профиль для vendored bwrap); классификатор auto-mode — правило в
  `.claude/settings.local.json` autoMode.allow.
