---
tier: 2
topic: integrations-details
scope: Детали внешних интеграций — эндпоинты, форматы запросов/ответов, env-переменные, конфиги, цены
tier1: ../core/access-and-integrations.md
updated: 2026-08-06
importance: high
source: manual
status: working
source_of_truth: canonical
last_verified: 2026-08-06
---

# Интеграции — детали (Tier 2)

> Значения секретов тут НЕ хранятся — только ГДЕ они лежат и КАК устроен доступ.
> Сводка-реестр: `../core/access-and-integrations.md` (tier1).

## Google Gemini — активен ✅ (Stage 1, M0)
- **Задачи:** генерация картинок И анализ фото/текст (одним ключом закрыты обе).
- **Модели:** картинки — `gemini-3.1-flash-image` (Nano Banana 2); текст/зрение — `gemini-flash-latest`.
- **Эндпоинт:** `https://generativelanguage.googleapis.com/v1beta/models/<model>:generateContent`,
  заголовок `X-goog-api-key`. Картинка: `generationConfig.responseModalities:["IMAGE"]`, ответ —
  `candidates[0].content.parts[].inlineData{mimeType,data(base64)}`.
- **Ключ:** `GEMINI_API_KEY` — только в `.env`/`.env.local` (gitignore), на сервере `/opt/remlab/.env`.
  Значение НЕ в git/памяти. Проверен рабочим 2026-07-01.
- **Клиент в коде:** `lib/providers/gemini.ts` (fetch, без SDK) за интерфейсами `lib/providers/types.ts`.
  Фабрики — `lib/providers/index.ts` (`getImageProvider` / `getVisionProvider`). Ошибки — `Result<T,E>`.
- **Смоук:** `pnpm smoke:providers` (реальный вызов, не в CI). Юнит на моках — `tests/unit/providers.test.ts`.

## OpenAI — ключ есть ✅ (используется автопилотом рекламы, НЕ приложением)
- Ключ соседей (`v0-health-card/backend/.env`) жив (проверено 2026-07-11: биллинг ок, доступ
  gpt-4.1/gpt-5/5.1) — прежняя запись «ключа НЕТ» от 2026-07-01 неверна. Значение —
  `_secrets/ACCESS.md`; на сервере — `/opt/remlab/ads-watchdog/.env`.
- Используется: ads-watchdog `common.llm_for_ads` — тексты объявлений на `gpt-5.1-chat-latest`
  (бенч 2026-07-11: RU лучше Gemini), фолбэк Gemini. Приложение (vision-розетка `lib/providers/`)
  ключ НЕ использует — при желании можно включить без правок вызывающего кода.
- Гоча GPT-5.x: reasoning-токены съедают `max_completion_tokens` — ставить с запасом (≥2000).

## Observability — PostHog (ADR-0012)
- **Что:** аналитика + ошибки. Клиент `lib/analytics.ts` (`track`/`captureError`), REST `POST {host}/capture/`.
- **Ключ:** `POSTHOG_KEY` (+ `POSTHOG_HOST`, дефолт `https://eu.i.posthog.com`) в env. Без ключа — no-op.
- ⚠️ Одним ключом на проде НЕ включить: compose передаёт в app явный `environment:`-список без
  `POSTHOG_*` — нужна правка compose.
- **События (06.08):** 22 объявлено в `lib/analytics.ts`, 12 эмитится (estimate_*, lab_tab,
  lead_*, quiz_completed, viz_started и др.); `brief_completed`/`style_selected`/`paywall_viewed`
  объявлены, но НЕ эмитятся.
- Бесплатный тариф PostHog: 1M событий/мес. Sentry не заводим (покрыто PostHog).

