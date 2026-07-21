---
tier: 1
topic: access-and-integrations
scope: Внешние интеграции/доступы — где ключи, какие модели/эндпоинты, форматы, клиенты в коде
tier2: "../domain/integrations.md"
updated: 2026-07-21
importance: high
source: manual
status: working
source_of_truth: canonical
last_verified: 2026-07-21
review_after: ""
---

# Access & Integrations — Tier 1 сводка

> Секретов тут НЕТ — только где они и как устроен доступ. Детали — Tier 2.

## Реестр
| Интеграция | Статус | Задача | Ключи (где) | Код |
|---|---|---|---|---|
| Google Gemini | активен ✅ | картинки + анализ фото | `GEMINI_API_KEY`: `.env.local` / прод `/opt/remlab/.env` | `lib/providers/gemini.ts` |
| OpenAI | ключ есть ✅ | GPT-5.1 тексты объявлений | `_secrets/ACCESS.md` | `infra/server/ads-watchdog/common.py` |
| PostHog | код есть, прод no-op (ADR-0012) | аналитика+ошибки | `POSTHOG_KEY` не задан | `lib/analytics.ts` |
| Гдеслон | late-binding, не блокер | партнёрки постепенно (канд. №1) | будут в `.env` | — |
| imagor | активен (ADR-0013) | сжатие картинок, internal-only | ключей НЕТ (unsafe); URL в compose | `lib/images/compress.ts` |
| GHCR/CI | частично (ADR-0011) | образы + авто-деплой | `GITHUB_TOKEN`; SSH `~/.ssh/remlab_ci_deploy` | GitHub Actions |
| Яндекс (WS/Директ/Метрика) | доступ ✅ | семантика/реклама/аналитика | `_secrets/ACCESS.md` (вне git) | кода нет, curl |
| YooKassa | код-скелет, БЕЗ ключей (К5) | оплата 60₽ визуализации | `YOOKASSA_SHOP_ID/SECRET_KEY` не заданы | `lib/payments/yookassa.ts`, webhook `app/api/pay/yookassa/webhook` |

## Ключевые факты
- **Gemini:** один ключ на обе задачи; модели `gemini-3.1-flash-image` и `gemini-flash-latest`.
- **OpenAI (ADR-0026):** ИИ-фолбэк парсинга ссылок — `chat/completions`, `OPENAI_EXTRACT_MODEL`
  (дефолт `gpt-4o-mini`); `OPENAI_API_KEY` в `/opt/remlab/.env` (тот же, что у ads-watchdog).
- **PostHog:** free 1M событий/мес; Sentry не заводим. На проде не включён (нет `POSTHOG_*` в compose).
- **CI:** **секрет `DEPLOY_SSH_KEY` НЕ задан → авто-деплой пропускает шаги** (катим вручную `./deploy.sh`).
- **Яндекс:** общий аккаунт; Direct-токен до ≈2027-04; Метрика `110599064`; кампании Этапов 1–4 (чужую `708745261` не трогать). [[marketing-acquisition]].

**Tier 2:** `../domain/integrations.md` (эндпоинты, форматы, env, цены). Решения — `decisions.md` (ADR-0007/0011/0012/0013).
