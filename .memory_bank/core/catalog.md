---
tier: 1
topic: catalog
scope: Каталог — загрузка из фидов/API, свежесть, сторожа
tier2: "../domain/catalog-enrichment.md"
updated: 2026-10-29
importance: high
source: manual
status: working
source_of_truth: canonical
last_verified: 2026-10-13
review_after: 2026-12-05
---

# Каталог — Tier 1 сводка

**Состав (11.10):** 20 552 товара, 7 магазинов (ВсеИнструменты НЕ подключён — ADR-0240); дев-БД `remlab-devdb`.
**Цикл:** crontab `40 10 * * *` UTC (фиды в 12:35 МСК) + `@reboot`; `refresh_daily.sh` — шаги
`ok|warn|FAIL|skipped`, статус на прод, дайджест в Telegram, прод-сторож (ADR-0172, [[deployment]]).

**Источник истины (ADR-0171, `tools/scout/load3.py`):** ФИД — ключ `(merchant_id, id)`, название, ссылка,
фото, `original_picture → image_url_hd`, `article`, цена, категория, params, описание (пустое не затирает).
API (`catalog_api_sync.py`, ежедневно, ADR-0239) — `charge`, пустые HD и описание; каноном состава НЕ является (видит 56 %);
комиссия — по `article`, HD и описание — по картинке/названию. Вычисляем: размеры (`dim_resolver.py`, оси по магазину×роли),
роль (`category_map.py` → `products.cat_role`, её читает витрина `lr_roles` — ADR-0236; детское — `rug_kids.py`, мягкое детских линий — `category_map.py:soft_kids`; свет — по «Тип»,
`category_map.py:light_role`),
`in_stock` (`stock_truth.reconcile()`, единственный писатель).

**Дельта (`load3.py:HASH_VERSION` = 7; смена правил `dim_resolver` — подъём, сторож `RULES_FINGERPRINT`):** text/geometry/image/attrs → `stale`
(commercial и image_hd — только счётчики), смена контракта → baseline. Исчез → `missing`, 3 дня → `archived`; не удаляем.
Порог «< 70 %» — по магазину против последнего успеха (`catalog_import_runs`).
Карантин фидов — `feed_guard.py` (≤30 ч). Обогащение `enrich.py --vision` — ежедневно, ≤200, сперва товары банков (`enrich.py:daily_pick`).

**Наличие и размеры честно** — [[stock-and-dims]]; там же категория без размеров — карантин, роль остаётся (ADR-0309, `dimless.py`).

**Стили и готовность к мешам (ADR-0237/0238).** `style_score.py` (правила → CLIP → `gpt-6-luna`, потолок
`STYLE_DAILY_LIMIT=1000`) пишет оценки в кэш и в таблицу `product_style_scores`. Витрина `catalog_ready` (`bootstrap.sql`):
роль → стиль → размеры → `mesh_uri` → готовность (11.10: 3 532 с мешем, 14 411 к генерации).

**Тесты:** `--selftest` у модулей выше — CI `scout-selftest`. **Дыры:** 155 товаров divan.ru не в экспорте; ormatek.com — антибот.

**Tier 2:** `../domain/catalog-enrichment.md` · `../domain/integrations.md`.
