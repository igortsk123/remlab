---
tier: 1
topic: access-and-integrations
scope: Внешние интеграции/доступы — где ключи, какие модели/эндпоинты, форматы, клиенты в коде
tier2: "../domain/integrations.md"
updated: 2026-07-09
importance: high
source: manual
status: working
source_of_truth: canonical
last_verified: 2026-07-09
review_after: ""
---

# Access & Integrations — Tier 1 сводка

> Секретов тут НЕТ — только ГДЕ они и КАК устроен доступ. Эндпоинты/форматы/env/цены — Tier 2.

## Реестр
| Интеграция | Статус | Задача | Ключи (где) | Код |
|---|---|---|---|---|
| Google Gemini | активен ✅ | картинки + анализ фото/текст | `GEMINI_API_KEY`: локально `.env.local`, прод `/opt/remlab/.env` | `lib/providers/gemini.ts` |
| OpenAI | розетка | сменный vision | `OPENAI_API_KEY` (нигде нет) | ставится в `lib/providers/index.ts` |
| PostHog | код есть, прод no-op (ADR-0012) | аналитика+ошибки | `POSTHOG_KEY` НЕ задан (без ключа no-op) | `lib/analytics.ts` |
| Гдеслон | план v0.3 | affiliate-фиды, ~3% с выкупа | появятся в `.env` | — |
| imagor | активен (ADR-0013) | сжатие картинок, internal-only | ключей НЕТ (`IMAGOR_UNSAFE=1`); `IMAGOR_BASE_URL` захардкожен в compose | `lib/images/compress.ts` |
| GHCR/CI | частично (ADR-0011) | образы + авто-деплой | `GITHUB_TOKEN`; SSH `~/.ssh/remlab_ci_deploy` | GitHub Actions |

## Ключевые факты
- **Gemini:** один ключ на обе задачи; модели `gemini-3.1-flash-image` (Nano Banana 2) и `gemini-flash-latest`. Интерфейсы `lib/providers/types.ts`, фабрики `getImageProvider`/`getVisionProvider`, ошибки `Result<T,E>`.
- **PostHog:** free 1M событий/мес; Sentry не заводим. Одним ключом включить НЕЛЬЗЯ: compose передаёт в app явный `environment:`-список без POSTHOG_* — нужна правка compose.
- **Affiliate-блокеры:** атрибуция web→app МП, cookie duration, ставки; locale-agnostic (РФ→UK).
- **Трейсинг:** ассеты на томе `remlab-traces`, трейс в Postgres — см. `core/observability-tracing.md`.
- **CI:** образы `ghcr.io/igortsk123/remlab-app`; **секрет `DEPLOY_SSH_KEY` НЕ задан → авто-деплой пропускает шаги**. GitHub PAT (read-only Actions) у Клода локально.
- **Цены:** рычаг Stage 1 — генерация картинки (~$0.045–0.067/шт); vision — доли цента.

**Tier 2:** `../domain/integrations.md` — эндпоинты, форматы, env, смоуки, детали деплоя, цены. Решения — `decisions.md` (ADR-0007/0011/0012/0013).