## Affiliate-сеть и фиды (М0/v0.4 — КЛЮЧЕВАЯ; доступ есть, код ещё НЕ написан)
- **Статус 2026-08-01 (ADR-0042):** аккаунт Гдеслон есть, **доступ одобрен к 14 магазинам**.
  Merchant ID (mid = `_id` в shops.json): divan.ru 112923, sanok.ru 109882, petrovich.ru 94804,
  ormatek.com 93965, nonton.ru 116933, askona.ru 111950, tvoydom.ru 99272, lemanapro.ru 95644,
  mnogomebeli.com 114667, maxidom.ru 117043, lazurit.com 102708, gipfel.ru 112098,
  divanboss.ru 114082, h-f-l.ru 110353. План интеграции — [[gdeslon-catalog]].
- **Гдеслон API (подтверждено ресёрчем 2026-08-01, доки = FAQ gdeslon.ru/faq/17,20,21,23,24,26):**
  - **Товарные фиды**: создаются владельцем в кабинете `/export_files/` (выбор магазинов/категорий →
    постоянная ссылка; URL содержит ключ = секрет). Формат **YML (Яндекс.Маркет XML) в ZIP** с одним
    .xml; партнёрские ссылки УЖЕ вшиты в `<url>` (f.gdeslon.ru/cf/…); характеристики — `<param name="…">`
    (габариты «Ширина/Глубина/Высота» — состав зависит от магазина, полноту мерить). Обновление —
    по расписанию магазина. Эталон парсинга — офиц. плагин github.com/GdeSlon/wp-affiliate-shop.
  - **Deeplink (подтверждено живьём 2026-08-01)**: официальный шаблон
    `https://sf.gdeslon.ru/cf/<ПОЛНЫЙ_API_TOKEN>?mid={mid}&goto={encoded_url}`; в фидах ссылки
    `af.gdeslon.ru/cm/{hash10}` (hash10 = первые 10 симв. токена), erid per-merchant — в
    `tagging_ads` оффера. Сид `link_routes` возможен БЕЗ ручного `/deeplinks/`.
    ⚠️ Шаблон содержит токен → строки link_routes не светить в логах.

  - **XML API поиска**: `GET https://api.gdeslon.ru/api/search.xml?q=…&m=<mid>&l=100&p=N&_gs_at=<TOKEN>`
    (токен из `/api_settings/xml`; лимит 100/запрос). Категории: `api.gdeslon.ru/gdeslon-categories.json`
    (публично; мебель = корень 41: 42 детская, 613 кухня, 615 спальня, 617 столы, 619 стулья, 621 корпусная).
  - **Продажи**: `POST https://www.gdeslon.ru/api/orders/` (Basic `ID:key`); state 3=подтверждён, 4=оплачен.
    Постбэки — faq/24 (`GDESLON_POSTBACK_SECRET`). Sub ID: sub_id…sub_id5.
- UK-аналоги позже: Awin/CJ.
- **Пайплайн фидов (Stage 1):** загрузка → нормализация (категории/размеры/цвета/материалы/style_tags) →
  embeddings (image+text) → векторный индекс (pgvector) → ресинк цен/наличия/статуса; фильтр мусора.
- **Атрибуция:** click_id при переходе → постбэк сети «оформлен»/«выкуплен» → атрибутированная покупка
  (события `affiliate_*`). Блокер к проверке: атрибуция web→app МП, cookie duration, реальные ставки.
- **locale-agnostic:** источник фидов/сеть/валюта/rates — через абстракции (РФ→UK без хардкода рубля).
- Значения ключей API сети — только в `.env` (когда появятся), не в память. Детали: `../../docs/master-brief-v0.3.md` §4.4.

## Трейсинг пайплайна + imagor (ADR-0013)
- **imagor** (сжатие картинок, Go+libvips) — сервис `remlab-imagor` на `remlab-net`, **internal-only**
  (без публичного порта), `IMAGOR_UNSAFE=1`, `FILE_LOADER_BASE_DIR=/mnt/data` (том `remlab-traces` ro).
  Клиент — `lib/images/compress.ts`, вызов `${IMAGOR_BASE_URL}/unsafe/fit-in/1536x1536/filters:format(webp):quality(80):strip_exif()/<key>`.
