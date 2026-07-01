---
tier: 2
topic: deployment
scope: Playbook прод-деплоя, smoke-тест и откат
tier1: "core/architecture.md"
updated: 2026-07-01
importance: high
source: manual
---

# Deployment — playbook

> ⚠️ Хост делит боевую внутреннюю VPN-ноду (remnanode/rw-core/warp). НЕ ломать её. Всё — изолированно.
> Статус на 2026-07-01: ✅ LIVE — каркас развёрнут (S2+S3). https://remont-lab.online отдаёт 200, LE-cert валиден.
> ⚠️ **Сервер aarch64 (ARM)** — образы ТОЛЬКО под `linux/arm64` (buildx + binfmt); `deploy.sh` это делает. Обычный `docker build` на amd64 → app рестартит.

## Production
- 🌐 URL: https://remont-lab.online (домен GoDaddy, A → 89.167.127.0, без CF-прокси)
- 🔒 Сертификат: Let's Encrypt, TLS-ALPN-01 на :443, авто-продление Caddy (ADR-0003)
- 📦 Контейнеры: `remlab-app` (Next.js `next start`, :3000 internal), `remlab-caddy` (:443), `remlab-db` (postgres:17+pgvector, volume `remlab-db`). `restart: unless-stopped`, mem_limit app 1G / pg 1G / caddy 128M (ADR-0004)
- 🌉 Прокси: Caddy (не системный nginx — он у VPN на :80)

## Сервер / окружение
- Хост: exit-fi `89.167.127.0` (Hetzner, Ubuntu 24.04). 2 vCPU / 3.7 GB / 38 GB. Docker + compose v2.
- Рабочая директория: `/opt/remlab`. Docker-сеть: `remlab-net` (изоляция от VPN).
- Особенности: swap 4 GB (swappiness=10); iptables INPUT=DROP, :443 открыт, :80 закрыт; SSH `root@` (также :22222).
- Соседи (НЕ трогать): `remnanode` + `rw-core` (:8444/:9443/:2222), системный nginx :80.

## Пайплайн (сборка локально → образ на сервер)
1. Локально: `pnpm typecheck && pnpm lint && pnpm test && pnpm build`.
2. Кросс-сборка arm64: `docker buildx build --platform linux/arm64 --load -t remlab-app:<tag>` (нужен `tonistiigi/binfmt --install arm64` + buildx builder `remlabx`). Всё это делает `./deploy.sh <tag>`.
3. Сохранить предыдущий образ на сервере как `remlab-app:prev` (для отката).
4. `docker save remlab-app:<tag> | gzip | ssh root@89.167.127.0 'gunzip | docker load'`.
5. `ssh ... 'cd /opt/remlab && docker compose up -d'`.
6. Smoke-test (ниже). Провал → откат на `:prev`.
7. Очистка: оставить последние 2 тега `remlab-app`, `docker image prune -f` (dangling, scoped — образ VPN не трогать).
(Автоматизировано в `deploy.sh` — S3.)

## Ручной откат
```
ssh root@89.167.127.0 'cd /opt/remlab && docker tag remlab-app:prev remlab-app:latest && docker compose up -d'
```

## Smoke-test (после деплоя — обязательно)
```
curl -s -o /dev/null -w "%{http_code}\n" https://remont-lab.online/        # 200
curl -s https://remont-lab.online/api/health                                # {"ok":true,...}
# VPN цел:
ssh root@89.167.127.0 'docker ps --format "{{.Names}} {{.Status}}" | grep remnanode'   # Up
ssh root@89.167.127.0 'ss -tlnp | grep -E ":8444|:9443|:2222"'                          # на месте
```

## Автоочистка / защита от переполнения (ADR-0005)
- Логи Docker: json-file `max-size=10m max-file=3` (daemon.json).
- weekly systemd-timer `remlab-cleanup`: dangling-образы, build-cache, stopped remlab-контейнеры (без глобального `system prune -a`).
- Бэкап БД: ночной `pg_dump` в `/opt/remlab/backups`, хранить последние 7.
- df-watchdog: алерт при >80%.

## Секреты
`.env` в `/opt/remlab` (вне git, вне Memory Bank): `DATABASE_URL`, ключи инференса/платёжки, `SENTRY_DSN`, `POSTHOG_KEY`. В репо — `.env.example`.

## Принципы
- Верифицируй деплой, не предполагай: health-эндпоинт с версией/commit, поллить до совпадения.
- Перед правкой сервера — бэкап (iptables-save, cp конфигов), rollback записан в плане.
- Не трогать общие конфиги VPN (системный nginx, iptables-правила ноды) без нужды.
