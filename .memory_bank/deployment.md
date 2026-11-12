---
tier: 1
topic: deployment
scope: Деплой/откат/сервер exit-fi
tier2: "domain/deployment-details.md"
updated: 2026-11-12
importance: high
source: manual
status: working
source_of_truth: canonical
last_verified: 2026-11-09
review_after: 2026-12-05
---

# Deployment — playbook

> ⚠️ Хост делит боевую VPN-ноду (remnanode/rw-core/warp) — НЕ ломать. Сервер aarch64 (`linux/arm64`).

## Production (LIVE)
- https://remont-lab.online (A → 89.167.127.0, без CF); LE TLS-ALPN-01 :443, Caddy (ADR-0003).
- Контейнеры: `app`, `caddy`, `db`, `imagor`, `traces-init`, `mesh-receiver`, `draft` (рендер демо, образ из CI —
  ADR-0278) — `docker-compose.yml`, сеть `remlab-net`, ADR-0004; Caddy проксирует `/api/{draft,warm,render,job,share}*`.
- Статика: `/test/*`, `/demo` (ADR-0201), `/test/mesh-audit/*` и `/rt/*` immutable (ADR-0194, 0212); `/lab/*` — Next.
  Без парного `redir /x /x/` — 404 без слэша.
- **Caddyfile едет деплоем** (`infra/server/caddy-sync.sh`, ADR-0256) — руками на сервере НЕ править.
  **Один сервис — только `up -d --no-deps`** (иначе трогает и `app`). Образ `app` — из `/opt/remlab/.env`
  (`deploy-remote.sh`); нет там — дефолт `remlab-app:latest` = откат прода (ADR-0202).

## Сервер
exit-fi 89.167.127.0 (2 vCPU/3.7G/38G), compose v2, `/opt/remlab`, swap 4G.
SSH root@: публикация :22222, деплой — порт по умолчанию.
Соседей НЕ трогать: remnanode, rw-core, nginx :80. Секреты — `/opt/remlab/.env` (вне git).

## Деплой (ADR-0179)
Push в `main` → CI gate → `Deploy prod` (`deploy.yml`). Сервер — `infra/server/deploy-remote.sh` под
`.deploy.lock`: `prev` → образ → БД → активация. `tools/ops/deploy-need.sh`: доки — без выката, предка прода не катит (ADR-0360), `--status`. Детали — Tier 2. `./deploy.sh` — запасной (не с DEV-VM).

## Откат / smoke
- smoke = `ok=true` И `version == TARGET_SHA` . Не 200 → откат на `prev`; версия не та — стоп (Tier 2).
  Вручную: `/`=200, `/api/health` ok, remnanode Up.
- Демо: `tools/scout/publish_demo.sh --rollback` (копии `demo.prev-*` ×3); кладёт `.br`/`.gz`, Caddy — `precompressed`.

## Безопасность (ADR-0207, ADR-0256)
Патчи с публичным RCE — сразу. Заслон `@nextrce` в Caddy не снимать.
**13.10 (ADR-0256):** ПДн только в базе; после деплоя `tools/security-smoke.sh`; `remlab-draft` выкатывает деплой (ADR-0278). Детали — Tier 2.

## Сторожа
Каталог (ADR-0172), диск `cleanup.sh` (ADR-0005), безопасность — `disk-watchdog.sh`. Правка сервера = бэкап + rollback.
Доступность — `health-watch.sh` → Telegram; дампы, миграция дев-БД — DEV `tools/ops/`. «Прод без DEV», DEV-рендер — Tier 2.
**Tier 2:** `domain/deployment-details.md` — конвейер, две базы, Caddy и статик, сторожа.
