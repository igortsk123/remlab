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
- **Прод:** https://remont-lab.online — ✅ LIVE **продуктовый Stage 1** (версия `ba4535000279`, 2026-07-01). Раньше был каркас. Valid LE cert (до 2026-09-29, авто-продление). Postgres в проде, GEMINI_API_KEY в `/opt/remlab/.env`. Бэкап БД перед деплоем: `/opt/remlab/backups/pre-stage1-*.sql.gz`. Откат: образ `remlab-app:prev`. VPN (`remnanode`) не задет.
- **Репозиторий:** github.com/igortsk123/remlab (публичный, ветка `main`, deploy key `~/.ssh/remlab_deploy_ed25519`). CI: GitHub Actions гейт.
- **Окружение / сервер:** exit-fi `89.167.127.0` (Hetzner EU, Ubuntu 24.04, **aarch64/ARM**, 2 vCPU / 3.7 GB / 38 GB). ⚠️ на сервере живёт боевая внутренняя VPN-нода — изоляция обязательна.
- **Деплой:** кросс-сборка arm64 локально (buildx+эмуляция) → `docker save|ssh|docker load` → `docker compose up` в `/opt/remlab`. Скрипт: `deploy.sh`. Playbook: `deployment.md`.

## Что готово к 2026-07-01
- **S1 ✅:** проект remlab по шаблону Memory Bank; обе концепции в `docs/` + intake (archived); `docs/DECISIONS.md`; план `plans/remlab-bootstrap.md`; Memory Bank заполнен; `/memory-check` зелёный.
- **S2 ✅:** exit-fi подготовлен — бэкапы (`/root/backup-remlab/`), swap 4G (swappiness=10), сеть `remlab-net`, `/opt/remlab`, таймеры `remlab-cleanup` (weekly) / `remlab-watchdog` (daily) / `remlab-db-backup` (nightly). VPN-нода не задета.
- **S3 ✅:** каркас Next.js (TS strict, standalone) + Dockerfile + `docker-compose` (Caddy :443 LE / remlab-app / postgres17+pgvector). Стек живой: app Up, db healthy, pgvector 0.8.4 + pg_trgm. HTTPS 200, `/api/health` version=bootstrap-s3. VPN цел, диск 36%, swap ~0.
- **S4 ✅:** регресс-сетка — Vitest (unit) + Playwright (smoke) + GitHub Actions CI-гейт (typecheck+lint+test+build+e2e). Репо на GitHub `igortsk123/remlab` (deploy key, ветка main). CI-run `success`.
- **Bootstrap (S1–S4) завершён** → `completed_plans/remlab-bootstrap.md`.
- **Stage 1 — master roadmap** (`plans/stage1-master-roadmap.md`): M0…M8 подряд. Дизайн-направление: тёплый минимализм japandi/скандинавский (кремовый/беж/greige, дерево, шалфей/терракота).
- **M0 ✅ (2026-07-01):** провайдеры ИИ. Gemini одним ключом: картинки `gemini-3.1-flash-image` (Nano Banana 2), анализ/текст `gemini-flash-latest`. Код `lib/providers/`. Ключ в `.env.local`. Смоук `pnpm smoke:providers` OK. ADR-0007.
- **M1–M7 ✅ (2026-07-01):** продуктовый Stage 1 собран (каркас, но с НАСТОЯЩИМ ИИ):
  - Контракты `contracts/*` (Zod), хранилище `modules/store/` (in-memory, ADR-0008), сессия `lib/session.ts`.
  - Модули: `room-analysis` (vision), `visual-generation` (restyle фото по эталону), `ideas` (идеи+seed-каталог товаров/материалов+бюджет), `generation-job` (оркестратор).
  - Экраны `app/`: landing → `/start` → `/p/[id]/brief`(фото+бриф) → `/style` → `/preview`(AI-превью+идеи+товары/материалы+бюджет+paywall CTA) → `/paywall`(оплата-демо→полный план) → `/rooms`(workspace) + `/soon`(fake-door стоимости). Тема japandi `app/globals.css`.
  - Проверено: typecheck/lint/build зелёные; 8 unit (вкл. интеграцию конвейера на фейк-ИИ); реальный Gemini restyle «до/после» подтверждён визуально.
- **M8 почти готов:** e2e happy-path (Playwright, весь путь) — в CI (локально Ubuntu 26.04 не ставит браузер). Фейк-ИИ по флагу (ADR-0010).
  - **Postgres активирован (ADR-0011):** `db/schema.ts` (Drizzle, `projects`=jsonb), `modules/store/pg-repository.ts`; `repo()` выбирает PG при `DATABASE_URL`, иначе in-memory. Проверено на реальной PG (тест `pg-repository.test.ts`, в CI против сервиса postgres). Миграция `pnpm db:migrate` + `db/init/002-projects.sql`.
  - **Авто-деплой через GitHub (ADR-0011):** `.github/workflows/deploy.yml` после зелёного CI на main → сборка arm64 в раннере → `deploy.sh` (VPN не грузим). **Ждёт разово от владельца:** секреты `DEPLOY_SSH_KEY`, `DEPLOY_HOST` в GitHub + `GEMINI_API_KEY` в `/opt/remlab/.env` на сервере. Без секретов деплой безопасно пропускается.
  - **Осталось:** observability (Sentry/PostHog — опционально, нужны DSN); первый реальный прогон деплоя после установки секретов.
- Продуктовые решения владельца: ADR-0009 (japandi / restyle фото / «Скоро» для стоимости).

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
- **Память: всё durable — только в `.memory_bank/`** (не в локальной памяти Клода). В конце сессии — `/memory-consolidate` → `/memory-check`. Скиллы: init/consolidate/check/cleanup. Концепция: `guides/memory-automation.md`.
