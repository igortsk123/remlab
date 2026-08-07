---
tier: 1
topic: catalog
scope: Каталог товаров — состав, свежесть, обогащение, дельта
tier2: "../domain/catalog-enrichment.md"
updated: 2026-08-08
importance: high
source: manual
status: working
source_of_truth: canonical
last_verified: 2026-08-08
---

# Каталог — Tier 1 сводка

**Состав:** ~32 000 товаров (ADR-0070; фиды divan.ru/mdm-complect 07.08), дев-БД
`remlab-devdb`; pgvector нет. Загрузка `load3.py`, cron 09:40 `refresh_daily.sh`
(feed_guard → load3 → phash → обогащение дельты → индексы/heal → health; алерты alert.sh).

**Роль товара — из дерева категорий фида** (`category_map.py` → `products.cat_role`);
+3 категории картин (ADR-0078). View `lr_roles` — историческая, не источник.

**Обогащение:** active-пул полностью (`gpt-5.6-luna`, furniture-v1/p3/s5); стиль —
признаки+ранги (ADR-0071); батчи ADR-0073; дельта text/geometry сбрасывает версию.
Мониторинг: судья terra ежедневно (`enrich-drift.jsonl`); phash 99.7%.

**Дельта и жизненный цикл (К1, ADR-0068):** `product_enrichment` переживает пропажу из фида;
статусы в `load3.py`; phash; обратный индекс; контракт `delta_check.py`.

**Размеры (ADR-0079, 08.08):** evidence-резолвер `tools/scout/dim_resolver.py` вместо
`>400→/10`; провенанс dims_source+dims_evidence; scrape/manual фид не затирает. Итог: 0 битых,
+4 610 с шириной (divan.ru 0→5 310), шторы разблокированы. Предохранители T0 — `feed_guard.py`,
терминальность батча по результату. Детали — Tier 2 и ADR-0079.

**Выбор модели (К3):** голден 256 — luna роль 92.6%/функция 89.8% — **model-agreement, не
точность** (эталон = terra). Человеческий эталон — `tools/scout/gold_human.py` (выборка 400,
/test/gold-human/annotate.html, α, калибровка 0.65; разметка — владелец). Merge text/vision
починен парными батчами #t/#v (T2).



**Дыры:** премиум-тир беден у половины ролей; лофт/неокл/джапанди дефицитны (снабжение —
владелец). Ковры/стулья закрыты 07.08; шторы 08.08. К4: --refresh еженедельно + heal.

**Tier 2:** `../domain/catalog-enrichment.md` · `../domain/integrations.md` · `../core/furniture.md`.
