---
tier: 1
topic: access-and-integrations
scope: Интеграции/доступы — где ключи, эндпоинты, форматы, клиенты в коде
tier2: "../domain/integrations.md"
updated: 2026-08-01
importance: high
source: manual
status: working
source_of_truth: canonical
last_verified: 2026-07-21
review_after: ""
---

# Access & Integrations — Tier 1 сводка

> Секретов тут НЕТ — только где они. Детали — Tier 2.

## Реестр
| Интеграция | Статус | Задача | Ключи (где) | Код |
|---|---|---|---|---|
| Google Gemini | ⚠️ КЛЮЧ МЁРТВ 2026-08-01 — пересоздать; проверить прод | картинки+анализ | `GEMINI_API_KEY` | `lib/providers/gemini.ts` |
| OpenAI | ✅ соседский | GPT-5.1 тексты; gpt-image-2 витрина | `_secrets/ACCESS.md` | ads-watchdog; scout |
| PostHog | код есть, прод no-op (ADR-0012) | аналитика+ошибки | `POSTHOG_KEY` не задан | `lib/analytics.ts` |
| Гдеслон | доступ ✅ 14 магазинов (ADR-0042) | фиды→каталог, /go/ реф | `GDESLON_*` в `.env` | кода нет; план `gdeslon-catalog` |
| imagor | активен (ADR-0013) | сжатие картинок, internal | ключей НЕТ (unsafe) | `lib/images/compress.ts` |
| GHCR/CI | авто-деплой ✅ (arm64) | образы + деплой | `GITHUB_TOKEN`; SSH `remlab_ci_deploy` | GitHub Actions |
| Яндекс (WS/Директ/Метрика) | доступ ✅ | реклама/аналитика | `_secrets/ACCESS.md` (вне git) | кода нет, curl |
| Лид-канал П7 | скелет до токенов | заявки+диалог | `LEADS_*` в `/opt/remlab/.env` — `[[leads]]` | `lib/leads/*` |
| YooKassa | код-скелет, БЕЗ ключей (К5) | оплата 60₽ визуализации | ключи не заданы | `lib/payments/yookassa.ts` |
| fal.ai | активен ✅ | NB2/Seedream/Flux/SAM2/LaMa per-request | `FAL_KEY` (mltest/.env) | scout/mltest |
| РФ-прокси | ✅ ADR-0031 | фолбэк parse-link; квота 1 ГБ | `PARSE_PROXY_URLS`; креды — VPN `_secrets/` | `lib/calc/fetch-page.ts` |

## Ключевые факты
- **Gemini:** один ключ на обе задачи; модели `gemini-3.1-flash-image` и `gemini-flash-latest`.
- **OpenAI (ADR-0026):** ИИ-фолбэк парсинга ссылок; `OPENAI_EXTRACT_MODEL` (деф. `gpt-4o-mini`).
- **Яндекс:** Метрика `110599064`; чужую кампанию `708745261` не трогать. [[marketing-acquisition]].
- **UI-иконки:** PNG 512 от владельца (Drive `1l2j65g8…`) → `public/icons/`; только `<img>` (нет sharp).

**Tier 2:** `../domain/integrations.md` (эндпоинты, форматы, env, цены). Решения — `decisions.md` (ADR-0007/0011/0012/0013).
