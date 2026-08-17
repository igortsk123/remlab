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

## 2026-07-11 — М1 «Смета-лист» построена (v0.4, ADR-0016)
Фронт переделан под концепцию Смета-first: калькуляторы материалов (вход А, формулы+golden),
вилка стоимости ремонта (вход Б, плейсхолдер-нормативы), смета-чек-лист по постоянной ссылке,
/go/ редирект-слой (late-binding реф + лог кликов), лендинг v0.4. Схема estimates/link_clicks/
link_routes. Задеплоено, прод-verify пройден (PG-рендер, /go/ 302+лог). Планы:
`completed_plans/m1-estimate-core.md`; в очереди — `plans/pricing-db-ru.md`.

## 2026-07-28 — launch-prep: зонт П1–П7 закрыт, платформа готова к запуску
П1 витрина-заглушки (`ComingSoon`, флаг `NEXT_PUBLIC_SHOW_WIP`); П2 «Моя лаборатория» — центр
сохранений (список расчётов, счётчик-бейдж, cookie 30 дн); П3 UX калькуляторов (VizCta скрыт,
LeadCard без дублей, подсказки «что дальше», «новый расчёт» + автоочистка черновика); П4 масштаб
100–130% (CSS zoom, `ZoomControl`) + мобильные правки; П5 ядро чтения ссылок (фикс цены-артикула,
htmlToText для LLM, пометки авто/вручную `autoKeys`); П6 финал (e2e лаборатории и заглушек, сверка
рекламы: кампании SUSPENDED); П7 лид-канал «найдём дешевле» (город-автокомплит ~1106 городов,
служебный TG-бот, ответ реплаем). Детали — `completed_plans/launch-p*.md`, ADR-0029.

## 2026-07-30 — UX-полировка по фидбеку владельца + чтение ссылок П5b
Пакет ADR-0030 (`completed_plans/calc-ux-batch.md`): ламинат — цена за м² (парсер «Размер доски»,
шт/упак, юнит «м 2»; формула через целые упаковки); удаление расчётов в `/lab`; «?»-подсказки
(раппорт, стыковка обоев со смещением, смещение рядов); ИИ-фолбэк parse-link перестал молчать.
Шапка (`completed_plans/header-compact-lab-arrows.md` + правки владельца по ходу): один ряд,
1100px, центрирование блока «бренд+кнопки», сворачивание на мобильном при скролле; Стили/Советы
скрывались и были возвращены. Иконки владельца (Drive → `public/icons/`) вместо emoji на `/calc`,
главной, `/start`; фавиконка-колба `app/icon.png`. П5b чтения ссылок — ADR-0031/0032.

## Где
- **Стадия:** v0.4 «Смета-first» (ADR-0016); ядро сметы М1 в проде (входы А/Б, чек-лист, /go/ реф) —
  `core/estimate.md`. Автопилот рекламы DRY-RUN на все кампании — `advertising/autopilot.md`.
- **Запуск: ЗОНТ launch-prep ЗАКРЫТ (2026-07-28) — платформа ГОТОВА.** П1–П7 в проде (витрина-
  заглушки, лаборатория-центр, UX калькуляторов, зум 100–130%, чтение ссылок, лид-канал; хронология
  — `changelog/project-history.md`). **Ждут владельца:** токены 3 ботов + SMTP (`core/leads.md`),
  включение Этапа 1 рекламы. Кампании SUSPENDED; Этап 2/AI-дизайн НЕ включать (ведут на заглушки).
