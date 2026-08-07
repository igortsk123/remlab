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
- Статик: `/test/*` → `/opt/remlab/test` (browse+noindex), `/lab/*` → `/opt/remlab/temp`.
  ⚠ Bind `./test:/srv/test:ro` — в РЕПОЗИТОРНОМ compose (серверные правки затирает CI-деплой,
  урок 07.08). Публикация — конвейером (`layout10_page.py --publish`, rsync).

## Сервер
exit-fi 89.167.127.0 (Hetzner, 2 vCPU/3.7G/38G), compose v2, `/opt/remlab`; swap 4G;
:443 открыт, :80 закрыт; SSH root@ (:22222). Соседи НЕ трогать: remnanode, rw-core, nginx :80.

## Деплой — `./deploy.sh <tag>` (всё автоматом)
buildx arm64 → прежний образ в `:prev` → `docker save|ssh|docker load` → `compose up -d`
(+ 5b: SQL-миграции `db/init/*.sql` psql-ом, идемпотентно) → smoke → провал = откат на `:prev`.

**Авто-деплой РАБОТАЕТ (2026-07-31):** push в `main` → `CI gate` (typecheck/lint/unit/e2e) → джоба
`Deploy prod`; проверка — health.version == HEAD. Ручной `./deploy.sh` — запасной
(⚠️ НЕ с DEV-VM: OOM). CI гейтит e2e.

## Откат / smoke
- Откат: на сервере `docker tag remlab-app:prev remlab-app:latest && docker compose up -d`
- Smoke: `/`=200; `/api/health` ok; VPN цел (remnanode Up, :8444/:9443/:2222).

## Автоочистка (ADR-0005)
Логи json-file 10m×3; weekly `remlab-cleanup` (шаг 6 с 08.08 — трейсы >90 дн., shell-эквивалент
trace-prune, бэкап cleanup.sh.bak-2026-08-08); ночной `pg_dump` (7 шт); df-watchdog >80%.

## Секреты
`.env` в `/opt/remlab` (вне git): `POSTGRES_PASSWORD`/`GEMINI_API_KEY`/`TRACE_ADMIN_TOKEN` и пр.
Compose передаёт app ЯВНЫЙ `environment:`-список — новый ключ = правка compose. В репо — `.env.example`.

## Принципы
Верифицируй деплой (health-версия); перед правкой сервера — бэкап + rollback; VPN не трогать.

