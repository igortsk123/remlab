---
tier: 1
topic: deployment
scope: Деплой/откат/сервер exit-fi
tier2: "domain/deployment-details.md"
updated: 2026-09-08
importance: high
source: manual
status: working
source_of_truth: canonical
last_verified: 2026-09-08
review_after: 2026-12-05
---

# Deployment — playbook

> ⚠️ Хост делит боевую VPN-ноду (remnanode/rw-core/warp) — НЕ ломать. Сервер aarch64 (`linux/arm64`).

## Production (LIVE)
- https://remont-lab.online (A → 89.167.127.0, без CF); LE TLS-ALPN-01 :443, Caddy (ADR-0003).
- Контейнеры (`docker-compose.yml`, сеть `remlab-net`): `app` (Next :3000), `caddy`, `db`,
  `imagor`, `traces-init`, `mesh-receiver`; лимиты — ADR-0004. Вне compose: `draft:8099`
  (DEV-рендер демо), Caddy проксирует `/api/{draft,warm,render,job,share}*`.
- Статика: `/test/*` → `./test` (служебное), `/demo` → `./demo` (ADR-0201),
  `/test/mesh-audit/*` — кэш immutable (ADR-0194); `/lab/*` — Next.
- **Caddyfile деплой НЕ синхронизирует** — руками: бэкап → `validate` → `reload`. **Один сервис —
  только `up -d --no-deps`**: иначе `app` пересоздаётся на дефолтном образе и прод откатывается
  (ADR-0202; образ — в `.env`).

## Сервер
exit-fi 89.167.127.0 (2 vCPU/3.7G/38G), compose v2, `/opt/remlab`, swap 4G, SSH root@ (:22222).
Соседи НЕ трогать: remnanode, rw-core, nginx :80. Секреты — `/opt/remlab/.env` (вне git).

## Деплой (ADR-0179)
Push в `main` → CI gate → `Deploy prod` (`deploy.yml`, по `workflow_run.head_sha`). Серверная
часть одна — `infra/server/deploy-remote.sh` под `.deploy.lock`: `prev` → образ → БД → активация →
запись образа в `.env`. Схема — `tools/apply-db-init.sh`, `db/init` (`rsync --delete`); каталожные
миграции — `tools/scout/NNN-*.sql` → дев-БД. Ручной `./deploy.sh <tag>` — запасной (НЕ с DEV-VM).

## Откат / smoke
- `deploy.yml`: smoke = `ok=true` И `version == TARGET_SHA` (одного 200 мало). Откат — тег `prev`
  (команда в Tier 2). Вручную: `/`=200, `/api/health` ok, VPN цел (remnanode Up).

## Безопасность (инцидент 08.09, ADR-0207)
Патчи с публичным RCE — сразу (RSC CVE-2025-55182: на 15.5.4 в контейнер приехал майнер; сейчас
15.5.25/React 19.1.9). В Caddy не снимать журнал обращений и заслон `@nextrce`. `.env` после
машинной правки — `docker compose config --quiet`.

## Сторожа
Каталог (ADR-0172), диск `cleanup.sh` (ADR-0005). Правка сервера = бэкап + rollback.

**Tier 2:** `domain/deployment-details.md` — конвейер по шагам, две базы, Caddy и статик, сторожа.