- **Мебельный трек v3 «стили+правила» (2026-08-03, ADR-0042–0050):** сеты по СТИЛЯМ —
  126 (7 метражей × 6 стилей × 3 тира, sets3.json), стиль-скоринг 15.7k товаров, судья с
  политикой замен, правило разнообразия ≤3/≤5; свод правил гостиной (2 раунда мульти-джоб
  ресёрча → occupancy.json: динамические шкалы от площади — решения владельца); расстановка:
  ЗОНА-БИЛДЕР (ADR-0050) + DFS-периферия; витрина-6 v4 отдана (по кадру на стиль). Свежесть —
  ежедневный автоцикл (+стиль-дельта новинок). Прод-ядро расстановки — план
  [[prod-layout-engine]] in_progress (спека `guides/layout-engine-spec.md`, Э0 добыча правил
  workflow'ом; Э1+ в свежей сессии). Планы [[sets-style-v3]]/[[layout-quality]]/[[room-size-fit]]
  in_progress; [[scalability-hardening]] draft. **Ждут владельца:** вердикт витрины v4;
  cozyhome (ковры!); divan/askona/ormatek; Gemini-ключ. Сводки — `core/furniture.md`,
  `core/styles.md`, `core/lr-checklist.md`.
- **Чтение ссылок П5b ЗАКРЫТ (2026-07-30, ADR-0031/0032):** только сервер — direct → резидентский
  прокси (`PARSE_PROXY_URLS` в `/opt/remlab/.env`) для всех магазинов; вход LLM = JSON-LD + окно
  «Характеристик»; загрузки файла НЕТ. ⚠️ Ozon/WB блокируют IP пула (капча) — нужен прокси-анблокер
  (Bright Data/Zyte), решение владельца.
- **UX-полировка (ADR-0030/0034–0039) и Калькулятор v2 (ADR-0018–0028)** — в проде; детали:
  `core/estimate.md`, `core/user-flow.md`, `decisions.md`.
- **Дизайн-система (2026-07-31, ADR-0041):** весь UI на **Untitled UI React** (Tailwind v4 +
  React Aria, copy-paste в `components/base|application`), палитра-гибрид (терракота-brand,
  stone-нейтраль, крем; `styles/brand.css`), Inter self-host. Старые токены/классы удалены;
  4 атомарных деплоя U0–U4 (план `uui-migration`) + полировки p1/p2 (кнопки brand-500, тёплый
  графит текста, tap-подсказки, мобильная шапка/вкладки скроллом). Правила — `.claude/rules/ui-rules.md`.
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

## 2026-08-09 — вытеснено из project-state при /memory-check
- Рефери-пакет 08.08 (полные детали): демоции FLOOR_OVERFILL/SOFA_SLIVER, чеки камин/окно,
  ярусы=приоритет удержания, мёртвая зона, wall-back из данных, ТВ distance-first, 47 кодов;
  приёмка пакета 243/252. MASTER-truth-first T0-T6: 7 коммитов fa717bb…adf5c87; батч-гейт
  (биллинг, 1 859 карточек); real-бенч; _ROOM_BAND-недетерминизм починен; 87 тестов.
- Волна MASTER-layout-v5 (хронология итераций L3.1-L3.3, фантомный baseline, честный A/B
  флагом) — см. лог в plans/MASTER-layout-v5.md.


## 2026-08-16/17 — Свод №13 Q0–Q5 (ADR-0107)
Слепая оценка р.1 → метрики владельца (view_metrics), identity-адаптер (кресло 3/4, диван 2, столик 2
доезжают до солвера), media-формы + сертификаты семейств, plan_key_v2 shadow, второй pod = атомарный
комплект (compose2 pod_kit) + check_quiet_contract, П/facing ожили (TOO_DEEP exemption), L_right.
Каталог: конвейер стоял с 11.08 (nonton 404) — починен/закалён; pod только из живых фидов. Codex-советник
как правило владельца (постоянные сессии). Экзамены: 269+3, TIMEOUT 0; галерея опубликована.

## 2026-08-14 — вытеснено из project-state 17.08 (предыдущий фокус расстановки)

**Хвост М5 мастер-плана** (владелец 13.08: «интересует только расстановка»). Ядро сметы
М1–М3 по-прежнему не построено — осознанный выбор приоритета, не забывать.

**Состояние движка.** Раскладка собирается ТОЛЬКО из шаблонов зон; шаблон — объект с паспортом
и машинными инвариантами (`services/planner-solver/rules/templates.json`,
`services/planner-solver/planner/invariants.py`, ADR-0088). Геометрия схем (13 чисел) и размеры
слотов живут в правилах, не в коде; конверт −20/+10 применяется только при ПОДБОРЕ товара
(`tools/scout/compose2.py`), солверу менять габарит SKU запрещено (прогон падает).
Порядок стадий — дизайнерский (ADR-0091): фокус-стена → диван → циркуляция → носитель →
ковёр/столик → доп. посадка → хранение → свет → декор; вторичная зона откатывается целиком,
если ухудшила маршрут/«щели»/фокус (`services/planner-solver/planner/quality.py`).

**Волна модификаторов 14.08 (ADR-0094, свод №5) — ЗАВЕРШЕНА:** mode × shape × контур
(эркер/колонна/квадрат) комбинируются скорингом; clearance-классы + dead_side; подбор по
массе/ножкам/посадке; концентрация хранения в малых; лестница достижима до «без дивана»;
приоритеты зон — таблица `zone_priority` в данных; 17 сторожевых hard классифицированы (R5);
маршрут в артефакте (`_route_cm`, min 75 по 252). Гейт: 252/252, медиа 252/252, сторожа
126/126. Completed-планы: MASTER-layout-modifiers, MASTER-tv-sofa-pair, elongated-room-mode,
slots-everywhere, rules-consistency-audit, conflict-audit-modifiers. Отложено честно:
swivel (нет данных обогащения), open-plan (нет сцен), потолок (Room.ceiling_cm спит),
камин-ось без ТВ (недостижима при медиа-минимуме). Плюс bay_armchair 1.0 (кресло в эркере) свод №6 (ADR-0095: entry-зона, угловой по главной секции) свод №7 (ADR-0096: столовая от 15 м²) и dining_sacrifice (ADR-0097) — 14.08. **Свод №8 v2 (внешний рефери, согласован диалогом
с пруфами; ADR-0098…0101, MASTER-zones-v2 completed):** dining-паспорт в коде, каскад
full_island→compact→edge с объяснимостью (тихий edge 0), виртуальный экран
(SCREEN_OVER_WINDOW + вейвер +tvw), зеркала Г-дивана, статусы зон данными, оси-замеры,
приёмка 269 сцен (№253+ свои проёмы). Планка dining 196-197 честная (брак «экран
на окне» вскрыт). **Свод №9 (ADR-0102/0103, completed):** P0 двойной носитель (3 уровня); trace dining;
mode по топологии; cohesion-оси; корень-баг знака зеркала исправлен; сцены №270-272. Экзамен 272/272. **Свод №10 (аудит V4;
ADR-0104, MASTER-zones-v4 completed):** band=кап (перекос посадки устранён: pouf
149→22, sectional_armchair 153), axis contract, functional claim (dining 209,
острова 44+62), H2 закрыт shadow-данными, role-скоуп behind-sofa, единый контракт
угла, аудит контрактов, debug-оверлей. Follow-up: композитор-альтернативы (C3),
вторая зона больших, FAR-large перемер.
Заполнение пола — диагностика, не цель.

**Замер 12.08 (252 фикс-сцены, `tools/scout/acceptance_run.py`):** чисто 252/252 · медиа-зона
223 · смещение носителя от оси медиана 27 см · маршрут ≥70 см везде · хранение 242 ·
столовая 72 · посадочные на ковре 100% · предметов вне шаблонов 0 · сторожа
`services/planner-solver/tests/test_template_integrity.py` 8/8.

**Очередь (только расстановка):** `plans/slots-everywhere.md` (черновик — конверт слота есть у
6 ролей из 15, у ДИВАНА нет; отсюда 32 сцены с пустой фокус-стеной) ·
`plans/template-library-v2.md` (недостающие схемы) · `plans/design-order-pipeline.md` (partial:
камин как источник оси, маршрут в отборе позиции посадки).

**Витрина владельца:** https://remont-lab.online/test/acceptance-plans/ — 252 плана с номерами
(«План №N», номер стабилен), пересобирается `tools/scout/acceptance_gallery.py`.

