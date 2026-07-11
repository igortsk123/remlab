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
> см. `plans/`, `archive/plans/`, `completed_plans/`.

## Планирование (2026-07-11)
Утром: аудит проекта (идея 8/10, состояние 6/10) → конвейер «Деньги» Э0–Э8 + 10 sub-планов
(`guides/execution-playbook.md`). **Вечером — пивот ADR-0016:** конвейер superseded, мастер
теперь `plans/MASTER-cost-first.md`; commercial-master-plan, MASTER-roadmap и 10 планов —
в `archive/plans/` (причины — в таблице «Судьба» мастера). Живые sub-: e0/e2/e3/e4/e7 + ml-замеры.

**Реклама (2026-07-11):** доступы Яндекса получены (общий аккаунт с v0-health-card,
`_secrets/ACCESS.md`), семантика собрана (`domain/wordstat-semantics.md`). **Метрика
`110599064` + 6 целей воронки на сайте; кампания Поиск `712721026` залита и на модерации**
(5 групп, 30 ключей, 10 объявлений, потолки 3 500 ₽/нед и 20 ₽/клик, РСЯ off) — включится
сама при пополнении баланса владельцем. Снимок/протоколы — `advertising/campaign_state.md`,
сводка — `core/marketing-acquisition.md`.

## Где
- **Стадия:** Stage 1 LIVE в проде; концепция **v0.4 «Смета-first»** (ADR-0016; прежние
  пивоты: v0.3 ADR-0014). Ядро сметы (М1–М3) не построено.
- **Прод:** https://remont-lab.online — версия `tracing-142829` (2026-07-02), собрана из ветки
  `feature/pipeline-tracing`; ветка **уже влита в `main`** (проверено 2026-07-11: по коду
  прод == main, main впереди только док-коммитами). Контейнеры: `remlab-app`,
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
