---
tier: 1
topic: catalog
scope: Каталог товаров — состав, свежесть, обогащение, дельта
tier2: "../domain/catalog-enrichment.md"
updated: 2026-08-06
importance: high
source: manual
status: working
source_of_truth: canonical
last_verified: 2026-08-06
---

# Каталог — Tier 1 сводка

**Состав:** 25 034 товара (после очистки ADR-0070), дев-БД `remlab-devdb`; pgvector не ставим.
Загрузка — `load3.py`, cron 09:40 `refresh_daily.sh`.

**Роль товара — из дерева категорий фида** (`feed_taxonomy.py` → `category_map.py` →
`products.cat_role`): 1 931 категория, берём 76. Регекс-view `lr_roles` — историческая, не источник.

**Обогащение сейчас (06.08):** весь active-пул **25 028/25 028** в `product_enrichment`
(`gpt-5.6-luna`, furniture-v1/p3/s5, качество 0.86 — системная эвристика, не голден); стиль —
признаки+ранги (ADR-0071). Батч-дисциплина ADR-0073: отправка блокируется при незабранном
пакете, забор архивирует id в `enrich-batch-log.txt`. Легаси: `style-scores.json`,
`embeddings.npz` (3 793, CLIP), `item_function.py`.

**Дельта и жизненный цикл (К1, ADR-0068):** обогащение в отдельной таблице `product_enrichment`,
переживает исчезновение из фида; хеши и статусы `active/out_of_stock/missing/archived` в
`load3.py`; отпечаток картинки `phash.py`; обратный индекс `sets_incremental.py`; контракт
`delta_check.py`. Повторный прогон фида — 0 семантических изменений из 87 639.

**Выбор модели (К3):** голден 256 товаров (`golden_eval.py`) — `gpt-5.6-luna`: роль 92.6%,
функция 89.8%, ≈16 $ за пул пакетом. Отчёт — `/test/golden/golden.html`.

**Чего нет (аудит 06.08 → [[MASTER-pipeline-hardening]], там детали):** дельта-хеши не
запускают переобогащение; крон не забирает батчи, алертинга нет; предохранителей фида нет
(всё — волна А1); индексов кандидатов нет (К4).

**Дыры каталога:** «кашпо» — 0 (садовый DENY бьёт раньше ALLOW, А2); ковёр — 26 (ADR-0066);
картин и штор нет; 77 active без картинки в кэше.

**Tier 2:** `../domain/catalog-enrichment.md` · `../domain/integrations.md` · `../core/furniture.md`.
