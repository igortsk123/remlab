---
tier: 1
topic: deployment
scope: Деплой/откат/сервер exit-fi
tier2: "domain/deployment-details.md"
updated: 2026-09-05
importance: high
source: manual
last_verified: 2026-09-05
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

## Деплой (ADR-0179)
Push в `main` → CI gate → `Deploy prod`; выкатывается `workflow_run.head_sha` (проверенный коммит,
не HEAD ветки). Серверная часть одна для CI и ручного пути — `infra/server/deploy-remote.sh` под
замком `.deploy.lock`: `prev` ← image ID работающего контейнера → образ → БД+миграции → активация.
Схему применяет один `tools/apply-db-init.sh`; `db/init` синхронизируется `rsync --delete`.
`db/init` = только прод, каталожные миграции — `tools/scout/NNN-*.sql` → дев-БД.
Ручной `./deploy.sh <tag>` — запасной (НЕ с DEV-VM: OOM).

## Откат / smoke
- Smoke сверяет `ok=true` И `version == TARGET_SHA` (одного 200 мало: при сорванном выкате сайт
  отвечает 200 на старой версии). Откат — только если сайт реально не отвечает.
- Откат: `flock /opt/remlab/.deploy.lock env REMLAB_IMAGE=remlab-app:prev APP_VERSION=prev docker compose up -d`
- Smoke вручную: `/`=200; `/api/health` ok; VPN цел (remnanode Up).

## Сторожа и секреты
Каталог (ADR-0172), диск/очистка (ADR-0005/0176), `.env` в `/opt/remlab` вне git — подробности и
история правок сервера в Tier 2.

## Принципы
Верифицируй health-версию; правка сервера = бэкап + rollback; VPN не трогать.

**Tier 2:** `domain/deployment-details.md` — конвейер по шагам, две базы и гарда, сторожа, секреты.
