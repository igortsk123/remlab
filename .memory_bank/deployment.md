---
tier: 1
topic: deployment
scope: Деплой/откат/сервер exit-fi
tier2: "domain/deployment-details.md"
updated: 2026-09-05
importance: high
source: manual
status: working
source_of_truth: canonical
last_verified: 2026-09-05
review_after: 2026-12-05
---

# Deployment — playbook

> ⚠️ Хост делит боевую VPN-ноду (remnanode/rw-core/warp) — НЕ ломать. Сервер aarch64 — образы `linux/arm64`.

## Production (LIVE)
- https://remont-lab.online (A → 89.167.127.0, без CF); LE TLS-ALPN-01 :443, Caddy (ADR-0003).
- Контейнеры (`docker-compose.yml`, сеть `remlab-net`): `remlab-app` (Next standalone :3000),
  `remlab-caddy`, `remlab-db` (pgvector:pg17), `remlab-imagor`, `traces-init`, `mesh-receiver`;
  лимиты памяти — ADR-0004. Вне compose: `draft:8099` (DEV-рендер демо) — Caddy проксирует
  `/api/{draft,warm,render,job,share}*`.
- Статик `/test/*` → `/opt/remlab/test` (публикации только на хаб, `hub_page.py --publish`);
  `/lab/*` — Next; `/test/mesh-audit/*` — кэш immutable (ADR-0194).
- **Caddyfile деплой НЕ синхронизирует** — правка руками: бэкап `Caddyfile.bak-<дата>` →
  `caddy validate` → `caddy reload`; `deploy.sh` требует паритета с репо.

## Сервер
exit-fi 89.167.127.0 (2 vCPU/3.7G/38G), compose v2, `/opt/remlab`, swap 4G, SSH root@ (:22222).
Соседи НЕ трогать: remnanode, rw-core, nginx :80.

## Деплой (ADR-0179)
Push в `main` → CI gate → `Deploy prod` (`deploy.yml`, выкатывается `workflow_run.head_sha`).
Серверная часть одна для CI и ручного пути — `infra/server/deploy-remote.sh` под `.deploy.lock`:
`prev` ← image ID работающего контейнера → образ → БД → активация. Схема — `tools/apply-db-init.sh`;
`db/init` (только прод, `rsync --delete`); каталожные миграции — `tools/scout/NNN-*.sql` → дев-БД.
Ручной `./deploy.sh <tag>` — запасной (НЕ с DEV-VM: OOM).

## Откат / smoke
- `deploy.yml`: smoke = `ok=true` И `version == TARGET_SHA` (одного 200 мало), шаг на `!cancelled()`.
  Ручной `deploy.sh` решает по HTTP 200 — версию в `/api/health` проверять глазами.
- Откат: `flock /opt/remlab/.deploy.lock env REMLAB_IMAGE=remlab-app:prev APP_VERSION=prev docker compose up -d`
- Smoke вручную: `/`=200; `/api/health` ok; VPN цел (remnanode Up).

## Сторожа и секреты
Каталог (ADR-0172), диск `infra/server/cleanup.sh` (ADR-0005), `.env` в `/opt/remlab` вне git.
Принципы: верифицируй health-версию; правка сервера = бэкап + rollback.

**Tier 2:** `domain/deployment-details.md` — конвейер по шагам, две базы, Caddy и статик, сторожа.
