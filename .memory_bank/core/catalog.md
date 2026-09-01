---
tier: 1
topic: catalog
scope: Каталог — состав, свежесть, дельта
tier2: "../domain/catalog-enrichment.md"
updated: 2026-09-01
importance: high
source: manual
status: working
source_of_truth: canonical
last_verified: 2026-09-01
---

# Каталог — Tier 1 сводка

**Состав:** 20 544 товара (29.08, ADR-0136), дев-БД `remlab-devdb`. Загрузка: фиды `load3.py`
+ **API Гдеслона** `catalog_api_sync.py` (HD-фото 800×600, описания; ID в API побиты float64 →
связь по картинке+названию). Cron 09:40 `refresh_daily.sh` (под `flock`): feed_guard →
shops_check → load3 → catalog_api → **stock_check** → phash → enrich (ADR-0135) → … →
sets_heal → stock_audit; алерты alert.sh.

**Медиа (ADR-0124):** резолвятся из `products` (`catalog_media.py`); мёртвая карточка сильнее
карантина фида. Живость фото трёхзначная (уроки 320/326): сбой/шаблон — не приговор
(`img_alive.py`).

**Наличие — производное, ОДИН писатель (ADR-0141):** `in_stock` = фид `active` И программа не
`retired` И карточка не `gone/oos`; материализует только `stock_truth.reconcile()`, сторож
`--audit` ночью. Свидетельство даёт `stock_check.py` (классификатор `page_alive.py`, schema.org,
контракт магазина sku/series — `series` с 01.09 не назначен никому); снятие — по ДВУМ
отрицательным по одной ссылке (≥15 мин), `unknown` не снимает. Детали — Tier 2.

**Ссылки — ДВЕ РАЗНЫЕ (ADR-0144):** человеку — партнёрская `products.url` (атрибуция — в
редиректе); машине — прямая карточка `direct_url` (проверки и скрейп; ботом в реф не ходим).
Обе отдаёт `catalog_media.media()` (`url`/`probe_url`). Путь НЕ обрезаем, `reflink.direct()`
идемпотентна (`reflink.py --selftest`).

**Роль товара** — лист дерева категорий фида (ADR-0078/0108, `category_map.py` → `cat_role`).
**Обогащение:** active-пул (`gpt-5.6-luna`), phash 99.7%; долг — `enriched_at is null` (урок
325); `openai.off`, лимит $5/день. **Размеры (ADR-0079):** `dim_resolver.py`, провенанс
dims_source/evidence.

**Свежесть фидов (ADR-0107):** `feed_guard` → `feed-freshness.json`. nonton удалён 29.08
(партнёрка закрыта; бэкап graveyard_nonton_* в БД).

**Дыры ассортимента:** премиум и лофт/неокл/джапанди дефицитны — Tier 2.

**Tier 2:** `../domain/catalog-enrichment.md` · `../domain/integrations.md` · `../core/furniture.md`.
