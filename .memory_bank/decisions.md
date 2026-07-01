---
tier: 1
topic: decisions
scope: ADR-лог — архитектурные решения с обоснованием и влиянием
tier2: "../docs/DECISIONS.md"
updated: 2026-07-01
importance: high
source: manual
status: stable
source_of_truth: canonical
last_verified: 2026-07-01
review_after: ""
---

# Decisions — ADR-лог

> Полные ADR с контекстом/последствиями — в `docs/DECISIONS.md`. Здесь — короткая навигация по решениям.

## [2026-07-01] Стек проекта
**Решение:** TypeScript (strict) end-to-end: Next.js (App Router, full-stack) + Drizzle + Zod (контракты на границах) + Inngest (durable jobs) + внешний инференс (Vertex/fal/Replicate за провайдер-интерфейсом) + YooKassa + Sentry + PostHog + Vitest/Playwright + GitHub Actions.
**Почему:** соло + не-кодер → один рантайм и сквозные типы убирают класс ошибок, которые владелец не читает.
**Альтернативы:** Python+TS два рантайма — отвергнуто (два деплоя, рассинхрон).
**Влияет на:** `core/architecture.md`, структуру `/modules`, `/contracts`.

## [2026-07-01] Self-host на exit-fi вместо Vercel — ADR-0001 (docs/DECISIONS.md)
Изолированный docker-compose на Hetzner exit-fi. Причина: свой сервер, контроль, дёшево. Fallback — Vercel+Supabase.

## [2026-07-01] БД в контейнере postgres:17+pgvector — ADR-0002
Не Supabase Cloud (полный self-host Supabase не влезает рядом с VPN). Auth/Realtime — интерим (anonymous id + polling), позже отдельным ADR.

## [2026-07-01] TLS Let's Encrypt TLS-ALPN-01 на :443 — ADR-0003
Домен GoDaddy A→сервер напрямую; :80 закрыт. Caddy авто-выпуск/продление на :443.

## [2026-07-01] Щедрые лимиты памяти контейнеров — ADR-0004
app 1G / pg 1G (shared_buffers 128MB) / caddy 128M — защита VPN-ноды от OOM.

## [2026-07-01] Дисковая гигиена/автоочистка + swap 4G — ADR-0005
Ротация логов Docker, scoped-очистка образов, weekly timer, ротация бэкапов, df-watchdog, swappiness=10.

## [2026-07-01] Образы под linux/arm64 — ADR-0006
exit-fi оказался ARM (aarch64). Собираем кросс-сборкой buildx `--platform linux/arm64` + binfmt. `deploy.sh` делает это сам. Обычный amd64-билд не запускается на сервере.

## [2026-07-01] Провайдер ИИ = Gemini для обеих задач (M0) — ADR-0007
**Решение:** и генерацию картинок, и анализ фото делаем через Google Gemini одним ключом:
картинки `gemini-3.1-flash-image` (Nano Banana 2), текст/зрение `gemini-flash-latest`. Провайдер за
интерфейсом (`lib/providers/`), сменный под задачу. Детали доступа — `core/access-and-integrations.md`.
**Почему:** ключ Gemini доступен и проверен; Nano Banana 2 силён в editing/consistency по эталонному
фото (наш кейс «перерисовать комнату, сохранив её»); анализ фото у всех стоит доли цента — не рычаг;
OpenAI-ключа в наличии нет. Одна интеграция = проще.
**Альтернативы:** OpenAI GPT-Image (дороже ~$0.167 hi; выше в бенчах text-to-image, не в editing) /
Imagen 4 Fast ($0.02, слабее в editing) — отложены, подключаемы через сменный провайдер.
**Влияет на:** `core/access-and-integrations.md`, `lib/providers/*`, экономику M4/paywall (резолюция).

## [2026-07-01] Каркас Stage 1: in-memory store + Zod как источник формы — ADR-0008
**Решение:** для каркаса Stage 1 источник правды по данным — Zod-контракты (`/contracts`, тип через
`z.infer`), рантайм-хранилище — за интерфейсом `ProjectRepository` с in-memory реализацией
(`modules/store/`). Модель упрощена до одного агрегата `Project` (вместо 11 таблиц спеки §4).
Настоящий Postgres/Drizzle подключается на шаге деплоя заменой реализации Repository.
**Почему:** локальной БД нет, CI должен быть герметичным/быстрым, миграции без живой БД дают дрейф.
Абстракция даёт рабочий проходимый flow сейчас и чистую замену на PG позже без правок вызывающих.
**Альтернативы:** поднимать Postgres в CI/локально сразу — отложено (лишняя связность на этапе каркаса).
**Влияет на:** `modules/store/`, `contracts/*`, план деплоя (там PgRepository + миграции).

## [2026-07-01] Продуктовые решения Stage 1 (владелец) — ADR-0009
**Решения владельца:** (1) дизайн — тёплый **japandi** (крем/беж/greige, дерево, шалфей/терракота);
(2) AI-превью = **перерисовка ФОТО пользователя** (сохраняем геометрию комнаты, меняем стиль/декор),
не картинка-вдохновение; честный дисклеймер «это концепт, проверьте размеры»;
(3) сценарий **«Рассчитать стоимость» — fake-door «Скоро»** (Cost Engine позже, считает движок, не LLM).
**Влияет на:** `app/globals.css` (тема), `modules/visual-generation` (restyle по эталону), `/soon`, `core/user-flow.md`.

## [2026-07-01] Фейковый ИИ-провайдер по флагу для тестов/e2e — ADR-0010
**Решение:** `REMLAB_FAKE_AI=1` → `lib/providers/fake.ts` (детерминированные заглушки в тех же контрактах).
e2e и unit гоняются без ключей и трат; реальный прогон — без флага (Gemini).
**Влияет на:** `lib/providers/index.ts`, `playwright.config.ts` (webServer), CI.

## [2026-07-01] Postgres активирован + авто-деплой через GitHub — ADR-0011
**Решение:** (1) БД — Postgres (`projects` = jsonb-агрегат, `db/schema.ts` Drizzle, `modules/store/pg-repository.ts`).
Выбор реализации в `repo()`: `DATABASE_URL` задан → PG (прод), иначе in-memory (локально/тесты). Миграция —
`tools/migrate.mjs` (идемпотентно) + `db/init/002-projects.sql` (свежая БД); на сервере применяется через
контейнер db (`psql -f`, deploy.sh шаг 5b). (2) Деплой **по умолчанию автоматический через GitHub Actions**:
`.github/workflows/deploy.yml` запускается после зелёного «CI gate» на main, собирает arm64-образ **в раннере**
(не на боевом сервере — VPN-нода) и катит через `deploy.sh` (save|ssh load|compose up|migrate|smoke|rollback).
**Требует (owner, разово):** секреты репозитория `DEPLOY_SSH_KEY` (ssh root@сервер) и `DEPLOY_HOST=89.167.127.0`;
на сервере `/opt/remlab/.env` должен содержать `GEMINI_API_KEY` (+ `POSTGRES_PASSWORD`). Без секретов деплой-джоба
безопасно пропускается. Прямой SSH к проду мной не используется (только через GitHub-автоматизацию).
**Почему:** тяжёлая сборка вне фрагильного сервера; воспроизводимый, откатываемый деплой без ручных шагов.
**Влияет на:** `docker-compose.yml` (GEMINI_API_KEY в app), `deploy.sh`, `.github/workflows/*`, `core/access-and-integrations.md`.
