---
tier: 1
topic: catalog
scope: Каталог — загрузка из фидов/API, свежесть, сторожа
tier2: "../domain/catalog-enrichment.md"
updated: 2026-10-14
importance: high
source: manual
status: working
source_of_truth: canonical
last_verified: 2026-10-13
review_after: 2026-12-05
---

# Каталог — Tier 1 сводка

**Состав (11.10):** 20 552 товара, in_stock ~17 900, 7 магазинов (Орматек 93965 подключён 11.10;
ВсеИнструменты НЕ подключён — ADR-0240); дев-БД `remlab-devdb`.
**Цикл:** crontab `40 10 * * *` UTC (фиды собираются 12:35 МСК) + `@reboot`; `refresh_daily.sh` — шаги
`ok|warn|FAIL|skipped`, статус на прод, дайджест в Telegram, прод-сторож (ADR-0172, [[deployment]]).

**Источник истины (ADR-0171, `tools/scout/load3.py`):** ФИД — ключ `(merchant_id, id)`, название, ссылка,
фото, `original_picture → image_url_hd`, `article`, цена, категория, params, описание (пустое не затирает).
API (`catalog_api_sync.py`, ЕЖЕДНЕВНО с 11.10, сплошной обход + добор словами, ADR-0239) — `charge`,
пустые HD и описание; каноном состава НЕ является (видит 56 % магазина и молча обрывается);
комиссия связывается по `article`, HD и описание — по картинке/названию. Вычисляем: размеры (`dim_resolver.py`, оси по магазину×роли),
роль (`category_map.py` → `products.cat_role`; витрина `lr_roles` ЧИТАЕТ её и не угадывает — ADR-0236),
`in_stock` (`stock_truth.reconcile()`, единственный писатель).

**Дельта (HASH_VERSION=4, `load3.py`):** text/geometry/image/attrs → `stale` (payload остаётся;
commercial и image_hd — только счётчики журнала), смена контракта → baseline. Исчез → `missing`, 3 дня → `archived`; не удаляем.
Порог «< 70 %» — по магазину против последнего успеха (`catalog_import_runs`), одна транзакция.
Карантин фидов — `feed_guard.py` (≤30 ч).

**Наличие и размеры честно** — [[stock-and-dims]].

**Стили и готовность к мешам (ADR-0237/0238).** `style_score.py` (правила → CLIP → `gpt-6-luna`, потолок
`STYLE_DAILY_LIMIT=1000`) пишет оценки в кэш и в таблицу `product_style_scores`. Витрина `catalog_ready` (`bootstrap.sql`):
роль → стиль → размеры → `mesh_uri` → готовность (11.10: 3 532 с мешем, 14 411 к генерации).

**Тесты:** `--selftest` у модулей выше — CI `scout-selftest`. **Дыры:** 155 товаров divan.ru не в экспорте; диванов без глубины 1 012/2 345.

**Tier 2:** `../domain/catalog-enrichment.md` · `../domain/integrations.md`. Цена показа — `tools/scout/price_truth.py` (ADR-0260).
