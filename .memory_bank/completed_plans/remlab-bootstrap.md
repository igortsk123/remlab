---
workstream: bootstrap
slug: remlab-bootstrap
status: completed
created: 2026-07-01
updated: 2026-07-01
completed: 2026-07-01
---

## Цель
Развернуть полностью независимый проект **remlab** (AI-помощник по ремонту) по шаблону Memory Bank + подготовить сервер exit-fi (89.167.127.0) + запустить изолированный контейнерный стек (Next.js + postgres/pgvector за Caddy/LE) — migration-ready.

## Источник задачи
Пользователь: развернуть remlab на exit-fi отдельным контейнером (чтобы быстро перенести потом), swap 4GB, БД в контейнере, домен remont-lab.online (GoDaddy A→89.167.127.0), Let's Encrypt авто-продление, автоочистка/защита от переполнения диска, щедрые лимиты памяти. Сборка локально → пуш образа. Сначала план, затем выполнение (подтверждено).

## Верхнеуровневый план (эпики)
- **M1** Каркас проекта + Memory Bank (S1) — локально, риск 0.
- **M2** Подготовка сервера exit-fi (S2) — prod, обратимо.
- **M3** Каркас Next.js + контейнеры (S3) — доставка на прод.
- **M4** (рекоменд.) Регресс-сетка CI/тесты (S4).
- **M5+** Фичи по тех-спеке (Stage 0 спайки → Stage 1 → …) — отдельные подпланы.

## Подпланы по сессиям

### S1 — Memory Bank + скелет (локально) [in_progress]
- [x] Создать /home/pakar/igor/remlab, git init
- [x] apply.sh (template + skills)
- [x] intake: goal.md, deploy-and-decisions.md, обе концепции (docs/ + _intake/brief)
- [x] docs/DECISIONS.md
- [x] сохранить этот план
- [ ] /memory-init (сгенерить core/, source-of-truth, project-state, decisions, заполнить CLAUDE.md/INDEX)
- [ ] /memory-check зелёный

### S2 — Подготовка сервера exit-fi (prod, обратимо)
- [ ] Бэкап: iptables-save, /etc/nginx, /etc/docker/daemon.json, снимок docker ps/портов → /root/backup-remlab/
- [ ] Swap 4 GB + vm.swappiness=10 (fstab + sysctl)
- [ ] mkdir /opt/remlab; docker network create remlab-net
- [ ] Ротация логов Docker (daemon.json json-file max-size=10m max-file=3) + проверка что remnanode поднялся
- [ ] systemd-timer remlab-cleanup (dangling + build-cache + stopped remlab) + df-watchdog (>80%)
- [ ] Проверка: remnanode Up, rw-core :8444/:9443/:2222 целы, :443 свободен, dig remont-lab.online
- Rollback: swapoff+удалить swapfile; iptables-restore; удалить remlab-net и /opt/remlab; вернуть daemon.json

### S3 — Каркас Next.js + БД + контейнеры (на прод)
- [ ] Next.js (TS strict, output standalone), структура §2 спеки, healthcheck-страница
- [ ] docker-compose: caddy(:443 LE ALPN) + remlab-app(:3000) + postgres:17+pgvector (volume remlab-db); mem-лимиты (app 1G / pg 1G / caddy 128M); logging limits; restart unless-stopped; сеть remlab-net
- [ ] Multi-stage Dockerfile; локальная сборка → docker save|gzip|ssh|docker load
- [ ] .env на сервере (секреты вне git), .env.example в репо; CREATE EXTENSION vector
- [ ] deploy.sh (build→push→up + очистка старых образов, scoped) + rollback
- [ ] ночной pg_dump в /opt/remlab/backups (rotate 7) в timer
- DoD: https://remont-lab.online → 200 + валидный LE cert; pgvector живой; VPN цел; деплой/откат/бэкап/автоочистка по скриптам

### S4 (рекоменд.) — Регресс-сетка
- [ ] Vitest + Playwright golden-path smoke + GitHub Actions CI-гейт; Sentry/PostHog обёртки

### S5+ — Фичи (отдельные планы)
Stage 0 спайки (латентность инференса из EU, бенч §8.3) → Stage 1 каркас → генерация free → каталог+matching → paywall → compose → Cost Engine.

## Критерии приёмки (bootstrap)
- [ ] remlab самодостаточен, Memory Bank заполнен, /memory-check зелёный
- [ ] exit-fi: swap+гигиена работают, VPN не задет, rollback записан
- [ ] контейнерный стек живой на https://remont-lab.online, migration-ready
- [ ] секретов в git/памяти нет

## Лог выполнения
- 2026-07-01 — план создан, S1 начат (scaffold + intake + docs готовы)
- 2026-07-01 — **S1 ✅** Memory Bank заполнен, `/memory-check` зелёный (22 дока).
- 2026-07-01 — **S2 ✅** exit-fi: бэкапы, swap 4G, `remlab-net`, `/opt/remlab`, 3 systemd-таймера (cleanup/watchdog/db-backup). VPN цел, :443 свободен, DNS резолвится.
- 2026-07-01 — **S3 ✅** каркас Next.js (TS strict, standalone) + Docker + compose (Caddy/app/pg17+pgvector). Обнаружено: сервер **aarch64** → перешли на кросс-сборку arm64 (ADR-0006). Прод LIVE: https://remont-lab.online 200, LE-cert валиден, pgvector 0.8.4. VPN цел.
- 2026-07-01 — **S4 ✅** Vitest unit + Playwright smoke + GitHub Actions CI-гейт. Пуш в GitHub (igortsk123/remlab, deploy key). CI-run `success` (typecheck+lint+test+build+e2e браузерный).

## Completion summary
Bootstrap выполнен полностью (S1–S4). remlab — независимый проект по шаблону Memory Bank (обе концепции в docs/, 6 ADR). Сервер exit-fi подготовлен изолированно (swap 4G, remlab-net, 3 systemd-таймера: cleanup/watchdog/db-backup), VPN-нода не задета. Контейнерный стек (Caddy LE :443 + Next.js + postgres17/pgvector) живой на https://remont-lab.online (arm64, кросс-сборка). Репо на GitHub, CI-гейт зелёный. Rollback: образ `remlab-app:prev` + `/root/backup-remlab/`. Следующее: `plans/stage1-skeleton.md` (draft) либо Stage 0 спайки (нужны ключи инференса/каталог).

## Follow-up work
- [ ] S5+ подпланы по мере подхода к фичам
