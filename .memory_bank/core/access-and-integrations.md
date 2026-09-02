---
tier: 1
topic: access-and-integrations
scope: Интеграции/доступы — ключи, клиенты
tier2: "../domain/integrations.md"
updated: 2026-09-02
importance: high
source: manual
status: working
source_of_truth: canonical
last_verified: 2026-08-02
review_after: ""
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
сессия советника; с 02.09 снова отвечает — длинный структурированный промпт, `-o` в файл,
таймаут 900 с). Решения — ADR-0007/0011/0012/0013/0045.

- **Vercel AI Gateway (26.08):** единственный рабочий путь к платным картинкам (прямые ключи
  OpenAI без кредитов). Эндпоинты, ключ и клиент — `../domain/integrations.md`.

- **fal.ai:** клиент `tools/scout/falmini.py`; на мешах заменён Salad (ADR-0131).

## Прочие доступы (детали — `../domain/integrations.md`)
- **SaladCloud + GHCR (31.08):** GPU под меши вместо fal; орг `prodstore`/`dmodel`, ключи в
  `_secrets/`, образ только digest'ом. Грабли API — ADR-0137, [[mesh-pipeline]].
- **Гдеслон (26.08):** программы через shops.xml по api_token; XML-поиск только с хоста
  `api.gdeslon.ru` (www теряет параметры); API выгрузок нет.
- **Sketchfab (01.09):** модели-заглушки ТВ/окно/дверь отобраны, все CC-BY (нужен кредит).
  БЛОКЕР: скачивание требует аккаунта, которого у агента нет.
