---
tier: 1
topic: deployment
scope: Деплой/откат/сервер exit-fi
tier2: "domain/deployment-details.md"
updated: 2026-10-18
importance: high
source: manual
status: working
source_of_truth: canonical
last_verified: 2026-10-14
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
  **Один сервис — только `up -d --no-deps`**: иначе `app`
  пересоздаётся на дефолтном образе и прод откатывается (ADR-0202; образ — в `.env`).

## Сервер
exit-fi 89.167.127.0 (2 vCPU/3.7G/38G), compose v2, `/opt/remlab`, swap 4G.
SSH root@: публикация :22222, деплой — порт по умолчанию.
Соседей НЕ трогать: remnanode, rw-core, nginx :80. Секреты — `/opt/remlab/.env` (вне git).

## Деплой (ADR-0179)
Push в `main` → CI gate → `Deploy prod` (`deploy.yml`). Сервер — `infra/server/deploy-remote.sh` под
`.deploy.lock`: `prev` → образ → БД → активация. Детали — Tier 2. `./deploy.sh` — запасной (не с DEV-VM).

## Откат / smoke
- smoke = `ok=true` И `version == TARGET_SHA` (одного 200 мало). Откат — тег `prev` (Tier 2).
  Вручную: `/`=200, `/api/health` ok, remnanode Up.

## Безопасность (ADR-0207, ADR-0256)
Патчи с публичным RCE — сразу (инцидент 08.09: майнер на 15.5.4). Заслон `@nextrce` в Caddy не снимать.
**13.10 (ADR-0256):** ПДн только в базе; без секрета всё закрыто; после деплоя `tools/security-smoke.sh`;
`remlab-draft` выкатывает деплой (ADR-0278), `draft-run.sh` — аварийный. Детали — Tier 2 § Безопасность.

## Сторожа
Каталог (ADR-0172), диск `cleanup.sh` (ADR-0005), безопасность — `disk-watchdog.sh`. Правка сервера = бэкап + rollback.
Доступность — `health-watch.sh` раз в 2 мин → Telegram; копия дампа вне сервера и репетиция восстановления — DEV
`tools/ops/` (ADR-0266). Что ломается без DEV — Tier 2 § «Прод без DEV». DEV-рендер и туннель — юниты `systemctl --user`
(`tools/scout/systemd/`, сторож `tools/scout/dev_render_backend.sh`; 18.10, T-04) — Tier 2 § «DEV-рендер».

**Tier 2:** `domain/deployment-details.md` — конвейер, две базы, Caddy и статик, сторожа.
