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
last_verified: 2026-09-05
review_after: 2026-12-05
---

# Deployment — playbook

> ⚠️ Хост делит боевую VPN-ноду (remnanode/rw-core/warp) — НЕ ломать. Сервер aarch64 — образы `linux/arm64`.

## Production (LIVE)
- https://remont-lab.online (A → 89.167.127.0, без CF); LE TLS-ALPN-01 :443, Caddy (ADR-0003).
- Контейнеры (`docker-compose.yml`, сеть `remlab-net`): `remlab-app` (Next :3000), `remlab-caddy`,
  `remlab-db`, `remlab-imagor`, `traces-init`, `mesh-receiver`; лимиты — ADR-0004. Вне compose:
  `draft:8099` (DEV-рендер демо) — Caddy проксирует `/api/{draft,warm,render,job,share}*`.
- Статика: `/test/*` → `./test` (служебное, листинг, `hub_page.py --publish`), `/demo` → `./demo`
  (демо партнёра, ADR-0201), `/test/mesh-audit/*` — кэш immutable (ADR-0194); `/lab/*` — Next.
- **Caddyfile деплой НЕ синхронизирует** — руками: бэкап → `caddy validate` → `caddy reload`;
  `deploy.sh` требует паритета с репо. **Один сервис — только `up -d --no-deps`**: иначе
  пересоздаётся `app` на дефолтном образе и прод откатывается (ADR-0202; образ — в `.env`).

## Сервер
exit-fi 89.167.127.0 (2 vCPU/3.7G/38G), compose v2, `/opt/remlab`, swap 4G, SSH root@ (:22222).
Соседи НЕ трогать: remnanode, rw-core, nginx :80.

## Деплой (ADR-0179)
Push в `main` → CI gate → `Deploy prod` (`deploy.yml`, выкатывается `workflow_run.head_sha`).
Серверная часть одна для CI и ручного пути — `infra/server/deploy-remote.sh` под `.deploy.lock`:
`prev` → образ → БД → активация → запись образа в `.env`. Схема — `tools/apply-db-init.sh`;
`db/init` (только прод, `rsync --delete`); каталожные миграции — `tools/scout/NNN-*.sql` → дев-БД.
Ручной `./deploy.sh <tag>` — запасной (НЕ с DEV-VM: OOM).

## Откат / smoke
- `deploy.yml`: smoke = `ok=true` И `version == TARGET_SHA` (одного 200 мало), шаг на `!cancelled()`;
  ручной `deploy.sh` — по 200, версию смотреть глазами в `/api/health`.
- Откат — тег `prev` (полная команда в Tier 2).
- Smoke вручную: `/`=200; `/api/health` ok; VPN цел (remnanode Up).

## Сторожа и секреты
Каталог (ADR-0172), диск `cleanup.sh` (ADR-0005), `.env` вне git. Правка сервера = бэкап + rollback.

**Tier 2:** `domain/deployment-details.md` — конвейер по шагам, две базы, Caddy и статик, сторожа.
