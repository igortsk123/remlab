---
tier: 1
topic: project-state
scope: Снимок «где проект сейчас» — точка ресинхронизации при /clear и resume
tier2: ""
updated: 2026-07-01
importance: high
source: manual
status: working
source_of_truth: canonical
last_verified: 2026-07-01
review_after: ""
---

# Project State — снимок состояния

> Обновлять после каждого крупного изменения. Первое, что читает агент при resume/`/clear`.

## Где
- **Прод:** https://remont-lab.online — ✅ LIVE (каркас), валидный Let's Encrypt cert (до 2026-09-29, авто-продление).
- **Репозиторий:** локально `/home/pakar/igor/remlab` (git init; remote — TBD для CI/S4)
- **Окружение / сервер:** exit-fi `89.167.127.0` (Hetzner EU, Ubuntu 24.04, **aarch64/ARM**, 2 vCPU / 3.7 GB / 38 GB). ⚠️ на сервере живёт боевая внутренняя VPN-нода — изоляция обязательна.
- **Деплой:** кросс-сборка arm64 локально (buildx+эмуляция) → `docker save|ssh|docker load` → `docker compose up` в `/opt/remlab`. Скрипт: `deploy.sh`. Playbook: `deployment.md`.

## Что готово к 2026-07-01
- **S1 ✅:** проект remlab по шаблону Memory Bank; обе концепции в `docs/` + intake (archived); `docs/DECISIONS.md`; план `plans/remlab-bootstrap.md`; Memory Bank заполнен; `/memory-check` зелёный.
- **S2 ✅:** exit-fi подготовлен — бэкапы (`/root/backup-remlab/`), swap 4G (swappiness=10), сеть `remlab-net`, `/opt/remlab`, таймеры `remlab-cleanup` (weekly) / `remlab-watchdog` (daily) / `remlab-db-backup` (nightly). VPN-нода не задета.
- **S3 ✅:** каркас Next.js (TS strict, standalone) + Dockerfile + `docker-compose` (Caddy :443 LE / remlab-app / postgres17+pgvector). Стек живой: app Up, db healthy, pgvector 0.8.4 + pg_trgm. HTTPS 200, `/api/health` version=bootstrap-s3. VPN цел, диск 36%, swap ~0.
- **S4:** не начат (CI/тесты — рекоменд.).

## ⚠️ Ключевой факт железа
Сервер **aarch64 (ARM)** → образы собирать под `linux/arm64` (buildx + `tonistiigi/binfmt`). `deploy.sh` уже делает это. Обычный `docker build` на amd64-машине даст неработающий образ (app будет рестартить).

## Ключевые решения (зафиксировано)
- Self-host docker-compose на exit-fi вместо Vercel (ADR-0001).
- БД: `postgres:17 + pgvector` в контейнере, не Supabase Cloud (ADR-0002).
- TLS: Let's Encrypt TLS-ALPN-01 на :443 через Caddy, без :80 (ADR-0003).
- Щедрые лимиты памяти (app 1G / pg 1G / caddy 128M) как страховка blast-radius (ADR-0004).
- Дисковая гигиена/автоочистка + swap 4 GB (ADR-0005).
- Стек: TS strict + Next.js + Drizzle + Zod + Inngest + внешний инференс (спека §1).

## Что НЕ делаем (вне scope сейчас)
Фичи Stage 1/1B (генерация, каталог, paywall, Cost Engine) — только после каркаса (S3) отдельными планами (S5+). Repeat-reference/кухня/ванная/точная смета/подрядчики — не в Stage 1.

## Open questions
- Auth: интерим (anonymous session id) vs GoTrue-контейнер vs Supabase Cloud — решить на Stage 1.
- Realtime статуса job: polling (интерим) vs self-host Realtime — решить на Stage 2.
- git remote (GitHub) для CI (S4) — куда пушим.

## Policies (как ведём разработку)
- План-first (`.claude/rules/agent-workflow.md`): код только после «деплой».
- Не ломать VPN-ноду на exit-fi: бэкап+rollback перед правками сервера, изолированная сеть/лимиты.
- Секреты только в `.env` на сервере, не в git/памяти.
- Гипотезы, не аксиомы: отклонения → `docs/DECISIONS.md`.
- Migration-ready: всё приложение = compose + env + volume-dump + образ.
