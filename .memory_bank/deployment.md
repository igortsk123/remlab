---
tier: 1
topic: deployment
scope: Деплой/откат/сервер exit-fi — playbook
tier2: ""
updated: 2026-08-04
importance: high
source: manual
last_verified: 2026-08-04
---

# Deployment — playbook

> ⚠️ Хост делит боевую VPN-ноду (remnanode/rw-core/warp) — НЕ ломать, всё изолированно.
> ⚠️ Сервер aarch64 (ARM): образы ТОЛЬКО `linux/arm64` (buildx+binfmt; `deploy.sh` делает сам).

## Production (LIVE)
- https://remont-lab.online (GoDaddy A → 89.167.127.0, без CF); LE TLS-ALPN-01 :443, Caddy авто-продление (ADR-0003).
- Контейнеры (compose, сеть `remlab-net`): `remlab-app` (Next **standalone**, `node server.js`, :3000 —
  НЕ `next start`), `remlab-caddy` (:443), `remlab-db` (pgvector:pg17), `remlab-imagor`, `traces-init`.
  mem app 1G / pg 1G / caddy 128M (ADR-0004).
- Статик без пересборки (Caddyfile `handle_path`): `/test/*` → `/opt/remlab/test` (страницы проверок
  владельцу, browse+noindex), `/lab/*` → `/opt/remlab/temp`.

## Сервер
exit-fi 89.167.127.0 (Hetzner, Ubuntu 24.04, 2 vCPU/3.7G/38G), Docker+compose v2, рабдир `/opt/remlab`.
Swap 4G; iptables INPUT=DROP (:443 открыт, :80 закрыт); SSH root@ (и :22222).
Соседи НЕ трогать: remnanode, rw-core (:8444/:9443/:2222), системный nginx :80.

## Деплой — `./deploy.sh <tag>` (всё автоматом)
buildx arm64 → прежний образ в `:prev` → `docker save|ssh|docker load` → `compose up -d`
(+ 5b: SQL-миграции `db/init/*.sql` psql-ом, идемпотентно) → smoke → провал = откат на `:prev`.

**Авто-деплой РАБОТАЕТ (2026-07-31):** push в `main` → `CI gate` (typecheck/lint/unit/e2e) → джоба
`Deploy prod`; проверка — `/api/health.version` == HEAD main. Ручной `./deploy.sh` — запасной
(⚠️ НЕ с DEV-VM pakardev: QEMU-сборка OOM'ит). CI гейтит e2e — правишь UI, чини `e2e/*.spec.ts`.

## Откат / smoke
- Откат: `ssh root@89.167.127.0 'cd /opt/remlab && docker tag remlab-app:prev remlab-app:latest && docker compose up -d'`
- Smoke: `/` = 200; `/api/health` = `{"ok":true}`; VPN цел: remnanode Up, :8444/:9443/:2222 живы.

## Автоочистка (ADR-0005)
Логи json-file 10m×3; weekly `remlab-cleanup`; ночной `pg_dump` → `/opt/remlab/backups` (7 шт); df-watchdog >80%.

## Секреты
`.env` в `/opt/remlab` (вне git): `POSTGRES_PASSWORD`/`GEMINI_API_KEY`/`TRACE_ADMIN_TOKEN` и пр.
Compose передаёт app ЯВНЫЙ `environment:`-список — новый ключ = правка compose. В репо — `.env.example`.

## Принципы
Верифицируй деплой (health-версия); перед правкой сервера — бэкап + rollback; VPN не трогать.
