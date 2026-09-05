---
workstream: commercial
slug: gdeslon-catalog
title: Каталог Гдеслона — фиды, размеры, клики (Ф0–Ф2 мебельного трека)
status: draft
created: 2026-08-01
updated: 2026-08-01
completed:
archived: 2026-09-05
archived_by: memory-bank-audit-2026-09
archive_reason: superseded — каталог грузится через API Гдеслона, загрузка переписана (catalog-load-hardening)
superseded_by: ADR-0136, ADR-0171
---

## Цель
Товарные фиды 14 одобренных магазинов Гдеслона → таблица `products` с габаритами Ш×Г×В
(покрытие ≥90% в мебельных категориях) + клики `/go/p/` с sub_id + deeplink-маршруты
в `link_routes` для существующих сметных ссылок.

## Источник задачи
Владелец 2026-08-01: Гдеслон одобрил доступ (divan.ru, askona, ormatek, lazurit, mnogomebeli,
divanboss, h-f-l, nonton, tvoydom + DIY: petrovich, lemanapro, maxidom, sanok, gipfel).
Возврат к мебельной теме через каталог+планировщик+сеты. Полный контекст и ресёрч —
план-сессия `~/.claude/plans/divan-ru-sunny-marble.md`; решения — ADR-0042.
Заменяет (supersedes) `sub-e2-feeds.md` (расходился с прод-кодом `/go/`).

## Прочитай сначала
- ADR-0042 в `decisions.md`; `domain/integrations.md` (раздел Гдеслон — эндпоинты, mid, формат фида).
- `app/go/[eid]/[iid]/route.ts` + `lib/estimate/links.ts` — прод-редирект, НЕ ломать.
- `tools/migrate.mjs` + `db/init/004-estimates.sql` — паттерн миграций (raw SQL, идемпотентно).
- Эталон парсинга фида: github.com/GdeSlon/wp-affiliate-shop (`cron.php`, `gs_tools.php`).

## Ручные шаги владельца (блокеры Ф0)
- [ ] Кабинет `/export_files/`: создать выгрузки по всем 14 магазинам → ссылки в `.env` (НЕ в git).
- [ ] Кабинет `/api_settings/xml`: токен `_gs_at` → `GDESLON_API_TOKEN`.
- [ ] Кабинет `/deeplinks/`: hash + erid (для Ф2, сид link_routes).

## Скоуп — что входит
**Ф0 разведка:** `tools/feed-probe.ts` (ZIP→sax→отчёт: частотка `<param>`, % размеров по
источникам param/название/описание, % picture/price, цены); фикстуры 20–30 офферов (без ключей)
в `tests/fixtures/gdeslon/`. Гейт: Ш×Г ≥70% на divan.ru + ormatek/askona — иначе стоп.
**Ф1 каталог:** `db/init/007-products.sql` (+`tools/migrate.mjs`): `products`
(PK shop_mid+external_id; category_id + наша category; name/brand/url/image_url;
price_rub/old_price_rub/in_stock; w_cm/d_cm/h_cm, dims_source 'param'|'name'|'description'|'typical',
dims_confidence; params jsonb) + `feed_ingests` (observability). `contracts/catalog.ts` (Zod +
enum категорий + маппинг категорий Гдеслона→наши). `modules/catalog/{parse,dims,typical-dims,ingest}.ts`:
sax-стрим; парсер размеров (param→название→описание, нормализация мм/см, санити-диапазоны по
категории/оси, confidence); фолбэк типовых размеров (справочники+медианы каталога, confidence ~0.3,
помечать «примерные»); идемпотентный upsert, исчезнувшие → in_stock=false. `tools/feed-ingest.ts`
(CLI --shop/--all/--report). Ресинк 1×/сутки systemd-таймером по образцу remlab-cleanup.
`lib/env.ts`: GDESLON_FEEDS (json mid→url), GDESLON_API_TOKEN.
**Ф1b скрейп-дозаполнение размеров (решение владельца 2026-08-01, «сначала план»):**
там, где фид не дал Ш×Г — аккуратный обход карточек товаров по ПРЯМЫМ url (из `goto=` парт.
ссылки / `destination-url` фида — реф-домены НЕ трогаем, чтобы не светить скрейп в статистике сети).
- Очередь: только целевые категории гостиной (потом спальня), МИНУС садовая/уличная/офисная/
  детская. Ядро (~1,5 тыс. страниц): диваны+шкафы+стеллажи Много Мебели (~990; divanboss —
  клон ассортимента, парсим один домен, матчим на второй по имени+ширине), торшеры (~140) и
  ковры (~240) tvoydom, мелочь nonton (~110). tvoydom-столы (3,5 тыс.) — только журнальные/
  обеденные/консоли по фильтру, не всё.
- Транспорт: 1 страница за раз, интервал 4–6 с с джиттером, gzip, обычный браузерный UA,
  только HTML (~200–450 КБ/стр), таймауты/ретраи, стоп при росте ошибок. Сначала DIRECT
  (с DEV-VM/локально — бесплатно); резидентские прокси `PARSE_PROXY_URLS` — ТОЛЬКО фолбэк
  при банах (квота 1 ГБ, беречь). Пилот-факты: tvoydom — характеристики в инлайн-JSON HTML
  (curl достаточно); mnogomebeli — JS-рендер, нужен headless (Playwright, блокировать
  картинки/шрифты/аналитику) ИЛИ оставить typical-глубину (диваны 95–110 см).
