---
tier: 1
topic: project-state
scope: Снимок «где проект сейчас» — точка ресинхронизации при /clear и resume
tier2: "changelog/project-history.md"
updated: 2026-07-11
importance: high
source: manual
status: working
source_of_truth: canonical
last_verified: 2026-07-09
---

# Project State — снимок состояния

> Это СНИМОК «где проект сейчас», НЕ журнал (держи ≤ ~8 KB). Обновляя,
> ПЕРЕПИСЫВАЙ разделы под текущее состояние, а не дописывай хронологию: история сессий/волн —
> append в `changelog/project-history.md`, завершённые планы — в `completed_plans/`. Снимок =
> что истинно СЕЙЧАС + ссылки. Первое, что читает агент при resume/`/clear`; обновил — `updated:`.

> ⚠️ TODO: снимок сверен на 2026-07-02; работы 2026-07-05…09 не подняты —
> см. `plans/MASTER-roadmap.md`, `plans/` (драфты), `completed_plans/`.

## Планирование (2026-07-11) — коммерческий трек
Проведён полный аудит проекта (3 explore-агента + 2 план-агента + веб-ресёрч рынка); оценки:
идея 8/10, текущее состояние 6/10. Создан **`plans/commercial-master-plan.md`** (конвейер
«Деньги»: Э0–Э8, гейты, kill-критерии; ∥ конвейер «Ядро» = [[MASTER-roadmap]]) + **10 подпланов
`plans/sub-*.md`** для исполнителя Opus 4.8 + правила исполнения `guides/execution-playbook.md`
(чекпоинты ⏸ владельца, эскалация). Первый к исполнению — `sub-e0-stopkran`; параллельно
`sub-ml-sizes` (приоритет владельца: размеры плавают). sub-e5/sub-e6 записаны черновиками
без verify-прохода (пометка в их логе). Tier 0 ужат (TIER0-BLOAT закрыт), audit чисто.

## Где
- **Стадия:** Stage 1 LIVE в проде; принят пивот модели **v0.3** (ADR-0014), идёт доводка кода.
- **Прод:** https://remont-lab.online — версия `tracing-142829` (2026-07-02), собрана из ветки
  `feature/pipeline-tracing` → **прод ВПЕРЕДИ `main`**. Контейнеры: `remlab-app`,
  `remlab-caddy`, `remlab-db` (pg17+pgvector), `remlab-imagor`. LE-cert до 2026-09-29. Секреты —
  только `/opt/remlab/.env`. Бэкапы БД: `/opt/remlab/backups/`. Откат: образ `remlab-app:prev`.
- **Репозиторий:** github.com/igortsk123/remlab (`main`, deploy key `~/.ssh/remlab_deploy_ed25519`).
  CI: GitHub Actions гейт.
- **Сервер:** exit-fi `89.167.127.0` (Hetzner EU, Ubuntu 24.04, **aarch64/ARM**, 2 vCPU / 3.7 GB / 38 GB).
  НЕ выделенный remlab-сервер: на хосте боевая VPN-нода `remnanode` (+`rw-core`, nginx :80) — не
  трогать; remlab изолирован (`remlab-net`, mem-лимиты).
- **Деплой:** вручную `./deploy.sh` — кросс-сборка **linux/arm64** (buildx+binfmt) → образ по ssh →
  `compose up` → smoke. ⚠️ `docker build` на amd64 даст нерабочий образ. Авто-деплой через GHCR
  настроен, но **НЕ активен** (нет секрета `DEPLOY_SSH_KEY`). Playbook: `deployment.md`.

## Бизнес-модель v0.3 (мастер: `docs/master-brief-v0.3.md`, приоритет над v0.2)
Affiliate-first freemium; граница free/paid = «что сделать с комнатой»: (1) «Освежить без ремонта» —
**бесплатно**: визуализация + до 3 реальных товаров с реф-ссылками (Гдеслон, ~3%); (2) «Недорого
обновить» — **~1 490 ₽**: мебель без лимита + материалы, БЕЗ сметы/чертежей/дизайнера; (3) «Ремонт
под ключ» — **9 900 ₽**: + гайды/чертежи/смета (Cost Engine) + живой дизайнер. B2B ~990 ₽/комн.;
vision — застройщики. Реф-ссылки везде. Рынок РФ→UK. Matching: генерация → похожее в фидах (pgvector).
Детали: `product_brief.md` + `core/{market,user-flow,data-model,access-and-integrations}.md`.
- **Код-долг v0.3:** `FREE_VISIBLE=3` верна только для вар.1; нужны реальные товары из фидов +
  реф-ссылки (сейчас seed), варианты 2/3, согласование с `interventionLevel`. «Открыть все бесплатно» — НЕВЕРНО.
