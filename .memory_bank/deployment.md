---
tier: 1
topic: deployment
scope: Деплой/откат/сервер exit-fi — playbook
tier2: ""
updated: 2026-08-31
importance: high
source: manual
last_verified: 2026-08-04
---

# Deployment — playbook

> ⚠️ Хост делит боевую VPN-ноду (remnanode/rw-core/warp) — НЕ ломать.
> ⚠️ Сервер aarch64: образы только `linux/arm64` (`deploy.sh` делает сам).

## Production (LIVE)
- https://remont-lab.online (A → 89.167.127.0, без CF); LE TLS-ALPN-01 :443, Caddy (ADR-0003).
- Контейнеры (сеть `remlab-net`): `remlab-app` (Next standalone `node server.js` :3000 — НЕ
  `next start`), `remlab-caddy` (:443), `remlab-db` (pgvector:pg17), `remlab-imagor`,
  `traces-init`; mem app 1G / pg 1G / caddy 128M (ADR-0004).
- Статик: `/test/*` → `/opt/remlab/test`, `/lab/*` → `/opt/remlab/temp`.
- **Правило владельца 11.08: все публикации — на хаб /test/** (`tools/scout/hub_page.py`:
  LINKS + `--publish`). ⚠ Bind `./test:/srv/test:ro` — в РЕПОЗИТОРНОМ compose (серверные
  правки затирает CI-деплой, урок 07.08).

## Сервер
exit-fi 89.167.127.0 (2 vCPU/3.7G/38G), compose v2, `/opt/remlab`; swap 4G; :443 открыт;
SSH root@ (:22222). Соседи НЕ трогать: remnanode, rw-core, nginx :80.

## Деплой — `./deploy.sh <tag>` (всё автоматом)
buildx arm64 → `:prev` → save|ssh|load → `compose up -d` (+SQL-миграции `db/init/*.sql`
идемпотентно) → smoke → провал = откат на `:prev`.

**Авто-деплой:** push в `main` → CI gate → `Deploy prod` (health.version == HEAD). Ручной
`./deploy.sh` — запасной (⚠️ НЕ с DEV-VM: OOM).

## Откат / smoke
- Откат: `docker tag remlab-app:prev remlab-app:latest && docker compose up -d`
- Smoke: `/`=200; `/api/health` ok; VPN цел (remnanode Up).

## Автоочистка (ADR-0005)
Логи 10m×3; weekly `remlab-cleanup` (+трейсы >90 дн.); ночной `pg_dump` ×7; df-watchdog >80%.

## Правки сервера 31.08 (ADR-0139; откат — бэкапы *.bak-20260831)
- sshd `GatewayPorts clientspecified`; iptables вход bridge→`172.18.0.1:8601` (rules.v4) —
  туннель DEV-рендера, наружу не торчит. Выключить = удалить
  `/opt/remlab/test/share/render-proxy.conf`. Контейнер `remlab-draft` правится docker cp;
  пересоздание образа: trimesh/scipy/fast-simplification, `asset_strategy.py`, `rules/`,
  `DRAFT_HOST=0.0.0.0`, mem 1.5G.

## Секреты
`.env` в `/opt/remlab` (вне git): `POSTGRES_PASSWORD`/`GEMINI_API_KEY`/`TRACE_ADMIN_TOKEN`.
Compose передаёт app ЯВНЫЙ `environment:`-список — новый ключ = правка compose.

## Принципы
Верифицируй health-версию; правка сервера = бэкап + rollback; VPN не трогать.

