---
tier: 2
topic: integrations-details
scope: Детали внешних интеграций — эндпоинты, форматы запросов/ответов, env-переменные, конфиги, цены
tier1: ../core/access-and-integrations.md
updated: 2026-07-09
importance: high
source: manual
status: working
source_of_truth: canonical
last_verified: 2026-07-09
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

## OpenAI — «розетка» на будущее (не активен)
- Провайдер сменный: `OPENAI_API_KEY` в env → отдельный клиент можно поставить на vision в `index.ts`
  без правок вызывающего кода. В соседнем `v0-health-card` ключа OpenAI НЕТ (проверено 2026-07-01).

## Observability — PostHog (ADR-0012)
- **Что:** аналитика + ошибки. Клиент `lib/analytics.ts` (`track`/`captureError`), REST `POST {host}/capture/`.
- **Ключ:** `POSTHOG_KEY` (+ `POSTHOG_HOST`, дефолт `https://eu.i.posthog.com`) в env. Без ключа — no-op.
- **События:** project_started, brief_completed, style_selected, preview_ready, paywall_viewed, pack_unlocked, app_error.
- Бесплатный тариф PostHog: 1M событий/мес. Sentry не заводим (покрыто PostHog).

## Affiliate-сеть и фиды товаров (v0.3 — планируется, ещё НЕ интегрировано)
- **Сеть РФ:** **Гдеслон** (и аналоги) — фиды AliExpress, «Симфония мебели» и др. (~200+ магазинов),
  комиссия ~3% с выкупа. Реф-ссылки в подборе (free и paid). UK-аналоги позже: Awin/CJ.
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
- **Данные:** фото-ассеты — на томе `remlab-traces` → `/opt/remlab/data/traces`; трейс — в Postgres
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

## Цены (ориентир, 2026)
- Картинка Gemini 3.1 Flash Image: ~$0.045 (512px) / ~$0.067 (1K) / batch −50% (~$0.034 за 1K).
- Анализ фото (vision-вход): доли цента у всех (~$0.0002–0.001/фото) — не лимитирующий фактор.
- Вывод: главный денежный рычаг Stage 1 — стоимость **генерации** картинки; резолюция под free/paid — рычаг.

**Tier 1:** `../core/access-and-integrations.md` — сводка-реестр. Решение по провайдерам — `decisions.md` (ADR-0007).