- **Новые воркстримы Stage 1:** фиды Гдеслон (загрузка→нормализация→embeddings→ресинк), affiliate-трекинг
  (click_id→постбэк), метрика similarity, лимиты/anti-abuse генераций, «похожая мебель по фото», SEO SSR/SSG.

## Что готово (со ссылками)
- **Bootstrap S1–S4** (Memory Bank, сервер, каркас, регресс-сетка) — `completed_plans/remlab-bootstrap.md`.
- **Stage 1 M0–M8** — `plans/stage1-master-roadmap.md`: Gemini-провайдеры `lib/providers/` (ADR-0007);
  контракты `contracts/*` (Zod); store in-memory → Postgres/Drizzle (ADR-0008/0011); модули
  room-analysis / visual-generation / ideas / generation-job; экраны landing→brief→style→preview→
  paywall→rooms (+`/soon`); тема japandi; e2e в CI, фейк-ИИ по флагу (ADR-0010).
- **Observability** — `lib/analytics.ts` → PostHog (ADR-0012), no-op без ключа; воронка + captureError.
- **Трейсинг AI-пайплайна в проде** (ADR-0013) — `generation_runs/steps/assets`, захват в слое
  провайдеров, реестры промптов/пайплайнов, imagor-сжатие; разбор: `/trace` (гард
  `TRACE_ADMIN_TOKEN`); ретеншн 90 дн `pnpm trace:prune` (пока вручную) —
  `core/observability-tracing.md`, `completed_plans/pipeline-tracing.md`.
- Хронология вех/сессий — `changelog/project-history.md`.

## Ключевые решения (строкой; полные — `decisions.md`, `docs/DECISIONS.md`)
ADR-0001 self-host compose на exit-fi, не Vercel · 0002 pg17+pgvector в контейнере, не Supabase ·
0003 LE TLS-ALPN-01 :443 через Caddy · 0004 mem-лимиты app 1G/pg 1G/caddy 128M ·
0005 автоочистка+swap 4G · 0006 кросс-сборка arm64 · 0007 Gemini одним ключом · 0008 in-memory
store → 0011 Postgres при `DATABASE_URL` · 0009 japandi / restyle фото / «Скоро» для стоимости ·
0010 фейк-ИИ по флагу (e2e) · 0012 PostHog, без Sentry · 0013 трейсинг пайплайна · 0014 пивот v0.3.
Стек: TS strict + Next.js + Drizzle + Zod + Inngest + внешний инференс (спека §1).

## Что НЕ делаем (вне scope сейчас)
Repeat-reference / кухня / ванная / точная смета / подрядчики — не в Stage 1.

## Open questions / TODO
- Мердж `feature/pipeline-tracing` → `main` (на ветке и доки v0.3). SSH к проду гейтится harness —
  деплой только с явного разрешения владельца.
- Активировать авто-деплой: секрет `DEPLOY_SSH_KEY` (= приватный `~/.ssh/remlab_ci_deploy`, уже в
  `authorized_keys`); у Клода read-only PAT — нужен Secrets+Actions write или ручная установка.
- `trace:prune` повесить на таймер `remlab-cleanup`.
- Код под v0.3 — см. «Код-долг» выше.
- Auth: anonymous session id (интерим) vs GoTrue vs Supabase Cloud — Stage 1.
- Realtime статуса job: polling (интерим) vs self-host — Stage 2.
- Поднять в снимок работы 2026-07-05…09 (плашка вверху).

## Policies (как ведём разработку)
- План-first (`.claude/rules/agent-workflow.md`): код только после «деплой».
- Не ломать VPN-ноду на exit-fi: бэкап+rollback перед правками сервера, изоляция сети/лимиты.
- Секреты только в `.env` на сервере, не в git/памяти.
- Гипотезы, не аксиомы: отклонения → `docs/DECISIONS.md`.
- Migration-ready: приложение = compose + env + volume-dump + образ.
- **Память: durable — только в `.memory_bank/`.** Конец сессии — `/memory-check` (свод+гигиена);
  концепция — `guides/memory-automation.md`.
