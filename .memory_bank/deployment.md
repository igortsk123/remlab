---
tier: 1
topic: deployment
scope: Деплой/откат/сервер exit-fi
tier2: "domain/deployment-details.md"
updated: 2026-09-28
importance: high
source: manual
status: working
source_of_truth: canonical
last_verified: 2026-09-28
review_after: 2026-12-05
---

# Deployment — playbook

> ⚠️ Хост делит боевую VPN-ноду (remnanode/rw-core/warp) — НЕ ломать. Сервер aarch64 (`linux/arm64`).

## Production (LIVE)
- https://remont-lab.online (A → 89.167.127.0, без CF); LE TLS-ALPN-01 :443, Caddy (ADR-0003).
- Контейнеры: `app` (Next :3000), `caddy`, `db`, `imagor`, `traces-init`, `mesh-receiver`
  (`docker-compose.yml`, сеть `remlab-net`, лимиты ADR-0004). Вне compose `draft:8099`
  (DEV-рендер демо) — Caddy проксирует `/api/{draft,warm,render,job,share}*`.
- Статика: `/test/*` → `./test`, `/demo` → `./demo` (ADR-0201), `/test/mesh-audit/*` — immutable
  (ADR-0194); `/lab/*` — Next. Маршрут без парного `redir /x /x/` = 404 без слэша.
- **Caddyfile деплой НЕ синхронизирует** — руками: бэкап → ⚠ `diff` с сервером (он НОВЕЕ репо:
  `log`, `@nextrce`) → `validate` → `reload`. **Один сервис — только `up -d --no-deps`**: иначе
  `app` пересоздаётся на дефолтном образе и прод откатывается (ADR-0202; образ — в `.env`).

## Сервер
exit-fi 89.167.127.0 (2 vCPU/3.7G/38G), compose v2, `/opt/remlab`, swap 4G, SSH root@ (:22222).
Соседей НЕ трогать: remnanode, rw-core, nginx :80. Секреты — `/opt/remlab/.env` (вне git).

## Деплой (ADR-0179)
Push в `main` → CI gate → `Deploy prod` (`deploy.yml`, по `workflow_run.head_sha`). Серверная
часть одна — `infra/server/deploy-remote.sh` под `.deploy.lock`: `prev` → образ → БД → активация →
запись образа в `.env`. Схема и каталожные миграции — Tier 2. Ручной `./deploy.sh <tag>` —
запасной (не с DEV-VM).

## Откат / smoke
- smoke = `ok=true` И `version == TARGET_SHA` (одного 200 мало). Откат — тег `prev` (Tier 2).
  Вручную: `/`=200, `/api/health` ok, VPN цел (remnanode Up).

## Безопасность (инцидент 08.09, ADR-0207)
Патчи с публичным RCE — сразу (RSC CVE-2025-55182: на 15.5.4 в контейнер приехал майнер; сейчас
15.5.25/React 19.1.9). Журнал и заслон `@nextrce` в Caddy не снимать. `.env` после машинной
правки — `docker compose config --quiet`.

## Сторожа
Каталог (ADR-0172), диск `cleanup.sh` (ADR-0005). Правка сервера = бэкап + rollback.

**Tier 2:** `domain/deployment-details.md` — конвейер, две базы, Caddy и статик, сторожа.
