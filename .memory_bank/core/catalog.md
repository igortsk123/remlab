---
tier: 1
topic: catalog
scope: Каталог — загрузка из фидов/API, свежесть, сторожа
tier2: "../domain/catalog-enrichment.md"
updated: 2026-09-05
importance: high
source: manual
status: working
source_of_truth: canonical
last_verified: 2026-09-05
review_after: 2026-12-05
---

# Каталог — Tier 1 сводка

**Состав (03.09):** 20 588 товаров, in_stock 18 736, 6 магазинов Гдеслона; дев-БД `remlab-devdb` (DEV-VM).
**Цикл:** crontab `40 10 * * *` UTC (фиды Гдеслона собираются 12:35 МСК) + `@reboot`; `refresh_daily.sh` —
шаги `ok|warn|FAIL|skipped` (`WARN:<код>:`), статус на прод, дайджест в Telegram, прод-сторож (ADR-0172,
[[deployment]]). Аудит с владельцем — `_intake/owner/dialog-catalog-load-0309.md`.

**Источник истины (ADR-0171, `tools/scout/load3.py`):** ФИД — ключ `(merchant_id, id)`, название, ссылка,
фото, `original_picture → image_url_hd`, `article`, цена, категория, params, описание (пустое не затирает).
API (`catalog_api_sync.py`, по понедельникам) — только `charge → charge_rub` (64 % in_stock, ≈5,9 % цены);
связь по `article` (id в API округлён). Вычисляем: размеры (`dim_resolver.py`, оси по магазину×роли),
роль (`category_map.py`: лист дерева + `OVERRIDES` + `MIXED`), `in_stock` (`stock_truth.reconcile()`,
единственный писатель).

**Дельта (HASH_VERSION=4, `load3.py`):** commercial/text/geometry/image/image_hd/attrs → `enrichment_status=stale`
(payload остаётся), смена контракта → baseline. Исчез → `missing` (in_stock=false в тот же день), 3 дня →
`archived`; не удаляем. Порог «< 70 %» — по магазину против последнего успеха (`catalog_import_runs`),
одна транзакция. Карантин фидов — `feed_guard.py` (fresh ≤30 ч, `yml_date` по МСК).

**Наличие и размеры честно** — отдельная сводка [[stock-and-dims]] (03.09).

**Тесты:** `--selftest` (`load3`, `dim_resolver`, `category_map`, `feed_guard`, `reflink`, `stock_truth`,
`page_alive`, `stock_check`, `footprint`, `salad/ingest_registry`, `mesh_priority` + сверка копий `asset_strategy`) — CI `scout-selftest`. **Дыры:** 155 товаров divan.ru не в экспорте (кабинет);
пустая выгрузка `e2fccbea`; диванов без глубины 1 012/2 345.

**Tier 2:** `../domain/catalog-enrichment.md` · `../domain/integrations.md` · `completed_plans/catalog-load-hardening.md`.
