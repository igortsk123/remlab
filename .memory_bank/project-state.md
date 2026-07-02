---
tier: 1
topic: project-state
scope: Снимок «где проект сейчас» — точка ресинхронизации при /clear и resume
tier2: ""
updated: 2026-07-02
importance: high
source: manual
status: working
source_of_truth: canonical
last_verified: 2026-07-01
review_after: ""
---

# Project State — снимок состояния

> Обновлять после каждого крупного изменения. Первое, что читает агент при resume/`/clear`.

## ⚠️ Пивот бизнес-модели v0.2 → v0.3 (2026-07-02, ADR-0014)
Принята модель **v0.3 — `docs/master-brief-v0.3.md` (мастер-документ, приоритет выше v0.2).**
**Affiliate-first freemium, три ступени:** (1) бесплатно — подбор до N (3–5) реальных товаров из фидов
**с открытыми реф-ссылками** (доход ~3%, сеть Гдеслон); (2) платно — «комната целиком» + Cost Engine +
план + PDF (розница ~2 990 ₽, дизайнеры-B2B ~990 ₽/комн.); (3) vision — застройщики «квартира+ремонт в
ипотеку». Рынок РФ→UK (locale-agnostic). Product matching = генерация→поиск похожего в фидах (pgvector).
**Уточнения владельца (2026-07-02) — граница free/paid = уровень «что сделать с комнатой» (3 варианта):**
- **1. «Освежить без ремонта» — бесплатно:** визуализация + до 3 реальных предметов мебели (открыто, реф-ссылки).
- **2. «Недорого обновить» — платно ~1 490 ₽:** мебель любое кол-во + материалы, БЕЗ сметы/чертежей/дизайнера.
- **3. «Ремонт под ключ» — платно 9 900 ₽** (рынок сверен): мебель+материалы+гайды+чертежи+смета
  (Cost Engine)+**живой дизайнер**. Замена дизайнера, но в 5–10× дешевле (дизайн-проект комнаты РФ ~45–100 тыс).
- Реф-ссылки во всех вариантах; материалы подняты в платные Stage 1 (в брифе были Stage 2). **Код-долг:**
  `FREE_VISIBLE=3` верна для вар.1; нужно реальные товары из фидов+реф-ссылки (сейчас seed), варианты 2/3,
  согласование с `interventionLevel`. «Открыть все бесплатно» — НЕВЕРНО.
- **Postgres self-host подтверждён владельцем** — «Supabase» из брифа НЕ берём (ADR-0001/0002). Конфликт закрыт.
**Новые воркстримы Stage 1:** пайплайн фидов Гдеслон (загрузка→нормализация→embeddings→ресинк),
affiliate-трекинг (click_id→постбэк), метрика similarity, лимиты/anti-abuse генераций, вход «похожая мебель
по фото», SEO SSR/SSG. Обновлены: `product_brief`, `core/market`, `core/user-flow`, `core/data-model`,
`core/access-and-integrations`, `source-of-truth`, `CLAUDE.md`, `INDEX`.

## Где
- **Прод:** https://remont-lab.online — ✅ LIVE **Stage 1 + трейсинг пайплайна** (версия `tracing-142829`, 2026-07-02; собрана из ветки `feature/pipeline-tracing`, поэтому прод ВПЕРЕДИ `main`). Контейнеры: `remlab-app`, `remlab-caddy`, `remlab-db`, **`remlab-imagor`** (+ боевая `remnanode` VPN, не задета). Valid LE cert (до 2026-09-29). GEMINI_API_KEY + TRACE_ADMIN_TOKEN в `/opt/remlab/.env`. Бэкапы БД: `/opt/remlab/backups/pre-*.sql.gz` (последний `pre-tracing-20260702-142741`). Откат: образ `remlab-app:prev`. Выкладки **вручную** (`deploy.sh`), авто-деплой ещё не активен.
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
- **M8 (2026-07-01):** e2e happy-path (Playwright, весь путь) — в CI (локально Ubuntu 26.04 не ставит браузер). Фейк-ИИ по флагу (ADR-0010).
  - **Postgres активирован (ADR-0011):** `db/schema.ts` (Drizzle, `projects`=jsonb), `modules/store/pg-repository.ts`; `repo()` выбирает PG при `DATABASE_URL`, иначе in-memory. Проверено на реальной PG (тест `pg-repository.test.ts`, в CI против сервиса postgres). Миграция `pnpm db:migrate` + `db/init/002-projects.sql`.
  - **Прод развёрнут вручную** (`deploy.sh`, сборка локально → образ на сервер), бэкап+rollback, VPN цел. GEMINI_API_KEY добавлен в `/opt/remlab/.env`.
  - **Observability:** лёгкий слой `lib/analytics.ts` — **PostHog** (ADR-0012), no-op без `POSTHOG_KEY`. События воронки: project_started/preview_ready/pack_unlocked + captureError. Sentry не заводим (PostHog free покрывает ошибки).
  - **Прод-фиксы (грабли, устранены):** (1) `Body exceeded 1 MB limit` — фото с телефона >1МБ падало в Server Action → `next.config.mjs experimental.serverActions.bodySizeLimit=12mb`; (2) `/rooms` 500 — `cookies().set()` в рендере страницы запрещён в проде → разделил `getSessionId()` (пишет, для actions) и `readSessionId()` (только чтение, для страниц).
