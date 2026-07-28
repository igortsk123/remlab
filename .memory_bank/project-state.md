---
tier: 1
topic: project-state
scope: Снимок «где проект сейчас» — точка ресинхронизации при /clear и resume
tier2: "changelog/project-history.md"
updated: 2026-07-28
importance: high
source: manual
status: working
source_of_truth: canonical
last_verified: 2026-07-28
---

# Project State — снимок состояния

> Это СНИМОК «где проект сейчас», НЕ журнал (держи ≤ ~8 KB). Обновляя,
> ПЕРЕПИСЫВАЙ разделы под текущее состояние, а не дописывай хронологию: история сессий/волн —
> append в `changelog/project-history.md`, завершённые планы — в `completed_plans/`. Снимок =
> что истинно СЕЙЧАС + ссылки. Первое, что читает агент при resume/`/clear`; обновил — `updated:`.

## Где
- **Стадия:** v0.4 «Смета-first» (ADR-0016); ядро сметы М1 в проде (входы А/Б, чек-лист, /go/ реф) —
  `core/estimate.md`. Автопилот рекламы DRY-RUN на все кампании — `advertising/autopilot.md`.
- **Запуск (launch-prep, 2026-07-28): ЗОНТ ЗАКРЫТ — платформа ГОТОВА К ЗАПУСКУ.** П1–П7 выкачены — П1 витрина-заглушки; П2 «Моя лаборатория»
  = центр сохранений (список расчётов, счётчик-бейдж, cookie 30 дн); П3 UX калькуляторов (VizCta
  скрыт, LeadCard-баннер без дублей, подсказки «что дальше», «?» раппорт/шов, «новый расчёт» +
  автоочистка черновика после сохранения); П4 масштаб 100–130% (CSS zoom, ZoomControl в шапке) +
  мобильные правки; П5-ядро чтения ссылок (фикс цены-артикула, htmlToText для LLM, пометки
  авто/вручную autoKeys, «Нашли: <товар>»); П7 лид-канал «найдём дешевле» (модалка с городом-
  автокомплитом ~1106 городов, служебный TG-бот, ответ реплаем; АКТИВАЦИЯ по токенам владельца —
  `core/leads.md`); П6 финал (e2e лаборатория+заглушки, сверка рекламы: все кампании SUSPENDED,
  Этап 2/AI-дизайн НЕ включать — ведут на заглушки). Ждут владельца: токены 3 ботов + SMTP, адрес
  РФ-прокси (П5b), включение Этапа 1 рекламы.
- **Калькулятор v2 UX-полировка (2026-07-21…22, ADR-0018–0027):** NumInput, липкая шапка, плитка
  стены+пол разными плитками, автозаполнение по ссылке (regex + ИИ-фолбэк OpenAI), лид-карточка,
  проёмы убраны из UI (ADR-0027). Детали — `core/estimate.md`, `decisions.md`.
- **Прод:** https://remont-lab.online — версия = git SHA (АВТО-деплой на каждый push в main,
  нативный arm64-раннер, с 2026-07-28). Контейнеры: `remlab-app`,
  `remlab-caddy`, `remlab-db` (pg17+pgvector), `remlab-imagor`. LE-cert до 2026-09-29. Секреты —
  только `/opt/remlab/.env`. Бэкапы БД: `/opt/remlab/backups/`. Откат: образ `remlab-app:prev`.
- **Репозиторий:** github.com/igortsk123/remlab (`main`, CI-deploy-ключ `~/.ssh/remlab_ci_deploy` —
  авторизован на сервере как `remlab-ci-deploy`; для секрета `DEPLOY_SSH_KEY`. `remlab_deploy_ed25519` НЕ авторизован).
  CI: GitHub Actions гейт.
- **Память (инфра):** кит Memory Bank **v1.3.0** (2026-07-12, план `completed_plans/kit-align-v13`).
  Аудит ловит CODE-REF (память↔код) и FROZEN-MEMORY; CI `.github/workflows/memory-audit.yml` в режиме
  **`warn`** (`_kit/gate-mode.txt`; флип в `block` — позже); захват на ходу `_intake/session-scratch.md`;
  метрики footprint+находки → `changelog/metrics.log` (`tools/metrics-append.sh`). Footprint Tier 0 ≈ 2.1%.
- **Сервер:** exit-fi `89.167.127.0` (Hetzner EU, Ubuntu 24.04, **aarch64/ARM**, 2 vCPU / 3.7 GB / 38 GB).
  НЕ выделенный remlab-сервер: на хосте боевая VPN-нода `remnanode` (+`rw-core`, nginx :80) — не
  трогать; remlab изолирован (`remlab-net`, mem-лимиты).
