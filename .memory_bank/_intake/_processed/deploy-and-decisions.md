# Инфраструктура, деплой и подтверждённые решения (2026-07-01)

## Хостинг
- **Сервер:** exit-fi, `89.167.127.0`, Hetzner (EU/Финляндия), Ubuntu 24.04, 2 vCPU / 3.7 GB RAM / 38 GB диск.
- ⚠️ **Это боевая VPN exit-нода** проекта VPN (remnanode + rw-core + warp). VPN внутренний (не платный, для своих). Правило: не ломать существующие подключения, работать изолированно, свои свободные порты, бэкап+rollback перед правками.
- Порт **:443 (tcp/udp) свободен** и открыт в iptables (INPUT policy DROP, 443 ACCEPT). Порт **:80 снаружи закрыт**.
- remnanode держит :8444/:9443/:2222; nginx — только :80 default. Наш стек их не трогает.

## Домен и TLS
- Домен: **remont-lab.online**, A-запись на **GoDaddy** → `89.167.127.0` (прямая, без Cloudflare-прокси).
- **TLS: Let's Encrypt через TLS-ALPN-01 на :443** (Caddy, авто-выпуск и авто-продление). :80 не открываем.

## Стратегия деплоя (migration-ready)
- **Сборка локально** (dev-машина, RAM до 12 GB): `pnpm build` + `docker build` + тесты + CI.
- На сервер уезжает **только готовый образ**: `docker save | gzip | ssh | docker load` (GHCR — позже).
- Рантайм на сервере лёгкий: `next start` в контейнере.
- Всё приложение = `docker-compose` + `.env` + volume-dump БД + образ → переезд копированием этих артефактов.
- Путь на сервере: `/opt/remlab`. Docker-сеть: `remlab-net` (изоляция от VPN).

## Целевая архитектура (стартовая)
```
Caddy :443 (LE auto-renew) → remlab-app :3000 (Next.js) → postgres:17+pgvector (volume remlab-db)
```

## Подтверждённые решения
- **БД:** контейнер `postgres:17 + pgvector` на exit-fi (не Supabase Cloud). Volume + ночной `pg_dump`.
- **Swap:** 4 GB, `vm.swappiness=10`.
- **Лимиты памяти (щедрые, как страховка blast-radius):** remlab-app 1 GB, postgres 1 GB (shared_buffers=128MB), caddy 128 MB. Подтверждено владельцем.
- **Дисковая гигиена / автоочистка:** ротация логов Docker (json-file max-size=10m max-file=3); очистка старых образов после каждого деплоя (последние 2 тега remlab-app, prune dangling, scoped — VPN-образ не трогаем); еженедельный systemd-timer remlab-cleanup (dangling + build-cache + stopped remlab); ротация бэкапов БД (последние 7); df-watchdog (алерт при >80%).

## Секреты (дисциплина)
Секреты только в `.env` на сервере (вне git и вне Memory Bank). В репо — `.env.example`. Не хранить в памяти: токены API, пароли БД, ключи платёжки, DSN.

## План работ
Верхнеуровневый план + подпланы по сессиям — в `.memory_bank/plans/remlab-bootstrap.md`.
Порядок: S1 (этот каркас памяти) → S2 (подготовка сервера) → S3 (каркас Next.js + контейнеры) → S4 (CI/тесты) → S5+ (фичи по тех-спеке: Stage 0 спайки → Stage 1 …).
