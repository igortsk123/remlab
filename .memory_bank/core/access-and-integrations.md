---
tier: 1
topic: access-and-integrations
scope: Интеграции/доступы — ключи, клиенты
tier2: "../domain/integrations.md"
updated: 2026-09-05
importance: high
source: manual
status: working
source_of_truth: canonical
last_verified: 2026-09-05
review_after: 2026-12-05
---

# Access & Integrations — Tier 1 сводка

> Секретов тут НЕТ — только где они. Детали — Tier 2.

## Чужие ключи на машине
Соседние проекты (sib, sing, sup2) держат ключи в своих `.env` — не наши. Прежде чем сказать
«у нас нет доступа», прогнать `node tools/access-inventory.mjs` (урок 57).

## Ключевые факты
- **Gemini:** один ключ на обе задачи; `gemini-3.1-flash-image`, `gemini-flash-latest`.
- **OpenAI (ADR-0026):** фолбэк парсинга ссылок; `OPENAI_EXTRACT_MODEL` (деф. `gpt-4o-mini`).
  Реестр моделей и цен для обогащения каталога (сверять перед прогоном, ADR-0067) —
  `../domain/catalog-enrichment.md`; `gpt-4o-mini` под картинки НЕ брать.
- **Яндекс:** Метрика `110599064`; кампанию `708745261` не трогать. [[marketing-acquisition]].

**Tier 2:** `../domain/integrations.md` — эндпоинты, форматы, env, фиды, § Codex (постоянная
сессия советника; как звать — там же). Решения — ADR-0007/0011/0012/0013/0045.

- **Vercel AI Gateway (26.08):** единственный рабочий путь к платным картинкам (прямые ключи
  OpenAI без кредитов). Эндпоинты, ключ и клиент — `../domain/integrations.md`.

- **fal.ai:** клиент `tools/scout/falmini.py`; на мешах заменён Salad (ADR-0131).

## Прочие доступы (детали — `../domain/integrations.md`)
- **Мост мешей DEV↔прод:** `MESH_REVIEW_SECRET` (кука владельца) + `MESH_REVIEW_MACHINE_TOKEN`
  (Bearer конвейера); общие для mesh-review/mesh-audit — Tier 2.
- **SaladCloud + GHCR (31.08):** GPU под меши вместо fal; орг `prodstore`/`dmodel`, ключи в
  `_secrets/`, образ только digest'ом. Грабли API — ADR-0137, [[mesh-pipeline]].
- **Гдеслон (03.09):** фиды первичны (`original_picture`, `article`, описание), API — комиссия;
  id округлён (связь по `article`), `available` бесполезен — ADR-0171.
- **Telegram `@remlabservice_bot` (03.09):** токен и chat_id в `tools/scout/.env.alert` и `/opt/remlab/catalog-watchdog/.env`.
- **Sketchfab (01.09):** заглушки ТВ/окно/дверь отобраны, все CC-BY (нужен кредит); БЛОКЕР —
  скачивание требует аккаунта, которого у агента нет.