- **Деплой (АВТО, работает с 2026-07-28):** push в `main` → CI gate → **`deploy.yml` собирает arm64
  на НАТИВНОМ раннере `ubuntu-24.04-arm`** (repo public; БЕЗ QEMU — эмуляция крашила Next-SWC SIGILL) →
  push в GHCR → сервер `docker compose pull` (не собирает) → smoke+откат. Секрет `DEPLOY_SSH_KEY` задан
  (ключ `remlab_ci_deploy`). Версия в `/api/health` = git SHA. Локальный `./deploy.sh` — НЕ использовать:
  arm64-сборка под QEMU OOM'ит DEV-VM `pakardev` (2.7 ГБ). Playbook: `deployment.md`, грабля: `core/lessons.md`.

## Концепция v0.4 «Смета-first» (ADR-0016, 2026-07-11; мастер: `plans/MASTER-cost-first.md`)
Ядро — «Смета-лист»: расчёт количеств/стоимости → сохранённый список с реф-ссылками (комиссия,
в т.ч. со ссылок самого юзера через deeplink). Входы: А калькуляторы материалов (~70–90k/мес),
Б «сколько стоит ремонт» (~52k+). Хвосты: визуализация по фото (бывшее ядро, ступень М5),
мастера-лиды (М6, партнёрка — не свой каталог). Утверждённый сценарий — в мастер-плане.
Этапы: М0 партнёрка (Гдеслон ⏸) ∥ М1 смета → М2 вход А (+Этап 4 рекламы) → М3 вход Б
(+Этап 2) → М4 автопилот на все → М5 визуализация+мебель → М6 мастера → М7 SEO.
- **Код-долг v0.4:** ядро сметы М1–М3 не построено; фиды (sub-e2) расширить материалами.
- Модель v0.3 (3 ступени, мебельный affiliate) — историческая; её paid-механика вернётся в М5.
- Ревизия планов: 12 → `archive/plans/` (таблица «Судьба» в мастере), живые: sub-e0/e2/e3/e4/e7,
  ml-замеры («сфоткай—посчитаем»), ads-*.

## Что готово (со ссылками)
- **Bootstrap S1–S4** (Memory Bank, сервер, каркас, регресс-сетка) — `completed_plans/remlab-bootstrap.md`.
- **Stage 1 M0–M8** — `archive/plans/stage1-master-roadmap.md`: Gemini-провайдеры `lib/providers/` (ADR-0007);
  контракты `contracts/*` (Zod); store in-memory → Postgres/Drizzle (ADR-0008/0011); модули
  room-analysis / visual-generation / ideas / generation-job; экраны landing→brief→style→preview→
  paywall→rooms (+`/soon`); тема japandi; e2e в CI, фейк-ИИ по флагу (ADR-0010).
- **Observability** — `lib/analytics.ts` → PostHog (ADR-0012), no-op без ключа; воронка + captureError.
- **Сквозная навигация + разделы-каркасы (2026-07-12, ADR-0017)** — единая шапка `SiteHeader` на
  всех страницах (2 выделенные кнопки-калькулятора + Дизайн/Стили/Советы + «Моя лаборатория» `/lab`);
  главная пересобрана «о проекте целиком»; новые `/styles` (игра «узнай свой вкус» + статьи-плейсхолдеры),
  `/sovety` (плейсхолдеры). Контент/фото интерьеров/аккаунт — позже —
  `completed_plans/site-nav-and-scenarios.md`, `core/user-flow.md`.
- **Калькулятор v2 (ADR-0018, К0–К6) — в проде**, основной на `/calc/[kind]` (localStorage);
  скелеты К5/К6 ждут ключей владельца (YooKassa, токены ботов); ПДн — TODO. `core/estimate.md`.
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
0010 фейк-ИИ по флагу (e2e) · 0012 PostHog, без Sentry · 0013 трейсинг пайплайна · 0014 пивот
v0.3 · 0015 авто-коммит+пуш · **0016 пивот v0.4 «Смета-first»**.
Стек: TS strict + Next.js + Drizzle + Zod + Inngest + внешний инференс (спека §1).

## Что НЕ делаем (вне scope v0.4)
Свой каталог бригад · точная смета работ (только грубо, отдельной строкой) · fit-движок ·
UK · кухня как вход (пока).

## Open questions / TODO
- ~~Мердж `feature/pipeline-tracing` → `main`~~ — уже влита (сверено git, 2026-07-11).
- Активировать авто-деплой: секрет `DEPLOY_SSH_KEY` (= приватный `~/.ssh/remlab_ci_deploy`, уже в
  `authorized_keys`); у Клода read-only PAT — нужен Secrets+Actions write или ручная установка.
- `trace:prune` повесить на таймер `remlab-cleanup`.
- Код под v0.4 — см. «Код-долг» в разделе Концепции.
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
