---
tier: 1
topic: deployment
scope: Деплой/откат/сервер exit-fi — playbook
tier2: ""
updated: 2026-09-03
importance: high
source: manual
last_verified: 2026-09-03
---

# Deployment — playbook

> ⚠️ Хост делит боевую VPN-ноду (remnanode/rw-core/warp) — НЕ ломать.
> ⚠️ Сервер aarch64: образы только `linux/arm64` (`deploy.sh` делает сам).

## Production (LIVE)
- https://remont-lab.online (A → 89.167.127.0, без CF); LE TLS-ALPN-01 :443, Caddy (ADR-0003).
- Контейнеры (сеть `remlab-net`): `remlab-app` (Next standalone `node server.js` :3000 — НЕ
  `next start`), `remlab-caddy` (:443), `remlab-db` (pgvector:pg17), `remlab-imagor`,
  `traces-init`; mem app 1G / pg 1G / caddy 128M (ADR-0004).
- Статик: `/test/*` → `/opt/remlab/test`, `/lab/*` → `/opt/remlab/temp`. Публикации — только на хаб
  /test/ (`hub_page.py`: LINKS + `--publish`, владелец 11.08); bind `./test` — в репозиторном compose.

## Сервер
exit-fi 89.167.127.0 (2 vCPU/3.7G/38G), compose v2, `/opt/remlab`, swap 4G, SSH root@ (:22222).
Соседи НЕ трогать: remnanode, rw-core, nginx :80.

## Деплой
Push в `main` → CI gate → `Deploy prod` (health.version == HEAD). Ручной `./deploy.sh <tag>` — запасной
(buildx arm64 → `:prev` → load → `compose up -d` + `db/init/*.sql` → smoke → откат на `:prev`; НЕ с DEV-VM: OOM).

## Откат / smoke
- Откат: `docker tag remlab-app:prev remlab-app:latest && docker compose up -d`
- Smoke: `/`=200; `/api/health` ok; VPN цел (remnanode Up).

## Сторож каталога (ADR-0172)
`remlab-catalog-watchdog.timer` 15:30 UTC: нет сегодняшнего статуса в `refresh-status.json` или
`overall=FAIL` → Telegram. Kill-switch `DISABLED`, откат `systemctl disable --now`; юниты —
`infra/server/systemd/`.

## Автоочистка (ADR-0005)
Логи 10m×3; weekly `remlab-cleanup` (+трейсы >90 дн.); ночной `pg_dump` ×7; df-watchdog >80%.

## Правки сервера 31.08
sshd `GatewayPorts clientspecified`, iptables-туннель DEV-рендера, `remlab-draft` через docker cp —
детали и откат в ADR-0139 (бэкапы `*.bak-20260831`).

## Секреты
`.env` в `/opt/remlab` (вне git): `POSTGRES_PASSWORD`/`GEMINI_API_KEY`/`TRACE_ADMIN_TOKEN`.
Compose передаёт app ЯВНЫЙ `environment:`-список — новый ключ = правка compose.

## Принципы
Верифицируй health-версию; правка сервера = бэкап + rollback; VPN не трогать.