- Парсинг: JSON-LD Product → инлайн-JSON → таблица характеристик (regex/DOM, как ADR-0032);
  LLM НЕ на потоке (дорого), только на единичные непонятные.
- Запись: `dims_source='scrape'` (конфиденс выше typical), `scraped_at`, `scrape_status`;
  отчёт покрытия до/после. Повторный прогон — только по новым/изменённым товарам.
**Ф2 клики:** `app/go/p/[pid]/route.ts` (лог в `product_clicks` → 302 на products.url +
sub_id=clickId; URL только из БД). `tools/routes-seed.ts` — заполнить `link_routes` 14 доменов
официальным шаблоном `https://sf.gdeslon.ru/cf/<API_TOKEN>?mid=<mid>&goto={url}` (подтверждён
доками кабинета; erid при необходимости — из tagging_ads фида).

## Скоуп — что НЕ входит
Планировщик и эргономика (`ergonomics-planner`); сеты и Excel (`living-room-sets`); постбэки,
embeddings/pgvector, подбор-по-фото (follow-up); правки `/go/[eid]/[iid]`; UI.

## Файлы к изменению
- [ ] `tools/feed-probe.ts`, `tools/feed-ingest.ts`, `tools/routes-seed.ts` (новые CLI, tsx — devDep)
- [ ] `db/init/007-products.sql` (новый), `tools/migrate.mjs`, `db/schema.ts`
- [ ] `contracts/catalog.ts` (новый)
- [ ] `modules/catalog/{parse,dims,typical-dims,ingest}.ts` (новые)
- [ ] `app/go/p/[pid]/route.ts` (новый)
- [ ] `lib/env.ts`, `.env.example` (имена без значений), `lib/analytics.ts` (+`product_click`)
- [ ] `infra/server/feed-resync.sh`, `infra/server/systemd/remlab-feed-resync.{service,timer}` (новые)
- [ ] `tests/fixtures/gdeslon/*`, `tests/unit/{feed-probe,catalog-dims,catalog-ingest,product-click}.test.ts`, `e2e/affiliate.spec.ts`

## Задачи
- [ ] Ф0: probe-CLI + отчёт по 2 фидам + фикстуры + гейт покрытия
- [ ] Чекпоинт владельца: отчёт покрытия → какие магазины в первую волну, терпимы ли провалы
- [ ] Ф1: миграция + контракты + parse/dims/typical/ingest + CLI + ресинк + тесты
- [ ] Чекпоинт владельца: таблица покрытия по всем фидам
- [ ] Ф2: /go/p/ + routes-seed + тесты/e2e
- [ ] Чекпоинт владельца: hash/erid; ручная проверка 2–3 переходов (кука атрибуции)

## Критерии приёмки
- [ ] Lint / build / тесты проходят; нет ошибок типов; не задеты файлы вне scope
- [ ] Покрытие Ш×Г (реальные, не typical) ≥90% в целевых мебельных категориях
- [ ] Двойной инжест идемпотентен; большие ZIP — потоково, не в request-цикле
- [ ] Ключи фидов не попали в git/фикстуры/логи
- [ ] `/go/[eid]/[iid]` ведёт через f.gdeslon.ru для доменов из link_routes (без правок кода)

## Definition of Done — память (без этого `completed` запрещён)
- [ ] Memory Bank обновлён: `core/access-and-integrations.md`, `domain/integrations.md`, `core/estimate.md` (реф), `project-state.md`
- [ ] Новая область «каталог» → `core/catalog.md` заведена, видна в decision tree (INDEX)
- [ ] «Уроки» заполнены; отброшенное → `core/lessons.md`
- [ ] `/memory-check` выполнен, audit «чисто»

## Лог выполнения
- 2026-08-01 — план создан (draft) по итогам план-сессии (3 ресёрч-агента: репо, API Гдеслона, эргономика)

- 2026-08-01 — РАЗВЕДКА Ф0–Ф1b выполнена вне репо (tools/scout/, dev-БД remlab-devdb): 7 фидов
  скачаны и загружены (87 635 тов.), ГЕЙТ покрытия ПРОЙДЕН (мебель 87–100% Ш×Г), скрейп-волна 1
  tvoydom завершена (839 стр., свет/декор 76–99%). Токен _gs_at получен (в .env.local/_secrets).
  Deeplink подтверждён живьём. Блокер: divan/askona/ormatek не подключены (API пуст) — ждём владельца.
  Прод-код Ф1–Ф2 по-прежнему НЕ начат.

## Completion summary

### Уроки (ОБЯЗАТЕЛЬНО; для partial/cancelled — особенно)

## Follow-up work
- [ ] Постбэки Гдеслона (GDESLON_POSTBACK_SECRET, raw jsonb, идемпотентный upsert click_id+order_id)
- [ ] Материалы (petrovich/lemana/maxidom) в смету М5 — данные уже будут в products
