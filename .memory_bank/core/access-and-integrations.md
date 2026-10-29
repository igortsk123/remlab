---
tier: 1
topic: access-and-integrations
scope: Интеграции/доступы — ключи, клиенты
tier2: "../domain/integrations.md"
updated: 2026-10-29
importance: high
source: manual
status: working
source_of_truth: canonical
last_verified: 2026-10-11
review_after: 2026-12-05
---

# Access & Integrations — Tier 1 сводка

> Секретов тут НЕТ — только где они. Детали — Tier 2.

**Чужие ключи** (sib, sing, sup2-repo) — не наши; прежде чем сказать «нет доступа» — `node tools/access-inventory.mjs` (урок 57).

## Ключевые факты
- **Gemini:** приложение — через шлюз Vercel (`AI_PROVIDER=gateway` по умолчанию, `lib/providers/gateway.ts`, ADR-0277); прямой ключ отключён 14.10.
- **OpenAI:** прямой ключ без денег — не пополняем (ADR-0325); дочитка по ссылке — через шлюз (`lib/providers/index.ts:getExtractProvider`);
  прямой OpenAI остался только в Python DEV (`judge.py`, `pipeline*.py`) — долг. `gpt-4o-mini` под картинки НЕ брать (ADR-0067).
- **Яндекс:** Метрика `110599064`; кампанию `708745261` не трогать. [[marketing-acquisition]].

**Tier 2:** `../domain/integrations.md` — эндпоинты, форматы, env, фиды, § Codex (сессия сломана
15.10 → `--ephemeral`; `vercel*` — только экономно `vercel-sol` при исчерпании подписки, ADR-0301/0327). Решения — ADR-0007/0011/0012/0013/0045.

- **Vercel AI Gateway:** единственный путь к LLM; «нет денег» — `tools/scout/llm_gateway.py:NoCredits`,
  баланс и траты — `GET /v1/credits` (`balance`, `total_used`, бесплатно), тревога `gateway_no_credits` в дайджесте DEV (`tools/ops/dev-checks.sh`).

- **fal.ai:** клиент `tools/scout/falmini.py`; на мешах заменён Salad (ADR-0131).

## Прочие доступы (детали — `../domain/integrations.md`)
- **Мост мешей DEV↔прод:** `MESH_REVIEW_SECRET` (кука владельца) + `MESH_REVIEW_MACHINE_TOKEN`
  (Bearer конвейера); общие для mesh-review/mesh-audit — Tier 2.
- **SaladCloud + GHCR (31.08):** GPU под меши вместо fal; орг `prodstore`/`dmodel`, ключи в
  `_secrets/`, образ только digest'ом. События машин — `log-entries` (бесплатно, [[mesh-pool]] Tier 2 § 6). Грабли API — ADR-0137.
  **02.10:** GHCR — единственная копия образа (ADR-0232); вход — `GHCR_TOKEN` (`_secrets/`),
  не `gh auth token`: токену под пакеты `gh` требует ещё `read:org`.
- **Гдеслон (03.09):** фиды первичны (`original_picture`, `article`, описание), API — комиссия;
  id округлён (связь по `article`), `available` бесполезен — ADR-0171.
- **Telegram `@remlabservice_bot` (03.09):** токен и chat_id в `tools/scout/.env.alert` и `/opt/remlab/catalog-watchdog/.env`. С 14.10 — и клиентский бот; UptimeRobot — Tier 2.