- **⚠️ Авто-деплой настроен, но ЕЩЁ НЕ АКТИВЕН (2026-07-01):** `.github/workflows/deploy.yml` — инкрементальный через **GHCR** (сборка arm64 в раннере с кэшем слоёв → push в `ghcr.io/igortsk123/remlab-app` → сервер `docker compose pull` только изменённых слоёв; `docker-compose.yml` образ = `${REMLAB_IMAGE:-remlab-app:latest}`). Хост — публичный IP в env, нужен **только секрет `DEPLOY_SSH_KEY`**. Прогоны `Deploy prod` зелёные, но **шаги SKIPPED** — гейт не видит `DEPLOY_SSH_KEY` (секрет в GitHub не задан/не сохранён). CI-деплой-ключ `~/.ssh/remlab_ci_deploy` уже добавлен в `authorized_keys` сервера и проверен. **Чтобы активировать:** задать секрет `DEPLOY_SSH_KEY` = приватный `remlab_ci_deploy`. Владелец дал read-only GitHub PAT (у Клода локально, не в репо) — прав на запись секрета/запуск нет; ждём токен с Secrets+Actions write ЛИБО ручную установку секрета.
- Продуктовые решения владельца: ADR-0009 (japandi / restyle фото / «Скоро» для стоимости).

## Трейсинг AI-пайплайна (2026-07-02, ADR-0013) — ветка `feature/pipeline-tracing`
- **Что:** сквозной лог каждого прогона: `generation_runs`(seq=номер генерации)/`generation_steps`/`generation_assets`.
  Захват — в слое провайдеров (`lib/providers/traced.ts` + `runWithTrace` + AsyncLocalStorage): любой вызов LLM
  логирует себя → лог не отстаёт при смене модели/промпта/шага. Реестры: `lib/prompts/registry.ts`,
  `lib/pipelines/registry.ts` (`preview-v1`). Сжатие фото перед LLM — **imagor** (`lib/images/compress.ts`).
- **Разбор:** скилл `/trace`, `pnpm trace <N>`, `GET /api/trace/<N>` + `/asset/<id>` (гард `TRACE_ADMIN_TOKEN`);
  «Генерация #N» на `/preview`; кнопка «Сообщить о проблеме» (`/api/trace/report`). Ретеншн 90 дн (`pnpm trace:prune`).
- **Проверено локально:** typecheck/lint/build зелёные, 9 unit passed (+ `trace.test.ts`; fake-ИИ пишет трейс).
- **✅ ЗАДЕПЛОЕНО В ПРОД (2026-07-02):** версия `tracing-142829` на `remont-lab.online` (health 200). Контейнер
  `remlab-imagor` (`shumc/imagor:latest`, нативный **arm64**) поднят на `remlab-net` internal-only; том
  `remlab-traces` → `/opt/remlab/data/traces`. Trace-таблицы+sequence созданы (миграция 002+003 в `deploy.sh`
  шаг 5b). Sequence сброшен → **первая генерация будет #1**. `TRACE_ADMIN_TOKEN` сгенерирован и лежит в
  `/opt/remlab/.env` (значение НЕ в git/памяти). Бэкап БД перед деплоем: `/opt/remlab/backups/pre-tracing-20260702-142741.sql.gz`.
  Образ `:prev` для отката. VPN-нода `remnanode` цела. Память сервера после: ~822/3806 МБ.
- **⚠️ Ещё НЕ сделано:** `trace:prune` на таймер `remlab-cleanup` (ретеншн — ручной пока); **мердж ветки
  `feature/pipeline-tracing` в `main`** (прод собран из working tree ветки — прод ВПЕРЕДИ main; на ветке же
  лежат доки пивота v0.3). SSH к проду гейтится harness — нужно явное разрешение владельца на деплой.

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
