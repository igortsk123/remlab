---
tier: 1
topic: catalog
scope: Каталог товаров — состав, свежесть, обогащение, дельта
tier2: "../domain/catalog-enrichment.md"
updated: 2026-08-05
importance: high
source: manual
status: working
source_of_truth: canonical
last_verified: 2026-08-05
---

# Каталог — Tier 1 сводка

**Состав (2026-08-05):** 87 659 товаров, 7 магазинов, дев-БД `remlab-devdb` (`products` +
view `lr_roles`, pgvector НЕ установлен). В наличии 87 607; описание из фида у 26 987 (31%).
Релевантны гостиной — **26 114** (`lr_roles.role is not null`): это и есть пул обогащения,
а не весь каталог.

**Загрузка:** `tools/scout/load3.py` (ZIP-фиды → идемпотентный upsert, `last_seen`, сырые `params`),
cron 09:40 `refresh_daily.sh`. Исчезнувшие из фида → `in_stock=false` (ADR-0045).

**Обогащение сейчас:** роль — регексы по `category_path` в view `lr_roles`; стилевой вектор шести
стилей — `style-scores.json` (15 735 тов., `style_score.py`); визуальные эмбеддинги —
`embeddings.npz` (3 793, CLIP B/32, локально); подтип — `item_function.py` (ADR-0065).

**Дельта и жизненный цикл (К1, готово 2026-08-05, ADR-0068):** обогащение живёт в отдельной
таблице `product_enrichment` (`tools/scout/001-enrichment.sql`) и переживает исчезновение товара
из фида; `load3.py` считает хеши и ставит статусы `active/out_of_stock/missing/archived`,
`in_stock` — производное. Отпечаток картинки — `phash.py`, обратный индекс товар→комплекты —
`sets_incremental.py`, контракт — `delta_check.py`. Замер: повторный прогон фида — 0 семантических
изменений из 87 639. Детали и пороги — Tier 2.

**Чего нет:** каскада по стоимости и версий обогащения (К2), золотой выборки (К3), индексов
кандидатов и точечной пересборки (К4). План — [[MASTER-catalog-ai]]. Модели и цены (ADR-0067) —
в Tier 2; `gpt-4o-mini` под картинки НЕ брать.

**Дыры каталога:** ковров для гостиной практически нет (17 записей, почти все банные/придверные,
ADR-0066); ТВ-тумба не нужна, пока в комплектах нет телевизора; картины и шторы отсутствуют.

**Tier 2:** `../domain/catalog-enrichment.md` · `../domain/integrations.md` · `../core/furniture.md`.
