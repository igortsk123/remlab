---
tier: 1
topic: access-and-integrations
scope: Внешние интеграции/доступы — где ключи, какие модели/эндпоинты, форматы, клиенты в коде
tier2: "../domain/integrations.md"
updated: 2026-07-11
importance: high
source: manual
status: working
source_of_truth: canonical
last_verified: 2026-07-11
review_after: ""
---

# Access & Integrations — Tier 1 сводка

> Секретов тут НЕТ — только где они и как устроен доступ. Детали — Tier 2.

## Реестр
| Интеграция | Статус | Задача | Ключи (где) | Код |
|---|---|---|---|---|
| Google Gemini | активен ✅ | картинки + анализ фото | `GEMINI_API_KEY`: `.env.local` / прод `/opt/remlab/.env` | `lib/providers/gemini.ts` |
| OpenAI | ключ есть ✅ | GPT-5.1 тексты объявлений | `_secrets/ACCESS.md` | `ads-watchdog/common.py` |
| PostHog | код есть, прод no-op (ADR-0012) | аналитика+ошибки | `POSTHOG_KEY` не задан | `lib/analytics.ts` |
| Гдеслон | М0 ⏸ ключевой | deeplink+фиды → реф-смета | будут в `.env` | — |
| imagor | активен (ADR-0013) | сжатие картинок, internal-only | ключей НЕТ (unsafe); URL в compose | `lib/images/compress.ts` |
| GHCR/CI | частично (ADR-0011) | образы + авто-деплой | `GITHUB_TOKEN`; SSH `~/.ssh/remlab_ci_deploy` | GitHub Actions |
| Яндекс (WS/Директ/Метрика) | доступ ✅ | семантика/реклама/аналитика | `_secrets/ACCESS.md` (вне git) | кода нет, curl |

## Ключевые факты
- **Gemini:** один ключ на обе задачи; модели `gemini-3.1-flash-image` и `gemini-flash-latest`.
- **PostHog:** free 1M событий/мес; Sentry не заводим. Одним ключом на проде не включить (compose не пробрасывает `POSTHOG_*` — детали в Tier 2).
- **М0 (Гдеслон):** deeplink чужой ссылки?; DIY-магазины; комиссии; cookie/атрибуция.
- **Трейсинг:** ассеты на томе `remlab-traces`, трейс в Postgres — см. `core/observability-tracing.md`.
- **CI:** **секрет `DEPLOY_SSH_KEY` НЕ задан → авто-деплой пропускает шаги**; GitHub PAT (read-only Actions) у Клода локально.
- **Яндекс:** общий аккаунт с v0-health-card; Direct-токен до ≈2027-04; Метрика `110599064`; кампании Этапов 1–4 (чужую `708745261` не трогать). Сводка — [[marketing-acquisition]].
- **Цены:** рычаг Stage 1 — генерация картинки ~$0.05/шт (Tier 2).

**Tier 2:** `../domain/integrations.md` (эндпоинты, форматы, env, цены). Решения — `decisions.md` (ADR-0007/0011/0012/0013).
