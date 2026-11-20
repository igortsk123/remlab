---
tier: 1
topic: deployment
scope: Деплой/откат/сервер exit-fi
tier2: "domain/deployment-details.md"
updated: 2026-11-20
importance: high
source: manual
status: working
source_of_truth: canonical
last_verified: 2026-11-17
review_after: 2026-12-05
---

# Deployment — playbook

> ⚠️ Хост делит боевую VPN-ноду (remnanode/rw-core/warp) — НЕ ломать. Сервер aarch64 (`linux/arm64`).

## Production (LIVE)
- https://remont-lab.online (A → 89.167.127.0, без CF); LE TLS-ALPN-01 :443, Caddy (ADR-0003).
- Контейнеры: `app`, `caddy`, `db`, `imagor`, `traces-init`, `mesh-receiver`, `draft` (рендер демо, образ из CI —
  ADR-0278) — `docker-compose.yml`, сеть `remlab-net`, ADR-0004; Caddy — `/api/{draft,warm,render,job,share}*`.
- Статика: `/test/*`, `/demo` (ADR-0201), `/rt/*` immutable (ADR-0194, 0212); без парного `redir /x /x/` — 404 без слэша.
- **Caddyfile едет деплоем** (`infra/server/caddy-sync.sh`, ADR-0256), руками не править. **Один сервис — `up -d --no-deps`**.
  Образ `app` — из `/opt/remlab/.env`; нет там — `remlab-app:latest` = откат прода (ADR-0202).

## Сервер
exit-fi (2 vCPU/3.7G/38G), `/opt/remlab`, swap 4G; SSH root@ :22222 (деплой — по умолчанию). Соседей НЕ трогать: remnanode, rw-core,
nginx :80. Секреты — `/opt/remlab/.env`.

## Деплой (ADR-0179)
Push в `main` → CI gate → `Deploy prod` (`deploy.yml`). Сервер — `infra/server/deploy-remote.sh` под `.deploy.lock`: `prev` → образ → БД →
активация. `tools/ops/deploy-need.sh`: доки — без выката, предка прода не катит (ADR-0360), `--status`. `./deploy.sh` — запасной (не с DEV-VM).
**«Прод позади» долго — проверить, что CI собрал образ:** на сервере `docker manifest inspect ghcr.io/igortsk123/remlab-app:<sha>`, `tools/ops/ci-status.sh`
(урок 713). /demo не опережает сервер (ADR-0433).

## Откат / smoke
- smoke = `ok=true` И `version == TARGET_SHA`; не 200 → откат на `prev`. Вручную: `/`=200, `/api/health` ok, remnanode Up.
- Демо: `tools/scout/publish_demo.sh --rollback <метка>` (копии `demo.prev-*`); вне ночи всегда перевыпускает туры (придержать — Tier 2).

## Безопасность (ADR-0207, ADR-0256)
Патчи с публичным RCE — сразу. Заслон `@nextrce` в Caddy не снимать.
ПДн только в базе; после деплоя `tools/security-smoke.sh`; `remlab-draft` выкатывает деплой (ADR-0278).

## Сторожа
Каталог (ADR-0172), диск `cleanup.sh` (ADR-0005), `disk-watchdog.sh`, доступность `health-watch.sh` → Telegram. Правка сервера = бэкап + rollback.
Правило для web-образа — исключением в `.dockerignore`, сторож `tools/ops/docker_context.py` (урок 674).
**Tier 2:** `domain/deployment-details.md` — конвейер, две базы, Caddy и статик, сторожа, `docker-prune.timer` DEV.
