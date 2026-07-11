---
workstream: commercial
slug: sub-e2-feeds
title: Э2 — фиды Гдеслон, автоподбор, постбэки
status: draft
created: 2026-07-11
updated: 2026-07-11
completed:
---

# Э2: фиды Гдеслон — автоподбор

## Цель
SEED → реальные товары Гдеслон: целевые категории с Ш×Г×В, embeddings в pgvector, автоподбор 3 товаров, subid-клики, постбэки.

## Источник задачи
Этап Э2 [[commercial-master-plan]]. Старт — по CTR-gate Э1 (viz→клик ≥15%).

## Прочитай сначала
- `.memory_bank/plans/commercial-master-plan.md` (гейты, kill Э2), `.memory_bank/plans/MASTER-roadmap.md` п.7 (DINOv3+SigLIP 2, HNSW, эмбеддить КРОП), `docs/master-brief-v0.3.md` (free: 3 товара открыто).
- `db/schema.ts`, `tools/migrate.mjs`, `db/init/003-traces.sql` — паттерн миграций.
- `modules/ideas/index.ts` (SEED, FREE_VISIBLE), `modules/generation-job/index.ts:99` (`buildCatalog()`), `contracts/project.ts` (bbox НЕТ).
- `lib/images/compress.ts` (imagor file-loader), `lib/prompts/registry.ts` (`roomAnalysisPrompt` v2 → bump по `pipeline-tracing`).
- `.memory_bank/project-state.md` — прод (`feature/pipeline-tracing`) впереди `main`.

## Скоуп — что входит
Б1–Б7 ниже. Целевые категории: диваны/кровати/столы/стулья/шкафы/кресла + декор, ТОЛЬКО они.

## Скоуп — что НЕ входит
Fit «влезет» — Э5 (w/d/h_cm кладём сейчас); оплата/paywall/`unlockPack`; UK; Inngest (Э3); Cost Engine; 10-млн фид — никогда.

## Файлы к изменению
- [ ] `db/schema.ts`, `db/init/004-catalog.sql` (новый), `tools/migrate.mjs` — таблицы+индексы синхронно.
- [ ] `contracts/catalog.ts` (новый); `contracts/project.ts` — опц. `bbox`, `productId`/`url`/`imageUrl` (легаси читается).
- [ ] `lib/prompts/registry.ts` (bbox, v2→v3); `modules/room-analysis/index.ts` (`rawSchema`: bbox, кламп 0..1).
- [ ] `modules/catalog/parse.ts`, `normalize.ts`, `ingest.ts`; `modules/product-matching/index.ts` (новые).
- [ ] `tools/feed-ingest.ts`, `tools/feed-embed.ts` (новые, CLI на `tsx`); `package.json` — devDep `tsx`.
- [ ] `modules/generation-job/index.ts` — подбор вместо `buildCatalog()`; `modules/ideas/index.ts` — убрать locked/FREE_VISIBLE.
- [ ] `app/p/[id]/preview/page.tsx`; новые route.ts: `app/go/[clickId]`, `app/api/affiliate/postback`, `app/api/admin/feed-resync`.
- [ ] `lib/analytics.ts` — `EventName` += 3 события (см. Б4–Б6); `lib/env.ts` — опц. `GDESLON_FEED_URL`, `GDESLON_POSTBACK_SECRET`, `ADMIN_TASK_SECRET`, `FAL_KEY` (значения — в `.env` сервера).
- [ ] `infra/server/feed-resync.sh`, `infra/server/systemd/remlab-feed-resync.{service,timer}` (новые, как `remlab-cleanup.*`).
- [ ] `tests/fixtures/gdeslon/`, `tests/unit/{feed-normalize,product-matching,affiliate-postback}.test.ts`, `e2e/affiliate.spec.ts` (новые).
- [ ] `docs/DECISIONS.md` — ADR: модель, клики, tsx.