- **Env (в `/opt/remlab/.env` на сервере):** `TRACE_DIR=/app/data/traces`, `IMAGOR_BASE_URL=http://remlab-imagor:8000`,
  `TRACE_ADMIN_TOKEN` (гард admin-роутов разбора; не задан → открыто), `TRACE_RETENTION_DAYS` (дефолт 90).
- **Данные:** фото-ассеты — на named-томе `remlab-traces` (Docker-managed, bind-пути на хосте НЕТ); трейс — в Postgres
  (`generation_runs/steps/assets`). Разбор: `/api/trace/<N>`, `/api/trace/asset/<id>`, скилл `/trace`, `pnpm trace <N>`.
- Детали архитектуры: `../core/observability-tracing.md`.

## Деплой / CI-доступы (ADR-0011)
- **Реестр образов:** `ghcr.io/igortsk123/remlab-app` (GHCR). Пуш из GitHub Actions встроенным `GITHUB_TOKEN`;
  сервер логинится в GHCR тем же токеном (передаётся в раннере) и делает `docker compose pull` (инкрементально).
- **Сервер:** `/opt/remlab/.env` содержит `POSTGRES_PASSWORD`, `GEMINI_API_KEY` (добавлен 2026-07-01).
  Compose образ = `${REMLAB_IMAGE:-remlab-app:latest}`.
- **CI-деплой-ключ:** `~/.ssh/remlab_ci_deploy` (создан 2026-07-01) — публичная часть в `authorized_keys`
  сервера (вход проверен). Приватную часть нужно положить в GitHub-секрет `DEPLOY_SSH_KEY`, чтобы раннер
  заходил на сервер. **Пока секрет НЕ задан → авто-деплой пропускает шаги** (см. project-state).
  Значения секретов в память НЕ пишем.
- **GitHub PAT (наблюдение CI):** владелец выдал fine-grained токен (у Клода локально, вне репо;
  read-only Actions на 2026-07-01) — хватает читать логи/прогоны, не хватает писать секреты/запускать workflow.

## Яндекс: Wordstat / Директ / Метрика — доступ есть ✅ (проверен 2026-07-11)
- **Откуда:** общий Яндекс-аккаунт владельца с проектом `v0-health-card`; значения токенов —
  `.memory_bank/_secrets/ACCESS.md` (вне git), первоисточник — `v0-health-card/backend/.env`.
  Подробный мануал соседей — `v0-health-card/.memory_bank/yandex_credentials.md`.
- **Wordstat (семантика):** Yandex Cloud search-api, `POST https://searchapi.api.cloud.yandex.net/v2/wordstat/<ep>`,
  заголовки `Authorization: Api-Key <YANDEX_CLOUD_API_KEY>` + `Content-Type: application/json`.
  Эндпоинты (имена проверены живыми вызовами 2026-07-11; в доке health-card два названы неверно):
  `topRequests` (топ фраз+ассоциации, посл. 30 дней), `dynamics` (требует `period:"PERIOD_MONTHLY"`
  и даты RFC3339: `fromDate:"2024-07-01T00:00:00Z"`), `regions` (НЕ `getRegionsDistribution` — тот 404;
  отдаёт count+share+affinityIndex), `getRegionsTree` (справочник id→label).
  Body topRequests: `{"phrase","numPhrases"(1-2000),"regions":["225"=РФ,"213"=Мск,"2"=СПб],"devices":["DEVICE_ALL"]}`.
  `folderId` НЕ обязателен ни для одного из 4 (проверено; в доке соседей помечен блокером — неактуально).
  Счётчики = показы/мес. Скрипт сбора-образец: scratchpad сессии 2026-07-11 `wordstat_collect.sh`.
