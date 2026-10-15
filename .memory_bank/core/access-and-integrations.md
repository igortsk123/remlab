---
tier: 1
topic: access-and-integrations
scope: Интеграции/доступы — ключи, клиенты
tier2: "../domain/integrations.md"
updated: 2026-10-15
importance: high
source: manual
status: working
source_of_truth: canonical
last_verified: 2026-10-11
review_after: 2026-12-05
---

# Access & Integrations — Tier 1 сводка

> Секретов тут НЕТ — только где они. Детали — Tier 2.

## Чужие ключи на машине
Соседние проекты (sib, sing, sup2-repo) держат ключи в своих `.env` — не наши. Прежде чем сказать
«у нас нет доступа», прогнать `node tools/access-inventory.mjs` (урок 57).

## Ключевые факты
- **Gemini:** один ключ на обе задачи; `gemini-3.1-flash-image`, `gemini-flash-latest`. **14.10: ключ отключён** (Google удалил сервисный аккаунт) — на DEV и на сервере.
- **OpenAI (ADR-0026):** фолбэк парсинга ссылок; `gpt-4o-mini` под картинки НЕ брать (ADR-0067) — Tier 2 § OpenAI.
- **Яндекс:** Метрика `110599064`; кампанию `708745261` не трогать. [[marketing-acquisition]].

**Tier 2:** `../domain/integrations.md` — эндпоинты, форматы, env, фиды, § Codex (постоянная
сессия советника; как звать — там же; при исчерпании лимита — `--profile vercel`, ADR-0253; подписку и шлюз в одной
сессии не смешивать — 15.10 это сломало сессию 01a00a62; кредиты шлюза 15.10 = 0, 402). Решения — ADR-0007/0011/0012/0013/0045.

- **Vercel AI Gateway (26.08):** единственный рабочий путь к LLM (прямой OpenAI без кредитов); лимит, похоже,
  суточный (13.10 исчерпан в 20:40, с 00:00 UTC снова работает). «Нет денег» — `tools/scout/llm_gateway.py:NoCredits`,
  проверка каналов — дайджест DEV (`tools/ops/dev-checks.sh`). Детали — `../domain/integrations.md`.

- **fal.ai:** клиент `tools/scout/falmini.py`; на мешах заменён Salad (ADR-0131).

## Прочие доступы (детали — `../domain/integrations.md`)
- **Мост мешей DEV↔прод:** `MESH_REVIEW_SECRET` (кука владельца) + `MESH_REVIEW_MACHINE_TOKEN`
  (Bearer конвейера); общие для mesh-review/mesh-audit — Tier 2.
- **SaladCloud + GHCR (31.08):** GPU под меши вместо fal; орг `prodstore`/`dmodel`, ключи в
  `_secrets/`, образ только digest'ом. Грабли API — ADR-0137, [[mesh-pipeline]].
  **02.10:** GHCR — единственная копия образа (ADR-0232); вход — `GHCR_TOKEN` (`_secrets/`),
  не `gh auth token`: токену под пакеты `gh` требует ещё `read:org`.
- **Гдеслон (03.09):** фиды первичны (`original_picture`, `article`, описание), API — комиссия;
  id округлён (связь по `article`), `available` бесполезен — ADR-0171.
- **Telegram `@remlabservice_bot` (03.09):** токен и chat_id в `tools/scout/.env.alert` и `/opt/remlab/catalog-watchdog/.env`. С 14.10 — и клиентский бот; UptimeRobot — Tier 2.
- **Sketchfab (01.09)** — Tier 2.
