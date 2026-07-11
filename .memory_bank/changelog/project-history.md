---
tier: 2
topic: project-history
scope: Хронология вех/волн проекта (append-only). Снимок «где сейчас» — в project-state.md
tier1: "../project-state.md"
updated: 2026-07-09
importance: normal
source: manual
status: working
source_of_truth: historical
last_verified: 2026-07-09
---

# Project History — хронология проекта (свежее сверху)

> Append-журнал вех: волны работ, крупные merge, смены этапа. Сюда переносится хронология из
> `project-state.md`, когда снимок начинает раздуваться (audit: BLOATED). Папка `changelog/`
> исключена из decision tree и аудита — журнал не грузится в контекст без нужды, но хранит историю.

## Формат записи
```
## YYYY-MM-DD — <веха одной строкой>
<2–5 строк: что сделано/решено, ссылки на планы/ADR>
```

---

<!-- Реальные записи добавляются ниже (сверху — свежие). -->

## 2026-07-02 — Пивот бизнес-модели v0.2 → v0.3 (ADR-0014)
Принята модель **v0.3** — `docs/master-brief-v0.3.md` (мастер-документ, приоритет выше v0.2).
Affiliate-first freemium, три ступени: (1) бесплатно — подбор до N (3–5) реальных товаров из фидов
с открытыми реф-ссылками (доход ~3%, сеть Гдеслон); (2) платно — «комната целиком» + Cost Engine +
план + PDF (розница ~2 990 ₽, дизайнеры-B2B ~990 ₽/комн.); (3) vision — застройщики «квартира+ремонт
в ипотеку». Рынок РФ→UK (locale-agnostic). Product matching = генерация→поиск похожего в фидах (pgvector).
Уточнения владельца (2026-07-02) — граница free/paid = уровень «что сделать с комнатой» (3 варианта):
«Освежить без ремонта» — бесплатно (визуализация + до 3 реальных предметов, реф-ссылки); «Недорого
обновить» — ~1 490 ₽ (мебель любое кол-во + материалы, БЕЗ сметы/чертежей/дизайнера); «Ремонт под
ключ» — 9 900 ₽, рынок сверен (мебель+материалы+гайды+чертежи+смета Cost Engine+живой дизайнер —
замена дизайнера в 5–10× дешевле, дизайн-проект комнаты РФ ~45–100 тыс). Реф-ссылки во всех вариантах;
материалы подняты в платные Stage 1 (в брифе были Stage 2). Postgres self-host подтверждён владельцем —
«Supabase» из брифа НЕ берём (ADR-0001/0002), конфликт закрыт. Обновлены: `product_brief`, `core/market`,
`core/user-flow`, `core/data-model`, `core/access-and-integrations`, `source-of-truth`, `CLAUDE.md`, `INDEX`.

## 2026-07-02 — Трейсинг AI-пайплайна реализован и задеплоен в прод (ADR-0013)
Ветка `feature/pipeline-tracing`. Сквозной лог каждого прогона: `generation_runs` (seq=номер генерации) /
`generation_steps` / `generation_assets`; захват в слое провайдеров (`lib/providers/traced.ts` +
`runWithTrace` + AsyncLocalStorage) — любой вызов LLM логирует себя, лог не отстаёт при смене
модели/промпта/шага. Реестры: `lib/prompts/registry.ts`, `lib/pipelines/registry.ts` (`preview-v1`).
Сжатие фото перед LLM — imagor (`lib/images/compress.ts`). Разбор: скилл `/trace`, `pnpm trace <N>`,
`GET /api/trace/<N>` + `/asset/<id>` (гард `TRACE_ADMIN_TOKEN`), «Генерация #N» на `/preview`, кнопка
«Сообщить о проблеме» (`/api/trace/report`). Ретеншн 90 дн (`pnpm trace:prune`). Проверено локально:
typecheck/lint/build зелёные, 9 unit passed (+ `trace.test.ts`; fake-ИИ пишет трейс).
Деплой: версия `tracing-142829` на remont-lab.online (health 200); контейнер `remlab-imagor`
(`shumc/imagor:latest`, нативный arm64) на `remlab-net` internal-only; том `remlab-traces` →
`/opt/remlab/data/traces`; trace-таблицы+sequence созданы (миграции 002+003 в `deploy.sh` шаг 5b),
sequence сброшен → первая генерация #1. `TRACE_ADMIN_TOKEN` сгенерирован → `/opt/remlab/.env` (не в
git/памяти). Бэкап БД `pre-tracing-20260702-142741.sql.gz`; образ `:prev` для отката; VPN-нода
`remnanode` цела; память сервера после ~822/3806 МБ. Прод собран из working tree ветки → прод ВПЕРЕДИ `main`.

## 2026-07-01 — Stage 1 продукт M0–M8: реальный ИИ, Postgres, ручной прод-деплой, observability
Roadmap: `plans/stage1-master-roadmap.md` (M0…M8 подряд); дизайн-направление — тёплый минимализм
japandi/скандинавский (кремовый/беж/greige, дерево, шалфей/терракота).
- **M0:** провайдеры ИИ — Gemini одним ключом: картинки `gemini-3.1-flash-image` (Nano Banana 2),
  анализ/текст `gemini-flash-latest`; код `lib/providers/`; ключ в `.env.local`; смоук
  `pnpm smoke:providers` OK (ADR-0007).