- **Директ (реклама):** `POST https://api.direct.yandex.com/json/v5/<resource>`, заголовки
  `Authorization: Bearer <YANDEX_DIRECT_TOKEN>`, `Accept-Language: ru`, `Content-Type: application/json; charset=utf-8`;
  body `{"method":"get","params":{...}}`. Токен до ≈2027-04-05, refresh-flow — в ACCESS.md.
  ⚠️ В аккаунте чужие кампании v0-health-card: `708745261` (SUSPENDED) + 26 архивных — НЕ трогать.
  Кампании remlab: Этапы 1–4 (`712721026`, `712722343…345`) — снимок `../advertising/campaign_state.md`.
  Грабли: autotargeting не удаляется (ставка-минимум при ручной стратегии); минусовка скрупулёзно;
  РСЯ выключена до валидации Поиска.
- **Метрика (аналитика):** наш счётчик **`110599064`** (remont-lab.online; создан 2026-07-11 через
  `POST api-metrika.yandex.net/management/v1/counters`, OAuth тот же; гоча: `code_options`-флаги —
  ЧИСЛА 0/1, не bool). 6 целей воронки (id 581463533…540, cutoff 2026-07-11). Код: `lib/metrika.ts`
  (`trackGoal`) + `components/MetrikaPageviews.tsx` (SPA-hit). Чужой счётчик health-card — 108400985.
- **Семантика ниши remlab** (Wordstat-исследование 2026-07-11): `wordstat-semantics.md` (Tier 2).

## Цены (ориентир, 2026)
- Картинка Gemini 3.1 Flash Image: ~$0.045 (512px) / ~$0.067 (1K) / batch −50% (~$0.034 за 1K).
- Анализ фото (vision-вход): доли цента у всех (~$0.0002–0.001/фото) — не лимитирующий фактор.
- Вывод: главный денежный рычаг Stage 1 — стоимость **генерации** картинки; резолюция под free/paid — рычаг.

**Tier 1:** `../core/access-and-integrations.md` — сводка-реестр. Решение по провайдерам — `decisions.md` (ADR-0007).


## Гдеслон: свежесть фидов и наличие (2026-08-02, ADR-0045)
- Выгрузки: ПОСТОЯННЫЕ ссылки export.gdeslon.ru/uploads/exports/<hash>.xml.zip — все 7 в
  `_secrets/ACCESS.md`; фид регенерится на стороне Гдеслона (~ежесуточно, `yml_catalog date`).
- ⚠️ `available` в выгрузках НЕ проставляется (все true) — наличие определять ТОЛЬКО по
  карточкам магазинов: tvoydom — `"quantity":N` в инлайн-JSON (страница ~4 МБ, читать целиком;
  текстовый маркер «нет в наличии» там ЛОЖНЫЙ — из шаблона); nonton/gipfel/sanok — текстовый
  маркер честный; mnogomebeli/divanboss — SPA, карточки для прямого захода 404 → живость =
  модель упоминается на странице серии.
- `products.direct_url` = полный unquote goto= (для SPA-пары — обрезка до серии); реф-переход
  строить deeplink'ом `sf.gdeslon.ru/cf/<токен>?mid=&goto=<direct_url>` — комиссия сохраняется.
- Автоцикл: `tools/scout/refresh_daily.sh` (cron 09:40 + @reboot, guard) → load3.py (upsert,
  снятие исчезнувших) → health.py (карточки, автозамены sets2) → sync_metrics.py (цены/размеры/
  площади/перцентили тиров). XML API search — точечная перепроверка.

## UI-иконки (перенос из Tier1-сводки, 2026-08-02)
PNG 512 от владельца (Drive `1l2j65g8…`) → `public/icons/`; вставлять только `<img>` (sharp в проде нет).

## fal.ai — inference-API (добавлено 2026-08-04)
- Ключ `FAL_KEY`, значение в `_secrets/ACCESS.md`; найден в `.env` соседнего проекта mltest.
- Баланс: `GET https://rest.alpha.fal.ai/billing/user_balance`, заголовок `Authorization: Key <FAL_KEY>`
  (на 2026-08-04 — $9.03).
