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

**Состав:** 25 670 товаров (очистка ADR-0070 + кашпо 636, А2), дев-БД `remlab-devdb`; pgvector
не ставим. Загрузка — `load3.py`, cron 09:40 `refresh_daily.sh` (vision-обогащение дельты +
автозабор `enrich_wait.sh` + судья `enrich_judge.py`; алерты `alert.sh`).

**Роль товара — из дерева категорий фида** (`feed_taxonomy.py` → `category_map.py` →
`products.cat_role`): 1 931 категория, берём 76. Регекс-view `lr_roles` — историческая, не источник.

**Обогащение (06.08):** весь active-пул **25 664/25 664** (`gpt-5.6-luna`, furniture-v1/p3/s5,
качество 0.86 — эвристика, не голден); стиль — признаки+ранги (ADR-0071); батчи — ADR-0073
(гейт+журнал); дельта text/geometry сбрасывает версию (А1); phash 99.7%. Мониторинг: судья
terra ежедневно, дрифт `enrich-drift.jsonl`, копилка `golden-candidates.jsonl` (замер:
роль 96.7%, стиль 100%). Легаси: `style-scores.json`, `embeddings.npz`.

**Дельта и жизненный цикл (К1, ADR-0068):** обогащение в отдельной таблице `product_enrichment`,
переживает исчезновение из фида; хеши и статусы `active/out_of_stock/missing/archived` в
`load3.py`; отпечаток картинки `phash.py`; обратный индекс `sets_incremental.py`; контракт
`delta_check.py`. Повторный прогон фида — 0 семантических изменений из 87 639.

**Выбор модели (К3):** голден 256 товаров (`golden_eval.py`) — `gpt-5.6-luna`: роль 92.6%,
функция 89.8%, ≈16 $ за пул пакетом. Отчёт — `/test/golden/golden.html`.

**Закрыто волнами А1/А2 (06.08):** автозабор батчей, дельта→переобогащение, алертинг
(TG-токен — за владельцем, пока маркер-файл), предохранитель фида, KIDS в daily, кашпо 636.

**Дыры каталога:** ковёр — 26 (в фидах их нет — источник за владельцем, ADR-0066); картин и
штор нет; индексов точечной пересборки нет (К4).

**Tier 2:** `../domain/catalog-enrichment.md` · `../domain/integrations.md` · `../core/furniture.md`.