- **M1–M7:** продуктовый Stage 1 (каркас с настоящим ИИ): контракты `contracts/*` (Zod), хранилище
  `modules/store/` (in-memory, ADR-0008), сессия `lib/session.ts`; модули room-analysis (vision),
  visual-generation (restyle фото по эталону), ideas (идеи+seed-каталог товаров/материалов+бюджет),
  generation-job (оркестратор); экраны landing → `/start` → `/p/[id]/brief` → `/style` → `/preview`
  (AI-превью+идеи+товары/материалы+бюджет+paywall CTA) → `/paywall` (оплата-демо→полный план) →
  `/rooms` + `/soon` (fake-door стоимости); тема japandi `app/globals.css`. Typecheck/lint/build
  зелёные; 8 unit (вкл. интеграцию конвейера на фейк-ИИ); реальный Gemini restyle «до/после»
  подтверждён визуально. Продуктовые решения владельца: ADR-0009.
- **M8:** e2e happy-path (Playwright, весь путь) — в CI (локально Ubuntu 26.04 не ставит браузер);
  фейк-ИИ по флагу (ADR-0010). Postgres активирован (ADR-0011): `db/schema.ts` (Drizzle,
  `projects`=jsonb), `modules/store/pg-repository.ts`; `repo()` выбирает PG при `DATABASE_URL`,
  иначе in-memory; проверено на реальной PG (`pg-repository.test.ts`, в CI против сервиса postgres);
  миграция `pnpm db:migrate` + `db/init/002-projects.sql`.
- **Прод развёрнут вручную** (`deploy.sh`, сборка локально → образ на сервер), бэкап+rollback, VPN цел.
  GEMINI_API_KEY добавлен в `/opt/remlab/.env`.
- **Observability:** `lib/analytics.ts` — PostHog (ADR-0012), no-op без `POSTHOG_KEY`; события воронки
  project_started/preview_ready/pack_unlocked + captureError. Sentry не заводим (PostHog free покрывает ошибки).
- **Прод-грабли (устранены):** (1) `Body exceeded 1 MB limit` — фото с телефона >1МБ падало в Server
  Action → `next.config.mjs experimental.serverActions.bodySizeLimit=12mb`; (2) `/rooms` 500 —
  `cookies().set()` в рендере страницы запрещён в проде → разделены `getSessionId()` (пишет, для
  actions) и `readSessionId()` (только чтение, для страниц).
- **Авто-деплой настроен, НЕ активирован:** `.github/workflows/deploy.yml` — инкрементальный через GHCR
  (сборка arm64 в раннере с кэшем слоёв → push в `ghcr.io/igortsk123/remlab-app` → сервер
  `docker compose pull`; `docker-compose.yml` образ = `${REMLAB_IMAGE:-remlab-app:latest}`). Прогоны
  `Deploy prod` зелёные, но шаги SKIPPED — секрет `DEPLOY_SSH_KEY` в GitHub не задан. CI-ключ
  `~/.ssh/remlab_ci_deploy` добавлен в `authorized_keys` сервера и проверен. Владелец дал read-only
  GitHub PAT (у Клода локально, не в репо) — прав на запись секрета нет; ждём токен Secrets+Actions
  write либо ручную установку секрета.

## 2026-07-01 — Bootstrap S1–S4 завершён (`completed_plans/remlab-bootstrap.md`)
- **S1:** проект remlab по шаблону Memory Bank; обе концепции в `docs/` + intake (archived);
  `docs/DECISIONS.md`; план `plans/remlab-bootstrap.md`; Memory Bank заполнен; `/memory-check` зелёный.
- **S2:** exit-fi подготовлен — бэкапы (`/root/backup-remlab/`), swap 4G (swappiness=10), сеть
  `remlab-net`, `/opt/remlab`, таймеры `remlab-cleanup` (weekly) / `remlab-watchdog` (daily) /
  `remlab-db-backup` (nightly). VPN-нода не задета.
- **S3:** каркас Next.js (TS strict, standalone) + Dockerfile + `docker-compose` (Caddy :443 LE /
  remlab-app / postgres17+pgvector). Стек живой: app Up, db healthy, pgvector 0.8.4 + pg_trgm;
  HTTPS 200, `/api/health` version=bootstrap-s3. Обнаружен aarch64 → кросс-сборка arm64 (ADR-0006).
  VPN цел, диск 36%, swap ~0.
- **S4:** регресс-сетка — Vitest (unit) + Playwright (smoke) + GitHub Actions CI-гейт
  (typecheck+lint+test+build+e2e). Репо GitHub `igortsk123/remlab` (deploy key, ветка main). CI-run `success`.

## 2026-07-11 — Яндекс-доступы, семантика Вордстат, починка CI gate
- Доступы Wordstat/Директ/Метрика перенесены из v0-health-card (значения — `_secrets/ACCESS.md`),
  проверены живыми вызовами; исправлены имена эндпоинтов из доки соседей (`regions`, PERIOD_MONTHLY).
- Собрана семантика ниши (~70 масок, 6+3 кластера, динамика 24 мес, регионы) →
  `domain/wordstat-semantics.md` + новая Tier 1 `core/marketing-acquisition.md`. Неявный спрос
  проверен: «под ключ»/мебель «недорого» в лоб не брать, mid-funnel цены (~95k) — в эшелон 3.
- **CI gate был красный с 2026-07-02** (7 прогонов): 7f970ad сменил флоу на /select, e2e не обновили.
  Спека переписана (16181c8), проверена в докере playwright v1.51.1 (4/4), запушена. Урок →
  `core/regression-net.md` (грабля).