- Цены (замер 2026-08-04): SDXL 1024² ≈ $0.0023 · Trellis image-to-3D $0.02/модель ·
  FLUX.2-dev ≈ $0.012 · своя GPU per-second: A100 40G $0.99/час, H100 $1.89/час.
- Расчёт под наш объём: 637 уникальных товаров в 126 комплектах → 3D-ассеты ≈ $13 разово;
  кадр «базовый рендер + 6–10 пообъектных врисовок» ≈ $0.03–0.06. Аренда своей GPU
  ($95–409/мес) окупается от ~5000 кадров в месяц — сейчас не нужна.
- Где применяется: LaMa-стирание в `services/room-measure/run_viz.py`; планируется
  depth-ControlNet + пообъектный инпейнт для мебельного трека ([[llm-layout-planner]]).


## Реестр
| Интеграция | Статус | Задача | Ключи (где) | Код |
|---|---|---|---|---|
| Google Gemini | ⚠️ КЛЮЧ МЁРТВ 2026-08-01 — пересоздать; проверить прод | картинки+анализ | `GEMINI_API_KEY` | `lib/providers/gemini.ts` |
| OpenAI | ✅ соседский | GPT-5.1 тексты; gpt-image-2 витрина | `_secrets/ACCESS.md` | ads-watchdog; scout |
| PostHog | код есть, прод no-op (ADR-0012) | аналитика+ошибки | `POSTHOG_KEY` не задан | `lib/analytics.ts` |
| Гдеслон | доступ ✅ 14 магазинов (ADR-0042) | фиды→каталог, /go/ реф | `GDESLON_*` в `.env` | app-интеграции нет; scout-разведка живёт (`tools/scout/*`); план `gdeslon-catalog` |
| imagor | активен (ADR-0013) | сжатие картинок, internal | ключей НЕТ (unsafe) | `lib/images/compress.ts` |
| GHCR/CI | авто-деплой ✅ (arm64) | образы + деплой | `GITHUB_TOKEN`; SSH `remlab_ci_deploy` | GitHub Actions |
| Яндекс (WS/Директ/Метрика) | доступ ✅ | реклама/аналитика | `_secrets/ACCESS.md` (вне git) | кода нет, curl |
| Лид-канал П7 | скелет до токенов | заявки+диалог | `LEADS_*` в `/opt/remlab/.env` — `[[leads]]` | `lib/leads/*` |
| YooKassa | код-скелет, БЕЗ ключей (К5) | оплата 60₽ визуализации | ключи не заданы | `lib/payments/yookassa.ts` |
| fal.ai | активен ✅ | NB2/Seedream/Flux/SAM2/LaMa per-request | `FAL_KEY` (mltest/.env) | scout/mltest |
| РФ-прокси | ✅ ADR-0031 | фолбэк parse-link; квота 1 ГБ | `PARSE_PROXY_URLS`; креды — VPN `_secrets/` | `lib/calc/fetch-page.ts` |

## Codex (OpenAI CLI) — постоянная сессия-советник (16.08.2026)
> **Скоуп правила (20.08.2026):** владелец убрал правило из глобального `~/.claude/CLAUDE.md` —
> оно действует ТОЛЬКО в remlab и sup2, полный текст в `CLAUDE.md` каждого проекта (§ Codex).
> Два `resume` одной сессии параллельно не запускать: вызовы конфликтуют.
- **Сессия проекта:** `01a00a62-33e2-7051-93c6-37bff5c6937e` (онбординг 16.08: прочитал CLAUDE.md, INDEX, ADR-0099…0106,
  MASTER-zones-v7, свои аудиты, карту кода; конспект — `_intake/codex-onboarding-notes.md`).
