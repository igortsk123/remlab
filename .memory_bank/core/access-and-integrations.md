---
tier: 1
topic: access-and-integrations
scope: Интеграции/доступы — ключи, клиенты
tier2: "../domain/integrations.md"
updated: 2026-08-28
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
Соседние проекты (sib, sing, sup2) держат свои ключи в своих `.env` — НЕ наши, не трогать.
Инвентаризация: `node tools/access-inventory.mjs`. Прежде чем сказать «у нас нет доступа» —
прогнать её (урок 57).

## Ключевые факты
- **Gemini:** один ключ на обе задачи; модели `gemini-3.1-flash-image` и `gemini-flash-latest`.
- **OpenAI (ADR-0026):** ИИ-фолбэк парсинга ссылок; `OPENAI_EXTRACT_MODEL` (деф. `gpt-4o-mini`).
  Реестр моделей и цен для обогащения каталога (сверять перед прогоном, ADR-0067) —
  `../domain/catalog-enrichment.md`; `gpt-4o-mini` под картинки НЕ брать.
- **Яндекс:** Метрика `110599064`; чужую кампанию `708745261` не трогать. [[marketing-acquisition]].

**Tier 2:** `../domain/integrations.md` — эндпоинты, форматы, env, фиды, § Codex (постоянная
сессия советника). Решения — ADR-0007/0011/0012/0013/0045.

## Vercel AI Gateway (26.08)
`https://ai-gateway.vercel.sh/v1`: `/images/edits` (`image[]`, `mask`) для `openai/gpt-image-*`;
`/chat/completions` + `modalities:['image']` для Google-картинок — `draft_render._chat_edit`.
Ключ `VERCEL_AI_GATEWAY_KEY`: `_secrets/ACCESS.md` и `/opt/remlab/.env`; клиент `gw_key()`.
Прямые ключи OpenAI без кредитов — рабочий путь только шлюз.

## fal.ai (2026-08-05 → 28.08)
Клиент `tools/scout/falmini.py`; на треке мешей заменён Salad (ADR-0131).
Модели редактирования и ограничения масок — `../domain/integrations.md` §fal.

## SaladCloud + GHCR (31.08) — GPU под меши, вместо fal
Орг `prodstore`/`dmodel`; ключи, цены, спека группы — `_secrets/ACCESS.md`, `_secrets/salad-group-create-body.json`.
Образ ТОЛЬКО digest'ом; боевой `…mesh-hunyuan:cu124-baked` (веса внутри). Все API-грабли
(curl-only/WAF, PATCH-молчание, квоты, reallocate) — ADR-0137; детали — [[mesh-pipeline]].

## Гдеслон API (26.08)
Программы: shops.xml по api_token (ежедневный `--check`); XML-поиск — только хост
api.gdeslon.ru (www теряет параметры); API выгрузок нет.
