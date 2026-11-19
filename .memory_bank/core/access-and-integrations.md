---
tier: 1
topic: access-and-integrations
scope: Интеграции/доступы — ключи, клиенты
tier2: "../domain/integrations.md"
updated: 2026-11-19
importance: high
source: manual
status: working
source_of_truth: canonical
last_verified: 2026-11-19
review_after: 2026-12-05
---

# Access & Integrations — Tier 1 сводка

> Секретов тут НЕТ — только где они. Детали — Tier 2.

**Ключи скриптов scout** — резолвер `tools/scout/env_keys.py` (`--where`, `--ping`; из worktree — основная копия) → Tier 2 § env_keys.
**Чужие ключи** (sib, sing, sup2-repo) — не наши; прежде чем сказать «нет доступа» — `node tools/access-inventory.mjs` (урок 57).

## Ключевые факты
- **Gemini:** приложение — через шлюз Vercel (`AI_PROVIDER=gateway` по умолчанию, `lib/providers/gateway.ts`, ADR-0277); прямой ключ отключён 14.10.
- **OpenAI:** прямой ключ без денег — не пополняем (ADR-0325); дочитка по ссылке — через шлюз (`lib/providers/index.ts:getExtractProvider`);
  прямой OpenAI в ~18 скриптах DEV — долг. `gpt-4o-mini` под картинки НЕ брать (ADR-0067).
- **Яндекс:** Метрика `110599064`; кампанию `708745261` не трогать. [[marketing-acquisition]].

**Tier 2:** `../domain/integrations.md` — эндпоинты, форматы, env, фиды, § Codex (`vercel*` — только `vercel-sol`, ADR-0327). Решения — ADR-0007/0011/0012/0013/0045.

- **Vercel AI Gateway:** основной путь к LLM; «нет денег» — `tools/scout/llm_gateway.py:NoCredits`; баланс — `GET /v1/credits`
  ключом `VERCEL_AI_GATEWAY_KEY` (0 → 402 у фото и у Codex `vercel-sol`), тревога `gateway_no_credits` (`tools/ops/dev-checks.sh`).
- **fal.ai:** `tools/scout/falmini.py`; меши — Salad (ADR-0131); 403 «locked» = баланс пуст.

## Прочие доступы (детали — `../domain/integrations.md`)
- **Мост мешей DEV↔прод:** `MESH_REVIEW_SECRET` + `MESH_REVIEW_MACHINE_TOKEN` — Tier 2.
- **SaladCloud + GHCR (31.08):** GPU под меши вместо fal; орг `prodstore`/`dmodel`, ключи в
  `_secrets/`, образ только digest'ом. События машин — `log-entries` (бесплатно, [[mesh-pool]] Tier 2 § 6). Грабли API — ADR-0137.
  GHCR — единственная копия образа (ADR-0232), вход `GHCR_TOKEN` (Tier 2). `HF_TOKEN` (DINOv3, 18.11) — Tier 2 § env_keys.
- **RunPod (19.11):** карты ≥40 ГБ, ключ в `_secrets/` — Tier 2.
- **GitHub, логи CI (19.11):** ключ на чтение Actions до ≈17.02.2027 — Tier 2 § GitHub.
- **Гдеслон (03.09):** фиды первичны (`original_picture`, `article`, описание), API — комиссия;
  id округлён (связь по `article`), `available` бесполезен — ADR-0171.
- **Telegram `@remlabservice_bot`:** токен в `tools/scout/.env.alert` (+ сторож каталога на сервере); клиентский бот, UptimeRobot — Tier 2.