- **Как звать:** `codex exec --sandbox read-only -C /home/pakar/igor/remlab -o answer.md resume 01a00a62-33e2-7051-93c6-37bff5c6937e - < prompt.md   (флаги — ДО resume)`
  (промпт короткий: «что изменилось с прошлого раза (коммиты/файлы) + вопрос»). Для НЕЗАВИСИМОГО second opinion
  (когда нельзя показывать нашу гипотезу) — по-прежнему `codex exec --ephemeral`.
- Раз в несколько сводов — новый онбординг (сессия распухает/устаревает), старую архивировать (`codex archive <id>`).
- **⚠️ 01.09.2026 — СОВЕТНИК НЕ РАБОТАЕТ.** Три вызова подряд (постоянная сессия и два
  `--ephemeral`) завершились с кодом 0, но БЕЗ финального ответа: постоянная сессия вернула пустой
  файл `-o`, свежие обрывались после первой реплики (в логе — только план работ и вывод
  инструментов, 936 КБ). Практическое следствие: правило `codex-adviser.md` (случай 5 — план на
  критику до показа владельцу) сейчас не исполняется. Планы `demo-ux-audit` и
  `demo-collection-flow` показаны БЕЗ независимого разбора, это отмечено в самих планах.
  Гипотезы к проверке: распухшая сессия (нужен новый онбординг), вендорный bwrap
  (`warning: Codex could not find bubblewrap on PATH`), лимит вывода.
- Песочница: `/etc/apparmor.d/codex-bwrap-userns` (профиль для vendored bwrap); классификатор auto-mode — правило в
  `.claude/settings.local.json` autoMode.allow.

## Sketchfab — модели-заглушки для сцены (01.09.2026)
> Tier 1: `../core/access-and-integrations.md`
Нужны нейтральные меши вместо крашеных прямоугольников: телевизор, окно, дверь. Отобраны
(все **CC-BY**: коммерческое использование разрешено, ОБЯЗАТЕЛЕН кредит автору — значит нужна
строка с авторами на странице):
- окно ПВХ `7151f52364c24177abbaca26b7451cdb` (Annelida, 11 820 граней) — белый профиль, две створки;
- дверь `25c899e4a6494bf483c081c1f6b2caf9` (ESINDESIGN, 1 760) или набор из пяти
  `6c23d87651ea4559bda349fcda77d22b` (FreeMeshBase, 5 178);
- ТВ на ножках `f90d4fb91dd34b6791e8d66d00f96591` (HippoStance, 2 706);
- ТВ настенный `c91f9ac4de274b5aad362e0f19c3f16b` (abdillaamy, 2 880).

**БЛОКЕР:** скачивание со Sketchfab требует входа в аккаунт — у агента его нет. Дверь, выбранная
владельцем (`4fc22c8c214444bd84be13c52bbdb538`, «Door 001»), НЕ СКАЧИВАЕТСЯ вовсе: лицензия
Standard, `isDownloadable:false`, платная модель магазина.
**Проверено, что НЕ подходит:** Poly Haven (чистый CC0, скачивание без регистрации) — из 521
модели телевизоры только ламповые винтажные, дверей и окон для квартиры нет вовсе.
Альтернатива без лицензии — сделать свои меши нашим конвейером по фото.
Поиск через открытый API: `https://api.sketchfab.com/v3/search?type=models&q=…&downloadable=true`.


## Vercel AI Gateway (26.08)
`https://ai-gateway.vercel.sh/v1`: `/images/edits` (`image[]`, `mask`) для `gpt-image-*`;
`/chat/completions` + `modalities:['image']` для Google-картинок — `draft_render._chat_edit`.
Ключ `VERCEL_AI_GATEWAY_KEY`: `_secrets/ACCESS.md` и `/opt/remlab/.env`; клиент `gw_key()`.
Прямые ключи OpenAI без кредитов — рабочий путь только шлюз.


## fal.ai (2026-08-05 → 28.08)
Клиент `tools/scout/falmini.py`; на мешах заменён Salad (ADR-0131). Модели и маски —
`../domain/integrations.md` §fal.
