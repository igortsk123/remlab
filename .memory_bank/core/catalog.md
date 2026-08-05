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

**Обогащение сейчас:** роль — регексы по `category_path` внутри view `lr_roles`; стилевой вектор
шести стилей — `style-scores.json` (15 735 товаров, `style_score.py`: правила → CLIP zero-shot →
`gpt-5-mini` батчами, только новинки); визуальные эмбеддинги — `embeddings.npz` (3 793, CLIP B/32
через fastembed, локально); функциональный подтип — `item_function.py` (ADR-0065).

**Дельта и жизненный цикл (К1, готово 2026-08-05, ADR-0068):** таблица `product_enrichment`
(`tools/scout/001-enrichment.sql`, применяется `db_migrate.py`) — обогащение отдельно от товара и
переживает исчезновение из фида. `load3.py` считает три хеша (`commercial/text/geometry` + URL
картинки) и ставит статусы `active/out_of_stock/missing/archived` (три пропуска подряд → архив);
`products.in_stock` остаётся производным. Перцептивный отпечаток — `phash.py` (dHash+pHash+цвет,
4 678 товаров): порог косинуса 0.985, иначе CLIP склеивал один диван в разной ткани. Обратный
индекс товар→комплекты — `sets_incremental.py` (915 товаров, 1 920 связей). Контракт проверяется
`delta_check.py`. Замер: повторный прогон фида даёт 0 семантических изменений из 87 639.

**Чего нет:** каскада по стоимости и версионирования обогащения (К2), золотой выборки (К3),
индексов кандидатов и точечной пересборки (К4). План — [[MASTER-catalog-ai]].

**Модели и цены** (сверять перед прогоном, ADR-0067): `gpt-5-nano` $0.05/$0.40 — дешёвый текст,
`gpt-5.6-luna` $0.20/$1.20 — текст и vision, Batch −50%. `gpt-4o-mini` под картинки НЕ брать.

**Дыры каталога:** ковров для гостиной практически нет (17 записей, почти все банные/придверные,
ADR-0066); ТВ-тумба не нужна, пока в комплектах нет телевизора; картины и шторы отсутствуют.

**Tier 2:** `../domain/catalog-enrichment.md` · `../domain/integrations.md` · `../core/furniture.md`.