## Задачи
**Б0.** Чекпоинт 1; URL фида → `.env` (содержит ключ, в git нельзя); свести прод и `main`; 10–20 реальных `<offer>` → фикстуры.
**Б1 БД.** `products`: PK/upsert shop+external_id; category/name/brand/url/image_url/old_price; w/d/h_cm (real null), price_rub (int), in_stock, style_tags, embedding vector(N — чекпоинт 3), updated_at. `affiliate_clicks`: click_id uuid PK, project_id, product_id. `affiliate_conversions`: click_id+order_id (UNIQUE), amount, commission, status, raw jsonb. Индексы: HNSW `vector_cosine_ops`, btree(category, price_rub), in_stock.
**Б2 инжест.** `parse.ts`: sax-стрим. `normalize.ts`: размеры из `<param>` (мм/см) и названия («ШхГхВ», «200x90x75 см», порядок осей разный) → см; 0/>1000 → null; тесты на реальных фикстурах. `ingest.ts`: upsert; исчезнувшие → `in_stock=false` (клики ссылаются). Отчёт покрытия → stdout+файл.
**Б3 embeddings.** Шорт-лист fal/Replicate (SigLIP 2/CLIP; нет DINOv3 → DECISIONS) → чекпоинт 3. Батчи 25–100: картинка (`image_url`; CDN не отдаёт → скачать, base64) + текст «название+категория»; ретраи; перезапуск с `embedding IS NULL`.
**Б4 matching.** Кроп: входное фото — ассет трейса на томе imagor → кроп по file-loader-ключу; bbox нет → всё фото. объекты action=change/remove, бюджет, стили; label→категория → `WHERE category AND in_stock AND price_rub BETWEEN` → `ORDER BY embedding <=> $1 LIMIT K` → 3 товара (разные категории). Similarity → трейс + `products_matched`. Пусто/ошибка → SEED + `captureError`.
**Б5 клики.** Кнопка товара → `/go/<uuid>?product&project`. `/go`: Zod → insert (on conflict do nothing) → URL только из БД (open redirect) → 302 subid=click_id (формат — как в Э1) → `product_click` source=auto; ручные Э1 — manual. Locked-блок убрать, paywall не трогать.
**Б6 постбэки.** Секрет query = `GDESLON_POSTBACK_SECRET` (иначе 401); raw в jsonb ДО разбора; upsert (click_id, order_id); статусы pending/approved/declined обновляют строку; событие `affiliate_conversion`.
**Б7 ресинк.** Батч ~500 самых старых `updated_at` → цена/наличие; таймер 15–30 мин (каталог за сутки); curl, секрет из `/opt/remlab/.env`; `remnanode` не трогать. Полный инжест — CLI.

## Гейты
- [ ] `pnpm typecheck && pnpm lint && pnpm test && pnpm build`.
- [ ] `pnpm e2e` (REMLAB_FAKE_AI=1) + `affiliate.spec.ts`: `/go`→302 с subid, клик в БД; постбэк → конверсия; повтор — без дублей.
- [ ] `pnpm tsx tools/feed-ingest.ts --report` → покрытие размеров ≥90%.
- [ ] `curl -X POST '<postback>?secret=WRONG'` → 401; верный → 2xx.
- [ ] top-K по HNSW < 200 мс; два resync подряд → одно состояние, батч < интервала.
- [ ] 5 golden-комнат: вердикт владельца «осмысленно»; в проде 1–2 нед: авто-CTR ≥70% ручного Э1 (source auto/manual).

## Чекпоинты владельца
- [ ] ⏸ До инжеста: кампании (магазин/категории/товары/комиссия). «Какие берём?»
- [ ] ⏸ После инжеста: таблица покрытия размеров. «Где провалы терпимы, где сменить магазины?»
- [ ] ⏸ Перед embeddings: 2–3 модели (качество/цена/скорость). «Какую берём?»
- [ ] ⏸ После matching: 5 скринов (комната+3 товара+цены). «Поставил бы руками? Что заменить?»
- [ ] ⏸ Перед выкаткой: превью витрины. «Карточки и подписи ок?»

## Если пошло не по плану
- Фид большой → по кампаниям отдельными URL; покрытие <90% после 2 итераций → минус худшие магазины; дальше — к владельцу.
- Embeddings дорого → меньше батч, кэш, только in_stock, fal↔Replicate; дороже бюджета → стоп.
- Подбор мусорный → similarity в трейсе; итерация 2: кроп/текст, bbox↔всё фото; вдвое хуже ручного → kill: human-in-the-loop.
- Постбэк иной → raw jsonb по факту; тестовая конверсия в кабинете.
- HNSW ест память → ≤100 тыс. строк, меньше m/ef; иначе CAX21 (владелец).

## Критерии приёмки
- [ ] `products`: целевые категории, ≥90% с Ш×Г×В, у всех embedding.
- [ ] Preview: 3 реальных товара, `/go` с subid; locked нет; SEED — только фолбэк (app_error).
- [ ] Постбэк и ресинк идемпотентны; similarity в трейсе и PostHog; e2e зелёный; VPN-нода не тронута.
- [ ] ADR записаны; выкатка по `agent-workflow.md` (гейты → push main → `./deploy.sh`).

## Definition of Done — память
- [ ] `core/catalog-affiliate.md` (новая область ≤3 KB: таблицы, клик→постбэк, ресинк).
- [ ] `core/access-and-integrations.md`: Гдеслон (фид, постбэк, env-имена), embeddings-провайдер.
- [ ] ADR в `decisions.md`/`docs/DECISIONS.md`; `project-state.md` переписан; `/memory-check` чисто; реестр мастер-плана обновлён.

## Лог выполнения
- 2026-07-11 — план создан, draft.

## Completion summary

## Follow-up work
- Э3: Inngest вместо CLI/systemd; Э5: fit по w/d/h_cm; paid «3 альтернативы»; UK locale; дашборд конверсий.
